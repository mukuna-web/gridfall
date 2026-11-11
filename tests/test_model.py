"""Task 6: the translation curve, the two simple guesses, the angle and moon correction, the over-count rule and the
lockbox guard (docs/plan.md, Week 4). Every table here is synthetic: no storm data is read."""

import pickle
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from blackout.model import (
    LockboxError,
    Translator,
    WindOnly,
    apply_overcount_rule,
    check_no_lockbox,
    fit_angle_moon,
    fit_nothing,
    fit_translation,
    fit_wind_only,
    noise_report,
    overcount_summary,
    predict_nothing,
    sec_term,
)
from blackout.storms import Storm, get_storm, load_storms

ANGLE, MOON, CALM = 0.30, 0.10, 0.02  # slopes and intercept the synthetic calm nights are built with
COUNTIES = 8
BASELINE_NIGHTS = 31  # baseline_start .. baseline_end, both included


def make_storm(storm_id: str, role: str = "main", landfall: date = date(2022, 9, 28)) -> Storm:
    baseline_end = landfall - timedelta(days=3)
    return Storm(storm_id, storm_id, None, landfall, baseline_end - timedelta(days=30), baseline_end,
                 landfall + timedelta(days=21), role, ("FL",))


STORMS = [
    make_storm("aaa2018", landfall=date(2018, 9, 14)),
    make_storm("bbb2020", landfall=date(2020, 8, 27)),
    make_storm("ccc2022"),
    make_storm("box2024", role="lockbox", landfall=date(2024, 10, 9)),
    make_storm("sss2021", role="stress", landfall=date(2021, 2, 15)),
]
BY_ID = {s.id: s for s in STORMS}


def row(storm_id="ccc2022", night=date(2022, 9, 29), fips="12001", pct_darker=0.0, truth=0.0, status="ok",
        covered=True, wind_band=64, zenith=0.0, moon=0.0) -> dict:
    return {"storm_id": storm_id, "fips": fips, "night": night, "status": status, "pct_darker": pct_darker,
            "sensor_zenith": zenith, "lunar_irradiance": moon, "official_pct_out": truth, "customers": 1000.0,
            "wind_band": wind_band, "covered": covered}


def storm_table(storm: Storm, seed: int, moon_share: float = 0.4) -> pd.DataFrame:
    """Every night of `storm` for 8 counties. Calm nights are pure angle and moon noise around CALM; after landfall
    % out decays from up to 0.9 and % darker tracks it, on top of the same angle and moon terms."""
    rng = np.random.default_rng(seed)
    records = []
    for night in storm.nights:
        day = (night - storm.landfall).days
        for k in range(COUNTIES):
            zenith = rng.uniform(0, 65)
            moon = rng.uniform(0, 1) if rng.random() < moon_share else 0.0
            out = 0.9 * np.exp(-day / 4) * (k + 1) / COUNTIES if day >= 0 else 0.0
            darker = CALM + ANGLE * sec_term(zenith) + MOON * moon + 0.8 * out + rng.normal(0, 0.01)
            records.append(row(storm.id, night, f"12{2 * k + 1:03d}", darker, out, zenith=zenith, moon=moon,
                               wind_band=(64, 50, 34, 0)[k % 4]))
    return pd.DataFrame(records)


def grid(values, zenith=30.0, moon=0.2) -> pd.DataFrame:
    return pd.DataFrame([row(pct_darker=v, zenith=zenith, moon=moon) for v in values])


def calm_nights(table: pd.DataFrame, storm: Storm) -> pd.DataFrame:
    return table[pd.to_datetime(table["night"]) <= pd.Timestamp(storm.baseline_end)]


# --- lockbox guard -----------------------------------------------------------------------------------------------

def test_lockbox_guard_raises():
    storms = load_storms()
    t = pd.concat([storm_table(get_storm("ian2022"), seed=1), storm_table(get_storm("milton2024"), seed=2)],
                  ignore_index=True)
    for fit in (fit_translation, fit_wind_only, fit_nothing, fit_angle_moon, WindOnly.fit, noise_report):
        with pytest.raises(LockboxError):
            fit(t)
    assert isinstance(fit_translation(t, final=True), Translator)
    assert set(fit_wind_only(t, final=True)) == {0, 34, 50, 64}
    check_no_lockbox({"ian2022", "uri2021"}, storms)
    with pytest.raises(LockboxError):
        check_no_lockbox({"ian2022", "helene2024"}, storms)
    check_no_lockbox({"helene2024", "milton2024"}, storms, final=True)
    with pytest.raises(ValueError, match="nosuch2030"):
        check_no_lockbox({"nosuch2030"}, storms)


# --- over-count rule ---------------------------------------------------------------------------------------------

def test_overcount_rule_drops_above_105_and_clips_the_rest():
    df = pd.DataFrame({"storm_id": ["aaa2018"] * 6 + ["bbb2020"] * 2,
                       "official_pct_out": [0.5, 1.0, 1.02, 1.05, 1.06, 2.0, np.nan, np.inf]})
    before = df.copy()
    out = apply_overcount_rule(df)
    np.testing.assert_array_equal(out["official_pct_out"], [0.5, 1.0, 1.0, 1.0, np.nan, np.nan, np.nan, np.nan])
    assert out["official_pct_out_overcount"].tolist() == [False, False, False, False, True, True, False, True]
    pd.testing.assert_frame_equal(df, before)  # a new frame; the input is untouched
    renamed = df.rename(columns={"official_pct_out": "official_pct_out_30"})
    assert apply_overcount_rule(renamed, "official_pct_out_30")["official_pct_out_30_overcount"].sum() == 3
    summary = overcount_summary(df).set_index("storm_id")
    assert summary.loc["aaa2018"].tolist() == [6, 2, 2]  # with a value, clipped to 1.0, dropped
    assert summary.loc["bbb2020"].tolist() == [1, 0, 1]  # an infinite % out (no MCC customers) is dropped too


# --- angle and moon correction -----------------------------------------------------------------------------------

def test_angle_moon_correction_recovers_known_slope():
    storm = BY_ID["ccc2022"]
    train = storm_table(storm, seed=5)
    rng = np.random.default_rng(6)
    # Storm nights with the opposite angle dependence, and a cloudy calm night: neither may enter the correction.
    decoys = pd.DataFrame([row(storm.id, storm.landfall + timedelta(days=int(d)), "12201", 0.9 - 0.5 * sec_term(z),
                               0.5, zenith=z) for d, z in zip(rng.integers(0, 22, 300), rng.uniform(0, 65, 300))])
    blind = pd.DataFrame([row(storm.id, storm.baseline_end, "12203", 5.0, 0.0, status="cant_see", zenith=60.0,
                              moon=1.0)])
    t = pd.concat([train, decoys, blind], ignore_index=True)
    c = fit_translation(t, storms=STORMS).correction
    assert c == fit_angle_moon(t, storms=STORMS)
    assert c.b_sec == pytest.approx(ANGLE, abs=0.01)
    assert c.b_moon == pytest.approx(MOON, abs=0.01)
    assert c.intercept == pytest.approx(CALM, abs=0.01)
    assert c.rows == BASELINE_NIGHTS * COUNTIES
    calm = calm_nights(train, storm)
    corrected = c.apply(calm)
    assert corrected.std() < calm["pct_darker"].std() / 5
    assert corrected.mean() == pytest.approx(CALM, abs=0.005)  # the intercept is kept
    missing_angle = pd.DataFrame([row(pct_darker=0.5, zenith=np.nan, moon=0.2)])
    assert c.apply(missing_angle)[0] == pytest.approx(0.5 - c.b_moon * 0.2)  # a NaN feature contributes 0


def test_correction_without_moonlight_keeps_the_angle_slope():
    c = fit_angle_moon(storm_table(BY_ID["ccc2022"], seed=7, moon_share=0.0), storms=STORMS)
    assert c.b_moon == 0.0
    assert c.b_sec == pytest.approx(ANGLE, abs=0.01)


def test_zenith_must_be_a_view_angle():
    c = fit_angle_moon(storm_table(BY_ID["ccc2022"], seed=13), storms=STORMS)
    corrected = c.apply(pd.DataFrame([row(pct_darker=0.5, zenith=-30.0), row(pct_darker=0.5, zenith=30.0)]))
    assert corrected[0] == pytest.approx(corrected[1])  # sec is even: a zenith signed by scan side reads the same
    with pytest.raises(ValueError, match="zenith"):
        c.apply(pd.DataFrame([row(zenith=4500.0)]))  # an unscaled layer is not a view angle


def test_correction_without_calm_nights_warns_and_changes_nothing():
    storm = BY_ID["ccc2022"]
    t = storm_table(storm, seed=8)
    storm_nights = t[pd.to_datetime(t["night"]) >= pd.Timestamp(storm.landfall)]
    with pytest.warns(UserWarning, match="calm"):
        c = fit_angle_moon(storm_nights, storms=STORMS)
    assert (c.intercept, c.b_sec, c.b_moon, c.rows) == (0.0, 0.0, 0.0, 0)
    np.testing.assert_array_equal(c.apply(storm_nights), storm_nights["pct_darker"].to_numpy())


def test_noise_report_in_sample_and_leave_one_out():
    mains = [storm_table(s, seed=10 + i) for i, s in enumerate(STORMS[:3])]
    stress = storm_table(BY_ID["sss2021"], seed=20).assign(pct_darker=9.0)  # not a main storm: never used
    t = pd.concat([*mains, stress], ignore_index=True)
    r = noise_report(t, STORMS)
    assert r["storms"] == ["aaa2018", "bbb2020", "ccc2022"]
    assert r["rows"] == 3 * BASELINE_NIGHTS * COUNTIES
    assert r["raw_sd"] > 5 * r["in_sample_sd"]
    assert r["loso_sd"] == pytest.approx(r["in_sample_sd"], rel=0.25)
    assert r["coefficients"]["sec"] == pytest.approx(ANGLE, abs=0.01)
    assert set(r["per_storm"]) == set(r["storms"])
    assert all(v["rows"] == BASELINE_NIGHTS * COUNTIES for v in r["per_storm"].values())
    single = noise_report(mains[0], STORMS)
    assert single["storms"] == ["aaa2018"] and np.isnan(single["loso_sd"])
    with pytest.raises(LockboxError):
        noise_report(pd.concat([t, storm_table(BY_ID["box2024"], seed=21)], ignore_index=True), STORMS)


# --- the translation curve ---------------------------------------------------------------------------------------

def test_monotone():
    train = pd.concat([storm_table(s, seed=i) for i, s in enumerate(STORMS[:3])], ignore_index=True)
    pred = fit_translation(train, storms=STORMS).predict(grid(np.linspace(-0.3, 1.3, 161)))
    assert np.isfinite(pred).all()
    assert np.all(np.diff(pred) >= 0)
    assert pred.min() >= 0 and pred.max() <= 1
    assert pred[0] < 0.1 and pred[-1] > 0.5  # it learned something: very dark means mostly out


def test_cant_see_not_trained():
    train = storm_table(BY_ID["ccc2022"], seed=3)
    # Finite % darker on purpose, so only the status keeps these rows out (a calm night among them).
    blind = [(date(2022, 9, 29), "cant_see"), (date(2022, 9, 30), "not_measurable"), (date(2022, 9, 10), "cant_see")]

    def with_blind(truth: float, darker: float) -> pd.DataFrame:
        rows = [row(night=n, fips="12099", pct_darker=darker, truth=truth, status=s, zenith=50.0) for n, s in blind]
        return pd.concat([train, pd.DataFrame(rows)], ignore_index=True)

    a, b = with_blind(0.0, 0.9), with_blind(1.0, 5.0)
    g = grid(np.linspace(-0.2, 1.0, 61))
    fit_a, fit_b = fit_translation(a, storms=STORMS), fit_translation(b, storms=STORMS)
    np.testing.assert_array_equal(fit_a.predict(g), fit_b.predict(g))
    assert fit_a.correction == fit_b.correction
    assert np.isnan(fit_a.predict(a[a["status"] != "ok"])).all()  # can't see is NaN, never 0


def test_only_covered_rows_with_usable_truth_are_trained():
    train = storm_table(BY_ID["ccc2022"], seed=4)

    def with_extras(uncovered: float, overcount: float, clipped: float) -> pd.DataFrame:
        night = date(2022, 9, 29)
        extras = [row(night=night, fips="12101", pct_darker=0.6, truth=uncovered, covered=False),
                  row(night=night, fips="12103", pct_darker=0.6, truth=np.nan),
                  row(night=night, fips="12105", pct_darker=0.6, truth=overcount),
                  row(night=night, fips="12107", pct_darker=0.6, truth=clipped)]
        return pd.concat([train, pd.DataFrame(extras)], ignore_index=True)

    a = fit_translation(with_extras(0.0, 1.3, 1.03), storms=STORMS)
    b = fit_translation(with_extras(1.0, 7.0, 1.0), storms=STORMS)
    assert a.rows == len(train) + 1  # only the clipped row joins
    g = grid(np.linspace(-0.2, 1.0, 61))
    np.testing.assert_array_equal(a.predict(g), b.predict(g))


def test_fit_needs_trainable_rows():
    uncovered = storm_table(BY_ID["ccc2022"], seed=9).assign(covered=False)
    with pytest.raises(ValueError, match="no rows"):
        fit_translation(uncovered, storms=STORMS)
    with pytest.raises(ValueError, match="no rows"):
        fit_wind_only(uncovered, storms=STORMS)


def test_translator_pickles_and_exposes_its_curve():
    tr = fit_translation(storm_table(BY_ID["aaa2018"], seed=11), storms=STORMS)
    g = grid(np.linspace(-0.2, 1.0, 25))
    np.testing.assert_array_equal(pickle.loads(pickle.dumps(tr)).predict(g), tr.predict(g))
    x, y = tr.curve_points
    assert len(x) == len(y) >= 2
    assert np.all(np.diff(x) > 0) and np.all(np.diff(y) >= 0)
    assert y.min() >= 0 and y.max() <= 1
    assert tr.storms == ("aaa2018",)


# --- simple guesses ----------------------------------------------------------------------------------------------

def wind_toy() -> pd.DataFrame:
    return pd.DataFrame([
        row(wind_band=64, truth=0.6), row(wind_band=64, truth=1.0),
        row(wind_band=64, truth=0.0, status="cant_see", pct_darker=np.nan),
        row(wind_band=64, truth=0.0, covered=False),
        row(wind_band=64, truth=np.nan),
        row(wind_band=64, truth=1.4),  # over-count: dropped
        row(wind_band=50, truth=1.03), row(wind_band=50, truth=0.5),  # 1.03 is clipped to 1.0
        row(wind_band=34, truth=0.1), row(wind_band=34, truth=0.3),
    ])


def test_wind_only_means():
    means = fit_wind_only(wind_toy(), storms=STORMS)
    assert means[64] == pytest.approx(0.8)
    assert means == pytest.approx({64: 0.8, 50: 0.75, 34: 0.2})


def test_wind_only_predictor():
    model = WindOnly.fit(wind_toy(), storms=STORMS)
    assert model.overall == pytest.approx((0.6 + 1.0 + 1.0 + 0.5 + 0.1 + 0.3) / 6)
    new = pd.DataFrame([row(wind_band=64), row(wind_band=34), row(wind_band=0),
                        row(wind_band=64, status="cant_see", pct_darker=np.nan)])
    pred = model.predict(new)
    np.testing.assert_allclose(pred[:3], [0.8, 0.2, model.overall])  # an unseen band gets the overall mean
    assert np.isnan(pred[3])


def test_wind_only_from_band_means_alone():
    """final.py builds WindOnly(fit_wind_only(...)) without the row counts, so an unseen band (Uri's -1) gets the
    plain mean of the band means; WindOnly.fit passes the row-weighted training mean instead."""
    model = WindOnly({64: 0.8, 34: 0.2})
    assert model.overall == pytest.approx(0.5)
    pred = model.predict(pd.DataFrame([row(wind_band=64), row(wind_band=-1),
                                       row(wind_band=64, status="cant_see", pct_darker=np.nan)]))
    np.testing.assert_allclose(pred[:2], [0.8, 0.5])
    assert np.isnan(pred[2])
    with pytest.raises(ValueError, match="band"):
        WindOnly({})


def test_wind_only_needs_a_band_on_every_training_row():
    """A missing wind band would be cast to an arbitrary integer band (0 on this Mac), so it stops the fit. A missing
    band on a row that is never trained on (can't see) changes nothing."""
    t = wind_toy()
    first, blind = np.arange(len(t)) == 0, (t["status"] != "ok").to_numpy()
    with pytest.raises(ValueError, match="wind_band"):
        fit_wind_only(t.assign(wind_band=np.where(first, np.nan, t["wind_band"])), storms=STORMS)
    untrained = t.assign(wind_band=np.where(blind, np.nan, t["wind_band"]))
    assert fit_wind_only(untrained, storms=STORMS) == pytest.approx(fit_wind_only(t, storms=STORMS))


def test_predict_nothing_only_where_the_satellite_sees():
    df = pd.DataFrame([row(), row(status="cant_see", pct_darker=np.nan),
                       row(status="not_measurable", pct_darker=np.nan), row(pct_darker=np.nan)])
    pred = predict_nothing(df)
    assert pred[0] == 0.0 and np.isnan(pred[1:]).all()
    np.testing.assert_array_equal(fit_nothing(df, storms=STORMS).predict(df), pred)
    # All three methods are scored on exactly the same rows.
    assert np.isnan(WindOnly({64: 0.5}, 0.5).predict(df)[1:]).all()
    tr = fit_translation(storm_table(BY_ID["aaa2018"], seed=12), storms=STORMS)
    assert np.isnan(tr.predict(df)[1:]).all() and np.isfinite(tr.predict(df)[0])
