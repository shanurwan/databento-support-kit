"""Offline reproducer: overlapping mapping intervals for one instrument_id -> NaN symbols.
Mirrors the real mappings Databento returned for symbols=["ES.c.0","ES.v.0"], stype_in=continuous,
GLBX.MDP3 ohlcv-1d, 2026-09-14..2026-09-24 (instrument 42140870 = ESU6)."""
import datetime as dt
import numpy as np
from databento.common.symbology import InstrumentMap, MappingInterval

D = dt.date
v0 = MappingInterval(D(2026, 9, 14), D(2026, 9, 16), "ES.v.0")
c0 = MappingInterval(D(2026, 9, 14), D(2026, 9, 20), "ES.c.0")
days = np.array(["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"], dtype="datetime64[D]")
ids = np.full(days.shape, 42140870, dtype=np.uint64)

for name, order in [("v.0 then c.0", [v0, c0]), ("c.0 then v.0", [c0, v0])]:
    m = InstrumentMap()
    m._insert_intervals([42140870] * 2, order)
    print(f"{name:14s} resolve_many ->", list(m.resolve_many(ids, days)),
          "| resolve ->", [m.resolve(42140870, d.astype(object)) for d in days])

# Same defect without a tie: A covers 9/10-9/20, B starts later and ends earlier
m = InstrumentMap()
m._insert_intervals([1, 1], [MappingInterval(D(2026, 9, 10), D(2026, 9, 20), "A"), MappingInterval(D(2026, 9, 14), D(2026, 9, 16), "B")])
print("nested A⊃B     resolve(9/17) ->", m.resolve(1, D(2026, 9, 17)), "(A covers 9/17)")
