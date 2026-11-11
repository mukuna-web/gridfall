"""The chart code split out of ian_lee.py (scripts/phase0/ian_lee_chart.py): where landfall sits on the night axis,
and labels that give each night's pass as found, not 01:30 EDT."""

import sys
from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pytest
from phase0_fakes import ian

chart = ian.chart
NIGHTS = np.array([float(mdates.date2num(pd.Timestamp(day))) for day in ("2022-09-27", "2022-09-28")])


def num(stamp: str) -> float:
    return float(mdates.date2num(pd.Timestamp(stamp)))


def test_ian_lee_imports_the_chart_module_next_to_it():
    assert Path(chart.__file__) == Path(ian.__file__).with_name("ian_lee_chart.py")
    assert sys.modules["ian_lee_chart"] is chart and callable(chart.plot_nights)


def test_landfall_sits_between_the_passes_around_it():
    # Night Sep 27 is drawn at Sep 27 but seen at the Sep 28 pass, 07:00 UTC; night Sep 28 at the Sep 29 pass. Landfall
    # at 19:05 UTC is 12 h 05 min into the 24 h between them. (The old marker assumed 01:30 EDT passes: Sep 27 13:35.)
    passes = np.array([num("2022-09-28 07:00"), num("2022-09-29 07:00")])
    assert chart.moment_x(ian.LANDFALL_UTC, passes, NIGHTS) == pytest.approx(num("2022-09-27 12:05"))
    assert chart.moment_x(ian.LANDFALL_UTC, passes[::-1], NIGHTS[::-1]) == pytest.approx(num("2022-09-27 12:05"))


def test_moments_outside_the_passes_keep_the_nearest_pass_offset():
    passes = np.array([num("2022-09-28 07:00"), num("2022-09-29 06:00")])
    before, after = pd.Timestamp("2022-09-27 07:00", tz="UTC"), pd.Timestamp("2022-09-30 06:00", tz="UTC")
    assert chart.moment_x(before, passes, NIGHTS) == pytest.approx(num("2022-09-26"))
    assert chart.moment_x(after, passes, NIGHTS) == pytest.approx(num("2022-09-29"))


def test_labels_give_the_pass_times_found_not_0130_edt():
    table = pd.DataFrame({
        "pass_utc": pd.to_datetime(["2022-09-28 06:30:00", "2022-09-29 07:00:00", "2022-09-30 06:57:57"], utc=True),
        "pass_source": ["VNP46A1", "VNP46A1", "nominal_solar_time"],
    })
    xlabel, note = chart.pass_text(table)
    assert xlabel.endswith("each point is that night's satellite pass, 06:30–07:00 UTC on the file date")
    assert note == ("Pass time = median VNP46A1 UTC_Time over the county on 2 nights; 01:30 local mean solar time at "
                    "the county's longitude on 1 night.")
    assert "EDT" not in xlabel + note
