# Databento first-line support playbook

Eighteen tickets a frontline engineer is likely to see in the first weeks, each reproduced against the real Databento API on 2026-11-23. I used `databento` 0.90.0 and `databento-dbn` 0.73.0 on Python 3.12, from Kuala Lumpur, on a new account with only historical access.

Every "Evidence" block is the response the API actually returned. Response summaries are in [`evidence/`](evidence/); the market data itself is not redistributed. The paid pulls behind them cost $0.04 in total. Each ticket ends with a reply I would send and whether it needs escalating.

`python dbdoctor.py ...` runs most of these checks in one go. It uses only free endpoints and never prints the key.

| # | Area | Ticket |
|---|------|--------|
| 1 | Auth | [Key works in the portal, 400 in my script](#1-key-works-in-the-portal-400-in-my-script) |
| 2 | Auth | [401 Authentication failed](#2-401-authentication-failed) |
| 3 | Auth | [I pasted my error into Slack and it contained my key](#3-i-pasted-my-error-into-slack-and-it-contained-my-key) |
| 4 | Live | [Historical works, live does not](#4-historical-works-live-does-not) |
| 5 | Live | [Can't connect to the live gateway](#5-cant-connect-to-the-live-gateway) |
| 6 | Live | [Live feels slow from Asia](#6-live-feels-slow-from-asia) |
| 7 | Dates | [422 data_end_after_available_end](#7-422-data_end_after_available_end) |
| 8 | Dates | [Today's data: get_cost says $0, get_range says 403](#8-todays-data-get_cost-says-0-get_range-says-403) |
| 9 | Dates | [Other 422s: start before the dataset, start after end](#9-other-422s-start-before-the-dataset-start-after-end) |
| 10 | Dates | [Why are there trades before the open?](#10-why-are-there-trades-before-the-open) |
| 11 | Symbology | [None of the symbols could be resolved (futures)](#11-none-of-the-symbols-could-be-resolved-futures) |
| 12 | Symbology | [BRK/B is missing from my data](#12-brkb-is-missing-from-my-data) |
| 13 | Symbology | [My continuous series jumps, or rolls on a different day](#13-my-continuous-series-jumps-or-rolls-on-a-different-day) |
| 14 | Symbology | [symbol column is NaN for some rows](#14-symbol-column-is-nan-for-some-rows) |
| 15 | Data | [Missing one-minute bars](#15-missing-one-minute-bars) |
| 16 | Data | [Prices look 1,000,000,000x too big](#16-prices-look-1000000000x-too-big) |
| 17 | Billing | [How much will this cost? / surprise bill](#17-how-much-will-this-cost--surprise-bill) |
| 18 | Platform | [504 The remote gateway timed out](#18-504-the-remote-gateway-timed-out) |

---

## 1. Key works in the portal, 400 in my script

**Evidence.** The same valid key, with different wrapping:

| Key as sent | Response |
|---|---|
| `key + "\n"` (from `open(f).read()`) | `400 auth_invalid_username_in_basic_auth` |
| `key + " "` | `400 auth_invalid_username_in_basic_auth` |
| `key + "\r\n"` (file saved on Windows) | `400 auth_invalid_username_in_basic_auth` |
| `'"' + key + '"'` (quotes copied from a .env) | `400 auth_invalid_username_in_basic_auth` |
| key without `db-` | `401 auth_authentication_failed` |

**Cause.** The client sends the key as given. The server rejects anything that isn't exactly the 32-character `db-...` value.

**Reply.** "Your key is fine. The value reaching the API has an extra newline or quotes around it, which usually comes from reading it out of a file. Use `open(path).read().strip()`, or set `DATABENTO_API_KEY` without quotes. `dbdoctor.py` shows exactly which characters are extra without printing the key."

**Escalate?** No. Feedback for the client team: strip whitespace in `Historical(key)`. Every case above would then just work.

## 2. 401 Authentication failed

**Evidence.** `401 auth_authentication_failed | Authentication failed. | documentation: https://databento.com/docs/portal/api-keys`. On the live gateway the same mistake gives `success=0|error=Authentication failed.`

**Cause.** The key is wrong, revoked, or from another team, or the `db-` prefix is missing.

**Reply.** Ask for the key's last five characters (its bucket ID) or its fingerprint from `dbdoctor`, never the whole key. Compare it with **API keys** in the portal.

**Escalate?** Only if the portal shows the key as active and the fingerprint matches.

## 3. I pasted my error into Slack and it contained my key

**Evidence.** The 400 in ticket 1 echoes the full key in the message: `Invalid username in Basic auth ('db-…')`.

**Reply.** "Please rotate that key now in the portal (API keys → rotate). The error text includes the key, so delete the post too." Moderators should remove the message straight away.

**Escalate?** Yes, as a product/security note: the error body should not echo credentials. Report it privately, not in a public issue.

## 4. Historical works, live does not

**Evidence.** On the raw gateway handshake: `success=0|error=A live data license is required to access GLBX.MDP3.` In Python, `Live.subscribe(...)` raises `BentoError: A live data license is required to access GLBX.MDP3.` The same key reads GLBX.MDP3 history without issue.

**Cause.** Historical usage-based access does not include live. Live needs a licence per dataset.

**Reply.** Point them to **Plans and live data**. If they only need recent data, intraday historical also needs the live licence (ticket 8).

**Escalate?** To sales or accounts if they believe they already have the licence.

## 5. Can't connect to the live gateway

**Evidence.**
```
$ nc -vz glbx-mdp3.lsg.databento.com 13000
Connection to glbx-mdp3.lsg.databento.com (209.127.153.140) 13000 port [tcp/*] succeeded!
$ nc -vz glbx.mdp3.lsg.databento.com 13000
nc: getaddrinfo for host "glbx.mdp3.lsg.databento.com" port 13000: Name or service not known
$ timeout 3 nc glbx-mdp3.lsg.databento.com 13000
lsg_version=0.9.4
cram=<challenge>
```
[`evidence/live_handshake.txt`](evidence/live_handshake.txt) is a `tcpdump -A` capture of six handshakes (auth hashes and bucket IDs redacted). The key never crosses the wire, only SHA-256(challenge + key).

**Cause and checks, in order.**
1. Hostname: the dataset with dots changed to dashes (`glbx-mdp3`). Custom clients often get this wrong.
2. Outbound TCP 13000. If `nc -vz` hangs, a corporate firewall is dropping it.
3. Banner: if TCP connects but no `lsg_version=` line arrives, a TLS-intercepting proxy is in the path. The protocol is plain TCP.
4. Auth reply: `success=0|error=...` maps to tickets 1, 2 and 4. A CR in the key gives `Illegal characters in field auth`.

**Escalate?** Only when steps 1–3 pass from a clean network and it still fails.

## 6. Live feels slow from Asia

**Evidence.** From Kuala Lumpur, six handshakes: TCP connect 233–244 ms, auth reply 691–754 ms after connect start (three round trips).

**Reply.** That round trip is the distance to the US gateways, not a fault. Connect once and keep the session open, and use `ts_event` and `ts_recv` (exchange and Databento capture times) for latency analysis, not your local receive time. Users in APAC should expect this RTT on every reconnect.

**Escalate?** No, unless RTT jumps well above this baseline (`mtr` to the gateway).

## 7. 422 data_end_after_available_end

**Evidence.** `422 data_end_after_available_end | The dataset XNAS.ITCH has data available up to '2026-11-23 10:30:00+00:00'. The end in the query ('2026-12-30 ...') is after the available range.`

**Note.** "Available up to" here tracked the clock (10:30 at 10:33 UTC). It was the same for GLBX.MDP3 and XNAS.ITCH. It is not where the data ends; see ticket 8.

**Reply.** `end` is exclusive and must not be in the future. For "everything up to now", leave `end` empty or use the `end` from `metadata.get_dataset_range`.

## 8. Today's data: get_cost says $0, get_range says 403

**Evidence.** At 10:45 UTC, `get_dataset_range(XNAS.ITCH).end` was `05:00:00Z`.

| Window (2026-11-23) | `get_cost` | `timeseries.get_range` |
|---|---|---|
| 00:00 to 05:00 | 0.0 | 200, header only |
| 00:00 to 09:00 | 0.0 | **403 license_not_found_unauthorized**: "A live data license is required to access XNAS.ITCH data after 2026-11-23T05:00:00Z." |

`symbology.resolve` returns the same 403.

**Cause.** Without a live licence, historical data stops at the `get_dataset_range` edge. Data after it is intraday and needs the live licence. `get_cost` does not apply that check, so a cost preflight passes and the real request fails.

**Reply.** Explain the edge, and give them the `end` from `get_dataset_range` as the safe boundary.

**Escalate?** As a product note: `get_cost` should return the same 403, or flag the licensed part of the window.

## 9. Other 422s: start before the dataset, start after end

**Evidence.**
- `422 data_start_before_available_start | start in query ('2000-01-03 ...') was before the available start of dataset XNAS.ITCH ('2018-05-01 ...')`
- `422 data_time_range_start_on_or_after_end | start 2026-11-18 cannot be on or after end 2026-11-17`
- A typo'd dataset gives `400 validation_failed | Invalid dataset, was 'GLBX.MDP'. Use any of [...]`. Lowercase (`glbx.mdp3`) is accepted.

**Reply.** These messages are clear. Answer with the corrected parameters plus a link to the dataset's coverage page.

## 10. Why are there trades before the open?

**Evidence.** AAPL trades for `start="2026-11-17", end="2026-11-18"`:
- 151,408 records.
- The first is at `2026-11-17 00:00:39 UTC` = `2026-11-16 19:00:39` New York.
- 3,274 trades before 09:30 ET.
- The DataFrame index is `ts_recv`, not `ts_event`. The median gap between them was 169 µs (p99 184 µs).

**Cause.** Dates without a time are **UTC midnight**, and XNAS.ITCH includes extended hours.

**Reply.** Pass times with an offset (`2026-11-17T09:30-05:00`), or `df.index.tz_convert("America/New_York")` and filter. Use `ts_event` for exchange time. For CME, the trading day starts at 17:00 Chicago the evening before.

## 11. None of the symbols could be resolved (futures)

**Evidence.** `symbols="ES", dataset=GLBX.MDP3` → `422 symbology_invalid_request | None of the symbols could be resolved`. `symbology.resolve` lists it under `not_found`.

**Cause.** `ES` is a product root, not an instrument.

**Reply.** Pick one:

| Want | symbols | stype_in |
|---|---|---|
| One contract | `ESZ6` | `raw_symbol` |
| Front month, rolled | `ES.c.0` (calendar), `ES.v.0` (volume), `ES.n.0` (open interest) | `continuous` |
| Every ES contract and spread | `ES.FUT` | `parent` |

`ES.FUT` on 2026-11-17 resolved to outrights *and* calendar spreads (`ESZ6-ESM7`, `ESH8-ESM8`, ...). Warn them before they pull MBO for all of it.

## 12. BRK/B is missing from my data

**Evidence.** On XNAS.ITCH, `BRK.B` resolves to instrument 2306, while `BRK B`, `BRK/B` and `BRKB` are all `not_found`. In a request with other symbols they **disappear silently**: only an all-missing request gets the 422.

**Reply.** Use the dot form. Always check `not_found` from `symbology.resolve` before a large pull.

## 13. My continuous series jumps, or rolls on a different day

**Evidence.** ES ohlcv-1d, September 2026 roll:

| Date | ES.v.0 (volume) | ES.c.0 (calendar) |
|---|---|---|
| 09-15 | ESU6 7598.50 | ESU6 7598.50 |
| 09-16 | **ESZ6** 7657.25 | ESU6 7590.00 |
| 09-18 | ESZ6 7725.00 | ESU6 7643.25 |
| 09-20 | ESZ6 7734.50 | **ESZ6** 7734.50 |

**Cause.** The roll rules differ: volume rolled on 16 Sep, calendar on 20 Sep. The series is **not back-adjusted**, so the step at the roll (about 80 points here) is the ESU6/ESZ6 calendar spread, not bad data.

**Reply.** Choose the roll rule that matches the strategy. Back-adjust yourself using the `instrument_id` change as the roll marker.

## 14. symbol column is NaN for some rows

**Evidence.** `symbols=["ES.c.0","ES.v.0"], stype_in="continuous"`, then `to_df()`:

```
2026-09-16  instrument 42140870  symbol NaN     <- ES.c.0 maps here until 09-20
2026-09-17  instrument 42140870  symbol NaN
2026-09-18  instrument 42140870  symbol NaN
```

The mappings inside the DBN file are correct (`ES.c.0 → 42140870` for 09-14 to 09-20). On the same file, `databento` 0.68.0 labels these rows `ES.c.0`; 0.68.1 through 0.90.0 return NaN.

**Cause.** A client bug. Since the 0.68.1 vectorised mapping, `InstrumentMap.resolve()` and `resolve_many()` only check the *latest-starting* interval for an instrument. When two requested symbols share an instrument and that interval ends first (`ES.v.0` rolls on 09-16), the dates still covered by `ES.c.0` resolve to nothing. Write-up and offline repro: [`findings/symbology-overlap.md`](findings/symbology-overlap.md).

**Workaround.** Request each continuous symbol in its own call, or key on `instrument_id` and join the `symbology.resolve` output. `dbdoctor` warns when a request has overlapping mappings.

**Escalate?** Yes, to the client team, with the repro and a tested patch.

## 15. Missing one-minute bars

**Evidence.** ohlcv-1m, 14:30 to 21:00 UTC on 2026-11-17: AAPL has 390 bars, WVVI has **16**.

**Cause.** OHLCV bars are built from trades. A minute with no trade has no bar. This is not data loss.

**Reply.** Forward-fill the close if they need a regular grid (`df.resample("1min").last().ffill()`). If they want quotes in quiet minutes, `bbo-1m` / `cbbo-1m` is the schema to use.

## 16. Prices look 1,000,000,000x too big

**Evidence.** The same AAPL trade: `to_df()` gives `353.61`, `to_df(price_type="fixed")` gives `353610000000`. Raw DBN, the C++/Rust clients and CSV exports without `pretty_px` use fixed-point integers with 1e-9 units.

**Reply.** Divide by `1e9` (`databento.FIXED_PRICE_SCALE`), or use `price_type="float"` / `pretty_px=True`.

## 17. How much will this cost? / surprise bill

**Evidence.** All from `metadata.get_cost`, which is free:

| Request (GLBX.MDP3, 1 day) | Cost |
|---|---|
| ESZ6, mbo | $2.37 |
| ALL_SYMBOLS, mbo | **$2,232.88** (1.33 TB billable) |
| ALL_SYMBOLS, ohlcv-1m | $1.82 |
| ALL_SYMBOLS, ohlcv-1d | $0.37 |

A new account had usage-based access enabled with **no limit**, and a card on file.

**Reply.** Run `get_cost` (or `dbdoctor --budget`) before any large pull. Start with the coarsest schema that answers the question. Set a monthly limit under Billing → Usage-based access → Manage.

**Escalate?** Billing questions about a past charge go to accounts, along with the request parameters.

## 18. 504 The remote gateway timed out

**Evidence.** One `symbology.resolve` call (`ES`, raw_symbol) returned `504 The remote gateway timed out.` Five immediate retries returned 200 in 0.83–6.5 s.

**Reply.** It's transient. Retry with exponential backoff. If it keeps happening, send the UTC times and the request parameters (the API returns no request ID).

**Escalate?** If a customer sees it repeatedly within minutes, or on several endpoints. Check the status page first.
