"""HURDAT2 best tracks and the strongest wind zone each county's centre sat in (Task 4).

Wind radii are the maximum extent of 34-, 50- and 64-kt winds in each quadrant (NE, SE, SW, NW), in nautical
miles. The track is interpolated to hourly points first, so the swath has no gaps between 6-hourly fixes.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

QUADRANTS = ("ne", "se", "sw", "nw")
BANDS = (64, 50, 34)
RADIUS_COLUMNS = [f"r{kt}_{q}" for kt in (34, 50, 64) for q in QUADRANTS]
EARTH_RADIUS_NM = 3440.065
NOT_APPLICABLE = -1  # stress storms such as Uri have no wind field


def _coordinate(text: str) -> float:
    value = float(text[:-1])
    return -value if text[-1] in "SW" else value


def parse_hurdat2(path: Path) -> pd.DataFrame:
    """One row per track point: atcf_id, time (UTC), record, status, lat, lon, vmax_kt, then the 12 radii (nm)."""
    rows = []
    atcf_id = None
    for line in Path(path).read_text().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4 or not parts[0]:
            continue
        if parts[0][:2].isalpha():
            atcf_id = parts[0]
            continue
        radii = [float(x) if x not in ("", "-999") else np.nan for x in parts[8:20]]
        radii += [np.nan] * (12 - len(radii))
        rows.append([atcf_id, f"{parts[0]} {parts[1]}", parts[2], parts[3], _coordinate(parts[4]),
                     _coordinate(parts[5]), float(parts[6]), *radii])
    out = pd.DataFrame(rows, columns=["atcf_id", "time", "record", "status", "lat", "lon", "vmax_kt", *RADIUS_COLUMNS])
    out["time"] = pd.to_datetime(out["time"], format="%Y%m%d %H%M").dt.tz_localize("UTC")
    out["vmax_kt"] = out["vmax_kt"].where(out["vmax_kt"] >= 0)
    return out


def hourly(track: pd.DataFrame) -> pd.DataFrame:
    """The track linearly interpolated to every whole hour between its first and last fix."""
    track = track.sort_values("time").drop_duplicates("time")
    numeric = ["lat", "lon", "vmax_kt", *RADIUS_COLUMNS]
    indexed = track.set_index("time")[numeric]
    grid = pd.date_range(indexed.index[0].ceil("h"), indexed.index[-1].floor("h"), freq="h")
    joined = indexed.reindex(indexed.index.union(grid)).interpolate(method="time", limit_area="inside")
    return joined.loc[grid].reset_index(names="time")


def _distance_and_bearing(lat0: float, lon0: float, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Great-circle distance (nm) and initial bearing (degrees from north) from the centre to each point."""
    p0, p1 = np.radians(lat0), np.radians(lat)
    dl = np.radians(lon - lon0)
    a = np.sin((p1 - p0) / 2) ** 2 + np.cos(p0) * np.cos(p1) * np.sin(dl / 2) ** 2
    distance = 2 * EARTH_RADIUS_NM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    bearing = np.degrees(np.arctan2(np.sin(dl) * np.cos(p1),
                                    np.cos(p0) * np.sin(p1) - np.sin(p0) * np.cos(p1) * np.cos(dl))) % 360
    return distance, bearing


def band_at_points(track: pd.DataFrame, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """The strongest zone (0, 34, 50 or 64) each point fell inside at any hour of the track."""
    band = np.zeros(len(lat), dtype=int)
    for _, fix in hourly(track).iterrows():
        distance, bearing = _distance_and_bearing(fix["lat"], fix["lon"], lat, lon)
        quadrant = (bearing // 90).astype(int)  # 0 NE, 1 SE, 2 SW, 3 NW
        for kt in BANDS:
            radius = np.array([fix[f"r{kt}_{q}"] for q in QUADRANTS], dtype=float)[quadrant]
            inside = np.nan_to_num(radius, nan=0.0) > 0
            inside &= distance <= np.nan_to_num(radius, nan=0.0)
            band = np.where(inside & (band < kt), kt, band)
    return band


def storm_track(hurdat: pd.DataFrame, atcf_id: str) -> pd.DataFrame:
    """The storm's tropical-storm and hurricane fixes (status TS or HU). Post-tropical, depression and remnant
    stages are left out: their wide gradient winds would pull in states far from the damage (decision log)."""
    track = hurdat[(hurdat["atcf_id"] == atcf_id) & hurdat["status"].isin(["TS", "HU"])]
    if track.empty:
        raise ValueError(f"no TS/HU fixes for {atcf_id}")
    return track.reset_index(drop=True)


def wind_band_by_county(track: pd.DataFrame, counties: gpd.GeoDataFrame) -> pd.Series:
    """fips -> 0, 34, 50 or 64: the strongest zone containing the county's representative point."""
    points = counties.geometry.representative_point()
    bands = band_at_points(track, points.y.to_numpy(), points.x.to_numpy())
    return pd.Series(bands, index=counties["fips"].to_numpy(), name="wind_band")
