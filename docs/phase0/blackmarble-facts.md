# Black Marble VNP46A2 (Collection 2): reconciled fact sheet

Phase 0, 2026-11-05. Source: *Black Marble User Guide (Collection 2.0)*, NASA, October 2024, `data/raw/docs/BlackMarbleUserGuide_Collection2.0.pdf` (a local copy, gitignored and not in the repository; 64 PDF pages, sha256 starts `3bd88ecfb705`). This reconciles Reader A, Reader B and `agent-docs.md` after re-reading every cited page. The machine-readable version is `blackmarble-facts.json`.

- **Pages** are the numbers printed on the page, as in the guide's contents page. PDF page = printed page + 6.
- **(inference)** means worked out here, not stated in the guide. **Not stated** means the guide is silent.

## What the code reads

| Fact | Value | Source |
|---|---|---|
| HDF5 group | `/HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields` (with a space in `Data Fields`) | List 2 p.15; App. B pp.44–45 (spot-checked) |
| Layer to use | `DNB_BRDF-Corrected_NTL`; never the gap-filled layer on event nights | Table 8 p.16; p.24 |
| NTL fill, scale, offset | −999.9 (stored as float32 `-999.9f`), 1.0, 0.0; the offset attribute is named `offset` | Table 8 p.16; App. B p.44 (spot-checked) |
| Good pixel | `Mandatory_Quality_Flag` = 0 | Table 9 p.16 |
| Cloud confidence | `QF_Cloud_Mask` bits 6–7 | Table 6 p.14; App. B p.45 (spot-checked) |
| Tile | 10° × 10°, 2400 × 2400 px, 1/240° per px; Lee County is `h09v06` (derived) | p.7; App. B p.44 |

### Layers (Table 8 p.16; attributes in App. B pp.44–45)

| Layer | dtype | Units | Fill | Valid | Scale | Offset |
|---|---|---|---|---|---|---|
| `DNB_BRDF-Corrected_NTL` | float32 | nWatts·cm⁻²·sr⁻¹ | −999.9 | ≥ 0 | 1.0 | 0.0 |
| `Gap_Filled_DNB_BRDF-Corrected_NTL` | float32 | nWatts·cm⁻²·sr⁻¹ | −999.9 | ≥ 0 | 1.0 | 0.0 |
| `DNB_Lunar_Irradiance` | uint16 | nWatts·cm⁻² | 65535 | 0–65534 | 0.1 | 0.0 |
| `Mandatory_Quality_Flag` | uint8 | flag | 255 | 0–5 | n/a | n/a |
| `Latest_High_Quality_Retrieval` | uint8 | number of days | 255 | 0–254 | 1.0 | 0.0 |
| `Snow_Flag` | uint8 | flag | 255 | 0–1 | n/a | n/a |
| `QF_Cloud_Mask` | uint16 | flag | 65535 | 0–65534 | n/a | n/a |
| `lat` | float64, 1-D | degrees north | −999.9 | −90 to 90 | n/a | n/a |
| `lon` | float64, 1-D | degrees east | −999.9 | −180 to 180 | n/a | n/a |

### Mandatory_Quality_Flag (Table 9 pp.16–17; App. B p.45)

| Code | Meaning |
|---|---|
| 0 | High quality, main algorithm |
| 1 | Poor: outlier, potential cloud contamination or other issues |
| 2 | Poor: high solar zenith angle, 102–108° |
| 3 | Poor: lunar eclipse |
| 4 | Poor: aurora |
| 5 | Poor: glint |
| 255 | No retrieval (fill) |

Collection 2 has no code for "gap-filled". The Figure 4E/5E legends (pp.24–25) show older classes; trust Table 9.

### QF_Cloud_Mask bits (Table 6 pp.13–14; App. B p.45)

| Bits | Field | Values |
|---|---|---|
| 0 | Day/Night | 0 night, 1 day |
| 1–3 | Land/Water Background | 000 land & desert, 001 land no desert, 010 inland water, 011 sea water, 101 coastal |
| 4–5 | Cloud Mask Quality | 00 poor, 01 low, 10 medium, 11 high |
| 6–7 | Cloud Confidence | 00 confident clear, 01 probably clear, 10 probably cloudy, 11 confident cloudy |
| 8 | Shadow Detected | 1 yes |
| 9 | Cirrus Detection (IR) (BTM15 – BTM16) | 1 cloud |
| 10 | Snow/ Ice Surface | 1 snow/ice |
| 11 | VI used | 1 yes ("VI" is not defined) |
| 12 | Aurora Detected | 1 yes |
| 13 | Lunar Eclipse Detected | 1 yes |

- App. B names bits 6–7 `Cloud Detection Results & Confidence Indicator`, with the same values.
- **Not stated:** that bit 0 is the least significant bit; bits 14–15; land/water codes 100, 110 and 111.
- Standard decode **(inference):** mask 65535 first, then cloud confidence = `(qf >> 6) & 3`, giving 0–3 in the order above.

`Snow_Flag` (Table 10 p.17): 0 = no snow or ice, 1 = snow or ice, 255 = fill.

## Gap-filling and Latest_High_Quality_Retrieval

- Temporal gap-filling is one of the algorithm's three key enhancements (p.2). The night processing uses both temporal and spatial gap-filling (p.10).
- When gap-filling runs, the date of the latest high-quality main-algorithm retrieval goes into a separate layer. If an outlier persists, the algorithm "defaults to a monthly climatology" of recent moonless high-quality values (p.24).
- So after a storm, `Gap_Filled_DNB_BRDF-Corrected_NTL` can show pre-storm lights on a cloudy night **(inference)**. The plan's ban on that layer is right.
- `Latest_High_Quality_Retrieval` is a uint8 day count (Table 8 p.16; App. B pp.44–45). Figures 4F and 5F plot it on a scale from 0 to 16 days or more (pp.24–25).
- The text on p.24 calls this value a date, but the layer stores a number of days. **Not stated:** the day the count starts from, what 0 means, and what is stored when nothing was filled.
- **Not stated:** the search window, the spatial method, or which pixels get filled.

## Dates

- `AYYYYDDD` is the `Julian Date of Acquisition (A-YYYYDDD)` (p.6), which means the day of the year:
  - the figure captions write dates as `DOY 2015-091` (p.24);
  - `VNP46A2.A2024100` covers 2024-04-09, from 00:00:00 to 23:59:59 (pp.43–44);
  - `VNP46A1.A2023100` covers 2023-04-10 (pp.39–40);
  - the production stamps decode the same way.
- **Not stated in words:** whether the date is a UTC or a local day. The evidence points to UTC **(inference)**:
  - `PGE_EndTime` ends in `Z` (p.39);
  - the A2 file for day D takes the A1 file for day D as input (p.43);
  - the example A1 tile's input granules are stamped 05:36 to 09:00 on the file's own date (p.39). Those are UTC times under standard VIIRS naming (outside knowledge).
- **Ian (arithmetic):** `A2022271` is 2022-09-28, the landfall day (about 19:05 UTC). `A2022272` is 2022-09-29, which should hold the first night after landfall.

## Overpass time

**Not stated.**
- VNP46A2 has no time layer (p.15).
- Per-pixel time exists only in VNP46A1 `UTC_Time`, long name `View Time (UTC)`, in decimal hours (Table 5 p.12; App. A p.43).
- Figure 3 lists the overpass time as a model input but gives no value (p.9).
- The 02:00 local time on p.27 is when a field experiment ran, not the overpass time.

*Outside knowledge; verify with `UTC_Time`:* S-NPP's night pass is near 01:30 local **solar** time. At 82°W that means roughly 06–08 UTC (about 02–04 EDT), not 01:30 EDT. File dates don't change, but the hour used to match EAGLE-I might.

## Tile grid

- Tiles are named `hXXvYY` (p.7). In Figure 2, h runs from 00 to 35 west to east and v from 00 to 17 north to south (p.7).
- There are 460 land tiles. The caption calls them "approximately" 10° (p.8), but every metadata bound is exactly 10°.
- Each tile is 2400 × 2400 pixels (App. B p.44). At 15 arc-seconds (pp.2, 6), that is 1/240° per pixel.
- **Example bounds:**
  - h10v04: west −80, east −70, south 40, north 50 (pp.39–40, 43–44);
  - h10v05: north 40 (p.50), south 30 (p.54).
- **Derived:** `h = floor((lon+180)/10)` and `v = floor((90−lat)/10)`, which put all of Lee County in `h09v06`.
- **Pixel centres or edges: not stated.** Test on a real h09v06 file:
  - centres give `lat[0]` ≈ 29.997917, `lat[-1]` ≈ 20.002083 and `lon[0]` ≈ −89.997917;
  - top-left edges give 30.0, 20.004167 and −90.0.

## Other caveats

- **Encoding (App. B pp.44–45):**
  - the offset attribute is `offset`, not `add_offset`;
  - `valid_range` is text, such as `">=0.0 \n"`, and the units strings end in `\n`;
  - the flag layers have no scale or offset attributes;
  - the fill is a float32 value, so mask in float32 or with `< 0`.
- **`lat` and `lon`:** both are 1-D float64 arrays on `phony_dim_0`. The dumps print lon's attributes as `lat:valid_min = -180.f` and so on (pp.43, 45, 50, 58), which is a documentation artifact.
- **Fill values:** they "can arise" when the solar zenith angle is below 102°. That footnote belongs to VNP46A1 (Table 5 p.13). The guide doesn't say whether cloudy pixels carry the fill value.
- **Viewing angle:** it matters (p.6). The A2 product has no view-angle layer; `Sensor_Zenith` exists only in A1 (p.11).
- **Vegetation:** neither C1 nor C2 applies a vegetation correction (p.10). Trees stripped by a storm could brighten pixels **(inference)**.
- **Moon:** on moon-free nights the algorithm sets θm = 10° and Em = 0.26 nW·m⁻² (unit as printed, p.5). A lunar zenith angle above 108° means no moon (p.28).
- **Noise floor:** the detection-limit targets are 3.0, 0.5 and 0.25 nW·cm⁻²·sr⁻¹ (Table 14 p.26). The 742 m footprint (p.7) is coarser than the roughly 463 m cell.
- **Coast:** the Figure 4E legend groups "Fill Value / Water Pixel" together (p.24). Bits 1–3 mark coastal pixels as 101 (p.14).
- **Latency:** standard processing takes 3–5 h (p.2). The near-real-time feed through LANCE takes about 3 h (pp.23, 29).
- **No outage method:** the guide gives none, but it cites Wang et al. 2018 and Román et al. 2019 (pp.29–30).
- **Errors in the guide:**
  - several "Table" cross-references have no number (pp.10, 15, 17, 24, 26);
  - it points to "List 2" where List 3 is meant (p.17);
  - it cites an "Equation 4" that doesn't exist (p.3);
  - two sections are numbered 2.3 (pp.4–5);
  - the List of Tables puts Table 11 on p.15, but it starts on p.18.

## Resolved disagreements

| Field | Decision | Page |
|---|---|---|
| All page fields | Same pages. A used printed numbers (15/16/16/7) and B used PDF indices (21/22/22/13). This sheet uses printed numbers. | — |
| `hdf5_page` | 15: the List 2 tree, which matches App. B's nesting. Path confirmed. | 15 |
| `flags_page` | 16: Table 9 runs from p.16 to p.17. | 16 |
| `tile_grid.page` | 7: the filename field and the Figure 2 grid. The caption is on p.8. | 7 |
| NTL fill and scale (spot check) | −999.9, 1.0, 0.0 in Table 8 and App. B | 16 |
| Cloud bits 6–7 (spot check) | Same values in Table 6, App. B and the App. A flag meanings | 14 |
| Bit 10 name | Kept as printed, `Snow/ Ice Surface`; B had normalised it. Values are identical. | 14 |
| `gap_fill`, `latest_high_quality_retrieval` | No conflict, so merged. Added that p.24 calls the value a date while the layer stores days. | 24 |
| `date_convention` | Day of year. UTC or local is not stated (null). Added evidence pointing to UTC. | 6 |
| `overpass_time` | Not stated (null). The "05:30 UTC" in agent-docs is its own inference, and probably about 1.5 h early. | — |
| Solar zenith < 102° gives fill | B is right that fill "can arise" there. The footnote belongs to VNP46A1. | 13 |
| h10v05 bounds | North 40 is on p.50 and south 30 on p.54 (B is right; A cited p.54 for both). | 50 |
| lon attributes, `phony_dim_0` | B is right, and the same pattern appears in all four appendices. | 45 |
| Table 14 ±5% | All three resolution values carry ±5%. | 26 |
| Pitahaya 0.43 | This is the level reached, not the spec. The breakthrough spec is 0.5. | 28 |
| agent-docs edge values | `lat[-1]` would be 20.004167, not 20, for edge coordinates. Its centre values are right. | — |
| Other agent-docs claims | Re-checked; they agree with both readers. | — |
