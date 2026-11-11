# Phase 0 docs check: Black Marble C2 and EAGLE-I facts

Agent `docs`, 2026-11-05. Everything below comes from the three primary sources listed here. Anything I worked out myself is marked **(inference)**. "Not stated" means the source does not cover it.

## Sources

| Key | Document | Local copy (gitignored) | sha256 (first 12) |
|---|---|---|---|
| BMG | *Black Marble User Guide (Collection 2.0)*, NASA, Oct 2024, PI Zhuosen Wang. 64 PDF pages | `data/raw/docs/BlackMarbleUserGuide_Collection2.0.pdf` | `3bd88ecfb705` |
| SD | Brelsford et al., *A dataset of recorded electricity outages by United States county 2014–2022*, Scientific Data 11:271 (2024), doi:10.1038/s41597-024-03095-5. 13 pages | `data/raw/docs/eaglei_scidata_2024.pdf` | `d65d711717bf` |
| FS | figshare article 24237376, version 4, published 2026-02-25, CC BY 4.0 (API JSON) | `data/raw/docs/figshare_24237376.json` | `83d46fb6c3e7` |

**Page numbers.** BMG pages are the printed numbers, and PDF page = printed page + 6, so Table 8 on printed p. 16 is PDF p. 22. SD pages are the journal's pages 1–13.

## What changes the code or the plan (read first)

1. **Mandatory_Quality_Flag code 2 does not mean "outlier or cloud" in Collection 2.** In C2, code 1 is poor quality for an outlier, possible cloud contamination or other issues. Code 2 is poor quality because the solar zenith angle is 102–108°, which is twilight (BMG Table 9 pp. 16–17; the file's `Description` attribute, App. B p. 45). Plan Task 1, check 2 tests "MQF = 2", so it should test code 1 instead.
   - Code 2 should almost never appear over Lee County at the post-midnight pass, because the Sun is far more than 108° from the zenith then **(inference)**.
   - I remember Collection 1 using code 2 for outliers, which would explain the plan's wording. I did not verify this.
   - A real, sudden blackout could itself be flagged as an outlier (code 1). The guide does not say how daily outliers are detected **(inference)**.
2. **The lunar layer is named `DNB_Lunar_Irradiance`, not `Lunar_Irradiance`** (BMG List 2 p. 15; Table 8 p. 16).
3. **VNP46A2 attributes are not CF-clean.** The offset attribute is spelled `offset`, not `add_offset`. `valid_range` is a text string such as `">=0.0 \n"`, and the `units` strings end in `" \n"` (BMG App. B pp. 44–45). Read the raw arrays with h5py and mask by hand; don't rely on automatic CF decoding **(inference)**.
4. **Gap-filling pastes in older values** (BMG p. 24). On a cloudy night after the storm, the gap-filled layer would show the lights from before the storm. This confirms the plan's ban on that layer.
5. **EAGLE-I timestamps are UTC** (SD pp. 6–7). In September, Lee County is on EDT (UTC−4), so the 01:30 local pass on date D lines up with the 05:30 UTC run on D **(inference)**. Check 3 in the plan should therefore see the surge about 4 h "late" when the stamps are read as local time. That confirms the paper; it doesn't discover anything new.
6. **EAGLE-I leaves out zero rows, and a missing row can mean either zero or a collection gap.** The data don't say which (SD pp. 6–7).
   - Timeouts are typical when outage maps get heavy traffic during extreme weather. Missed outages usually turn up in the next 15-minute run (SD p. 5).
   - So a single 05:30 run can look like zero for every county of one utility. Use a short window of runs around the pass instead **(inference)**.
   - The plan's rule that "no rows for the whole state means missing" won't catch a gap at a single utility **(inference)**.
7. **`coverage_history.csv` and `DQI.csv` cover only 2018–2022, and `MCC.csv` gives customers as of 2022** (SD pp. 6–7; FS description).
   - Idalia (2023), Beryl, Helene and Milton (2024) have no state-coverage rows, so the 0.8 state-coverage cutoff needs a fallback written into the decision log, for example carrying 2022 forward **(inference)**.
   - Coverage percentages are stored as fractions such as 0.67 (SD Table 5, p. 7).
8. **The guide doesn't say whether pixel coordinates are centres or edges.** Tile bounds are whole degrees (BMG App. B pp. 43–44). Check this on the first file (see "Verify on real files").
9. **The C2 guide gives no overpass time.** Per-pixel view time exists only in VNP46A1, as `UTC_Time` (long name "View Time (UTC)", in decimal hours) (BMG Table 5 p. 12; App. A p. 43).

## D1. VNP46A2 layers

**HDF5 path:** `/HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields/<layer>`. The group name `Data Fields` contains a space (BMG List 2 p. 15; App. B p. 44).
- Each 2-D layer is 2400 × 2400, with dimensions `phony_dim_0` and `phony_dim_1`.
- The file also contains an empty group `/HDFEOS/ADDITIONAL/FILE_ATTRIBUTES` and the dataset `/HDFEOS INFORMATION/StructMetadata.0` (App. B pp. 44–45).
- The guide counts 7 science layers plus `lat` and `lon` (p. 15).

The table below is from BMG Table 8 (p. 16), with attribute spellings from App. B (pp. 44–45).

| Layer | Type | Units | Fill | Valid | Scale | Offset |
|---|---|---|---|---|---|---|
| `DNB_BRDF-Corrected_NTL` | float32 | nW·cm⁻²·sr⁻¹ | −999.9 | ≥ 0 | 1.0 | 0.0 |
| `Gap_Filled_DNB_BRDF-Corrected_NTL` | float32 | nW·cm⁻²·sr⁻¹ | −999.9 | ≥ 0 | 1.0 | 0.0 |
| `DNB_Lunar_Irradiance` | uint16 | nW·cm⁻² | 65535 | 0–65534 | 0.1 | 0.0 |
| `Mandatory_Quality_Flag` | uint8 | flag | 255 | 0–5 | n/a | n/a |
| `Latest_High_Quality_Retrieval` | uint8 | number of days | 255 | 0–254 | 1.0 | 0.0 |
| `Snow_Flag` | uint8 | flag | 255 | 0–1 | n/a | n/a |
| `QF_Cloud_Mask` | uint16 | bit flags | 65535 | 0–65534 | n/a | n/a |
| `lat` | float64, 1-D, 2400 values | degrees_north | −999.9 | −90 to 90 | n/a | n/a |
| `lon` | float64, 1-D, 2400 values | degrees_east | −999.9 | −180 to 180 | n/a | n/a |

Notes:
- Only `DNB_Lunar_Irradiance` changes when the scale is applied (multiply by 0.1) **(inference)**.
- In VNP46A1 the offset attribute is spelled `add_offset` instead (App. A pp. 40–43).
- The fill value is stored as float32 (`-999.9f`), so mask with `< 0` or a tolerance, not with exact equality **(inference)**.
- Not stated: whether cloudy pixels in `DNB_BRDF-Corrected_NTL` hold a value or the fill value. Build the clear mask from `QF_Cloud_Mask` and the quality flag, not from fill values **(inference)**.
- Useful global attributes (App. B pp. 43–44): `RangeBeginningDate/Time`, `RangeEndingDate/Time`, `StartTime`, `EndTime`, the four `*BoundingCoord` values, `GRingPointLatitude/Longitude`, `HorizontalTileNumber`, `VerticalTileNumber`, `PlatformShortName = "SUOMI-NPP"` and `InputPointer`.

## D2. Mandatory_Quality_Flag codes

Source: BMG Table 9 (pp. 16–17), and the identical `Description` attribute (App. B p. 45).

| Code | Meaning |
|---|---|
| 0 | High quality, main algorithm |
| 1 | Poor quality, main algorithm: outlier, possible cloud contamination, or other issues |
| 2 | Poor quality, main algorithm: high solar zenith angle, 102–108° |
| 3 | Poor quality, main algorithm: lunar eclipse |
| 4 | Poor quality, main algorithm: aurora |
| 5 | Poor quality, main algorithm: glint |
| 255 | No retrieval (fill value) |

- Pixels where the solar zenith angle is below 102° get the fill value, because 102° is the code's nighttime cutoff (Table 5 footnote, p. 13).
- There is no code for "gap-filled", even though p. 24 says the QA flags report when gap-filling runs.
- Figures 4 and 5 (pp. 24–25) use an older legend with "Temporal Gap-Filling" and "Outlier Removal" classes. Trust Table 9 and the in-file attribute over the figures **(inference)**.

## D3. QF_Cloud_Mask bit layout

Source: BMG Table 6 (pp. 13–14), and the same text in the VNP46A2 `Description` attribute (App. B p. 45). The layer is uint16 with fill 65535. The guide doesn't say that bit 0 is the least significant bit, but that is the standard reading, and the decode column assumes it **(inference)**.

| Bits | Field | Values | Decode (inference) |
|---|---|---|---|
| 0 | Day/night | 0 = night, 1 = day | `qf & 1` |
| 1–3 | Land/water background | 000 land and desert, 001 land without desert, 010 inland water, 011 sea water, 101 coastal | `(qf >> 1) & 7` |
| 4–5 | Cloud mask quality | 00 poor, 01 low, 10 medium, 11 high | `(qf >> 4) & 3` |
| 6–7 | Cloud detection and confidence | 00 confident clear, 01 probably clear, 10 probably cloudy, 11 confident cloudy | `(qf >> 6) & 3` |
| 8 | Shadow detected | 1 = yes | `(qf >> 8) & 1` |
| 9 | Cirrus detection (IR, from the M15 − M16 brightness temperature) | 1 = cloud | `(qf >> 9) & 1` |
| 10 | Snow/ice surface | 1 = snow or ice | `(qf >> 10) & 1` |
| 11 | VI used | 1 = yes | `(qf >> 11) & 1` |
| 12 | Aurora detected | 1 = yes | `(qf >> 12) & 1` |
| 13 | Lunar eclipse detected | 1 = yes | `(qf >> 13) & 1` |
| 14–15 | Not described | — | — |

`Snow_Flag` is a separate layer: 0 = no snow or ice, 1 = snow or ice, 255 = fill (Table 10, p. 17).

## D4. Gap-filling and Latest_High_Quality_Retrieval

- Temporal gap-filling is one of the algorithm's three key enhancements, meant to cut persistent data gaps (BMG §2.1 p. 2). The night processing uses both temporal and spatial gap-filling (p. 10).
- **How it works (p. 24, paraphrased).** When gap-filling runs, the date of the latest high-quality main-algorithm retrieval goes into a separate layer. If the value still fails the outlier test after temporal filling, the algorithm falls back to a monthly climatology built from the most recent moonless high-quality values. The flags let users judge whether a filled value is recent.
- **`Latest_High_Quality_Retrieval`.** It is uint8, with units "Number of Days", valid range 0–254 and fill 255 (Table 8 p. 16; App. B pp. 44–45). Figures 4F and 5F plot it on a scale from 0 to 16 days or more (pp. 24–25).
- What a value of 0 means is not stated. Reading the layer as the age, in days, of the value used is **(inference)**.
- **Does it paste in older values? Yes**: either the most recent earlier high-quality value or a monthly climatology (p. 24).
- The example VNP46A2 file for A2024100 lists a `VNP46A2_DB` file for the previous day, A2024099, among its inputs (App. B p. 43). That looks like a rolling store of past values **(inference)**.
- The monthly and yearly composites also replace aurora-contaminated pixels with gap-filled values (p. 6). Their quality code 2 means gap-filled from historical data (Table 12, p. 23).

## D5. Date convention and overpass time

- **File names (§3.2, pp. 6–7).** Example: `VNP46A1.A2018001.h08v05.002.2023184124809.h5`. The parts are:
  - the product name;
  - `A` + year + day of year, the acquisition date (the guide calls it a Julian date);
  - the tile;
  - `.002`, the collection;
  - the production time as `YYYYDDDHHMMSS`;
  - `.h5`, for HDF5.
- **UTC day or local day?** The guide doesn't say in words. The evidence points to a UTC calendar day **(inference, strongly supported)**:
  - The VNP46A2 example A2024100 has a metadata range from 2024-04-09 00:00:00.000 to 2024-04-09 23:59:59.000 (App. B pp. 43–44).
  - The VNP46A1 example's `PGE_EndTime` ends in "Z", meaning UTC (App. A p. 39).
  - VNP46A1 stores per-pixel time in UTC (Table 5 p. 12).
- **Overpass time: not stated.** The field test in Fig. 7 ran at 02:00 local time (p. 27), but that is the experiment's time, not a stated overpass time.
- For each grid cell, the gridding picks high-quality observations from 6-minute granules that are least cloudy and least off-nadir (§3.3 p. 7). So the orbit used, and therefore the pass time, can vary between pixels and between nights **(inference)**. VNP46A1's `UTC_Time` and `Granule` layers show it (Table 5 pp. 12–13).
- **The plan's convention holds.** A pass near 01:30 EDT is about 05:30 UTC, which falls inside UTC day D. So "the file for D shows the night from D−1 into D" is right for Florida **(inference)**.
- **Ian day-of-year codes** (computed with `date`):
  - A2022271 = Sep 28, the landfall day.
  - A2022272 = Sep 29, the first dark file the plan expects.
  - The download window is A2022237 to A2022292.

## D6. Tile grid

- The grid is a 15 arc-second geographic (linear lat/lon) grid, delivered as HDF-EOS (BMG §3 p. 6).
- There are 460 non-overlapping land tiles, each about 10° × 10° (Fig. 2 caption, p. 8). `h` runs from 00 to 35 west to east, and `v` from 00 to 17 north to south (Fig. 2, p. 7).
- Tile names are `hXXvYY` (p. 7).
- Each tile is 2400 × 2400 pixels (App. B p. 44). Since 10° / 2400 = 1/240° = 15″, this matches the stated resolution **(inference)**.
- **Example bounds:**
  - h10v04: north 50, south 40, west −80, east −70 (App. B pp. 43–44).
  - h10v05: north 40, south 30 (App. D).
  - These agree with the plan's `h = floor((lon+180)/10)` and `v = floor((90−lat)/10)`, which give h09v06 for Lee County **(inference)**.
- **Pixel edges or centres: not stated.** The bounding coordinates are whole-degree tile edges, and the guide doesn't show the contents of `StructMetadata.0`.
- The DNB's native ground footprint is about 742 m and nearly constant (§3.3 p. 7). That is coarser than the roughly 460 m grid cell, so neighbouring pixels are not independent **(inference)**.
- Geolocation uncertainty targets are 133 m (threshold) and 50 m (breakthrough) (Table 14, pp. 26–27).

## D7. Caveats for outage detection (BMG)

- **Moonlight.**
  - VNP46A2 removes moonlight by modelling the lunar irradiance and how the surface reflects moonlight (its lunar BRDF) (§2.2–2.3, pp. 3–5). Moonlight is present for about half of each lunar cycle (Fig. 1 caption, p. 4).
  - On nights without moonlight, the algorithm assumes a near-nadir lunar geometry (θm = 10°) and a small fixed irradiance from airglow (p. 5). A lunar zenith angle above 108° means no moon (Fig. 7 caption, p. 28).
  - The guide doesn't give the leftover moonlight error for the daily product. Use `DNB_Lunar_Irradiance` to tag bright-moon nights **(inference)**.
- **Snow.**
  - A snow albedo is used when the day's snow flag is set (p. 3). Snow raises the amount of reflected light (p. 6), and it makes cloud masking hard (Fig. 4 caption, p. 24).
  - This doesn't matter for Ian. For the Uri stress test, a snow-free baseline compared with snowy storm nights could hide outages **(inference)**.
- **Ephemeral lights.** C2 has no flag separating persistent from ephemeral lights. The guide uses "ephemeral" only for artifacts such as aurora (pp. 24–25). Aurora is MQF 4 or cloud-mask bit 12, a lunar eclipse is MQF 3 or bit 13, and glint is MQF 5.
- **Viewing angle.**
  - City lights show a strong angle effect: radiance at nadir can be much higher than off-nadir (p. 6).
  - The composites split observations into near-nadir (view zenith 0–20°) and off-nadir (40–60°) (Table 11, pp. 19–22).
  - VNP46A2 has no view-angle layer, but VNP46A1 has `Sensor_Zenith` (Table 5, p. 11). Changes in view angle from night to night can mimic dimming or hide it **(inference)**.
- **Vegetation.** Neither C1 nor C2 applies a vegetation (canopy) correction (p. 10). Trees stripped by the storm could raise the observed radiance and offset a real outage **(inference)**.
- **Twilight.** A solar zenith angle below 102° gives the fill value, and 102–108° gives MQF 2 (pp. 13, 17).
- **Sensor flags.** Stray light, saturation and calibration flags exist only in VNP46A1's `QF_DNB` (Table 7, p. 14).
- **Noise floor.** The NTL detection-limit targets are 3.0 (threshold), 0.5 (breakthrough) and 0.25 (goal) nW·cm⁻²·sr⁻¹ (Table 14, p. 26). A moonless field test reports VNP46A2 within the breakthrough detection limit, quoting an Lmin of 0.43 (p. 28). Dim rural pixels sit close to this noise floor **(inference)**.
- **Latency.** Standard processing finishes within 3–5 hours of acquisition (p. 2). The near-real-time feed through LANCE takes about 3 hours (pp. 23, 29).

## D8. EAGLE-I

Source: SD unless noted.

### Timezone

- All EAGLE-I data are in UTC (p. 6).
- `run_start_time` is a UTC stamp marking the start of a collection run, in the stated format `MM/DD/YY 00:00` (p. 7).
- Runs start at :00, :15, :30 and :45 past each hour and take under 5 minutes (p. 4).
- The example table shows `1/1/22 0:00` (Table 4, p. 6), so parse the real file's format defensively **(inference)**.

### Counties with no outage

- **They are left out.** Zero values are not included, and a missing entry is either a zero or a collection gap, without saying which (p. 6). Rows with 0 customers out are excluded (p. 7).
- Counties whose utilities are all unmonitored are dropped entirely. That was 1,072 counties in 2014 and 182 in 2022 (p. 3).
- The paper gives two different county totals, 3,226 (p. 1) and 3,222 (p. 3).
- **Columns:** `fips_code`, `county`, `state` (full name), `customers_out` (an integer) and `run_start_time`. The example table shows FIPS codes zero-padded, as in "01005" (Table 4 and pp. 6–7).

### MCC

- `MCC.csv` has 3,235 rows and gives the modelled number of electric customers per county as of 2022. Its columns are `County_FIPS` and `Customers` (pp. 6–7).
- A FIPS code missing from the list means EAGLE-I lacks the utilities serving that county (p. 7).
- **Method.** Each utility's customer total from EIA-861 is spread over the counties it serves in proportion to population. Population is the average of LandScan daytime and night-time population: c_i = p_i·C/P (p. 3). The full method is in Moehl et al. (submitted 2023).
- A "customer" is usually a meter, which may be a household, a business or a facility, so customers are not people (p. 3).
- The paper's Table 6 shows padded FIPS codes, but the plan says the real file is unpadded and starts with a byte-order mark. Check the file.

### Coverage

- `coverage_history.csv` has 280 rows: one per state per year, for 2018–2022 (Table 5 and p. 7).
- Its columns are `year`, `state`, `total_customers` (from the nearest EIA-861), `min_covered`, `max_covered`, `min_pct_covered` and `max_pct_covered`. The percentages are fractions.
- Coverage shifts during a year as utilities are added or dropped (p. 7).
- Nationally, coverage was 86% in 2018 (137 M customers, 339 utilities) and 92% in 2022 (146 M customers, 456 utilities) (p. 2). The paper elsewhere says 80–90% (p. 3).

### DQI

- `DQI.csv` has 50 rows: one per FEMA region per year, for 2018–2022 (pp. 6–8).
- **Formula:** DQI = 0.4·S + 0.3·E + 0.2·C + 0.1·P, with each component rescaled to 0–100 (Eq. 2, p. 10).
- **Components (p. 10):**
  - S, success rate: the customer-weighted share of collection periods in which parsers finished without error.
  - E, percent enabled: the customer-weighted share of periods in which the parser was on.
  - C, customer coverage: covered customers divided by the EIA total for the region.
  - P, spatial precision: 100 for county-level data, 75 for points, 50 for ZIP codes and 25 for non-standard polygons.
- The DQI is published only at region level, so that quality numbers for individual utilities aren't released (p. 8).
- There is no DQI before 2018 (p. 11).
- Florida is in FEMA Region IV (Fig. 2, p. 8).

### Stated limitations

- About 8% of customers were not covered in 2022, mostly at small, rural or municipal utilities (p. 2).
- Outages shorter than 15 minutes are not captured reliably. A 10-minute outage has about a 2/3 chance of being seen, and a 5-minute outage about 1/3 (pp. 3–4).
- Small, rural and independent utilities are captured less reliably (p. 3).
- Changes in which utilities are covered, and in data quality, affect comparisons over long periods or large areas (p. 3).
- The data depend on what utilities publish, and the formats vary, so some time inconsistencies can't be avoided (pp. 3–4).
- Point outages are put in the county that contains the point. ZIP and polygon outages are split between counties by area overlap, not by population (pp. 4–5).
- Some collection errors (parser, connection, timeout, runtime, cache, scheduler) mean no outages are collected for that utility in that run. Location, sub-utility and webdriver errors mean partial data. Timeouts are typical during extreme weather (p. 5).
- Utilities sometimes publish stale or wrong outage numbers (p. 5).
- Corrections made in near real time are included without being marked (p. 6).
- Privileged users, such as FEMA Regional Coordinators, can overwrite the parsed data by hand. This is typical in hurricanes and wildfires (p. 6).
- A utility that changes its name, website or reporting creates a coverage gap (Table 5 caption, p. 7). Fixes found in the annual census apply going forward, not backward (p. 9).

### Figshare record (FS)

- Version 4, CC BY 4.0, with outage files for 2014–2025. The 2022 file is 1,187,596,176 bytes.
- The description repeats the three extra files: coverage for 2018–2022, MCC as of 2022, and DQI for 2018–2022.
- **Timezone, zero handling and limitations: not stated.**
- The description has two small slips: it says "eight years" for 2014–2025, and it dates the update that added 2023 data to 2/16/2023.

## Not stated, by source

- **BMG:**
  - the overpass time;
  - the word "UTC" for the date in the file name;
  - whether `lat` and `lon` give pixel centres or edges;
  - how daily outliers (MQF 1) are detected;
  - what `Latest_High_Quality_Retrieval` = 0 means;
  - whether cloudy pixels in the main NTL layer get the fill value;
  - the leftover moonlight error in the daily product;
  - bits 14–15 of `QF_Cloud_Mask` and the bit-order convention.
- **SD:**
  - how daylight saving is handled, beyond "UTC";
  - how to tell a zero from a gap;
  - coverage and DQI after 2022.
- **FS:** timezone, zero handling and limitations.

## Verify on the real files (Task 1, "Inspect the files")

1. For h09v06, read `lat[0]`, `lat[-1]` and `lon[0]`. If they are about 29.9979167, 20.0020833 and −89.9979167, the arrays give pixel centres; 30, 20 and −90 would mean edges **(inference)**.
2. On `DNB_BRDF-Corrected_NTL`, expect an attribute named `offset` and a string `valid_range`.
3. Count the MQF values over Lee County for Sep 29 to Oct 1. Expect codes 0, 1 and 255, with almost no 2.
4. In one VNP46A1 tile, read `UTC_Time` over Lee County. Expect roughly 05–07 UTC **(inference)**.
5. Check the header and timestamp format of the EAGLE-I 2022 file, and the padding and byte-order mark of `MCC.csv`.

---
**Update 2026-11-06 (orchestrator):** these items are now settled.
- **Quality flags:** the plan and code use `Mandatory_Quality_Flag` 0 as "clear", and check 2 now looks at code 1.
- **Pass time:** about 01:30 local *mean solar* time, or about 07:00 UTC over Lee. Each night's exact time comes from VNP46A1 `UTC_Time`.
- **EAGLE-I zero rows:** the 2022 file does contain explicit 0 rows (4.96% of rows), despite the paper's wording.
- **Timestamp format:** the real files use `YYYY-MM-DD HH:MM:SS`.
