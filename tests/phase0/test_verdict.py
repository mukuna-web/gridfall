"""Tests for scripts/phase0/verdict.py: the pre-registered 'lines move together' rule, on synthetic night tables."""

import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/phase0/verdict.py"
spec = importlib.util.spec_from_file_location("verdict", SCRIPT)
verdict = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verdict)

LANDFALL_FILE = dt.date(2022, 9, 28)


def table(darker, official, status=None, start=dt.date(2022, 9, 29)):
    """One row per file date from `start`; nights are file date minus 1. Adds 3 quiet baseline rows."""
    rows = []
    for i, (d, o) in enumerate(zip(darker, official)):
        file_date = start + dt.timedelta(days=i)
        rows.append({"file_date": file_date, "night": file_date - dt.timedelta(days=1),
                     "status": (status or ["ok"] * len(darker))[i], "pct_darker": d, "eaglei_pct_out": o,
                     "in_baseline": False, "after_landfall": file_date > LANDFALL_FILE})
    for i, d in enumerate((0.02, -0.01, 0.0)):
        file_date = dt.date(2022, 9, 1) + dt.timedelta(days=i)
        rows.append({"file_date": file_date, "night": file_date - dt.timedelta(days=1), "status": "ok",
                     "pct_darker": d, "eaglei_pct_out": 0.0, "in_baseline": True, "after_landfall": False})
    return pd.DataFrame(rows)


def test_lines_that_peak_and_recover_together_pass():
    result = verdict.judge(table([0.8, 0.7, 0.5, 0.3, 0.1, 0.05], [0.7, 0.6, 0.45, 0.25, 0.08, 0.03]))
    assert result["verdict"] == "pass"
    assert result["checks"]["peak_timing"]["nights_apart"] == 0
    assert result["checks"]["same_direction"]["spearman"] == 1.0


def test_a_peak_two_nights_late_fails():
    result = verdict.judge(table([0.2, 0.3, 0.8, 0.5, 0.1, 0.05], [0.7, 0.6, 0.45, 0.25, 0.08, 0.03]))
    assert result["checks"]["peak_timing"]["holds"] is False
    assert result["verdict"] == "fail"


def test_fewer_than_three_visible_nights_is_inconclusive():
    status = ["ok", "cant_see", "cant_see", "cant_see", "ok", "cant_see"]
    result = verdict.judge(table([0.8, 0.7, 0.5, 0.3, 0.1, 0.05], [0.7, 0.6, 0.45, 0.25, 0.08, 0.03], status))
    assert result["verdict"].startswith("inconclusive")
    assert result["n_visible_nights"] == 2


def test_cloudy_nights_are_left_out_of_the_comparison():
    status = ["ok", "cant_see", "ok", "ok", "ok", "ok"]
    result = verdict.judge(table([0.8, 0.0, 0.5, 0.3, 0.1, 0.05], [0.7, 0.6, 0.45, 0.25, 0.08, 0.03], status))
    assert "2022-09-29" not in result["visible_nights"]  # the cant_see night (file Sep 30) is excluded
    assert result["verdict"] == "pass"


def test_only_one_line_recovering_fails_recovery_timing():
    result = verdict.judge(table([0.8, 0.75, 0.7, 0.7, 0.65, 0.6], [0.7, 0.6, 0.45, 0.25, 0.08, 0.03]))
    assert result["checks"]["recovery_timing"]["holds"] is False
    assert result["verdict"] == "fail"


def test_neither_line_recovering_is_inconclusive():
    result = verdict.judge(table([0.8, 0.78, 0.76, 0.75, 0.74, 0.73], [0.7, 0.69, 0.68, 0.67, 0.66, 0.65]))
    assert result["verdict"].startswith("inconclusive")


def test_baseline_noise_is_reported():
    result = verdict.judge(table([0.8, 0.7, 0.5, 0.3, 0.1, 0.05], [0.7, 0.6, 0.45, 0.25, 0.08, 0.03]))
    assert result["baseline_noise"]["n_nights"] == 3
    assert abs(result["baseline_noise"]["mean_pct_darker"] - 0.00333) < 1e-3


def test_missing_official_value_drops_the_night():
    result = verdict.judge(table([0.8, 0.7, 0.5, 0.3, 0.1, 0.05], [0.7, float("nan"), 0.45, 0.25, 0.08, 0.03]))
    assert result["n_visible_nights"] == 5
