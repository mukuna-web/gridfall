"""Task 2: EAGLE-I loader, zero-vs-missing rule and the feed-dropout check (docs/plan.md, Week 2)."""

import time
from functools import cache
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from blackout.outages import (
    STATE_FIPS,
    coverage_for,
    customers_out_at,
    flag_dropouts,
    load_mcc,
    load_outages,
)

FIXTURES = Path(__file__).parent / "fixtures"
EAGLEI = FIXTURES / "eaglei_small.csv"
MCC = FIXTURES / "mcc_small.csv"
COVERAGE = FIXTURES / "coverage_small.csv"
NO_FLAGS = pd.DataFrame({"fips": pd.Series(dtype=object), "time": pd.Series(dtype="datetime64[ns, UTC]")})
WINDOWS = {  # name: state prefix, first stamp, last stamp (both included in the fixture)
    "A": ("12", "2022-09-29 07:45", "2022-09-29 12:15"),
    "B": ("12", "2022-09-30 05:30", "2022-09-30 09:00"),
    "C": ("12", "2022-09-15 06:45", "2022-09-15 10:45"),
    "D": ("12", "2022-10-18 22:00", "2022-10-19 01:30"),
    "E": ("12", "2022-10-17 12:00", "2022-10-17 16:00"),
    "F": ("12", "2022-10-07 21:00", "2022-10-08 01:30"),
    "G": ("12", "2022-09-17 12:30", "2022-09-17 17:00"),
    "H": ("22", "2021-08-30 16:00", "2021-08-30 19:00"),
    "I": ("48", "2021-02-18 04:30", "2021-02-18 06:30"),
}
LEE, CHARLOTTE, COLLIER, HILLSBOROUGH = "12071", "12015", "12021", "12057"


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


@cache
def window(name: str) -> pd.DataFrame:
    """A fixture window, loaded as [first stamp, last stamp + 15 min)."""
    prefix, first, last = WINDOWS[name]
    return load_outages(EAGLEI, {prefix}, utc(first), utc(last) + pd.Timedelta(minutes=15))


def flag_set(flags: pd.DataFrame) -> set[tuple[str, pd.Timestamp]]:
    return set(zip(flags["fips"], pd.to_datetime(flags["time"], utc=True)))


# --- synthetic frames: runs every 15 minutes on one day --------------------------------------------------------

DAY = "2022-07-01"


def at(hhmm: str) -> pd.Timestamp:
    return utc(f"{DAY} {hhmm}")


def runs(first: str = "06:00", count: int = 33) -> list[pd.Timestamp]:
    return [at(first) + pd.Timedelta(minutes=15 * k) for k in range(count)]


def series(times: list[pd.Timestamp], value: float | None, changes: list[tuple[str, str, float | None]] = ()) -> list:
    """`value` in every run, except `(first, last, new)` spans (HH:MM, both included). None means no row."""
    out = []
    for t in times:
        v = value
        for first, last, new in changes:
            if at(first) <= t <= at(last):
                v = new
        out.append(v)
    return out


def frame(columns: dict[str, list], times: list[pd.Timestamp]) -> pd.DataFrame:
    rows = [(fips, t, v) for fips, values in columns.items() for t, v in zip(times, values) if v is not None]
    out = pd.DataFrame(rows, columns=["fips", "time", "customers_out"]).astype({"customers_out": "float64"})
    return out.sort_values(["time", "fips"]).reset_index(drop=True)


def ninety_minute_case(prefix: str = "12", other: float = 1_000, absent_in_dip: bool = False) -> pd.DataFrame:
    times = runs()
    low = None if absent_in_dip else 500
    return frame({f"{prefix}001": series(times, 100_000, [("09:00", "10:15", low)]),
                  f"{prefix}003": series(times, other)}, times)


# --- loading ---------------------------------------------------------------------------------------------------

def test_load_types_and_whole_state(tmp_path):
    b = window("B")
    assert len(b) == 783
    assert b["time"].nunique() == 15
    assert b["fips"].nunique() == 57
    assert all(isinstance(f, str) and len(f) == 5 and f.startswith("12") for f in b["fips"])
    assert str(b["time"].dt.tz) == "UTC"
    assert b["customers_out"].dtype == np.float64

    parquet = tmp_path / "window_b.parquet"
    duckdb.connect().execute(
        f"copy (select * from read_csv('{EAGLEI}', types={{'fips_code': 'VARCHAR'}})) to '{parquet}' (format parquet)")
    prefix, first, last = WINDOWS["B"]
    from_parquet = load_outages(parquet, {prefix}, utc(first), utc(last) + pd.Timedelta(minutes=15))
    pd.testing.assert_frame_equal(from_parquet, b)

    two_rows = tmp_path / "alabama.csv"
    two_rows.write_text("fips_code,county,state,customers_out,run_start_time\n"
                        "01005,Barbour,Alabama,4,2022-01-01 00:00:00\n"
                        "01009,Blount,Alabama,160,2022-01-01 00:00:00\n")
    alabama = load_outages(two_rows, {"01"}, utc("2022-01-01 00:00"), utc("2022-01-01 00:15"))
    assert list(alabama["fips"]) == ["01005", "01009"]


def test_parquet_with_integer_codes_rejected(tmp_path):
    parquet = tmp_path / "bigint.parquet"
    duckdb.connect().execute(f"copy (select * from read_csv('{EAGLEI}')) to '{parquet}' (format parquet)")
    with pytest.raises(ValueError, match="VARCHAR"):
        load_outages(parquet, {"12"}, utc("2022-09-30 07:00"), utc("2022-09-30 08:00"))


def test_window_filter(monkeypatch):
    with monkeypatch.context() as m:
        m.setenv("TZ", "America/Los_Angeles")
        time.tzset()
        got = load_outages(EAGLEI, {"12"}, utc("2022-09-30 07:00"), utc("2022-09-30 08:00"))
    time.tzset()
    assert len(got) == 208
    assert sorted(got["time"].unique()) == [utc("2022-09-30 07:00"), utc("2022-09-30 07:15"),
                                            utc("2022-09-30 07:30"), utc("2022-09-30 07:45")]


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        load_outages(EAGLEI, {"12"}, pd.Timestamp("2022-09-30 07:00"), utc("2022-09-30 08:00"))
    with pytest.raises(ValueError):
        customers_out_at(window("B"), LEE, pd.Timestamp("2022-09-30 07:00"))
    with pytest.raises(ValueError):
        load_outages(EAGLEI, {"FL"}, utc("2022-09-30 07:00"), utc("2022-09-30 08:00"))
    with pytest.raises(ValueError):  # a naive `when` is caught before an empty frame returns NaN
        customers_out_at(window("B").iloc[0:0], LEE, pd.Timestamp("2022-09-30 07:00"))


def test_state_fips_covers_coverage_file():
    assert len(STATE_FIPS) == 56
    assert STATE_FIPS["FL"] == "12" and STATE_FIPS["VI"] == "78"


# --- zero, missing and absent ----------------------------------------------------------------------------------

def test_empty_count_is_nan_and_skipped():
    h = window("H")
    assert len(h) == 687
    empty = h[h["customers_out"].isna()]
    assert len(empty) == 82
    assert set(empty["time"]) == {utc("2021-08-30 17:30"), utc("2021-08-30 18:30")}
    jefferson, when = "22051", utc("2021-08-30 17:30")
    assert np.isnan(customers_out_at(h, jefferson, when, window_minutes=0, dropouts=NO_FLAGS))
    assert customers_out_at(h, jefferson, when, window_minutes=15, dropouts=NO_FLAGS) == 200679.0


def test_absent_county_in_live_run_is_zero():
    c = window("C")
    when = utc("2022-09-15 08:45")
    near = c[(c["time"] - when).abs() <= pd.Timedelta(minutes=60)]
    per_run = near.groupby("time").size()
    assert len(per_run) == 9 and per_run.between(24, 26).all()
    assert CHARLOTTE not in set(near["fips"])
    assert customers_out_at(c, CHARLOTTE, when) == 0.0
    only_charlotte = c[c["fips"] == CHARLOTTE]
    assert only_charlotte.empty
    assert np.isnan(customers_out_at(only_charlotte, CHARLOTTE, when))


def test_missing_state_run_is_nan():
    d = window("D")
    stamps = set(d["time"])
    for missing in ("2022-10-18 23:15", "2022-10-19 00:15", "2022-10-19 00:30"):
        assert utc(missing) not in stamps
    when = utc("2022-10-19 00:22:30")
    assert np.isnan(customers_out_at(d, LEE, when, window_minutes=15))
    assert customers_out_at(d, LEE, when, window_minutes=60) == 11520.0


# --- the dropout rule on real windows --------------------------------------------------------------------------

def test_single_timeout_run_ignored():
    times = runs("08:00", 9)
    df = frame({"12001": series(times, 5_000, [("09:00", "09:00", 0)]), "12003": series(times, 1_000)}, times)
    assert customers_out_at(df, "12001", at("09:00")) == 5000.0
    assert flag_set(flag_dropouts(df)) == {("12001", at("09:00"))}


def test_dropout_1_flagged():
    flags = flag_dropouts(window("A"))
    dip = [utc("2022-09-29 09:15") + pd.Timedelta(minutes=15 * k) for k in range(7)]
    lee = sorted(flags.loc[flags["fips"] == LEE, "time"])
    assert lee == dip
    listed = ["12007", "12009", "12011", "12015", "12021", "12027", "12035", "12043", "12051", "12061", "12071",
              "12081", "12085", "12086", "12093", "12099", "12107", "12109", "12111", "12115", "12127"]
    got = flag_set(flags)
    for fips in listed:
        assert all((fips, t) in got for t in dip), fips
    assert not set(flags["time"]) & {utc("2022-09-29 09:00"), utc("2022-09-29 11:00")}
    assert len(flags) == 165


def test_feed_dropout_is_missing():
    a = window("A")
    flags = flag_dropouts(a)
    when = utc("2022-09-29 10:00")
    assert np.isnan(customers_out_at(a, LEE, when, 30, flags))
    assert customers_out_at(a, LEE, when, 30, NO_FLAGS) == 175458.0
    assert customers_out_at(a, LEE, when, 60, flags) == 421267.5
    assert customers_out_at(a, LEE, when, 60, NO_FLAGS) == 175468.0
    assert customers_out_at(a, LEE, when, 90, flags) == 421267.5


def test_single_run_dropout_teco():
    a = window("A")
    flags = flag_dropouts(a)
    when = utc("2022-09-29 11:30")
    assert set(flags.loc[flags["time"] == when, "fips"]) == {"12057", "12101", "12105"}
    assert np.isnan(customers_out_at(a, HILLSBOROUGH, when, 0, flags))
    assert customers_out_at(a, HILLSBOROUGH, when, 0, NO_FLAGS) == 1214.0


def test_partial_dropout_dropped():
    b = window("B")
    flags = flag_dropouts(b)
    expected = {(f, utc(t)) for f in (LEE, COLLIER) for t in ("2022-09-30 07:00", "2022-09-30 07:15")}
    assert flag_set(flags) == expected
    shorter = load_outages(EAGLEI, {"12"}, utc("2022-09-30 06:00"), utc("2022-09-30 08:45"))
    assert flag_set(flag_dropouts(shorter)) == expected
    when = utc("2022-09-30 07:28:03")
    assert customers_out_at(b, LEE, when, 30, flags) == 411676.0
    assert customers_out_at(b, LEE, when, 30, NO_FLAGS) == 325973.0
    assert customers_out_at(b, LEE, when, 60, flags) == 411615.0
    assert customers_out_at(b, LEE, when, 60, NO_FLAGS) == 409085.5
    assert customers_out_at(b, LEE, when, 90, flags) == 411614.5
    assert customers_out_at(b, COLLIER, when, 30, flags) == 166534.0
    assert customers_out_at(b, COLLIER, when, 30, NO_FLAGS) == 154277.0


def test_real_restoration_step_kept():
    f = window("F")
    flags = flag_dropouts(f)
    assert LEE not in set(flags["fips"])
    assert customers_out_at(f, LEE, utc("2022-10-07 23:15"), dropouts=flags) == 65644.0
    assert set(flags["time"]) == {utc("2022-10-08 00:30")}
    assert len(flags) == 20 and CHARLOTTE in set(flags["fips"])


def test_one_run_spike_is_not_a_level():
    e = window("E")
    flags = flag_dropouts(e)
    assert flags.empty
    when = utc("2022-10-17 14:00")
    assert customers_out_at(e, LEE, when, dropouts=flags) == 11399.0
    for minutes in (0, 15, 30):
        assert customers_out_at(e, LEE, when, minutes, flags) == 11275.0


def test_unrelated_churn_not_flagged():
    assert flag_dropouts(window("G")).empty


def test_uri_restoration_blip_not_flagged():
    i = window("I")
    flags = flag_dropouts(i)
    assert flags.empty
    assert customers_out_at(i, "48201", utc("2021-02-18 05:30"), dropouts=flags) == 86820.0


# --- the dropout rule on synthetic frames ----------------------------------------------------------------------

@pytest.mark.parametrize("other, absent, without", [(1_000, False, 500.0), (900_000, False, 500.0),
                                                    (1_000, True, 0.0)])
def test_synthetic_90_minute_dropout(other, absent, without):
    df = ninety_minute_case(other=other, absent_in_dip=absent)
    flags = flag_dropouts(df)
    dip = [at("09:00") + pd.Timedelta(minutes=15 * k) for k in range(6)]
    assert flag_set(flags) == {("12001", t) for t in dip}
    when = at("09:37:30")
    assert np.isnan(customers_out_at(df, "12001", when, 30, flags))
    assert customers_out_at(df, "12001", when, 60, flags) == 100000.0
    assert customers_out_at(df, "12001", when, 60, NO_FLAGS) == without


def test_synthetic_split_dip_is_one_dip():
    times = runs()
    df = frame({"12001": series(times, 100_000, [("09:00", "09:30", 500), ("10:00", "10:30", 500)]),
                "12003": series(times, 1_000)}, times)
    flags = flag_dropouts(df)
    assert len(flags) == 6 and set(flags["fips"]) == {"12001"}
    assert customers_out_at(df, "12001", at("09:45"), 60, flags) == 100000.0
    assert customers_out_at(df, "12001", at("09:45"), 60, NO_FLAGS) == 500.0


def test_rider_not_flagged():
    times = runs()
    df = frame({"12001": series(times, 100_000, [("09:00", "09:45", 500)]),
                "12003": series(times, 10_000, [("09:30", "09:45", 8_000)]),
                "12005": series(times, 1_000)}, times)
    flags = flag_dropouts(df)
    assert set(flags["fips"]) == {"12001"}
    assert customers_out_at(df, "12003", at("09:30"), 0, flags) == 8000.0


def test_thresholds_are_pinned():
    times = runs("08:00", 9)
    flagged = frame({"12001": series(times, 7_500, [("09:00", "09:00", 0)]), "12003": series(times, 92_500)}, times)
    assert flag_set(flag_dropouts(flagged)) == {("12001", at("09:00"))}
    kept = frame({"12001": series(times, 7_500, [("09:00", "09:00", 0)]), "12003": series(times, 100_000)}, times)
    assert flag_dropouts(kept).empty

    times = runs()
    three_hours = frame({"12001": series(times, 100_000, [("09:15", "11:45", 500)]),
                         "12003": series(times, 1_000)}, times)
    flags = flag_dropouts(three_hours)
    assert len(flags) == 11
    assert np.isnan(customers_out_at(three_hours, "12001", at("10:30"), 60, flags))
    longer = frame({"12001": series(times, 100_000, [("09:15", "12:00", 500)]), "12003": series(times, 1_000)}, times)
    flags = flag_dropouts(longer)
    assert flags.empty
    assert customers_out_at(longer, "12001", at("10:30"), 60, flags) == 500.0


def test_ramp_and_step_not_flagged():
    times = runs()
    factor = (2_000 / 400_000) ** (1 / 32)
    df = frame({"12001": [200_000 - k * (199_000 / 32) for k in range(33)],
                "12003": series(times, 1_000),
                "12005": [400_000 * factor**k for k in range(33)],
                "12007": series(times, 100_000, [("09:00", "14:00", 60_000)])}, times)
    flags = flag_dropouts(df)
    assert flags.empty
    assert customers_out_at(df, "12001", at("10:00"), dropouts=flags) == 100500.0
    assert customers_out_at(df, "12007", at("09:00"), dropouts=flags) == 60000.0


def test_walk_resumes_after_rejected_dip():
    times = runs()
    df = frame({"12001": series(times, 1_000, [("06:00", "06:15", 6_000)]),
                "12003": series(times, 5_000, [("06:00", "07:30", 0)]),
                "12005": series(times, 1_500, [("07:00", "07:15", 0)]),
                "12007": series(times, 500)}, times)
    assert flag_dropouts(df).empty


def test_states_are_independent():
    times = runs()
    louisiana = ninety_minute_case(prefix="22")
    mississippi_times = [t for t in times if t not in (at("11:00"), at("11:15"))]
    mississippi = frame({"28001": series(mississippi_times, 5_000, [("12:00", "12:15", 0)]),
                         "28003": series(mississippi_times, 1_000)}, mississippi_times)
    df = pd.concat([louisiana, mississippi]).sort_values(["time", "fips"]).reset_index(drop=True)
    flags = flag_dropouts(df)
    assert len(flags) == 8
    assert flag_set(flags) >= {("28001", at("12:00")), ("28001", at("12:15"))}
    assert (flags["fips"] == "22001").sum() == 6
    assert np.isnan(customers_out_at(df, "28001", at("11:07:30"), 8, flags))


def test_empty_frame_gives_nan_and_no_flags():
    empty = window("B").iloc[0:0]
    assert flag_dropouts(empty).empty
    assert np.isnan(customers_out_at(empty, LEE, utc("2022-09-30 07:00")))


# --- customers and coverage ------------------------------------------------------------------------------------

def test_mcc_bom_and_padding():
    assert load_mcc(MCC)["01001"] == 24619


def test_mcc_drops_grand_total():
    counts = load_mcc(MCC)
    assert "Grand Total" not in counts
    assert all(len(k) == 5 and k.isdigit() for k in counts)


def test_coverage_fallback():
    assert coverage_for(COVERAGE, "TX", 2024) == 0.93
    assert coverage_for(COVERAGE, "TX", 2021) == 0.94


def test_coverage_before_first_year_raises():
    with pytest.raises(ValueError):
        coverage_for(COVERAGE, "FL", 2017)
