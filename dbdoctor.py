#!/usr/bin/env python3
"""dbdoctor: first-line diagnostics for Databento API requests.

Runs the checks a support engineer would run on a "my request doesn't work"
ticket, using only free endpoints (metadata, symbology, the live gateway
handshake). It never downloads data and never starts a live session.

    python dbdoctor.py --dataset GLBX.MDP3 --symbols ES.c.0,ES.v.0 \
        --stype-in continuous --schema ohlcv-1d --start 2026-09-14 --end 2026-09-24 --live

Ends with a paste-ready escalation block. The API key is never printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import socket
import sys
import time
from dataclasses import asdict, dataclass, field

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
KEY_RE = re.compile(r"^db-[A-Za-z0-9]{29}$")
LIVE_PORT = 13000


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------- pure helpers

def key_fingerprint(key: str) -> str:
    """Safe to share: lets support match two reports to one key without seeing it."""
    return "sha256:" + hashlib.sha256(key.strip().encode()).hexdigest()[:10]


def redact(text: str, key: str | None) -> str:
    text = re.sub(r"db-[A-Za-z0-9]{20,}", "db-<redacted>", text)
    if key:
        text = text.replace(key.strip(), "<redacted>")
    return text


def check_key_hygiene(raw: str | None) -> Check:
    if not raw:
        return Check("api key", FAIL, "No key found (DATABENTO_API_KEY unset and no --key-file).",
                     "Copy the key from https://databento.com/portal/keys into DATABENTO_API_KEY.")
    problems = []
    if raw != raw.strip():
        tail = repr(raw[len(raw.rstrip()):]) if raw != raw.rstrip() else ""
        head = repr(raw[: len(raw) - len(raw.lstrip())]) if raw != raw.lstrip() else ""
        problems.append(f"leading/trailing whitespace {head}{tail}".strip())
    k = raw.strip()
    if k[:1] in "\"'" or k[-1:] in "\"'":
        problems.append("wrapped in quotes")
        k = k.strip("\"'")
    if not k.startswith("db-"):
        problems.append("does not start with 'db-'")
    elif not KEY_RE.match(k):
        problems.append(f"unexpected length or characters (length {len(k)}, expected 32)")
    fp = key_fingerprint(k)
    if problems:
        return Check("api key", FAIL, "Key format problem: " + "; ".join(problems) + f" [{fp}]",
                     "The server answers these with 400 auth_invalid_username_in_basic_auth "
                     "(whitespace/quotes) or 401 auth_authentication_failed (bad prefix). "
                     "Strip the value when reading it from a file: open(path).read().strip().",
                     {"fingerprint": fp})
    return Check("api key", PASS, f"Well-formed key [{fp}]", data={"fingerprint": fp})


def parse_day(s: str) -> dt.datetime:
    ts = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


EQUITY_SUFFIXES = ("ITCH", "PILLAR", "PITCH", "BASIC", "MINI", "MEMOIR", "SUMMARY", "TRADES", "TOPS", "DOM", "NLS")


def check_window(start: str, end: str | None, avail_start: str, last_ingested: str, dataset: str = "") -> list[Check]:
    out = []
    s = parse_day(start)
    a0, a1 = parse_day(avail_start[:26]), parse_day(last_ingested[:26])
    e = parse_day(end) if end else None
    if e and s >= e:
        out.append(Check("time window", FAIL, f"start {s} is on or after end {e}.",
                         "Server error: 422 data_time_range_start_on_or_after_end. `end` is exclusive."))
    if s < a0:
        out.append(Check("time window", FAIL, f"start {s.date()} is before the dataset starts ({a0.date()}).",
                         f"Server error: 422 data_start_before_available_start. Use start >= {a0.date()}."))
    if e and e > a1:
        out.append(Check("time window", WARN,
                         f"end {e} is after the historical edge ({a1}). Without a live license, data after it "
                         "fails with 403 license_not_found_unauthorized (metadata.get_cost still quotes $0 for it); "
                         "past 'now' every key gets 422 data_end_after_available_end.",
                         f"Set end <= {a1.isoformat()} (metadata.get_dataset_range), or add a live license "
                         "for intraday historical data."))
    naive = "T" not in start and "+" not in start
    if naive:
        et = s.astimezone(dt.timezone(dt.timedelta(hours=-5)))
        out.append(Check("timezone", INFO,
                         f"Dates without a time are UTC midnight: start={start} means {s.isoformat()} "
                         f"= {et.strftime('%Y-%m-%d %H:%M')} New York (EST)."
                         + (" Pre-market records are included." if dataset.endswith(EQUITY_SUFFIXES) else
                            " For CME (GLBX.MDP3) the trading day starts at 17:00 Chicago the evening before."
                            if dataset == "GLBX.MDP3" else ""),
                         "Pass explicit times with an offset, e.g. 2026-11-17T09:30-05:00, or filter on the index after tz_convert."))
    if not out:
        out.append(Check("time window", PASS, f"{s} .. {e or 'open'} is inside {a0.date()} .. {a1}"))
    return out


def symbol_suggestions(sym: str, dataset: str, stype_in: str) -> list[str]:
    tips = []
    ds = dataset.upper()
    if ds == "GLBX.MDP3" and stype_in == "raw_symbol" and re.fullmatch(r"[A-Z0-9]{1,4}", sym):
        tips.append(f"'{sym}' is a product root, not a contract. Use parent '{sym}.FUT' (stype_in=parent), "
                    f"continuous '{sym}.c.0' (stype_in=continuous), or a contract like '{sym}Z6'.")
    if ds.endswith(("ITCH", "PILLAR", "PITCH", "BASIC", "MINI")) and re.search(r"[ /]|^[A-Z]{3,4}[AB]$", sym):
        base = re.sub(r"[ /]", ".", sym)
        tips.append(f"US share classes use a dot on these datasets: try '{base}'.")
    if sym != sym.strip():
        tips.append("symbol has surrounding whitespace")
    if stype_in == "continuous" and not re.fullmatch(r".+\.[cnv]\.\d+", sym):
        tips.append("continuous symbols look like ROOT.c.N (calendar), ROOT.v.N (volume) or ROOT.n.N (open interest).")
    return tips


def find_overlaps(result: dict[str, list[dict]]) -> list[dict]:
    """Input symbols that map to the same instrument on overlapping dates."""
    spans: dict[str, list[tuple[str, str, str]]] = {}
    for sym, entries in result.items():
        for m in entries:
            spans.setdefault(m["s"], []).append((m["d0"], m["d1"], sym))
    found = []
    for iid, items in spans.items():
        items.sort()
        for i, (a0, a1, sa) in enumerate(items):
            for b0, b1, sb in items[i + 1:]:
                if sa != sb and b0 < a1 and a0 < b1:
                    found.append({"instrument_id": iid, "a": [sa, a0, a1], "b": [sb, b0, b1],
                                  "unequal_ends": a1 != b1})
    return found


def overlap_check(overlaps: list[dict], client_version: str | None) -> Check:
    if not overlaps:
        return Check("symbol overlap", PASS, "No two input symbols share an instrument on the same dates.")
    lines = [f"instrument {o['instrument_id']}: {o['a'][0]} {o['a'][1]}..{o['a'][2]} and "
             f"{o['b'][0]} {o['b'][1]}..{o['b'][2]}" for o in overlaps]
    affected = client_version and _ver(client_version) >= (0, 68, 1)
    detail = ("Each record carries one instrument_id, so it can be labelled with only one of these symbols. "
              + "; ".join(lines))
    fix = "Request each continuous/parent symbol separately if you need every label."
    if affected and any(o["unequal_ends"] for o in overlaps):
        detail += (f". With databento-python {client_version} (>=0.68.1) to_df() can return symbol=NaN on dates "
                   "covered by only one of them (InstrumentMap only checks the latest-starting interval).")
        fix += " Or key on instrument_id and join symbology.resolve() output yourself."
    return Check("symbol overlap", WARN, detail, fix, {"overlaps": overlaps})


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def escalation_block(args: argparse.Namespace, checks: list[Check], versions: dict) -> str:
    bad = [c for c in checks if c.status in (FAIL, WARN)]
    req = {k: getattr(args, k) for k in ("dataset", "schema", "symbols", "stype_in", "start", "end")}
    lines = [
        "### Escalation summary",
        f"- Time (UTC): {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Client: {', '.join(f'{k} {v}' for k, v in versions.items())}",
        f"- Key fingerprint: {next((c.data.get('fingerprint') for c in checks if c.name == 'api key'), 'n/a')} (not the key)",
        f"- Request: `{json.dumps(req)}`",
        "- Findings:",
    ]
    lines += [f"  - [{c.status}] {c.name}: {c.detail}" for c in bad] or ["  - none"]
    lines.append("- Reproduce: `python dbdoctor.py " + " ".join(sys.argv[1:]) + "`")
    return "\n".join(lines)


# ---------------------------------------------------------------- network checks

def live_check(dataset: str, key: str, timeout: float = 10) -> Check:
    host = dataset.lower().replace(".", "-") + ".lsg.databento.com"
    t0 = time.perf_counter()
    try:
        addr = socket.gethostbyname(host)
    except OSError as e:
        return Check("live gateway", FAIL, f"DNS failed for {host}: {e}",
                     "Gateway host is the dataset with '.' replaced by '-', e.g. glbx-mdp3.lsg.databento.com.")
    try:
        s = socket.create_connection((host, LIVE_PORT), timeout=timeout)
    except OSError as e:
        return Check("live gateway", FAIL, f"TCP {addr}:{LIVE_PORT} failed: {e}",
                     f"Outbound TCP {LIVE_PORT} is probably blocked. Test with `nc -vz {host} {LIVE_PORT}`; "
                     "ask the network team to allow it.")
    conn_ms = (time.perf_counter() - t0) * 1000
    try:
        f = s.makefile("rwb", buffering=0)
        version = f.readline().decode().strip()
        cram = f.readline().decode().strip().split("=", 1)[1]
        digest = hashlib.sha256(f"{cram}|{key}".encode()).hexdigest()
        f.write(f"auth={digest}-{key[-5:]}|dataset={dataset}|encoding=dbn|ts_out=0\n".encode())
        reply = f.readline().decode().strip()
    finally:
        s.close()  # no start_session: nothing is streamed or billed
    auth_ms = (time.perf_counter() - t0) * 1000
    data = {"host": host, "addr": addr, "gateway": version, "connect_ms": round(conn_ms, 1), "auth_ms": round(auth_ms, 1)}
    timing = f"{version}, connect {conn_ms:.0f} ms, auth {auth_ms:.0f} ms"
    if reply.startswith("success=1"):
        return Check("live gateway", PASS, f"Authenticated on {host} ({timing})", data=data)
    err = reply.split("error=", 1)[-1]
    fix = {
        "A live data license": "Historical access does not include live. Add a live license for this dataset "
                               "in the portal (Plans and live data), or use historical/intraday replay.",
        "Authentication failed": "Key is wrong or revoked; check it in the portal.",
        "Illegal characters": "Key contains whitespace or control characters; strip it.",
    }
    return Check("live gateway", FAIL, f"{host} rejected auth: '{err}' ({timing})",
                 next((v for k, v in fix.items() if err.startswith(k)), ""), data)


def run(args: argparse.Namespace) -> list[Check]:
    import databento as db

    versions = {"python": platform.python_version(), "databento": db.__version__, "os": platform.system()}
    try:
        from importlib.metadata import version
        versions["databento-dbn"] = version("databento-dbn")
    except Exception:
        pass
    args._versions = versions

    raw = open(args.key_file, newline="").read() if args.key_file else os.environ.get("DATABENTO_API_KEY")
    checks = [check_key_hygiene(raw)]
    key = (raw or "").strip().strip("\"'")
    if checks[0].status == FAIL and not raw:
        return checks
    client = db.Historical(key)

    def api(name, fn, fix=""):
        try:
            return fn()
        except Exception as e:  # BentoClientError carries the server's case code
            checks.append(Check(name, FAIL, redact(str(e).replace("\n", " | "), raw), fix))
            return None

    datasets = api("historical auth", client.metadata.list_datasets)
    if datasets is None:
        return checks
    checks.append(Check("historical auth", PASS, f"Key accepted; {len(datasets)} datasets visible."))

    ds = args.dataset.strip().upper()
    if ds not in datasets:
        close = [d for d in datasets if d.split(".")[0] == ds.split(".")[0]]
        checks.append(Check("dataset", FAIL, f"'{args.dataset}' is not a dataset.",
                            f"Did you mean {close or datasets[:5]}? Codes are VENUE.FEED, e.g. GLBX.MDP3."))
        return checks
    rng = api("dataset range", lambda: client.metadata.get_dataset_range(dataset=ds))
    schemas = api("schemas", lambda: client.metadata.list_schemas(dataset=ds)) or []
    if args.schema not in schemas:
        checks.append(Check("schema", FAIL, f"{args.schema} is not offered on {ds}.", f"Available: {schemas}"))
        return checks
    sr = rng["schema"].get(args.schema, rng)
    checks.append(Check("dataset", PASS, f"{ds}/{args.schema}: {sr['start'][:10]} .. last ingested {sr['end'][:19]}Z"))
    checks += check_window(args.start, args.end, sr["start"], sr["end"], ds)

    syms = [s for s in args.symbols.split(",")] if args.symbols else ["ALL_SYMBOLS"]
    if syms != ["ALL_SYMBOLS"]:
        end_date = (args.end or args.start)[:10]
        if end_date <= args.start[:10]:
            end_date = (parse_day(args.start) + dt.timedelta(days=1)).date().isoformat()
        res = api("symbology", lambda: client.symbology.resolve(
            dataset=ds, symbols=syms, stype_in=args.stype_in, stype_out="instrument_id",
            start_date=args.start[:10], end_date=end_date))
        if res:
            nf, partial = res.get("not_found", []), res.get("partial", [])
            if nf:
                tips = [t for s in nf for t in symbol_suggestions(s, ds, args.stype_in)]
                checks.append(Check("symbology", FAIL if len(nf) == len(syms) else WARN,
                                    f"Not found on {ds} ({args.stype_in}): {nf}. "
                                    + ("All symbols missing: the server answers 422 symbology_invalid_request."
                                       if len(nf) == len(syms) else "Missing symbols are silently dropped from the data."),
                                    " ".join(tips) or "Check spelling and the date range with symbology.resolve."))
            if partial:
                checks.append(Check("symbology", WARN, f"Only part of the window resolves for {partial} "
                                    "(listed/expired/renamed inside the range).", "Narrow the window or check corporate actions."))
            if not nf and not partial:
                checks.append(Check("symbology", PASS, f"All {len(syms)} symbol(s) resolve."))
            checks.append(overlap_check(find_overlaps(res.get("result", {})), db.__version__))

    if not any(c.status == FAIL for c in checks):
        kw = dict(dataset=ds, symbols=syms, stype_in=args.stype_in, start=args.start, end=args.end)
        cost = api("cost", lambda: client.metadata.get_cost(schema=args.schema, **kw))
        size = api("cost", lambda: client.metadata.get_billable_size(schema=args.schema, **kw))
        if cost is not None:
            ladder = {}
            for sc in [x for x in ("mbo", "mbp-1", "trades", "ohlcv-1m", "ohlcv-1d") if x in schemas]:
                try:
                    ladder[sc] = round(client.metadata.get_cost(schema=sc, **kw), 4)
                except Exception:
                    pass
            status = FAIL if cost > args.budget else PASS
            checks.append(Check("cost", status,
                                f"${cost:,.4f} for {human_bytes(size or 0)} billable (budget ${args.budget:,.2f}). "
                                f"Same request by schema: {ladder}",
                                "Over budget: narrow symbols/dates or use a coarser schema. Pre-check with "
                                "metadata.get_cost; set a monthly limit in Billing > Usage-based access."
                                if status == FAIL else "", {"cost": cost, "bytes": size, "ladder": ladder}))

    if args.live:
        checks.append(live_check(ds, key))
    return checks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dataset", required=True)
    p.add_argument("--schema", default="trades")
    p.add_argument("--symbols", default="")
    p.add_argument("--stype-in", default="raw_symbol")
    p.add_argument("--start", required=True)
    p.add_argument("--end")
    p.add_argument("--budget", type=float, default=1.0, help="USD; FAIL if the request would cost more")
    p.add_argument("--live", action="store_true", help="also test the live gateway handshake (no data)")
    p.add_argument("--key-file")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    checks = run(args)
    versions = getattr(args, "_versions", {})
    if args.json:
        print(json.dumps({"versions": versions, "checks": [asdict(c) for c in checks]}, indent=1, default=str))
    else:
        for c in checks:
            print(f"[{c.status}] {c.name}: {c.detail}")
            if c.fix:
                print(f"       fix: {c.fix}")
        print()
        print(escalation_block(args, checks, versions))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
