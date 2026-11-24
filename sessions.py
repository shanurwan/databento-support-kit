"""Exchange trading sessions and trade dates for Databento data.

Databento's ohlcv-1d bars and date-only `start`/`end` use UTC days. Exchanges don't:

* CME's trade date starts at 17:00 Chicago the evening before (22:00 or 23:00 UTC, by DST).
* Osaka's day session opens at 08:45 JST = 23:45 UTC the previous day, and its night
  session (17:00-06:00 JST) counts toward the NEXT business day.
* HKEX futures' after-hours session (17:00-03:00 HKT) is registered as the next
  business day's trades.

This module maps timestamps to exchange trade dates, gives the UTC window for one
trade date, and rebuilds daily bars by session.

    from sessions import session_bars, trade_window, session_table
    start, end = trade_window("XOSE", date(2026, 12, 1))    # pass to timeseries.get_range
    daily = session_bars(store.to_df(), "GLBX")             # from ohlcv-1m

Times and holidays come from the exchanges' own pages (SOURCES), checked 2026-11-24.
Session ends are padded by a few minutes so closing-auction prints are included.
Not modelled: product-specific hours (e.g. OSE JGB, TOCOM electricity), expiry-day
hours, and changes that are only proposed. Verify against the exchange before trading.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd

T, D = dt.time, dt.date


@dataclass(frozen=True)
class Session:
    name: str
    start: dt.time          # local time
    end: dt.time            # local time; end <= start means it runs past midnight
    # Which calendar day the session starts on, relative to the trade date it counts toward:
    #   "same"          starts on the trade date
    #   "prev_business" starts on the previous business day (Friday night -> Monday)
    #   "prev_calendar" starts the calendar day before (CME: Monday's session opens Sunday)
    starts: str = "same"
    trading: bool = True    # False for order-entry-only phases (pre-open) with no trades


@dataclass(frozen=True)
class Schedule:
    effective: dt.date
    sessions: tuple[Session, ...]
    half_day: tuple[Session, ...] = ()


@dataclass(frozen=True)
class Venue:
    code: str
    name: str
    tz: str
    schedules: tuple[Schedule, ...]          # sorted by effective date
    holidays: frozenset[dt.date] = frozenset()
    half_days: frozenset[dt.date] = frozenset()
    # If set, every timestamp from the first session's start to the last session's end
    # belongs to the trade date, including exchange-holiday sessions in between (OSE).
    contiguous: bool = False
    # Half-days have no evening session, so the next trade date has no night/T+1 session (HKFE).
    no_night_after_half_day: bool = False
    note: str = ""
    sources: tuple[str, ...] = ()

    def is_business_day(self, d: dt.date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def next_business_day(self, d: dt.date) -> dt.date:
        d += dt.timedelta(days=1)
        while not self.is_business_day(d):
            d += dt.timedelta(days=1)
        return d

    def prev_business_day(self, d: dt.date) -> dt.date:
        d -= dt.timedelta(days=1)
        while not self.is_business_day(d):
            d -= dt.timedelta(days=1)
        return d

    def schedule_for(self, d: dt.date) -> Schedule:
        found = [s for s in self.schedules if s.effective <= d]
        if not found:
            raise ValueError(f"no {self.code} schedule before {self.schedules[0].effective}")
        return found[-1]


def _spans(v: Venue, trade_date: dt.date) -> list[tuple[Session, dt.datetime, dt.datetime]]:
    """UTC [start, end) of each session that belongs to trade_date."""
    tz = ZoneInfo(v.tz)
    sched = v.schedule_for(trade_date)
    sessions = sched.half_day if trade_date in v.half_days and sched.half_day else sched.sessions
    out = []
    for s in sessions:
        if s.starts == "prev_business" and v.no_night_after_half_day and v.prev_business_day(trade_date) in v.half_days:
            continue
        day = {"same": trade_date,
               "prev_business": v.prev_business_day(trade_date),
               "prev_calendar": trade_date - dt.timedelta(days=1)}[s.starts]
        if day != trade_date:  # a schedule change applies from the day the session starts
            s = next((x for x in v.schedule_for(day).sessions if x.name == s.name), s)
        start = dt.datetime.combine(day, s.start, tz)
        end = dt.datetime.combine(day + dt.timedelta(days=1) if s.end <= s.start else day, s.end, tz)
        out.append((s, start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)))
    return out


def trade_window(code: str, trade_date: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """UTC [start, end) covering every session of one trade date, pre-open included."""
    v = VENUES[code]
    if not v.is_business_day(trade_date):
        raise ValueError(f"{trade_date} is not a {code} business day")
    spans = _spans(v, trade_date)
    return pd.Timestamp(min(s for _, s, _ in spans)), pd.Timestamp(max(e for _, _, e in spans))


def session_table(code: str, trade_date: dt.date) -> pd.DataFrame:
    v = VENUES[code]
    tz = ZoneInfo(v.tz)
    return pd.DataFrame([{
        "session": s.name + ("" if s.trading else " (orders only)"),
        "local": f"{a.astimezone(tz):%a %d %b %H:%M} - {b.astimezone(tz):%H:%M}",
        "UTC": f"{a:%a %d %b %H:%M} - {b:%H:%M}",
    } for s, a, b in _spans(v, trade_date)])


def assign_trade_date(ts: pd.Series, code: str) -> pd.Series:
    """Exchange trade date for each UTC timestamp; NaT outside every trading session."""
    v = VENUES[code]
    ts = pd.to_datetime(ts, utc=True)
    out = pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    d, hi = (ts.min() - pd.Timedelta(days=5)).date(), (ts.max() + pd.Timedelta(days=5)).date()
    while d <= hi:
        if v.is_business_day(d):
            spans = _spans(v, d)
            if v.contiguous:
                tr = [(a, b) for x, a, b in spans if x.trading]
                spans = [(Session("trading day", T(0), T(0)), min(a for a, _ in tr), max(b for _, b in tr))]
            for s, a, b in spans:
                if s.trading:
                    out[(ts >= a) & (ts < b)] = pd.Timestamp(d)
        d += dt.timedelta(days=1)
    return out


def session_bars(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """Daily OHLCV by exchange trade date from Databento ohlcv-1m/1s/1h (a to_df() DataFrame)."""
    x = df.reset_index()
    ts_col = "ts_event" if "ts_event" in x.columns else x.columns[0]
    x["trade_date"] = assign_trade_date(x[ts_col], code)
    x = x.dropna(subset=["trade_date"]).sort_values(ts_col)
    keys = ["trade_date"] + (["symbol"] if "symbol" in x.columns else [])
    g = x.groupby(keys)
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum(), "bars": g.size()})


def utc_day_contents(code: str, utc_day: dt.date) -> pd.DataFrame:
    """Which sessions (and trade dates) end up inside one UTC-day ohlcv-1d bar."""
    v = VENUES[code]
    a = pd.Timestamp(utc_day, tz="UTC")
    b = a + pd.Timedelta(days=1)
    rows = []
    d = utc_day - dt.timedelta(days=3)
    while d <= utc_day + dt.timedelta(days=3):
        if v.is_business_day(d):
            for s, sa, sb in _spans(v, d):
                lo, hi = max(a, pd.Timestamp(sa)), min(b, pd.Timestamp(sb))
                if s.trading and lo < hi:
                    rows.append({"trade_date": str(d), "session": s.name,
                                 "minutes_in_utc_day": int((hi - lo).total_seconds() // 60),
                                 "of_session_minutes": int((pd.Timestamp(sb) - pd.Timestamp(sa)).total_seconds() // 60)})
        d += dt.timedelta(days=1)
    return pd.DataFrame(rows)


def _dates(*items: str) -> frozenset[dt.date]:
    return frozenset(D.fromisoformat(s) for s in items)


JPX_HOLIDAYS = _dates(  # https://www.jpx.co.jp/english/corporate/about-jpx/calendar/index.html
    "2026-01-01", "2026-01-02", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20", "2026-04-29",
    "2026-05-04", "2026-05-05", "2026-05-06", "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22",
    "2026-09-23", "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31",
    "2027-01-01", "2027-01-11", "2027-02-11", "2027-02-23", "2027-03-22", "2027-04-29", "2027-05-03",
    "2027-05-04", "2027-05-05", "2027-07-19", "2027-08-11", "2027-09-20", "2027-09-23", "2027-10-11",
    "2027-11-03", "2027-11-23", "2027-12-31")
HKEX_HOLIDAYS = _dates(  # https://www.hkex.com.hk/Services/Trading/Derivatives/Overview/Trading-Calendar-and-Holiday-Schedule
    "2026-01-01", "2026-02-17", "2026-02-18", "2026-02-19", "2026-04-03", "2026-04-06", "2026-04-07",
    "2026-05-01", "2026-05-25", "2026-06-19", "2026-07-01", "2026-10-01", "2026-10-19", "2026-12-25",
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-26", "2027-03-29", "2027-04-05", "2027-05-13",
    "2027-06-09", "2027-07-01", "2027-09-16", "2027-10-01", "2027-10-08", "2027-12-27")
HKEX_HALF_DAYS = _dates("2026-02-16", "2026-12-24", "2026-12-31", "2027-02-05", "2027-12-24", "2027-12-31")

VENUES: dict[str, Venue] = {}


def register(v: Venue) -> None:
    VENUES[v.code] = v


register(Venue(
    "GLBX", "CME Globex (equity index futures)", "America/Chicago",
    (Schedule(D(2000, 1, 1), (Session("globex", T(17, 0), T(16, 0), "prev_calendar"),)),),
    note="Daily halt 16:00-17:00 CT. Holiday early closes are not modelled.",
    sources=("https://www.cmegroup.com/trading-hours.html",)))

register(Venue(
    "XTKS", "Tokyo Stock Exchange (cash equities)", "Asia/Tokyo",
    (Schedule(D(2000, 1, 1), (
        Session("pre-open", T(8, 0), T(9, 0), trading=False),
        Session("morning", T(9, 0), T(11, 30)),
        Session("afternoon", T(12, 30), T(15, 5)))),
     Schedule(D(2024, 11, 5), (
        Session("pre-open", T(8, 0), T(9, 0), trading=False),
        Session("morning", T(9, 0), T(11, 30)),
        Session("afternoon + closing auction 15:25-15:30", T(12, 30), T(15, 35))))),
    holidays=JPX_HOLIDAYS,
    note="Close moved 15:00 -> 15:30 on 2024-11-05. Random close (15:29:30-15:30) planned from 2027-10-12. "
         "ToSTNeT off-auction trades (08:20-18:00) are not modelled.",
    sources=("https://www.jpx.co.jp/english/equities/trading/domestic/01.html",
             "https://www.jpx.co.jp/english/equities/trading/domestic/tvdivq0000006blj-att/tradinghours_eg.pdf")))

_ose_old = (Session("night", T(16, 30), T(6, 5), "prev_business"),   # pre-open phases not modelled
            Session("day", T(8, 45), T(15, 20)))
_ose_new = (Session("night pre-open", T(16, 45), T(17, 0), "prev_business", trading=False),
            Session("night", T(17, 0), T(6, 5), "prev_business"),
            Session("day pre-open", T(8, 0), T(8, 45), trading=False),
            Session("day", T(8, 45), T(15, 50)))
for code, name in (("XOSE", "Osaka Exchange (index futures and options)"),
                   ("XTKT", "Tokyo Commodity Exchange (energy futures)")):
    register(Venue(
        code, name, "Asia/Tokyo",
        (Schedule(D(2021, 9, 21), _ose_old), Schedule(D(2024, 11, 5), _ose_new)),
        holidays=JPX_HOLIDAYS, contiguous=True,
        note="Trading day = night session from the previous business day + the day session. Holiday-trading "
             "sessions (since 2022-09-23) count toward the next business day; none on 31 Dec or 2 Jan. "
             "JGB futures, TOCOM electricity, Nikkei VI and rubber have other hours."
             " Before 2024-11-05: day close 15:15, night 16:30-06:00 (J-GATE 3.0, 2021-09-21).",
        sources=("https://www.jpx.co.jp/english/derivatives/rules/trading-hours/index.html",
                 "https://www.jpx.co.jp/english/derivatives/rules/trading-hours/01.html",
                 "https://www.jpx.co.jp/english/derivatives/rules/holidaytrading/index.html")))

register(Venue(
    "XHKG", "HKEX Securities Market (OMD-C)", "Asia/Hong_Kong",
    (Schedule(D(2000, 1, 1),
              (Session("pre-opening (POS)", T(9, 0), T(9, 30)),
               Session("morning", T(9, 30), T(12, 0)),
               Session("afternoon", T(13, 0), T(16, 0)),
               Session("closing auction (CAS)", T(16, 0), T(16, 10))),
              half_day=(Session("pre-opening (POS)", T(9, 0), T(9, 30)),
                        Session("morning", T(9, 30), T(12, 0)),
                        Session("closing auction (CAS)", T(12, 0), T(12, 10)))),),
    holidays=HKEX_HOLIDAYS, half_days=HKEX_HALF_DAYS,
    note="POS auction matches at a random time 09:20-09:22; CAS closes at random 16:08-16:10. "
         "Trading continues under severe weather since 2024-09-23. Holidays taken from the derivatives calendar.",
    sources=("https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market?sc_lang=en",)))

_hkfe_day = (Session("morning pre-open", T(8, 45), T(9, 15)),
             Session("morning", T(9, 15), T(12, 0)),
             Session("afternoon pre-open", T(12, 30), T(13, 0)),
             Session("afternoon", T(13, 0), T(16, 35)))
register(Venue(
    "XHKF", "HKEX Futures (index futures, OMD-D)", "Asia/Hong_Kong",
    (Schedule(D(2000, 1, 1), (Session("after-hours (T+1)", T(17, 15), T(3, 5), "prev_business"),) + _hkfe_day,
              half_day=(Session("after-hours (T+1)", T(17, 15), T(3, 5), "prev_business"),
                        Session("morning pre-open", T(8, 45), T(9, 15)), Session("morning", T(9, 15), T(12, 35)))),
     Schedule(D(2026, 7, 20), (Session("after-hours (T+1)", T(17, 0), T(3, 5), "prev_business"),) + _hkfe_day,
              half_day=(Session("after-hours (T+1)", T(17, 0), T(3, 5), "prev_business"),
                        Session("morning pre-open", T(8, 45), T(9, 15)), Session("morning", T(9, 15), T(12, 35))))),
    holidays=HKEX_HOLIDAYS, half_days=HKEX_HALF_DAYS, no_night_after_half_day=True,
    note="After-hours trades are registered as the next business day's. AHT opened 17:15 before 2026-07-20. "
         "Earlier schedule changes (before the 17:15 AHT) are not modelled. A 04:15 AHT close is proposed for March 2027 (not modelled). Expiring month trades 13:00-16:00 only "
         "on its last day, with no AHT. Holiday-trading contracts are not modelled.",
    sources=("https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Derivatives-Market?sc_lang=en",
             "https://www.hkex.com.hk/Global/Exchange/FAQ/Derivatives-Market/Trading/After-Hours-Trading-(AHT)?sc_lang=en",
             "https://www.hkex.com.hk/Services/Trading/Derivatives/Overview/Trading-Mechanism/After-Hours-Trading?sc_lang=en")))
