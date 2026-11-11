# Agent `geo`: Census counties, ACS housing units, Ian's HURDAT2 track

Phase 0, Hurricane Ian (AL092022), Lee County FL (12071). Written 2026-11-05 by agent `geo`.
Everything here is reproducible with the scripts listed in section 7.

## Status

| Item | Result |
|---|---|
| Task 1: Florida counties | Done: `data/interim/fl_counties.gpkg` |
| Task 2: ACS 2022 housing units | **BLOCKED**: the Census API now requires a key (section 1). `fl_housing_acs2022.csv` was not produced |
| Task 3: Ian track | Done: `data/interim/ian_track.csv`, 40 records |
| G1: 67 counties in both sources | **Partial**: shapefile half PASS, ACS half BLOCKED |
| G2: bounding boxes and Black Marble tiles | PASS: Lee, Charlotte and Collier all need only h09v06 |
| G3: Ian landfall records | PASS: 5 `L` records; Florida (Cayo Costa) landfall = 2022-09-28 19:05 UTC |
| G4: rough wind bands (preview) | PASS: 4 counties inside the 64 kt sectors, 29 inside the 34 kt sectors |
| G5: counties crossing 30°N | PASS: 13 counties need both v05 and v06 |

## 1. Blocker: the ACS download (needs a decision)

`https://api.census.gov/data/2022/acs/acs5?get=NAME,B25001_001E&for=county:*&in=state:12` does not return
data any more. Every data query I tried (a custom or the default curl user agent, the whole state or one county) gets
`HTTP 302 -> https://api.census.gov/data/missing_key.html` with the header `x-datawebapi-keyerror: 1`.
A metadata endpoint (`/data/2022/acs/acs5/variables/B25001_001E.json`) still answers without a key.
First seen 2026-11-06 06:49 UTC; the fetch script recorded the same result at 07:01 UTC.

A key needs a sign-up form, and this run's rules forbid accounts and forms, so I did not request one and did
not follow the redirect. Nothing was written to `fl_housing_acs2022.csv`; `geo_build.py` skips it and exits 2;
G1 reports its ACS half as BLOCKED.

**Option A (recommended; needs the user's OK because it is a file the task did not name).** The same ACS 2022
5-year table is published as a keyless bulk file on the same host as the county shapefile:

- File: `acsdt5y2022-b25001.dat`, 17,865,235 bytes, Last-Modified Mon, 30 Oct 2023 16:36:58 GMT
- Source: `https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/data/5YRData/acsdt5y2022-b25001.dat`
- Format, from inspection reads (directory listings, the README and a 700-byte ranged read; nothing saved): pipe-delimited, header
  `GEO_ID|B25001_E001|B25001_M001`, for example the US row `0100000US|140943613|3164`. `B25001_E001` is the
  estimate the API calls `B25001_001E`. County rows should look like `0500000US12071` (the standard Census GEOID
  pattern; not yet seen in this file).
- Plan: save it under `data/raw/census/`, never extract or execute it, keep the 67 rows whose `GEO_ID` matches
  `0500000US12xxx`. `geo_build.py` already enforces 67 rows, unique 5-character fips starting with 12, and
  positive unit counts. The parser was tested on synthetic lines only, so the first real run is its real test.
- Command once approved:
  `uv run python -I scripts/phase0/geo_fetch.py --acs-bulk && uv run python -I scripts/phase0/geo_build.py && uv run python -I scripts/phase0/geo_checks.py`

**Option B.** The user registers a free Census API key themselves and tells the team. The fetch script would
then need a one-line change to append the key from an environment variable.

## 2. Downloads (untrusted data; nothing extracted or executed)

| File (under `data/raw/`) | Bytes | SHA-256 | Last-Modified |
|---|---|---|---|
| `census/cb_2022_us_county_500k.zip` | 11,656,552 | `4a2c23c5486916115137fed7e84a32a4dcfeae453d02840d3e3f1fd8efc3ba58` | Mon, 17 Apr 2023 18:49:17 GMT |
| `hurdat2/hurdat2-1851-2025-02272026.txt` | 7,082,381 | `1b9b0c7beed5b4505838658b1d30e159fc84330c60891a58cfcf43ae55c37202` | Thu, 05 Mar 2026 16:03:11 GMT |

Sources: `https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_county_500k.zip` and
`https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-02272026.txt` (HTTP 200, retrieved 2026-11-06 06:52 UTC).
The HURDAT2 ETag is `"6c118d-64c4912c5182a"`. The shapefile is read in place from the zip through GDAL.
Provenance is in `data/interim/geo_fetch_manifest.json`.

## 3. Outputs (`data/interim/`)

- `fl_counties.gpkg`: layer `fl_counties`, 67 MultiPolygon rows sorted by fips, columns `fips` (TEXT, the 5-character
  GEOID), `name` (TEXT, the shapefile `NAME`, for example "Lee") and geometry, EPSG:4326. The source is NAD83
  (EPSG:4269); the shift to WGS84 is null in PROJ, so coordinates are unchanged. This is the 1:500k cartographic
  file: generalized and clipped to the shoreline.
- `ian_track.csv`: one row per best-track record, 40 rows, columns `time_utc` (ISO 8601 with Z), `record_id`
  (blank for routine 6-hourly records), `status`, `lat`, `lon` (signed decimal degrees, west negative),
  `max_wind_kt`, `min_pressure_mb`, then `r34_ne_nm r34_se_nm r34_sw_nm r34_nw_nm r50_* r64_*` in nautical miles.
  The converter maps `-999` (radii, pressure) and `-99` (wind) to an empty cell. Ian's block contains none of
  those sentinels, so nothing was blanked; a radius of `0` means "no winds of that strength in that quadrant" and
  is kept as 0. The raw file's 21st field (radius of maximum wind) was not requested and is not in the CSV.
  The header line `AL092022, IAN, 40,` declares 40 entries and 40 were parsed.
- `fl_housing_acs2022.csv`: not produced (section 1).
- `geo_fetch_manifest.json`, `geo_checks.json`: download provenance and the machine-readable test results.

Read the CSVs with `dtype={"fips": str}`; read the track with `dtype={"record_id": str}` so the blank identifier does not
become a float NaN column.

## 4. Test results

### G1: 67 counties in both sources, 5-character GEOIDs

Status: **partial**. Shapefile half PASS: 67 Florida counties, `fips` are unique 5-character digit strings, columns are
exactly `fips, name, geometry`, CRS is EPSG:4326, and Lee (12071), Charlotte (12015) and Collier (12021) are present.
The GeoPackage was also read back with plain sqlite3: one `fl_counties` feature layer, 67 rows, 67 distinct fips, all of
length 5, `fips` and `name` stored as TEXT. ACS half **BLOCKED**: no ACS response exists, so the "67 counties in the ACS
response" check and the housing units for Lee, Charlotte and Collier cannot be reported yet.

```text
=== G1: BLOCKED - shapefile half PASS; ACS half BLOCKED
  shapefile: 67 counties, fips dtype object, CRS EPSG:4326, columns ['fips', 'name', 'geometry']
  targets present: 12071=Lee, 12015=Charlotte, 12021=Collier
  ACS half: BLOCKED - no data/interim/fl_housing_acs2022.csv (Census API needs a key)
```

### G2: bounding boxes (W, S, E, N) and tiles

Rule: h = floor((lon + 180) / 10), v = floor((90 - lat) / 10). Tile h09v06 covers lon -90 to -80 and lat 20 to 30.
Tiles were derived two ways, from the bounding box and from the polygon actually overlapping each tile; they agree.

```text
=== G2: PASS - all three need only h09v06
  Lee (12071): W=-82.2721 S=26.3162 E=-81.5622 N=26.7895 -> h=9..9 v=6..6 -> bbox tiles ['h09v06'], polygon tiles ['h09v06']
  Charlotte (12015): W=-82.3752 S=26.7696 E=-81.5625 N=27.0353 -> h=9..9 v=6..6 -> bbox tiles ['h09v06'], polygon tiles ['h09v06']
  Collier (12021): W=-81.8458 S=25.8035 E=-80.8726 N=26.5171 -> h=9..9 v=6..6 -> bbox tiles ['h09v06'], polygon tiles ['h09v06']
```

### G3: Hurricane Ian landfall (`L`) records

```text
=== G3: PASS - 5 L records parsed; Cayo Costa row identified
  'L' records in AL092022 (UTC; distances are to Florida county polygons, which stop at the shoreline):
    2022-09-27T08:30:00Z  22.2N 83.7W  HU 110 kt 947 mb  [280.1 km from Monroe; 494.3 km from Lee]
    2022-09-28T02:00:00Z  24.6N 82.9W  HU 110 kt 952 mb  [4.0 km from Monroe; 217.9 km from Lee]
    2022-09-28T19:05:00Z  26.7N 82.2W  HU 130 kt 941 mb  [1.7 km from Lee; 1.7 km from Lee]  <- Cayo Costa
    2022-09-28T20:35:00Z  26.8N 82.0W  HU 125 kt 945 mb  [inside Charlotte; 3.3 km from Lee]
    2022-09-30T18:05:00Z  33.3N 79.2W  HU 70 kt 978 mb  [356.7 km from Nassau; 759.5 km from Lee]
  Cayo Costa landfall = 2022-09-28T19:05:00Z = 2022-09-28 15:05 EDT local
    64 kt radii (nm): NE 30  SE 40  SW 30  NW 45
    50 kt radii (nm): NE 50  SE 60  SW 70  NW 80
    34 kt radii (nm): NE 130  SE 150  SW 100  NW 150
  CSV vs raw HURDAT2 re-read: 40 rows, 0 mismatches; r64<=r50<=r34 in every quadrant of every record: True
```

HURDAT2 carries no place names, so the Cayo Costa attribution rests on position: the 19:05 UTC record is the `L` record
closest to Lee County (1.7 km off the shoreline-clipped polygon; Cayo Costa is a Lee County barrier island). The 20:35 UTC
record, 90 minutes later, is inside Charlotte County (the Charlotte Harbor landfall). The other three are Cuba (08:30 UTC
27 Sep), an offshore Monroe County point near the Dry Tortugas (02:00 UTC 28 Sep) and the South Carolina coast (18:05 UTC
30 Sep), identified by position only. The Cayo Costa landfall is 15:05 EDT, which fits the plan's "mid-afternoon landfall".
Data-quality checks passed: every CSV row matches an independent re-read of the raw text (0 mismatches in 40 rows), and
the radii nest (64 kt <= 50 kt <= 34 kt) in every quadrant of every record.

### G4: rough wind bands at the Cayo Costa landfall (preview only)

Method: landfall point = the 19:05 UTC record (26.7N, 82.2W). County shapes and the point are projected to EPSG:3086
(NAD83(HARN) / Florida GDL Albers, metres); `geometry.representative_point()` is taken in that projection; distance and
bearing are measured in the plane; 1 nm = 1852 m. The bearing picks the quadrant (NE [0,90), SE [90,180), SW [180,270),
NW [270,360), clockwise from north) and the county is "inside" when its distance is at most that quadrant's radius.

**Simplification: this uses a single track point (the landfall record), not the full wind swath.** It also treats each
quadrant radius, which HURDAT2 defines as a maximum extent, as a pie-slice sector; it represents each county by one point;
and it ignores that HURDAT2 rounds positions to 0.1 degree. On the one-point-per-county rule, Monroe is the only one of the
67 counties whose representative point is not in its largest polygon part: it sits in the Keys (24.68N 81.50W, 235 km from
the landfall), while the mainland body (73% of the county's area) starts 123 km away. Using that nearest mainland point
instead gives the same answer for Monroe at every threshold (outside 64 and 50 kt, inside 34 kt). Counties just outside
the 34 kt sectors (Seminole -5.3 km, Levy -15.6 km, Volusia -37.4 km) are the kind a full swath along the later track
would likely add.

- 64 kt (4): Lee, Charlotte, Sarasota, Manatee
- 50 kt (9): Charlotte, Collier, DeSoto, Hendry, Hillsborough, Lee, Manatee, Pinellas, Sarasota
- 34 kt (29): Brevard, Broward, Charlotte, Citrus, Collier, DeSoto, Glades, Hardee, Hendry, Hernando, Highlands, Hillsborough, Indian River, Lake, Lee, Manatee, Martin, Miami-Dade, Monroe, Okeechobee, Orange, Osceola, Palm Beach, Pasco, Pinellas, Polk, St. Lucie, Sarasota, Sumter

Robustness: a true WGS84 geodesic version of the same test (distance and azimuth) flips no county at any threshold (largest
distance gap 0.21%, largest azimuth gap 1.0 degree from grid convergence). Moving the landfall point by up to +/-0.05
degree in latitude and longitude (8 shifts) changes membership only for Manatee at 64 kt (4 of 8 shifts), Collier (1),
Hardee (2) and Pinellas (1) at 50 kt, and Lake (3) and Seminole (1) at 34 kt. Treat those as borderline.

```text
=== G4: PASS - wind bands computed (preview only)
  landfall point 2022-09-28T19:05:00Z 26.7N 82.2W; planar EPSG:3086, 1 nm = 1852 m; representative_point() taken in EPSG:3086
  64 kt: 4 of 67 counties inside
      Lee          12071  d=  39.5 km  bearing=114.7 SE  radius=  74.1 km  margin= +34.6 km
      Charlotte    12015  d=  43.1 km  bearing= 57.6 NE  radius=  55.6 km  margin= +12.5 km
      Sarasota     12115  d=  51.7 km  bearing=351.1 NW  radius=  83.3 km  margin= +31.6 km
      Manatee      12081  d=  82.3 km  bearing=347.5 NW  radius=  83.3 km  margin=  +1.0 km
      nearest misses: DeSoto (-9.0 km); Hendry (-23.3 km); Collier (-30.3 km)
  50 kt: 9 of 67 counties inside
      Lee          12071  d=  39.5 km  bearing=114.7 SE  radius= 111.1 km  margin= +71.6 km
      Charlotte    12015  d=  43.1 km  bearing= 57.6 NE  radius=  92.6 km  margin= +49.5 km
      Sarasota     12115  d=  51.7 km  bearing=351.1 NW  radius= 148.2 km  margin= +96.5 km
      DeSoto       12027  d=  64.6 km  bearing= 35.8 NE  radius=  92.6 km  margin= +28.0 km
      Manatee      12081  d=  82.3 km  bearing=347.5 NW  radius= 148.2 km  margin= +65.8 km
      Hendry       12051  d=  97.4 km  bearing= 95.1 SE  radius= 111.1 km  margin= +13.7 km
      Collier      12021  d= 104.4 km  bearing=124.3 SE  radius= 111.1 km  margin=  +6.8 km
      Hillsborough 12057  d= 134.3 km  bearing=357.2 NW  radius= 148.2 km  margin= +13.9 km
      Pinellas     12103  d= 142.9 km  bearing=337.3 NW  radius= 148.2 km  margin=  +5.3 km
      nearest misses: Hardee (-3.6 km); Glades (-9.7 km); Highlands (-21.0 km)
  34 kt: 29 of 67 counties inside
      Lee          12071  d=  39.5 km  bearing=114.7 SE  radius= 277.8 km  margin=+238.3 km
      Charlotte    12015  d=  43.1 km  bearing= 57.6 NE  radius= 240.8 km  margin=+197.7 km
      Sarasota     12115  d=  51.7 km  bearing=351.1 NW  radius= 277.8 km  margin=+226.1 km
      DeSoto       12027  d=  64.6 km  bearing= 35.8 NE  radius= 240.8 km  margin=+176.2 km
      Manatee      12081  d=  82.3 km  bearing=347.5 NW  radius= 277.8 km  margin=+195.5 km
      Hardee       12049  d=  96.2 km  bearing= 22.7 NE  radius= 240.8 km  margin=+144.5 km
      Hendry       12051  d=  97.4 km  bearing= 95.1 SE  radius= 277.8 km  margin=+180.4 km
      Glades       12043  d= 102.3 km  bearing= 70.2 NE  radius= 240.8 km  margin=+138.4 km
      Collier      12021  d= 104.4 km  bearing=124.3 SE  radius= 277.8 km  margin=+173.4 km
      Highlands    12055  d= 113.6 km  bearing= 50.3 NE  radius= 240.8 km  margin=+127.1 km
      Hillsborough 12057  d= 134.3 km  bearing=357.2 NW  radius= 277.8 km  margin=+143.5 km
      Pinellas     12103  d= 142.9 km  bearing=337.3 NW  radius= 277.8 km  margin=+134.9 km
      Okeechobee   12093  d= 149.2 km  bearing= 62.3 NE  radius= 240.8 km  margin= +91.6 km
      Polk         12105  d= 152.1 km  bearing= 17.3 NE  radius= 240.8 km  margin= +88.6 km
      Palm Beach   12099  d= 172.8 km  bearing= 90.5 SE  radius= 277.8 km  margin=+105.0 km
      Osceola      12097  d= 178.8 km  bearing= 35.2 NE  radius= 240.8 km  margin= +61.9 km
      Broward      12011  d= 180.7 km  bearing=108.4 SE  radius= 277.8 km  margin= +97.1 km
      Pasco        12101  d= 182.0 km  bearing=353.3 NW  radius= 277.8 km  margin= +95.8 km
      Martin       12085  d= 183.3 km  bearing= 74.4 NE  radius= 240.8 km  margin= +57.5 km
      St. Lucie    12111  d= 187.4 km  bearing= 65.5 NE  radius= 240.8 km  margin= +53.3 km
      Indian River 12061  d= 191.8 km  bearing= 53.2 NE  radius= 240.8 km  margin= +48.9 km
      Miami-Dade   12086  d= 204.5 km  bearing=127.1 SE  radius= 277.8 km  margin= +73.3 km
      Hernando     12053  d= 207.7 km  bearing=353.9 NW  radius= 277.8 km  margin= +70.1 km
      Sumter       12119  d= 214.9 km  bearing=  1.6 NE  radius= 240.8 km  margin= +25.8 km
      Orange       12095  d= 225.0 km  bearing= 22.3 NE  radius= 240.8 km  margin= +15.7 km
      Brevard      12009  d= 229.8 km  bearing= 37.8 NE  radius= 240.8 km  margin= +10.9 km
      Monroe       12087  d= 235.0 km  bearing=161.7 SE  radius= 277.8 km  margin= +42.8 km
      Lake         12069  d= 239.6 km  bearing= 11.2 NE  radius= 240.8 km  margin=  +1.1 km
      Citrus       12017  d= 241.5 km  bearing=352.7 NW  radius= 277.8 km  margin= +36.3 km
      nearest misses: Seminole (-5.3 km); Levy (-15.6 km); Volusia (-37.4 km)
  geodesic cross-check: classification flips {'64': [], '50': [], '34': []}; max distance gap 0.21%; max azimuth gap 1.0 deg (grid convergence)
  membership flips if the landfall point moves up to +/-0.05 deg (of 8 shifts): {"64": {"Manatee": 4}, "50": {"Collier": 1, "Hardee": 2, "Pinellas": 1}, "34": {"Lake": 3, "Seminole": 1}}
```

### G5: counties that cross 30°N

13 counties have polygon area in both tile rows v05 (lat above 30) and v06 (lat 30 and below), so each needs two tiles:
Bay, Bradford, Clay, Columbia, Franklin, Gulf, Lafayette, Liberty, St. Johns, Suwannee, Taylor, Union, Wakulla.

Franklin is the thinnest crossing: its northern edge is 30.0139, about 1.5 km above the line, in a generalized file, so
treat it as the one to re-check against finer boundaries if it matters. Liberty and Wakulla are the next thinnest: their
southern edges are only about 3 km below the line. The bounding-box test (S < 30 < N) and the polygon-overlap test agree,
and a separate latitude-line intersection gives the same 13. No other county comes closer than 0.05 degree (about 6 km)
to the line without crossing it: Alachua N=29.9453, Gilchrist N=29.9355, Jefferson S=30.0817, Duval S=30.1037.

No Florida county reaches 80°W (the h09/h10 edge): the easternmost point is E=-80.0314, about 3 km inside h09. So the
whole state needs only h09v05 and h09v06, but a buffer wider than about 3 km on the Palm Beach side would ask for h10.

```text
=== G5: PASS - 13 counties cross 30N
  13 counties need both v05 and v06 (polygon overlaps both tile rows):
      Franklin   12037  S=29.5870 N=30.0139  tiles=['h09v05', 'h09v06']
      St. Johns  12109  S=29.6224 N=30.2529  tiles=['h09v05', 'h09v06']
      Taylor     12123  S=29.6657 N=30.3042  tiles=['h09v05', 'h09v06']
      Gulf       12045  S=29.6667 N=30.2014  tiles=['h09v05', 'h09v06']
      Bradford   12007  S=29.7182 N=30.1431  tiles=['h09v05', 'h09v06']
      Clay       12019  S=29.7187 N=30.1935  tiles=['h09v05', 'h09v06']
      Lafayette  12067  S=29.8222 N=30.2607  tiles=['h09v05', 'h09v06']
      Columbia   12023  S=29.8256 N=30.5977  tiles=['h09v05', 'h09v06']
      Suwannee   12121  S=29.8823 N=30.4429  tiles=['h09v05', 'h09v06']
      Union      12125  S=29.9199 N=30.1431  tiles=['h09v05', 'h09v06']
      Bay        12005  S=29.9244 N=30.5677  tiles=['h09v05', 'h09v06']
      Wakulla    12129  S=29.9691 N=30.3035  tiles=['h09v05', 'h09v06']
      Liberty    12077  S=29.9714 N=30.6064  tiles=['h09v05', 'h09v06']
  bbox test (S<30<N) disagrees with the polygon test for: []
  nearest counties that do NOT cross: Alachua N=29.9453; Gilchrist N=29.9355; Jefferson S=30.0817; Duval S=30.1037
  Florida extent W=-87.6349 S=24.5213 E=-80.0314 N=31.0009; tiles used by any county: ['h09v05', 'h09v06']
```

## 5. Notes for later tasks

1. Landfall points are not inside county polygons: the cartographic file stops at the shoreline, and the Cayo Costa
   point lies in the water, 1.7 km from Lee's polygon. Use distance or nearest-county logic, not point-in-polygon.
2. The first two `L` records in Ian's block are Cuba and the Dry Tortugas area (by position), then the two Florida
   mainland landfalls. Select by position or nearest county, never "first L record".
3. HURDAT2 times are UTC. Cayo Costa 19:05 UTC = 15:05 EDT (relevant to Phase 0 check 3, the EAGLE-I timezone).
4. Panhandle and Big Bend counties (Bay, Gulf, Franklin, Wakulla, Taylor and others) are on the G5 list, so the plan's
   Michael and Idalia counties will need v05 and v06 mosaics in Phase 1.

## 6. Deviations from the brief

- Task 2 not completed as specified (section 1).
- Extra files written to `data/interim/`: `geo_fetch_manifest.json`, `geo_checks.json`.
- Extra G4 columns beyond the ask: the 50 kt band, the geodesic cross-check and the position-shift sensitivity.
- `geo_verify_independent.py` (a second, differently-coded check of G1-G5) is an addition, not an ask.

## 7. Reproduce and verify

```text
uv run python -I scripts/phase0/geo_fetch.py               # downloads; exit 2 until an ACS file exists
uv run python -I scripts/phase0/geo_build.py               # parser self-test, then the three interim files
uv run python -I scripts/phase0/geo_checks.py              # G1-G5 evidence; exit 2 while G1's ACS half is blocked
uv run python -I scripts/phase0/geo_verify_independent.py  # different code paths; exit 0 when all agree
uv run ruff check scripts/phase0/geo_*.py
```

Scripts: `scripts/phase0/geo_fetch.py`, `geo_build.py`, `geo_checks.py`, `geo_verify_independent.py`.

---
**Update 2026-11-06 (orchestrator):** the ACS block is resolved.
- The keyless summary file `acsdt5y2022-b25001.dat` (17,865,235 bytes, sha256 `5bc8c5cf…7512`) was fetched from www2.census.gov, under the user's approval for dataset downloads.
- `data/interim/fl_housing_acs2022.csv` now covers all 67 counties, and G1 = PASS.
- Housing units: Lee 419,916; Charlotte 111,330; Collier 229,814.
