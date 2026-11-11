"""Check 4, the night convention, on hand-built night tables: which files are searched and when it confirms."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from phase0_fakes import ian

SEP_27, SEP_28, SEP_29, SEP_30 = (dt.date(2022, 9, day) for day in (27, 28, 29, 30))
FILE_DATES = tuple(dt.date(2022, 8, 25) + dt.timedelta(days=i) for i in range(38))  # Aug 25 to Oct 1, as downloaded
CANT_SEE = {"status": "cant_see", "pct_darker": np.nan, "visible_share": 0.2}


def night_table(changes: dict | None = None, missing: tuple = ()) -> pd.DataFrame:
    """The check-4 columns of the night table: every file seen, lit (2% darker, nobody out) through Sep 28, then 75%
    darker with 90% out. `changes` maps a file date to the columns that differ; `missing` dates were not downloaded."""
    rows = []
    for day in (day for day in FILE_DATES if day not in missing):
        after = day > SEP_28
        row = {"file_date": day, "night": ian.night_of(day), "status": "ok", "pct_darker": 0.75 if after else 0.02,
               "visible_share": 0.9, "eaglei_pct_out": 0.9 if after else 0.0}
        rows.append({**row, **(changes or {}).get(day, {})})
    return pd.DataFrame(rows)


def controls(check: dict) -> dict:
    return {row["file_date"]: row for row in check["controls"]}


def test_the_two_controls_straddle_landfall():
    # Updated with the pass-time fix: this compared 01:30 New York passes (05:30 UTC). Now any pass the script accepts
    # (04:00-10:00 UTC on the file date) puts the Sep 28 pass before landfall and the Sep 29 pass after it.
    latest = pd.Timestamp(dt.datetime.combine(ian.EXPECTED_LAST_LIT_FILE, ian.PASS_WINDOW_UTC[1]), tz="UTC")
    earliest = pd.Timestamp(dt.datetime.combine(SEP_29, ian.PASS_WINDOW_UTC[0]), tz="UTC")
    assert latest < ian.LANDFALL_UTC < earliest
    nominal = [ian.nominal_pass_utc(day, -81.9) for day in (ian.EXPECTED_LAST_LIT_FILE, SEP_29)]
    assert nominal[0] < ian.LANDFALL_UTC < nominal[1]
    assert (ian.EXPECTED_LAST_LIT_FILE, ian.EXPECTED_FIRST_DARK_FILE) == (SEP_28, SEP_29)
    assert ian.BASELINE_LAST < SEP_28


def test_lit_sep_28_and_dark_sep_29_confirm_the_convention():
    table = night_table()
    check = ian.first_dark_file(table)
    assert (check["file_date"], check["night"], check["days_after_nasa_date"]) == (SEP_29, SEP_28, -1)
    assert check["eaglei_pct_out"] == 0.9 and check["verdict"] == "confirmed"
    lit, dark = controls(check)[SEP_28], controls(check)[SEP_29]
    assert (lit["status"], lit["dark"], lit["pct_darker"], lit["eaglei_pct_out"]) == ("ok", False, 0.02, 0.0)
    assert (dark["status"], dark["dark"], dark["pct_darker"], dark["eaglei_pct_out"]) == ("ok", True, 0.75, 0.9)
    assert ian.first_dark_file(table.iloc[::-1]) == check  # the row order does not matter
    assert table.equals(night_table())  # the input is left as it was


def test_a_dark_baseline_night_and_a_dark_sep_28_with_nobody_out_are_inconclusive():
    """The review's case: dim nights before the storm, and Sep 28 dimmed by cloud while EAGLE-I has 0% out."""
    check = ian.first_dark_file(night_table({
        dt.date(2022, 8, 25): {"pct_darker": 0.5},  # before the baseline: not searched
        dt.date(2022, 9, 3): {"pct_darker": 0.32},  # in the baseline: not searched
        SEP_28: {"pct_darker": 0.35},
    }))
    assert (check["file_date"], check["days_after_nasa_date"], check["eaglei_pct_out"]) == (SEP_28, -2, 0.0)
    assert check["verdict"] == "inconclusive"  # cloud on Sep 28 and a convention off by one look the same
    sep_28 = controls(check)[SEP_28]
    assert (sep_28["status"], sep_28["dark"], sep_28["pct_darker"], sep_28["eaglei_pct_out"]) == ("ok", True, 0.35, 0.0)
    assert controls(check)[SEP_29]["dark"]


@pytest.mark.parametrize(
    ("changes", "missing", "first_dark"),
    [
        ({SEP_28: CANT_SEE}, (), SEP_29),  # Sep 28 unseen: a convention off by one would give the same answer
        ({SEP_29: CANT_SEE}, (), SEP_30),  # Sep 29 unseen, as the morning after a hurricane often is
        ({SEP_29: {"pct_darker": 0.1}}, (), SEP_30),  # Sep 29 seen and lit: a shift the other way
        ({SEP_27: {"pct_darker": 0.4}}, (), SEP_27),  # dark before landfall, after the baseline
        ({}, (SEP_28,), SEP_29),  # no Sep 28 file
        ({day: {"pct_darker": 0.1} for day in FILE_DATES}, (), None),  # nothing ever goes dark
    ],
)
def test_anything_else_is_inconclusive(changes, missing, first_dark):
    check = ian.first_dark_file(night_table(changes, missing))
    assert (check["file_date"], check["verdict"]) == (first_dark, "inconclusive")


def test_unseen_and_missing_controls_say_why():
    unseen = controls(ian.first_dark_file(night_table({SEP_29: CANT_SEE})))[SEP_29]
    assert (unseen["status"], unseen["dark"], unseen["visible_share"]) == ("cant_see", False, 0.2)
    assert np.isnan(unseen["pct_darker"])
    absent = controls(ian.first_dark_file(night_table(missing=(SEP_28,))))[SEP_28]
    assert (absent["status"], absent["dark"], absent["night"]) == ("no_file", False, SEP_27)
    assert (absent["pct_darker"], absent["visible_share"], absent["eaglei_pct_out"]) == (None, None, None)


def test_nothing_dark_reports_no_file_date():
    check = ian.first_dark_file(night_table({day: {"pct_darker": 0.1} for day in FILE_DATES}))
    assert all(check[key] is None for key in (*ian.CHECK_4_COLUMNS, "days_after_nasa_date"))
