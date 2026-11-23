"""Offline tests. Fixtures are real API responses captured on 2026-11-23."""
import dbdoctor as d

GOOD = "db-" + "A" * 29

# symbology.resolve, GLBX.MDP3, ["ES.c.0","ES.v.0"], continuous, 2026-09-14..2026-09-24
ES_RESOLVE = {
    "ES.v.0": [{"d0": "2026-09-14", "d1": "2026-09-16", "s": "42140870"},
               {"d0": "2026-09-16", "d1": "2026-09-24", "s": "10252"}],
    "ES.c.0": [{"d0": "2026-09-14", "d1": "2026-09-20", "s": "42140870"},
               {"d0": "2026-09-20", "d1": "2026-09-24", "s": "10252"}],
}


def test_key_ok():
    c = d.check_key_hygiene(GOOD)
    assert c.status == d.PASS and GOOD not in c.detail


def test_key_trailing_newline_and_crlf():
    for raw in (GOOD + "\n", GOOD + "\r\n", GOOD + " "):
        c = d.check_key_hygiene(raw)
        assert c.status == d.FAIL and "whitespace" in c.detail and "auth_invalid_username" in c.fix


def test_key_quoted_and_prefix():
    assert "quotes" in d.check_key_hygiene(f'"{GOOD}"').detail
    assert "db-" in d.check_key_hygiene(GOOD[3:]).detail


def test_key_missing():
    assert d.check_key_hygiene(None).status == d.FAIL


def test_fingerprint_ignores_whitespace_and_hides_key():
    assert d.key_fingerprint(GOOD) == d.key_fingerprint(GOOD + "\n")
    assert GOOD[3:] not in d.key_fingerprint(GOOD)


def test_redact_server_echo():
    # The 400 auth_invalid_username_in_basic_auth body echoes the key back
    msg = f"400 auth_invalid_username_in_basic_auth | Invalid username in Basic auth ('{GOOD}\r')."
    assert GOOD not in d.redact(msg, GOOD + "\r")


def test_overlap_detected_from_real_es_mapping():
    o = d.find_overlaps(ES_RESOLVE)
    ids = {x["instrument_id"] for x in o}
    assert ids == {"42140870", "10252"}
    c = d.overlap_check(o, "0.90.0")
    assert c.status == d.WARN and "NaN" in c.detail
    assert "NaN" not in d.overlap_check(o, "0.68.0").detail


def test_no_overlap_for_adjacent_rolls():
    # ES.c.0 and ES.c.1 hand the same contract over without sharing a day
    res = {"ES.c.0": [{"d0": "2026-09-14", "d1": "2026-09-20", "s": "1"}],
           "ES.c.1": [{"d0": "2026-09-20", "d1": "2026-09-24", "s": "1"}]}
    assert d.find_overlaps(res) == []


def test_window_errors_match_server_cases():
    a0, a1 = "2018-05-01T00:00:00.000000000Z", "2026-11-23T05:00:00.000000000Z"
    texts = " ".join(c.fix + c.detail for c in d.check_window("2026-11-18", "2026-11-17", a0, a1))
    assert "data_time_range_start_on_or_after_end" in texts
    assert "data_start_before_available_start" in " ".join(c.fix for c in d.check_window("2000-01-03", "2000-01-04", a0, a1))
    tail = d.check_window("2026-11-23T00:00", "2026-11-23T09:00", a0, a1)
    assert any(c.status == d.WARN and "license_not_found_unauthorized" in c.detail for c in tail)


def test_timezone_note_by_dataset():
    a0, a1 = "2018-05-01T00:00:00Z", "2026-11-23T05:00:00Z"
    eq = [c for c in d.check_window("2026-11-17", "2026-11-18", a0, a1, "XNAS.ITCH") if c.name == "timezone"][0]
    fut = [c for c in d.check_window("2026-11-17", "2026-11-18", a0, a1, "GLBX.MDP3") if c.name == "timezone"][0]
    assert "19:00" in eq.detail and "Pre-market" in eq.detail
    assert "17:00 Chicago" in fut.detail


def test_symbol_suggestions():
    assert any("ES.FUT" in t and "ES.c.0" in t for t in d.symbol_suggestions("ES", "GLBX.MDP3", "raw_symbol"))
    assert any("'BRK.B'" in t for t in d.symbol_suggestions("BRK/B", "XNAS.ITCH", "raw_symbol"))
    assert any("ROOT.c.N" in t for t in d.symbol_suggestions("ES", "GLBX.MDP3", "continuous"))


def test_human_bytes():
    assert d.human_bytes(7267584) == "6.9 MB"
    assert d.human_bytes(512) == "512.0 B"
