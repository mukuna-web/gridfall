"""The baseline and the per-night sums: % darker, visible share and status."""

import datetime as dt

import numpy as np
import pytest
from phase0_fakes import ian


def filled(value, like: np.ndarray, dtype) -> np.ndarray:
    return np.broadcast_to(np.asarray(value, dtype=dtype), like.shape).copy()


def night(radiance, quality=0, cloud=0, snow=0, day=dt.date(2022, 9, 1)) -> "ian.NightPixels":
    radiance = np.asarray(radiance, dtype=np.float64)
    return ian.NightPixels(day, radiance, filled(quality, radiance, np.uint8), filled(cloud, radiance, np.uint8),
                           filled(snow, radiance, np.uint8))


def test_baseline_needs_at_least_five_clear_nights():
    four = [night([10.0, 20.0]) for _ in range(4)]
    cloudy = [night([99.0, 99.0], cloud=3) for _ in range(3)]  # cloudy nights do not count
    median, clear_nights = ian.baseline_median(four + cloudy)
    assert clear_nights.tolist() == [4, 4] and np.isnan(median).all()
    median, clear_nights = ian.baseline_median(four + cloudy + [night([12.0, 22.0], cloud=[0, 3])])
    assert clear_nights.tolist() == [5, 4]
    assert median[0] == 10.0 and np.isnan(median[1])


def test_baseline_without_any_file_fails_fast():
    with pytest.raises(ian.InputError, match="no baseline"):
        ian.baseline_median([])


def test_same_pixel_rule():
    baseline = np.array([10.0, 10.0, np.nan, 10.0])
    radiance = np.array([2.0, 50.0, 7.0, 4.0])
    clear = np.array([True, False, True, True])  # pixel 1 is cloudy; pixel 2 is clear but has no baseline
    metrics = ian.night_metrics(radiance, clear, baseline)
    assert (metrics["tonight"], metrics["base_visible"], metrics["base_total"]) == (6.0, 20.0, 30.0)
    assert metrics["pct_darker"] == pytest.approx(0.7)
    assert metrics["visible_share"] == pytest.approx(2 / 3)
    assert (metrics["status"], metrics["n_seen_pixels"]) == ("ok", 2)


def test_all_cloudy_night_is_cant_see():
    cloudy = night([1.0, 2.0, 3.0], cloud=3)
    metrics = ian.night_metrics(cloudy.radiance, ian.clear_mask(cloudy), np.array([10.0, 10.0, 10.0]))
    assert metrics["status"] == "cant_see"
    assert np.isnan(metrics["pct_darker"]) and metrics["visible_share"] == 0.0


def test_no_baseline_light_is_not_measurable():
    no_baseline = ian.night_metrics(np.array([1.0]), np.array([True]), np.array([np.nan]))
    dark = ian.night_metrics(np.array([0.0]), np.array([True]), np.array([0.0]))
    for metrics in (no_baseline, dark):
        assert metrics["status"] == "not_measurable"
        assert np.isnan(metrics["pct_darker"]) and np.isnan(metrics["visible_share"])


def test_visible_share_of_exactly_half_is_ok():
    radiance, clear = np.array([5.0, 5.0]), np.array([True, False])
    assert ian.night_metrics(radiance, clear, np.array([10.0, 10.0]))["status"] == "ok"
    assert ian.night_metrics(radiance, clear, np.array([10.0, 10.5]))["status"] == "cant_see"


def test_brighter_than_baseline_gives_a_negative_pct_darker():
    metrics = ian.night_metrics(np.array([15.0]), np.array([True]), np.array([10.0]))
    assert metrics["pct_darker"] == pytest.approx(-0.5)


def test_sums_are_float64():
    radiance = np.array([2.0**24, 1.0], dtype=np.float32)  # float32 cannot hold 2**24 + 1
    metrics = ian.night_metrics(radiance, np.array([True, True]), radiance.copy())
    assert metrics["tonight"] == 2.0**24 + 1
