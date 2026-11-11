"""Phase 0 spike: Hurricane Ian in Lee County, FL (12071), night lights vs EAGLE-I outages, night by night.

Written by Claude at the user's request as a Phase 0 spike (see docs/decision-log.md). The method follows
docs/plan.md (Global Constraints, Week 1) and docs/design.md section 6; the Black Marble facts are in
docs/phase0/blackmarble-facts.json. The chart is ian_lee_chart.py, imported by path (python -I skips this folder).
Run from the repo root: uv run python -I scripts/phase0/ian_lee.py [--eaglei-tz UTC]

Reads  data/raw/blackmarble/VNP46A2/**/VNP46A2.A2022*.h09v06*.h5 and, for the pass times, any
       data/raw/blackmarble/VNP46A1/**/VNP46A1.A2022*.h09v06*.h5 (untrusted data: read with h5py, never run),
       data/interim/fl_counties.gpkg (or data/raw/census/cb_2022_us_county_500k.zip when the gpkg is absent),
       data/interim/eaglei_fl_2022-08-20_2022-10-25.parquet and data/raw/eaglei/MCC.csv.
Writes data/interim/phase0_lee_nights.csv (one row per file date), docs/img/phase0_ian_lee.png and the JSON summary
       of the four checks (data/interim/phase0_lee_summary.json, stdout). Exit 1 = an input is missing or unexpected.
"""

import argparse
import datetime as dt
import importlib.util
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import Affine

CHART_SPEC = importlib.util.spec_from_file_location("ian_lee_chart", Path(__file__).with_name("ian_lee_chart.py"))
chart = sys.modules["ian_lee_chart"] = importlib.util.module_from_spec(CHART_SPEC)
CHART_SPEC.loader.exec_module(chart)

REPO = Path(__file__).resolve().parents[2]
TILES_DIR = Path("data/raw/blackmarble/VNP46A2")
A1_DIR = Path("data/raw/blackmarble/VNP46A1")
COUNTIES_GPKG = Path("data/interim/fl_counties.gpkg")
COUNTIES_ZIP = Path("data/raw/census/cb_2022_us_county_500k.zip")
EAGLEI_PARQUET = Path("data/interim/eaglei_fl_2022-08-20_2022-10-25.parquet")
MCC_CSV = Path("data/raw/eaglei/MCC.csv")
OUT_CSV = Path("data/interim/phase0_lee_nights.csv")
OUT_PNG = Path("docs/img/phase0_ian_lee.png")
OUT_JSON = Path("data/interim/phase0_lee_summary.json")

LEE_FIPS = "12071"
TILE, COLLECTION = "h09v06", "002"
TILE_GLOBS = {product: f"{product}.A2022*.{TILE}*.h5" for product in ("VNP46A2", "VNP46A1")}
TILE_NAME = re.compile(r"^(VNP46A[12])\.A(\d{4})(\d{3})\.(h\d{2}v\d{2})\.(\d{3})\.\d{13}\.h5$")

# VNP46A2 Collection 2 (docs/phase0/blackmarble-facts.json: User Guide List 2 p.15, Tables 6 and 8-10 pp.13-17,
# App. B pp.44-45). The gap-filled layer pastes older values into gaps (p.24), so only check 1 reads it.
DATA_GROUP = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"
NTL, GAP_FILLED_NTL = "DNB_BRDF-Corrected_NTL", "Gap_Filled_DNB_BRDF-Corrected_NTL"
LATEST_HQ = "Latest_High_Quality_Retrieval"  # uint8 days; reading it as the age of a filled value is an inference
QUALITY, CLOUD_MASK, SNOW = "Mandatory_Quality_Flag", "QF_Cloud_Mask", "Snow_Flag"
NTL_FILL = -999.9  # stored as float32 -999.9f, so it is matched in the layer's own dtype
CLOUD_MASK_FILL, LATEST_HQ_FILL = 65535, 255
# Mandatory_Quality_Flag (Table 9): 0 high quality; 1 poor (outlier or possible cloud); 2 twilight;
# 3 lunar eclipse; 4 aurora; 5 glint; 255 fill. Only 0 counts as clear.
GOOD_QUALITY, POOR_OUTLIER_OR_CLOUD = (0,), 1
CLEAR_CLOUD = (0, 1)  # QF_Cloud_Mask bits 6-7 (Table 6 p.14): 00 confident clear, 01 probably clear
NO_CLOUD_INFO = 255  # cloud code given to QF_Cloud_Mask fill, so it never counts as clear
NO_SNOW = 0  # Snow_Flag (Table 10 p.17): 0 no snow or ice, 1 snow or ice, 255 fill
# VNP46A1 (Table 5 pp.11-12, App. A pp.40-43): VNP46A2's group and lat/lon, add_offset not offset. UTC_Time: float32
# decimal hours, scale 1, fill -999.9f, valid 0-24. Sensor_Zenith: int16 degrees, scale 0.01, fill -32768, valid 0-9000.
UTC_TIME, SENSOR_ZENITH = "UTC_Time", "Sensor_Zenith"
A1_LAYERS = {UTC_TIME: (-999.9, (0.0, 24.0)), SENSOR_ZENITH: (-32768, (0.0, 90.0))}  # fill, valid range once scaled
PIXEL_DEG = 1 / 240  # 15 arc-seconds: 2400 pixels across a 10-degree tile
GRID_TOL_DEG = 1e-5  # about 1 m: how closely lat/lon must follow the 1/240-degree grid. Float32-precision pixel
# centres must pass, while doubled spacing, a quarter-pixel phase, mixed centres and edges and off-tile grids must fail.

LANDFALL_UTC = pd.Timestamp("2022-09-28 19:05", tz="UTC")  # Cayo Costa, HURDAT2 (docs/phase0/agent-geo.md G3)
BASELINE_FIRST, BASELINE_LAST = dt.date(2022, 8, 26), dt.date(2022, 9, 25)  # file dates, both ends included
MIN_BASELINE_NIGHTS, VISIBLE_SHARE_MIN = 5, 0.5
# A file dated D (UTC) holds the Suomi NPP pass near 01:30 local *mean solar* time on D (about 06:58 UTC, 02:58 EDT,
# at Lee's 81.9 W), which ends the night of D - 1. A night's pass is the median VNP46A1 UTC_Time over the county, else
# 01:30 mean solar time at its representative point; outside 04:00-10:00 UTC on D the night label is wrong: fail fast.
PASS_SOLAR_TIME, PASS_WINDOW_UTC = dt.time(1, 30), (dt.time(4), dt.time(10))
PASS_FROM_A1, PASS_NOMINAL = "VNP46A1", "nominal_solar_time"  # the pass_source values
LOCAL_TZ = "America/New_York"  # Lee County's civil clock: check 3 and the chart's landfall label
EAGLEI_TZ = "UTC"  # clock of EAGLE-I run_start_time; the data paper says UTC (docs/phase0/agent-docs.md D8)
EAGLEI_WINDOW = pd.Timedelta(60, unit="min")
SURGE_SHARES = (0.10, 0.50)
SURGE_SEARCH = (pd.Timestamp("2022-09-27"), pd.Timestamp("2022-09-30"))  # run stamps, on either clock
N_GAP_FILLED_FILES, DARK_PCT = 3, 0.3
# Check 4 (plan, Week 1). Under the night convention the Sep 28 pass came about half a day before landfall and the
# Sep 29 pass about half a day after, so Sep 28 should be seen and lit, and Sep 29 should be the first dark file.
EXPECTED_FIRST_DARK_FILE = dt.date(2022, 9, 29)
EXPECTED_LAST_LIT_FILE = EXPECTED_FIRST_DARK_FILE - dt.timedelta(days=1)
# NASA Earth Observatory image 150431 shows the VIIRS views as they appeared on September 30, 2022, against an August
# composite (https://earthobservatory.nasa.gov/images/150431/power-outages-after-hurricane-ian). The page does not
# say whether that is the UTC file date or the local night; days_after_nasa_date compares it with the file date.
NASA_IMAGE_DATE = dt.date(2022, 9, 30)
CHECK_4_COLUMNS = ("file_date", "night", "pct_darker", "visible_share", "eaglei_pct_out")
GAP_COLUMNS = ("pct_darker_gap_filled", "visible_share_gap_filled", "pct_darker_gap_filled_on_clear_pixels",
               "n_pixels_gap_filled_only", "latest_hq_retrieval_days_median")


class InputError(ValueError):
    """An input is missing, or is not what the guide and the Phase 0 notes describe."""


@dataclass(frozen=True)
class Paths:
    root: Path
    tiles: Path
    a1_tiles: Path
    counties_gpkg: Path
    counties_zip: Path
    eaglei: Path
    mcc: Path
    out_csv: Path
    out_png: Path
    out_json: Path

    @classmethod
    def under(cls, root: Path) -> "Paths":
        parts = (TILES_DIR, A1_DIR, COUNTIES_GPKG, COUNTIES_ZIP, EAGLEI_PARQUET, MCC_CSV, OUT_CSV, OUT_PNG, OUT_JSON)
        return cls(root, *(root / part for part in parts))


@dataclass(frozen=True)
class TileFile:
    path: Path
    file_date: dt.date  # UTC acquisition date D: the night pass early on D, which ends the night of D - 1


@dataclass(frozen=True)
class Grid:
    transform: Affine
    shape: tuple[int, int]
    convention: str  # what the file's lat/lon values mark: "centres" or "edges"


@dataclass(frozen=True)
class Window:
    rows: slice
    cols: slice
    mask: np.ndarray  # county pixels inside the rows x cols box


@dataclass(frozen=True)
class NightPixels:
    """One file's layers over the county pixels: 1-D arrays in the same pixel order for every file."""

    file_date: dt.date
    radiance: np.ndarray  # float64 nW/cm2/sr, NaN where fill or negative
    quality: np.ndarray  # Mandatory_Quality_Flag
    cloud: np.ndarray  # QF_Cloud_Mask bits 6-7 (0-3), NO_CLOUD_INFO where the mask is fill
    snow: np.ndarray  # Snow_Flag


def night_of(file_date: dt.date) -> dt.date:
    """A file dated D (UTC) holds the pass early on D (about 07:00 UTC over Lee), which ends the night of D - 1."""
    return file_date - dt.timedelta(days=1)


def in_baseline(file_date: dt.date) -> bool:
    return BASELINE_FIRST <= file_date <= BASELINE_LAST


def nominal_pass_utc(file_date: dt.date, lon: float) -> pd.Timestamp:
    """01:30 local mean solar time on the file date at `lon` (degrees east): UTC = D 01:30 - lon/15 hours."""
    solar = pd.Timestamp(dt.datetime.combine(file_date, PASS_SOLAR_TIME), tz="UTC")
    return (solar - pd.Timedelta(lon / 15, unit="h")).round("s")


def check_timezone(name: str) -> None:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InputError(f"--eaglei-tz {name!r} is not an IANA time zone, such as UTC or America/New_York") from exc


def missing_inputs(paths: Paths) -> list[str]:
    missing, glob = [], TILE_GLOBS["VNP46A2"]  # VNP46A1 is optional: without it a night takes the nominal pass
    if not (paths.tiles.is_dir() and any(p.is_file() for p in paths.tiles.rglob(glob))):
        missing.append(f"VNP46A2 tiles {paths.tiles}/**/{glob}: run scripts/phase0/download_blackmarble.py "
                       "(it needs EARTHDATA_TOKEN)")
    if not (paths.counties_gpkg.is_file() or paths.counties_zip.is_file()):
        missing.append(f"county polygon: {paths.counties_gpkg}, or {paths.counties_zip} when the gpkg is absent")
    if not paths.eaglei.is_file():
        missing.append(f"EAGLE-I Florida extract {paths.eaglei}: run scripts/phase0/eaglei_extract.py")
    if not paths.mcc.is_file():
        missing.append(f"EAGLE-I customers per county {paths.mcc}")
    return missing


def parse_tile_name(path: Path, product: str = "VNP46A2") -> TileFile:
    match = TILE_NAME.match(path.name)
    if match is None or match.group(1, 4, 5) != (product, TILE, COLLECTION):
        raise InputError(f"{path.name} is not named {product}.AYYYYDDD.{TILE}.{COLLECTION}.<13-digit stamp>.h5")
    year, day_of_year = int(match[2]), int(match[3])
    file_date = dt.date(year, 1, 1) + dt.timedelta(days=day_of_year - 1)
    if day_of_year < 1 or file_date.year != year:
        raise InputError(f"{path.name}: day {day_of_year} does not exist in {year}")
    return TileFile(path, file_date)


def find_tiles(directory: Path, product: str = "VNP46A2", required: bool = True) -> list[TileFile]:
    """The product's files for TILE under `directory`, by date; two for a date, or none when required, fail fast."""
    found = (p for p in directory.rglob(TILE_GLOBS[product]) if p.is_file())
    tiles = sorted((parse_tile_name(p, product) for p in found), key=lambda t: t.file_date)
    if required and not tiles:
        raise InputError(f"no {TILE_GLOBS[product]} files under {directory}")
    dates = [tile.file_date for tile in tiles]
    repeated = sorted({day for day in dates if dates.count(day) > 1})
    if repeated:
        names = [tile.path.name for tile in tiles if tile.file_date in repeated]
        raise InputError(f"more than one file for {', '.join(map(str, repeated))}: {names}; keep one per date")
    return tiles


def load_county(paths: Paths, fips: str = LEE_FIPS):
    """The county polygon in EPSG:4326 and its source: fl_counties.gpkg (column fips) or, only when that file is
    absent, the Census zip (GEOID). This gpkg-to-zip step is the one documented fallback."""
    if paths.counties_gpkg.is_file():
        source, column = COUNTIES_GPKG, "fips"
    elif paths.counties_zip.is_file():
        source, column = COUNTIES_ZIP, "GEOID"
    else:
        raise InputError(f"missing both {paths.counties_gpkg} and {paths.counties_zip}")
    frame = gpd.read_file(paths.root / source)
    if column not in frame.columns or frame.crs is None:
        raise InputError(f"{source.name} needs a {column} column and a CRS (found {list(frame.columns)}, {frame.crs})")
    rows = frame[frame[column].astype(str).eq(fips)]
    if len(rows) != 1:
        raise InputError(f"{source.name} has {len(rows)} rows with {column} = {fips}; expected exactly 1")
    geometry = rows.to_crs("EPSG:4326").geometry.iloc[0]
    if geometry is None or geometry.is_empty:
        raise InputError(f"{source.name}: the geometry of {fips} is empty")
    return geometry, source


def load_customers(path: Path, fips: str = LEE_FIPS) -> int:
    """Customers in one county from MCC.csv: UTF-8 with a byte-order mark, unpadded County_FIPS, Grand Total row."""
    table = pd.read_csv(path, encoding="utf-8-sig", dtype={"County_FIPS": str})
    if not {"County_FIPS", "Customers"} <= set(table.columns):
        raise InputError(f"{path.name} columns are {list(table.columns)}; expected County_FIPS and Customers")
    codes = table["County_FIPS"].str.strip()
    is_county = codes.str.fullmatch(r"\d{1,5}").fillna(False).astype(bool)
    match = table.loc[is_county & codes.str.zfill(5).eq(fips), "Customers"]
    if len(match) != 1 or not float(match.iloc[0]) > 0:
        raise InputError(f"{path.name} has no single positive customer count for {fips}")
    return int(match.iloc[0])


def load_lee_runs(path: Path, fips: str = LEE_FIPS) -> pd.Series:
    """Lee customers_out on every run that has Florida rows, indexed by the naive run_start_time.

    A run with Florida rows but no Lee row counts as 0, because EAGLE-I leaves out counties with no outage. A Lee
    row with an empty count stays NaN (unknown, never 0). Runs with no Florida rows are absent, so they are skipped.
    """
    table = pd.read_parquet(path)
    needed = {"fips_code", "county", "state", "customers_out", "run_start_time"}
    if not needed <= set(table.columns):
        raise InputError(f"{path.name} lacks columns {sorted(needed - set(table.columns))}")
    stamps = pd.to_datetime(table["run_start_time"])
    codes = table["fips_code"].astype(str)
    if stamps.dt.tz is not None or not codes.str.fullmatch(r"\d{5}").all():
        raise InputError(f"{path.name}: expected naive run_start_time stamps and 5-digit fips_code strings")
    is_lee = codes.eq(fips)
    runs = pd.DatetimeIndex(stamps[codes.str.startswith(fips[:2])].unique()).sort_values()
    if runs.empty or not is_lee.any() or stamps[is_lee].duplicated().any():
        raise InputError(f"{path.name}: expected Florida runs and at most one {fips} row per run")
    counts = table.loc[is_lee, "customers_out"].astype("float64").to_numpy()
    return pd.Series(counts, index=pd.DatetimeIndex(stamps[is_lee])).reindex(runs, fill_value=0.0)


def tile_bounds(tile: str) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a 10-degree tile, inverting h = floor((lon+180)/10), v = floor((90-lat)/10)."""
    h, v = int(tile[1:3]), int(tile[4:6])
    return -180.0 + 10 * h, 80.0 - 10 * v, -170.0 + 10 * h, 90.0 - 10 * v


def axis_start(name: str, values: np.ndarray) -> tuple[float, float, str]:
    """(outer edge of pixel 0, signed step, convention) for one of the file's 1-D lat/lon arrays.

    The guide does not say whether lat/lon mark pixel centres or edges. Pixel edges fall on the 1/240-degree
    lattice (tile bounds are whole degrees), so a value half a pixel off it is a centre: lat[0] = 29.99792 on
    h09v06 means centres; lat[0] = 30.0 would mean edges.
    """
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size < 2:
        raise InputError(f"{name} must be a 1-D array with at least 2 values, not shape {values.shape}")
    steps = np.diff(values)
    if not (np.all(np.abs(np.abs(steps) - PIXEL_DEG) <= GRID_TOL_DEG) and (np.all(steps > 0) or np.all(steps < 0))):
        raise InputError(f"{name} spacing runs {steps.min():.9f} to {steps.max():.9f} degrees; expected a constant "
                         f"+/-1/240 = {PIXEL_DEG:.9f} within {GRID_TOL_DEG:g}")
    step = (values[-1] - values[0]) / (values.size - 1)
    phase = (values[0] / PIXEL_DEG) % 1.0
    if abs(phase - 0.5) <= GRID_TOL_DEG / PIXEL_DEG:
        start, convention, offset = values[0] - step / 2, "centres", 0.5
    elif min(phase, 1.0 - phase) <= GRID_TOL_DEG / PIXEL_DEG:
        start, convention, offset = values[0], "edges", 0.0
    else:
        raise InputError(f"{name}[0] = {values[0]:.9f} is neither a pixel centre nor a pixel edge of the 1/240 grid")
    drift = np.max(np.abs(values - (start + (np.arange(values.size) + offset) * step)))
    if drift > GRID_TOL_DEG:
        raise InputError(f"{name} drifts {drift:.2e} degrees from an even 1/240-degree grid")
    return float(start), float(step), convention


def grid_bounds(grid: Grid) -> tuple[float, float, float, float]:
    t, (rows, cols) = grid.transform, grid.shape
    xs, ys = (t.c, t.c + t.a * cols), (t.f, t.f + t.e * rows)
    return min(xs), min(ys), max(xs), max(ys)


def grid_from_arrays(lat: np.ndarray, lon: np.ndarray, shape: tuple[int, ...], tile: str = TILE) -> Grid:
    """Affine transform built from the file's own lat and lon arrays (rows follow lat, columns follow lon)."""
    row_edge, lat_step, lat_convention = axis_start("lat", lat)
    col_edge, lon_step, lon_convention = axis_start("lon", lon)
    if lat_convention != lon_convention:
        raise InputError(f"lat marks pixel {lat_convention} but lon marks pixel {lon_convention}")
    if tuple(shape) != (len(lat), len(lon)):
        raise InputError(f"layer shape {tuple(shape)} is not (len(lat), len(lon)) = ({len(lat)}, {len(lon)})")
    grid = Grid(Affine(lon_step, 0.0, col_edge, 0.0, lat_step, row_edge), (len(lat), len(lon)), lat_convention)
    (west, south, east, north), (t_west, t_south, t_east, t_north) = grid_bounds(grid), tile_bounds(tile)
    tol = GRID_TOL_DEG
    if west < t_west - tol or south < t_south - tol or east > t_east + tol or north > t_north + tol:
        raise InputError(f"grid bounds {grid_bounds(grid)} fall outside tile {tile} {tile_bounds(tile)}")
    return grid


def is_full_tile(grid: Grid, tile: str = TILE) -> bool:
    size = round(10 / PIXEL_DEG)
    close = np.allclose(grid_bounds(grid), tile_bounds(tile), rtol=0, atol=GRID_TOL_DEG)
    return bool(close and grid.shape == (size, size))


def county_window(geometry, grid: Grid) -> Window:
    """County pixels, rasterized with all_touched=False: a pixel belongs to the county when its centre does."""
    full = rasterize([(geometry, 1)], out_shape=grid.shape, transform=grid.transform, fill=0, all_touched=False,
                     dtype="uint8").astype(bool)
    if not full.any():
        raise InputError("the county polygon covers no pixel centre of the tile grid")
    rows, cols = np.flatnonzero(full.any(axis=1)), np.flatnonzero(full.any(axis=0))
    row_slice, col_slice = slice(int(rows[0]), int(rows[-1]) + 1), slice(int(cols[0]), int(cols[-1]) + 1)
    return Window(row_slice, col_slice, full[row_slice, col_slice])


def open_tile(path: Path) -> h5py.File:
    try:
        return h5py.File(path, "r")
    except OSError as exc:
        raise InputError(f"cannot open {path.name} as HDF5 ({exc}); delete it and download it again") from exc


def layer(h5: h5py.File, name: str, path: Path) -> h5py.Dataset:
    if DATA_GROUP not in h5:
        raise InputError(f"{path.name} has no group /{DATA_GROUP}")
    if name not in h5[DATA_GROUP]:
        raise InputError(f"{path.name} has no layer {name} (found {sorted(h5[DATA_GROUP])})")
    return h5[DATA_GROUP][name]


def read_grid(h5: h5py.File, path: Path, shape_layer: str = NTL) -> Grid:
    return grid_from_arrays(layer(h5, "lat", path)[()], layer(h5, "lon", path)[()], layer(h5, shape_layer, path).shape)


def require_same_grid(found: Grid, expected: Grid, path: Path) -> None:
    same_transform = np.allclose(tuple(found.transform)[:6], tuple(expected.transform)[:6], rtol=0, atol=GRID_TOL_DEG)
    if found.shape != expected.shape or not same_transform:
        raise InputError(f"{path.name} is on another grid than the first file ({found} vs {expected})")


def decode_layer(raw: np.ndarray, attrs: h5py.AttributeManager, where: str, offset_name: str = "offset",
                 fill: float = NTL_FILL, valid: tuple[float, float] = (0.0, math.inf)) -> np.ndarray:
    """Float64 values: scale and offset from the attributes (named 'offset' in VNP46A2, App. B pp.44-45, and add_offset
    in VNP46A1, App. A pp.40-43); fill and values outside `valid` become NaN by hand, never by CF auto-decoding."""
    absent = [name for name in ("scale_factor", offset_name) if name not in attrs]
    if absent:
        raise InputError(f"{where} has no {' or '.join(absent)} attribute (found {sorted(attrs)})")
    scale, offset = (float(np.ravel(attrs[name])[0]) for name in ("scale_factor", offset_name))
    fills = [fill] + ([np.ravel(attrs["_FillValue"])[0]] if "_FillValue" in attrs else [])
    is_fill = np.isin(raw, np.asarray(fills, dtype=raw.dtype))
    physical = raw.astype(np.float64) * scale + offset
    return np.where(is_fill | ~((physical >= valid[0]) & (physical <= valid[1])), np.nan, physical)


decode_radiance = decode_layer  # VNP46A2 radiance: fill and negative values become NaN


def read_decoded(h5: h5py.File, name: str, path: Path, window: Window, **decoding) -> np.ndarray:
    data = layer(h5, name, path)
    return decode_layer(data[window.rows, window.cols], data.attrs, f"{path.name} {name}", **decoding)[window.mask]


def cloud_confidence(qf: np.ndarray) -> np.ndarray:
    """QF_Cloud_Mask bits 6-7 (Table 6 p.14), with bit 0 the least significant bit (the standard reading):
    0 confident clear, 1 probably clear, 2 probably cloudy, 3 confident cloudy; fill becomes NO_CLOUD_INFO."""
    bits = np.asarray(qf).astype(np.uint16)
    return np.where(bits == CLOUD_MASK_FILL, NO_CLOUD_INFO, (bits >> 6) & 0b11).astype(np.uint8)


def read_window(h5: h5py.File, name: str, path: Path, window: Window) -> np.ndarray:
    return layer(h5, name, path)[window.rows, window.cols][window.mask]


def read_night(tile: TileFile, grid: Grid, window: Window) -> NightPixels:
    """Main path: DNB_BRDF-Corrected_NTL and the three flag layers over the county. Never the gap-filled layer."""
    with open_tile(tile.path) as h5:
        require_same_grid(read_grid(h5, tile.path), grid, tile.path)
        return NightPixels(
            file_date=tile.file_date,
            radiance=read_decoded(h5, NTL, tile.path, window),
            quality=read_window(h5, QUALITY, tile.path, window),
            cloud=cloud_confidence(read_window(h5, CLOUD_MASK, tile.path, window)),
            snow=read_window(h5, SNOW, tile.path, window),
        )


def read_gap_filled(tile: TileFile, grid: Grid, window: Window) -> tuple[np.ndarray, np.ndarray]:
    """Check 1 only: the gap-filled radiance and Latest_High_Quality_Retrieval (days) over the county."""
    with open_tile(tile.path) as h5:
        require_same_grid(read_grid(h5, tile.path), grid, tile.path)
        radiance = read_decoded(h5, GAP_FILLED_NTL, tile.path, window)
        days = read_window(h5, LATEST_HQ, tile.path, window).astype(np.float64)
    return radiance, np.where(days == LATEST_HQ_FILL, np.nan, days)


def night_pass(file_date: dt.date, a1: TileFile | None, grid: Grid, window: Window, lon: float) -> dict:
    """pass_utc: the median VNP46A1 UTC_Time over the county pixels when that file has any valid time there, else the
    nominal pass at `lon`; pass_source; and sensor_zenith_median (degrees) from the VNP46A1 file, NaN without one."""
    hours = zenith = np.array([])
    if a1 is not None:
        with open_tile(a1.path) as h5:  # on the VNP46A2 grid, so the county pixels are the same ones
            require_same_grid(read_grid(h5, a1.path, UTC_TIME), grid, a1.path)
            hours, zenith = (read_decoded(h5, name, a1.path, window, offset_name="add_offset", fill=fill, valid=valid)
                             for name, (fill, valid) in A1_LAYERS.items())
    if np.isfinite(hours).any():
        day = pd.Timestamp(file_date, tz="UTC")
        when, source = (day + pd.Timedelta(float(np.nanmedian(hours)), unit="h")).round("s"), PASS_FROM_A1
    else:
        when, source = nominal_pass_utc(file_date, lon), PASS_NOMINAL
    first, last = (pd.Timestamp(dt.datetime.combine(file_date, clock), tz="UTC") for clock in PASS_WINDOW_UTC)
    if not first <= when <= last:
        raise InputError(f"the {source} pass for the {file_date} file is at {when:%Y-%m-%d %H:%M} UTC, outside "
                         f"{first:%H:%M}-{last:%H:%M} UTC on the file date, so night = file date - 1 would not hold")
    median_zenith = float(np.nanmedian(zenith)) if np.isfinite(zenith).any() else math.nan
    return {"pass_utc": when, "pass_source": source, "sensor_zenith_median": median_zenith}


def clear_mask(night: NightPixels, quality: tuple[int, ...] = GOOD_QUALITY) -> np.ndarray:
    """Clear: a quality code in `quality` (only 0 on the main path), cloud confident or probably clear, no snow,
    and a radiance value."""
    return (np.isin(night.quality, quality) & np.isin(night.cloud, CLEAR_CLOUD) & (night.snow == NO_SNOW)
            & ~np.isnan(night.radiance))


def baseline_median(nights: list[NightPixels], min_nights: int = MIN_BASELINE_NIGHTS) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel median of clear radiance over the baseline files (NaN with fewer than min_nights clear), and the
    number of clear nights per pixel."""
    if not nights:
        raise InputError(f"no tiles dated {BASELINE_FIRST} to {BASELINE_LAST}, so there is no baseline")
    stack = np.vstack([np.where(clear_mask(night), night.radiance, np.nan) for night in nights])
    clear_nights = np.count_nonzero(~np.isnan(stack), axis=0)
    enough = clear_nights >= min_nights
    median = np.full(stack.shape[1], np.nan)
    median[enough] = np.nanmedian(stack[:, enough], axis=0)
    return median, clear_nights


def night_status(visible_share: float, base_total: float) -> str:
    if not base_total > 0:
        return "not_measurable"
    return "cant_see" if visible_share < VISIBLE_SHARE_MIN else "ok"


def night_metrics(radiance: np.ndarray, clear: np.ndarray, baseline: np.ndarray) -> dict:
    """% darker over the pixels that are clear tonight and have a baseline: the same pixels on both sides."""
    has_baseline = ~np.isnan(baseline)
    seen = clear & has_baseline & ~np.isnan(radiance)
    tonight = float(np.sum(radiance[seen], dtype=np.float64))
    base_visible = float(np.sum(baseline[seen], dtype=np.float64))
    base_total = float(np.sum(baseline[has_baseline], dtype=np.float64))
    visible_share = base_visible / base_total if base_total > 0 else math.nan
    return {
        "status": night_status(visible_share, base_total),
        "pct_darker": 1.0 - tonight / base_visible if base_visible > 0 else math.nan,
        "visible_share": visible_share,
        "tonight": tonight,
        "base_visible": base_visible,
        "base_total": base_total,
        "n_seen_pixels": int(np.count_nonzero(seen)),
    }


def customers_out_at(lee_runs: pd.Series, when: pd.Timestamp, window: pd.Timedelta = EAGLEI_WINDOW) -> tuple[float, int]:
    """Median Lee customers_out over the usable runs within +/- window of `when`, and how many runs that was.
    Scrapers time out during storms, so one run is not enough. NaN when no usable run is left."""
    near = lee_runs[(lee_runs.index >= when - window) & (lee_runs.index <= when + window)].dropna()
    return (float(near.median()), int(near.size)) if near.size else (math.nan, 0)


def hours_after_landfall(stamp: pd.Timestamp, clock: str) -> float:
    return float((stamp.tz_localize(clock).tz_convert("UTC") - LANDFALL_UTC) / dt.timedelta(hours=1))


def surge_timing(lee_runs: pd.Series, customers: int) -> dict:
    """Check 3: when Lee first passed 10% and 50% out, and its peak, reading the stamps as UTC and as New York."""
    start, end = SURGE_SEARCH
    runs = lee_runs[(lee_runs.index >= start) & (lee_runs.index < end)].dropna()
    crossings = {f"first_{share:.0%}_out": runs.index[runs >= share * customers] for share in SURGE_SHARES}
    marks = {name: stamps[0] if len(stamps) else None for name, stamps in crossings.items()}
    marks["peak"] = runs.idxmax() if runs.size else None
    described = {
        name: None if stamp is None else {
            "stamp": stamp,
            "customers_out": runs[stamp],
            "pct_out": runs[stamp] / customers,
            "hours_after_landfall_if_utc": hours_after_landfall(stamp, "UTC"),
            "hours_after_landfall_if_new_york": hours_after_landfall(stamp, LOCAL_TZ),
        }
        for name, stamp in marks.items()
    }
    return {"landfall_utc": LANDFALL_UTC, "searched_stamps": [start, end], **described}


def night_row(night: NightPixels, baseline: np.ndarray, lee_runs: pd.Series, customers: int, eaglei_tz: str,
              overpass: dict) -> dict:
    """One night-table row. EAGLE-I is read around the night's pass (night_pass), as a naive stamp on its own clock."""
    clear = clear_mask(night)
    keep_code_1 = night_metrics(night.radiance, clear_mask(night, GOOD_QUALITY + (POOR_OUTLIER_OR_CLOUD,)), baseline)
    code_1_only = night_metrics(night.radiance, clear_mask(night, (POOR_OUTLIER_OR_CLOUD,)), baseline)
    target = overpass["pass_utc"].tz_convert(eaglei_tz).tz_localize(None)
    customers_out, n_runs = customers_out_at(lee_runs, target)
    return {
        "file_date": night.file_date,
        "night": night_of(night.file_date),
        **night_metrics(night.radiance, clear, baseline),
        "n_county_pixels": int(night.radiance.size),
        "n_clear_pixels": int(np.count_nonzero(clear)),
        "in_baseline": in_baseline(night.file_date),
        "after_landfall": night.file_date > LANDFALL_UTC.date(),
        **overpass,
        "eaglei_clock": eaglei_tz,
        "eaglei_target": target,
        "eaglei_n_runs": n_runs,
        "eaglei_customers_out": customers_out,
        "eaglei_pct_out": customers_out / customers,
        "mqf1_share": float(np.mean(night.quality == POOR_OUTLIER_OR_CLOUD)),
        "pct_darker_keep_mqf1": keep_code_1["pct_darker"],
        "visible_share_keep_mqf1": keep_code_1["visible_share"],
        "status_keep_mqf1": keep_code_1["status"],
        "pct_darker_mqf1_only": code_1_only["pct_darker"],
        "n_mqf1_seen_pixels": code_1_only["n_seen_pixels"],
    }


def gap_filled_check(tile: TileFile, night: NightPixels, grid: Grid, window: Window, baseline: np.ndarray) -> dict:
    """Check 1 for one file: the gap-filled layer at face value (no flags, as a naive user would take it), and on
    the main path's own clear pixels."""
    gap, age_days = read_gap_filled(tile, grid, window)
    clear, has_value = clear_mask(night), ~np.isnan(gap)
    face_value = night_metrics(gap, has_value, baseline)
    filled_only = has_value & ~clear & ~np.isnan(baseline)
    ages = age_days[filled_only & ~np.isnan(age_days)]
    return dict(zip(GAP_COLUMNS, (
        face_value["pct_darker"],
        face_value["visible_share"],
        night_metrics(gap, clear, baseline)["pct_darker"],
        int(np.count_nonzero(filled_only)),
        float(np.median(ages)) if ages.size else math.nan,
    )))


def gap_filled_checks(tiles: list[TileFile], nights: list[NightPixels], grid: Grid, window: Window,
                      baseline: np.ndarray) -> dict:
    """Check 1 on the first three file dates after landfall: the only place the gap-filled layer is read."""
    by_date = {night.file_date: night for night in nights}
    after = [tile for tile in tiles if tile.file_date > LANDFALL_UTC.date()][:N_GAP_FILLED_FILES]
    return {tile.file_date: gap_filled_check(tile, by_date[tile.file_date], grid, window, baseline) for tile in after}


def gap_filled_report(table: pd.DataFrame, gap_checks: dict) -> list[dict]:
    rows = table.set_index("file_date")
    corrected = ["night", "status", "pct_darker", "visible_share"]
    return [{"file_date": day, **rows.loc[day, corrected].to_dict(), **check} for day, check in gap_checks.items()]


def quality_code_1_report(table: pd.DataFrame, nights: list[NightPixels]) -> list[dict]:
    """Check 2 on each post-landfall file: how much of Lee is flagged 1, and % darker if code 1 were kept."""
    rows = table.set_index("file_date")
    columns = ["mqf1_share", "status", "pct_darker", "status_keep_mqf1", "pct_darker_keep_mqf1",
               "pct_darker_mqf1_only", "eaglei_pct_out"]
    report = []
    for night in (n for n in nights if n.file_date > LANDFALL_UTC.date()):
        codes, counts = np.unique(night.quality, return_counts=True)
        report.append({"file_date": night.file_date, "mqf_counts": dict(zip(codes.tolist(), counts.tolist())),
                       **rows.loc[night.file_date, columns].to_dict()})
    return report


def control_row(rows: pd.DataFrame, day: dt.date) -> dict:
    """One check-4 control file: what the satellite saw and EAGLE-I's % out at its pass; "no_file" if absent."""
    match = rows[rows["file_date"].eq(day)]
    if match.empty:
        return {**dict.fromkeys(CHECK_4_COLUMNS), "file_date": day, "night": night_of(day), "status": "no_file",
                "dark": False}
    return match.iloc[0][[*CHECK_4_COLUMNS, "status", "dark"]].to_dict()


def first_dark_file(table: pd.DataFrame) -> dict:
    """Check 4, the night convention: the first dark file (status ok, pct_darker above DARK_PCT) after the baseline.

    Files up to BASELINE_LAST are not searched: a dim night there says nothing about the storm. The Sep 28 and Sep 29
    files are reported as controls, with EAGLE-I's % out at their passes. A dark Sep 28 looks the same whether cloud
    or view angle dimmed it or the convention is off by one, and a file the satellite could not see shows nothing,
    so the verdict is "confirmed" only when Sep 28 is ok and not dark, Sep 29 is ok and dark, and no earlier file
    after the baseline is dark. Anything else is "inconclusive".
    """
    rows = table.sort_values("file_date")
    rows = rows.assign(dark=rows["status"].eq("ok") & (rows["pct_darker"] > DARK_PCT))
    dark = rows[rows["dark"] & (rows["file_date"] > BASELINE_LAST)]
    found = {} if dark.empty else dark.iloc[0][list(CHECK_4_COLUMNS)].to_dict()
    lit_control, dark_control = (control_row(rows, day) for day in (EXPECTED_LAST_LIT_FILE, EXPECTED_FIRST_DARK_FILE))
    confirmed = (lit_control["status"] == "ok" and not lit_control["dark"] and dark_control["dark"]
                 and found.get("file_date") == EXPECTED_FIRST_DARK_FILE)
    return {
        "rule": f"first file date after the baseline (which ends {BASELINE_LAST}) with status ok and pct_darker > "
                f"{DARK_PCT}",
        **{key: found.get(key) for key in CHECK_4_COLUMNS},
        "expected_file_date": EXPECTED_FIRST_DARK_FILE,
        "nasa_black_marble_date": NASA_IMAGE_DATE,
        "days_after_nasa_date": (found["file_date"] - NASA_IMAGE_DATE).days if found else None,
        "controls": [lit_control, dark_control],
        "verdict": "confirmed" if confirmed else "inconclusive",
        "verdict_rule": f"confirmed only when the {EXPECTED_LAST_LIT_FILE} file is ok and not dark, the "
                        f"{EXPECTED_FIRST_DARK_FILE} file is ok and dark, and no earlier file after the baseline is "
                        "dark; otherwise inconclusive",
    }


def nights_report(table: pd.DataFrame) -> dict:
    is_ok = table["status"].eq("ok")
    pair = table.loc[is_ok & table["after_landfall"], ["pct_darker", "eaglei_pct_out"]].dropna()
    return {
        "n_file_dates": len(table),
        "status_counts": table["status"].value_counts().to_dict(),
        "cant_see_nights": table.loc[table["status"].eq("cant_see"), "night"].tolist(),
        "max_pct_darker_ok": table.loc[is_ok, "pct_darker"].max(),
        "max_eaglei_pct_out": table["eaglei_pct_out"].max(),
        "n_ok_nights_after_landfall_with_eaglei": len(pair),
        "pearson_r_ok_nights_after_landfall": pair.corr().iloc[0, 1] if len(pair) >= 3 else None,
    }


def pass_report(table: pd.DataFrame, a1_dates: set[dt.date], lon: float) -> dict:
    """How the passes were found; VNP46A1 files without a valid UTC_Time over the county fell back to the nominal."""
    hours = (table["pass_utc"] - table["pass_utc"].dt.normalize()) / pd.Timedelta(1, unit="h")
    nominal = set(table.loc[table["pass_source"].eq(PASS_NOMINAL), "file_date"])
    return {
        "rule": f"median {UTC_TIME} over the county in the same-date VNP46A1 file, else {PASS_SOLAR_TIME:%H:%M} local "
                f"mean solar time at the county's representative point (UTC = {PASS_SOLAR_TIME:%H:%M} - lon/15 h)",
        "representative_point_lon": lon,
        "n_vnp46a1_files": len(a1_dates),
        "source_counts": table["pass_source"].value_counts().to_dict(),
        "hours_utc_min_median_max": [hours.min(), hours.median(), hours.max()],
        "vnp46a1_without_valid_utc_time": sorted(a1_dates & nominal),
    }


def attr_value(value: object) -> object:
    """An HDF5 attribute as plain JSON: text decoded and trimmed, one-element arrays unwrapped."""
    items = np.ravel(value).tolist() if isinstance(value, np.ndarray) else [value]
    items = [item.decode("utf-8", "replace") if isinstance(item, bytes) else item for item in items]
    items = [item[:200] if isinstance(item, str) else item for item in items]
    return items[0] if len(items) == 1 else items[:10]


def describe_file(h5: h5py.File, path: Path, grid: Grid) -> dict:
    """What docs/phase0.md should record: layers and types, the NTL attributes and the lat/lon convention."""
    fields, lat, lon = h5[DATA_GROUP], layer(h5, "lat", path)[()], layer(h5, "lon", path)[()]
    return {
        "file": path.name,
        "data_group": f"/{DATA_GROUP}",
        "layers": {name: [str(item.dtype), list(item.shape)] for name, item in fields.items()
                   if isinstance(item, h5py.Dataset)},
        "ntl_attributes": {key: attr_value(value) for key, value in fields[NTL].attrs.items()},
        "lat_first_last": [lat[0], lat[-1]],
        "lon_first_last": [lon[0], lon[-1]],
        "lat_lon_mark": grid.convention,
        "transform_abcdef": list(grid.transform)[:6],
        "bounds_west_south_east_north": list(grid_bounds(grid)),
        "is_full_tile": is_full_tile(grid),
    }


def tile_inventory(tiles: list[TileFile]) -> dict:
    dates = [tile.file_date for tile in tiles]
    span = set(pd.date_range(dates[0], dates[-1], freq="D").date)
    return {"n_files": len(tiles), "first_file_date": dates[0], "last_file_date": dates[-1],
            "missing_dates_between": sorted(span - set(dates))}


def baseline_report(nights: list[NightPixels], baseline: np.ndarray, clear_nights: np.ndarray) -> dict:
    has_baseline = ~np.isnan(baseline)
    return {
        "file_dates_inclusive": [BASELINE_FIRST, BASELINE_LAST],
        "n_files": sum(in_baseline(night.file_date) for night in nights),
        "min_clear_nights": MIN_BASELINE_NIGHTS,
        "n_pixels_with_baseline": int(has_baseline.sum()),
        "clear_nights_per_pixel_min_median_max": [clear_nights.min(), np.median(clear_nights), clear_nights.max()],
        "base_total": float(np.sum(baseline[has_baseline], dtype=np.float64)),
    }


def jsonable(value: object) -> object:
    """Plain JSON: NaN and infinities become null, numpy scalars Python numbers, dates ISO strings."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [jsonable(item) for item in value]
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, (dt.date, pd.Timestamp)):
        return value.isoformat()
    return str(value) if isinstance(value, Path) else value


def run(root: Path, eaglei_tz: str = EAGLEI_TZ) -> dict:
    """Read the inputs, find each night's pass, build the night table and the four checks, write the CSV, the chart
    and the JSON summary, and return the summary."""
    check_timezone(eaglei_tz)
    paths = Paths.under(root)
    if missing := missing_inputs(paths):
        raise InputError("missing inputs:\n  " + "\n  ".join(missing))
    tiles = find_tiles(paths.tiles)
    a1_files = {tile.file_date: tile for tile in find_tiles(paths.a1_tiles, "VNP46A1", required=False)}
    county, county_source = load_county(paths)
    lon = float(county.representative_point().x)
    customers, lee_runs = load_customers(paths.mcc), load_lee_runs(paths.eaglei)
    with open_tile(tiles[0].path) as h5:
        grid = read_grid(h5, tiles[0].path)
        first_file = describe_file(h5, tiles[0].path, grid)
    window = county_window(county, grid)
    nights = [read_night(tile, grid, window) for tile in tiles]
    passes = {t.file_date: night_pass(t.file_date, a1_files.get(t.file_date), grid, window, lon) for t in tiles}
    baseline, clear_nights = baseline_median([night for night in nights if in_baseline(night.file_date)])
    gap_checks = gap_filled_checks(tiles, nights, grid, window, baseline)
    blank = dict.fromkeys(GAP_COLUMNS, math.nan)
    table = pd.DataFrame([{**night_row(night, baseline, lee_runs, customers, eaglei_tz, passes[night.file_date]),
                           **gap_checks.get(night.file_date, blank)} for night in nights])
    for target in (paths.out_csv, paths.out_png, paths.out_json):
        target.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(paths.out_csv, index=False)
    chart.plot_nights(table, paths.out_png, eaglei_tz, layer=NTL, baseline=(BASELINE_FIRST, BASELINE_LAST),
                      landfall_utc=LANDFALL_UTC, local_tz=LOCAL_TZ)
    summary = {
        "script": "scripts/phase0/ian_lee.py",
        "county": {"fips": LEE_FIPS, "polygon_source": county_source, "n_pixels": int(window.mask.sum()),
                   "mcc_customers": customers},
        "tiles": tile_inventory(tiles),
        "grid": first_file,
        "baseline": baseline_report(nights, baseline, clear_nights),
        "pass": pass_report(table, set(a1_files), lon),
        "eaglei": {"clock": eaglei_tz, "centred_on": "each night's pass_utc, read on the EAGLE-I clock",
                   "window_minutes": EAGLEI_WINDOW / dt.timedelta(minutes=1), "n_florida_runs": int(lee_runs.size)},
        "nights": nights_report(table),
        "checks": {
            "1_gap_filled_vs_corrected": gap_filled_report(table, gap_checks),
            "2_quality_code_1": quality_code_1_report(table, nights),
            "3_eaglei_surge_timing": surge_timing(lee_runs, customers),
            "4_first_dark_file": first_dark_file(table),
        },
        "outputs": {"csv": OUT_CSV, "png": OUT_PNG, "json": OUT_JSON},
    }
    paths.out_json.write_text(json.dumps(jsonable(summary), indent=1, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 0: Hurricane Ian in Lee County, night lights vs EAGLE-I.")
    parser.add_argument("--eaglei-tz", default=EAGLEI_TZ, help=f"clock of EAGLE-I run_start_time (default {EAGLEI_TZ})")
    parser.add_argument("--root", type=Path, default=REPO, help="read and write under this folder instead of the repo")
    args = parser.parse_args(argv)
    try:
        summary = run(args.root.resolve(), args.eaglei_tz)
    except InputError as exc:
        print(f"ian_lee.py: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(jsonable(summary), indent=1, allow_nan=False))  # the same text as the JSON file
    return 0


if __name__ == "__main__":
    sys.exit(main())
