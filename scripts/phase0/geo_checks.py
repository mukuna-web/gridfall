"""Phase 0, agent `geo`: tests G1-G5 against the interim files.

Run from the repo root (after geo_build.py):

    uv run python -I scripts/phase0/geo_checks.py

Prints the evidence for each test and writes data/interim/geo_checks.json.
Exit code: 0 every test PASS, 1 any FAIL, 2 nothing failed but a part is BLOCKED.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod
from shapely.geometry import Point, Polygon, box

REPO_ROOT = Path(__file__).resolve().parents[2]
INTERIM = REPO_ROOT / "data" / "interim"
RAW_HURDAT2 = REPO_ROOT / "data" / "raw" / "hurdat2" / "hurdat2-1851-2025-02272026.txt"
COUNTIES_GPKG = INTERIM / "fl_counties.gpkg"
HOUSING_CSV = INTERIM / "fl_housing_acs2022.csv"
TRACK_CSV = INTERIM / "ian_track.csv"
RESULTS_JSON = INTERIM / "geo_checks.json"

TARGETS = {"12071": "Lee", "12015": "Charlotte", "12021": "Collier"}
EXPECTED_TILE = "h09v06"
TILE_DEG = 10
NM_TO_M = 1852.0
METRIC_CRS = "EPSG:3086"  # NAD83(HARN) / Florida GDL Albers, metres
THRESHOLDS_KT = (64, 50, 34)
QUADRANTS = ("ne", "se", "sw", "nw")
LATITUDE_SPLIT = 30.0
POSITION_STEP_DEG = (
    0.05  # HURDAT2 rounds positions to 0.1 degree, so the true centre is within +/-0.05
)
CAYO_COSTA_MAX_KM_FROM_LEE = 15.0


@dataclass(frozen=True)
class Outcome:
    test: str
    status: str  # PASS | FAIL | BLOCKED
    summary: str
    evidence: tuple[str, ...]
    data: dict


# ----------------------------------------------------------------------------- tiles
def tile_h(lon: float) -> int:
    return math.floor((lon + 180.0) / TILE_DEG)


def tile_v(lat: float) -> int:
    return math.floor((90.0 - lat) / TILE_DEG)


def tile_name(h: int, v: int) -> str:
    return f"h{h:02d}v{v:02d}"


def tile_box(h: int, v: int) -> Polygon:
    west = h * TILE_DEG - 180
    north = 90 - v * TILE_DEG
    return box(west, north - TILE_DEG, west + TILE_DEG, north)


def tiles_by_bounds(west: float, south: float, east: float, north: float) -> list[str]:
    return [
        tile_name(h, v)
        for v in range(tile_v(north), tile_v(south) + 1)
        for h in range(tile_h(west), tile_h(east) + 1)
    ]


def tiles_by_polygon(geometry) -> list[str]:
    """Tiles the county polygon actually overlaps (area > 0), not just its bbox."""
    west, south, east, north = geometry.bounds
    return [
        tile_name(h, v)
        for v in range(tile_v(north), tile_v(south) + 1)
        for h in range(tile_h(west), tile_h(east) + 1)
        if geometry.intersection(tile_box(h, v)).area > 0
    ]


# ----------------------------------------------------------------------------- loaders
def load_inputs() -> tuple[gpd.GeoDataFrame, pd.DataFrame | None, pd.DataFrame]:
    counties = gpd.read_file(COUNTIES_GPKG)
    housing = (
        pd.read_csv(HOUSING_CSV, dtype={"fips": str}) if HOUSING_CSV.exists() else None
    )
    track = pd.read_csv(TRACK_CSV, dtype={"record_id": str})
    return counties, housing, track


def _is_fips(series: pd.Series) -> bool:
    return bool(
        series.map(lambda f: isinstance(f, str) and len(f) == 5 and f.isdigit()).all()
    )


# ----------------------------------------------------------------------------- G1
def _g1_shapefile_problems(counties: gpd.GeoDataFrame) -> list[str]:
    absent = sorted(set(TARGETS) - set(counties["fips"]))
    checks = [
        (len(counties) != 67, f"shapefile has {len(counties)} FL counties, want 67"),
        (
            not _is_fips(counties["fips"]),
            "shapefile fips are not all 5-character digit strings",
        ),
        (
            bool(counties["fips"].duplicated().any()),
            "duplicate fips in the county file",
        ),
        (
            list(counties.columns) != ["fips", "name", "geometry"],
            f"unexpected columns {list(counties.columns)}",
        ),
        (
            counties.crs is None or counties.crs.to_epsg() != 4326,
            f"county CRS is {counties.crs}, want EPSG:4326",
        ),
        (bool(absent), f"missing target counties {absent}"),
    ]
    return [message for failed, message in checks if failed]


def _g1_acs_part(
    counties: gpd.GeoDataFrame, housing: pd.DataFrame
) -> tuple[list[str], list[str], dict[str, int]]:
    """(evidence, problems, housing units of the target counties) for the ACS half."""
    same_set = set(housing["fips"]) == set(counties["fips"])
    checks = [
        (len(housing) != 67, f"ACS has {len(housing)} rows, want 67"),
        (
            not _is_fips(housing["fips"]),
            "ACS fips are not all 5-character digit strings",
        ),
        (not same_set, "ACS fips set differs from the shapefile fips set"),
    ]
    units = housing.set_index("fips")["housing_units"]
    evidence = [
        f"ACS: {len(housing)} rows, fips dtype {housing['fips'].dtype}, same fips set as shapefile: {same_set}",
        "housing units: "
        + ", ".join(f"{TARGETS[f]} ({f}) = {units.get(f)}" for f in TARGETS),
    ]
    return (
        evidence,
        [m for failed, m in checks if failed],
        {f: int(units[f]) for f in TARGETS if f in units.index},
    )


def check_g1(counties: gpd.GeoDataFrame, housing: pd.DataFrame | None) -> Outcome:
    problems = _g1_shapefile_problems(counties)
    names = counties.set_index("fips")["name"]
    evidence = [
        (
            f"shapefile: {len(counties)} counties, fips dtype {counties['fips'].dtype}, "
            f"CRS {counties.crs.to_string() if counties.crs else None}, columns {list(counties.columns)}"
        ),
        "targets present: " + ", ".join(f"{f}={names.get(f)}" for f in TARGETS),
    ]
    units: dict[str, int] = {}
    if housing is None:
        evidence.append(
            "ACS half: BLOCKED - no data/interim/fl_housing_acs2022.csv (Census API needs a key)"
        )
    else:
        acs_evidence, acs_problems, units = _g1_acs_part(counties, housing)
        evidence, problems = [*evidence, *acs_evidence], [*problems, *acs_problems]

    status = "FAIL" if problems else ("BLOCKED" if housing is None else "PASS")
    summary = (
        "; ".join(problems)
        if problems
        else (
            "shapefile half PASS; ACS half BLOCKED"
            if housing is None
            else "67 counties in both"
        )
    )
    data = {"shapefile_count": len(counties), "housing_units": units}
    return Outcome("G1", status, summary, tuple(evidence), data)


# ----------------------------------------------------------------------------- G2
def check_g2(counties: gpd.GeoDataFrame) -> Outcome:
    evidence: list[str] = []
    data: dict = {}
    problems: list[str] = []
    for fips, label in TARGETS.items():
        geometry = counties.loc[counties["fips"] == fips, "geometry"].iloc[0]
        west, south, east, north = geometry.bounds
        by_bounds = tiles_by_bounds(west, south, east, north)
        by_polygon = tiles_by_polygon(geometry)
        data[fips] = {
            "name": label,
            "bounds_wsen": [west, south, east, north],
            "tiles_bbox": by_bounds,
            "tiles_polygon": by_polygon,
        }
        evidence.append(
            f"{label} ({fips}): W={west:.4f} S={south:.4f} E={east:.4f} N={north:.4f} "
            f"-> h={tile_h(west)}..{tile_h(east)} v={tile_v(north)}..{tile_v(south)} "
            f"-> bbox tiles {by_bounds}, polygon tiles {by_polygon}"
        )
        if by_bounds != [EXPECTED_TILE] or by_polygon != [EXPECTED_TILE]:
            problems.append(
                f"{label} needs {by_bounds}/{by_polygon}, want [{EXPECTED_TILE}]"
            )
    status = "FAIL" if problems else "PASS"
    return Outcome(
        "G2",
        status,
        "; ".join(problems) or f"all three need only {EXPECTED_TILE}",
        tuple(evidence),
        data,
    )


# ----------------------------------------------------------------------------- G3
def raw_ian_tokens() -> list[list[str]]:
    """Independent re-read of the raw HURDAT2 Ian block (token lists, no conversion)."""
    lines = RAW_HURDAT2.read_text(encoding="utf-8").splitlines()
    start = next(i for i, text in enumerate(lines) if text.startswith("AL092022,"))
    declared = int(lines[start].split(",")[2])
    return [
        [t.strip() for t in text.split(",")]
        for text in lines[start + 1 : start + 1 + declared]
    ]


def _csv_int(value) -> int | None:
    return None if pd.isna(value) else int(value)


def _row_mismatches(tokens: list[str], row: pd.Series, columns: list[str]) -> list[str]:
    """Differences between one raw HURDAT2 token list and the matching CSV row."""
    stamp = datetime.strptime(tokens[0] + tokens[1], "%Y%m%d%H%M").strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    lat = f"{abs(row['lat']):.1f}{'N' if row['lat'] >= 0 else 'S'}"
    lon = f"{abs(row['lon']):.1f}{'W' if row['lon'] < 0 else 'E'}"
    record = "" if pd.isna(row["record_id"]) else row["record_id"]
    raw_header = (stamp, tokens[2], tokens[3], tokens[4], tokens[5])
    csv_header = (row["time_utc"], record, row["status"], lat, lon)
    raw_numbers = [None if int(t) in (-99, -999) else int(t) for t in tokens[6:20]]
    csv_numbers = [_csv_int(row[c]) for c in columns[5:19]]  # wind, pressure, 12 radii
    found = []
    if raw_header != csv_header:
        found.append(f"{stamp}: time/id/status/position differ")
    if raw_numbers != csv_numbers:
        found.append(f"{stamp}: wind/pressure/radii differ")
    return found


def crosscheck_track_against_raw(track: pd.DataFrame) -> list[str]:
    """Compare every CSV row with the raw tokens; returns a list of mismatch messages."""
    raw = raw_ian_tokens()
    if len(raw) != len(track):
        return [f"row count: raw {len(raw)} vs csv {len(track)}"]
    columns = list(track.columns)
    return [
        m
        for tokens, (_, row) in zip(raw, track.iterrows())
        for m in _row_mismatches(tokens, row, columns)
    ]


def radii_nest(track: pd.DataFrame) -> bool:
    """Higher thresholds must not reach farther: r64 <= r50 <= r34 in every quadrant."""
    return all(
        (
            (track[f"r64_{q}_nm"] <= track[f"r50_{q}_nm"])
            & (track[f"r50_{q}_nm"] <= track[f"r34_{q}_nm"])
        ).all()
        for q in QUADRANTS
    )


def landfall_radii(row: pd.Series) -> dict[int, dict[str, int]]:
    radii = {kt: {q: row[f"r{kt}_{q}_nm"] for q in QUADRANTS} for kt in THRESHOLDS_KT}
    if any(pd.isna(v) for per_kt in radii.values() for v in per_kt.values()):
        raise ValueError(
            "landfall record has a missing wind radius; cannot build a wind band"
        )
    return {kt: {q: int(v) for q, v in per_kt.items()} for kt, per_kt in radii.items()}


def annotate_landfalls(track: pd.DataFrame, counties: gpd.GeoDataFrame) -> pd.DataFrame:
    """The 'L' records plus the nearest Florida county and the distance to Lee County (km)."""
    landfalls = track.loc[track["record_id"] == "L"].reset_index(drop=True)
    metric = counties.to_crs(METRIC_CRS)
    points = gpd.GeoSeries(
        gpd.points_from_xy(landfalls["lon"], landfalls["lat"]), crs="EPSG:4326"
    ).to_crs(METRIC_CRS)
    km = (
        np.array([metric.distance(point).to_numpy() for point in points]) / 1000.0
    )  # (landfalls, counties)
    nearest = km.argmin(axis=1)
    lee = int(np.flatnonzero(counties["fips"].to_numpy() == "12071")[0])
    return landfalls.assign(
        nearest_county=counties["name"].to_numpy()[nearest],
        km_to_nearest=km[np.arange(len(landfalls)), nearest],
        km_to_lee=km[:, lee],
    )


def pick_cayo_costa(landfalls: pd.DataFrame) -> pd.Series:
    """Cayo Costa is a Lee County barrier island: take the 'L' record closest to Lee."""
    return landfalls.loc[landfalls["km_to_lee"].idxmin()]


def _landfall_line(row: pd.Series, chosen_time: str) -> str:
    mark = "  <- Cayo Costa" if row["time_utc"] == chosen_time else ""
    where = (
        f"inside {row['nearest_county']}"
        if row["km_to_nearest"] == 0
        else f"{row['km_to_nearest']:.1f} km from {row['nearest_county']}"
    )
    return (
        f"  {row['time_utc']}  {row['lat']:.1f}N {abs(row['lon']):.1f}W  {row['status']} "
        f"{int(row['max_wind_kt'])} kt {int(row['min_pressure_mb'])} mb  "
        f"[{where}; {row['km_to_lee']:.1f} km from Lee]{mark}"
    )


def check_g3(track: pd.DataFrame, counties: gpd.GeoDataFrame) -> Outcome:
    landfalls = annotate_landfalls(track, counties)
    chosen = pick_cayo_costa(landfalls)
    radii = landfall_radii(chosen)
    local = datetime.fromisoformat(chosen["time_utc"]).astimezone(
        ZoneInfo("America/New_York")
    )
    mismatches = crosscheck_track_against_raw(track)
    nests = radii_nest(track)

    evidence = [
        "'L' records in AL092022 (UTC; distances are to Florida county polygons, which stop at the shoreline):"
    ]
    evidence += [
        _landfall_line(row, chosen["time_utc"]) for _, row in landfalls.iterrows()
    ]
    evidence.append(
        f"Cayo Costa landfall = {chosen['time_utc']} = {local:%Y-%m-%d %H:%M %Z} local"
    )
    for kt in THRESHOLDS_KT:
        per = radii[kt]
        evidence.append(
            f"  {kt} kt radii (nm): NE {per['ne']}  SE {per['se']}  SW {per['sw']}  NW {per['nw']}"
        )
    evidence.append(
        f"CSV vs raw HURDAT2 re-read: {len(track)} rows, {len(mismatches)} mismatches; "
        f"r64<=r50<=r34 in every quadrant of every record: {nests}"
    )

    problems = []
    if chosen["km_to_lee"] > CAYO_COSTA_MAX_KM_FROM_LEE:
        problems.append(
            f"closest L record is {chosen['km_to_lee']:.1f} km from Lee, expected <{CAYO_COSTA_MAX_KM_FROM_LEE:.0f}"
        )
    if mismatches or not nests:
        problems.append(f"csv/raw mismatches {mismatches[:3]} nests={nests}")
    radii_cols = [c for c in landfalls.columns if c.startswith(("r34", "r50", "r64"))]
    data = {
        "landfall_records": landfalls.drop(columns=radii_cols).to_dict("records"),
        "cayo_costa": {
            "time_utc": chosen["time_utc"],
            "lat": float(chosen["lat"]),
            "lon": float(chosen["lon"]),
            "local": f"{local:%Y-%m-%d %H:%M %Z}",
            "radii_nm": radii,
        },
    }
    summary = (
        "; ".join(problems)
        or f"{len(landfalls)} L records parsed; Cayo Costa row identified"
    )
    return Outcome("G3", "FAIL" if problems else "PASS", summary, tuple(evidence), data)


# ----------------------------------------------------------------------------- G4
def quadrant_of(bearing_deg: float) -> str:
    """Clockwise from north, closed on the left: NE [0,90), SE [90,180), SW [180,270), NW [270,360)."""
    bearing = bearing_deg % 360.0
    return (
        "ne"
        if bearing < 90
        else "se"
        if bearing < 180
        else "sw"
        if bearing < 270
        else "nw"
    )


def _band_columns(
    dist_m: np.ndarray, quads: list[str], radii_nm: dict[int, dict[str, int]]
) -> dict[str, np.ndarray]:
    columns: dict[str, np.ndarray] = {}
    for kt in THRESHOLDS_KT:
        radius_m = np.array([radii_nm[kt][q] for q in quads], dtype=float) * NM_TO_M
        columns[f"r{kt}_km"] = radius_m / 1000.0
        columns[f"in{kt}"] = dist_m <= radius_m
        columns[f"margin{kt}_km"] = (radius_m - dist_m) / 1000.0
    return columns


def representative_points(counties: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """geometry.representative_point() computed in the metric CRS."""
    return counties.to_crs(METRIC_CRS).geometry.representative_point()


def planar_band_table(
    counties: gpd.GeoDataFrame,
    reps: gpd.GeoSeries,
    lon: float,
    lat: float,
    radii_nm: dict[int, dict[str, int]],
) -> pd.DataFrame:
    """Distance/bearing from the landfall point to each representative point, planar in EPSG:3086."""
    origin = (
        gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(METRIC_CRS).iloc[0]
    )
    dx, dy = reps.x.to_numpy() - origin.x, reps.y.to_numpy() - origin.y
    dist_m = np.hypot(dx, dy)
    bearing = (
        np.degrees(np.arctan2(dx, dy)) % 360.0
    )  # grid bearing, clockwise from the projection's north
    quads = [quadrant_of(b) for b in bearing]
    return pd.DataFrame(
        {
            "fips": counties["fips"].to_numpy(),
            "name": counties["name"].to_numpy(),
            "dist_km": dist_m / 1000.0,
            "bearing_deg": bearing,
            "quad": quads,
            **_band_columns(dist_m, quads, radii_nm),
        }
    )


def geodesic_band_table(
    reps: gpd.GeoSeries, lon: float, lat: float, radii_nm: dict[int, dict[str, int]]
) -> pd.DataFrame:
    """Same test with true WGS84 geodesic distance and azimuth (cross-check of the planar version)."""
    ll = reps.to_crs("EPSG:4326")
    n = len(ll)
    azimuth, _, dist_m = Geod(ellps="WGS84").inv(
        np.full(n, lon), np.full(n, lat), ll.x.to_numpy(), ll.y.to_numpy()
    )
    dist_m, azimuth = np.asarray(dist_m), np.asarray(azimuth)
    quads = [quadrant_of(a) for a in azimuth]
    return pd.DataFrame(
        {
            "dist_km": dist_m / 1000.0,
            "bearing_deg": azimuth % 360.0,
            "quad": quads,
            **_band_columns(dist_m, quads, radii_nm),
        }
    )


def shifted_flip_counts(
    counties, reps, lon, lat, radii_nm, baseline
) -> dict[int, dict[str, int]]:
    """Counties whose band membership changes when the landfall point moves +/-0.05 deg (8 shifts)."""
    shifts = [
        (dlat, dlon)
        for dlat in (-1, 0, 1)
        for dlon in (-1, 0, 1)
        if (dlat, dlon) != (0, 0)
    ]
    tables = [
        planar_band_table(
            counties,
            reps,
            lon + dlon * POSITION_STEP_DEG,
            lat + dlat * POSITION_STEP_DEG,
            radii_nm,
        )
        for dlat, dlon in shifts
    ]
    result: dict[int, dict[str, int]] = {}
    for kt in THRESHOLDS_KT:
        counts = sum(
            (t[f"in{kt}"].to_numpy() != baseline[f"in{kt}"].to_numpy()).astype(int)
            for t in tables
        )
        result[kt] = {
            name: int(c) for name, c in zip(baseline["name"], counts) if c > 0
        }
    return result


def _band_lines(table: pd.DataFrame, kt: int) -> list[str]:
    inside = table.loc[table[f"in{kt}"]].sort_values("dist_km")
    lines = [f"{kt} kt: {len(inside)} of {len(table)} counties inside"]
    for _, r in inside.iterrows():
        lines.append(
            f"    {r['name']:<12} {r['fips']}  d={r['dist_km']:6.1f} km  bearing={r['bearing_deg']:5.1f} "
            f"{r['quad'].upper()}  radius={r[f'r{kt}_km']:6.1f} km  margin={r[f'margin{kt}_km']:+6.1f} km"
        )
    outside = (
        table.loc[~table[f"in{kt}"]]
        .sort_values(f"margin{kt}_km", ascending=False)
        .head(3)
    )
    lines.append(
        "    nearest misses: "
        + "; ".join(
            f"{r['name']} ({r[f'margin{kt}_km']:+.1f} km)"
            for _, r in outside.iterrows()
        )
    )
    return lines


def check_g4(counties: gpd.GeoDataFrame, track: pd.DataFrame) -> Outcome:
    chosen = pick_cayo_costa(annotate_landfalls(track, counties))
    radii = landfall_radii(chosen)
    lon, lat = float(chosen["lon"]), float(chosen["lat"])
    reps = representative_points(counties)
    planar = planar_band_table(counties, reps, lon, lat, radii)
    geodesic = geodesic_band_table(reps, lon, lat, radii)
    flips = shifted_flip_counts(counties, reps, lon, lat, radii, planar)
    geodesic_flips = {
        str(kt): planar.loc[planar[f"in{kt}"] != geodesic[f"in{kt}"], "name"].tolist()
        for kt in THRESHOLDS_KT
    }

    evidence = [
        (
            f"landfall point {chosen['time_utc']} {lat:.1f}N {abs(lon):.1f}W; planar {METRIC_CRS}, "
            f"1 nm = {NM_TO_M:.0f} m; representative_point() taken in {METRIC_CRS}"
        )
    ]
    for kt in THRESHOLDS_KT:
        evidence += _band_lines(planar, kt)
    gap_pct = float(
        (
            (planar["dist_km"] - geodesic["dist_km"]).abs()
            / geodesic["dist_km"].clip(lower=1e-9)
        ).max()
        * 100
    )
    turn = float(
        np.abs(
            ((planar["bearing_deg"] - geodesic["bearing_deg"] + 180) % 360) - 180
        ).max()
    )
    evidence.append(
        f"geodesic cross-check: classification flips {geodesic_flips}; max distance gap {gap_pct:.2f}%; "
        f"max azimuth gap {turn:.1f} deg (grid convergence)"
    )
    evidence.append(
        f"membership flips if the landfall point moves up to +/-{POSITION_STEP_DEG} deg (of 8 shifts): "
        + json.dumps({str(kt): v for kt, v in flips.items()})
    )
    rep_ll = reps.to_crs("EPSG:4326")
    table = planar.assign(
        rep_lon=rep_ll.x.to_numpy(), rep_lat=rep_ll.y.to_numpy()
    ).round(4)
    data = {
        "inside": {
            str(kt): planar.loc[planar[f"in{kt}"], "name"].tolist()
            for kt in THRESHOLDS_KT
        },
        "position_flips": {str(kt): v for kt, v in flips.items()},
        "geodesic_flips": geodesic_flips,
        "table": table.to_dict("records"),
    }
    return Outcome(
        "G4", "PASS", "wind bands computed (preview only)", tuple(evidence), data
    )


# ----------------------------------------------------------------------------- G5
def _county_extent_rows(counties: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for _, county in counties.iterrows():
        west, south, east, north = county.geometry.bounds
        rows.append(
            {
                "fips": county["fips"],
                "name": county["name"],
                "south": south,
                "north": north,
                "west": west,
                "east": east,
                "tiles": tiles_by_polygon(county.geometry),
                "crosses_bbox": south < LATITUDE_SPLIT < north,
            }
        )
    return pd.DataFrame(rows)


def _nearest_non_crossing(
    table: pd.DataFrame, crossing: set[str], k: int = 4
) -> list[str]:
    others = table.loc[~table["fips"].isin(crossing)]
    gap = np.where(
        others["north"] < LATITUDE_SPLIT,
        LATITUDE_SPLIT - others["north"],
        others["south"] - LATITUDE_SPLIT,
    )
    nearest = others.assign(gap_deg=gap).nsmallest(k, "gap_deg")
    return [
        f"{r.name_} {'N' if r.north < LATITUDE_SPLIT else 'S'}="
        f"{r.north if r.north < LATITUDE_SPLIT else r.south:.4f}"
        for r in nearest.rename(columns={"name": "name_"}).itertuples()
    ]


def check_g5(counties: gpd.GeoDataFrame) -> Outcome:
    table = _county_extent_rows(counties)
    two = table[table["tiles"].map(lambda t: {"v05", "v06"} <= {x[3:] for x in t})]
    disagree = table.loc[table["crosses_bbox"] != table["fips"].isin(two["fips"])]
    west, south, east, north = counties.total_bounds
    all_tiles = sorted({t for ts in table["tiles"] for t in ts})

    evidence = [
        f"{len(two)} counties need both v05 and v06 (polygon overlaps both tile rows):"
    ]
    evidence += [
        f"    {r['name']:<10} {r['fips']}  S={r['south']:.4f} N={r['north']:.4f}  tiles={r['tiles']}"
        for _, r in two.sort_values("south").iterrows()
    ]
    evidence.append(
        f"bbox test (S<30<N) disagrees with the polygon test for: {disagree['name'].tolist()}"
    )
    evidence.append(
        "nearest counties that do NOT cross: "
        + "; ".join(_nearest_non_crossing(table, set(two["fips"])))
    )
    evidence.append(
        f"Florida extent W={west:.4f} S={south:.4f} E={east:.4f} N={north:.4f}; "
        f"tiles used by any county: {all_tiles}"
    )
    data = {
        "two_tile_counties": two[["fips", "name", "south", "north"]].to_dict("records"),
        "all_tiles": all_tiles,
        "florida_extent_wsen": [west, south, east, north],
    }
    status = "FAIL" if len(disagree) else "PASS"
    return Outcome(
        "G5", status, f"{len(two)} counties cross 30N", tuple(evidence), data
    )


# ----------------------------------------------------------------------------- driver
def _json_default(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"not serializable: {type(value)}")


def main() -> int:
    counties, housing, track = load_inputs()
    outcomes = [
        check_g1(counties, housing),
        check_g2(counties),
        check_g3(track, counties),
        check_g4(counties, track),
        check_g5(counties),
    ]
    for outcome in outcomes:
        print(f"\n=== {outcome.test}: {outcome.status} - {outcome.summary}")
        for line in outcome.evidence:
            print("  " + line)
    results = {
        o.test: {"status": o.status, "summary": o.summary, **o.data} for o in outcomes
    }
    RESULTS_JSON.write_text(json.dumps(results, indent=2, default=_json_default) + "\n")
    print("\nSUMMARY: " + ", ".join(f"{o.test}={o.status}" for o in outcomes))
    statuses = {o.status for o in outcomes}
    return 1 if "FAIL" in statuses else 2 if "BLOCKED" in statuses else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, StopIteration) as error:
        print(f"CHECKS FAILED TO RUN: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
