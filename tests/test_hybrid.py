"""The hybrid model (satellite + wind band + timing) and the wind-and-timing baseline (decision log, 2026-11-08)."""

import itertools
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from blackout.hybrid import county_noise, fit_hybrid, fit_wind_timing
from blackout.model import LockboxError, fit_angle_moon
from blackout.storms import Storm


def storm(sid: str, landfall: date, role: str = "main") -> Storm:
    return Storm(id=sid, name=sid, atcf_id=None, landfall=landfall, baseline_start=landfall - timedelta(days=12),
                 baseline_end=landfall - timedelta(days=3), window_end=landfall + timedelta(days=6), role=role,
                 states=("FL",))


STORMS = [storm("a2020", date(2020, 9, 10)), storm("b2021", date(2021, 9, 10)),
          storm("lock2024", date(2024, 9, 10), role="lockbox")]


def world(sid: str, seed: int, counties: int = 30) -> pd.DataFrame:
    """A storm where hit counties (band 64) lose power for 3 nights after landfall and go dark in proportion;
    calm nights carry noise. The truth depends only on darkening and context, so a sound model should find it."""
    rng = np.random.default_rng(seed)
    s = next(x for x in STORMS if x.id == sid)
    rows = []
    for c in range(counties):
        band = 64 if c < counties // 2 else 0
        for night in s.nights:
            day = (night - s.landfall).days
            out = 0.6 * (band == 64) * (0 <= day <= 2)
            darker = out + rng.normal(0, 0.08)
            rows.append({"storm_id": sid, "fips": f"12{c:03d}", "night": night, "status": "ok", "covered": True,
                         "pct_darker": darker, "sensor_zenith": 20.0, "lunar_irradiance": 0.5,
                         "visible_share": 0.95, "base_total": 50_000.0, "wind_band": band,
                         "official_pct_out": out})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def train() -> pd.DataFrame:
    return pd.concat([world("a2020", 1), world("b2021", 2)], ignore_index=True)


def test_hybrid_learns_outages_and_stays_near_zero_on_calm_nights(train):
    model = fit_hybrid(train, STORMS)
    test = world("b2021", 3)
    pred = model.predict(test)
    day = (pd.to_datetime(test["night"]) - pd.Timestamp(date(2021, 9, 10))).dt.days
    hit = (test["wind_band"] == 64) & day.between(0, 2)
    assert pred[hit.to_numpy()].mean() == pytest.approx(0.6, abs=0.1)
    assert pred[~hit.to_numpy()].mean() < 0.05


def test_hybrid_is_monotone_in_darkening(train):
    model = fit_hybrid(train, STORMS)
    row = world("b2021", 4).iloc[[0]]
    preds = [model.predict(row.assign(pct_darker=d, wind_band=64))[0] for d in np.linspace(-0.3, 1.0, 14)]
    assert all(b >= a - 1e-12 for a, b in itertools.pairwise(preds))


def test_cant_see_rows_give_nan_and_are_not_trained(train):
    model = fit_hybrid(train, STORMS)
    blind = world("b2021", 5).assign(status="cant_see")
    assert np.isnan(model.predict(blind)).all()
    poisoned = train.copy()
    poisoned.loc[poisoned.index[:50], "status"] = "cant_see"
    poisoned.loc[poisoned.index[:50], "official_pct_out"] = 1.0
    again = fit_hybrid(poisoned.assign(status=poisoned["status"]), STORMS)
    clean = fit_hybrid(train.drop(index=train.index[:50]), STORMS)
    probe = world("b2021", 6)
    assert np.allclose(again.predict(probe), clean.predict(probe))


def test_lockbox_guard(train):
    locked = pd.concat([train, world("lock2024", 7)], ignore_index=True)
    with pytest.raises(LockboxError):
        fit_hybrid(locked, STORMS)
    with pytest.raises(LockboxError):
        fit_wind_timing(locked, STORMS)
    fit_hybrid(locked, STORMS, final=True)


def test_wind_timing_ignores_the_satellite(train):
    model = fit_wind_timing(train, STORMS)
    test = world("b2021", 8)
    a = model.predict(test)
    b = model.predict(test.assign(pct_darker=test["pct_darker"] + 0.5))
    assert np.allclose(a, b)


def test_county_noise_uses_only_calm_nights_and_no_truth(train):
    correction = fit_angle_moon(train, STORMS)
    z1, sd1 = county_noise(train, correction, STORMS)
    z2, sd2 = county_noise(train.assign(official_pct_out=0.0), correction, STORMS)
    assert np.allclose(z1, z2) and np.allclose(sd1, sd2)
    assert np.all(sd1 >= 0.05)


def test_predict_refuses_a_batch_without_baseline_nights(train):
    model = fit_hybrid(train, STORMS)
    event_only = world("b2021", 10)
    event_only = event_only[event_only["night"] >= date(2021, 9, 10)]
    with pytest.raises(ValueError, match="calm baseline nights"):
        model.predict(event_only)


def test_deterministic(train):
    probe = world("b2021", 9)
    assert np.array_equal(fit_hybrid(train, STORMS).predict(probe), fit_hybrid(train, STORMS).predict(probe))
