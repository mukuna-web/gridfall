"""Black Marble tiles: tile ids, the HDF5 layers we read, the clear mask, nights and pass times (Task 3).

Only `DNB_BRDF-Corrected_NTL` is read, never the gap-filled layer, which pastes in older values on cloudy nights.
Pixel (0, 0) of tile hHHvVV has its top-left corner at lon = HH*10 - 180, lat = 90 - VV*10; each pixel is 1/240 deg.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

GROUP = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"
RADIANCE = "DNB_BRDF-Corrected_NTL"
GAP_FILLED = "Gap_Filled_DNB_BRDF-Corrected_NTL"  # never read; named so tests can check that
PIXELS_PER_DEGREE = 240
NAME = re.compile(r"^(?P<product>VNP46A[12]|VJ146A[12])\.A(?P<year>\d{4})(?P<doy>\d{3})\.(?P<tile>h\d{2}v\d{2})\.")
A1_FOR = {"VNP46A2": "VNP46A1", "VJ146A2": "VJ146A1"}


def tile_ids_for_bbox(west: float, south: float, east: float, north: float) -> list[str]:
    """Tiles covering [west, east) x (south, north], sorted. An edge exactly on a 10-degree line adds no tile."""
    if west > east or south > north:
        raise ValueError(f"bad box: west={west}, east={east}, south={south}, north={north}")
    h0 = math.floor((west + 180) / 10)
    h1 = max(h0, math.ceil((east + 180) / 10) - 1)
    v0 = math.floor((90 - north) / 10)
    v1 = max(v0, math.ceil((90 - south) / 10) - 1)
    hs = range(max(h0, 0), min(h1, 35) + 1)
    vs = range(max(v0, 0), min(v1, 17) + 1)
    return sorted(f"h{h:02d}v{v:02d}" for h in hs for v in vs)


def tile_origin(tile_id: str) -> tuple[float, float]:
    """(lon, lat) of the top-left corner of pixel (0, 0)."""
    h, v = int(tile_id[1:3]), int(tile_id[4:6])
    return h * 10 - 180.0, 90.0 - v * 10


@dataclass(frozen=True)
class TileNight:
    tile_id: str
    file_date: date
    radiance: np.ndarray  # float32, fill -> NaN
    quality: np.ndarray  # uint8 Mandatory_Quality_Flag (0 is the only clear value in Collection 2)
    cloud_conf: np.ndarray  # uint8 0-3, QF_Cloud_Mask bits 6-7
    snow: np.ndarray  # uint8 Snow_Flag (255 is fill)
    lunar_irradiance: np.ndarray | None = None  # float32 nW/cm^2, fill -> NaN


@dataclass(frozen=True)
class PassNight:
    """The VNP46A1 / VJ146A1 layers the build needs: view time and sensor zenith."""

    tile_id: str
    file_date: date
    utc_time: np.ndarray  # float32 decimal hours, fill -> NaN
    sensor_zenith: np.ndarray  # float32 degrees, fill -> NaN


def parse_name(name: str) -> tuple[str, date, str]:
    """(product, file_date, tile_id) from a Black Marble file name; A2022272 is day 272 of 2022 (Sep 29)."""
    match = NAME.match(Path(name).name)
    if not match:
        raise ValueError(f"not a VNP46/VJ146 A1 or A2 file name: {name!r}")
    file_date = date(int(match["year"]), 1, 1) + timedelta(days=int(match["doy"]) - 1)
    return match["product"], file_date, match["tile"]


def _layer(group: h5py.Group, name: str) -> np.ndarray:
    """A layer as float32 with its `_FillValue` (a 1-element array) as NaN and its scale and offset applied."""
    data = group[name]
    raw = data[...]
    fill = data.attrs["_FillValue"][0]
    scale = float(data.attrs.get("scale_factor", [1.0])[0])
    offset = float(data.attrs.get("add_offset", data.attrs.get("offset", [0.0]))[0])
    out = raw.astype(np.float32) * np.float32(scale) + np.float32(offset)
    out[raw == fill] = np.nan
    return out


def tile_night_from_h5(h5: h5py.File, name: str) -> TileNight:
    product, file_date, tile_id = parse_name(name)
    if product not in A1_FOR:
        raise ValueError(f"{name}: expected a VNP46A2 or VJ146A2 file")
    group = h5[GROUP]
    cloud = group["QF_Cloud_Mask"][...]
    lunar = _layer(group, "DNB_Lunar_Irradiance") if "DNB_Lunar_Irradiance" in group else None
    return TileNight(
        tile_id=tile_id,
        file_date=file_date,
        radiance=_layer(group, RADIANCE),
        quality=group["Mandatory_Quality_Flag"][...].astype(np.uint8),
        # Collection 2 User Guide, Table 6 (printed pp. 13-14): bits 6-7 are cloud confidence,
        # 00 confident clear, 01 probably clear, 10 probably cloudy, 11 confident cloudy. Fill 65535 decodes to 3.
        cloud_conf=((cloud >> 6) & 0b11).astype(np.uint8),
        snow=group["Snow_Flag"][...].astype(np.uint8),
        lunar_irradiance=lunar,
    )


def pass_night_from_h5(h5: h5py.File, name: str) -> PassNight:
    product, file_date, tile_id = parse_name(name)
    if product not in A1_FOR.values():
        raise ValueError(f"{name}: expected a VNP46A1 or VJ146A1 file")
    group = h5[GROUP]
    return PassNight(tile_id, file_date, _layer(group, "UTC_Time"), _layer(group, "Sensor_Zenith"))


def read_tile(path: Path) -> TileNight:
    """Read the corrected radiance, flags and lunar irradiance of a local VNP46A2 / VJ146A2 file."""
    path = Path(path)
    parse_name(path.name)  # reject bad names before opening the file
    with h5py.File(path, "r") as h5:
        return tile_night_from_h5(h5, path.name)


def read_pass(a1_path: Path) -> PassNight:
    a1_path = Path(a1_path)
    with h5py.File(a1_path, "r") as h5:
        return pass_night_from_h5(h5, a1_path.name)


def read_utc_time(a1_path: Path) -> np.ndarray:
    """VNP46A1's `UTC_Time` (decimal hours) with fill -999.9 as NaN."""
    return read_pass(a1_path).utc_time


def find_a1(a2_path: Path, a1_dir: Path) -> Path | None:
    """The A1 file for an A2 file, matched by product, date and tile (production stamps differ, so no prefix swap)."""
    product, file_date, tile_id = parse_name(Path(a2_path).name)
    stamp = f"A{file_date.year}{file_date.timetuple().tm_yday:03d}"
    hits = sorted(Path(a1_dir).glob(f"{A1_FOR[product]}.{stamp}.{tile_id}.*.h5"))
    return hits[-1] if hits else None


def clear_mask(t: TileNight, allow_snow: bool = False) -> np.ndarray:
    """Clear: quality 0, cloud confident or probably clear, no snow (or snow allowed), and a radiance value."""
    snow_ok = (t.snow == 0) | ((t.snow == 1) & allow_snow)
    return (t.quality == 0) & (t.cloud_conf <= 1) & snow_ok & ~np.isnan(t.radiance)


def night_of(file_date: date) -> date:
    """A file dated D (UTC) holds the ~01:30 local-solar-time pass of night D - 1."""
    return file_date - timedelta(days=1)


def pass_time_utc(file_date: date, lon: float, utc_hours: float | None = None) -> pd.Timestamp:
    """The pass time on `file_date`: `utc_hours` when given and finite, else 01:30 local mean solar time."""
    midnight = pd.Timestamp(file_date, tz="UTC")
    hours = utc_hours if utc_hours is not None and np.isfinite(utc_hours) else 1.5 - lon / 15.0
    return (midnight + pd.Timedelta(hours=float(hours))).round("s")
