"""Synthetic inputs for the Phase 0 Ian / Lee County tests: tiny VNP46A2 and VNP46A1 files, EAGLE-I runs, MCC and
counties.

The HDF5 files use the real group path, layer names, dtypes, scale and fill values (docs/phase0/
blackmarble-facts.json: User Guide C2 Table 8 p.16, App. B pp.44-45; for VNP46A1, Table 5 pp.11-12 and App. A
pp.40-43) on a 6 x 6 piece of tile h09v06 near Lee County, so nothing here needs the network or real tiles. The
script is loaded from its path because scripts/ is not a package.
"""

import datetime as dt
import importlib.util
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "phase0" / "ian_lee.py"


def load_script():
    spec = importlib.util.spec_from_file_location("ian_lee", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ian_lee"] = module  # dataclasses look their module up here while the class is built
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # leave no __pycache__ in scripts/phase0
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


ian = sys.modules["ian_lee"] if "ian_lee" in sys.modules else load_script()

DATA_GROUP = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"
NTL, GAP_FILLED = "DNB_BRDF-Corrected_NTL", "Gap_Filled_DNB_BRDF-Corrected_NTL"
# layer: dtype, _FillValue, scale_factor, offset (None: no such attribute on the layer), valid_range text
LAYERS = {
    NTL: ("float32", -999.9, 1.0, 0.0, ">=0.0 \n"),
    GAP_FILLED: ("float32", -999.9, 1.0, 0.0, ">=0.0 \n"),
    "DNB_Lunar_Irradiance": ("uint16", 65535, 0.1, 0.0, "0 - 65534 \n"),
    "Mandatory_Quality_Flag": ("uint8", 255, None, None, "0 - 5 \n"),
    "Latest_High_Quality_Retrieval": ("uint8", 255, 1.0, 0.0, "0 - 254 \n"),
    "Snow_Flag": ("uint8", 255, None, None, "0 - 1 \n"),
    "QF_Cloud_Mask": ("uint16", 65535, None, None, "0 - 65534 \n"),
}
UNITS = {NTL: "nWatts·cm−2·sr−1 \n", GAP_FILLED: "nWatts·cm−2·sr−1 \n", "DNB_Lunar_Irradiance": "nWatts·cm−2 \n",
         "Latest_High_Quality_Retrieval": "Number of Days \n"}
# VNP46A1 layers for the pass time (Table 5 pp.11-12, App. A pp.42-43): dtype, _FillValue, scale_factor, add_offset,
# valid_min and valid_max (as stored), units and long_name.
A1_LAYERS = {
    "UTC_Time": ("float32", -999.9, 1.0, 0.0, 0, 24, "decimal hours", "View Time (UTC)"),
    "Sensor_Zenith": ("int16", -32768, 0.01, 0.0, 0, 9000, "degrees", "Sensor Zenith Angle"),
}

PIXEL = 1 / 240
ROW0, COL0, SIZE = 840, 1920, 6  # a 6 x 6 window of h09v06 near Lee County, counted from the tile's NW corner
WEST, NORTH = -90 + COL0 * PIXEL, 30 - ROW0 * PIXEL  # -82.0 and 26.5: the outer edges of the window
LAT = NORTH - (np.arange(SIZE) + 0.5) * PIXEL  # pixel centres, as real h09v06 files are expected to store them
LON = WEST + (np.arange(SIZE) + 0.5) * PIXEL
INNER = (slice(1, 5), slice(1, 5))  # the 16 pixels whose centres fall inside COUNTY


def pixel_box(top: float, bottom: float, left: float, right: float):
    """A lon/lat box whose edges sit at fractional pixel positions of the window (row 0, column 0 = NW pixel)."""
    return box(WEST + left * PIXEL, NORTH - bottom * PIXEL, WEST + right * PIXEL, NORTH - top * PIXEL)


COUNTY = pixel_box(0.75, 5.25, 0.75, 5.25)  # holds the centres of rows 1-4 and columns 1-4, touches the outer ring


def cloud_mask_bits(confidence) -> np.ndarray:
    """QF_Cloud_Mask with bits 6-7 = confidence, plus night (bit 0 = 0), land (bits 1-3 = 001) and a
    high-quality cloud mask (bits 4-5 = 11), so the decoder has to isolate bits 6-7."""
    return (np.asarray(confidence, dtype=np.uint16) << 6) | (0b11 << 4) | (0b001 << 1)


def tile_name(file_date: dt.date, stamp: str = "2024147200718") -> str:
    return f"VNP46A2.A{file_date:%Y}{file_date.timetuple().tm_yday:03d}.h09v06.002.{stamp}.h5"


def write_tile(directory: Path, file_date: dt.date, *, ntl=10.0, quality=0, cloud=0, snow=0, gap_filled=None,
               latest_hq=0, cloud_mask=None, lat=LAT, lon=LON, skip=()) -> Path:
    """Write one synthetic VNP46A2 file. Layer values are scalars or arrays shaped like the grid; `cloud` is the
    bits 6-7 confidence unless raw `cloud_mask` values are given; layers named in `skip` are left out."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / tile_name(file_date)
    values = {
        NTL: ntl,
        GAP_FILLED: ntl if gap_filled is None else gap_filled,
        "DNB_Lunar_Irradiance": 0,
        "Mandatory_Quality_Flag": quality,
        "Latest_High_Quality_Retrieval": latest_hq,
        "Snow_Flag": snow,
        "QF_Cloud_Mask": cloud_mask_bits(cloud) if cloud_mask is None else cloud_mask,
    }
    with h5py.File(path, "w") as h5:
        fields = h5.create_group(DATA_GROUP)
        for name, (dtype, fill, scale, offset, valid_range) in LAYERS.items():
            if name in skip:
                continue
            data = np.broadcast_to(np.asarray(values[name]), (len(lat), len(lon))).astype(dtype)
            dataset = fields.create_dataset(name, data=data, fillvalue=np.asarray(fill, dtype=dtype))
            dataset.attrs["_FillValue"] = np.asarray([fill], dtype=dtype)
            if scale is not None:
                dataset.attrs["scale_factor"], dataset.attrs["offset"] = np.float32(scale), np.float32(offset)
            dataset.attrs["valid_range"] = valid_range
            dataset.attrs["units"] = UNITS.get(name, "Flag, no units \n")
        for name, axis in (("lat", lat), ("lon", lon)):
            fields.create_dataset(name, data=np.asarray(axis, dtype="float64")).attrs["_FillValue"] = np.float32(-999.9)
        h5.attrs["HorizontalTileNumber"], h5.attrs["VerticalTileNumber"] = np.bytes_(b"09"), np.bytes_(b"06")
    return path


def a1_name(file_date: dt.date, stamp: str = "2024065214519") -> str:
    return f"VNP46A1.A{file_date:%Y}{file_date.timetuple().tm_yday:03d}.h09v06.002.{stamp}.h5"


def write_a1_tile(directory: Path, file_date: dt.date, *, utc_time=7.0, sensor_zenith=2500, lat=LAT, lon=LON,
                  skip=(), offset_name="add_offset") -> Path:
    """Write one synthetic VNP46A1 file: UTC_Time in decimal hours and Sensor_Zenith as stored (hundredths of a
    degree), each a scalar or an array shaped like the grid. Layers named in `skip` are left out, and `offset_name`
    can give the offset attribute another name."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / a1_name(file_date)
    values = {"UTC_Time": utc_time, "Sensor_Zenith": sensor_zenith}
    with h5py.File(path, "w") as h5:
        fields = h5.create_group(DATA_GROUP)
        for name, (dtype, fill, scale, offset, low, high, units, long_name) in A1_LAYERS.items():
            if name in skip:
                continue
            data = np.broadcast_to(np.asarray(values[name]), (len(lat), len(lon))).astype(dtype)
            dataset = fields.create_dataset(name, data=data, fillvalue=np.asarray(fill, dtype=dtype))
            dataset.attrs["_FillValue"] = np.asarray([fill], dtype=dtype)
            dataset.attrs["scale_factor"], dataset.attrs[offset_name] = np.float32(scale), np.float32(offset)
            dataset.attrs["valid_min"], dataset.attrs["valid_max"] = np.asarray([low, high], dtype=dtype)
            dataset.attrs["units"], dataset.attrs["long_name"] = units, long_name
        for name, axis in (("lat", lat), ("lon", lon)):
            fields.create_dataset(name, data=np.asarray(axis, dtype="float64")).attrs["_FillValue"] = np.float32(-999.9)
    return path


def write_eaglei(path: Path, rows) -> Path:
    """An EAGLE-I-like parquet; rows are (fips_code, customers_out or None, run stamp on the naive file clock)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({
        "fips_code": pd.array([fips for fips, _, _ in rows], dtype="string"),
        "county": pd.array(["Lee" if fips == "12071" else "Other" for fips, _, _ in rows], dtype="string"),
        "state": pd.array(["Florida" if fips.startswith("12") else "Georgia" for fips, _, _ in rows], dtype="string"),
        "customers_out": pd.array([count for _, count, _ in rows], dtype="Int64"),
        "run_start_time": pd.to_datetime([stamp for _, _, stamp in rows]).as_unit("us"),
    })
    frame.to_parquet(path, index=False)
    return path


def write_mcc(path: Path, customers: dict[str, int]) -> Path:
    """MCC.csv as EAGLE-I ships it: UTF-8 byte-order mark, CRLF, unpadded County_FIPS and a Grand Total row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["County_FIPS,Customers", *(f"{int(fips)},{count}" for fips, count in customers.items()),
             f"Grand Total,{sum(customers.values())}"]
    path.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode() + b"\r\n")
    return path


def counties(code_column: str, name_column: str, lee=COUNTY, crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({code_column: ["12015", "12071"], name_column: ["Charlotte", "Lee"]},
                            geometry=[pixel_box(0, 1, 0, 6), lee], crs=crs)


def write_county_gpkg(path: Path, lee=COUNTY) -> Path:
    """Like data/interim/fl_counties.gpkg: layer fl_counties with fips, name and geometry in EPSG:4326."""
    path.parent.mkdir(parents=True, exist_ok=True)
    counties("fips", "name", lee).to_file(path, layer="fl_counties", driver="GPKG")
    return path


def write_county_zip(path: Path, lee=COUNTY) -> Path:
    """Like cb_2022_us_county_500k.zip: a zipped shapefile with GEOID and NAME, in NAD83."""
    parts = path.parent / f"{path.stem}_parts"
    parts.mkdir(parents=True)
    counties("GEOID", "NAME", lee, crs="EPSG:4269").to_file(parts / f"{path.stem}.shp")
    with zipfile.ZipFile(path, "w") as archive:
        for part in sorted(parts.iterdir()):
            archive.write(part, part.name)
    return path


# ---- one synthetic Ian, end to end: 39 files dated 2022-08-26 to 2022-10-03 -------------------------------
LEE_CUSTOMERS = 1000
FILE_DATES = tuple(dt.date(2022, 8, 26) + dt.timedelta(days=i) for i in range(39))
CHECK_1_FILES = (dt.date(2022, 9, 29), dt.date(2022, 9, 30), dt.date(2022, 10, 1))
RING = 1000.0  # light just outside the county: it would swamp every number if the county mask were wrong
DIM_BASELINE_FILE = dt.date(2022, 9, 3)  # thin cloud flagged "probably clear": seen, and 40% darker, before Ian
COUNTY_LIGHT = {DIM_BASELINE_FILE: 6.0, dt.date(2022, 9, 29): 2.5, dt.date(2022, 9, 30): 3.0,
                dt.date(2022, 10, 1): 4.0, dt.date(2022, 10, 2): 6.0, dt.date(2022, 10, 3): 9.0}  # 10.0 on other dates
# Both sit inside the +/-60 min window around the Sep 29 pass, 07:00 UTC from its fake VNP46A1 file. (They were at
# 05:30 and 05:45 while the pass was taken as 01:30 on the New York clock, which is 05:30 UTC.)
TIMED_OUT_RUN = pd.Timestamp("2022-09-29 07:00")  # Florida rows but no Lee row: counts as 0
MISSED_RUN = pd.Timestamp("2022-09-29 07:15")  # no Florida rows at all: skipped
LEE_OUT = (("2022-09-28 15:15", 150), ("2022-09-28 18:45", 600), ("2022-09-29", 700), ("2022-09-30", 650),
           ("2022-10-01", 500), ("2022-10-02", 400), ("2022-10-03", 300))  # 5 before the first stamp
# VNP46A1 files for three dates: UTC_Time (hours) and Sensor_Zenith (hundredths of a degree) over the county. Every
# other date has no VNP46A1 file, so its pass is 01:30 local mean solar time at the county's longitude.
A1_FILES = {dt.date(2022, 9, 28): (6.5, 1000), dt.date(2022, 9, 29): (7.0, 2550),
            dt.date(2022, 10, 1): (-999.9, 4000)}  # Oct 1: UTC_Time is fill over the whole county


def scenario_layers(day: dt.date) -> dict:
    """Steady light of 10 before landfall (cloudy when the day of month divides by 4 in the baseline, and one dim
    "probably clear" baseline night that still leaves the baseline median at 10), a blackout on Sep 29, cloud on
    Sep 30 (where the gap-filled layer shows pre-storm light), quality 1 on half of Lee on Oct 1, then recovery.
    Only the three check-1 files carry the gap-filled layer."""
    ntl, quality = np.full((SIZE, SIZE), RING), np.zeros((SIZE, SIZE), dtype=np.uint8)
    ntl[INNER] = COUNTY_LIGHT.get(day, 10.0)
    layers = {"ntl": ntl, "quality": quality, "cloud": 0, "latest_hq": 0}
    if ian.in_baseline(day) and day.day % 4 == 0:
        layers["cloud"] = 3
    if day == DIM_BASELINE_FILE:
        layers["cloud"] = 1
    if day == dt.date(2022, 9, 30):
        pre_storm = np.full((SIZE, SIZE), RING)
        pre_storm[INNER] = 10.0
        layers.update(cloud=3, gap_filled=pre_storm, latest_hq=2)
    if day == dt.date(2022, 10, 1):
        ntl[1:5, 1:3], quality[1:5, 1:3] = 0.5, 1
    if day not in CHECK_1_FILES:
        layers["skip"] = (GAP_FILLED,)
    return layers


def a1_layers(day: dt.date) -> dict:
    """The county's UTC_Time and Sensor_Zenith inside, another orbit (9.5 h, 70 degrees) on the outer ring, which
    must never reach a median, and on Sep 29 one fill pixel and one pixel from a later orbit inside the county."""
    hours, zenith = A1_FILES[day]
    utc, angle = np.full((SIZE, SIZE), 9.5), np.full((SIZE, SIZE), 7000)
    utc[INNER], angle[INNER] = hours, zenith
    if day == dt.date(2022, 9, 29):
        utc[1, 1], utc[4, 4], angle[2, 2] = -999.9, 8.7, -32768
    return {"utc_time": utc, "sensor_zenith": angle}


def lee_out(stamp: pd.Timestamp) -> int:
    value = 5
    for start, count in LEE_OUT:
        value = count if stamp >= pd.Timestamp(start) else value
    return value


def eaglei_rows() -> list[tuple]:
    rows = []
    for stamp in pd.date_range("2022-09-20", "2022-10-05", freq="15min"):
        if stamp == MISSED_RUN:
            continue
        rows.append(("12015", 10, stamp))
        if stamp != TIMED_OUT_RUN:
            rows.append(("12071", lee_out(stamp), stamp))
    return rows


def build_ian_root(root: Path, county: str = "gpkg") -> Path:
    """A repo-shaped folder with every Phase 0 input for the synthetic Ian; county is "gpkg" or "zip"."""
    for day in FILE_DATES:
        write_tile(root / ian.TILES_DIR / f"{day:%Y}" / f"{day.timetuple().tm_yday:03d}", day, **scenario_layers(day))
    for day in A1_FILES:
        write_a1_tile(root / ian.A1_DIR / f"{day:%Y}" / f"{day.timetuple().tm_yday:03d}", day, **a1_layers(day))
    if county == "gpkg":
        write_county_gpkg(root / ian.COUNTIES_GPKG)
    else:
        write_county_zip(root / ian.COUNTIES_ZIP)
    write_eaglei(root / ian.EAGLEI_PARQUET, eaglei_rows())
    write_mcc(root / ian.MCC_CSV, {"01001": 24619, "12015": 500, "12071": LEE_CUSTOMERS})
    return root
