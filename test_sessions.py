"""Session rules pinned to dates. Times from the exchanges' pages, checked 2026-11-24."""
import datetime as dt

import pandas as pd
import pytest

import sessions as s

D = dt.date
U = lambda x: pd.Timestamp(x, tz="UTC")


def test_cme_monday_opens_sunday_and_follows_dst():
    assert s.trade_window("GLBX", D(2026, 10, 30)) == (U("2026-10-29 22:00"), U("2026-10-30 21:00"))
    assert s.trade_window("GLBX", D(2026, 11, 2)) == (U("2026-11-01 23:00"), U("2026-11-02 22:00"))


def test_ose_night_session_counts_toward_next_business_day():
    # Monday 30 Nov's trading day starts Friday 27 Nov 17:00 JST (08:00 UTC)
    start, end = s.trade_window("XOSE", D(2026, 11, 30))
    assert start == U("2026-11-27 07:45")            # night pre-open 16:45 JST
    assert end == U("2026-11-30 06:50")              # 15:45 JST close + padding
    td = s.assign_trade_date(pd.Series([U("2026-11-27 11:00")]), "XOSE")   # Fri 20:00 JST
    assert td.iloc[0] == pd.Timestamp("2026-11-30")


def test_ose_day_session_opens_previous_utc_day():
    rows = s.session_table("XOSE", D(2026, 12, 1))
    day = rows[rows.session == "day"].iloc[0]
    assert day.UTC.startswith("Mon 30 Nov 23:45")


def test_ose_schedule_change_2024_11_05():
    assert s.trade_window("XOSE", D(2024, 11, 1))[1] == U("2024-11-01 06:20")   # 15:15 close
    assert s.trade_window("XOSE", D(2024, 11, 6))[1] == U("2024-11-06 06:50")   # 15:45 close


def test_ose_holiday_trading_rolls_into_next_trade_date():
    # 2026-09-21..23 are JPX holidays; holiday-session trades count toward Thu 24 Sep
    td = s.assign_trade_date(pd.Series([U("2026-09-22 02:00")]), "XOSE")
    assert td.iloc[0] == pd.Timestamp("2026-09-24")


def test_tse_lunch_break_and_2024_close_change():
    lunch = s.assign_trade_date(pd.Series([U("2026-11-20 02:45")]), "XTKS")      # 11:45 JST
    assert pd.isna(lunch.iloc[0])
    assert s.trade_window("XTKS", D(2024, 11, 1))[1] == U("2024-11-01 06:05")
    assert s.trade_window("XTKS", D(2024, 11, 5))[1] == U("2024-11-05 06:35")
    # pre-open order entry starts 23:00 UTC the previous day, but has no trades
    assert s.trade_window("XTKS", D(2026, 11, 20))[0] == U("2026-11-19 23:00")


def test_hkfe_after_hours_is_next_business_day():
    td = s.assign_trade_date(pd.Series([U("2026-11-20 10:00")]), "XHKF")         # Fri 18:00 HKT
    assert td.iloc[0] == pd.Timestamp("2026-11-23")


def test_hkfe_aht_open_moved_2026_07_20():
    assert s.trade_window("XHKF", D(2026, 7, 20))[0] == U("2026-07-17 09:15")   # Fri 17:15 HKT
    assert s.trade_window("XHKF", D(2026, 7, 21))[0] == U("2026-07-20 09:00")   # Mon 17:00 HKT


def test_hkex_half_day_and_no_night_after_it():
    assert s.trade_window("XHKG", D(2026, 12, 24))[1] == U("2026-12-24 04:10")  # CAS ends 12:10 HKT
    # 24 Dec half-day has no evening session and 25 Dec is a holiday: Mon 28 Dec starts at 08:45 HKT
    assert s.trade_window("XHKF", D(2026, 12, 28))[0] == U("2026-12-28 00:45")


def test_not_a_business_day():
    with pytest.raises(ValueError):
        s.trade_window("XOSE", D(2026, 11, 23))      # JPX holiday (BCP test day)


def test_utc_day_mixes_trade_dates_on_ose():
    c = s.utc_day_contents("XOSE", D(2026, 12, 1))
    got = {(r.trade_date, r.session): r.minutes_in_utc_day for r in c.itertuples()}
    assert got[("2026-12-01", "day")] == 410          # 09:00-15:50 JST; misses the 08:45 open
    assert got[("2026-12-02", "night")] == 785         # the whole night session belongs to Dec 2
    assert got[("2026-12-02", "day")] == 15            # and Dec 2's opening auction
