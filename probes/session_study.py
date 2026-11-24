"""Session vs UTC daily bars on real CME data (ESZ6), against the official settlement.

Pulls ohlcv-1m, ohlcv-1d and statistics for one contract behind a get_cost guard,
rebuilds daily bars two ways from the 1-minute bars, and measures how they differ.
"""
import json, os, sys
import databento as db
import pandas as pd

MAX = 1.00
DS, SYM = "GLBX.MDP3", "ESZ6"
START, END = "2026-10-04", "2026-11-21"   # Sunday open of the first session .. Saturday
TZ = "America/Chicago"
c = db.Historical(os.environ["DATABENTO_API_KEY"])

def pull(schema):
    kw = dict(dataset=DS, symbols=SYM, schema=schema, start=START, end=END)
    cost = c.metadata.get_cost(**kw)
    if cost > MAX:
        sys.exit(f"{schema}: ${cost} over budget")
    path = f"out/sess_{schema}.dbn.zst"
    if not os.path.exists(path):
        c.timeseries.get_range(**kw).to_file(path)
    print(f"{schema}: ${cost:.4f}")
    return db.DBNStore.from_file(path).to_df(), cost

m1, c1 = pull("ohlcv-1m")
d1, c2 = pull("ohlcv-1d")
st, c3 = pull("statistics")

m1 = m1.reset_index().rename(columns={"ts_event": "ts"}) if "ts_event" in m1.reset_index().columns else m1.reset_index()
m1["ts"] = pd.to_datetime(m1["ts_event"] if "ts_event" in m1 else m1["ts"], utc=True)

def agg(g):
    g = g.sort_values("ts")
    return pd.Series({"open": g["open"].iloc[0], "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].iloc[-1], "volume": int(g["volume"].sum()), "bars": len(g)})

# 1) UTC-day bars rebuilt from 1m: must equal Databento's ohlcv-1d if ohlcv-1d is UTC-day based
m1["utc_day"] = m1["ts"].dt.tz_convert("UTC").dt.date
utc = m1.groupby("utc_day").apply(agg)

d1 = d1.reset_index()
d1["utc_day"] = pd.to_datetime(d1["ts_event"], utc=True).dt.date
d1 = d1.set_index("utc_day")[["open", "high", "low", "close", "volume"]]
common = utc.index.intersection(d1.index)
match_utc = ((utc.loc[common, ["open", "high", "low", "close"]].values == d1.loc[common, ["open", "high", "low", "close"]].values).all(axis=1)
             & (utc.loc[common, "volume"].values == d1.loc[common, "volume"].values))

# 2) CME session bars: session for trade date D runs 17:00 CT on D-1 .. 16:00 CT on D
local = m1["ts"].dt.tz_convert(TZ)
m1["trade_date"] = (local + pd.Timedelta(hours=7)).dt.date   # 17:00 CT -> next day's 00:00
sess = m1.groupby("trade_date").apply(agg)
sess = sess[[pd.Timestamp(d).weekday() < 5 for d in sess.index]]

# 3) Official settlement (stat_type 3 = SETTLEMENT_PRICE), keyed by the trade date the exchange reports
st = st.reset_index()
settle = st[st["stat_type"] == 3].copy()
settle["ts_ref"] = pd.to_datetime(settle["ts_ref"], utc=True)
settle["trade_date"] = settle["ts_ref"].dt.date   # ts_ref = trade date at 00:00 UTC; converting to CT shifts it a day
settle = settle.sort_values("ts_recv").groupby("trade_date")["price"].last()

rows = []
for d in sess.index:
    s = sess.loc[d]
    u = d1.loc[d] if d in d1.index else None
    rows.append({
        "trade_date": str(d),
        "session_open": s["open"], "session_close": s["close"], "session_high": s["high"], "session_low": s["low"],
        "session_volume": s["volume"],
        "utc_open": None if u is None else u["open"], "utc_close": None if u is None else u["close"],
        "utc_high": None if u is None else u["high"], "utc_low": None if u is None else u["low"],
        "utc_volume": None if u is None else int(u["volume"]),
        "settlement": settle.get(d),
    })
df = pd.DataFrame(rows).dropna(subset=["utc_open"])
tick = 0.25
df["open_diff_ticks"] = ((df["utc_open"] - df["session_open"]).abs() / tick).round()
df["close_diff_ticks"] = ((df["utc_close"] - df["session_close"]).abs() / tick).round()
df["hl_differs"] = (df["utc_high"] != df["session_high"]) | (df["utc_low"] != df["session_low"])
df["vol_share_moved"] = (df["utc_volume"] - df["session_volume"]).abs() / df["session_volume"]
df["settle_vs_session_close_ticks"] = ((df["settlement"] - df["session_close"]).abs() / tick).round()
df["settle_vs_utc_close_ticks"] = ((df["settlement"] - df["utc_close"]).abs() / tick).round()

summary = {
    "cost_usd": round(c1 + c2 + c3, 4),
    "minutes": len(m1),
    "ohlcv_1d_equals_utc_day_rebuild": f"{int(match_utc.sum())}/{len(common)}",
    "trade_days": len(df),
    "days_open_differs": int((df["open_diff_ticks"] > 0).sum()),
    "days_close_differs": int((df["close_diff_ticks"] > 0).sum()),
    "days_high_or_low_differs": int(df["hl_differs"].sum()),
    "median_open_diff_ticks": float(df["open_diff_ticks"].median()),
    "max_open_diff_ticks": float(df["open_diff_ticks"].max()),
    "max_close_diff_ticks": float(df["close_diff_ticks"].max()),
    "median_volume_mismatch_pct": round(float(df["vol_share_moved"].median()) * 100, 1),
    "settlement_days": int(df["settlement"].notna().sum()),
    "settle_eq_session_close_days": int((df["settle_vs_session_close_ticks"] == 0).sum()),
    "median_settle_vs_utc_close_ticks": float(df["settle_vs_utc_close_ticks"].median()),
    "median_settle_vs_session_close_ticks": float(df["settle_vs_session_close_ticks"].median()),
}
# DST: the session boundary in UTC before/after 1 Nov 2026
summary["session_start_utc_before_dst_end"] = str(pd.Timestamp("2026-10-29 17:00", tz=TZ).tz_convert("UTC"))
summary["session_start_utc_after_dst_end"] = str(pd.Timestamp("2026-11-05 17:00", tz=TZ).tz_convert("UTC"))

df.to_csv("out/session_study_days.csv", index=False)
json.dump(summary, open("out/session_study.json", "w"), indent=1, default=str)
print(json.dumps(summary, indent=1, default=str))
print(df[["trade_date", "session_open", "utc_open", "session_close", "utc_close", "settlement", "session_volume", "utc_volume"]].head(8).to_string())
