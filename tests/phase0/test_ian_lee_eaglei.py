"""EAGLE-I side: the zero-versus-missing rule, the pass time, the run window, MCC and the surge timing."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from phase0_fakes import ian, write_eaglei, write_mcc

# A pass stamp on the EAGLE-I clock, like a VNP46A1 UTC_Time of 7.0 h. These tests used 05:30 (01:30 on the New
# York clock) until the pass moved to its real time near 01:30 local mean solar time, about 07:00 UTC over Lee.
AT_PASS = pd.Timestamp("2022-09-29 07:00")


def lee_runs(tmp_path, rows) -> pd.Series:
    return ian.load_lee_runs(write_eaglei(tmp_path / "eaglei.parquet", rows))


def test_zero_versus_missing(tmp_path):
    rows = [
        ("12071", 400, "2022-09-29 06:30"),
        ("12015", 9, "2022-09-29 06:45"),  # Florida reported, Lee absent: 0
        ("12071", 0, "2022-09-29 07:00"),  # an explicit zero row: 0
        ("13001", 5, "2022-09-29 07:15"),  # no Florida rows at all: skipped
    ]
    runs = lee_runs(tmp_path, rows)
    assert runs.to_dict() == {
        pd.Timestamp("2022-09-29 06:30"): 400.0,
        pd.Timestamp("2022-09-29 06:45"): 0.0,
        pd.Timestamp("2022-09-29 07:00"): 0.0,
    }
    assert ian.customers_out_at(runs, AT_PASS) == (0.0, 3)
    value, n_runs = ian.customers_out_at(runs, pd.Timestamp("2022-09-29 09:30"))  # no usable run left
    assert np.isnan(value) and n_runs == 0


def test_an_empty_lee_count_is_unknown_not_zero(tmp_path):
    runs = lee_runs(tmp_path, [("12071", None, "2022-09-29 07:00"), ("12071", 300, "2022-09-29 07:15")])
    assert np.isnan(runs[AT_PASS])
    assert ian.customers_out_at(runs, AT_PASS) == (300.0, 1)


def test_the_nominal_pass_is_0130_mean_solar_time_not_0130_new_york():
    """Replaces the test that 01:30 New York is 05:30 UTC: Suomi NPP passes near 01:30 local *mean solar* time, which
    at Lee County's 81.9 W is 01:30 + 81.9/15 h = 06:57:36 UTC (02:58 EDT), about 1.5 h after 05:30 UTC."""
    when = ian.nominal_pass_utc(dt.date(2022, 9, 29), -81.9)
    assert when == pd.Timestamp("2022-09-29 06:57:36", tz="UTC")
    assert abs(when - pd.Timestamp("2022-09-29 06:58", tz="UTC")) < pd.Timedelta(1, unit="min")
    assert when.tz_convert("America/New_York").tz_localize(None) == pd.Timestamp("2022-09-29 02:57:36")
    # Mean solar time has no daylight saving: in December the same longitude still passes at 06:57:36 UTC.
    assert ian.nominal_pass_utc(dt.date(2022, 12, 1), -81.9) == pd.Timestamp("2022-12-01 06:57:36", tz="UTC")
    assert ian.EAGLEI_TZ == "UTC"


def test_window_median_ignores_a_single_timed_out_run(tmp_path):
    stamps = pd.date_range("2022-09-29 06:00", "2022-09-29 08:00", freq="15min")
    rows = [("12015", 9, stamp) for stamp in stamps]
    rows += [("12071", 5000, stamp) for stamp in stamps if stamp != AT_PASS]  # Lee missing from the 07:00 run
    runs = lee_runs(tmp_path, rows)
    assert runs[AT_PASS] == 0.0
    assert ian.customers_out_at(runs, AT_PASS) == (5000.0, 9)


def test_window_is_plus_or_minus_sixty_minutes(tmp_path):
    stamps = ["2022-09-29 05:45", "2022-09-29 06:00", "2022-09-29 08:00", "2022-09-29 08:15"]
    runs = lee_runs(tmp_path, [("12071", count, stamp) for count, stamp in zip((1, 2, 4, 8), stamps)])
    assert ian.customers_out_at(runs, AT_PASS) == (3.0, 2)


def test_unpadded_eaglei_fips_fail_fast(tmp_path):
    with pytest.raises(ian.InputError, match="5-digit"):
        lee_runs(tmp_path, [("12071", 1, "2022-09-29 07:00"), ("1001", 1, "2022-09-29 07:00")])


def test_mcc_byte_order_mark_padding_and_grand_total(tmp_path):
    path = write_mcc(tmp_path / "MCC.csv", {"01001": 24619, "12071": 628635})
    assert path.read_bytes().startswith(b"\xef\xbb\xbfCounty_FIPS,Customers\r\n1001,24619")
    assert ian.load_customers(path, "01001") == 24619
    assert ian.load_customers(path) == 628635
    with pytest.raises(ian.InputError):
        ian.load_customers(path, "12015")


def lee_count(stamp: pd.Timestamp) -> int:
    if stamp < pd.Timestamp("2022-09-28 15:15"):
        return 50
    return 150 if stamp < pd.Timestamp("2022-09-28 18:45") else 600


def test_surge_timing_under_both_clocks(tmp_path):
    stamps = pd.date_range("2022-09-28 12:00", "2022-09-29 02:00", freq="15min")
    surge = ian.surge_timing(lee_runs(tmp_path, [("12071", lee_count(s), s) for s in stamps]), customers=1000)
    first = surge["first_10%_out"]
    assert first["stamp"] == pd.Timestamp("2022-09-28 15:15")
    assert first["hours_after_landfall_if_utc"] == pytest.approx(-23 / 6)  # 15:15 UTC is 3 h 50 min early
    assert first["hours_after_landfall_if_new_york"] == pytest.approx(1 / 6)  # 15:15 EDT is 19:15 UTC
    assert surge["first_50%_out"]["stamp"] == pd.Timestamp("2022-09-28 18:45")
    assert surge["peak"]["customers_out"] == 600.0
