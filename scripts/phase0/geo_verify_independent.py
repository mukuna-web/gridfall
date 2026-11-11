"""Phase 0, agent `geo`: independent re-derivation of the G1-G5 evidence.

Run from the repo root (after geo_build.py and geo_checks.py):

    uv run python -I scripts/phase0/geo_verify_independent.py

Uses different code paths from geo_checks.py: sqlite3 on the GeoPackage, the raw
shapefile read through GDAL's zip driver, a latitude-line intersection for G5, and
pure WGS84 geodesics from the raw HURDAT2 text for G4. Exit code 0 means every check agreed.
"""

import json
import math
import sqlite3
import sys
import zipfile
from pathlib import Path

import pyogrio
from pyproj import Geod
from shapely.geometry import LineString, Point

REPO = Path(__file__).resolve().parents[2]
GPKG = REPO / "data/interim/fl_counties.gpkg"
ZIP = REPO / "data/raw/census/cb_2022_us_county_500k.zip"
RESULTS = json.loads((REPO / "data/interim/geo_checks.json").read_text())

failures = []


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        failures.append(label)


# 1. GPKG structure through sqlite directly (not geopandas)
con = sqlite3.connect(f"file:{GPKG}?mode=ro", uri=True)
layers = con.execute(
    "select table_name, data_type, srs_id from gpkg_contents"
).fetchall()
check(
    "gpkg has exactly one feature layer fl_counties",
    layers == [("fl_counties", "features", 4326)],
    str(layers),
)
cols = con.execute("pragma table_info(fl_counties)").fetchall()
col_desc = [(c[1], c[2]) for c in cols]
print("   table columns:", col_desc)
check(
    "gpkg columns are fid/geom/fips/name",
    [c[0] for c in col_desc] == ["fid", "geom", "fips", "name"],
)
check(
    "fips/name are TEXT",
    dict(col_desc).get("fips") == "TEXT" and dict(col_desc).get("name") == "TEXT",
)
n = con.execute(
    "select count(*), count(distinct fips), min(length(fips)), max(length(fips)) from fl_counties"
).fetchone()
check("67 rows, 67 distinct fips, all length 5", n == (67, 67, 5, 5), str(n))
srs = con.execute(
    "select organization, organization_coordsys_id from gpkg_spatial_ref_sys where srs_id=4326"
).fetchone()
check("srs 4326 is EPSG:4326", srs == ("EPSG", 4326), str(srs))
rows = {
    f: (name, bytes(g))
    for f, name, g in con.execute("select fips, name, geom from fl_counties")
}
con.close()

# 2. Bounds from the raw shapefile via pyogrio (NAD83) vs the gpkg (WGS84): same to ~1e-6 deg
with zipfile.ZipFile(ZIP) as zf:
    members = zf.namelist()
print("   zip members:", [m for m in members if m.endswith((".shp", ".dbf", ".prj"))])
raw = pyogrio.read_dataframe(f"/vsizip/{ZIP}", where="STATEFP = '12'")
check("raw shapefile Florida rows == 67", len(raw) == 67, str(len(raw)))
for fips in ("12071", "12015", "12021"):
    raw_geom = raw.loc[raw["GEOID"] == fips, "geometry"].iloc[0]
    gp = pyogrio.read_dataframe(GPKG, where=f"fips = '{fips}'")
    gp_geom = gp["geometry"].iloc[0]
    delta = max(abs(a - b) for a, b in zip(raw_geom.bounds, gp_geom.bounds))
    h = (
        math.floor((gp_geom.bounds[0] + 180) / 10),
        math.floor((gp_geom.bounds[2] + 180) / 10),
    )
    v = (
        math.floor((90 - gp_geom.bounds[3]) / 10),
        math.floor((90 - gp_geom.bounds[1]) / 10),
    )
    check(
        f"{fips} NAD83 vs WGS84 bounds agree",
        delta < 1e-6,
        f"max delta {delta:.2e} deg",
    )
    check(
        f"{fips} tile is h09 v06",
        h == (9, 9) and v == (6, 6),
        f"h={h} v={v} bounds={tuple(round(b, 4) for b in gp_geom.bounds)}",
    )
    print(f"   {fips} W,S,E,N = {', '.join(f'{b:.4f}' for b in gp_geom.bounds)}")

# 3. 30N crossing by line intersection (different method than tile-polygon overlap)
line = LineString([(-95, 30.0), (-75, 30.0)])
fl = pyogrio.read_dataframe(GPKG)
crossing = sorted(
    fl.loc[fl.geometry.map(lambda g: g.intersection(line).length > 0), "name"]
)
expected = sorted(r["name"] for r in RESULTS["G5"]["two_tile_counties"])
check(
    "30N crossing set (line method) == G5 set",
    crossing == expected,
    f"{len(crossing)} counties: {crossing}",
)

# 4. G4 independent: haversine/geodesic from raw HURDAT2 text, rep point inside polygon
lines = (
    (REPO / "data/raw/hurdat2/hurdat2-1851-2025-02272026.txt").read_text().splitlines()
)
raw_row = next(l for l in lines if l.startswith("20220928, 1905,"))
tok = [t.strip() for t in raw_row.split(",")]
lat = float(tok[4][:-1]) * (1 if tok[4][-1] == "N" else -1)
lon = float(tok[5][:-1]) * (-1 if tok[5][-1] == "W" else 1)
r = {
    kt: dict(zip(("ne", "se", "sw", "nw"), map(int, tok[8 + 4 * i : 12 + 4 * i])))
    for i, kt in enumerate((34, 50, 64))
}
print(f"   raw landfall row -> lat={lat} lon={lon} radii={r}")
check(
    "raw 64kt radii == G3 radii",
    r[64] == RESULTS["G3"]["cayo_costa"]["radii_nm"]["64"],
    str(r[64]),
)
geod = Geod(ellps="WGS84")
inside = {64: [], 50: [], 34: []}
table = {row["name"]: row for row in RESULTS["G4"]["table"]}
worst = 0.0
for _, c in fl.iterrows():
    t = table[c["name"]]
    rp = Point(t["rep_lon"], t["rep_lat"])
    # rep point must be inside its county polygon (4326 check of the 3086-derived point)
    if not c.geometry.buffer(1e-4).contains(rp):
        failures.append(f"rep point outside {c['name']}")
    az, _, d = geod.inv(lon, lat, rp.x, rp.y)
    az %= 360
    q = "ne" if az < 90 else "se" if az < 180 else "sw" if az < 270 else "nw"
    worst = max(worst, abs(d / 1000 - t["dist_km"]) / t["dist_km"])
    for kt in (64, 50, 34):
        if d <= r[kt][q] * 1852:
            inside[kt].append(c["name"])
for kt in (64, 50, 34):
    want = sorted(RESULTS["G4"]["inside"][str(kt)])
    check(
        f"G4 {kt} kt set (independent geodesic) == script set",
        sorted(inside[kt]) == want,
        f"{len(want)} counties",
    )
print(f"   max relative gap planar-vs-geodesic distance: {worst * 100:.3f}%")

print("\nFAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
