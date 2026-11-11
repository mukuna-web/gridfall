"""Task 8: error ranges, restoration intervals and hour brackets (docs/plan.md, Week 5).

Synthetic data only. "Can't see" must never act as zero, so several fixtures give cant_see and not_measurable
nights an est of 0.0 on purpose: code that skips the status check would read those nights as restored.
"""

import math
import pickle
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from blackout.model import LockboxError
from blackout.ranges import MIN_BIN_ROWS, RangeModel, fit_ranges, pct_out_bracket, restoration_interval
from blackout.storms import get_storm

LANDFALL = date(2022, 9, 28)
SEED = 20261108
NAN = math.nan


def synthetic_preds(n: int, rng: np.random.Generator, spread=lambda p: 0.03 + 0.12 * p) -> pd.DataFrame:
    """LOSO-style predictions with a small under-prediction bias and misses whose size depends on the prediction."""
    pred = rng.uniform(0.0, 1.0, n)
    truth = np.clip(pred + rng.normal(0.03, spread(pred)), 0.0, 1.0)
    return pd.DataFrame({"pred_pct_out": pred, "official_pct_out": truth})


def share_inside(model: RangeModel, frame: pd.DataFrame) -> float:
    lo, hi = model.interval(frame["pred_pct_out"].to_numpy())
    truth = frame["official_pct_out"].to_numpy()
    return float(np.mean((truth >= lo) & (truth <= hi)))


def toy_preds() -> pd.DataFrame:
    """Predictions 0.000-0.495: five quantile bins of 20 rows; bin b's misses are (b + 1)(k - 10)/200 for k = 0-19.

    np.quantile's linear rule then gives a 10th percentile of -0.0405(b + 1) and a 90th of 0.0355(b + 1), and the
    edges are the 20/40/60/80% quantiles of the predictions: 0.099, 0.198, 0.297 and 0.396. Every truth stays at or
    below 0.72, so the over-count rule (which only touches values above 1.0) never changes the toy.
    """
    pred = np.arange(100) / 200
    b, k = np.divmod(np.arange(100), 20)
    return pd.DataFrame({"pred_pct_out": pred, "official_pct_out": pred + (b + 1) * (k - 10) / 200})


def assert_same_model(a: RangeModel, b: RangeModel) -> None:
    assert a.counts == b.counts
    for name in ("edges", "lo_offsets", "hi_offsets"):
        assert getattr(a, name) == pytest.approx(getattr(b, name))


def county(*rows, fips: str = "12071") -> pd.DataFrame:
    """One county's nights from (day after landfall, status, est) rows."""
    return pd.DataFrame({
        "fips": fips,
        "night": [LANDFALL + timedelta(days=day) for day, _, _ in rows],
        "status": [status for _, status, _ in rows],
        "est": [float(est) for _, _, est in rows],
    })


def passes(nights: pd.DataFrame, hour: float = 7 + 10 / 60) -> pd.DataFrame:
    """Give each night a pass at `hour` UTC on the morning after it (its file date), as the table's pass_utc does."""
    when = [pd.Timestamp(night, tz="UTC") + pd.Timedelta(days=1, hours=hour) for night in nights["night"]]
    return nights.assign(pass_utc=when)


# --- fit_ranges ------------------------------------------------------------------------------------------------

def test_range_coverage():
    rng = np.random.default_rng(SEED)
    model = fit_ranges(synthetic_preds(2_000, rng))
    assert 0.70 <= share_inside(model, synthetic_preds(1_000, rng)) <= 0.90


def test_range_coverage_holds_in_each_bin():
    """Tight misses below 0.5 and wide ones above: one global range would cover ~100% and ~50%; bins give ~80% each."""
    def spread(p):
        return np.where(p < 0.5, 0.01, 0.15)

    rng = np.random.default_rng(SEED)
    model = fit_ranges(synthetic_preds(2_000, rng, spread))
    fresh = synthetic_preds(2_000, rng, spread)
    assert 0.70 <= share_inside(model, fresh[fresh["pred_pct_out"] < 0.4]) <= 0.90
    assert 0.70 <= share_inside(model, fresh[fresh["pred_pct_out"] >= 0.6]) <= 0.90


def test_bins_are_prediction_quantiles_with_per_bin_percentiles():
    model = fit_ranges(toy_preds())
    assert model.edges == pytest.approx((0.099, 0.198, 0.297, 0.396))
    assert model.counts == (20, 20, 20, 20, 20)
    assert model.lo_offsets == pytest.approx(tuple(-0.0405 * (b + 1) for b in range(5)))
    assert model.hi_offsets == pytest.approx(tuple(0.0355 * (b + 1) for b in range(5)))
    assert model.interval(0.25) == pytest.approx((0.1285, 0.3565))


def test_interval_clips_to_unit_range_and_takes_arrays():
    model = fit_ranges(toy_preds())
    assert model.interval(0.01) == pytest.approx((0.0, 0.0455))  # 0.01 - 0.0405 clips to 0
    assert model.interval(0.95) == pytest.approx((0.7475, 1.0))  # 0.95 + 0.1775 clips to 1
    lo, hi = model.interval(np.array([[0.01, 0.25], [0.95, 0.15]]))
    assert lo.shape == hi.shape == (2, 2)
    np.testing.assert_allclose(lo, [[0.0, 0.1285], [0.7475, 0.069]])
    np.testing.assert_allclose(hi, [[0.0455, 0.3565], [1.0, 0.221]])


def test_interval_nan_in_nan_out():
    model = fit_ranges(toy_preds())
    lo, hi = model.interval(NAN)
    assert isinstance(lo, float) and math.isnan(lo) and math.isnan(hi)
    lo, hi = model.interval(pd.Series([0.25, NAN, math.inf, None], dtype="Float64"))
    np.testing.assert_allclose(lo, [0.1285, NAN, NAN, NAN])  # a non-finite prediction has no range, never 0 or 1
    np.testing.assert_allclose(hi, [0.3565, NAN, NAN, NAN])


def test_small_bins_merge_into_a_neighbour():
    frame = synthetic_preds(60, np.random.default_rng(SEED))
    model = fit_ranges(frame)  # five quantile bins of 12 rows: 12+12 -> 24, then 12+12 -> 24, then 24+12 -> 36
    assert model.counts == (24, 36)
    assert model.edges == pytest.approx((np.quantile(frame["pred_pct_out"], 0.4),))
    assert min(model.counts) >= MIN_BIN_ROWS


def test_too_few_rows_make_one_bin():
    frame = pd.DataFrame({"pred_pct_out": [0.1, 0.2, 0.3, 0.6, 0.9], "official_pct_out": [0.1, 0.3, 0.2, 0.7, 1.0]})
    model = fit_ranges(frame)
    assert model.edges == () and model.counts == (5,)
    assert model.lo_offsets == pytest.approx((-0.06,))  # misses -0.1, 0, 0.1, 0.1, 0.1
    assert model.hi_offsets == pytest.approx((0.1,))


def test_tied_predictions_share_a_bin():
    """An isotonic curve is a step function: rows sharing one prediction must land in one bin."""
    rng = np.random.default_rng(SEED)
    pred = np.concatenate([np.zeros(300), np.full(150, 0.35), rng.uniform(0.4, 1.0, 150)])
    truth = np.clip(pred + rng.normal(0.0, 0.05, 600), 0.0, 1.0)
    model = fit_ranges(pd.DataFrame({"pred_pct_out": pred, "official_pct_out": truth}))
    # quantile edges 0, 0, 0.35 and one inside the spread: the empty bin below 0 merges away
    assert model.counts == (300, 180, 120)
    assert model.edges[0] == pytest.approx(0.35)
    assert model.interval(0.0) == pytest.approx((0.0, np.quantile(truth[:300], 0.9)))


def test_fit_uses_only_measured_covered_finite_rows():
    clean = synthetic_preds(500, np.random.default_rng(SEED)).assign(status="ok", covered=True)
    junk = pd.DataFrame({
        "pred_pct_out": [0.5, NAN, 0.5, 0.5, 0.5, math.inf],
        "official_pct_out": [NAN, 0.5, 0.0, 0.0, 0.0, 0.5],
        "status": ["ok", "ok", "cant_see", "not_measurable", "ok", "ok"],
        "covered": [True, True, True, True, False, True],
    })
    mixed = pd.concat([clean, junk], ignore_index=True).sample(frac=1, random_state=1)
    assert_same_model(fit_ranges(mixed), fit_ranges(clean))


def test_overcounts_follow_the_curve_rule():
    """Decision log 2026-11-08 (model.apply_overcount_rule): an official % out above 1.05 is dropped from every fit,
    and one in (1.0, 1.05] counts as 1.0. loso() output still holds the raw EAGLE-I values, so fit_ranges must
    clean them itself, or over-counts (Highlands on Ian, Louisiana on Ida) would widen every range above them."""
    truth = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.00]
    base = pd.DataFrame({"pred_pct_out": 0.5, "official_pct_out": truth})
    model = fit_ranges(base)
    assert model.counts == (10,) and model.hi_offsets == pytest.approx((0.32,))  # misses ..., 0.3, 0.5
    clipped = base.assign(official_pct_out=[*truth[:-1], 1.04])
    before = clipped.copy(deep=True)
    assert_same_model(fit_ranges(clipped), model)  # left unclipped, 1.04 would make the 90th percentile 0.324
    pd.testing.assert_frame_equal(clipped, before)  # cleaned in a copy, never in the caller's frame
    overcounts = pd.DataFrame({"pred_pct_out": 0.5, "official_pct_out": [1.06, 1.5, math.inf]})
    assert_same_model(fit_ranges(pd.concat([base, overcounts], ignore_index=True)), model)  # kept: 0.554


def test_fit_custom_columns_leaves_input_alone():
    frame = toy_preds().rename(columns={"pred_pct_out": "p", "official_pct_out": "y"})
    before = frame.copy(deep=True)
    model = fit_ranges(frame, pred_col="p", truth_col="y")
    pd.testing.assert_frame_equal(frame, before)
    assert model.counts == (20,) * 5


def test_fit_rejects_bad_input():
    with pytest.raises(ValueError, match="n_bins"):
        fit_ranges(toy_preds(), n_bins=0)
    with pytest.raises(ValueError, match="pred_pct_out"):
        fit_ranges(toy_preds().drop(columns="pred_pct_out"))
    with pytest.raises(ValueError, match="no rows"):
        fit_ranges(toy_preds().assign(official_pct_out=NAN))


def test_lockbox_rows_refused_unless_final():
    """Review Focus 5: like every fit_*, fit_ranges calls model.check_no_lockbox first, on every row it is given."""
    lockbox = toy_preds().assign(storm_id="milton2024")
    with pytest.raises(LockboxError):
        fit_ranges(lockbox)
    assert fit_ranges(lockbox, final=True).counts == (20,) * 5
    unpredicted = pd.concat([toy_preds().assign(storm_id="ian2022"), lockbox.assign(pred_pct_out=NAN)])
    with pytest.raises(LockboxError):
        fit_ranges(unpredicted)  # the guard runs before any filter, so even rows that would be skipped refuse
    with pytest.raises(ValueError, match="nosuch2030"):
        fit_ranges(toy_preds().assign(storm_id="nosuch2030"))  # an unknown storm is an error, not a pass
    toy_storm = replace(get_storm("ian2022"), id="toy2022")
    assert fit_ranges(toy_preds().assign(storm_id="toy2022"), storms=[toy_storm]).counts == (20,) * 5


def test_range_model_pickles_and_prints():
    model = fit_ranges(toy_preds())
    again = pickle.loads(pickle.dumps(model))
    assert again == model and again.interval(0.5) == model.interval(0.5)
    table = model.to_frame()
    assert list(table.columns) == ["pred_from", "pred_to", "rows", "lo_offset", "hi_offset"]
    assert table["pred_from"].iloc[0] == -math.inf and table["pred_to"].iloc[-1] == math.inf
    assert table["rows"].tolist() == [20] * 5


def test_range_model_rejects_inconsistent_parts():
    with pytest.raises(ValueError):
        RangeModel(edges=(0.5,), lo_offsets=(-0.1,), hi_offsets=(0.1,), counts=(20,))
    with pytest.raises(ValueError):
        RangeModel(edges=(0.5, 0.4), lo_offsets=(-0.1,) * 3, hi_offsets=(0.1,) * 3, counts=(20,) * 3)
    with pytest.raises(ValueError):
        RangeModel(edges=(), lo_offsets=(0.2,), hi_offsets=(0.1,), counts=(20,))


# --- restoration_interval --------------------------------------------------------------------------------------

def test_interval_brackets_truth_with_cloud_gaps():
    truth = {0: 0.80, 1: 0.65, 2: 0.50, 3: 0.32, 4: 0.18, 5: 0.08, 6: 0.04, 7: 0.02}
    true_day = min(day for day, out in truth.items() if out <= 0.10)  # day 5, behind the clouds
    nights = county(
        (-2, "not_measurable", 0.0), (-1, "ok", 0.03),
        (0, "ok", 0.78), (1, "ok", 0.66), (2, "cant_see", NAN), (3, "ok", 0.30),
        (4, "cant_see", 0.0), (5, "cant_see", 0.0),  # clouds: an est of 0 here must not read as restored
        (6, "ok", 0.05), (7, "ok", 0.02),
    ).sample(frac=1, random_state=3)
    before = nights.copy(deep=True)
    lo, hi = restoration_interval(nights, LANDFALL)
    assert (lo, hi) == (3.0, 6.0)
    assert lo <= true_day <= hi
    pd.testing.assert_frame_equal(nights, before)


def test_never_restored_open_interval():
    nights = county(*[(day, "ok", 0.9 - 0.07 * day) for day in range(9)],
                    (9, "cant_see", 0.0), (10, "not_measurable", 0.0))
    assert restoration_interval(nights, LANDFALL) == (8.0, None)


def test_never_out_is_zero_zero():
    nights = county((-1, "ok", 0.6), (0, "ok", 0.10), (1, "ok", 0.04), (2, "cant_see", NAN), (3, "ok", 0.0))
    assert restoration_interval(nights, LANDFALL) == (0.0, 0.0)  # exactly 0.10 already counts as back


def test_unseen_landfall_nights_are_not_never_out():
    """Clouds on nights 0-2, then 4% out: back by day 3 at the latest, but nights 0-2 can't be called zero."""
    nights = county((0, "cant_see", 0.0), (1, "cant_see", NAN), (2, "not_measurable", 0.0), (3, "ok", 0.04))
    assert restoration_interval(nights, LANDFALL) == (0.0, 3.0)


def test_never_seen_after_landfall_is_unknown():
    nights = county((-3, "ok", 0.0), (-1, "ok", 0.02), (0, "cant_see", 0.0), (1, "ok", NAN), (2, "cant_see", 0.0))
    lo, hi = restoration_interval(nights, LANDFALL)
    assert math.isnan(lo) and math.isnan(hi)


def test_restoration_ignores_nights_before_landfall():
    nights = county((-2, "ok", 0.6), (-1, "ok", 0.05), (0, "ok", 0.7), (1, "ok", 0.4), (2, "ok", 0.09))
    assert restoration_interval(nights, LANDFALL) == (1.0, 2.0)


def test_first_night_back_ends_the_interval():
    nights = county((0, "ok", 0.6), (1, "ok", NAN), (2, "ok", 0.08), (3, "ok", 0.3), (4, "ok", 0.02))
    assert restoration_interval(nights, LANDFALL) == (0.0, 2.0)  # the ok night with no est is skipped
    assert restoration_interval(nights, LANDFALL, threshold=0.05) == (3.0, 4.0)


@pytest.mark.parametrize("threshold", [10, -0.1, NAN])
def test_restoration_rejects_bad_threshold(threshold):
    with pytest.raises(ValueError, match="threshold"):
        restoration_interval(county((0, "ok", 0.5), (1, "ok", 0.05)), LANDFALL, threshold=threshold)


@pytest.mark.parametrize("call", [
    lambda frame: restoration_interval(frame, LANDFALL),
    lambda frame: pct_out_bracket(frame, LANDFALL, 72),
])
def test_one_county_with_one_row_per_night(call):
    nights = county((0, "ok", 0.5), (1, "ok", 0.05))
    with pytest.raises(ValueError, match="one county"):
        call(pd.concat([nights, nights.assign(fips="12015")]))
    with pytest.raises(ValueError, match="twice"):
        call(pd.concat([nights, nights]))
    with pytest.raises(ValueError, match="est"):
        call(nights.drop(columns="est"))
    with pytest.raises(ValueError, match="no night"):
        call(nights.assign(night=[LANDFALL, None]))


# --- pct_out_bracket -------------------------------------------------------------------------------------------

def test_bracket_from_the_nights_either_side():
    nights = passes(county((-1, "ok", 0.02), (0, "ok", 0.70), (1, "ok", 0.50), (2, "cant_see", 0.0), (3, "ok", 0.30)))
    assert pct_out_bracket(nights, LANDFALL, 24) == (0.02, 0.70)  # the look before the storm, then the first after
    assert pct_out_bracket(nights, LANDFALL, 48) == (0.50, 0.70)
    assert pct_out_bracket(nights, LANDFALL, 72) == (0.30, 0.50)  # night 2 is cloudy, so night 3 is the next look


def test_bracket_none_when_blind():
    cloudy_after = passes(county((0, "ok", 0.7), (1, "ok", 0.5), (2, "cant_see", 0.0), (3, "not_measurable", 0.0),
                                 (4, "ok", NAN)))
    assert pct_out_bracket(cloudy_after, LANDFALL, 72) is None
    cloudy_before = passes(county((-1, "cant_see", 0.0), (0, "cant_see", 0.0), (1, "ok", 0.4)))
    assert pct_out_bracket(cloudy_before, LANDFALL, 24) is None
    assert pct_out_bracket(cloudy_before.iloc[0:0], LANDFALL, 24) is None


def test_bracket_reads_pass_utc_and_falls_back_to_0700():
    nights = county((-1, "ok", 0.05), (0, "ok", 0.60), (1, "ok", 0.45))
    # no pass_utc: night 0 passes at 07:00 UTC on Sep 29, exactly the target, and "at or after" includes it
    assert pct_out_bracket(nights, LANDFALL, 31) == (0.05, 0.60)
    # a 06:30 pass puts night 0 before the target, so night 1 becomes the next look
    early = passes(nights, hour=6.5)
    assert pct_out_bracket(early, LANDFALL, 31) == (0.45, 0.60)
    # a missing pass time falls back to 07:00 UTC for that night only, and a naive time reads as UTC
    mixed = early.assign(pass_utc=pd.Series([early["pass_utc"][0], pd.NaT, early["pass_utc"][2].tz_localize(None)],
                                            dtype=object))
    assert pct_out_bracket(mixed, LANDFALL, 31) == (0.05, 0.60)


def test_bracket_rejects_bad_hours_and_leaves_input_alone():
    nights = passes(county((0, "ok", 0.6), (1, "ok", 0.4)))
    before = nights.copy(deep=True)
    with pytest.raises(ValueError, match="hours"):
        pct_out_bracket(nights, LANDFALL, -24)
    with pytest.raises(ValueError, match="hours"):
        pct_out_bracket(nights, LANDFALL, NAN)
    assert pct_out_bracket(nights, LANDFALL, 48) == (0.4, 0.6)
    pd.testing.assert_frame_equal(nights, before)


def test_bracket_counts_hours_from_the_landfall_time():
    from blackout.ranges import pct_out_bracket

    nights = pd.DataFrame({"night": [date(2022, 9, 28), date(2022, 9, 29), date(2022, 9, 30)],
                           "status": ["ok", "ok", "ok"], "est": [0.6, 0.4, 0.2],
                           "pass_utc": pd.to_datetime(["2022-09-29 07:00", "2022-09-30 07:00", "2022-10-01 07:00"],
                                                      utc=True)})
    landfall = pd.Timestamp("2022-09-28 19:05", tz="UTC")
    # 24 h after 19:05 is 09-29 19:05: between the 09-29 07:00 and 09-30 07:00 passes
    assert pct_out_bracket(nights, landfall, 24) == (0.4, 0.6)
    # counted from midnight it would fall between the first two passes too, but 36 h moves to the next pair
    assert pct_out_bracket(nights, landfall, 36) == (0.2, 0.4)
