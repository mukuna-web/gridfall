"""Error ranges, restoration intervals and hour brackets (Task 8, docs/plan.md Week 5).

The app needs more than one number per county:
- `fit_ranges` learns how wrong the curve was on held-out storms, separately for each band of predicted % out, so
  every estimate carries a range: the middle 80% of past misses (design.md section 6, "Range").
- `restoration_interval` turns a county's nights into "back to 10% or less between day 4 and day 6" when clouds
  hide the nights in between (design.md section 6, "Duration").
- `pct_out_bracket` brackets % out at hour 24, 48 or 72 between the satellite's looks either side of that hour,
  for the portfolio example's waiting periods.

"Can't see" is never zero (Review Focus 4): only `status == "ok"` nights with a finite estimate count, and a county
the satellite never saw comes back as unknown (NaN or None), not as 0. `fit_ranges` follows the curve's own rules
from model.py: the lockbox guard runs first (Review Focus 5), and EAGLE-I over-counts get the same over-count rule.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from blackout.model import apply_overcount_rule, check_no_lockbox
from blackout.storms import Storm, load_storms

MIN_BIN_ROWS = 20  # below this, a bin's 10th and 90th percentiles are mostly noise
RANGE_QUANTILES = (0.1, 0.9)  # the middle 80% of past misses
FALLBACK_PASS = pd.Timedelta(days=1, hours=7)  # night N's pass is about 07:00 UTC on file date N + 1 in Florida
NIGHT_COLUMNS = ("night", "status", "est")


@dataclass(frozen=True)
class RangeModel:
    """Offsets that turn a predicted % out into a range, one pair per bin of predictions.

    Bin b holds predictions in [edges[b - 1], edges[b]); the first and last bins run to -inf and +inf, so a
    prediction outside the training range takes the nearest bin's offsets. `lo_offsets` and `hi_offsets` are the
    10th and 90th percentiles of (official - predicted) in each bin, and `counts` its training rows. Every field is
    a plain tuple, so the model pickles and prints as it is (`to_frame` lays it out for the docs).
    """

    edges: tuple[float, ...]
    lo_offsets: tuple[float, ...]
    hi_offsets: tuple[float, ...]
    counts: tuple[int, ...]

    def __post_init__(self) -> None:
        bins = len(self.edges) + 1
        if not len(self.lo_offsets) == len(self.hi_offsets) == len(self.counts) == bins:
            raise ValueError(f"{len(self.edges)} edges need {bins} offsets and counts each, got "
                             f"{len(self.lo_offsets)}, {len(self.hi_offsets)} and {len(self.counts)}")
        if any(upper <= lower for lower, upper in zip(self.edges, self.edges[1:])):
            raise ValueError(f"edges must rise strictly, got {self.edges}")
        if any(lo > hi for lo, hi in zip(self.lo_offsets, self.hi_offsets)):
            raise ValueError("a bin's lo offset can't exceed its hi offset")

    def interval(self, pred) -> tuple[float, float] | tuple[np.ndarray, np.ndarray]:
        """(lo, hi) for a prediction: pred plus its bin's offsets, clipped to [0, 1].

        A scalar gives two floats; an array, list or Series gives two arrays of its shape. A non-finite prediction
        (NaN, NA, inf) gives NaN: a county with no estimate has no range, never a range at 0 or 1.
        """
        p = _float_values(pred)
        bins = _bin_index(self.edges, p)
        finite = np.isfinite(p)
        lo = np.where(finite, np.clip(p + np.asarray(self.lo_offsets)[bins], 0.0, 1.0), np.nan)
        hi = np.where(finite, np.clip(p + np.asarray(self.hi_offsets)[bins], 0.0, 1.0), np.nan)
        if p.ndim == 0:
            return float(lo), float(hi)
        return lo, hi

    def to_frame(self) -> pd.DataFrame:
        """One row per bin, for docs/scorecard.md: the predictions it covers, its rows and its offsets."""
        bounds = (-math.inf, *self.edges, math.inf)
        return pd.DataFrame({"pred_from": bounds[:-1], "pred_to": bounds[1:], "rows": self.counts,
                             "lo_offset": self.lo_offsets, "hi_offset": self.hi_offsets})


def fit_ranges(loso_preds: pd.DataFrame, n_bins: int = 5, pred_col: str = "pred_pct_out",
               truth_col: str = "official_pct_out", *, storms: Iterable[Storm] | None = None,
               final: bool = False) -> RangeModel:
    """Learn ranges from held-out predictions: the 10th and 90th percentiles of (truth - pred) in each bin.

    Why bins: the curve's misses depend on its level (tight near 0% out, wide in the middle), so one global range
    would be too wide for quiet counties and too narrow for hard-hit ones. Bins are quantiles of the prediction, so
    each starts with about the same rows; tied quantiles collapse, so a flat step of the isotonic curve never
    straddles an edge, and a bin under MIN_BIN_ROWS rows merges into its smaller neighbour (one bin at the least).

    Rows count when pred and truth are both finite and, where the columns exist, `status == "ok"` and `covered`:
    the rows `fit_translation` trains on, after the same over-count rule (`model.apply_overcount_rule`: above 1.05
    is dropped, (1.0, 1.05] counts as 1.0). loso() output still holds raw EAGLE-I values, so the rule runs here;
    running it twice changes nothing. A can't-see row never enters a range, and an under-covered state's official
    count is not a miss. Pass loso() output, never in-sample predictions, or the ranges come out too narrow.

    Like every fit_*, this calls `model.check_no_lockbox` first, on every storm_id it is given (`storms` defaults to
    config/storms.yaml): rows from a lockbox storm raise LockboxError unless `final=True` (Task 9, after the
    pass-bar commit).
    """
    if "storm_id" in loso_preds.columns:
        known = list(storms) if storms is not None else load_storms()
        check_no_lockbox(set(loso_preds["storm_id"].unique()), known, final)
    if isinstance(n_bins, bool) or not isinstance(n_bins, (int, np.integer)) or n_bins < 1:
        raise ValueError(f"n_bins must be a whole number of at least 1, got {n_bins!r}")
    pred, truth = _range_rows(loso_preds, pred_col, truth_col)
    edges = _merge_small_bins(_quantile_edges(pred, n_bins), pred)
    bins = _bin_index(edges, pred)
    misses = truth - pred
    offsets = [np.quantile(misses[bins == b], RANGE_QUANTILES) for b in range(len(edges) + 1)]
    return RangeModel(
        edges=tuple(float(edge) for edge in edges),
        lo_offsets=tuple(float(lo) for lo, _ in offsets),
        hi_offsets=tuple(float(hi) for _, hi in offsets),
        counts=tuple(int(count) for count in np.bincount(bins, minlength=len(edges) + 1)),
    )


def restoration_interval(county_nights: pd.DataFrame, landfall: date,
                         threshold: float = 0.10) -> tuple[float, float | None]:
    """When the county got back to `threshold` or less, as (lo, hi) days after landfall.

    `county_nights` holds one county: columns night, status and est (estimated fraction out). Only ok nights on or
    after landfall with a finite est count, so a cloudy night is a gap, never a "restored" night.
    - Out, then back: hi is the first counted night at or below the threshold after the first one above it, and lo
      the counted night just before hi (still above it). Clouds in between are why it's an interval.
    - Out and never back: (last counted night, None), an open interval.
    - Never seen above the threshold: (0.0, first counted night), which is (0.0, 0.0) when the landfall night was
      seen. Unseen early nights can't be called zero, so the county was back by that night, not "never out".
    - No counted night at all: (NaN, NaN), unknown.
    """
    if not (np.isfinite(threshold) and 0.0 <= threshold <= 1.0):
        raise ValueError(f"threshold is a fraction of customers out, in [0, 1], got {threshold!r}")
    seen = _seen_nights(county_nights)
    day = (seen["night"] - pd.Timestamp(landfall)).dt.days.astype(float)
    counted = pd.DataFrame({"day": day, "est": seen["est"]})[day >= 0].sort_values("day")
    if counted.empty:
        return math.nan, math.nan
    days = counted["day"].to_numpy()
    out = counted["est"].to_numpy() > threshold
    if not out.any():
        return 0.0, float(days[0])
    first_out = int(np.argmax(out))
    back = np.flatnonzero(~out[first_out:])
    if back.size == 0:
        return float(days[-1]), None
    hi = first_out + int(back[0])
    return float(days[hi - 1]), float(days[hi])


def _start_time(landfall: date | pd.Timestamp) -> pd.Timestamp:
    """A tz-aware landfall time is used as it is; a plain date means 00:00 UTC that day."""
    if isinstance(landfall, pd.Timestamp) and landfall.tzinfo is not None:
        return landfall.tz_convert("UTC")
    return pd.Timestamp(landfall, tz="UTC")


def pct_out_bracket(county_nights: pd.DataFrame, landfall: date | pd.Timestamp,
                    hours: int) -> tuple[float, float] | None:
    """The estimated fraction out at landfall + `hours` (Storm.landfall_time, or 00:00 UTC for a plain date),
    bracketed by the satellite's looks either side.

    One look is the first ok night whose pass is at or after that time, the other the last ok night before it;
    the bracket is (min, max) of their estimates, so it holds whether power was going out or coming back. Pass
    times come from `pass_utc` (a naive time reads as UTC), else 07:00 UTC the day after the night. None when
    either side has no ok night: the satellite can't see, and that is not zero.
    """
    if not np.isfinite(hours) or hours < 0:
        raise ValueError(f"hours must be a finite number of hours after landfall, at least 0, got {hours!r}")
    seen = _seen_nights(county_nights)
    looks = pd.DataFrame({"when": _pass_times(seen), "est": seen["est"]})
    target = _start_time(landfall) + pd.Timedelta(hours=float(hours))
    after = looks[looks["when"] >= target]
    before = looks[looks["when"] < target]
    if after.empty or before.empty:
        return None
    low = after.loc[after["when"].idxmin(), "est"]
    high = before.loc[before["when"].idxmax(), "est"]
    return float(min(low, high)), float(max(low, high))


# --- helpers -----------------------------------------------------------------------------------------------------

def _float_values(values) -> np.ndarray:
    """A scalar, list, array or Series as float64, with pandas' NA as NaN (never as 0)."""
    if isinstance(values, (pd.Series, pd.Index, pd.api.extensions.ExtensionArray)):
        return values.to_numpy(dtype=float, na_value=np.nan)
    if np.ndim(values) == 0 and pd.isna(values):
        return np.array(np.nan)
    return np.asarray(values, dtype=float)


def _bin_index(edges, values: np.ndarray) -> np.ndarray:
    """Each value's bin; a value on an edge goes to the bin above, so tied predictions never split."""
    return np.searchsorted(np.asarray(edges, dtype=float), values, side="right")


def _range_rows(loso_preds: pd.DataFrame, pred_col: str, truth_col: str) -> tuple[np.ndarray, np.ndarray]:
    """Predictions and truths of the rows a range may learn from (see fit_ranges), as new arrays."""
    missing = [col for col in (pred_col, truth_col) if col not in loso_preds.columns]
    if missing:
        raise ValueError(f"loso_preds has no column(s) {missing}")
    used = [col for col in (pred_col, truth_col, "status", "covered") if col in loso_preds.columns]
    cleaned = apply_overcount_rule(loso_preds[used], truth_col)  # a new, narrow frame: the caller's stays as it was
    pred = _float_values(cleaned[pred_col])
    truth = _float_values(cleaned[truth_col])
    keep = np.isfinite(pred) & np.isfinite(truth)
    if "status" in cleaned.columns:
        keep = keep & cleaned["status"].eq("ok").to_numpy(dtype=bool, na_value=False)
    if "covered" in cleaned.columns:
        keep = keep & cleaned["covered"].to_numpy(dtype=bool, na_value=False)
    if not keep.any():
        raise ValueError(f"no rows with a finite {pred_col} and {truth_col} (status ok, covered, not an over-count) "
                         "to learn ranges from")
    return pred[keep], truth[keep]


def _quantile_edges(pred: np.ndarray, n_bins: int) -> np.ndarray:
    """Inner edges at the predictions' 1/n_bins quantiles, with ties collapsed to one edge."""
    return np.unique(np.quantile(pred, np.linspace(0.0, 1.0, n_bins + 1)[1:-1]))


def _merge_small_bins(edges: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Merge the smallest bin under MIN_BIN_ROWS rows into its smaller neighbour until every bin is big enough."""
    kept = tuple(float(edge) for edge in edges)
    counts = tuple(int(count) for count in np.bincount(_bin_index(kept, pred), minlength=len(kept) + 1))
    while len(counts) > 1 and min(counts) < MIN_BIN_ROWS:
        left = _pair_to_merge(counts, counts.index(min(counts)))
        counts = counts[:left] + (counts[left] + counts[left + 1],) + counts[left + 2:]
        kept = kept[:left] + kept[left + 1:]
    return np.asarray(kept, dtype=float)


def _pair_to_merge(counts: tuple[int, ...], small: int) -> int:
    """Left index of the two bins to merge: `small` and its smaller neighbour (the left one on a tie)."""
    if small == 0:
        return 0
    if small == len(counts) - 1 or counts[small - 1] <= counts[small + 1]:
        return small - 1
    return small


def _seen_nights(county_nights: pd.DataFrame) -> pd.DataFrame:
    """The nights the satellite measured (status ok, finite est), as a new frame with `night` as datetime64."""
    _check_one_county(county_nights)
    est = _float_values(county_nights["est"])
    seen = county_nights["status"].eq("ok").to_numpy(dtype=bool, na_value=False) & np.isfinite(est)
    rows = county_nights.loc[seen].reset_index(drop=True)
    return rows.assign(night=pd.to_datetime(rows["night"]), est=est[seen])


def _check_one_county(county_nights: pd.DataFrame) -> None:
    """One county, one row per night: a whole storm table passed by mistake would mix counties silently."""
    missing = [col for col in NIGHT_COLUMNS if col not in county_nights.columns]
    if missing:
        raise ValueError(f"county_nights has no column(s) {missing}")
    if "fips" in county_nights.columns and county_nights["fips"].nunique() > 1:
        raise ValueError(f"county_nights must hold one county, got {sorted(county_nights['fips'].astype(str).unique())}")
    nights = pd.to_datetime(county_nights["night"])
    if nights.isna().any():
        raise ValueError(f"county_nights has {int(nights.isna().sum())} row(s) with no night")
    if nights.duplicated().any():
        twice = sorted({str(night.date()) for night in nights[nights.duplicated()]})
        raise ValueError(f"county_nights lists night(s) {twice} twice; pass one county and one satellite")


def _pass_times(nights: pd.DataFrame) -> pd.Series:
    """Each night's pass in UTC: pass_utc where known (naive reads as UTC), else 07:00 UTC the next day."""
    fallback = (nights["night"] + FALLBACK_PASS).dt.tz_localize("UTC")
    if "pass_utc" not in nights.columns:
        return fallback
    return pd.to_datetime(nights["pass_utc"], utc=True).fillna(fallback)
