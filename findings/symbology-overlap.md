# `to_df()` returns NaN symbols when two requested symbols share an instrument

**Affects:** `databento` (Python) 0.68.1 through 0.90.0. 0.68.0 is correct.

## What a customer sees

Comparing roll rules is a common first request for futures users:

```python
store = client.timeseries.get_range(
    dataset="GLBX.MDP3", schema="ohlcv-1d", stype_in="continuous",
    symbols=["ES.c.0", "ES.v.0"], start="2026-09-14", end="2026-09-24",
)
store.to_df()[["instrument_id", "symbol"]]
```

| ts_event | instrument_id | 0.68.0 | 0.68.1 to 0.90.0 |
|---|---|---|---|
| 2026-09-16 | 42140870 | ES.c.0 | **NaN** |
| 2026-09-17 | 42140870 | ES.c.0 | **NaN** |
| 2026-09-18 | 42140870 | ES.c.0 | **NaN** |

Both versions read the same saved `.dbn.zst` file, so the server response is identical.

## Why

The DBN metadata is correct:

```
ES.v.0: 2026-09-14..2026-09-16 -> 42140870, 2026-09-16..2026-09-24 -> 10252
ES.c.0: 2026-09-14..2026-09-20 -> 42140870, 2026-09-20..2026-09-24 -> 10252
```

`InstrumentMap` sorts each instrument's intervals by start date. `resolve()` and `resolve_many()` then pick the last interval that starts on or before the date, and give up if that interval has ended. For 42140870 both intervals start on 09-14. If `ES.v.0` sorts last, then for 09-16 to 09-18 the chosen interval has ended, and the `ES.c.0` interval that still covers those dates is never checked.

Which symbol sorts last depends on insertion order, so the same data can label correctly or as NaN. A nested overlap (A covers 09-10..09-20, B covers 09-14..09-16) fails for every date in A after B ends, whatever the order.

## Offline repro

[`repro_overlap.py`](../repro_overlap.py), no API key needed:

```
v.0 then c.0   resolve_many -> ['ES.c.0', 'ES.c.0', 'ES.c.0', 'ES.c.0', 'ES.c.0']
c.0 then v.0   resolve_many -> ['ES.v.0', 'ES.v.0', None, None, None]
nested A⊃B     resolve(9/17) -> None (A covers 9/17)
```

## Fix

When the latest-starting interval has ended, walk back to an earlier interval that still covers the date. The common, non-overlapping case keeps the vectorised path unchanged. The patch is 14 lines in `databento/common/symbology.py`, plus a parametrised regression test (same start in both orders, and nested):

- The new test fails on `main` (2 of 3 cases) and passes with the patch.
- The full suite passes with the patch: 5,984 passed, 959 skipped.
- On the real file, `to_df()` then labels every row as 0.68.0 did.

## Workarounds until it ships

- Request each continuous or parent symbol in a separate call.
- Or key on `instrument_id` and join the `symbology.resolve()` result yourself.
- `dbdoctor.py` warns when a request's mappings overlap.
