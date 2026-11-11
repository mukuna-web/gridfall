"""The "% darker -> % out" translation curve, the two simple guesses and the lockbox guard (docs/plan.md, Task 6).

Three rules shape everything here:
- "Can't see" never becomes zero. Rows whose status is not "ok" stay out of every fit, and every predictor returns
  NaN for them, so the curve and both simple guesses are scored on exactly the same county-nights.
- EAGLE-I over-counts are dropped, never silently clipped (`apply_overcount_rule`).
- No fit touches a lockbox storm (Helene, Milton) before the pass bar is committed: every fit_* function calls
  `check_no_lockbox` first, and only Task 9's final fit passes `final=True`.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from blackout.storms import Storm, load_storms

TRUTH = "official_pct_out"
OK = "ok"
# Over-count rule (decided 2026-11-08). Above 1.05 a county reads more customers out than MCC says it has: an
# EAGLE-I over-count (Wharton on Uri, Highlands on Ian) or an MCC under-count, so the value is dropped from fitting
# and scoring. Between 1.0 and 1.05 the two sources merely disagree a little, so the value is clipped to 1.0.
OVERCOUNT_DROP = 1.05
FULL_OUTAGE = 1.0
# Below this many calm-night rows an OLS fit of three coefficients is noise, so no correction is applied.
MIN_CORRECTION_ROWS = 10
MAX_ZENITH = 90.0
CORRECTION_COLUMNS = ("pct_darker", "sensor_zenith", "lunar_irradiance")
CALM_COLUMNS = ("storm_id", "night", "status", *CORRECTION_COLUMNS)
FIT_COLUMNS = (*CALM_COLUMNS, "covered", TRUTH)
WIND_COLUMNS = ("storm_id", "status", "pct_darker", "covered", "wind_band", TRUTH)


class LockboxError(Exception):
    """A fit would touch a lockbox storm before the pass bar is committed."""


# --- small helpers -----------------------------------------------------------------------------------------------

def require_columns(df: pd.DataFrame, columns: Iterable[str], what: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{what} needs columns {missing}")


def floats(df: pd.DataFrame, column: str) -> np.ndarray:
    """A numeric column as float64 with NaN for missing, whatever pandas dtype it arrived in."""
    return pd.to_numeric(df[column]).to_numpy(dtype=float, na_value=np.nan)


def bools(df: pd.DataFrame, column: str) -> np.ndarray:
    """A flag column as bool. A missing flag reads False: a county with unknown coverage is not covered."""
    return df[column].astype("boolean").fillna(False).to_numpy(dtype=bool)


def storm_ids(df: pd.DataFrame) -> set:
    require_columns(df, ["storm_id"], "a county x night table")
    return set(df["storm_id"].unique())


def resolve_storms(storms: Iterable[Storm] | None) -> list[Storm]:
    return list(storms) if storms is not None else load_storms()


def nights(df: pd.DataFrame) -> np.ndarray:
    """The night column as datetime64, whether it holds datetime.date (the parquet tables) or timestamps."""
    return pd.to_datetime(df["night"]).to_numpy()


def storm_dates(df: pd.DataFrame, storms: Iterable[Storm], field: str) -> np.ndarray:
    """Each row's own storm's `field` (landfall, baseline_end, window_end) as datetime64; NaT for unknown storms."""
    by_id = {s.id: pd.Timestamp(getattr(s, field)) for s in storms}
    return pd.to_datetime(df["storm_id"].map(by_id)).to_numpy()


def baseline_rows(df: pd.DataFrame, storms: Iterable[Storm]) -> np.ndarray:
    """Calm nights: on or before the row's own storm's baseline_end (Milton's ends before Helene's landfall)."""
    return nights(df) <= storm_dates(df, storms, "baseline_end")


def readable_rows(df: pd.DataFrame) -> np.ndarray:
    """County-nights the satellite gives a reading for: status "ok" and a finite % darker."""
    require_columns(df, ["status", "pct_darker"], "a prediction")
    return (df["status"] == OK).to_numpy(dtype=bool) & np.isfinite(floats(df, "pct_darker"))


def training_rows(cleaned: pd.DataFrame) -> np.ndarray:
    """The rows every fit uses: readable, covered by EAGLE-I, and a usable official % out after the over-count rule."""
    return readable_rows(cleaned) & bools(cleaned, "covered") & np.isfinite(floats(cleaned, TRUTH))


# --- lockbox guard -----------------------------------------------------------------------------------------------

def check_no_lockbox(storm_ids: set[str], storms: list[Storm], final: bool = False) -> None:
    """Raise LockboxError if any id is a lockbox storm, unless this is the final fit (Task 9, after the pass bar)."""
    roles = {s.id: s.role for s in storms}
    unknown = sorted(str(i) for i in storm_ids if i not in roles)
    if unknown:
        raise ValueError(f"unknown storm ids {unknown}: not in the storm list")
    locked = sorted(i for i in storm_ids if roles[i] == "lockbox")
    if locked and not final:
        raise LockboxError(f"{locked} are lockbox storms: no fit may use them until the pass bar is committed "
                           "(only Task 9's final fit passes final=True)")


# --- over-count rule ---------------------------------------------------------------------------------------------

def apply_overcount_rule(df: pd.DataFrame, column: str = TRUTH) -> pd.DataFrame:
    """A copy with `column` cleaned: above 1.05 becomes NaN, (1.0, 1.05] becomes 1.0, and `<column>_overcount`
    marks the dropped rows. An infinite value (a county with zero MCC customers) is an over-count too."""
    require_columns(df, [column], "the over-count rule")
    values = floats(df, column)
    dropped = values > OVERCOUNT_DROP
    cleaned = np.where(dropped, np.nan, np.minimum(values, FULL_OUTAGE))
    return df.assign(**{column: cleaned, f"{column}_overcount": dropped})


def overcount_summary(df: pd.DataFrame, column: str = TRUTH) -> pd.DataFrame:
    """Per storm: county-nights with a value, values clipped to 1.0, and values dropped as over-counts."""
    require_columns(df, ["storm_id", column], "overcount_summary")
    values = floats(df, column)
    flags = pd.DataFrame({
        "storm_id": df["storm_id"].to_numpy(),
        "with_value": ~np.isnan(values),
        "clipped": (values > FULL_OUTAGE) & (values <= OVERCOUNT_DROP),
        "dropped": values > OVERCOUNT_DROP,
    })
    counts = flags.groupby("storm_id", sort=False)[["with_value", "clipped", "dropped"]].sum()
    return counts.astype(int).reset_index()


# --- angle and moon correction -----------------------------------------------------------------------------------

def sec_term(zenith_deg):
    """sec(zenith) - 1: zero looking straight down, growing as the slant path through the air lengthens."""
    return 1.0 / np.cos(np.radians(zenith_deg)) - 1.0


def _sec_column(df: pd.DataFrame) -> np.ndarray:
    """sec_term of the county's median sensor zenith. sec is even, so a zenith signed by scan side reads the same;
    90 degrees or more is not a view angle (an unscaled layer, say) and stops the fit instead of skewing it."""
    zenith = floats(df, "sensor_zenith")
    bad = np.abs(zenith) >= MAX_ZENITH
    if bad.any():
        raise ValueError(f"sensor_zenith must be within ±90 degrees, got {zenith[bad][:5].tolist()}")
    return sec_term(zenith)


def _finite_or_zero(values: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(values), values, 0.0)


@dataclass(frozen=True)
class AngleMoonCorrection:
    """pct_darker ~ intercept + b_sec * (sec(zenith) - 1) + b_moon * lunar_irradiance, fit on calm nights.

    Phase 0 found viewing angle explained most calm-night noise (Spearman -0.87) and moonlit nights read 6-11%
    darker. `apply` removes the two slopes but keeps the intercept, so calm nights stay where calm nights sit.
    """

    intercept: float
    b_sec: float
    b_moon: float
    rows: int

    def apply(self, df: pd.DataFrame) -> np.ndarray:
        """Corrected % darker; a missing angle or moon value contributes 0 rather than hiding the night."""
        require_columns(df, CORRECTION_COLUMNS, "the angle and moon correction")
        sec = _finite_or_zero(_sec_column(df))
        moon = _finite_or_zero(floats(df, "lunar_irradiance"))
        return floats(df, "pct_darker") - (self.b_sec * sec + self.b_moon * moon)

    def as_dict(self) -> dict:
        return {"intercept": self.intercept, "sec": self.b_sec, "moon": self.b_moon, "rows": self.rows}


def fit_angle_moon(train: pd.DataFrame, storms: Iterable[Storm] | None = None,
                   final: bool = False) -> AngleMoonCorrection:
    """OLS on the calm (baseline, status "ok") nights of `train` only, so a held-out storm never tunes it.

    A feature that does not vary on those nights (no moon at all, say) gets slope 0 instead of a slope that would
    only fight the intercept. With fewer than MIN_CORRECTION_ROWS calm rows it warns and applies no correction.
    """
    storms = resolve_storms(storms)
    check_no_lockbox(storm_ids(train), storms, final)
    require_columns(train, CALM_COLUMNS, "fit_angle_moon")
    calm = train[baseline_rows(train, storms) & readable_rows(train)]
    y = floats(calm, "pct_darker")
    features = {"sec": _sec_column(calm), "moon": floats(calm, "lunar_irradiance")}
    usable = np.isfinite(y) & np.isfinite(features["sec"]) & np.isfinite(features["moon"])
    n = int(usable.sum())
    if n < MIN_CORRECTION_ROWS:
        warnings.warn(f"angle and moon correction: {n} calm-night rows with both features (need "
                      f"{MIN_CORRECTION_ROWS}); no correction applied", UserWarning, stacklevel=2)
        return AngleMoonCorrection(0.0, 0.0, 0.0, n)
    varying = {name: x[usable] for name, x in features.items() if np.ptp(x[usable]) > 0}
    design = np.column_stack([np.ones(n), *varying.values()])
    coef = np.linalg.lstsq(design, y[usable], rcond=None)[0]
    slopes = dict(zip(varying, coef[1:]))
    return AngleMoonCorrection(float(coef[0]), float(slopes.get("sec", 0.0)), float(slopes.get("moon", 0.0)), n)


# --- the translation curve ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Translator:
    """The fitted curve from corrected % darker to % out, with the correction it was fit with."""

    curve: IsotonicRegression
    correction: AngleMoonCorrection
    rows: int
    storms: tuple[str, ...]

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Estimated % out; NaN (never 0) where the satellite gives no reading."""
        x = self.correction.apply(df)
        readable = readable_rows(df) & np.isfinite(x)
        out = np.full(len(df), np.nan)
        if readable.any():
            out[readable] = self.curve.predict(x[readable])
        return out

    @property
    def curve_points(self) -> tuple[np.ndarray, np.ndarray]:
        """The curve's breakpoints (corrected % darker, % out), for the docs; it is linear between them."""
        return np.array(self.curve.X_thresholds_, dtype=float), np.array(self.curve.y_thresholds_, dtype=float)


def fit_translation(train: pd.DataFrame, storms: Iterable[Storm] | None = None, final: bool = False) -> Translator:
    """Isotonic curve from corrected % darker to the cleaned official % out.

    Monotone because a darker county should never be estimated as less out; clipped to [0, 1] because % out is a
    share. Fit on rows that are "ok", covered and have a usable official % out (`training_rows`).
    """
    storms = resolve_storms(storms)
    ids = storm_ids(train)
    check_no_lockbox(ids, storms, final)
    require_columns(train, FIT_COLUMNS, "fit_translation")
    correction = fit_angle_moon(train, storms, final)
    cleaned = apply_overcount_rule(train)
    rows = training_rows(cleaned)
    if not rows.any():
        raise ValueError("fit_translation: no rows with status 'ok', covered and a usable official_pct_out")
    curve = IsotonicRegression(increasing=True, out_of_bounds="clip", y_min=0.0, y_max=1.0)
    curve.fit(correction.apply(cleaned)[rows], floats(cleaned, TRUTH)[rows])
    return Translator(curve, correction, int(rows.sum()), tuple(sorted(ids)))


# --- simple guesses ----------------------------------------------------------------------------------------------

def _wind_training(train: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    cleaned = apply_overcount_rule(train)
    rows = training_rows(cleaned)
    if not rows.any():
        raise ValueError("fit_wind_only: no rows with status 'ok', covered and a usable official_pct_out")
    bands = floats(cleaned, "wind_band")[rows]
    if not np.isfinite(bands).all():
        # Cast to int, a missing band becomes an arbitrary one (0 on some machines) and quietly joins its mean.
        raise ValueError(f"fit_wind_only: {int((~np.isfinite(bands)).sum())} training rows have no wind_band")
    return bands.astype(int), floats(cleaned, TRUTH)[rows]


def fit_wind_only(train: pd.DataFrame, storms: Iterable[Storm] | None = None, final: bool = False) -> dict[int, float]:
    """The guess to beat: mean cleaned official % out per wind band, over the same rows as fit_translation."""
    storms = resolve_storms(storms)
    check_no_lockbox(storm_ids(train), storms, final)
    require_columns(train, WIND_COLUMNS, "fit_wind_only")
    bands, truth = _wind_training(train)
    means = pd.Series(truth).groupby(bands).mean()
    return {int(band): float(mean) for band, mean in means.items()}


@dataclass(frozen=True)
class WindOnly:
    """Predicts the training mean for the row's wind band, or the overall mean for a band it never saw (Uri's -1).

    `WindOnly.fit` passes the row-weighted training mean as `overall`. Built from the band means alone, as final.py
    does with `WindOnly(fit_wind_only(...))`, the row counts are unknown, so `overall` falls back to the plain mean
    of the band means.
    """

    means: dict[int, float]
    overall: float | None = None

    def __post_init__(self) -> None:
        if not self.means:
            raise ValueError("WindOnly needs at least one wind band mean")
        if self.overall is None:  # frozen, so set once while the object is still being built
            object.__setattr__(self, "overall", float(np.mean(list(self.means.values()))))

    @classmethod
    def fit(cls, train: pd.DataFrame, storms: Iterable[Storm] | None = None, final: bool = False) -> WindOnly:
        means = fit_wind_only(train, storms, final)
        return cls(means, float(_wind_training(train)[1].mean()))

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """NaN where the satellite gives no reading, so it is scored on the same rows as the curve."""
        require_columns(df, ["wind_band"], "WindOnly.predict")
        guess = pd.Series(floats(df, "wind_band")).map(self.means).fillna(self.overall).to_numpy(dtype=float)
        return np.where(readable_rows(df), guess, np.nan)


def predict_nothing(df: pd.DataFrame) -> np.ndarray:
    """The "nothing happened" guess: 0% out, NaN where the satellite gives no reading (same rows as the curve)."""
    return np.where(readable_rows(df), 0.0, np.nan)


@dataclass(frozen=True)
class Nothing:
    """predict_nothing behind the same .predict interface as the other two methods."""

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return predict_nothing(df)


def fit_nothing(train: pd.DataFrame, storms: Iterable[Storm] | None = None, final: bool = False) -> Nothing:
    """Learns nothing, but still guards the lockbox like every other fit."""
    check_no_lockbox(storm_ids(train), resolve_storms(storms), final)
    return Nothing()


# --- noise report ------------------------------------------------------------------------------------------------

def _sd(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1)) if len(values) >= 2 and np.isfinite(values).all() else float("nan")


def _noise_stats(raw: np.ndarray, in_sample: np.ndarray, held_out: np.ndarray) -> dict:
    return {"rows": len(raw), "raw_sd": _sd(raw), "in_sample_sd": _sd(in_sample), "loso_sd": _sd(held_out)}


def _held_out_correction(main: pd.DataFrame, calm: pd.DataFrame, main_ids: list[str],
                         storms: list[Storm]) -> np.ndarray:
    out = np.full(len(calm), np.nan)
    if len(main_ids) < 2:
        return out
    ids = calm["storm_id"].to_numpy()
    for storm_id in main_ids:
        held = ids == storm_id
        fold = fit_angle_moon(main[main["storm_id"] != storm_id], storms)
        out[held] = fold.apply(calm[held])
    return out


def noise_report(df: pd.DataFrame, storms: Iterable[Storm] | None = None) -> dict:
    """sd of % darker on calm "ok" nights: raw, corrected in-sample, and corrected leave-one-storm-out.

    A correction judged on the nights it was fit on flatters itself, so each main storm is also corrected with
    coefficients fit on the other main storms only. Main storms only; sd uses ddof=1.
    """
    storms = resolve_storms(storms)
    present = storm_ids(df)
    check_no_lockbox(present, storms)
    require_columns(df, CALM_COLUMNS, "noise_report")
    main_ids = [s.id for s in storms if s.role == "main" and s.id in present]
    main = df[df["storm_id"].isin(main_ids)]
    calm = main[baseline_rows(main, storms) & readable_rows(main)]
    raw = floats(calm, "pct_darker")
    correction = fit_angle_moon(main, storms)
    in_sample = correction.apply(calm)
    held_out = _held_out_correction(main, calm, main_ids, storms)
    ids = calm["storm_id"].to_numpy()
    per_storm = {sid: _noise_stats(raw[ids == sid], in_sample[ids == sid], held_out[ids == sid]) for sid in main_ids}
    return {"storms": main_ids, **_noise_stats(raw, in_sample, held_out), "coefficients": correction.as_dict(),
            "per_storm": per_storm}
