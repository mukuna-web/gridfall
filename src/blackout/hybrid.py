"""The hybrid estimator: satellite darkening plus storm context (decision log, 2026-11-08, "Model choice").

The isotonic curve (model.py) maps % darker to % out over every county-night, and most of those are calm nights where
noise, not outages, makes a county read dark. So even strong darkening in a county the storm just hit is averaged
down to a few percent: on the first five main storms it estimated 16% of the official peak. Wind band and days since
landfall set the prior that the satellite should update. This model learns % out from both, with gradient-boosted
trees constrained to rise with darkening and wind band. A county's darkening is also scaled by its own calm-night
noise (Lee's 0.76 is a seven-sigma night; a dim rural county's is not).

`fit_wind_timing` is the same model without any satellite input: the honest test of what the satellite adds.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from blackout.model import (
    TRUTH,
    AngleMoonCorrection,
    apply_overcount_rule,
    check_no_lockbox,
    fit_angle_moon,
    readable_rows,
    resolve_storms,
    storm_ids,
    training_rows,
)
from blackout.storms import Storm

MIN_CALM_NIGHTS = 5
SD_FLOOR = 0.05
SD_FALLBACK = 0.3
DAYS_CLIP = (-40, 25)
# early_stopping is off: sklearn's default would hold out a random 10% of county-nights from the same storms,
# which makes the fit depend on the seed and the batch (decision log, "Model choice").
TREE_PARAMS = {"max_iter": 300, "learning_rate": 0.05, "min_samples_leaf": 40, "l2_regularization": 1.0,
               "random_state": 0, "early_stopping": False}
SATELLITE = ("z", "darker", "log_sd")
CONTEXT = ("wind_band", "days")
AUXILIARY = ("log_base_total", "lunar_irradiance", "sensor_zenith", "visible_share")
RISING = {"z", "darker", "wind_band"}  # % out never falls as these grow


def _days_since_landfall(df: pd.DataFrame, storms: list[Storm]) -> np.ndarray:
    landfall = {s.id: pd.Timestamp(s.landfall) for s in storms}
    unknown = set(df["storm_id"]) - set(landfall)
    if unknown:
        raise ValueError(f"no storm record for {sorted(unknown)}")
    days = (pd.to_datetime(df["night"]) - df["storm_id"].map(landfall)).dt.days.to_numpy(dtype=float)
    return np.clip(days, *DAYS_CLIP)


def county_noise(df: pd.DataFrame, correction: AngleMoonCorrection, storms: Iterable[Storm]) -> tuple[np.ndarray,
                                                                                                      np.ndarray]:
    """(z, sd): each county's corrected darkening scaled by its own spread on that storm's calm nights.

    Uses only baseline nights with status ok, never official counts, so it is known at prediction time. A county with
    fewer than MIN_CALM_NIGHTS calm readings takes the median spread of counties of similar brightness in its storm.
    """
    storms = resolve_storms(storms)
    baseline_end = {s.id: pd.Timestamp(s.baseline_end) for s in storms}
    x = correction.apply(df)
    calm = ((pd.to_datetime(df["night"]) <= df["storm_id"].map(baseline_end)).to_numpy()
            & np.asarray(readable_rows(df)) & np.isfinite(x))
    frame = pd.DataFrame({"storm_id": df["storm_id"].to_numpy(), "fips": df["fips"].to_numpy(), "x": x,
                          "calm": calm, "brightness": np.log1p(df["base_total"].clip(lower=0)).to_numpy()})
    readable_storms = set(frame.loc[np.asarray(readable_rows(df)), "storm_id"])
    without_calm = sorted(readable_storms - set(frame.loc[frame["calm"], "storm_id"]))
    if without_calm:
        raise ValueError(f"no calm baseline nights for {without_calm}: pass each storm's whole table, baseline "
                         "nights included, so every county's own noise can be measured")
    stats = frame[frame["calm"]].groupby(["storm_id", "fips"])["x"].agg(["mean", "std", "count"])
    frame = frame.join(stats, on=["storm_id", "fips"])
    enough = frame["count"].fillna(0).to_numpy() >= MIN_CALM_NIGHTS
    frame["band"] = frame.groupby("storm_id")["brightness"].transform(
        lambda v: pd.qcut(v.rank(method="first"), 5, labels=False, duplicates="drop") if v.notna().any() else v)
    typical = frame[enough].groupby(["storm_id", "band"])["std"].median().rename("typical")
    fallback = frame.join(typical, on=["storm_id", "band"])["typical"].to_numpy()
    sd = np.where(enough, frame["std"].to_numpy(), fallback)
    sd = np.maximum(np.where(np.isfinite(sd), sd, SD_FALLBACK), SD_FLOOR)
    centre = np.where(enough, frame["mean"].to_numpy(), 0.0)
    return (x - centre) / sd, sd


def _features(df: pd.DataFrame, correction: AngleMoonCorrection, storms: list[Storm], satellite: bool) -> pd.DataFrame:
    columns = {"wind_band": df["wind_band"].clip(lower=0).to_numpy(dtype=float),
               "days": _days_since_landfall(df, storms)}
    if satellite:
        z, sd = county_noise(df, correction, storms)
        columns = {"z": z, "darker": correction.apply(df), "log_sd": np.log(sd), **columns,
                   "log_base_total": np.log1p(df["base_total"].clip(lower=0)).to_numpy(dtype=float),
                   "lunar_irradiance": df["lunar_irradiance"].to_numpy(dtype=float),
                   "sensor_zenith": df["sensor_zenith"].to_numpy(dtype=float),
                   "visible_share": df["visible_share"].to_numpy(dtype=float)}
    return pd.DataFrame(columns)


@dataclass(frozen=True)
class HybridModel:
    """Fitted trees plus what they need at prediction time. `satellite=False` is the wind-and-timing baseline."""

    trees: HistGradientBoostingRegressor
    correction: AngleMoonCorrection
    fill: dict[str, float]
    storms: tuple[Storm, ...]
    satellite: bool
    rows: int

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Estimated % out in [0, 1]; NaN (never 0) where the satellite gives no reading, as for every method."""
        features = _features(df, self.correction, list(self.storms), self.satellite).fillna(self.fill)
        pred = np.clip(self.trees.predict(features), 0.0, 1.0)
        readable = np.asarray(readable_rows(df)) & np.isfinite(df["pct_darker"].to_numpy(dtype=float))
        return np.where(readable, pred, np.nan)


def _fit(train: pd.DataFrame, storms: Iterable[Storm] | None, final: bool, satellite: bool) -> HybridModel:
    storms = resolve_storms(storms)
    check_no_lockbox(storm_ids(train), storms, final)
    correction = fit_angle_moon(train, storms, final)
    cleaned = apply_overcount_rule(train)
    rows = np.asarray(training_rows(cleaned)) & np.isfinite(cleaned["pct_darker"].to_numpy(dtype=float))
    if not rows.any():
        raise ValueError("no rows with status 'ok', covered and a usable official_pct_out to fit on")
    features = _features(cleaned, correction, storms, satellite)[rows]
    fill = {name: float(np.nanmedian(features[name])) if features[name].notna().any() else 0.0
            for name in features.columns}
    features = features.fillna(fill)
    trees = HistGradientBoostingRegressor(monotonic_cst=[1 if name in RISING else 0 for name in features.columns],
                                          **TREE_PARAMS)
    trees.fit(features, cleaned[TRUTH].to_numpy(dtype=float)[rows])
    return HybridModel(trees, correction, fill, tuple(storms), satellite, int(rows.sum()))


def fit_hybrid(train: pd.DataFrame, storms: Iterable[Storm] | None = None, final: bool = False) -> HybridModel:
    """% out from corrected darkening, the county's calm-night noise, wind band and days since landfall."""
    return _fit(train, storms, final, satellite=True)


def fit_wind_timing(train: pd.DataFrame, storms: Iterable[Storm] | None = None, final: bool = False) -> HybridModel:
    """The same trees on wind band and days since landfall only: what a model with no satellite can do."""
    return _fit(train, storms, final, satellite=False)
