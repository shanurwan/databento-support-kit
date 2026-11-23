"""Round 1: free calls only (metadata + symbology). Records exact responses."""
import json, os, traceback
import databento as db

c = db.Historical(os.environ["DATABENTO_API_KEY"])
out = {}

def run(name, fn):
    try:
        r = fn()
        out[name] = {"ok": True, "result": r if isinstance(r, (dict, list, str, int, float)) else repr(r)}
    except Exception as e:
        out[name] = {"ok": False, "type": type(e).__name__, "msg": str(e)[:1500]}
    print(name, "->", json.dumps(out[name])[:400])

run("range_GLBX", lambda: c.metadata.get_dataset_range(dataset="GLBX.MDP3"))
run("range_XNAS", lambda: c.metadata.get_dataset_range(dataset="XNAS.ITCH"))
run("dataset_lowercase", lambda: c.metadata.get_dataset_range(dataset="glbx.mdp3"))
run("dataset_typo", lambda: c.metadata.get_dataset_range(dataset="GLBX.MDP"))
run("schemas_DBEQ", lambda: c.metadata.list_schemas(dataset="DBEQ.BASIC"))
run("schemas_GLBX", lambda: c.metadata.list_schemas(dataset="GLBX.MDP3"))
run("cond_XNAS", lambda: c.metadata.get_dataset_condition(dataset="XNAS.ITCH", start_date="2026-11-01"))
run("cost_ES_raw_mbo_day", lambda: c.metadata.get_cost(dataset="GLBX.MDP3", symbols="ESZ6", schema="mbo", start="2026-11-17", end="2026-11-18"))
run("cost_ALL_mbo_day", lambda: c.metadata.get_cost(dataset="GLBX.MDP3", symbols="ALL_SYMBOLS", schema="mbo", start="2026-11-17", end="2026-11-18"))
run("cost_ES_ohlcv1m_month", lambda: c.metadata.get_cost(dataset="GLBX.MDP3", symbols="ES.c.0", stype_in="continuous", schema="ohlcv-1m", start="2026-10-01", end="2026-11-01"))
run("cost_AAPL_trades_day", lambda: c.metadata.get_cost(dataset="XNAS.ITCH", symbols="AAPL", schema="trades", start="2026-11-17", end="2026-11-18"))
run("size_AAPL_trades_day", lambda: c.metadata.get_billable_size(dataset="XNAS.ITCH", symbols="AAPL", schema="trades", start="2026-11-17", end="2026-11-18"))
run("cost_schema_unsupported", lambda: c.metadata.get_cost(dataset="DBEQ.BASIC", symbols="AAPL", schema="mbo", start="2026-11-17", end="2026-11-18"))
run("cost_future_end", lambda: c.metadata.get_cost(dataset="XNAS.ITCH", symbols="AAPL", schema="trades", start="2026-11-17", end="2026-12-30"))
run("cost_before_start", lambda: c.metadata.get_cost(dataset="XNAS.ITCH", symbols="AAPL", schema="trades", start="2000-01-03", end="2000-01-04"))
run("cost_start_after_end", lambda: c.metadata.get_cost(dataset="XNAS.ITCH", symbols="AAPL", schema="trades", start="2026-11-18", end="2026-11-17"))
run("cost_ES_rawsym_parentstyle", lambda: c.metadata.get_cost(dataset="GLBX.MDP3", symbols="ES", schema="ohlcv-1d", start="2026-11-17", end="2026-11-18"))
run("sym_ES_raw", lambda: c.symbology.resolve(dataset="GLBX.MDP3", symbols=["ES"], stype_in="raw_symbol", stype_out="instrument_id", start_date="2026-11-17", end_date="2026-11-18"))
run("sym_ES_parent", lambda: c.symbology.resolve(dataset="GLBX.MDP3", symbols=["ES.FUT"], stype_in="parent", stype_out="instrument_id", start_date="2026-11-17", end_date="2026-11-18"))
run("sym_ES_c0", lambda: c.symbology.resolve(dataset="GLBX.MDP3", symbols=["ES.c.0", "ES.v.0", "ES.n.0"], stype_in="continuous", stype_out="instrument_id", start_date="2026-09-10", end_date="2026-09-25"))
run("sym_BRK", lambda: c.symbology.resolve(dataset="XNAS.ITCH", symbols=["BRK.B", "BRK B", "BRK/B", "BRKB"], stype_in="raw_symbol", stype_out="instrument_id", start_date="2026-11-17", end_date="2026-11-18"))
run("sym_weekend", lambda: c.symbology.resolve(dataset="XNAS.ITCH", symbols=["AAPL"], stype_in="raw_symbol", stype_out="instrument_id", start_date="2026-11-21", end_date="2026-11-23"))
run("unit_prices_GLBX", lambda: c.metadata.list_unit_prices(dataset="GLBX.MDP3"))

json.dump(out, open("out/probe1.json", "w"), indent=1, default=str)
