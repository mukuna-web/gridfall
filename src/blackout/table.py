"""The county x night table: satellite nights, EAGLE-I at the pass time, Census and NOAA, per storm (Task 5).

`build_storm` writes data/processed/county_nights_<storm>.parquet. Tiles are fetched into memory one tile at a time
(laads.py), reduced to per-county sums and medians, and dropped, so nothing raw is kept on disk.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import duckdb
import geopandas as gpd
import h5py
import httpx
import numpy as np
import pandas as pd

from blackout import aggregate as agg
from blackout.counties import load_counties
from blackout.laads import LaadsFile, client_for, earthdata_token, fetch_bytes, list_tile_files
from blackout.nightlights import (
    A1_FOR,
    PassNight,
    TileNight,
    clear_mask,
    pass_night_from_h5,
    pass_time_utc,
    tile_ids_for_bbox,
    tile_night_from_h5,
)
from blackout.outages import OutageIndex, coverage_for, flag_dropouts, load_outages
from blackout.storms import Storm
from blackout.winds import NOT_APPLICABLE, parse_hurdat2, storm_track, wind_band_by_county

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data/raw"
INTERIM = REPO / "data/interim"
PROCESSED = REPO / "data/processed"
IMG = REPO / "docs/img"
HURDAT = RAW / "hurdat2/hurdat2-1851-2025-02272026.txt"
COVERAGE = RAW / "eaglei/coverage_history.csv"
OFFICIAL_WINDOWS = (30, 60, 90)
SCORES_LOSO_FILE = "scorecard_loso.parquet"  # written by `blackout evaluate` (main storms)
SCORES_FINAL_FILE = "scorecard_final.parquet"  # written by `blackout lockbox` (Helene, Milton, Uri)
COVERAGE_MIN = 0.8
MIXED_PASS_HOURS = 1.0
FETCH_WORKERS = 6
TILE_SHAPE = (agg.TILE_PIXELS, agg.TILE_PIXELS)  # tests shrink it to keep fake tiles tiny
# Core tiles for the NOAA-20 cross-check: SW Florida (Lee) for Ian and Houston-Matagorda for Beryl. Ida keeps all four
# tiles, because the 30N tile edge runs through southern Louisiana and only 4 parishes sit wholly south of it.
CROSS_CHECK_TILES = {"ian2022": ["h09v06"], "beryl2024": ["h08v06"]}
READ_ERRORS = (OSError, KeyError, ValueError, httpx.HTTPError)  # network, HDF5 and file-name failures
TABLE_COLUMNS = [
    "storm_id", "fips", "night", "satellite",
    "pct_darker", "visible_share", "base_total", "status",
    "sensor_zenith", "lunar_irradiance",
    "official_customers_out", "official_customers_out_30", "official_customers_out_90",
    "official_pct_out", "official_pct_out_30", "official_pct_out_90",
    "customers", "housing_units",
    "pass_utc", "pass_source",
    "wind_band", "coverage", "covered",
]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


# --- EAGLE-I ---------------------------------------------------------------------------------------------------

def eaglei_extract_path(storm: Storm, interim: Path | None = None) -> Path:
    return (Path(interim) if interim is not None else INTERIM) / f"eaglei_{storm.id}.parquet"


def extract_eaglei(storm: Storm, source: Path | None = None, interim: Path | None = None) -> Path:
    """Copy the storm's states and dates (a day either side of the build window) into data/interim, or `interim`."""
    out = eaglei_extract_path(storm, interim)
    if out.exists():
        return out
    source = source or RAW / f"eaglei/eaglei_outages_{storm.landfall.year}.parquet"
    if not source.exists():
        raise FileNotFoundError(f"{source} is missing: run scripts/fetch_eaglei.py {storm.landfall.year}")
    start = pd.Timestamp(storm.baseline_start) - pd.Timedelta(days=1)
    end = pd.Timestamp(storm.window_end) + pd.Timedelta(days=3)
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"""copy (select fips_code, county, state, customers_out, run_start_time from read_parquet('{source}')
                  where list_contains(?, left(fips_code, 2)) and run_start_time >= ? and run_start_time < ?
                  order by run_start_time, fips_code)
            to '{out}' (format parquet, compression zstd)""",
        [sorted(storm.state_prefixes), start.to_pydatetime(), end.to_pydatetime()])
    return out


def load_storm_outages(storm: Storm, interim: Path | None = None) -> pd.DataFrame:
    start = pd.Timestamp(storm.baseline_start, tz="UTC")
    end = pd.Timestamp(storm.window_end, tz="UTC") + pd.Timedelta(days=2)
    outages = load_outages(extract_eaglei(storm, interim=interim), storm.state_prefixes, start, end)
    if outages.empty:
        raise ValueError(f"{storm.id}: no EAGLE-I rows for {storm.states} between {start} and {end}")
    return outages


def official_columns(outages: pd.DataFrame, flags: pd.DataFrame, fips: str, night: date, lon: float,
                     utc_hours: float | None, source: str = "VNP46A1", index: OutageIndex | None = None) -> dict:
    """EAGLE-I at the satellite pass over the county on `night` (file date night + 1): +-60 (headline), 30, 90."""
    when = pass_time_utc(night + timedelta(days=1), lon, utc_hours)
    if index is None:
        index = OutageIndex(outages[outages["fips"].str[:2] == fips[:2]], flags)
    has_time = utc_hours is not None and np.isfinite(utc_hours)
    return {
        "pass_utc": when,
        "pass_source": source if has_time else "formula",
        "official_customers_out": index.at(fips, when, 60),
        "official_customers_out_30": index.at(fips, when, 30),
        "official_customers_out_90": index.at(fips, when, 90),
    }


# --- satellite nights --------------------------------------------------------------------------------------------

@dataclass
class NightReading:
    """One tile on one night, reduced to what the table needs."""

    night: date
    clear: np.ndarray | None  # float32 clear radiance, NaN elsewhere; None when the A2 file is missing
    medians: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)  # name -> (median, count)
    quicklook: np.ndarray | None = None
    problems: list[str] = field(default_factory=list)


def _open(source: LaadsFile | Path, client) -> h5py.File:
    import io

    if isinstance(source, Path):
        return h5py.File(source, "r")
    return h5py.File(io.BytesIO(fetch_bytes(client, source)), "r")


def _read(source: LaadsFile | Path | None, client, kind: str) -> TileNight | PassNight | None:
    if source is None:
        return None
    name = source.name
    with _open(source, client) as h5:
        return tile_night_from_h5(h5, name) if kind == "a2" else pass_night_from_h5(h5, name)


def read_night(night: date, a2: LaadsFile | Path | None, a1: LaadsFile | Path | None, client, labels: np.ndarray,
               n: int, allow_snow: bool) -> NightReading:
    reading = NightReading(night, None)
    try:
        t = _read(a2, client, "a2")
    except READ_ERRORS as err:  # a bad or missing file makes the night unseen, never zero; reported in the summary
        reading.problems.append(f"A2 {night}: {type(err).__name__}: {err}")
        t = None
    try:
        p = _read(a1, client, "a1")
    except READ_ERRORS as err:
        reading.problems.append(f"A1 {night}: {type(err).__name__}: {err}")
        p = None
    if t is None and a2 is None:
        reading.problems.append(f"A2 {night}: not in the archive")
    if a1 is None:  # the pass time then falls back to the formula: say so, or it surfaces only as different numbers
        reading.problems.append(f"A1 {night}: not in the archive")
    if t is not None:
        clear = clear_mask(t, allow_snow)
        reading.clear = np.where(clear, t.radiance, np.float32(np.nan)).astype(np.float32)
        if t.lunar_irradiance is not None:
            reading.medians["lunar_irradiance"] = agg.group_median(t.lunar_irradiance, labels, n)
        reading.quicklook = agg.downsample(reading.clear)
        if p is not None:
            reading.medians["utc_clear"] = agg.group_median(np.where(clear, p.utc_time, np.nan), labels, n)
    if p is not None:
        reading.medians["utc_all"] = agg.group_median(p.utc_time, labels, n)
        reading.medians["sensor_zenith"] = agg.group_median(p.sensor_zenith, labels, n)
    return reading


def _local(product: str, name: str) -> Path | None:
    path = RAW / "blackmarble" / product / name
    return path if path.exists() else None


@dataclass
class TileOutput:
    tile_id: str
    sums: dict[date, dict[str, np.ndarray]]
    medians: dict[date, dict[str, tuple[np.ndarray, np.ndarray]]]
    quicklooks: dict[date, np.ndarray]
    baseline_quicklook: np.ndarray | None
    problems: list[str]


def process_tile(storm: Storm, tile_id: str, labels: np.ndarray, n: int, satellite: str, client) -> TileOutput:
    file_dates = [night + timedelta(days=1) for night in storm.nights]
    a2_files = list_tile_files(client, satellite, tile_id, file_dates[0], file_dates[-1])
    a1_files = list_tile_files(client, A1_FOR[satellite], tile_id, file_dates[0], file_dates[-1])

    def job(night: date) -> NightReading:
        day = night + timedelta(days=1)
        a2, a1 = a2_files.get(day), a1_files.get(day)
        a2_src = (_local(satellite, a2.name) or a2) if a2 else None
        a1_src = (_local(A1_FOR[satellite], a1.name) or a1) if a1 else None
        return read_night(night, a2_src, a1_src, client, labels, n, storm.allow_snow)

    with ThreadPoolExecutor(FETCH_WORKERS) as pool:
        readings = {r.night: r for r in pool.map(job, storm.nights)}
    problems = [p for r in readings.values() for p in r.problems]
    base_stack = [readings[d].clear for d in storm.baseline_nights if readings[d].clear is not None]
    shape = labels.shape
    base = agg.baseline_from_clear(base_stack) if base_stack else np.full(shape, np.nan, np.float32)
    empty = np.full(shape, np.nan, np.float32)
    sums = {night: agg.county_sums(r.clear if r.clear is not None else empty, base, labels, n)
            for night, r in readings.items()}
    return TileOutput(tile_id, sums, {night: r.medians for night, r in readings.items()},
                      {night: r.quicklook for night, r in readings.items() if r.quicklook is not None},
                      agg.downsample(base), problems)


def tiles_for(counties: gpd.GeoDataFrame) -> list[str]:
    tiles = set()
    for west, south, east, north in counties.geometry.bounds.itertuples(index=False):
        tiles.update(tile_ids_for_bbox(west, south, east, north))
    return sorted(tiles)


def _combine_medians(per_tile: list[TileOutput], night: date, name: str, n: int) -> np.ndarray:
    """Each county's median from the tile holding most of its valid pixels (exact for one-tile counties)."""
    best_value, best_count = np.full(n, np.nan), np.zeros(n)
    for out in per_tile:
        pair = out.medians.get(night, {}).get(name)
        if pair is None:
            continue
        value, count = pair
        better = count > best_count
        best_value = np.where(better, value, best_value)
        best_count = np.where(better, count, best_count)
    return best_value


# --- the table ---------------------------------------------------------------------------------------------------

def wind_bands(storm: Storm, counties: gpd.GeoDataFrame) -> pd.Series:
    if storm.role == "stress" or storm.atcf_id is None:
        return pd.Series(NOT_APPLICABLE, index=counties["fips"].to_numpy())
    return wind_band_by_county(storm_track(parse_hurdat2(HURDAT), storm.atcf_id), counties)


def assemble(storm: Storm, satellite: str, counties: gpd.GeoDataFrame, per_tile: list[TileOutput],
             outages: pd.DataFrame, flags: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    n = len(counties)
    fips = counties["fips"].tolist()
    lon = counties.geometry.representative_point().x.to_numpy()
    index = OutageIndex(outages, flags)
    bands = wind_bands(storm, counties)
    coverage = {s: coverage_for(COVERAGE, s, storm.landfall.year) for s in storm.states}
    frames, mixed = [], 0
    for night in storm.nights:
        sums = None
        for out in per_tile:
            sums = agg.add_sums(sums, out.sums[night])
        table = agg.finalize(sums, fips)
        utc_all = _combine_medians(per_tile, night, "utc_all", n)
        utc_clear = _combine_medians(per_tile, night, "utc_clear", n)
        mixed += int(np.sum(np.abs(utc_all - utc_clear) > MIXED_PASS_HOURS))
        official = [official_columns(outages, flags, f, night, x, u, A1_FOR[satellite], index)
                    for f, x, u in zip(fips, lon, utc_all)]
        table = pd.concat([table, pd.DataFrame(official)], axis=1)
        table["sensor_zenith"] = _combine_medians(per_tile, night, "sensor_zenith", n)
        table["lunar_irradiance"] = _combine_medians(per_tile, night, "lunar_irradiance", n)
        table["night"] = night
        frames.append(table)
    out = pd.concat(frames, ignore_index=True)
    by_fips = counties.set_index("fips")
    out["storm_id"] = storm.id
    out["satellite"] = satellite
    out["housing_units"] = out["fips"].map(by_fips["housing_units"]).astype(int)
    out = with_customers(out, counties)
    out["wind_band"] = out["fips"].map(bands).astype(int)
    out["coverage"] = out["fips"].map(by_fips["state"]).map(coverage)
    out["covered"] = out["coverage"] >= COVERAGE_MIN
    out = out[TABLE_COLUMNS].sort_values(["night", "fips"]).reset_index(drop=True)
    return out, {"mixed_pass_county_nights": mixed}


def drop_check(table: pd.DataFrame, storm: Storm, days: int = 7) -> dict:
    """The plan's drop rule: drop a storm when fewer than half its hit counties get an `ok` night within 7 days."""
    window = table[(table["night"] >= storm.landfall) & (table["night"] <= storm.landfall + timedelta(days=days))]
    hit = window[window["wind_band"] >= 34] if (table["wind_band"] >= 0).any() else window
    hit_counties = hit["fips"].nunique()
    seen = hit.loc[hit["status"] == "ok", "fips"].nunique()
    share = seen / hit_counties if hit_counties else 0.0
    return {"hit_counties": int(hit_counties), "hit_with_ok_night": int(seen), "share": round(share, 3),
            "dropped": bool(share < 0.5)}


def save_quicklooks(storm: Storm, per_tile: list[TileOutput], table: pd.DataFrame, satellite: str,
                    img: Path | None = None) -> list[Path]:
    """Baseline, peak night and +7 days, as tile mosaics. The peak night is picked from the satellite alone."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ok = table[(table["status"] == "ok") & (table["night"] >= storm.landfall - timedelta(days=1))
               & (table["night"] <= storm.landfall + timedelta(days=3))]
    if ok.empty:
        return []
    darkening = ok.assign(lost=ok["pct_darker"] * ok["base_total"]).groupby("night")["lost"].sum()
    peak = darkening.idxmax()
    hs = sorted({int(t.tile_id[1:3]) for t in per_tile})
    vs = sorted({int(t.tile_id[4:6]) for t in per_tile})
    size = next(iter(per_tile[0].quicklooks.values())).shape[0] if per_tile[0].quicklooks else 300

    def mosaic(pick) -> np.ndarray:
        canvas = np.full((size * len(vs), size * len(hs)), np.nan, np.float32)
        for out in per_tile:
            image = pick(out)
            if image is None:
                continue
            r, c = vs.index(int(out.tile_id[4:6])), hs.index(int(out.tile_id[1:3]))
            canvas[r * size:(r + 1) * size, c * size:(c + 1) * size] = image
        return canvas

    img_dir = Path(img) if img is not None else IMG
    img_dir.mkdir(parents=True, exist_ok=True)
    tag = table_path(storm, satellite).stem.removeprefix("county_nights_")
    paths = []
    for label, pick, title in (
        ("baseline", lambda o: o.baseline_quicklook, f"{storm.name}: baseline median"),
        ("peak", lambda o: o.quicklooks.get(peak), f"{storm.name}: night of {peak} (darkest)"),
        ("plus7", lambda o: o.quicklooks.get(peak + timedelta(days=7)), f"{storm.name}: night of {peak + timedelta(days=7)}"),
    ):
        fig, ax = plt.subplots(figsize=(6, 6 * len(vs) / len(hs)), dpi=110)
        ax.imshow(np.log10(np.clip(mosaic(pick), 0.3, None)), cmap="magma", vmin=-0.5, vmax=2.5)
        ax.set_title(title + " (clear pixels only; black is cloud or no light)", fontsize=8)
        ax.set_axis_off()
        path = img_dir / f"{tag}_{label}.png"
        fig.savefig(path, bbox_inches="tight", facecolor="black")
        plt.close(fig)
        paths.append(path)
    return paths


def with_customers(table: pd.DataFrame, counties: gpd.GeoDataFrame) -> pd.DataFrame:
    """A copy with `customers` and the official % out columns recomputed from `counties` (repaired counts)."""
    customers = dict(zip(counties["fips"], counties["customers"].astype("Float64").to_numpy(dtype=float,
                                                                                           na_value=np.nan)))
    out = table.copy()
    out["customers"] = out["fips"].map(customers)
    for suffix in ("", "_30", "_90"):
        with np.errstate(divide="ignore", invalid="ignore"):
            out[f"official_pct_out{suffix}"] = out[f"official_customers_out{suffix}"] / out["customers"]
    return out


def refresh_customers(storm: Storm, satellite: str | None = None) -> pd.DataFrame:
    """Rewrite a built table's customer counts and official % out after the customer repair (no tiles needed)."""
    path = table_path(storm, satellite)
    table = with_customers(pd.read_parquet(path), load_counties(storm.states))
    table.to_parquet(path, index=False)
    return table


def table_path(storm: Storm, satellite: str | None = None) -> Path:
    """The storm's own table (built from storm.satellite), or a cross-check table named after the other satellite."""
    satellite = satellite or storm.satellite
    suffix = "" if satellite == storm.satellite else f"_{satellite.lower()}"
    return PROCESSED / f"county_nights_{storm.id}{suffix}.parquet"


def cross_check_counties(counties: gpd.GeoDataFrame, tiles: list[str]) -> gpd.GeoDataFrame:
    """Counties lying wholly inside `tiles`, so a partial-tile build never sums a county from half its pixels."""
    inside = [set(tile_ids_for_bbox(*bounds)) <= set(tiles) for bounds in counties.geometry.bounds.itertuples(index=False)]
    return counties[inside].reset_index(drop=True)


def build_storm(storm: Storm, satellite: str | None = None, token: str | None = None, *,
                counties: gpd.GeoDataFrame | None = None, processed: Path | None = None,
                img: Path | None = None, interim: Path | None = None) -> pd.DataFrame:
    """Build and write <processed>/county_nights_<storm>.parquet (data/processed by default); returns the table.

    `counties` replaces load_counties(storm.states) for a partial rebuild (scripts/reproduce.py rebuilds the three
    sample counties); `processed` and `img` redirect the outputs so a check never overwrites the real tables, and
    `interim` is where the storm's EAGLE-I extract is read from or cut to, in place of the one cached in data/interim.

    The NOAA-20 cross-check (Task 9) builds only the storm's core tiles (CROSS_CHECK_TILES) to save ~2/3 of the
    download; it compares the two satellites on the same counties and nights, so full state coverage is not needed.
    """
    started = time.time()
    satellite = satellite or storm.satellite
    out_dir = Path(processed) if processed is not None else PROCESSED
    counties = load_counties(storm.states) if counties is None else counties.reset_index(drop=True)
    if satellite != storm.satellite and storm.id in CROSS_CHECK_TILES:
        counties = cross_check_counties(counties, CROSS_CHECK_TILES[storm.id])
    outages = load_storm_outages(storm, interim)
    flags = flag_dropouts(outages)
    tiles = tiles_for(counties)
    log(f"{storm.id}: {len(counties)} counties, {len(tiles)} tiles {tiles}, {len(outages):,} EAGLE-I rows, "
        f"{len(flags):,} dropout flags")
    n = len(counties)
    per_tile = []
    with client_for(token or earthdata_token(), timeout=300) as client:
        for tile_id in tiles:
            labels = agg.county_label_grid(tile_id, counties, shape=TILE_SHAPE)
            if not (labels > 0).any():
                continue
            tile_started = time.time()
            per_tile.append(process_tile(storm, tile_id, labels, n, satellite, client))
            log(f"{storm.id} {tile_id}: done in {time.time() - tile_started:.0f}s "
                f"({len(per_tile[-1].problems)} problems)")
    table, extra = assemble(storm, satellite, counties, per_tile, outages, flags)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / table_path(storm, satellite).name
    table.to_parquet(out_path, index=False)
    quicklooks = save_quicklooks(storm, per_tile, table, satellite, img)
    summary = {
        "storm": storm.id, "satellite": satellite, "counties": n, "tiles": [t.tile_id for t in per_tile],
        "nights": len(storm.nights), "rows": len(table),
        "status_counts": table["status"].value_counts().to_dict(),
        "dropout_flags": len(flags), "drop_rule": drop_check(table, storm), **extra,
        "problems": [p for t in per_tile for p in t.problems],
        "quicklooks": [str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p) for p in quicklooks],
        "minutes": round((time.time() - started) / 60, 1),
    }
    out_path.with_suffix(".json").write_text(json.dumps(summary, indent=2, default=str))
    log(f"{storm.id}: wrote {out_path.name} ({len(table):,} rows) in {summary['minutes']} min; "
        f"drop rule {summary['drop_rule']}")
    return table
