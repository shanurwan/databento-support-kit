# Daily bars: UTC days vs exchange sessions, measured on CME

**Question customers ask:** "Your daily bar doesn't match CME / TradingView / my broker."

**Short answer:** Databento's `ohlcv-1d` covers a UTC day. Exchanges define a day by trading session. On ES futures over seven weeks, the two disagreed on the open on 34 of 35 trade dates.

## Method

- **Data:** ESZ6 (one contract, so no roll), GLBX.MDP3, 5 Oct to 20 Nov 2026. Schemas: `ohlcv-1m` (48,300 bars), `ohlcv-1d` and `statistics`. Cost: $0.18.
- **Three daily series compared:**
  1. Databento `ohlcv-1d`.
  2. Daily bars rebuilt from `ohlcv-1m` by CME session, 17:00 Chicago the evening before to 16:00 Chicago, using [`sessions.py`](../sessions.py).
  3. CME's official settlement price (`statistics`, `stat_type == 3`).
- **Script:** [`probes/session_study.py`](../probes/session_study.py). Per-day output: [`evidence/session_study_days.csv`](../evidence/session_study_days.csv).

## Results (35 trade dates)

| Check | Result |
|---|---|
| `ohlcv-1d` equals 1-minute bars grouped by UTC date | **42 / 42 days identical**: daily bars are UTC days |
| Open differs from the session open | **34 / 35 days**; median 26 ticks (6.50 pts), max 242 ticks (60.50 pts) |
| Close differs from the session close | 28 / 35 days; max 184 ticks |
| High or low differs | 16 / 35 days |
| Volume difference | median 0.5% of the session (the evening hours are quiet) |
| Settlement equals the session close | 2 / 35 days; median gap 24 ticks |
| Settlement equals the UTC-day close | median gap 40 ticks |

The open is almost always wrong because the UTC day begins at 19:00 Chicago (18:00 after 1 Nov), one to two hours into the next session, so it opens on the overnight price.

## Three things that trip people up

1. **Daylight saving moves the session in UTC.** The session opens at 22:00 UTC before 1 Nov 2026 and at 23:00 UTC after. A fixed UTC offset is wrong for half the year.
2. **Close and settlement are different numbers.** ES settles from trading around 15:00 Chicago, but the session runs to 16:00. For marking positions, use `statistics` settlement, not an OHLCV close.
3. **Read settlement `ts_ref` in UTC.** The record for trade date D has `ts_ref = D 00:00 UTC`. Converting it to Chicago time, as you would for anything else on CME, gives 19:00 on D-1, which shifts every settlement one day. Each settlement also arrives more than once: around 15:00 CT with `stat_flags = 2`, then around 18:00 CT with `stat_flags = 3`. Keep the latest record for each trade date.

## Why this matters more in Asia

Databento's coming JPX and HKEX datasets (publishers added to [`dbn`](https://github.com/databento/dbn) on 2026-08-03 and 2026-11-16) put session boundaries even closer to UTC midnight. See [`APAC.md`](../APAC.md) for the per-venue tables.

## What to tell the customer

- For exchange-style daily bars, rebuild them from `ohlcv-1m` by session: `sessions.session_bars(df, "GLBX")`.
- To request one trade date, use `sessions.trade_window("GLBX", date)` as `start` and `end`.
- For settlement, use the `statistics` schema and read `ts_ref` as a UTC date.
- Databento's [public roadmap](https://roadmap.databento.com) has a trading-calendar request. Until it ships, this is the workaround.
