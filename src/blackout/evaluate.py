"""Leave-one-storm-out scoring (docs/plan.md, Task 7).

Each main storm is predicted by a fit on the other main storms only, then graded against EAGLE-I. The scorecard
counts only what it can check: hit counties the satellite could see, in states EAGLE-I covers, on nights with a
usable official count. `write_scorecard` is `uv run blackout evaluate`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import date
from functools import partial
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from blackout.hybrid import fit_hybrid, fit_wind_timing
from blackout.model import (
    OK,
    TRUTH,
    Translator,
    WindOnly,
    apply_overcount_rule,
    bools,
    fit_nothing,
    fit_translation,
    floats,
    nights,
    noise_report,
    overcount_summary,
    require_columns,
    resolve_storms,
    storm_ids,
)
from blackout.storms import REPO, Storm, load_storms
from blackout.table import SCORES_LOSO_FILE
from blackout.winds import NOT_APPLICABLE

PROCESSED = REPO / "data/processed"
SCORECARD = REPO / "docs/scorecard.md"
PREDICTIONS_FILE = "loso_predictions.parquet"
SCORES_FILE = SCORES_LOSO_FILE
TRUTH_COLUMNS = {60: TRUTH, 30: f"{TRUTH}_30", 90: f"{TRUTH}_90"}
WINDOWS = (60, 30, 90)  # the headline first
RESTORE_THRESHOLD = 0.10
OUT_CUT = 0.5  # "at least half out", for the catch rate and false alarms
HIT_BAND = 34  # tropical-storm-force winds
# The pre-registered curve (pass bar), its two simple guesses, then the hybrid and its no-satellite twin
# (decision log, 2026-11-08, "Model choice").
METHODS = ("isotonic", "wind_only", "nothing", "hybrid", "wind_timing")
FITS = {"isotonic": fit_translation, "wind_only": WindOnly.fit, "nothing": fit_nothing, "hybrid": fit_hybrid,
        "wind_timing": fit_wind_timing}
PRED_COLUMNS = {"isotonic": "pred_pct_out", "wind_only": "pred_wind_only", "nothing": "pred_nothing",
                "hybrid": "pred_hybrid", "wind_timing": "pred_wind_timing"}
SCORE_COLUMNS = ["storm_id", "mae_pp", "peak_total_est", "peak_total_official", "catch_rate_50", "false_alarm_50",
                 "restore_day_err", "measurable_share", "rows_scored", "overcount_dropped"]
COMBINED_COLUMNS = ["method", "window", *SCORE_COLUMNS]
ROW_INPUTS = ("storm_id", "fips", "night", "status", "covered", "wind_band", "customers")
CURVE_GRID = tuple(round(0.1 * k, 1) for k in range(10))
NAN = float("nan")


class Predictor(Protocol):
    def predict(self, df: pd.DataFrame) -> np.ndarray: ...


def _check_known(ids: set, storms: list[Storm], what: str) -> None:
    known = {s.id for s in storms}
    unknown = sorted(str(i) for i in ids if i not in known)
    if unknown:
        raise ValueError(f"{what}: unknown storm ids {unknown}")


# --- leave one storm out -----------------------------------------------------------------------------------------

def loso(df: pd.DataFrame, fit: Callable[[pd.DataFrame], Predictor],
         storms: Iterable[Storm] | None = None) -> pd.DataFrame:
    """The main storms' rows with `pred_pct_out`, each storm predicted by a fit that never saw it.

    The fit gets only the other main storms' rows: never the held-out storm, a lockbox storm or the stress storm.
    """
    storms = resolve_storms(storms)
    present = storm_ids(df)
    _check_known(present, storms, "loso")
    order = [s.id for s in storms if s.role == "main" and s.id in present]
    if len(order) < 2:
        raise ValueError(f"loso needs rows from at least two main storms, got {order}")
    main = df[df["storm_id"].isin(order)].reset_index(drop=True)
    ids = main["storm_id"].to_numpy()
    keys = pd.MultiIndex.from_arrays([main["fips"].to_numpy(), pd.to_datetime(main["night"]).to_numpy()])
    pred = np.full(len(main), np.nan)
    for held in order:
        test = ids == held
        # Storm windows overlap (Michael's baseline holds Florence's event nights for the shared states), so a
        # training row that is one of the held-out storm's own county-nights is left out too.
        shared = keys.isin(keys[test]) & ~test
        predictor = fit(main[~test & ~shared].reset_index(drop=True))
        values = np.asarray(predictor.predict(main[test].reset_index(drop=True)), dtype=float)
        if values.shape != (int(test.sum()),):
            raise ValueError(f"loso: the {held} predictor returned shape {values.shape} for {int(test.sum())} rows")
        pred[test] = values
    return main.assign(pred_pct_out=pred)


# --- restore day -------------------------------------------------------------------------------------------------

def restore_day(days: np.ndarray, values: np.ndarray, threshold: float = RESTORE_THRESHOLD) -> float:
    """`official_restore_day` on plain arrays (the scorecard calls it once per county, so it skips pandas)."""
    keep = np.isfinite(values) & np.isfinite(days)
    order = np.argsort(days[keep], kind="stable")
    d, v = days[keep][order], values[keep][order]
    if len(v) == 0:
        return NAN
    for i in range(int(np.argmax(v)) + 1, len(v)):  # argmax gives the first max
        if v[i] > threshold:
            continue
        later = np.flatnonzero(d >= d[i] + 1.0)
        if len(later) == 0:
            return NAN  # nothing a day later confirms this night, or any night after it
        if np.all(v[i:later[0] + 1] <= threshold):
            return float(d[i])
    return NAN


def official_restore_day(series: pd.Series, threshold: float = RESTORE_THRESHOLD) -> float:
    """Days after landfall until % out falls to `threshold` or below after its peak and stays there 24 hours.

    `series` is one county's nightly values indexed by days after landfall. The peak is the first maximum. A
    restored night needs the next non-NaN night at least a day later to be at or below `threshold` too. NaN nights
    are skipped: they neither count as restored nor break a restored stretch. NaN if it never restores. The same
    function gives the estimated restore day from predictions.
    """
    days = np.asarray(series.index, dtype=float)
    return restore_day(days, series.to_numpy(dtype=float, na_value=np.nan), threshold)


# --- scorecard ---------------------------------------------------------------------------------------------------

def truth_column(window: int) -> str:
    if window not in TRUTH_COLUMNS:
        raise ValueError(f"window must be one of {sorted(TRUTH_COLUMNS)} minutes, got {window!r}")
    return TRUTH_COLUMNS[window]


def _mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if len(values) else NAN


def _hit_rows(part: pd.DataFrame, storm: Storm) -> np.ndarray:
    """34-kt winds or more; the stress storm has no wind field (band -1), so every county counts."""
    bands = floats(part, "wind_band")
    return bands == NOT_APPLICABLE if storm.role == "stress" else bands >= HIT_BAND


def _peak_totals(night: np.ndarray, pred: np.ndarray, truth: np.ndarray, customers: np.ndarray,
                 scored: np.ndarray) -> dict:
    """The largest one-night sum of customers out over scored rows, estimated and official, each at its own peak."""
    rows = scored & np.isfinite(customers)
    if not rows.any():
        return {"peak_total_est": NAN, "peak_total_official": NAN}
    totals = pd.DataFrame({"night": night[rows], "est": pred[rows] * customers[rows],
                           "official": truth[rows] * customers[rows]}).groupby("night")[["est", "official"]].sum()
    return {"peak_total_est": float(totals["est"].max()), "peak_total_official": float(totals["official"].max())}


def _restore_day_error(fips: np.ndarray, day: np.ndarray, truth: np.ndarray, pred: np.ndarray,
                       counties: np.ndarray) -> float:
    """Median over counties of |estimated - official| restore day, skipping counties where either is NaN.

    The official series keeps every night (EAGLE-I does not care about clouds); the estimate exists only on nights
    the satellite saw. The caller blanks `pred` on every other night, so a value a predictor left there (a 0, say) is
    skipped like any NaN night instead of reading as restored.
    """
    idx = np.flatnonzero(counties)
    errors = []
    for positions in pd.Series(idx).groupby(fips[idx]).indices.values():
        rows = idx[positions]
        official, estimate = restore_day(day[rows], truth[rows]), restore_day(day[rows], pred[rows])
        if np.isfinite(official) and np.isfinite(estimate):
            errors.append(abs(estimate - official))
    return float(np.median(errors)) if errors else NAN


def _score_storm(part: pd.DataFrame, storm: Storm, column: str) -> dict:
    night = nights(part)
    landfall = np.datetime64(storm.landfall, "ns")
    in_window = (night >= landfall) & (night <= np.datetime64(storm.window_end, "ns"))
    day = (night - landfall) / np.timedelta64(1, "D")
    hit, ok, covered = _hit_rows(part, storm), (part["status"] == OK).to_numpy(dtype=bool), bools(part, "covered")
    truth, pred = floats(part, column), floats(part, "pred_pct_out")
    seen = np.where(ok, pred, np.nan)  # can't see never becomes a reading, whatever the predictor left there
    eligible = in_window & hit & ok & covered & np.isfinite(pred)
    scored = eligible & np.isfinite(truth)
    return {
        "storm_id": storm.id,
        "mae_pp": _mean(np.abs(pred - truth)[scored]) * 100,
        **_peak_totals(night, pred, truth, floats(part, "customers"), scored),
        "catch_rate_50": _mean(pred[scored & (truth >= OUT_CUT)] >= OUT_CUT),
        "false_alarm_50": _mean(truth[scored & (pred >= OUT_CUT)] < OUT_CUT),
        "restore_day_err": _restore_day_error(part["fips"].to_numpy(), day, truth, seen, in_window & hit & covered),
        "measurable_share": _mean(ok[in_window & hit]),
        "rows_scored": int(scored.sum()),
        "overcount_dropped": int((eligible & part[f"{column}_overcount"].to_numpy(dtype=bool)).sum()),
    }


def scorecard(preds: pd.DataFrame, window: int = 60, storms: Iterable[Storm] | None = None) -> pd.DataFrame:
    """One row per storm in `preds`, graded against the +-`window`-minute official % out.

    `window` only picks the truth column (the curve is always fit on +-60), cleaned by the over-count rule. Scored
    rows: nights from landfall to window_end, status "ok", covered, a usable truth and a prediction, hit counties.
    """
    column = truth_column(window)
    storms = resolve_storms(storms)
    require_columns(preds, (*ROW_INPUTS, "pred_pct_out", column), "scorecard")
    present = storm_ids(preds)
    _check_known(present, storms, "scorecard")
    cleaned = apply_overcount_rule(preds, column)
    ids = cleaned["storm_id"].to_numpy()
    rows = [_score_storm(cleaned[ids == s.id], s, column) for s in storms if s.id in present]
    return pd.DataFrame(rows, columns=SCORE_COLUMNS)


# --- write_scorecard ---------------------------------------------------------------------------------------------

def load_main_tables(processed: Path, storms: list[Storm]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Each main storm's table that exists, opened by exact name (never a glob, so lockbox files stay shut)."""
    tables, missing = {}, []
    for storm in (s for s in storms if s.role == "main"):
        path = processed / f"county_nights_{storm.id}.parquet"
        if not path.exists():
            missing.append(storm.id)
            continue
        table = pd.read_parquet(path)
        found = storm_ids(table)
        if found != {storm.id}:
            raise ValueError(f"{path.name} holds storm ids {sorted(map(str, found))}, expected only {storm.id}")
        tables[storm.id] = table
    return tables, missing


def loso_predictions(df: pd.DataFrame, storms: list[Storm]) -> pd.DataFrame:
    """The main storms' rows with one leave-one-storm-out column per method; the curve's is `pred_pct_out`.

    loso keeps the table's row order, so the three runs line up row for row.
    """
    runs = {m: loso(df, partial(FITS[m], storms=storms), storms) for m in METHODS}
    extra = {PRED_COLUMNS[m]: runs[m]["pred_pct_out"].to_numpy() for m in METHODS if m != "isotonic"}
    return runs["isotonic"].assign(**extra)


def score_all(preds: pd.DataFrame, storms: list[Storm]) -> pd.DataFrame:
    """Every method at every window, as one table with `method` and `window` columns."""
    inputs = preds[[*ROW_INPUTS, *TRUTH_COLUMNS.values()]]
    frames = [scorecard(inputs.assign(pred_pct_out=preds[PRED_COLUMNS[m]].to_numpy()), w, storms)
              .assign(method=m, window=w) for w in WINDOWS for m in METHODS]
    return pd.concat(frames, ignore_index=True)[COMBINED_COLUMNS]


def overcount_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per storm and truth window: county-nights with a value, clipped to 1.0, and dropped."""
    parts = [overcount_summary(df, TRUTH_COLUMNS[w]).set_index("storm_id").add_suffix(f"_{w}") for w in WINDOWS]
    return pd.concat(parts, axis=1)


def write_scorecard(processed: Path = PROCESSED, out: Path = SCORECARD) -> pd.DataFrame:
    """`blackout evaluate`: a DRAFT docs/scorecard.md and data/processed/loso_predictions.parquet.

    Scores the curve, the wind-only guess and "nothing happened" leave-one-storm-out at +-60 (headline), +-30 and
    +-90, and returns the combined score table. Main storms only; the lockbox stays shut.
    """
    processed, out = Path(processed), Path(out)
    storms = load_storms()
    tables, missing = load_main_tables(processed, storms)
    if len(tables) < 2:
        _write(out, render_too_few(list(tables), missing))
        return pd.DataFrame(columns=COMBINED_COLUMNS)
    df = pd.concat(tables.values(), ignore_index=True)
    preds = loso_predictions(df, storms)
    combined = score_all(preds, storms)
    preds.to_parquet(processed / PREDICTIONS_FILE, index=False)
    combined.to_parquet(processed / SCORES_FILE, index=False)  # export.py fills scorecard.json from it
    lockbox_path = processed / "lockbox_result.json"
    lockbox = json.loads(lockbox_path.read_text()) if lockbox_path.exists() else None
    integrity = integrity_section(lockbox) if lockbox else None
    sections = render_scorecard(combined, noise_report(df, storms), overcount_table(df),
                                diagnostics(preds, storms), satellite_increment(preds, storms),
                                fit_translation(df, storms=storms), list(tables), missing, lockbox, integrity)
    _write(out, sections)
    return combined


def _write(out: Path, lines: list[str]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n")


# --- markdown ----------------------------------------------------------------------------------------------------

LOCKBOX_LINE = "Lockbox (Helene, Milton) not scored yet."
SCORE_HEADER = ["Storm", "Method", "County error (pp)", "Peak out, est.", "Peak out, official", "Caught ≥50%",
                "False alarms ≥50%", "Restore-day error (days)", "Measurable", "Rows scored", "Over-counts dropped"]
NOISE_HEADER = ["Storm", "Calm county-nights", "Raw sd", "Corrected sd, in-sample", "Corrected sd, leave-one-storm-out"]
DRAFT_NOTE = ("Every score is leave-one-storm-out: each main storm is predicted by a fit on the other main storms "
              "only. The numbers move as storm tables are added.")
HOW_TO_READ = [
    ("- **Methods:** `isotonic` is the pre-registered night-light curve (angle- and moon-corrected % darker to % "
     "out); `wind_only` is the training storms' mean % out for the county's wind band; `nothing` says 0% out; "
     "`hybrid` adds the storm context (wind band, days since landfall) and each county's calm-night noise to the "
     "satellite reading; `wind_timing` is the same model with no satellite input, the test of what the satellite "
     "adds (decision log, \"Model choice\")."),
    ("- **Scored county-nights:** landfall to window end (landfall + 21 days), counties with 34-kt winds or more, "
     "status `ok` (the satellite could see), states EAGLE-I covers (coverage ≥ 0.8), and a usable official count. "
     "Can't-see nights are left out, never scored as zero."),
    "- **County error:** mean |estimate − official| in percentage points.",
    ("- **Peak out:** the largest one-night total of customers out over the scored counties, estimated and official, "
     "each at its own peak night."),
    ("- **Caught ≥50%:** share of county-nights officially at least half out that the method also put at least half "
     "out. **False alarms ≥50%:** share of the method's at-least-half calls that were officially under half."),
    ("- **Restore-day error:** median over hit counties of |estimated − official| restore day; restored means at or "
     "below 10% out after the peak and still there the next night."),
    "- **Measurable:** share of hit-county nights in the window the satellite could see.",
    ("- **Over-counts:** official % out above 1.05 is dropped (EAGLE-I over-count or MCC under-count); 1.0–1.05 is "
     "clipped to 1.0."),
]
NOISE_NOTE = ("sd of % darker on baseline nights the satellite could see, where it should sit near zero: raw, after "
              "the angle and moon correction fit on the same storms (in-sample), and after a correction fit on the "
              "other main storms only (leave-one-storm-out).")
OVERCOUNT_NOTE = ("County-nights (all statuses) whose official % out the over-count rule clipped to 1.0 or dropped, "
                  "per truth window. The `Over-counts dropped` column above counts only rows that would otherwise "
                  "be scored.")
CLOSING_NOTE = ("- These are leave-one-storm-out numbers on the main storms only, a draft for review rather than the "
                "lockbox test: the pass bar is committed before Helene and Milton are scored (Task 9).")


def _finite(value) -> bool:
    return value is not None and bool(np.isfinite(value))


def _num(value, digits: int) -> str:
    return f"{value:.{digits}f}" if _finite(value) else "n/a"


def _count(value) -> str:
    return f"{value:,.0f}" if _finite(value) else "n/a"


def _share(value) -> str:
    return f"{value:.0%}" if _finite(value) else "n/a"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|",
            *("| " + " | ".join(row) + " |" for row in rows)]


def _header(lockbox_scored: bool = False) -> list[str]:
    today = date.today().isoformat()
    title = "# Scorecard" if lockbox_scored else "# Scorecard (DRAFT)"
    note = f"*Written by `uv run blackout evaluate` on {today}. {DRAFT_NOTE}*" if lockbox_scored else \
        f"*DRAFT written by `uv run blackout evaluate` on {today}. {DRAFT_NOTE}*"
    guide = ("How to read the opened lockbox, with the verdict tables laid out section by section: "
             "[docs/scorecard-reading.md](scorecard-reading.md).")
    return [title, "", note, "", *([guide, ""] if lockbox_scored else [LOCKBOX_LINE, ""])]


def render_too_few(built: list[str], missing: list[str]) -> list[str]:
    reason = (f"Leave-one-storm-out scoring needs tables for at least two main storms; {len(built)} exist so far, "
              "so nothing is scored yet.")
    return [*_header(), reason, "", f"- **Built:** {', '.join(built) or 'none'}.",
            f"- **Not built yet:** {', '.join(missing) or 'none'}.", "",
            "Build more with `uv run blackout build --storm <id>`, then rerun `uv run blackout evaluate`."]


def _window_section(combined: pd.DataFrame, window: int, order: list[str]) -> list[str]:
    title = "±60 minutes (headline)" if window == 60 else f"±{window} minutes"
    part = combined[combined["window"] == window]
    lookup = {(r["storm_id"], r["method"]): r for r in part.to_dict("records")}
    rows = []
    for storm_id in order:
        for method in METHODS:
            r = lookup.get((storm_id, method))
            if r is None:
                continue
            rows.append([storm_id, method, _num(r["mae_pp"], 1), _count(r["peak_total_est"]),
                         _count(r["peak_total_official"]), _share(r["catch_rate_50"]), _share(r["false_alarm_50"]),
                         _num(r["restore_day_err"], 1), _share(r["measurable_share"]), _count(r["rows_scored"]),
                         _count(r["overcount_dropped"])])
    return [f"## {title}", "", *_table(SCORE_HEADER, rows), ""]


def _noise_section(noise: dict) -> list[str]:
    def line(label: str, stats: dict) -> list[str]:
        return [label, _count(stats["rows"]), _num(stats["raw_sd"], 3), _num(stats["in_sample_sd"], 3),
                _num(stats["loso_sd"], 3)]

    c = noise["coefficients"]
    rows = [line("All main storms", noise), *(line(sid, s) for sid, s in noise["per_storm"].items())]
    fit = (f"Correction fit on all main storms present: % darker = {_num(c['intercept'], 4)} + {_num(c['sec'], 4)} "
           f"× (sec(zenith) − 1) + {_num(c['moon'], 4)} × lunar irradiance, from {_count(c['rows'])} calm "
           "county-nights. The intercept is kept; only the two slopes are removed.")
    return ["## Noise on calm nights", "", NOISE_NOTE, "", *_table(NOISE_HEADER, rows), "", fit, ""]


def _overcount_section(table: pd.DataFrame, order: list[str]) -> list[str]:
    rows = [[sid, _count(table.loc[sid, "with_value_60"]),
             *(_count(table.loc[sid, f"{kind}_{w}"]) for w in WINDOWS for kind in ("clipped", "dropped"))]
            for sid in order if sid in table.index]
    header = ["Storm", "With a value ±60", *(f"{kind} ±{w}" for w in WINDOWS for kind in ("Clipped", "Dropped"))]
    return ["## Over-counts", "", OVERCOUNT_NOTE, "", *_table(header, rows), ""]


def _curve_section(curve: Translator) -> list[str]:
    estimates = curve.curve.predict(np.array(CURVE_GRID))
    rows = [[f"{x:.0%}", _share(y)] for x, y in zip(CURVE_GRID, estimates)]
    note = (f"The isotonic curve fit on all main storms present ({_count(curve.rows)} county-nights), for reading "
            "only: every score above comes from leave-one-storm-out fits.")
    return ["## The curve", "", note, "", *_table(["Corrected % darker", "Estimated % out"], rows), ""]


def _half_out_sentence(curve: pd.DataFrame) -> str:
    """Catch rate and false alarms in words. Either can have nothing to count (no county-night officially half out,
    or a curve that never calls half out), and the reading says so rather than printing "n/a" mid-sentence."""
    catch, alarm = curve["catch_rate_50"].mean(), curve["false_alarm_50"].mean()
    caught = (f"Of county-nights officially at least half out, the curve also put {_share(catch)} at least half out "
              "(mean over storms)" if _finite(catch) else "No scored county-night was officially at least half out")
    alarms = (f"{_share(alarm)} of its own at-least-half calls were false alarms" if _finite(alarm)
              else "the curve made no at-least-half calls, so it raised no false alarms")
    return f"- {caught}, and {alarms}."


def _reading(combined: pd.DataFrame) -> list[str]:
    """Plain sentences built only from the headline (+-60) numbers, so the draft never claims more than they say."""
    head = combined[combined["window"] == 60]
    mae = head.pivot(index="storm_id", columns="method", values="mae_pp")
    curve = head[head["method"] == "isotonic"].set_index("storm_id")
    vs_wind, vs_nothing = mae.dropna(subset=["isotonic", "wind_only"]), mae.dropna(subset=["isotonic", "nothing"])
    beat_wind = int((vs_wind["isotonic"] < vs_wind["wind_only"]).sum())
    beat_nothing = int((vs_nothing["isotonic"] < vs_nothing["nothing"]).sum())
    ratio = (curve["peak_total_est"] / curve["peak_total_official"]).replace([np.inf, -np.inf], np.nan)
    sentences = [
        (f"- On the headline ±60-minute truth, the night-light curve's county error was lower than the wind-only "
         f"guess in {beat_wind} of {len(vs_wind)} storms, and lower than \"nothing happened\" in {beat_nothing} of "
         f"{len(vs_nothing)}."),
        (f"- Averaged over storms, county error was {_num(mae['isotonic'].mean(), 1)} pp for the curve, "
         f"{_num(mae['wind_only'].mean(), 1)} pp for wind-only and {_num(mae['nothing'].mean(), 1)} pp for nothing "
         "happened."),
        (f"- On its peak night, the curve's total of customers out over the scored counties was a median "
         f"{_share(ratio.median())} of the official peak total."),
        _half_out_sentence(curve),
        (f"- Restore days were off by a median {_num(curve['restore_day_err'].median(), 1)} days (the median over "
         "storms of each storm's median county error)."),
        (f"- The satellite could see {_share(curve['measurable_share'].mean())} of hit-county nights in the event "
         "windows (mean over storms). Clouds and dark counties hide the rest, and those nights are left out, never "
         "counted as zero."),
        CLOSING_NOTE,
    ]
    return ["## Plain-language reading", "", *sentences, ""]


DIAG_HEADER = ["Method", "Rows", "County error (pp)", "Error where official ≥10% (pp)", "Bias (pp)",
               "AUC for ≥50% out", "Night-to-night agreement (Spearman of changes)"]


def diagnostics(preds: pd.DataFrame, storms: list[Storm], window: int = 60) -> pd.DataFrame:
    """Pooled diagnostics over every scored county-night of the main storms (defined before the lockbox opened).

    Most scored nights have almost no outage, so county error rewards guessing zero. These show what it hides: error
    where the official count is at least 10%, signed bias, how well a method ranks the half-out county-nights (AUC),
    and agreement on night-to-night changes, which shared decay cannot fake.
    """
    from scipy.stats import rankdata, spearmanr

    truth_col = truth_column(window)
    clean = apply_overcount_rule(preds, truth_col)
    landfall = clean["storm_id"].map({s.id: pd.Timestamp(s.landfall) for s in storms})
    end = clean["storm_id"].map({s.id: pd.Timestamp(s.window_end) for s in storms})
    night = pd.to_datetime(clean["night"])
    hit = (clean["wind_band"] >= HIT_BAND) | (clean["wind_band"] == NOT_APPLICABLE)
    rows = clean[(night >= landfall) & (night <= end) & (clean["status"] == "ok") & clean["covered"].astype(bool)
                 & hit & np.isfinite(clean[truth_col])]
    out = []
    for method, column in PRED_COLUMNS.items():
        part = rows[np.isfinite(rows[column])]
        t, q = part[truth_col].to_numpy(dtype=float), part[column].to_numpy(dtype=float)
        if not len(t):
            continue
        big = t >= RESTORE_THRESHOLD
        positive = t >= OUT_CUT
        auc = NAN
        if 0 < positive.sum() < len(t):
            ranks = rankdata(q)
            auc = (ranks[positive].sum() - positive.sum() * (positive.sum() + 1) / 2) / (positive.sum() * (~positive).sum())
        diffs = [(np.diff(g[column].to_numpy(dtype=float)), np.diff(g[truth_col].to_numpy(dtype=float)))
                 for _, g in part.sort_values("night").groupby(["storm_id", "fips"]) if len(g) >= 2]
        d_pred = np.concatenate([d for d, _ in diffs]) if diffs else np.array([])
        d_truth = np.concatenate([d for _, d in diffs]) if diffs else np.array([])
        rho = float(spearmanr(d_pred, d_truth).statistic) if len(d_pred) > 2 and np.ptp(d_pred) > 0 else NAN
        out.append({"method": method, "rows": len(t), "mae_pp": float(np.abs(q - t).mean() * 100),
                    "mae_big_pp": float(np.abs(q - t)[big].mean() * 100) if big.any() else NAN,
                    "bias_pp": float((q - t).mean() * 100), "auc_50": float(auc), "change_spearman": rho})
    return pd.DataFrame(out)


INCREMENT_HEADER = ["Storm", "Rows ≥10% out", "Hybrid error ≥10% (pp)", "Wind+timing error ≥10% (pp)", "Difference",
                    "Hybrid AUC ≥50%", "Wind+timing AUC ≥50%", "Difference"]


def _auc(truth_positive: np.ndarray, score: np.ndarray) -> float:
    from scipy.stats import rankdata

    n_pos, n_neg = int(truth_positive.sum()), int((~truth_positive).sum())
    if not n_pos or not n_neg:
        return NAN
    ranks = rankdata(score)
    return float((ranks[truth_positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def satellite_increment(preds: pd.DataFrame, storms: list[Storm], window: int = 60) -> pd.DataFrame:
    """What the satellite adds beyond wind band and timing: hybrid minus wind_timing, per storm and pooled.

    The two models share every input except the satellite reading, so this difference is the satellite's own
    contribution. Rows are the scored county-nights; the error column uses only nights officially at least 10% out,
    where an outage estimate matters. The last two rows pool every storm, then every storm but Ida, the one storm
    with most of the heavy-outage nights, so a reader can see how much rests on it.
    """
    truth_col = truth_column(window)
    clean = apply_overcount_rule(preds, truth_col)
    landfall = clean["storm_id"].map({s.id: pd.Timestamp(s.landfall) for s in storms})
    end = clean["storm_id"].map({s.id: pd.Timestamp(s.window_end) for s in storms})
    night = pd.to_datetime(clean["night"])
    rows = clean[(night >= landfall) & (night <= end) & (clean["status"] == "ok") & clean["covered"].astype(bool)
                 & (clean["wind_band"] >= HIT_BAND) & np.isfinite(clean[truth_col])
                 & np.isfinite(clean["pred_hybrid"]) & np.isfinite(clean["pred_wind_timing"])]

    def summarise(part: pd.DataFrame, label: str) -> dict:
        t = part[truth_col].to_numpy(dtype=float)
        big, positive = t >= RESTORE_THRESHOLD, t >= OUT_CUT
        out = {"storm_id": label, "rows_big": int(big.sum()), "rows_half": int(positive.sum())}
        for method, column in (("hybrid", "pred_hybrid"), ("wind_timing", "pred_wind_timing")):
            q = part[column].to_numpy(dtype=float)
            out[f"mae_big_{method}"] = float(np.abs(q - t)[big].mean() * 100) if big.any() else NAN
            out[f"auc_{method}"] = _auc(positive, q)
        out["mae_big_diff"] = out["mae_big_hybrid"] - out["mae_big_wind_timing"]
        out["auc_diff"] = out["auc_hybrid"] - out["auc_wind_timing"]
        return out

    per_storm = [summarise(part, sid) for sid, part in rows.groupby("storm_id", sort=False)]
    pooled = [summarise(rows, "all storms pooled")]
    if "ida2021" in set(rows["storm_id"]):
        pooled.append(summarise(rows[rows["storm_id"] != "ida2021"], "pooled without Ida"))
    return pd.DataFrame([*per_storm, *pooled])


def _increment_section(inc: pd.DataFrame) -> list[str]:
    if inc.empty:
        return []
    lines = ["## What the satellite adds: hybrid minus wind + timing (±60)", "",
             ("The two models share every input except the night-light reading. A negative error difference and a "
              "positive AUC difference mean the satellite helped. With eight storms the increment is small and not "
              "settled; the lockbox storms are its confirmatory test (decision log, \"Model choice\")."), "",
             "| " + " | ".join(INCREMENT_HEADER) + " |", "|" + "---|" * len(INCREMENT_HEADER)]
    for r in inc.itertuples(index=False):
        cells = [r.storm_id, f"{r.rows_big:,}", _num(r.mae_big_hybrid, 1), _num(r.mae_big_wind_timing, 1),
                 ("n/a" if not np.isfinite(r.mae_big_diff) else f"{r.mae_big_diff:+.1f}"),
                 _num(r.auc_hybrid, 3), _num(r.auc_wind_timing, 3),
                 ("n/a" if not np.isfinite(r.auc_diff) else f"{r.auc_diff:+.3f}")]
        lines.append("| " + " | ".join(cells) + " |")
    return [*lines, ""]


def _diagnostics_section(diag: pd.DataFrame) -> list[str]:
    if diag.empty:
        return []
    lines = ["## Diagnostics, all main storms pooled (±60)", "",
             ("Defined before the lockbox opened. County error rewards guessing zero because most scored nights have "
             "almost no outage; these columns show what it hides."), "",
             "| " + " | ".join(DIAG_HEADER) + " |", "|" + "---|" * len(DIAG_HEADER)]
    for row in diag.itertuples(index=False):
        cells = [row.method, f"{row.rows:,}", f"{row.mae_pp:.2f}", _num(row.mae_big_pp, 1), f"{row.bias_pp:+.2f}",
                 _num(row.auc_50, 3), _num(row.change_spearman, 3)]
        lines.append("| " + " | ".join(cells) + " |")
    return [*lines, ""]


def _num(value: float, digits: int) -> str:
    return "n/a" if not np.isfinite(value) else f"{value:.{digits}f}"


def integrity_section(lockbox: dict) -> list[str] | None:
    """S1a: the integrity checks of the recorded opening, when docs/lockbox_record.json and the frozen result exist."""
    from blackout.final import FROZEN_RESULT, integrity_checks, render_integrity

    record_path = REPO / "docs/lockbox_record.json"
    if not (record_path.exists() and Path(FROZEN_RESULT).exists()):
        return None
    record = json.loads(record_path.read_text())
    return render_integrity(record, integrity_checks(lockbox, record))


def render_scorecard(combined: pd.DataFrame, noise: dict, overcounts: pd.DataFrame, diag: pd.DataFrame,
                     increment: pd.DataFrame, curve: Translator, scored: list[str], missing: list[str],
                     lockbox: dict | None = None, integrity: list[str] | None = None) -> list[str]:
    from blackout.final import render_lockbox

    return [*_header(lockbox is not None), f"- **Scored:** {', '.join(scored)}.",
            f"- **Not built yet, so not scored:** {', '.join(missing) or 'none'}.", "",
            "## How to read it", "", *HOW_TO_READ, "",
            *(line for w in WINDOWS for line in _window_section(combined, w, scored)),
            *_diagnostics_section(diag), *_increment_section(increment),
            *_noise_section(noise), *_overcount_section(overcounts, scored), *_curve_section(curve),
            *_reading(combined), *(render_lockbox(lockbox, integrity) if lockbox else [])]
