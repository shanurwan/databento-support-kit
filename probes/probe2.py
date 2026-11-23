"""Round 2: tiny paid pulls, each behind a get_cost guard. Records behaviours customers ask about."""
import json, os
import databento as db
import pandas as pd

MAX = 0.50
c = db.Historical(os.environ["DATABENTO_API_KEY"])
spent = 0.0
out = {}

def pull(name, **kw):
    global spent
    cost = c.metadata.get_cost(**kw)
    if cost > MAX:
        raise SystemExit(f"{name}: cost {cost} > {MAX}, refusing")
    spent += cost
    store = c.timeseries.get_range(**kw)
    store.to_file(f"out/{name}.dbn.zst")
    print(f"{name}: cost ${cost:.4f}")
    return store, cost

# 1. Timestamps/timezones: what does start="2026-11-17" mean, ts_event vs ts_recv
s, cost = pull("aapl_trades", dataset="XNAS.ITCH", symbols="AAPL", schema="trades", start="2026-11-17", end="2026-11-18")
df = s.to_df()
out["aapl_trades"] = {
    "cost": cost, "rows": len(df), "index_name": df.index.name, "index_tz": str(df.index.tz),
    "first_ts_recv": str(df.index[0]), "first_ts_event": str(df["ts_event"].iloc[0]),
    "first_ts_et": str(df.index[0].tz_convert("America/New_York")),
    "rows_before_0930_et": int((df.index.tz_convert("America/New_York").time < pd.Timestamp("09:30").time()).sum()),
    "recv_minus_event_ns_median": int((df.index - df["ts_event"]).median().value),
    "recv_minus_event_ns_p99": int((df.index - df["ts_event"]).quantile(0.99).value) if hasattr((df.index - df["ts_event"]), "quantile") else None,
    "price_dtype": str(df["price"].dtype), "columns": list(df.columns),
}
raw = s.to_df(price_type="fixed", pretty_ts=False)
out["aapl_trades"]["fixed_price_example"] = int(raw["price"].iloc[0])
out["aapl_trades"]["float_price_example"] = float(df["price"].iloc[0])

# 2. OHLCV gaps: bars only exist when there is a trade
s, cost = pull("ohlcv_illiquid", dataset="XNAS.ITCH", symbols=["AAPL", "WVVI"], schema="ohlcv-1m", start="2026-11-17T14:30", end="2026-11-17T21:00")
df = s.to_df()
out["ohlcv_gaps"] = {"cost": cost, "bars_per_symbol": df.groupby("symbol").size().to_dict(), "expected_minutes": 390}

# 3. Continuous futures across the Sept roll: not back-adjusted, roll date differs by rule
s, cost = pull("es_cont", dataset="GLBX.MDP3", symbols=["ES.c.0", "ES.v.0"], stype_in="continuous", schema="ohlcv-1d", start="2026-09-14", end="2026-09-24")
df = s.to_df()
out["es_cont"] = {"cost": cost, "rows": df.reset_index()[["ts_event", "symbol", "instrument_id", "close"]].astype(str).values.tolist()}

# 4. Definition: what instrument_id / raw_symbol / tick size look like
s, cost = pull("es_def", dataset="GLBX.MDP3", symbols="ESZ6", schema="definition", start="2026-11-17", end="2026-11-18")
df = s.to_df()
cols = [x for x in ["raw_symbol", "instrument_id", "min_price_increment", "display_factor", "expiration", "currency", "exchange", "instrument_class"] if x in df.columns]
out["es_def"] = {"cost": cost, "rows": len(df), "first": df[cols].iloc[0].astype(str).to_dict()}

# 5. Equity instrument_id stability across days
r = c.symbology.resolve(dataset="XNAS.ITCH", symbols=["AAPL", "NVDA"], stype_in="raw_symbol", stype_out="instrument_id", start_date="2026-10-01", end_date="2026-11-20")
out["iid_stability"] = {k: sorted({m["s"] for m in v}) for k, v in r["result"].items()}

out["total_spent"] = spent
json.dump(out, open("out/probe2.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str)[:6000])
