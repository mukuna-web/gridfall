"""Phase 0, agent `geo`: build the interim county, housing and Ian-track files.

Run from the repo root (after geo_fetch.py):

    uv run python -I scripts/phase0/geo_build.py

Reads  data/raw/census/ and data/raw/hurdat2/ (untrusted data: parsed, never executed)
Writes data/interim/fl_counties.gpkg      fips, name, geometry (EPSG:4326), 67 rows
       data/interim/fl_housing_acs2022.csv fips, housing_units (only when an ACS raw file exists)
       data/interim/ian_track.csv          HURDAT2 AL092022, one row per best-track record

Exit code: 0 all built, 1 error, 2 partial (the ACS housing file could not be built).
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CENSUS = REPO_ROOT / "data" / "raw" / "census"
RAW_HURDAT2 = REPO_ROOT / "data" / "raw" / "hurdat2"
INTERIM = REPO_ROOT / "data" / "interim"

COUNTY_ZIP = RAW_CENSUS / "cb_2022_us_county_500k.zip"
ACS_API_JSON = RAW_CENSUS / "acs5_2022_fl_B25001.json"
ACS_BULK_DAT = RAW_CENSUS / "acsdt5y2022-b25001.dat"
HURDAT2_TXT = RAW_HURDAT2 / "hurdat2-1851-2025-02272026.txt"

FL_STATEFP = "12"
FL_COUNTY_COUNT = 67
IAN_ID = "AL092022"

# HURDAT2 field layout: date, time, record id, status, lat, lon, wind, pressure,
# 12 wind radii (34/50/64 kt x NE/SE/SW/NW), then (2021+ files) radius of max wind.
THRESHOLDS_KT = (34, 50, 64)
QUADRANTS = ("ne", "se", "sw", "nw")
RADII_COLUMNS = tuple(f"r{kt}_{quad}_nm" for kt in THRESHOLDS_KT for quad in QUADRANTS)
TRACK_COLUMNS = (
    "time_utc",
    "record_id",
    "status",
    "lat",
    "lon",
    "max_wind_kt",
    "min_pressure_mb",
) + RADII_COLUMNS
NULLABLE_INT_COLUMNS = ("max_wind_kt", "min_pressure_mb") + RADII_COLUMNS
MISSING_WIND, MISSING_PRESSURE, MISSING_RADIUS = -99, -999, -999

STORM_HEADER = re.compile(
    r"^(?P<id>[A-Z]{2}\d{6}),\s*(?P<name>[^,]*?)\s*,\s*(?P<n>\d+),\s*$"
)
LAT_TOKEN = re.compile(r"^(?P<v>\d{1,2}(?:\.\d+)?)(?P<h>[NS])$")
LON_TOKEN = re.compile(r"^(?P<v>\d{1,3}(?:\.\d+)?)(?P<h>[EW])$")
COUNTY_GEO_ID = re.compile(r"^0500000US(?P<fips>12\d{3})$")


# ----------------------------------------------------------------------------- counties
def load_fl_counties(zip_path: Path) -> gpd.GeoDataFrame:
    """Florida rows of the cartographic county file as fips, name, geometry (EPSG:4326)."""
    raw = gpd.read_file(zip_path)  # geopandas reads the .shp inside the zip in place
    missing = {"STATEFP", "GEOID", "NAME", "geometry"} - set(raw.columns)
    if missing:
        raise ValueError(f"county file lacks columns {sorted(missing)}")
    if raw.crs is None:
        raise ValueError("county file has no CRS")
    florida = raw.loc[raw["STATEFP"] == FL_STATEFP]
    frame = gpd.GeoDataFrame(
        {
            "fips": florida["GEOID"].astype(str).to_numpy(),
            "name": florida["NAME"].astype(str).to_numpy(),
        },
        geometry=florida.geometry.to_numpy(),
        crs=raw.crs,
    )
    result = frame.to_crs("EPSG:4326").sort_values("fips").reset_index(drop=True)
    _validate_counties(result)
    return result


def _validate_counties(counties: gpd.GeoDataFrame) -> None:
    if len(counties) != FL_COUNTY_COUNT:
        raise ValueError(
            f"expected {FL_COUNTY_COUNT} Florida counties, got {len(counties)}"
        )
    if not counties["fips"].map(lambda f: isinstance(f, str) and len(f) == 5).all():
        raise ValueError("fips must be 5-character strings")
    if (
        not counties["fips"].str.startswith(FL_STATEFP).all()
        or counties["fips"].duplicated().any()
    ):
        raise ValueError("fips must be unique and start with 12")
    if counties.geometry.is_empty.any() or counties.geometry.isna().any():
        raise ValueError("empty or missing county geometry")
    if counties.crs is None or counties.crs.to_epsg() != 4326:
        raise ValueError("counties must be in EPSG:4326")


# ----------------------------------------------------------------------------- housing
def parse_acs_api_json(text: str) -> pd.DataFrame:
    """Census Data API array-of-arrays response -> fips, housing_units."""
    rows = json.loads(text)
    header, body = rows[0], rows[1:]
    position = {name: header.index(name) for name in ("B25001_001E", "state", "county")}
    records = [
        {
            "fips": r[position["state"]] + r[position["county"]],
            "housing_units": int(r[position["B25001_001E"]]),
        }
        for r in body
    ]
    return pd.DataFrame.from_records(records, columns=["fips", "housing_units"])


def parse_acs_bulk(source: Path | io.StringIO) -> pd.DataFrame:
    """ACS table-based summary file (GEO_ID|B25001_E001|B25001_M001) -> Florida counties."""
    table = pd.read_csv(source, sep="|", dtype=str, usecols=["GEO_ID", "B25001_E001"])
    matched = table["GEO_ID"].str.extract(COUNTY_GEO_ID)["fips"]
    florida = table.loc[matched.notna()]
    return pd.DataFrame(
        {
            "fips": matched.loc[matched.notna()].to_numpy(),
            "housing_units": florida["B25001_E001"].astype(int).to_numpy(),
        }
    )


def validate_housing(housing: pd.DataFrame) -> pd.DataFrame:
    """Boundary checks on the ACS rows; returns a sorted copy."""
    if len(housing) != FL_COUNTY_COUNT:
        raise ValueError(
            f"expected {FL_COUNTY_COUNT} ACS Florida counties, got {len(housing)}"
        )
    if not housing["fips"].map(lambda f: isinstance(f, str) and len(f) == 5).all():
        raise ValueError("ACS fips must be 5-character strings")
    if (
        housing["fips"].duplicated().any()
        or not housing["fips"].str.startswith(FL_STATEFP).all()
    ):
        raise ValueError("ACS fips must be unique and start with 12")
    if not (housing["housing_units"] > 0).all():
        raise ValueError(
            "housing units must be positive (Census uses negative sentinels for n/a)"
        )
    return housing.sort_values("fips").reset_index(drop=True)


def load_housing() -> tuple[pd.DataFrame | None, str]:
    """Build the housing frame from whichever ACS raw file exists. Returns (frame, source)."""
    if ACS_API_JSON.exists():
        return validate_housing(
            parse_acs_api_json(ACS_API_JSON.read_text())
        ), ACS_API_JSON.name
    if ACS_BULK_DAT.exists():
        return validate_housing(parse_acs_bulk(ACS_BULK_DAT)), ACS_BULK_DAT.name
    return None, "no ACS raw file in data/raw/census/"


# ----------------------------------------------------------------------------- HURDAT2
def _optional_int(token: str, missing: int) -> int | None:
    value = int(token)
    return None if value == missing else value


def _coordinate(
    token: str, pattern: re.Pattern[str], negative: str, limit: float
) -> float:
    match = pattern.match(token)
    if not match:
        raise ValueError(f"bad coordinate token {token!r}")
    value = float(match["v"]) * (-1.0 if match["h"] == negative else 1.0)
    if abs(value) > limit:
        raise ValueError(f"coordinate {token!r} out of range")
    return value


def parse_track_line(line: str) -> dict[str, object]:
    """One HURDAT2 data line -> a row dict. -99/-999 sentinels become None."""
    fields = [token.strip() for token in line.strip().rstrip(",").split(",")]
    if len(fields) not in (20, 21):
        raise ValueError(f"expected 20 or 21 fields, got {len(fields)}: {line!r}")
    date, hhmm, record_id, status, lat, lon, wind, pressure, *rest = fields
    row: dict[str, object] = {
        "time_utc": datetime.strptime(date + hhmm, "%Y%m%d%H%M").strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "record_id": record_id,
        "status": status,
        "lat": _coordinate(lat, LAT_TOKEN, "S", 90.0),
        "lon": _coordinate(lon, LON_TOKEN, "W", 180.0),
        "max_wind_kt": _optional_int(wind, MISSING_WIND),
        "min_pressure_mb": _optional_int(pressure, MISSING_PRESSURE),
    }
    row.update(
        {
            col: _optional_int(tok, MISSING_RADIUS)
            for col, tok in zip(RADII_COLUMNS, rest[:12])
        }
    )
    return row


def extract_storm_block(lines: list[str], storm_id: str) -> list[str]:
    """Data lines of one storm; checks the header's declared entry count."""
    starts = [
        i
        for i, text in enumerate(lines)
        if (m := STORM_HEADER.match(text.rstrip("\n"))) and m["id"] == storm_id
    ]
    if len(starts) != 1:
        raise ValueError(
            f"{storm_id}: expected exactly one header line, found {len(starts)}"
        )
    start = starts[0]
    declared = int(STORM_HEADER.match(lines[start].rstrip("\n"))["n"])
    block = lines[start + 1 : start + 1 + declared]
    if len(block) != declared or any(STORM_HEADER.match(b.rstrip("\n")) for b in block):
        raise ValueError(
            f"{storm_id}: header declares {declared} entries but block is malformed"
        )
    return block


def build_track(lines: list[str], storm_id: str) -> pd.DataFrame:
    rows = [parse_track_line(text) for text in extract_storm_block(lines, storm_id)]
    track = pd.DataFrame(rows, columns=list(TRACK_COLUMNS))
    track = track.astype({col: "Int64" for col in NULLABLE_INT_COLUMNS})
    if (
        not track["time_utc"].is_monotonic_increasing
        or track["time_utc"].duplicated().any()
    ):
        raise ValueError("track times must be strictly increasing")
    return track


# ----------------------------------------------------------------------------- self-test
def _expect(label: str, got: object, want: object) -> None:
    if got != want:
        raise AssertionError(
            f"parser self-test failed [{label}]: got {got!r}, want {want!r}"
        )


def selftest() -> None:
    """Synthetic-line checks of the parsers, run on every build."""
    landfall = parse_track_line(
        "20220928, 1905, L, HU, 26.7N,  82.2W, 130,  941,  130,  150,  100,  150,"
        "   50,   60,   70,   80,   30,   40,   30,   45,   20"
    )
    _expect("time", landfall["time_utc"], "2022-09-28T19:05:00Z")
    _expect("coords", (landfall["lat"], landfall["lon"]), (26.7, -82.2))
    _expect("r64", [landfall[f"r64_{q}_nm"] for q in QUADRANTS], [30, 40, 30, 45])
    old = parse_track_line(
        "18510625, 0000,  , HU, 10.5S, 120.0E,  -99, -999, -999, -999, -999, -999,"
        " -999, -999, -999, -999,    0, -999, -999, -999"
    )
    _expect("blank id", old["record_id"], "")
    _expect("hemispheres", (old["lat"], old["lon"]), (-10.5, 120.0))
    _expect("-99 wind", old["max_wind_kt"], None)
    _expect("-999 pressure", old["min_pressure_mb"], None)
    _expect("-999 radius", old["r34_ne_nm"], None)
    _expect("zero radius kept", old["r64_ne_nm"], 0)
    api = parse_acs_api_json(
        '[["NAME","B25001_001E","state","county"],["X County, Florida","123","12","071"]]'
    )
    _expect("api fips", api["fips"].tolist(), ["12071"])
    bulk = parse_acs_bulk(
        io.StringIO(
            "GEO_ID|B25001_E001|B25001_M001\n0100000US|10|1\n0400000US12|9|1\n0500000US12071|5|2\n0500000US13001|4|2\n"
        )
    )
    _expect(
        "bulk filter",
        (bulk["fips"].tolist(), bulk["housing_units"].tolist()),
        (["12071"], [5]),
    )


# ----------------------------------------------------------------------------- writers
def _atomic_write(path: Path, write: Callable[[Path], None]) -> None:
    temp = path.with_name(
        f"{path.stem}.tmp{path.suffix}"
    )  # keeps the extension GDAL expects
    try:
        write(temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_gpkg(counties: gpd.GeoDataFrame, path: Path) -> None:
    _atomic_write(
        path, lambda t: counties.to_file(t, driver="GPKG", layer="fl_counties")
    )


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    _atomic_write(
        path, lambda t: frame.to_csv(t, index=False, na_rep="", lineterminator="\n")
    )


def main() -> int:
    selftest()
    print("parser self-test: OK")
    INTERIM.mkdir(parents=True, exist_ok=True)

    counties = load_fl_counties(COUNTY_ZIP)
    write_gpkg(counties, INTERIM / "fl_counties.gpkg")
    print(
        f"wrote data/interim/fl_counties.gpkg: {len(counties)} counties, CRS {counties.crs}"
    )

    track = build_track(HURDAT2_TXT.read_text(encoding="utf-8").splitlines(), IAN_ID)
    write_csv(track, INTERIM / "ian_track.csv")
    print(
        f"wrote data/interim/ian_track.csv: {len(track)} records "
        f"{track['time_utc'].iloc[0]} .. {track['time_utc'].iloc[-1]}"
    )

    housing, source = load_housing()
    if housing is None:
        print(f"SKIPPED data/interim/fl_housing_acs2022.csv: {source}")
        return 2
    write_csv(housing, INTERIM / "fl_housing_acs2022.csv")
    print(
        f"wrote data/interim/fl_housing_acs2022.csv: {len(housing)} counties from {source}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, AssertionError, KeyError, RuntimeError) as error:
        print(f"BUILD FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
