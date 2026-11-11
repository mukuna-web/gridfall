"""Static JSON for the app (Task 10): one folder per storm under app/public/data, plus index.json.

The app has no server, so everything it shows is computed here and checked against schema/export.schema.json, the
contract the app's types mirror. Three rules shape every file:
- "Can't see" is never zero (Review Focus 4). An estimate is written only where the satellite saw the county
  (status "ok"); every other cell is null, so the app hatches it instead of coloring it 0%, and the exposure sums
  count its policies as unknown.
- Every number is finite or null. A browser's JSON.parse rejects a bare NaN or Infinity, so the writer refuses them
  (allow_nan=False), and every file is validated and serialized before any file is written.
- Fractions are 0..1. EAGLE-I over-counts (more customers out than the county has) are cleaned by
  model.apply_overcount_rule, or shown as null when that rule isn't available; they are never capped silently.
After writing, every export is read back whole and checked across files (verify_export), so a folder the app can
load inconsistently is never left behind quietly.
"""

from __future__ import annotations

import importlib
import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import geopandas as gpd
import jsonschema
import numpy as np
import pandas as pd
from shapely.geometry import mapping

from blackout.counties import load_counties
from blackout.portfolio import INFLATED_SHARE, SEED, make_claims, make_portfolio
from blackout.storms import get_storm

LOCKBOX_RESULT = "lockbox_result.json"  # written by final.run_final; its absence means the lockbox is still shut


class LockboxClosedError(RuntimeError):
    """A lockbox storm was asked for before the pass bar was scored."""


class ExportIntegrityError(ValueError):
    """A written export fails its own re-read: schema, index entry, county keys, night order, ranges or the book."""


REPO = Path(__file__).resolve().parents[2]
APP_DATA = REPO / "app/public/data"
PROCESSED = REPO / "data/processed"
SAMPLE = REPO / "data/sample"
SCHEMA_PATH = REPO / "schema/export.schema.json"
SAMPLE_ID = "ian2022_sample"
SAMPLE_NAME = "Ian (sample: Lee, Charlotte, Collier)"
SAMPLE_SOURCE = "ian2022"
WAITING_PERIODS = (24, 48, 72)
DEFAULT_WAITING_PERIOD = 72
RESTORED_AT = 0.10  # "restored" means 10% out or less, as in evaluate.official_restore_day and ranges
SCORE_WINDOW = 60
SCORE_METHODS = ("isotonic", "wind_only", "nothing")
OPTIONAL_METHODS = ("hybrid", "wind_timing")  # written only when scored (decision log, "Model choice")
SCORE_METRICS = ("mae_pp", "peak_total_est", "peak_total_official", "catch_rate_50", "false_alarm_50",
                 "restore_day_err", "measurable_share")
STATUSES = ("ok", "cant_see", "not_measurable")
NO_ESTIMATE = "no_estimate"  # internal only: a visible night the fit left blank, kept out of ranges' "ok" nights
SIMPLIFY_DEG = 0.005
COORD_DECIMALS = 5  # about 1 m, far finer than the 0.005-degree (about 500 m) simplification
FRACTION_DECIMALS = 4  # 0.01 percentage points, already finer than EAGLE-I can check
DAY_DECIMALS = 2
SLACK = 1e-9  # float noise allowed around 0 and 1 before a fraction counts as out of range
TABLE_NEEDS = ("fips", "night", "satellite", "status", "official_pct_out")
PREDICTION_NEEDS = ("fips", "night", "status", "est", "lo", "hi")
COUNTY_NEEDS = ("fips", "name", "state", "housing_units", "customers", "geometry")
STORM_FILES = {  # file name -> its entry in the schema's $defs
    "meta.json": "meta", "counties.geojson": "counties", "states.geojson": "states", "nights.json": "nights",
    "restoration.json": "restoration", "exposure.json": "exposure", "claims.json": "claims",
    "scorecard.json": "scorecard",
}
PRETTY = frozenset({"index.json", "meta.json", "scorecard.json"})  # small files people read; the rest stay compact


@dataclass(frozen=True)
class StormInfo:
    """What the export needs to know about a storm. The sample reuses Ian's dates under its own id and name, and
    `source_id` is the storm its table and scorecard rows are filed under."""

    id: str
    name: str
    landfall: date
    baseline_end: date
    role: str
    source_id: str
    landfall_time: pd.Timestamp | None = None  # waiting periods count from here (Storm.landfall_time)


@dataclass(frozen=True)
class CountyEstimate:
    """A county's estimated restoration interval (days after landfall) and its % out bracket at each waiting period."""

    restored: tuple[float | None, float | None]
    brackets: dict[int, tuple[float, float] | None]


# --- entry points ------------------------------------------------------------------------------------------------

def export_storm(storm_id: str, out: Path = APP_DATA, predictions: Path | None = None,
                 scorecard: pd.DataFrame | None = None) -> Path:
    """Write <out>/<storm_id>/ from data/processed and list the storm in <out>/index.json; returns the folder.

    Reads county_nights_<id>.parquet (required) and predictions_<id>.parquet, the final fit's est/lo/hi (final.py).
    When the default predictions file doesn't exist yet the export still runs, with every estimate null and a note
    saying why, so the app can be built before the fit. Counties come from load_counties, which needs the Census
    files in data/raw/census. `scorecard` holds evaluate's rows (columns method and the metrics, optionally storm_id
    and window); without it the scorecard is written unscored, with null metrics and a note.
    """
    storm = get_storm(storm_id)
    if storm.role == "lockbox" and not (PROCESSED / LOCKBOX_RESULT).exists():
        raise LockboxClosedError(f"{storm.id} is a lockbox storm: run `uv run blackout lockbox` first, which scores it "
                                 "once against the committed pass bar and writes " + LOCKBOX_RESULT)
    table = read_table(PROCESSED / f"county_nights_{storm.id}.parquet", {storm.id},
                       f"build it first (uv run blackout build --storm {storm.id})")
    fit = read_predictions(predictions, PROCESSED / f"predictions_{storm.id}.parquet", {storm.id})
    counties = clean_counties(load_counties(storm.states))
    info = StormInfo(storm.id, storm.name, storm.landfall, storm.baseline_end, storm.role, storm.id,
                     storm.landfall_time)
    return write_export(info, table, fit, counties, Path(out), scorecard)


def export_sample(out: Path = APP_DATA, scorecard: pd.DataFrame | None = None) -> Path:
    """Write the bundled Ian sample (Lee, Charlotte, Collier) as storm "ian2022_sample", from data/sample alone.

    No network and no Census files, so a fresh clone can run the app without any NASA data. The three inputs
    (county_nights_ian_sample.parquet, predictions_ian_sample.parquet, counties_ian_sample.geojson) are committed.
    """
    ian = get_storm(SAMPLE_SOURCE)
    ids = {ian.id, SAMPLE_ID}
    table = read_table(SAMPLE / "county_nights_ian_sample.parquet", ids,
                       "the Ian sample is committed under data/sample (restore it with git)")
    fit = read_predictions(None, SAMPLE / "predictions_ian_sample.parquet", ids)
    shapes = SAMPLE / "counties_ian_sample.geojson"
    if not shapes.exists():
        raise FileNotFoundError(f"{shapes} is missing: the Ian sample needs its county shapes")
    counties = clean_counties(gpd.read_file(shapes))
    info = StormInfo(SAMPLE_ID, SAMPLE_NAME, ian.landfall, ian.baseline_end, ian.role, ian.id, ian.landfall_time)
    return write_export(info, table, fit, counties, Path(out), scorecard)


def expected_policies_out(exposure: dict, hours: int) -> dict[str, float | int]:
    """Policies expected without power `hours` after landfall: a low-high range plus the policies nobody can see.

    Python twin of the app's expectedPoliciesOut (app/src/lib/exposure.ts); both must agree on
    tests/fixtures/exposure_toy.json. A county whose bracket is null (or has a null end) adds its policies to
    unknown_policies and nothing to low or high: unknown is never counted as zero. Like the app, each bracket is read
    as (min, max), so the two agree even on a pair written high-first.
    """
    if hours not in WAITING_PERIODS:
        raise ValueError(f"hours must be one of the waiting periods {WAITING_PERIODS}, got {hours!r}")
    low, high, unknown = 0.0, 0.0, 0
    for fips, county in exposure.items():
        if str(hours) not in county["at"]:
            raise ValueError(f"{fips}: exposure has no bracket for {hours} h")
        policies = county["home"] + county["business"]
        bracket = county["at"][str(hours)]
        if bracket is None or None in bracket:
            unknown += policies
            continue
        low += policies * min(bracket)
        high += policies * max(bracket)
    return {"low": low, "high": high, "unknown_policies": unknown}


def write_export(info: StormInfo, table: pd.DataFrame, fit: pd.DataFrame | None, counties: gpd.GeoDataFrame,
                 out: Path, scorecard: pd.DataFrame | None = None) -> Path:
    """Build every file, check and serialize all of them, then write: a failed check leaves nothing half-written."""
    files = build_files(info, table, fit, counties, scorecard)
    index = merged_index(out / "index.json", index_entry(files["meta.json"]))
    schema = load_schema()
    for name, payload in files.items():
        check_file(STORM_FILES[name], payload, f"{info.id}/{name}", schema)
    check_file("index", index, "index.json", schema)
    folder = out / info.id
    texts = {folder / name: serialize(name, payload) for name, payload in files.items()}
    texts[out / "index.json"] = serialize("index.json", index)
    folder.mkdir(parents=True, exist_ok=True)
    for path, text in texts.items():
        write_text(path, text)
    verify_export(folder)  # read back as the app will; an inconsistent folder raises here, never later in a browser
    return folder


# --- inputs ------------------------------------------------------------------------------------------------------

def read_table(path: Path, storm_ids: set[str], hint: str) -> pd.DataFrame:
    """The county x night table (table.py), with keys checked: 5-digit fips, dates, known statuses, no repeats."""
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: {hint}")
    return clean_rows(pd.read_parquet(path), TABLE_NEEDS, storm_ids, path.name)


def read_predictions(explicit: Path | None, default: Path, storm_ids: set[str]) -> pd.DataFrame | None:
    """The fit's est/lo/hi, null wherever the fit's status isn't ok. None when the default file doesn't exist yet;
    a missing file that was asked for by name is an error."""
    path = Path(explicit) if explicit is not None else default
    if not path.exists():
        if explicit is not None:
            raise FileNotFoundError(f"{path} is missing")
        return None
    fit = clean_rows(pd.read_parquet(path), PREDICTION_NEEDS, storm_ids, path.name)
    return fit.assign(**{column: checked_fractions(fit, column, path.name) for column in ("est", "lo", "hi")})


def clean_rows(frame: pd.DataFrame, needs: tuple[str, ...], storm_ids: set[str], label: str) -> pd.DataFrame:
    """A copy with fips as 5-character strings and night as datetime.date, after checking the keys."""
    missing = [column for column in needs if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} lacks columns {missing}")
    if "storm_id" in frame.columns:
        found = set(frame["storm_id"].dropna().astype(str))
        if not found <= storm_ids:
            raise ValueError(f"{label} holds rows for {sorted(found - storm_ids)}, expected {sorted(storm_ids)}")
    fips = frame["fips"].astype(str).str.zfill(5)
    malformed = sorted(set(fips[~fips.str.fullmatch(r"\d{5}")]))
    if malformed:
        raise ValueError(f"{label}: fips must be 5 digits, got {malformed[:5]}")
    unknown = sorted(set(frame["status"].astype(str)) - set(STATUSES))
    if unknown or frame["status"].isna().any():
        raise ValueError(f"{label}: status must be one of {STATUSES}, got {unknown or ['<missing>']}")
    nights = pd.to_datetime(frame["night"])
    if nights.isna().any():
        raise ValueError(f"{label}: {int(nights.isna().sum())} rows have no night")
    cleaned = frame.assign(fips=fips, night=nights.dt.date)
    if cleaned.duplicated(["fips", "night"]).any():
        raise ValueError(f"{label} lists a county-night more than once")
    return cleaned


def checked_fractions(fit: pd.DataFrame, column: str, label: str) -> pd.Series:
    """`column` as fractions on the fit's ok rows and NaN elsewhere; anything outside [0, 1] there is a fit bug."""
    values = pd.to_numeric(fit[column], errors="raise").astype(float)
    values = values.where(np.isfinite(values))  # an infinite estimate is no estimate, never 100%
    ok = fit["status"] == "ok"
    outside = ok & ((values < -SLACK) | (values > 1 + SLACK))
    if outside.any():
        raise ValueError(f"{label}: {column} must be a fraction in [0, 1] on ok rows; {int(outside.sum())} rows "
                         f"are outside it, e.g. {values[outside].iloc[0]}")
    return values.clip(0.0, 1.0).where(ok)


def clean_counties(counties: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """fips, name, state, housing_units (int), customers (Int64, <NA> when MCC.csv has none) and geometry in
    EPSG:4326, sorted by fips. Shapes from the Census or from the sample GeoJSON go through the same checks."""
    missing = [column for column in COUNTY_NEEDS if column not in counties.columns]
    if missing:
        raise ValueError(f"counties lack columns {missing}")
    fips = counties["fips"].astype(str).str.zfill(5)
    if (~fips.str.fullmatch(r"\d{5}")).any() or fips.duplicated().any():
        raise ValueError("counties need unique 5-digit fips")
    if counties["name"].isna().any() or not counties["state"].astype(str).str.fullmatch(r"[A-Z]{2}").all():
        raise ValueError("every county needs a name and a 2-letter USPS state")
    geometry = counties.geometry if counties.crs is None else counties.geometry.to_crs("EPSG:4326")
    if (~geometry.geom_type.isin(["Polygon", "MultiPolygon"]) | geometry.is_empty).any():
        raise ValueError("county geometries must be non-empty polygons")
    clean = gpd.GeoDataFrame({
        "fips": fips.to_numpy(), "name": counties["name"].astype(str).to_numpy(),
        "state": counties["state"].astype(str).to_numpy(),
        "housing_units": whole_numbers(counties["housing_units"], "housing_units", allow_missing=False).astype(int),
        "customers": whole_numbers(counties["customers"], "customers", allow_missing=True),
    }, geometry=geometry.to_numpy(), crs="EPSG:4326")
    return clean.sort_values("fips").reset_index(drop=True)


def whole_numbers(values: pd.Series, label: str, allow_missing: bool) -> pd.Series:
    numbers = pd.to_numeric(values, errors="raise").astype("Float64").reset_index(drop=True)
    if numbers.isna().any() and not allow_missing:
        raise ValueError(f"{label} is missing for some counties")
    present = numbers.dropna()
    if (present < 0).any() or (present != present.round()).any():
        raise ValueError(f"{label} must be whole, non-negative numbers")
    return numbers.round().astype("Int64")


def optional_module(name: str) -> ModuleType | None:
    """The module, or None when it doesn't exist yet. Any other import error is a real bug and propagates."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as err:
        if err.name != name:
            raise
        return None


# --- the county x night cells ------------------------------------------------------------------------------------

def build_files(info: StormInfo, table: pd.DataFrame, fit: pd.DataFrame | None, counties: gpd.GeoDataFrame,
                scorecard: pd.DataFrame | None = None) -> dict[str, object]:
    """Every per-storm file, keyed by file name, as plain Python objects ready for JSON."""
    nights = export_nights(table, info)
    shown = table[table["night"].isin(nights)]
    official, official_notes = official_fractions(shown)
    cells, cell_notes = county_night_cells(shown.assign(official=official), fit, list(counties["fips"]), nights)
    frames = {fips: frame.reset_index(drop=True) for fips, frame in cells.groupby("fips", sort=True)}
    restore = {fips: official_restore(frame, info.landfall) for fips, frame in frames.items()}
    estimates = {fips: county_estimate(frame, info.landfall, info.landfall_time) for fips, frame in frames.items()}
    portfolio = make_portfolio(counties)
    claims = make_claims(portfolio, {fips: day for fips, day in restore.items()
                                     if documented_outage(frames[fips], info.landfall)})
    notes = [*standard_notes(portfolio, claims), *official_notes, *cell_notes, *coverage_notes(shown, counties),
             *customer_notes(counties)]
    return {
        "meta.json": meta_json(info, satellite(table), nights, notes),
        "counties.geojson": counties_geojson(counties),
        "states.geojson": states_geojson(counties),
        "nights.json": {fips: [night_entry(row) for row in frame.itertuples(index=False)]
                        for fips, frame in frames.items()},
        "restoration.json": {fips: {"est_lo": estimates[fips].restored[0], "est_hi": estimates[fips].restored[1],
                                    "official_day": rounded(restore[fips], DAY_DECIMALS)} for fips in frames},
        "exposure.json": exposure_json(portfolio, estimates),
        "claims.json": [{"claim_id": str(c.claim_id), "policy_id": str(c.policy_id), "fips": str(c.fips),
                         "claimed_days_out": float(c.claimed_days_out)} for c in claims.itertuples(index=False)],
        "scorecard.json": scorecard_json(info, scorecard),
    }


def export_nights(table: pd.DataFrame, info: StormInfo) -> list[date]:
    """The table's nights after the baseline window. Baseline nights stay out: each sits inside its own baseline
    median, so its "% darker" leans toward zero and says nothing about the storm."""
    nights = sorted(night for night in table["night"].unique() if night > info.baseline_end)
    if not nights:
        raise ValueError(f"{info.id}: the table has no night after the baseline window (ends {info.baseline_end})")
    return nights


def official_fractions(table: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """The headline official fraction (±60) per row, cleaned of over-counts, and notes saying how.

    model.apply_overcount_rule decides what an over-count is when model.py has it. Whatever it leaves above 1 (or
    everything above 1, without the rule) is shown as null, never capped, and counted in a note.
    """
    raw = pd.to_numeric(table["official_pct_out"], errors="raise").astype(float)
    rule = getattr(optional_module("blackout.model"), "apply_overcount_rule", None)
    cleaned = raw if rule is None else pd.to_numeric(rule(table)["official_pct_out"], errors="raise").astype(float)
    if len(cleaned) != len(raw):
        raise ValueError("apply_overcount_rule must keep every row")
    cleaned = pd.Series(cleaned.to_numpy(), index=table.index)
    over = (cleaned > 1 + SLACK) | np.isinf(cleaned)
    negative = cleaned < -SLACK
    kept = cleaned.where(~over & ~negative).clip(0.0, 1.0)
    dropped = int((raw.notna() & kept.isna() & ~negative).sum())
    clipped = int(((raw > 1 + SLACK) & (kept == 1.0)).sum())
    notes = []
    if rule is not None:
        notes.append(f"official is cleaned by model.apply_overcount_rule: {dropped} county-night(s) it treats as "
                     "EAGLE-I over-counts (more customers out than the county has) are shown as null, and "
                     f"{clipped} slightly above 100% are shown as 100%.")
    elif dropped:
        notes.append(f"{dropped} official reading(s) above 100% of the county's customers (EAGLE-I over-counts) are "
                     "shown as null, not capped (model.apply_overcount_rule was not available).")
    if negative.any():
        notes.append(f"{int(negative.sum())} negative official reading(s) are shown as null.")
    return kept, notes


def county_night_cells(table: pd.DataFrame, fit: pd.DataFrame | None, fips: list[str],
                       nights: list[date]) -> tuple[pd.DataFrame, list[str]]:
    """One row per county and exported night: status, official, est, lo, hi (and pass_utc when the table has it).

    The table says what the satellite saw. The fit can only take an estimate away (its non-ok status replaces the
    table's ok; a non-ok table status and its reason always stand), never show one where the table can't see, so a
    buggy fit can't turn a blind county-night into a number. est/lo/hi stay
    null unless the shown status is ok; a county-night with no table row at all shows as can't see.
    """
    grid = pd.MultiIndex.from_product([fips, nights], names=["fips", "night"]).to_frame(index=False)
    keep = ["fips", "night", "status", "official", *(["pass_utc"] if "pass_utc" in table.columns else [])]
    cells = grid.merge(table[keep], on=["fips", "night"], how="left", validate="one_to_one")
    notes = []
    absent = int(cells["status"].isna().sum())
    if absent:
        notes.append(f"{absent} county-night(s) have no row in the county x night table; they show as can't see.")
    unshaped = sorted(set(table["fips"]) - set(fips))
    if unshaped:
        notes.append(f"{len(unshaped)} table county(ies) have no shape and are left out: {unshaped[:5]}.")
    status = cells["status"].fillna("cant_see")
    if fit is None:
        notes.append("No predictions file yet (the final fit writes it), so est, lo and hi are null on every night.")
        return cells.assign(status=status, est=np.nan, lo=np.nan, hi=np.nan), notes
    fitted = grid.merge(fit[list(PREDICTION_NEEDS)], on=["fips", "night"], how="left", validate="one_to_one")
    has_fit = fitted["status"].notna()
    differs = int((has_fit & (fitted["status"] != status)).sum())
    if differs:
        notes.append(f"{differs} county-night(s) where the fit's status differs from the table's; an estimate is "
                     "shown only where both say ok.")
    status = fitted["status"].where(has_fit & (fitted["status"] != "ok") & (status == "ok"), status)
    est = fitted["est"].where(status == "ok")
    blank = int(((status == "ok") & est.isna()).sum())
    if blank:
        notes.append(f"{blank} visible county-night(s) have no estimate from the fit; they show as unknown.")
    # The ranges are learned from held-out misses, so a biased model's range can sit entirely below or above its
    # own point. A range that excludes the point reads as an error, so the point is folded in; coverage only rises.
    lo = np.fmin(fitted["lo"], est).where(est.notna())
    hi = np.fmax(fitted["hi"], est).where(est.notna())
    return cells.assign(status=status, est=est, lo=lo, hi=hi), notes


# --- restoration and exposure ------------------------------------------------------------------------------------

def official_restore(frame: pd.DataFrame, landfall: date) -> float:
    """evaluate.official_restore_day on the county's official fractions from landfall on, indexed by days after
    landfall. Earlier nights stay out: before Milton they hold Helene's outages. NaN when nothing is known.

    A county never above the restore threshold after landfall was never out by this measure, so it is back by its
    first reading (day 0 when EAGLE-I reported the landfall night), confirmed by a reading a day or more later as in
    evaluate's 24-hour rule; the convention ranges.restoration_interval uses for estimates. Nights EAGLE-I missed are
    unknown, never "not out", so they can't make it day 0 (Florence: 23 such counties). evaluate's rule looks for the
    drop after the peak, so it would date such a county to the night after its tiny peak (Ian: hundreds of counties,
    many at day 19-20), and the county card would show an outage that never happened.
    """
    after = frame[frame["night"] >= landfall]
    series = pd.Series(after["official"].to_numpy(dtype=float),
                       index=[(night - landfall).days for night in after["night"]])
    known = series.dropna().sort_index()
    if known.empty:
        return math.nan
    if not (known > RESTORED_AT).any():
        first = float(known.index[0])
        return first if (known.index >= first + 1).any() else math.nan
    evaluate = importlib.import_module("blackout.evaluate")
    day = evaluate.official_restore_day(series, threshold=RESTORED_AT)
    return math.nan if day is None else float(day)


def documented_outage(frame: pd.DataFrame, landfall: date) -> bool:
    """EAGLE-I showed the county above the restore threshold after landfall. Only such a county anchors synthetic
    claims, so an "honest" claim never sits in a county that may not have lost power at all."""
    return bool((frame.loc[frame["night"] >= landfall, "official"] > RESTORED_AT).any())


def estimate_view(frame: pd.DataFrame) -> pd.DataFrame:
    """night, status, est (and pass_utc) for ranges.py, with a visible night that has no estimate marked as not ok,
    so it can never be read as a seen night."""
    columns = ["night", "status", "est", *(["pass_utc"] if "pass_utc" in frame.columns else [])]
    blank = (frame["status"] == "ok") & frame["est"].isna()
    return frame[columns].assign(status=frame["status"].where(~blank, NO_ESTIMATE))


def county_estimate(frame: pd.DataFrame, landfall: date, landfall_time: pd.Timestamp | None = None) -> CountyEstimate:
    """The county's restoration interval and hour brackets from ranges.py; unknown (None) when the satellite never
    gave it an estimate, without asking ranges.py."""
    view = estimate_view(frame)
    if not (view["status"] == "ok").any():
        return CountyEstimate((None, None), dict.fromkeys(WAITING_PERIODS))
    ranges = importlib.import_module("blackout.ranges")
    lo, hi = ranges.restoration_interval(view[["night", "status", "est"]], landfall, threshold=RESTORED_AT)
    start = landfall_time if landfall_time is not None else landfall
    brackets = {hours: ranges.pct_out_bracket(view, start, hours=hours) for hours in WAITING_PERIODS}
    return CountyEstimate((rounded(lo, DAY_DECIMALS), rounded(hi, DAY_DECIMALS)), brackets)


def exposure_json(portfolio: pd.DataFrame, estimates: dict[str, CountyEstimate]) -> dict:
    """Policies per county by kind, and each waiting period's [low, high] fraction out (null when unknown)."""
    counts = pd.crosstab(portfolio["fips"], portfolio["kind"]).reindex(
        index=list(estimates), columns=["home", "business"], fill_value=0)
    return {fips: {"home": int(counts.at[fips, "home"]), "business": int(counts.at[fips, "business"]),
                   "at": {str(hours): bracket_json(estimate.brackets[hours]) for hours in WAITING_PERIODS}}
            for fips, estimate in estimates.items()}


def bracket_json(bracket: tuple[float, float] | None) -> list[float] | None:
    """[low, high], sorted so it reads as a range; null when either side is unknown."""
    if bracket is None:
        return None
    ends = [rounded(value, FRACTION_DECIMALS) for value in bracket]
    return None if None in ends else sorted(ends)


# --- small JSON pieces -------------------------------------------------------------------------------------------

def rounded(value: object, decimals: int) -> float | None:
    """A JSON number: rounded, with None, NaN and infinities as null (unknown), never as 0."""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, decimals) + 0.0  # + 0.0 turns -0.0 into 0.0


def night_entry(row) -> dict:
    return {"night": row.night.isoformat(), "status": row.status, "est": rounded(row.est, FRACTION_DECIMALS),
            "lo": rounded(row.lo, FRACTION_DECIMALS), "hi": rounded(row.hi, FRACTION_DECIMALS),
            "official": rounded(row.official, FRACTION_DECIMALS)}


def geometry_json(shape) -> dict:
    mapped = mapping(shape)
    return {"type": mapped["type"], "coordinates": rounded_coordinates(mapped["coordinates"])}


def rounded_coordinates(coordinates) -> list:
    if len(coordinates) and isinstance(coordinates[0], (int, float)):  # a position: [lon, lat]
        return [round(float(coordinates[0]), COORD_DECIMALS) + 0.0, round(float(coordinates[1]), COORD_DECIMALS) + 0.0]
    return [rounded_coordinates(part) for part in coordinates]


def counties_geojson(counties: gpd.GeoDataFrame) -> dict:
    shapes = counties.geometry.simplify(SIMPLIFY_DEG, preserve_topology=True)
    features = [
        {"type": "Feature", "geometry": geometry_json(shape),
         "properties": {"fips": fips, "name": name, "state": state, "housing_units": int(housing),
                        "customers": None if pd.isna(customers) else int(customers)}}
        for fips, name, state, housing, customers, shape in zip(
            counties["fips"], counties["name"], counties["state"], counties["housing_units"], counties["customers"],
            shapes)
    ]
    return {"type": "FeatureCollection", "features": features}


def states_geojson(counties: gpd.GeoDataFrame) -> dict:
    """State outlines: the full-detail counties dissolved first, then simplified, so borders don't leave slivers."""
    states = counties[["state", "geometry"]].dissolve(by="state").geometry
    shapes = states.simplify(SIMPLIFY_DEG, preserve_topology=True)
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": geometry_json(shape), "properties": {"state": state}}
                         for state, shape in shapes.items()]}


def satellite(table: pd.DataFrame) -> str:
    found = sorted(set(table["satellite"].dropna().astype(str)))
    if len(found) != 1:
        raise ValueError(f"expected one satellite in the table, found {found}")
    return found[0]


def generated_stamp() -> str:
    """The export's clock. SOURCE_DATE_EPOCH (seconds since 1970, UTC), when set, fixes it so a committed export or
    fixture is byte-reproducible (test-plan D-9); otherwise now. A malformed value is an error, not "now"."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is None or epoch == "":
        return datetime.now(UTC).isoformat(timespec="seconds")
    try:
        moment = datetime.fromtimestamp(int(epoch), UTC)
    except (ValueError, OverflowError, OSError) as err:
        raise ValueError(f"SOURCE_DATE_EPOCH must be whole seconds since 1970, got {epoch!r}") from err
    return moment.isoformat(timespec="seconds")


def meta_json(info: StormInfo, satellite_name: str, nights: list[date], notes: list[str]) -> dict:
    return {"id": info.id, "name": info.name, "landfall": info.landfall.isoformat(), "role": info.role,
            "satellite": satellite_name, "nights": [night.isoformat() for night in nights],
            "waiting_periods": list(WAITING_PERIODS), "default_waiting_period": DEFAULT_WAITING_PERIOD,
            "generated": generated_stamp(), "notes": notes}


def standard_notes(portfolio: pd.DataFrame, claims: pd.DataFrame) -> list[str]:
    business = float((portfolio["kind"] == "business").mean()) if len(portfolio) else 0.0
    estimates = ("est, lo and hi are the estimated fraction of customers without power and its 80% range, from "
                 "Black Marble night lights. They are null where the satellite can't see the county or it is too dark "
                 "to measure: unknown, never zero.")
    official = ("official is EAGLE-I's customers out at the satellite pass (median of the runs within ±60 minutes, "
                "feed-dropout runs removed) over the county's customer count.")
    book = (f"Policies and claims are synthetic: {len(portfolio):,} policies placed by Census housing units "
            f"({business:.0%} business, seed {SEED}) and {len(claims)} claims, about {INFLATED_SHARE:.0%} of them "
            "deliberately inflated past the county's official restoration day.")
    notes = [estimates, official, book]
    if claims.empty:
        notes.append("No county shows an official outage (above 10% out) with a restoration day, so there are no "
                     "synthetic claims.")
    return notes


def coverage_notes(table: pd.DataFrame, counties: gpd.GeoDataFrame) -> list[str]:
    """States where EAGLE-I covers too few customers for the curve to train on (table.py's `covered`)."""
    if not {"coverage", "covered"} <= set(table.columns):
        return []
    state_of = dict(zip(counties["fips"], counties["state"]))
    rows = table.assign(state=table["fips"].map(state_of)).dropna(subset=["state"])
    low = rows.loc[~rows["covered"].astype(bool)].groupby("state")["coverage"].first()
    if low.empty:
        return []
    listed = ", ".join(f"{state} ({share:.0%})" if np.isfinite(share) else f"{state} (unknown)"
                       for state, share in low.items())
    return [(f"EAGLE-I covers too few customers in {listed} for the curve to train on, so official numbers there "
             "undercount.")]


def customer_notes(counties: gpd.GeoDataFrame) -> list[str]:
    missing = int(counties["customers"].isna().sum())
    if not missing:
        return []
    return [f"{missing} county(ies) have no EAGLE-I customer count (MCC.csv), so official is null there."]


# --- scorecard ---------------------------------------------------------------------------------------------------

def scorecard_json(info: StormInfo, frame: pd.DataFrame | None, window: int = SCORE_WINDOW) -> dict:
    """The curve and the two simple guesses on this storm; null metrics and a note when it isn't scored yet."""
    rows = scorecard_rows(frame, {info.id, info.source_id}, window)
    if rows.empty:
        return {"storm_id": info.id, "window": window,
                "methods": {method: dict.fromkeys(SCORE_METRICS) for method in SCORE_METHODS},
                "note": f"Not scored yet: no scorecard row for {info.source_id} at ±{window} minutes."}
    methods = {}
    present = [m for m in OPTIONAL_METHODS if (rows["method"] == m).any()]
    for method in (*SCORE_METHODS, *present):
        match = rows[rows["method"] == method]
        if len(match) > 1:
            raise ValueError(f"scorecard has {len(match)} rows for {method} on {info.source_id}")
        first = match.iloc[0] if len(match) else None
        methods[method] = {metric: None if first is None or metric not in rows.columns else rounded(first[metric], 4)
                           for metric in SCORE_METRICS}
    return {"storm_id": info.id, "window": window, "methods": methods, "note": score_note(info.role, window)}


def scorecard_rows(frame: pd.DataFrame | None, storm_ids: set[str], window: int) -> pd.DataFrame:
    """evaluate's rows for this storm and window. A storm index or a `storm` column is read as storm_id."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["method"])
    rows = frame.reset_index() if frame.index.name in ("storm_id", "storm") else frame
    rows = rows.rename(columns={"storm": "storm_id"})
    if "method" not in rows.columns:
        raise ValueError(f"scorecard needs a method column ({', '.join(SCORE_METHODS)})")
    if "storm_id" in rows.columns:
        rows = rows[rows["storm_id"].astype(str).isin(storm_ids)]
    if "window" in rows.columns:
        rows = rows[rows["window"] == window]
    return rows


def score_note(role: str, window: int) -> str:
    base = (f"Scored against EAGLE-I at the satellite pass (±{window}-minute window). mae_pp is in percentage "
            "points; peak totals are customers.")
    caveat = {
        "main": " Leave-one-storm-out: the curve was fit without this storm.",
        "lockbox": " Lockbox storm: scored once, after the pass bar was committed.",
        "stress": " Stress test: the EAGLE-I dropout constants were tuned partly on Uri, so this is not a clean test.",
    }
    return base + caveat.get(role, "")


# --- index, schema and writing -----------------------------------------------------------------------------------

def index_entry(meta: dict) -> dict:
    return {key: meta[key] for key in ("id", "name", "landfall", "role", "satellite")}


def merged_index(path: Path, entry: dict) -> dict:
    """index.json with `entry` added or replaced. Other storms are kept, sorted by landfall; an index that can't be
    read is an error rather than something to overwrite."""
    storms = []
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise ValueError(f"{path} is not valid JSON; fix or delete it before exporting") from err
        check_file("index", current, str(path))
        storms = [storm for storm in current["storms"] if storm["id"] != entry["id"]]
    return {"storms": sorted([*storms, entry], key=lambda storm: (storm["landfall"], storm["id"]))}


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def check_file(kind: str, payload: object, label: str, schema: dict | None = None) -> None:
    """Validate one file against its $defs entry in schema/export.schema.json."""
    schema = schema or load_schema()
    validator = jsonschema.Draft202012Validator(
        {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{kind}"})
    try:
        validator.validate(payload)
    except jsonschema.ValidationError as err:
        raise ValueError(f"{label} breaks the export schema at {err.json_path}: {err.message}") from err


def serialize(name: str, payload: object) -> str:
    """JSON text; allow_nan=False makes a stray NaN or Infinity an error here instead of in the browser."""
    if name in PRETTY:
        return json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2) + "\n"
    return json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":")) + "\n"


def write_text(path: Path, text: str) -> None:
    """Write through a temporary file, so the app never reads half a file."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


# --- verification of a written export ----------------------------------------------------------------------------

def verify_export(folder: Path) -> dict[str, int]:
    """Read a written storm folder back as the app will, check it whole, and return counts (test-plan PX-02).

    Every file parses strictly (a bare NaN or Infinity is refused, as a browser's JSON.parse would), validates
    against its entry in the schema, and index.json beside the folder lists the storm exactly as meta.json does.
    Across files: the county fips of counties.geojson are the keys of nights, restoration and exposure; each nights
    list follows meta.nights; lo <= est <= hi wherever there is an estimate, and no range stands without one; the
    exposure book is the seeded portfolio of these counties, county by county; claims carry unique ids, name
    policies of that book in their own county, and sit only where EAGLE-I showed an outage (official_day > 0); the
    scorecard describes this storm. Anything else raises ExportIntegrityError naming the file.
    """
    folder = Path(folder)
    schema = load_schema()
    files = {name: read_verified(folder / name, kind, schema) for name, kind in STORM_FILES.items()}
    index = read_verified(folder.parent / "index.json", "index", schema)
    meta = files["meta.json"]
    if folder.name != meta["id"]:
        raise ExportIntegrityError(f"{folder}: meta.json describes {meta['id']!r}, not this folder")
    if index_entry(meta) not in index["storms"]:
        raise ExportIntegrityError(f"{folder.parent / 'index.json'} does not list {meta['id']} as its meta.json "
                                   "describes it")
    if files["scorecard.json"]["storm_id"] != meta["id"]:
        raise ExportIntegrityError(f"{folder.name}/scorecard.json describes {files['scorecard.json']['storm_id']!r}")
    fips = [feature["properties"]["fips"] for feature in files["counties.geojson"]["features"]]
    for name in ("nights.json", "restoration.json", "exposure.json"):
        if sorted(files[name]) != sorted(fips):
            raise ExportIntegrityError(f"{folder.name}/{name}: its counties are not those of counties.geojson")
    estimates, unseen = check_nights(folder.name, files["nights.json"], meta["nights"])
    policies = check_book(folder.name, files["counties.geojson"], files["exposure.json"], files["claims.json"],
                          files["restoration.json"])
    return {"files": len(files) + 1, "counties": len(fips), "nights": len(meta["nights"]),
            "county_nights": len(fips) * len(meta["nights"]), "estimates": estimates, "unseen": unseen,
            "policies": policies, "claims": len(files["claims.json"])}


def read_verified(path: Path, kind: str, schema: dict) -> object:
    """One file, parsed as strictly as a browser would and validated against its schema entry."""
    if not path.exists():
        raise ExportIntegrityError(f"{path} is missing")

    def refuse(token: str):
        raise ExportIntegrityError(f"{path} holds a bare {token}, which a browser's JSON.parse rejects")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=refuse)
    except json.JSONDecodeError as err:
        raise ExportIntegrityError(f"{path} is not valid JSON: {err}") from err
    try:
        check_file(kind, payload, str(path), schema)
    except ValueError as err:
        raise ExportIntegrityError(f"{path} breaks the export schema: {err}") from err
    return payload


def check_nights(label: str, nights: dict, expected: list[str]) -> tuple[int, int]:
    """Every list follows meta.nights, every range holds its point and no range stands without one; returns
    (estimates, unseen county-nights)."""
    estimates = unseen = 0
    for fips, entries in nights.items():
        if [entry["night"] for entry in entries] != expected:
            raise ExportIntegrityError(f"{label}/nights.json: {fips} does not follow meta.nights")
        for entry in entries:
            if entry["status"] != "ok":
                unseen += 1
            if entry["est"] is None:
                if entry["lo"] is not None or entry["hi"] is not None:
                    raise ExportIntegrityError(f"{label}/nights.json: {fips} on {entry['night']} has a range "
                                               f"[{entry['lo']}, {entry['hi']}] but no estimate")
                continue
            estimates += 1
            if entry["lo"] is None or entry["hi"] is None or not entry["lo"] <= entry["est"] <= entry["hi"]:
                raise ExportIntegrityError(f"{label}/nights.json: {fips} on {entry['night']} has est {entry['est']} "
                                           f"outside [{entry['lo']}, {entry['hi']}]")
    return estimates, unseen


def check_book(label: str, counties: dict, exposure: dict, claims: list, restoration: dict) -> int:
    """The exposure book is the seeded portfolio of these counties and the claims draw on it; returns the policies."""
    properties = [feature["properties"] for feature in counties["features"]]
    frame = pd.DataFrame({"fips": [p["fips"] for p in properties], "housing_units": [p["housing_units"] for p in properties]})
    try:
        book = make_portfolio(frame)
    except ValueError as err:
        raise ExportIntegrityError(f"{label}/counties.geojson cannot carry the book: {err}") from err
    kinds = pd.crosstab(book["fips"], book["kind"]).reindex(index=frame["fips"], columns=["home", "business"],
                                                           fill_value=0)
    for fips, county in exposure.items():
        if (county["home"], county["business"]) != (int(kinds.at[fips, "home"]), int(kinds.at[fips, "business"])):
            raise ExportIntegrityError(f"{label}/exposure.json: {fips} does not hold the seeded book's policies")
    county_of = dict(zip(book["policy_id"], book["fips"]))
    ids = [claim["claim_id"] for claim in claims]
    policies = [claim["policy_id"] for claim in claims]
    if len(set(ids)) != len(ids) or len(set(policies)) != len(policies):
        raise ExportIntegrityError(f"{label}/claims.json repeats a claim or policy id")
    for claim in claims:
        if county_of.get(claim["policy_id"]) != claim["fips"]:
            raise ExportIntegrityError(f"{label}/claims.json: {claim['claim_id']} names policy {claim['policy_id']}, "
                                       f"which is not in {claim['fips']} in the book")
        day = restoration[claim["fips"]]["official_day"]
        if day is None or not day > 0:
            raise ExportIntegrityError(f"{label}/claims.json: {claim['claim_id']} sits in {claim['fips']}, where "
                                       "EAGLE-I showed no outage to claim against")
    return len(book)
