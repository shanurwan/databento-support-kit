# databento-support-kit

First-line support tooling for the [Databento](https://databento.com) API, built and tested against the real API.

- **[`PLAYBOOK.md`](PLAYBOOK.md)**: 18 common tickets (auth, live gateway, date ranges, symbology, data shape, billing). Each has the exact response the API returned, the cause, a reply to send, and when to escalate.
- **[`dbdoctor.py`](dbdoctor.py)**: runs those checks on one request and prints a paste-ready escalation summary. It uses only free endpoints (metadata, symbology, the live handshake), never downloads data, never starts a live session, and never prints the API key.
- **[`findings/symbology-overlap.md`](findings/symbology-overlap.md)**: a client bug found while building the playbook. `to_df()` labels rows NaN when two requested symbols share an instrument (0.68.1+), with an offline repro and a tested fix.

## dbdoctor

```bash
pip install databento
export DATABENTO_API_KEY=db-...
python dbdoctor.py --dataset GLBX.MDP3 --symbols ES.c.0,ES.v.0 --stype-in continuous \
    --schema ohlcv-1d --start 2026-09-14 --end 2026-09-24 --live
```

```
[PASS] api key: Well-formed key [sha256:a9208ff639]
[PASS] historical auth: Key accepted; 31 datasets visible.
[PASS] dataset: GLBX.MDP3/ohlcv-1d: 2010-06-06 .. last ingested 2026-11-23T00:00:00Z
[INFO] timezone: Dates without a time are UTC midnight: start=2026-09-14 means 2026-09-14T00:00:00+00:00 = 2026-09-13 19:00 New York (EST). For CME (GLBX.MDP3) the trading day starts at 17:00 Chicago the evening before.
[PASS] symbology: All 2 symbol(s) resolve.
[WARN] symbol overlap: ... instrument 42140870: ES.v.0 2026-09-14..2026-09-16 and ES.c.0 2026-09-14..2026-09-20 ...
       fix: Request each continuous/parent symbol separately if you need every label. ...
[PASS] cost: $0.0002 for 1,008.0 B billable (budget $1.00). Same request by schema: {'mbo': 12.7719, 'mbp-1': 11.4475, 'trades': 5.2468, 'ohlcv-1m': 0.0779, 'ohlcv-1d': 0.0002}
[FAIL] live gateway: glbx-mdp3.lsg.databento.com rejected auth: 'A live data license is required to access GLBX.MDP3.' (lsg_version=0.9.4, connect 244 ms, auth 738 ms)
       fix: Historical access does not include live. Add a live license for this dataset in the portal ...

### Escalation summary
- Time (UTC): 2026-11-23 10:48:04
- Client: python 3.12.16, databento 0.90.0, os Linux, databento-dbn 0.73.0
- Key fingerprint: sha256:a9208ff639 (not the key)
- Request: {"dataset": "GLBX.MDP3", "schema": "ohlcv-1d", ...}
- Findings: ...
```

| Check | Catches |
|---|---|
| api key | whitespace, CRLF, quotes, missing `db-` (the server only says `400 auth_invalid_username_in_basic_auth`) |
| historical auth | 400 / 401, with the key redacted from the server's error text |
| dataset, schema | typos (suggests the right code), schema not offered |
| time window | start before coverage, start ≥ end, end past the historical edge (403 without a live licence), UTC vs exchange time |
| symbology | `not_found` / `partial`, with fixes (`ES` → `ES.FUT` / `ES.c.0`, `BRK/B` → `BRK.B`) |
| symbol overlap | input symbols sharing an instrument (the NaN-symbol bug) |
| cost | `get_cost` against `--budget`, plus the same request priced per schema |
| live gateway (`--live`) | DNS, TCP 13000, gateway version, CRAM auth, licence; connect and auth times |

Exit code is 1 if any check fails, so it can run in CI or in a support macro. `--json` gives machine-readable output.

## Tests

```bash
pip install pytest && pytest -q test_dbdoctor.py
```

The offline tests use API responses captured on 2026-11-23.

## Docker

```bash
docker build -t dbkit .
docker run --rm -e DATABENTO_API_KEY dbkit python dbdoctor.py --dataset XNAS.ITCH --symbols AAPL --start 2026-11-17 --end 2026-11-18
```

The image also has `nc`, `tcpdump`, `dig`, `strace`, `jq` and `curl` for the network steps in the playbook.

Not affiliated with Databento. MIT licence.
