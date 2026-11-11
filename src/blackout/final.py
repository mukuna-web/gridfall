"""Task 9: the final fit, per-storm predictions, the lockbox score against the pass bar, NOAA-20 check, trigger view.

Order matters for honesty. The pass bar is committed first (decision log, 2026-11-08). The final curve and ranges are
then fit on the eight main storms with `final=True`, and each locked storm is scored once.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from blackout import table as table_mod
from blackout.storms import Storm, load_storms
from blackout.table import SCORES_FINAL_FILE, drop_check, table_path

HIT_BAND = 34  # tropical-storm-force winds; the same cut evaluate.py scores on
AGREEMENT_MIN = 0.3
RESTORE_MARGIN_DAYS = 2.0
TRIGGER_SHARE, TRIGGER_HOURS = 0.5, 72
WINDOWS = (60, 30, 90)
REPO = Path(__file__).resolve().parents[2]
RESULT_FILE = "lockbox_result.json"  # the one opening's result; export.py waits for it, and its presence refuses a rerun
OPENED_MARKER = "lockbox_opened.json"  # written before the first locked table is read, so a crashed run leaves a trace
CODE_FILES = ("model.py", "hybrid.py", "ranges.py", "evaluate.py", "final.py")
NO_VERDICT = "no verdict"
STAMP = "%Y%m%dT%H%M%SZ"


class LockboxOpenedError(RuntimeError):
    """The lockbox has been opened once; running again would be a second look at Helene and Milton (D-12)."""


def git_state(repo: Path = REPO) -> tuple[str | None, bool | None]:
    """(HEAD's sha, whether the working tree has uncommitted changes), or (None, None) where git is unavailable."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

    try:
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))
    except (OSError, subprocess.CalledProcessError):
        return None, None


def load_tables(storms: list[Storm], satellite: str | None = None, strict: bool = False) -> pd.DataFrame:
    """Each storm's own table (storm.satellite: Beryl's is NOAA-20), unless one satellite is named for all.

    `strict` refuses to go on with a table missing: the pass bar names eight main storms, so the final fits must
    see all eight.
    """
    missing = [s.id for s in storms if not table_path(s, satellite).exists()]
    if missing and strict:
        raise FileNotFoundError(f"tables missing for {missing}; run `blackout build --all` first")
    frames = [pd.read_parquet(table_path(s, satellite)) for s in storms if s.id not in missing]
    if not frames:
        raise FileNotFoundError("no county_nights tables found; run `blackout build` first")
    return pd.concat(frames, ignore_index=True)


def provenance(storms: list[Storm], frame: pd.DataFrame) -> dict:
    """What the lockbox run was made from: the commit, the model code's hashes, and each training table."""
    head, dirty = git_state()
    hashes = {name: hashlib.sha256((REPO / "src/blackout" / name).read_bytes()).hexdigest()[:16] for name in CODE_FILES}
    tables = [{"storm_id": s.id, "satellite": s.satellite, "table": table_path(s).name,
               "rows": int((frame["storm_id"] == s.id).sum())} for s in storms]
    return {"git_head": head, "working_tree_dirty": dirty, "code_sha256_16": hashes, "training_tables": tables,
            "run_at_utc": pd.Timestamp.now(tz="UTC").isoformat()}


def drop_shared_county_nights(train: pd.DataFrame, held: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Training rows whose (fips, night) also appear in a held-out table are left out, as LOSO does. Only the keys
    of the held-out table are read, never its official counts."""
    train_keys = pd.MultiIndex.from_arrays([train["fips"].to_numpy(), pd.to_datetime(train["night"]).to_numpy()])
    held_keys = pd.MultiIndex.from_arrays([held["fips"].to_numpy(), pd.to_datetime(held["night"]).to_numpy()])
    shared = train_keys.isin(held_keys)
    return train[~shared].reset_index(drop=True), int(shared.sum())


def scored_rows(df: pd.DataFrame, storm: Storm, truth: str, pred: str = "pred_pct_out") -> pd.DataFrame:
    """The pass bar's rows: hit counties, event nights, status ok, covered, usable truth and prediction."""
    rows = df[(df["storm_id"] == storm.id) & (df["night"] >= storm.landfall) & (df["night"] <= storm.window_end)
              & (df["status"] == "ok") & df["covered"]]
    rows = rows[rows["wind_band"] >= HIT_BAND] if storm.role != "stress" else rows
    return rows[np.isfinite(rows[truth]) & np.isfinite(rows[pred])]


def first_difference_agreement(rows: pd.DataFrame, truth: str, pred: str = "pred_pct_out") -> tuple[float, int]:
    """Pooled Spearman of night-to-night changes (estimate vs official) between consecutive scored nights per
    county. Shared decay over time cancels out, unlike Spearman on levels (Phase 0: 0.77 raw, -0.06 detrended)."""
    diffs = []
    for _, county in rows.sort_values("night").groupby("fips"):
        if len(county) >= 2:
            diffs.append(pd.DataFrame({"d_pred": np.diff(county[pred].to_numpy()),
                                       "d_truth": np.diff(county[truth].to_numpy())}))
    if not diffs:
        return float("nan"), 0
    pooled = pd.concat(diffs, ignore_index=True)
    if len(pooled) < 3 or pooled["d_pred"].nunique() < 2 or pooled["d_truth"].nunique() < 2:
        return float("nan"), len(pooled)
    return float(spearmanr(pooled["d_pred"], pooled["d_truth"]).statistic), len(pooled)


def restore_day_errors(df: pd.DataFrame, storm: Storm, truth: str, pred: str = "pred_pct_out") -> pd.Series:
    """|estimated - official| restore day per hit county, both from official_restore_day's rule."""
    from blackout.evaluate import official_restore_day

    rows = df[(df["storm_id"] == storm.id) & (df["night"] >= storm.landfall) & (df["night"] <= storm.window_end)
              & df["covered"]]
    rows = rows[rows["wind_band"] >= HIT_BAND] if storm.role != "stress" else rows
    errors = {}
    for fips, county in rows.groupby("fips"):
        days = (pd.to_datetime(county["night"]) - pd.Timestamp(storm.landfall)).dt.days.to_numpy()
        ok = (county["status"] == "ok").to_numpy()
        est = pd.Series(np.where(ok, county[pred].to_numpy(dtype=float), np.nan), index=days).sort_index()
        off = pd.Series(county[truth].to_numpy(dtype=float), index=days).sort_index()
        e, o = official_restore_day(est), official_restore_day(off)
        if np.isfinite(e) and np.isfinite(o):
            errors[fips] = abs(e - o)
    return pd.Series(errors, dtype=float)


def pass_bar_check(df: pd.DataFrame, storm: Storm, window: int = 60) -> dict:
    """The three pass-bar conditions for one storm (decision log, "Pass bar, written before the lockbox opens")."""
    from blackout.model import apply_overcount_rule

    truth = {60: "official_pct_out", 30: "official_pct_out_30", 90: "official_pct_out_90"}[window]
    clean = apply_overcount_rule(df, truth)
    rows = scored_rows(clean, storm, truth)
    wind = scored_rows(clean, storm, truth, pred="pred_wind_only")
    both = rows.index.intersection(wind.index)
    mae_curve = float((clean.loc[both, "pred_pct_out"] - clean.loc[both, truth]).abs().mean() * 100)
    mae_wind = float((clean.loc[both, "pred_wind_only"] - clean.loc[both, truth]).abs().mean() * 100)
    agreement, pairs = first_difference_agreement(rows, truth)
    restore = restore_day_errors(clean, storm, truth)
    restore_median = float(restore.median()) if len(restore) else float("nan")
    checks = {
        "beats_wind_only": bool(len(both) and mae_curve < mae_wind),
        "agreement_ok": bool(np.isfinite(agreement) and agreement >= AGREEMENT_MIN),
        "restore_ok": bool(np.isfinite(restore_median) and restore_median <= RESTORE_MARGIN_DAYS),
    }
    return {"storm_id": storm.id, "window": window, "rows_scored": len(both),
            "mae_pp_curve": round(mae_curve, 2), "mae_pp_wind_only": round(mae_wind, 2),
            "first_difference_spearman": round(agreement, 3) if np.isfinite(agreement) else None,
            "change_pairs": pairs, "restore_day_median_error": restore_median if np.isfinite(restore_median) else None,
            "restore_counties": len(restore), **checks, "passes": all(checks.values())}


def trigger_view(df: pd.DataFrame, storm: Storm) -> dict:
    """Basis risk for a "county above 50% out at 72 hours" trigger: estimated vs official, hit counties."""
    from blackout.ranges import pct_out_bracket

    outcomes = {"paid_correctly": 0, "paid_wrongly": 0, "missed": 0, "correctly_unpaid": 0, "unknown": 0}
    rows = df[(df["storm_id"] == storm.id) & df["covered"]]
    rows = rows[rows["wind_band"] >= HIT_BAND] if storm.role != "stress" else rows
    for _, county in rows.groupby("fips"):
        est = pct_out_bracket(county.rename(columns={"pred_pct_out": "est"}), storm.landfall_time, TRIGGER_HOURS)
        target = storm.landfall_time + pd.Timedelta(hours=TRIGGER_HOURS)
        times = pd.to_datetime(county["pass_utc"], utc=True)
        after = county[(times >= target) & np.isfinite(county["official_pct_out"])]
        if est is None or after.empty:
            outcomes["unknown"] += 1
            continue
        paid = (est[0] + est[1]) / 2 > TRIGGER_SHARE
        truly = float(after.sort_values("night").iloc[0]["official_pct_out"]) > TRIGGER_SHARE
        key = {(True, True): "paid_correctly", (True, False): "paid_wrongly", (False, True): "missed",
               (False, False): "correctly_unpaid"}[(paid, truly)]
        outcomes[key] += 1
    return {"storm_id": storm.id, "trigger": f"county above {TRIGGER_SHARE:.0%} out at {TRIGGER_HOURS} h", **outcomes}


def noaa20_agreement(storms: list[Storm]) -> list[dict]:
    """County pct_darker on the same nights from Suomi NPP (VNP46A2) and NOAA-20 (VJ146A2)."""
    out = []
    for storm in storms:
        a, b = table_path(storm, "VNP46A2"), table_path(storm, "VJ146A2")
        if not (a.exists() and b.exists()):
            out.append({"storm_id": storm.id, "note": "table missing"})
            continue
        keys = ["fips", "night"]
        joined = pd.read_parquet(a).merge(pd.read_parquet(b), on=keys, suffixes=("_npp", "_n20"))
        both = joined[(joined["status_npp"] == "ok") & (joined["status_n20"] == "ok")]
        event = both[both["night"] >= storm.landfall]
        row = {"storm_id": storm.id, "pairs": len(both), "event_pairs": len(event)}
        if len(both) >= 3:
            row["pearson"] = round(float(np.corrcoef(both["pct_darker_npp"], both["pct_darker_n20"])[0, 1]), 3)
            row["spearman"] = round(float(spearmanr(both["pct_darker_npp"], both["pct_darker_n20"]).statistic), 3)
            row["median_abs_diff_pp"] = round(float((both["pct_darker_npp"] - both["pct_darker_n20"]).abs().median()
                                                    * 100), 1)
        if len(event) >= 3:
            row["event_spearman"] = round(float(spearmanr(event["pct_darker_npp"], event["pct_darker_n20"]).statistic), 3)
        out.append(row)
    return out


def lee_on_noaa20(ian: Storm) -> dict:
    """Phase 0's Lee County checks on NOAA-20: the darkest night and the half-recovery gap to EAGLE-I."""
    path = table_path(ian, "VJ146A2")
    if not path.exists():
        return {"note": "NOAA-20 Ian table missing"}
    lee = pd.read_parquet(path)
    lee = lee[(lee["fips"] == "12071") & (lee["night"] >= ian.landfall) & (lee["status"] == "ok")].sort_values("night")
    if lee.empty:
        return {"note": "no clear NOAA-20 night over Lee after landfall"}
    peak = lee.loc[lee["pct_darker"].idxmax()]
    official = lee.dropna(subset=["official_pct_out"])
    off_peak = official.loc[official["official_pct_out"].idxmax()] if not official.empty else None

    def half_night(frame: pd.DataFrame, column: str, top: float) -> date | None:
        after = frame[frame["night"] > frame.loc[frame[column].idxmax(), "night"]]
        below = after[after[column] < top / 2]
        return below["night"].iloc[0] if not below.empty else None

    dark_half = half_night(lee, "pct_darker", float(peak["pct_darker"]))
    off_half = half_night(official, "official_pct_out", float(off_peak["official_pct_out"])) if off_peak is not None \
        else None
    gap = (dark_half - off_half).days if dark_half and off_half else None
    return {"darkest_night": str(peak["night"]), "darkest_pct": round(float(peak["pct_darker"]), 3),
            "official_peak_night": str(off_peak["night"]) if off_peak is not None else None,
            "half_recovery_dark": str(dark_half) if dark_half else None,
            "half_recovery_official": str(off_half) if off_half else None, "recovery_gap_nights": gap}


def _strict(value: object) -> object:
    """JSON-safe copy: NaN and +-inf become null (json.dumps would write NaN/Infinity, which JSON.parse rejects)."""
    if isinstance(value, dict):
        return {str(k): _strict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_strict(payload), indent=2, default=str, allow_nan=False))


def storm_by_id() -> dict[str, Storm]:
    return {s.id: s for s in load_storms()}


def failure_facts(storm: Storm, satellite: str = "VNP46A2") -> dict:
    """Facts for docs/failures.md from one storm's table: clouds, dark counties, over-counts, missing customers."""
    path = table_path(storm, satellite)
    if not path.exists():
        return {"storm_id": storm.id, "note": "table missing"}
    t = pd.read_parquet(path)
    week = t[(t["night"] >= storm.landfall) & (t["night"] <= storm.landfall + pd.Timedelta(days=7).to_pytimedelta())]
    hit = week[week["wind_band"] >= HIT_BAND] if storm.role != "stress" else week
    status = hit["status"].value_counts(normalize=True)
    over = t[t["official_pct_out"] > 1.05]
    worst_over = over.sort_values("official_pct_out", ascending=False).drop_duplicates("fips").head(3)
    return {
        "storm_id": storm.id,
        "first_week_hit_ok": round(float(status.get("ok", 0.0)), 3),
        "first_week_hit_cant_see": round(float(status.get("cant_see", 0.0)), 3),
        "not_measurable_counties": int(t.loc[t["status"] == "not_measurable", "fips"].nunique()),
        "counties": int(t["fips"].nunique()),
        "overcount_county_nights": len(over),
        "worst_overcounts": [{"fips": r.fips, "night": str(r.night), "official_pct_out": round(float(r.official_pct_out), 2)}
                             for r in worst_over.itertuples()],
        "hit_counties_without_customers": sorted(t.loc[(t["wind_band"] >= HIT_BAND) & t["customers"].isna(), "fips"].unique()),
        "uncovered_states": sorted({f[:2] for f in t.loc[~t["covered"], "fips"]}),
    }


def range_coverage(preds: pd.DataFrame, ranges, truth: str = "official_pct_out") -> dict:
    """Share of held-out official values inside the 80% ranges: all usable rows, and hit counties after landfall."""
    from blackout.model import apply_overcount_rule

    clean = apply_overcount_rule(preds, truth)
    usable = clean[(clean["status"] == "ok") & clean["covered"] & np.isfinite(clean[truth])
                   & np.isfinite(clean["pred_pct_out"])]
    lo, hi = ranges.interval(usable["pred_pct_out"].to_numpy())
    inside = (usable[truth].to_numpy() >= lo - 1e-12) & (usable[truth].to_numpy() <= hi + 1e-12)
    landfall = usable["storm_id"].map({s.id: s.landfall for s in load_storms()})
    event = (usable["wind_band"] >= HIT_BAND).to_numpy() & (usable["night"] >= landfall).to_numpy()
    return {"all_rows": round(float(inside.mean()), 3) if len(inside) else None, "rows": len(inside),
            "hit_event_rows": round(float(inside[event].mean()), 3) if event.any() else None,
            "hit_event_count": int(event.sum())}


def score_frame(rows: pd.DataFrame, storms: list[Storm]) -> pd.DataFrame:
    """evaluate.scorecard for every method at +-60, 30 and 90, in evaluate's combined layout."""
    from blackout.evaluate import PRED_COLUMNS, scorecard

    out = []
    for method, column in PRED_COLUMNS.items():
        for window in (60, 30, 90):
            card = scorecard(rows.assign(pred_pct_out=rows[column]), window, storms)
            out.append(card.assign(method=method, window=window))
    frame = pd.concat(out, ignore_index=True)
    return frame[["method", "window", *[c for c in frame.columns if c not in ("method", "window")]]]


def predictions_frame(table: pd.DataFrame, est: np.ndarray, ranges) -> pd.DataFrame:
    """storm_id, fips, night, status, est, lo, hi: the file export.py reads (NaN unless status is ok)."""
    est = np.where(table["status"].to_numpy() == "ok", est, np.nan)
    lo, hi = ranges.interval(est)
    return pd.DataFrame({"storm_id": table["storm_id"].to_numpy(), "fips": table["fips"].to_numpy(),
                         "night": table["night"].to_numpy(), "status": table["status"].to_numpy(),
                         "est": est, "lo": lo, "hi": hi})


def _loso_ranges(main_rows: pd.DataFrame, fit, storms: list[Storm]):
    """Leave-one-storm-out predictions for one method and the ranges learned from their misses."""
    from blackout.evaluate import loso
    from blackout.ranges import fit_ranges

    preds = loso(main_rows, lambda train: fit(train, storms), storms)
    return preds, fit_ranges(preds, storms=storms)


def _window_check(checks: object, window: int) -> dict | None:
    """A storm's pass-bar check at `window`: keys are ints in memory and strings after a JSON round trip."""
    check = checks.get(window, checks.get(str(window))) if isinstance(checks, dict) else None
    return check if isinstance(check, dict) and "passes" in check else None


def verdict(pass_bar: dict, drop: dict | None = None, window: int = 60) -> str:
    """The committed rule (decision log, "Pass bar, written before the lockbox opens"): pass if every locked storm
    passes at ±60, partial if one does, fail if none. A storm the drop rule removed for clouds, or one with no scored
    result, leaves the verdict to the other storm alone, and the verdict says so; with no storm left, "no verdict".
    `pass_bar` is `results["pass_bar"]`; `drop` maps storm_id to `table.drop_check`'s output. Stress storms never
    appear in either, so they never move the verdict."""
    drop = drop or {}
    scored, left_out = {}, []
    for sid in sorted(set(pass_bar) | set(drop)):
        if sid in drop and drop[sid]["dropped"]:
            left_out.append(f"{sid} dropped by the drop rule")
            continue
        check = _window_check(pass_bar.get(sid), window)
        if check is None:
            entry = pass_bar.get(sid)
            note = entry.get("note", "no result") if isinstance(entry, dict) else "no result"
            left_out.append(f"{sid} not scored: {note}")
            continue
        scored[sid] = bool(check["passes"])
    if not scored:
        return f"{NO_VERDICT} ({'; '.join(left_out)})" if left_out else NO_VERDICT
    label = "pass" if all(scored.values()) else "partial" if any(scored.values()) else "fail"
    if not left_out:
        return label
    return f"{label} (covers {' and '.join(scored)} alone; {'; '.join(left_out)})"


def opening_paths(processed: Path, reopen_reason: str | None = None, now: pd.Timestamp | None = None) -> dict[str, Path]:
    """Where a run may write (D-12): the first opening writes into `processed`; once its result or the opening marker
    exists, a run refuses unless it gives `reopen_reason`, and then writes `lockbox_result_<UTC stamp>.json` and every
    other output under `reopen_<UTC stamp>/`, never over the record."""
    processed = Path(processed)
    first, marker = processed / RESULT_FILE, processed / OPENED_MARKER
    opened = first.exists() or marker.exists()
    if reopen_reason is None:
        if opened:
            found = first if first.exists() else marker  # only the marker: a first run crashed after opening
            raise LockboxOpenedError(
                f"{found} exists: the lockbox was opened once and its first result is the record (D-12). To look "
                f"again, run `blackout lockbox --reopen \"<reason>\"`: it writes lockbox_result_<UTC time>.json "
                "beside the record, never over it, and the reason must be logged in docs/decision-log.md")
        return {"folder": processed, "result": first, "marker": marker}
    if not isinstance(reopen_reason, str) or not reopen_reason.strip():
        raise ValueError("reopen_reason must say, in words, why the lockbox is opened again (decision log, D-12)")
    if not opened:
        raise FileNotFoundError(f"nothing to reopen: {first} does not exist; run without reopen_reason")
    stamp = (now if now is not None else pd.Timestamp.now(tz="UTC")).strftime(STAMP)
    result, folder = processed / f"lockbox_result_{stamp}.json", processed / f"reopen_{stamp}"
    if result.exists() or folder.exists():
        raise FileExistsError(f"{result.name} or {folder.name} already exists: a reopen never overwrites")
    return {"folder": folder, "result": result, "marker": folder / OPENED_MARKER}


def _mark_opened(marker: Path, reopen_reason: str | None) -> None:
    """Written before the first locked table is read, so even a run that crashes afterwards leaves a trace."""
    head, dirty = git_state()
    write_json(marker, {"opened_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "git_head": head,
                        "working_tree_dirty": dirty, "reopen_reason": reopen_reason})


def _score_held_storm(storm: Storm, table: pd.DataFrame, fits: dict, ranges, folder: Path) -> tuple[pd.DataFrame, dict]:
    """Predict one locked or stress storm with the final fits, write its predictions, return (rows, result entries)."""
    rows = table.assign(**{column: model.predict(table) for column, model in fits.items()},
                        pred_nothing=np.where(table["status"] == "ok", 0.0, np.nan))
    predictions_frame(rows, rows["pred_hybrid"].to_numpy(), ranges).to_parquet(
        folder / f"predictions_{storm.id}.parquet", index=False)
    hybrid_rows = rows.assign(pred_pct_out=rows["pred_hybrid"])
    entries = {"pass_bar" if storm.role == "lockbox" else "stress": {w: pass_bar_check(rows, storm, w) for w in WINDOWS},
               "hybrid": {w: pass_bar_check(hybrid_rows, storm, w) for w in WINDOWS}}
    if storm.role == "lockbox":
        entries["drop_rule"] = drop_check(rows, storm)
        entries["trigger"] = {"isotonic": trigger_view(rows, storm), "hybrid": trigger_view(hybrid_rows, storm)}
    return rows, entries


def _range_and_noaa20_sections(curve_loso, curve_ranges, hybrid_loso, hybrid_ranges, storms: list[Storm]) -> dict:
    ian = next((s for s in storms if s.id == "ian2022"), None)
    return {"ranges": {"isotonic": curve_ranges.to_frame().to_dict("records"),
                       "hybrid": hybrid_ranges.to_frame().to_dict("records")},
            "range_coverage_loso": {"isotonic": range_coverage(curve_loso, curve_ranges),
                                    "hybrid": range_coverage(hybrid_loso, hybrid_ranges)},
            "noaa20": noaa20_agreement([s for s in storms if s.id in ("ian2022", "ida2021", "beryl2024")]),
            "lee_noaa20": lee_on_noaa20(ian) if ian else {"note": "no Ian record"}}


def _score_held_storms(others: list[Storm], fits: dict, ranges, folder: Path, storms: list[Storm]) -> dict:
    """Score every locked and stress storm with the final fits and write their predictions and score table: the
    `pass_bar`, `hybrid`, `stress`, `trigger` and `drop_rule` sections, plus the satellite test once anything scored."""
    from blackout.evaluate import satellite_increment

    sections: dict = {"pass_bar": {}, "hybrid": {}, "stress": {}, "trigger": {}, "drop_rule": {}}
    scored = []
    for storm in others:
        if not table_path(storm).exists():
            sections["pass_bar" if storm.role == "lockbox" else "stress"][storm.id] = {"note": "table missing"}
            continue
        rows, entries = _score_held_storm(storm, pd.read_parquet(table_path(storm)), fits, ranges, folder)
        scored.append(rows)
        for section, value in entries.items():
            sections[section][storm.id] = value
    if not scored:
        return sections
    all_scored = pd.concat(scored, ignore_index=True)
    score_frame(all_scored, storms).to_parquet(folder / SCORES_FINAL_FILE, index=False)
    # The pre-registered secondary test (decision log, "Model choice"): hybrid minus wind + timing per storm.
    increment = satellite_increment(all_scored, storms).to_dict("records")
    sat_verdict, per_storm, _ = satellite_test(increment, sorted(s.id for s in others if s.role == "lockbox"))
    return {**sections, "satellite_increment": increment, "satellite_test": {"verdict": sat_verdict, "per_storm": per_storm}}


def run_final(processed: Path | None = None, reopen_reason: str | None = None) -> dict:
    """Open the lockbox once.

    The pass bar is judged on the pre-registered isotonic curve, exactly as committed. The hybrid (satellite + wind +
    timing; decision log "Model choice", logged before this ran) is scored on the same rows beside it and supplies
    the app's estimates and ranges. Main storms get leave-one-storm-out predictions; Helene, Milton and Uri get the
    final fits on all eight main storms (`final=True`). Opened once, it refuses to run again (`LockboxOpenedError`,
    D-12); given `reopen_reason` it writes a new, timestamped result beside the first (`opening_paths`). `processed`
    defaults to `table.PROCESSED` as it is when called (the CLI passes nothing), never to a folder bound at import.
    """
    from blackout.hybrid import fit_hybrid, fit_wind_timing
    from blackout.model import WindOnly, fit_translation
    from blackout.ranges import fit_ranges

    paths = opening_paths(table_mod.PROCESSED if processed is None else processed, reopen_reason)
    folder = paths["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    storms = load_storms()
    main = [s for s in storms if s.role == "main"]
    others = [s for s in storms if s.role != "main"]
    main_rows = load_tables(main, strict=True)
    curve_loso, curve_ranges = _loso_ranges(main_rows, fit_translation, storms)
    hybrid_loso, hybrid_ranges = _loso_ranges(main_rows, fit_hybrid, storms)
    for storm in main:
        rows = hybrid_loso[hybrid_loso["storm_id"] == storm.id]
        if not rows.empty:
            predictions_frame(rows, rows["pred_pct_out"].to_numpy(), hybrid_ranges).to_parquet(
                folder / f"predictions_{storm.id}.parquet", index=False)
    _mark_opened(paths["marker"], reopen_reason)  # before the first read of a locked table
    held_tables = [pd.read_parquet(table_path(s))[["fips", "night"]] for s in others if table_path(s).exists()]
    train_rows, shared = (drop_shared_county_nights(main_rows, pd.concat(held_tables, ignore_index=True))
                          if held_tables else (main_rows, 0))
    fits = {"pred_pct_out": fit_translation(train_rows, storms, final=True),
            "pred_wind_only": WindOnly.fit(train_rows, storms, final=True),  # row-weighted mean for Uri's band -1
            "pred_hybrid": fit_hybrid(train_rows, storms, final=True),
            "pred_wind_timing": fit_wind_timing(train_rows, storms, final=True)}
    final_ranges = fit_ranges(hybrid_loso, storms=storms, final=True)
    # run_at_utc is taken before the held-out storms are scored, as the recorded run did (D-20, "One run").
    prov = {**provenance(main, main_rows), "training_rows_dropped_as_shared_county_nights": shared}
    sections = _score_held_storms(others, fits, final_ranges, folder, storms)
    results = {**sections, "provenance": prov, "verdict": verdict(sections["pass_bar"], sections["drop_rule"]),
               **_range_and_noaa20_sections(curve_loso, curve_ranges, hybrid_loso, hybrid_ranges, storms)}
    if reopen_reason is not None:
        results = {**results, "reopen": {"reason": reopen_reason, "first_result": RESULT_FILE,
                                         "result": paths["result"].name, "outputs": folder.name}}
    write_json(paths["result"], results)
    return results


# --- the scorecard's lockbox section ---------------------------------------------------------------------------------

def _fmt(value, digits: int = 2, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def _yes(flag: bool | None) -> str:
    return "n/a" if flag is None else ("yes" if flag else "no")


def _check_rows(checks: dict, label: str) -> list[str]:
    """One pass-bar table for a storm: the three conditions at +-60, 30 and 90."""
    lines = [f"**{label}**", "", ("| Window | Rows | Error: curve (pp) | Error: wind-only (pp) | Beats wind-only | "
             "Change agreement | ≥ 0.3 | Restore-day error (days) | ≤ 2 | Passes |"), "|---|---|---|---|---|---|---|---|---|---|"]
    for window in ("60", "30", "90", 60, 30, 90):
        c = checks.get(window) if isinstance(checks, dict) else None
        if not c or not isinstance(c, dict) or "mae_pp_curve" not in c:
            continue
        lines.append(f"| ±{window} | {c['rows_scored']:,} | {_fmt(c['mae_pp_curve'])} | {_fmt(c['mae_pp_wind_only'])} | "
                     f"{_yes(c['beats_wind_only'])} | {_fmt(c['first_difference_spearman'], 3)} | {_yes(c['agreement_ok'])} | "
                     f"{_fmt(c['restore_day_median_error'], 1)} | {_yes(c['restore_ok'])} | **{_yes(c['passes'])}** |")
    return [*lines, ""]


MIN_BIG_ROWS = 10  # a locked storm needs this many scored county-nights >= 10% out to be evaluable at all
MIN_HALF_ROWS = 10  # and this many >= 50% out for the AUC condition to count
# Every key the test reads from an evaluate.satellite_increment row; a row lacking one is an error, never a default.
INCREMENT_KEYS = ("storm_id", "rows_big", "rows_half", "mae_big_hybrid", "mae_big_wind_timing", "mae_big_diff",
                  "auc_hybrid", "auc_wind_timing", "auc_diff")


def _increment_rows(increment: list[dict]) -> dict[str, dict]:
    for r in increment:
        if missing := [key for key in INCREMENT_KEYS if key not in r]:
            raise KeyError(f"satellite_increment row {r.get('storm_id', '?')!r} lacks {missing}")
    return {r["storm_id"]: r for r in increment}


def satellite_test(increment: list[dict], locked: list[str]) -> tuple[str, dict, list[str]]:
    """The hybrid's pre-registered test with its edge rules (decision log, 2026-11-08, correction note). Per locked
    storm: the error condition needs MIN_BIG_ROWS county-nights at least 10% out, or the storm is not evaluable; the
    AUC condition needs MIN_HALF_ROWS at least half out and a defined AUC, or the test rests on the error condition
    alone. A missing storm (drop rule, no table) is not evaluable and the verdict covers the other, as the pass bar
    does. Returns (verdict, per-storm detail, table rows)."""
    rows = _increment_rows(increment)
    per_storm, lines = {}, []
    for sid in locked:
        r = rows.get(sid)
        if r is None or r["rows_big"] < MIN_BIG_ROWS:
            per_storm[sid] = {"evaluable": False, "reason": "missing" if r is None else f"only {r['rows_big']} rows >= 10% out"}
            lines.append(f"| {sid} | {'n/a' if r is None else r['rows_big']} | not evaluable | n/a | n/a | n/a | not evaluable |")
            continue
        err_ok = r["mae_big_diff"] is not None and np.isfinite(r["mae_big_diff"]) and r["mae_big_diff"] < 0
        auc_defined = (r["rows_half"] >= MIN_HALF_ROWS and r["auc_diff"] is not None and np.isfinite(r["auc_diff"]))
        auc_ok = bool(auc_defined and r["auc_diff"] > 0)
        passes = bool(err_ok and (auc_ok or not auc_defined))
        per_storm[sid] = {"evaluable": True, "error_lower": bool(err_ok), "auc_evaluable": bool(auc_defined),
                          "auc_higher": auc_ok if auc_defined else None, "passes": passes}
        auc_text = (f"{_fmt(r['auc_hybrid'], 3)} vs {_fmt(r['auc_wind_timing'], 3)} ({_fmt(r['auc_diff'], 3)})"
                    if auc_defined else f"n/a ({r['rows_half']} rows >= 50% out)")
        lines.append(f"| {sid} | {r['rows_big']:,} | {_fmt(r['mae_big_hybrid'], 1)} vs {_fmt(r['mae_big_wind_timing'], 1)} "
                     f"({_fmt(r['mae_big_diff'], 1)}) | {_yes(err_ok)} | {auc_text} | "
                     f"{_yes(auc_ok) if auc_defined else 'rests on error'} | **{_yes(passes)}** |")
    real = [d["passes"] for d in per_storm.values() if d["evaluable"]]
    if not real:
        verdict = "not evaluable"
    elif all(real):
        verdict = "yes" if len(real) == len(locked) else "yes (on the evaluable storm only)"
    elif any(real):
        verdict = "partial"
    else:
        verdict = "no"
    return verdict, per_storm, lines


def render_lockbox(results: dict, integrity: list[str] | None = None) -> list[str]:
    """Markdown for docs/scorecard.md from lockbox_result.json: the verdict first, then every number behind it."""
    locked = sorted(results.get("pass_bar", {}))
    out = ["## Lockbox: Helene and Milton, scored once", "",
           (f"**Pass-bar verdict (pre-registered isotonic curve): {results.get('verdict', 'n/a').upper()}.** The bar was "
           "committed before these storms were opened (decision log, \"Pass bar, written before the lockbox opens\"): "
           "beat wind-only on county error, night-to-night agreement of at least 0.3, and a median restore-day "
           "error of at most 2 days, at ±60."), ""]
    for sid in locked:
        checks = results["pass_bar"][sid]
        if "note" in checks:
            out += [f"**{sid}:** {checks['note']}", ""]
            continue
        out += _check_rows(checks, f"{sid}: the pre-registered curve")
    out += list(integrity or [])  # S1a: the integrity checks on the recorded opening, when the record exists
    hybrid = results.get("hybrid", {})
    if hybrid:
        out += ["### The hybrid (secondary, post hoc): for information", "",
                ("The same three conditions, run on the hybrid. It was designed after the main storms were scored, so "
                "this is not its pre-registered test."), ""]
        for sid in sorted(hybrid):
            if "note" not in hybrid[sid]:
                out += _check_rows(hybrid[sid], f"{sid}: the hybrid")
    increment = results.get("satellite_increment")
    if increment:
        verdict, _, lines = satellite_test(increment, locked)
        out += ["### The hybrid's pre-registered test: does the satellite add to wind + timing?", "",
                (f"**Verdict: {verdict.upper()}.** On each locked storm the hybrid must beat `wind_timing` on error where "
                 "the official count is at least 10% out and on AUC for at least half out (decision log, \"Model "
                 "choice\" and its correction note: a storm needs 10 county-nights at least 10% out to count, and 10 "
                 "at least half out for the AUC condition). The differences are the evidence; the label is a sign "
                 "test on two storms."), "",
                ("| Storm | Rows ≥10% out | Error ≥10%: hybrid vs wind+timing (pp) | Lower | AUC ≥50%: hybrid vs "
                 "wind+timing | Higher | Passes |"), "|---|---|---|---|---|---|---|", *lines, ""]
    stress = results.get("stress", {})
    for sid, checks in sorted(stress.items()):
        out += ["### Uri, the stress test (snow)", "",
                ("Scored separately. The EAGLE-I dropout constants were tuned partly on Uri, and snow makes counties read "
                "brighter than their baseline (docs/failures.md, section 4), so this is neither a clean test nor a fair "
                "one for the method."), ""]
        if "note" not in checks:
            out += _check_rows(checks, f"{sid}: the pre-registered curve")
    trigger = results.get("trigger", {})
    if trigger:
        out += ["### Trigger view: \"county above 50% out at 72 hours\"", "",
                ("Basis risk for a parametric trigger on the locked storms: where an estimate-based trigger would have "
                "paid correctly, paid wrongly, or missed, against EAGLE-I at 72 hours after landfall."), "",
                "| Storm | Model | Paid correctly | Paid wrongly | Missed | Correctly unpaid | Unknown (can't see) |",
                "|---|---|---|---|---|---|---|"]
        for sid, by_model in sorted(trigger.items()):
            for model, t in sorted(by_model.items()):
                out.append(f"| {sid} | {model} | {t['paid_correctly']} | {t['paid_wrongly']} | {t['missed']} | "
                           f"{t['correctly_unpaid']} | {t['unknown']} |")
        out.append("")
    coverage = results.get("range_coverage_loso")
    if coverage:
        out += ["### Range calibration (leave-one-storm-out, main storms)", "",
                "Share of held-out official values inside the 80% ranges; the target is about 80%.", "",
                "| Model | All scored rows | Hit counties after landfall |", "|---|---|---|"]
        for model, c in sorted(coverage.items()):
            out.append(f"| {model} | {_fmt(c.get('all_rows'), 3)} ({c.get('rows', 0):,} rows) | "
                       f"{_fmt(c.get('hit_event_rows'), 3)} ({c.get('hit_event_count', 0):,} rows) |")
        out.append("")
    noaa = results.get("noaa20")
    if noaa:
        out += ["### NOAA-20 cross-check", "",
                "The same counties and nights seen by both satellites, uncorrected % darker.", "",
                "| Storm | County-nights both clear | Spearman | Storm nights | Spearman, storm nights | Median |difference| (pp) |",
                "|---|---|---|---|---|---|"]
        for r in noaa:
            if "note" in r:
                out.append(f"| {r['storm_id']} | {r['note']} | | | | |")
            else:
                out.append(f"| {r['storm_id']} | {r.get('pairs', 0):,} | {_fmt(r.get('spearman'), 3)} | {r.get('event_pairs', 0):,} | "
                           f"{_fmt(r.get('event_spearman'), 3)} | {_fmt(r.get('median_abs_diff_pp'), 1)} |")
        lee = results.get("lee_noaa20", {})
        if lee and "note" not in lee:
            out += ["", (f"Lee County on NOAA-20: darkest night {lee['darkest_night']} ({_fmt(lee['darkest_pct'], 3)} darker), "
                    f"official peak night {lee['official_peak_night']}; half-recovery {lee['half_recovery_dark']} against "
                    f"EAGLE-I's {lee['half_recovery_official']} ({lee['recovery_gap_nights']} nights).")]
        out.append("")
    return out


# --- S1a: integrity of the recorded opening (test plan §0.3) ----------------------------------------------------------

FROZEN_RESULT = REPO / "docs/lockbox_result.json"
PASS_BAR_COMMIT, MODEL_CHOICE_COMMIT = "2f534f9", "2187e37"
PREDICTIONS_WINDOW_MINUTES = 30
EXPECTED_ROLES = {"main": 8, "lockbox": 2, "stress": 1}
RESULT_WORD = {True: "pass", False: "fail", None: "not checked"}


def _check(check_id: str, name: str, passed: bool | None, detail: str) -> dict:
    return {"id": check_id, "check": name, "passed": passed, "detail": detail}


def _git_descends(repo: Path, head: str, ancestors: tuple[str, ...]) -> bool | None:
    """True when `head` descends from every ancestor, False when it does not, None without the history."""
    try:
        codes = [subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=repo, capture_output=True,
                                check=False).returncode for commit in ancestors]
    except OSError:
        return None
    return None if any(code not in (0, 1) for code in codes) else all(code == 0 for code in codes)


def _git_code_matches(repo: Path, head: str, hashes: dict[str, str]) -> bool | None:
    """Do the recorded 16-digit hashes equal the files at `head`? None without the history."""
    try:
        blobs = {name: subprocess.run(["git", "show", f"{head}:src/blackout/{name}"], cwd=repo, capture_output=True,
                                      check=True).stdout for name in hashes}
    except (OSError, subprocess.CalledProcessError):
        return None
    return all(hashlib.sha256(blob).hexdigest()[:16] == hashes[name] for name, blob in blobs.items())


def _dirty_tree_disclosed(log: Path) -> bool:
    """Does the decision log's D-20 entry name `working_tree_dirty`? Only text after the first "D-20" counts, and a
    log without that entry discloses nothing."""
    text = log.read_text() if log.exists() else ""
    return "D-20" in text and "working_tree_dirty" in text.split("D-20", 1)[1]


def _check_provenance(result: dict, repo: Path) -> list[dict]:
    """LB-41: ancestry, code hashes, the training tables, and a clean (or disclosed) working tree."""
    prov = result["provenance"]
    head = prov["git_head"] or ""
    descends = _git_descends(repo, head, (PASS_BAR_COMMIT, MODEL_CHOICE_COMMIT)) if head else None
    code = _git_code_matches(repo, head, prov["code_sha256_16"]) if head else None
    tables = prov["training_tables"]
    beryl = {(t["table"], t["satellite"]) for t in tables if t["storm_id"] == "beryl2024"}
    own = (len(tables) == EXPECTED_ROLES["main"]
           and all(t["table"] == f"county_nights_{t['storm_id']}.parquet" for t in tables))
    dirty = prov["working_tree_dirty"]
    disclosed = _dirty_tree_disclosed(repo / "docs/decision-log.md")
    return [
        _check("LB-41a", "the recorded commit descends from the pass bar and the model choice", descends,
               f"git_head `{head[:7] or 'none'}`; pass bar `{PASS_BAR_COMMIT}`, model choice `{MODEL_CHOICE_COMMIT}`"
               + ("" if descends is not None else "; no git history here")),
        _check("LB-41b", "the hashed model code is that commit's", code,
               ", ".join(f"{n} {h}" for n, h in prov["code_sha256_16"].items())
               + ("" if code is not None else "; no git history here")),
        _check("LB-41c", "eight main training tables, each the storm's own, Beryl's from NOAA-20",
               own and beryl == {("county_nights_beryl2024.parquet", "VJ146A2")},
               f"{len(tables)} tables; beryl2024: {', '.join(' '.join(b) for b in sorted(beryl)) or 'absent'}"),
        _check("LB-41d", "the working tree was clean at the run, or D-20 discloses it", dirty is False or disclosed,
               f"working_tree_dirty: {dirty}" + ("; disclosed in D-20" if dirty and disclosed else "")),
    ]


def _check_frozen(record: dict, frozen: Path) -> dict:
    """LB-45: the committed copy hashes as the record says."""
    digest = hashlib.sha256(frozen.read_bytes()).hexdigest() if frozen.exists() else None
    return _check("LB-45", "the record is frozen", digest == record["result_sha256"],
                  f"`{record['result_file']}` sha256 {digest[:16] + '…' if digest else 'file missing'}")


def _check_inputs(record: dict) -> dict:
    """LB-44: the run's inputs are recorded, and none of them was rebuilt after the run."""
    from collections import Counter

    tables = record["tables"]
    roles = Counter(t["role"] for t in tables)
    newer = [t["table"] for t in [*tables, *record.get("cross_check_tables", [])] if t["newer_than_run"]]
    passed = dict(roles) == EXPECTED_ROLES and not newer and not record["rebuilt_after_run"]
    return _check("LB-44", "the inputs are recorded and none is newer than the run", passed,
                  f"{len(tables)} tables hashed ({', '.join(f'{n} {r}' for r, n in sorted(roles.items()))}); "
                  + ("none rebuilt after the run" if not newer else "rebuilt after the run: " + ", ".join(newer)))


def _check_one_run(record: dict) -> dict:
    """LB-41, one run: every predictions file was written within minutes of run_at_utc."""
    preds = record["predictions"]
    spread = max((abs(p["minutes_from_run"]) for p in preds), default=None)
    return _check("LB-41e", f"every predictions file was written within {PREDICTIONS_WINDOW_MINUTES} minutes of the run",
                  bool(preds) and spread <= PREDICTIONS_WINDOW_MINUTES,
                  f"{len(preds)} files, the farthest {spread} min from run_at_utc" if preds else "none recorded")


def _check_models_apart(result: dict) -> dict:
    """LB-36: `pass_bar` holds the curve's numbers and `hybrid` the hybrid's."""
    pairs = [(sid, _window_check(result["pass_bar"][sid], 60), _window_check(result.get("hybrid", {}).get(sid), 60))
             for sid in sorted(result["pass_bar"])]
    scored = [(sid, c, h) for sid, c, h in pairs if c and h]
    passed = bool(scored) and all(c["mae_pp_curve"] != h["mae_pp_curve"] for _, c, h in scored)
    return _check("LB-36", "the verdict comes from the curve; the hybrid is scored apart", passed,
                  "; ".join(f"{sid}: curve {c['mae_pp_curve']} pp, hybrid {h['mae_pp_curve']} pp" for sid, c, h in scored)
                  or "no scored storm")


def _check_satellite(result: dict) -> dict:
    """LB-37: the hybrid's test recomputed from the recorded increment rows under the edge rules."""
    recorded = result["satellite_test"]
    recomputed, per_storm, _ = satellite_test(result["satellite_increment"], sorted(result["pass_bar"]))
    passed = recomputed == recorded["verdict"] and per_storm == recorded["per_storm"]
    return _check("LB-37", "the satellite test follows its edge rules", passed,
                  f"recorded {recorded['verdict']!r}, recomputed {recomputed!r}")


def _check_verdict(result: dict, record: dict) -> dict:
    """LB-40: the verdict under the committed rule, with the drop rule the recorded code did not apply."""
    recomputed = verdict(result["pass_bar"], record["drop_rule"])
    shares = ", ".join(f"{sid} {d['share']}" for sid, d in sorted(record["drop_rule"].items()))
    return _check("LB-40", "the verdict follows the committed rule, drop rule included", recomputed == result["verdict"],
                  f"recorded {result['verdict']!r}, under the committed rule {recomputed!r}; clear-night shares {shares}")


def _check_customers(record: dict) -> dict:
    """LB-43: the locked tables carry the repaired customer counts."""
    check, name = record["customers_check"], "locked truth uses the repaired customers"
    if not check["available"]:
        return _check("LB-43", name, None, check.get("reason", "not checked"))
    per_storm = check["per_storm"]
    return _check("LB-43", name, bool(per_storm) and all(v["match"] for v in per_storm.values()),
                  "; ".join(f"{sid}: {v['differ']} of {v['counties']} counties differ"
                            for sid, v in sorted(per_storm.items())))


def integrity_checks(result: dict, record: dict, repo: Path = REPO, frozen: Path = FROZEN_RESULT) -> list[dict]:
    """§0.3's checks that need only the frozen result, the record of its inputs and the git history: each is
    {"id", "check", "passed", "detail"}, with `passed` None where this machine cannot check (no git history, no
    Census files). The locked tables themselves are re-read by tests/realdata/test_after_opening.py."""
    return [_check_frozen(record, frozen), _check_inputs(record), *_check_provenance(result, repo),
            _check_one_run(record), _check_models_apart(result), _check_satellite(result),
            _check_verdict(result, record), _check_customers(record)]


def render_integrity(record: dict, checks: list[dict]) -> list[str]:
    """Markdown for docs/scorecard.md, S1a: the facts of the recorded opening, then pass or fail per check."""
    env = record["environment"]
    tables = record["tables"]
    newer = [t["table"] for t in tables if t["newer_than_run"]]
    head = (record.get("git_head") or "unknown")[:7]
    return ["### S1a Integrity of the recorded opening", "",
            (f"The record is `{record['result_file']}` (sha256 `{record['result_sha256'][:16]}…`), written by one run "
             f"of `blackout lockbox` at {record['run_at_utc'][:19].replace('T', ' ')} UTC on commit `{head}`. Its "
             f"inputs are in `docs/lockbox_record.json`: {len(tables)} tables hashed, "
             f"{'none rebuilt after the run' if not newer else 'rebuilt after the run: ' + ', '.join(newer)}; "
             f"Python {env['python']}, numpy {env['numpy']}, pandas {env['pandas']}, scikit-learn {env['scikit-learn']}, "
             f"scipy {env['scipy']}, pyarrow {env['pyarrow']}. Each check is recomputed from those files and the git "
             "history; a failed check is disclosed in the decision log (D-20) and never fixed by a rerun (D-12)."), "",
            "| Check | Result | Detail |", "|---|---|---|",
            *[f"| {c['id']} {c['check']} | {RESULT_WORD[c['passed']]} | {c['detail']} |" for c in checks], ""]
