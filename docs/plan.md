# Gridfall Implementation Plan

> **For the builder:** you write every line of code. Claude reviews each task before you start the next. Steps use checkboxes (`- [ ]`).
>
> **Update, 2026-11-08:** at your request, Claude builds Weeks 2–8 autonomously and you review (decision log, "Who writes Weeks 2–8").
>
> **Status, 2026-11-10:** this plan is kept as a record of how the build was laid out, and "you" in it is the project's author. Its checkboxes were never ticked as the work went on, so an empty box does not mean a step was left undone: the README says what was built, and the decision log records the calls made along the way.

**Goal:** Build a rerunnable pipeline and a static web app. Together they estimate customers out per US county after a hurricane from Black Marble night lights, graded against EAGLE-I on storms the model never saw.

**Architecture:**
- A Python package (`blackout`) turns satellite tiles plus EAGLE-I, Census and NOAA files into one county × night table.
- It fits a simple "% darker → % out" curve.
- It scores the curve by holding out one storm at a time, then on two locked-away storms.
- It exports static JSON, which a TypeScript React + MapLibre app reads.
- There's no server.

**Tech Stack:**
- Python 3.13 with uv, pytest, pytest-cov, ruff and jupyter.
- Python data libraries: blackmarblepy, h5py, numpy, pandas, geopandas, rasterio, duckdb, scikit-learn, matplotlib, pyyaml, httpx and jsonschema.
- App: TypeScript, Vite, React, maplibre-gl, and vitest with happy-dom.
- CI: GitHub Actions.

**Spec:** `docs/design.md` (the design note of 2026-11-05).

**Pace:** 8 weeks at about 10 hours a week (assumed).

## Global Constraints

**Ground rules**
- A personal project: public data only, and the policies and claims are synthetic.
- Claude writes the code from Week 2 on, at your request (2026-11-08), and you review. Nothing is pushed or hosted without your OK.

**Repo and data handling**
- Keep the repo on a local disk, not in a cloud-synced folder.
- Raw downloads go in `data/raw/`, which is gitignored. Process one storm at a time, and delete raw tiles and CSVs after extracting what you need.
- The NASA token lives only in the env var `EARTHDATA_TOKEN`. Never commit it, and gitignore `.env`. If the token is missing, fail fast with a clear message.

**Code standards**
- Functions return new DataFrames or arrays and never modify their inputs.
- Test coverage must be 80% or higher on `src/blackout` (`uv run pytest --cov=blackout`).
- Numbers are only reported at the county level. FIPS is always a 5-character string.

**Satellite data**
- Read only the `DNB_BRDF-Corrected_NTL` layer, never `Gap_Filled_DNB_BRDF-Corrected_NTL`. It is float32 with fill −999.9, under `/HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields/`.
- Clear pixels need `Mandatory_Quality_Flag` 0. In Collection 2, 1 means poor (outlier or possible cloud) and 2 means twilight.
- Use Collection 2 (`archiveSet` 5200). Suomi NPP is `VNP46A2` (main); NOAA-20 is `VJ146A2` (cross-check).
- Tiles are 10° × 10°, with 2400 × 2400 pixels each (1/240° per pixel). Tile ids follow `h = floor((lon + 180) / 10)` and `v = floor((90 − lat) / 10)`.
- Night convention: a file dated D (UTC) holds the pass at about 01:30 local *solar* time on D. In Florida that is about 07:00 UTC, and VNP46A1's `UTC_Time` gives the exact time. Label the file night D − 1, and compare it to EAGLE-I's ±60-minute median around that pass time, after dropping feed-dropout runs (Task 2).

**Storms and baselines**
- Main storms: Florence and Michael (2018), Laura and Isaias (2020), Ida (2021), Ian (2022), Idalia (2023), Beryl (2024).
- Lockbox: Helene and Milton (2024). Stress test: Uri (2021).
- Baseline: the median of clear nights in the 30 nights ending 3 days before landfall. Milton's baseline ends before Helene's landfall.

**Starting cutoffs** (tune on training storms only, and log every change)
- Visible share: 0.5. Baseline nights: at least 5 clear ones.
- State coverage: 0.8 (`covered = coverage >= 0.8`). At 0.8, Mississippi (0.66–0.77 in 2018–2022), Texas in 2020 (0.63), Alabama in 2018 (0.79) and Tennessee (every year) are not covered. Settle this before Task 5 builds the storms (decision log, 2026-11-08, open question 3).
- EAGLE-I dropout rule: `DIP_RATIO` 0.93, `MAX_DIP` 3 h, `FEED_SHARE` 0.5, `HOLD_RUNS` 2 (decision log, 2026-11-08). These are an exception to the heading: they were tuned partly on Uri, the stress test, so Uri's Task 9 score must say so.
- The pass bar is committed to `docs/decision-log.md` before the lockbox opens. Suggested bar: beat the wind-only guess on county error for both locked storms.

**Portfolio example**
- Waiting periods: 24, 48 or 72 hours, with 72 as the default.
- Synthetic portfolio: 100,000 policies, 5% of them business, seed 20261105.
- EAGLE-I is CC BY 4.0, so credit it in the README.

## Review Focus

1. **Zero, missing and dropout are different.** A county missing from a live EAGLE-I run means zero customers out. A run with no rows for the whole state means the scraper missed it, and an empty count is missing too: neither enters a median as zero (`flag_dropouts` reads empty counts as 0 only while looking for dips). Scrapers also time out or lose one utility's feed during storms, so take the median of a ±60-minute window of runs after dropping the runs `flag_dropouts` marks. Test in Task 2.
2. **FIPS joins fail silently.** `MCC.csv` stores unpadded integers and starts with a byte-order mark. The outage files use padded strings, but DuckDB guesses integers when a file has no leading-zero codes, so force VARCHAR. `load_outages` takes 2-digit state FIPS, while `Storm.states` and `coverage_for` use USPS codes: map them with `STATE_FIPS`. Test in Tasks 2, 4 and 5.
3. **Nights and timezones can be off by one.** The UTC file date, the local pass time and the EAGLE-I stamps must line up. EAGLE-I stamps are naive UTC, and DuckDB compares tz-aware bounds in its own session zone, so pass bounds to it as naive UTC. Test in Tasks 2, 3 and 5.
4. **"Can't see" never becomes zero.** Cloudy or dark counties stay out of training, out of the exposure sums and off the color scale. Test in Tasks 5, 6, 10, 11 and 12.
5. **The lockbox must not leak.** No fit or tuning call may touch Helene or Milton before the pass-bar commit. Test in Task 6.

## File map

```
gridfall/
  pyproject.toml · README.md · .github/workflows/ci.yml · .gitignore
  config/storms.yaml                 storm list, dates, roles
  schema/export.schema.json          contract between pipeline and app
  docs/ design.md · plan.md · decision-log.md · phase0.md · scorecard.md · failures.md · writeup.md · img/
  scripts/phase0/                    Phase 0 only (planned as a notebook, built as scripts)
  src/blackout/
    outages.py      EAGLE-I outages, dropout flags, customers (MCC), coverage, STATE_FIPS
    nightlights.py  tile ids, HDF5 layers, clear mask, NOAA-20 downloader
    storms.py       Storm records from storms.yaml
    winds.py        HURDAT2 parsing, wind band per county
    counties.py     county shapes, housing units, customers
    aggregate.py    county label grids, per-night county sums, % darker
    table.py        joins everything into county_nights_<storm>.parquet
    model.py        translation curve, simple guesses, lockbox guard
    evaluate.py     leave-one-storm-out, scorecard
    ranges.py       error ranges, restoration intervals, hour brackets
    portfolio.py    synthetic policies and claims
    export.py       static JSON for the app
    cli.py          `blackout build | evaluate | export`
  tests/ fixtures/ · test_<module>.py per module
  data/ raw/ interim/ processed/ (gitignored) · sample/ (committed, small)
  app/ src/types.ts · src/data/load.ts · src/lib/{exposure,claims,flags}.ts
       src/components/{StormMap,CountyCard,PortfolioPanel,ClaimCheck}.tsx · public/data/
```

---

## Week 1: Phase 0, Ian in Lee County, by hand

### Task 1: Repo, accounts, and the Phase 0 chart

There are no tests this week. It's a by-hand check that the idea works before anything gets built.

**Files:**
- the repo layout above (empty modules are fine)
- `scripts/phase0/` (planned as `notebooks/00_ian_lee_county.ipynb`; Phase 0 was built as scripts, and no such notebook is in the repository), `docs/phase0.md`, `docs/decision-log.md`
- the design doc and this plan, moved into `docs/`

- [ ] **Accounts.** Make a free NASA Earthdata account, generate a token, and put `export EARTHDATA_TOKEN=…` in your shell profile, not in the repo.
- [ ] **Project setup.**
  - Create a uv project with a src layout and import name `blackout`, plus a console script `blackout = "blackout.cli:main"`.
  - Add the Tech Stack dependencies, then run `git init`.
  - Gitignore `data/raw`, `data/interim`, `data/processed`, `.env` and `node_modules`.
- [ ] **Download the night lights.**
  - Get `VNP46A2` tile `h09v06` for 2022-08-25 to 2022-10-19 with `BlackMarbleDownloader(token, directory).download(gdf=lee, product_id=Product.VNP46A2, date_range=dates)`.
  - Import it with `from blackmarble.download import BlackMarbleDownloader` and `from blackmarble.types import Product`.
  - If Jupyter complains about a running event loop, run the download from a script instead.
- [ ] **Inspect the files.** Print the HDF5 tree of one file. Record the layer paths, fill value and scale factor in `docs/phase0.md`.
- [ ] **Get the county and outage data.**
  - Lee County (FIPS `12071`): take its shape from `cb_2022_us_county_500k.zip`.
  - Its outages: take the `12071` rows from `eaglei_outages_2022.csv`. Stream that 1.2 GB file with DuckDB `read_csv('<download url>')`, or download it, filter, and delete it.
  - Its customers: take them from `MCC.csv`, read as `utf-8-sig` with `zfill(5)` on the codes.
- [ ] **Plot two lines across the nights:**
  - "% darker", meaning clear pixels compared with their baseline median;
  - EAGLE-I % out at the satellite pass (about 07:00 UTC).
- [ ] **Run four checks and write each up in `docs/phase0.md`:**
  1. Compare the gap-filled and corrected layers on the first three nights after the Sep 28 landfall.
  2. Check whether "poor quality" pixels (`Mandatory_Quality_Flag` = 1, which Collection 2 uses for outliers and possible cloud) carry real outages.
  3. Find EAGLE-I's timezone. Outages should surge within hours of the mid-afternoon landfall on Sep 28. If the surge appears about 4 hours late, the stamps are UTC.
  4. Check the night convention: the first dark file should be dated Sep 29.
- [ ] **Commit:** `docs: phase 0 Ian / Lee County check`

**Done when:** the two lines move together, or `docs/phase0.md` explains why they don't. If they don't, stop and talk to Claude before Week 2.

## Week 2: Phase 1, tested loaders

This week now has 34 tests (25 in Task 2, 9 in Task 3), up from 16. Decide now whether the six tests under "Synthetic frames" in Task 2 stay in Week 2, and log the answer under question 5 of the 2026-11-08 decision-log entry. If they move to Week 3, they must pass before Task 5 builds the storms: they are the only tests that pin the `j+2` resume, the per-state walk, step 3's end search, the 0.93 and 3-hour edges, and flags on absent cells.

### Task 2: EAGLE-I loader

**Files:**
- `src/blackout/outages.py`
- `tests/test_outages.py`
- `tests/fixtures/eaglei_small.csv`, `mcc_small.csv`, `coverage_small.csv` (real rows; recipe below)

**Interfaces it produces:**
- `EAGLEI_TZ: str = "UTC"`. The data paper says UTC, and the Phase 0 checks agree. Runs come every 15 minutes.
- `STATE_FIPS: dict[str, str]`: USPS code to 2-digit FIPS (`"FL"` → `"12"`) for every code in `coverage_history.csv` (56: the 50 states, DC, PR, AS, GU, MP and VI). Tasks 4–5 use it to turn `Storm.states` into the prefixes `load_outages` takes.
- `load_outages(source: Path, states: set[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame`
  - `source` is a local `.csv` or `.parquet`; pick the DuckDB reader by suffix. No URLs: `httpfs` isn't installed and CI is offline.
  - `states` are 2-digit FIPS prefixes such as `{"12"}`, not USPS codes (`{"FL"}` would silently load nothing), so raise `ValueError` for any entry that isn't two digits. Keep every county of those states: the dropout check needs whole states.
  - Keep rows with `start <= time < end`. If `start` or `end` has no time zone, raise `ValueError` yourself (pandas would only raise `TypeError` later). Open a new DuckDB connection per call, and pass the bounds as naive UTC (`t.tz_convert("UTC").tz_localize(None)`) or run `SET TimeZone='UTC'` first. DuckDB compares tz-aware bounds in its session zone, America/Los_Angeles on this Mac, so tz-aware bounds return 0 of the 208 rows `test_window_filter` expects.
  - For a `.csv`, read `fips_code` as text with `read_csv(..., types={'fips_code': 'VARCHAR'})`. `read_parquet` has no `types` option, so for a `.parquet`, check that `fips_code` is VARCHAR and raise `ValueError` if it isn't. Push the state and time filters into SQL.
  - Columns: `fips` (5-character str), `time` (tz-aware UTC), `customers_out` (float64, NaN where the file's count is empty: 2,270 rows in the Ida extract, 8,325 in Uri's). Return the file's rows as they are: don't add rows for absent counties or fill empty counts.
- `flag_dropouts(outages) -> pd.DataFrame`, with columns `fips` and `time`, one row per feed-dropout reading.
  - *In plain words:* when EAGLE-I's scraper loses one utility's feed, that utility's counties all drop in the same run and come back within a few hours, so the state's total makes a short V. This finds those V's and marks the readings of the counties that caused them.
  - Constants: `DIP_RATIO = 0.93`, `MAX_DIP = 3 h`, `FEED_SHARE = 0.5`, and `HOLD_RUNS = 2` (fixed: the steps use runs `i−2`, `i−1`, `j` and `j+1`). The decision log's 2026-11-08 entry says why.
  - For each state (`fips[:2]`) on its own:
    1. Use the state's live runs: runs with at least one row for the state, empty counts included. A county with no row in a live run reads 0, as it does everywhere else. Here, and only here, an empty count also reads 0 (`customers_out_at` treats it as unusable). `S` is the state total of each run.
    2. Walk the live runs from the third one. At run `i` the held level is `B = min(S[i−2], S[i−1])`. A dip starts if `S[i] < 0.93 × B`; otherwise go to `i+1`.
    3. The dip ends at the first later run `j` where `S[j]` and `S[j+1]` are both at least `0.93 × B`. Run `j` must be at most 3 hours after run `i−1` (exactly 3 hours counts); run `j+1` may be later. If there is no such `j`, it is not a dropout: go to `i+1`.
    4. A county's shoulder is its smallest value at runs `i−2`, `i−1`, `j` and `j+1`. A county-run in the dip (runs `i` to `j−1`) is low when it reads below `0.93 ×` the shoulder.
    5. Only counties low in run `i` take part: a lost feed drops all its counties in the same run.
    6. County loss: for each taking-part county, its shoulder minus its lowest value in runs `i` to `j−1`, added up. State loss: `min(B, S[j], S[j+1])` minus the lowest `S` in the dip. If county loss `≥ 0.5 ×` state loss, flag those counties' low runs (absent and empty cells included); otherwise flag nothing.
    7. Whether or not anything was flagged, continue the walk at run `j+2`.
- `customers_out_at(outages, fips: str, when: pd.Timestamp, window_minutes: int = 60, dropouts: pd.DataFrame | None = None) -> float`
  - The median over the live runs of the county's state with `|time − when| <= window_minutes`, both ends included. Scrapers time out during storms, so one run is not enough.
  - A run gives the county's count, or 0.0 if the county has no row (explicit 0 rows also mean 0). An empty count makes that run unusable, never 0. Runs with no rows for the state are skipped.
  - Drop the runs flagged for this county, including flags on absent cells. NaN when no usable run is left.
  - `dropouts=None` runs `flag_dropouts(outages)` first; Task 5 runs it once per storm and passes it in.
  - Check `when` first: a naive `when` raises `ValueError`. After that, an empty frame gives NaN (and no flags) without raising.
  - Load at least 3 h 30 min of extra data on each side of every window you will query, and call `flag_dropouts` once on the whole load: near a load's edges a dip can be cut off, which changes where the walk goes next. Never filter the frame to one county first.
- `load_mcc(csv: Path) -> dict[str, int]`: reads with `utf-8-sig`, drops the trailing `Grand Total` row, and zero-pads codes to 5 characters.
- `coverage_for(coverage_csv: Path, state: str, year: int) -> float`: `max_pct_covered` for a USPS `state`, falling back to the latest earlier year. The file covers `1/1/18`–`1/1/22`; raise `ValueError` for a year before 2018.

- [ ] **Read why the dropout rule looks like this** in `docs/decision-log.md` (the 2026-11-08 entry, Claude's call). Override anything you disagree with there before coding.
- [ ] **Build the fixtures from real rows:**
  - `eaglei_small.csv`: for each window below, use DuckDB to copy every row of that state from its `data/interim` parquet (Florida from the Ian file, Louisiana from the Ida file, Texas from the Uri file), both end stamps included. Select by the `fips_code` prefix (12, 22, 48), because the `state` column holds full names such as "Florida".
    - A FL 2022-09-29 07:45–12:15 (1,156 rows); B FL 2022-09-30 05:30–09:00 (783); C FL 2022-09-15 06:45–10:45 (419); D FL 2022-10-18 22:00 to 10-19 01:30 (440); E FL 2022-10-17 12:00–16:00 (772); F FL 2022-10-07 21:00 to 10-08 01:30 (829); G FL 2022-09-17 12:30–17:00 (663); H LA 2021-08-30 16:00–19:00 (687, 82 empty); I TX 2021-02-18 04:30–06:30 (1,747, 9 empty).
    - Raw format: header `fips_code,county,state,customers_out,run_start_time`, times as `YYYY-MM-DD HH:MM:SS`, an empty field for an empty count, LF line endings, sorted by time then fips. Total: 7,496 rows and 341,528 bytes, with a final newline.
    - With no leading-zero codes in it, DuckDB guesses `fips_code` is BIGINT, so a loader that doesn't force VARCHAR either fails to bind `left(fips_code, 2)` or returns integers, and fails the type test.
    - Tests load a window as `[first stamp, last stamp + 15 min)`. The windows are shorter than the 3 h 30 min margin, but each gives the same flags as a 12-hour padded load (checked).
  - `mcc_small.csv`: the real file's first three lines and its last line, bytes untouched (BOM, CRLF, `1001,24619`, and `Grand Total,154451840` with no final newline):

    ```bash
    (head -n 3 data/raw/eaglei/MCC.csv; tail -n 1 data/raw/eaglei/MCC.csv) > tests/fixtures/mcc_small.csv
    ```
  - `coverage_small.csv`: the real header plus the FL, LA and TX rows for `1/1/18`–`1/1/22`, CRLF:

    ```bash
    grep -E '^year,|,(FL|LA|TX),' data/raw/eaglei/coverage_history.csv > tests/fixtures/coverage_small.csv
    ```
- [ ] **Write the tests.** Times are UTC. "Without" means `dropouts` is passed as an empty frame. A value given with no window uses the default ±60.
  - `test_load_types_and_whole_state`: window B → 783 rows, 15 runs, 57 counties; every `fips` a 5-character `str` starting `"12"`; `time` tz-aware UTC (check the zone, not the dtype string: DuckDB returns `datetime64[us, UTC]`); `customers_out` float64. Window B written to a `.parquet` in `tmp_path` gives the same 783 rows. Also write a CSV to `tmp_path` with the header and the real first two rows of `eaglei_outages_2022.csv` (`01005,Barbour,Alabama,4,2022-01-01 00:00:00` and `01009,Blount,Alabama,160,2022-01-01 00:00:00`): `load_outages(path, {"01"}, 2022-01-01 00:00, 2022-01-01 00:15)` gives fips `["01005", "01009"]` (pandas' default `read_csv` gives `1005`).
  - `test_window_filter`: inside `with monkeypatch.context() as m:`, call `m.setenv("TZ", "America/Los_Angeles")` and `time.tzset()`, then call `time.tzset()` again after the block. The test then catches tz-aware bounds even on a UTC machine, and leaves the zone as it was. `[2022-09-30 07:00, 08:00)` → 208 rows, stamps exactly 07:00, 07:15, 07:30 and 07:45.
  - `test_bad_inputs_rejected`: a naive `start`, a naive `when`, and `states={"FL"}` each raise `ValueError`.
  - `test_empty_count_is_nan_and_skipped`: window H → 687 rows, 82 NaN, all at 17:30 and 18:30. Without the rule, Jefferson (`22051`) at 17:30 is NaN at `window_minutes=0` and 200679.0 at 15. Use the empty frame on purpose: the default flags already drop Jefferson's 17:30 run, so they would hide a bug that reads an empty count as 0 (that bug gives 0.0).
  - `test_absent_county_in_live_run_is_zero`: window C. Charlotte (`12015`) at 2022-09-15 08:45 is 0.0 (9 live runs with 24–26 Florida rows each, none for Charlotte). Filter the frame to Charlotte first and no rows are left, so the result is NaN: that's why you never filter by county first.
  - `test_missing_state_run_is_nan`: window D lacks Florida rows at 23:15, 00:15 and 00:30, the only missing runs of 2022. Lee (`12071`) at 2022-10-19 00:22:30 is NaN at `window_minutes=15` and 11520.0 at 60.
  - `test_single_timeout_run_ignored`: synthetic state 12, 9 runs from 08:00, `12001` at 5,000 except 0 at 09:00, `12003` at 1,000 → 5000.0 at 09:00, and `flag_dropouts` gives exactly (`12001`, 09:00).
  - `test_dropout_1_flagged`: window A. Lee is flagged at exactly 09:15–10:45 (7 runs); 12007, 12009, 12011, 12015, 12021, 12027, 12035, 12043, 12051, 12061, 12071, 12081, 12085, 12086, 12093, 12099, 12107, 12109, 12111, 12115 and 12127 are each flagged in all 7; nothing at 09:00 or 11:00; 165 flags in all.
  - `test_feed_dropout_is_missing` (rewritten): window A, Lee at 2022-09-29 10:00: ±30 NaN (175,458.0 without); ±60 421267.5 (175,468.0 without), because only 09:00 and 11:00 remain, exactly on the window's ends, which also pins inclusive ends; ±90 421267.5.
  - `test_single_run_dropout_teco`: window A. The flags at 11:30 are exactly 12057, 12101 and 12105 (Hillsborough, Pasco, Polk); Hillsborough at 11:30 with `window_minutes=0` → NaN (1,214.0 without).
  - `test_partial_dropout_dropped`: window B. Flags exactly {12071, 12021} × {07:00, 07:15}, also when loaded as `[06:00, 08:45)`. Lee at the real pass, 07:28:03: ±30 411676.0 (325,973.0 without), ±60 411615.0 (409,085.5 without, Phase 0's value), ±90 411614.5; Collier ±30 166534.0 (154,277.0 without). Query at 07:28:03, not 07:00: at 07:00 ±30 is 411,615.0 either way.
  - `test_real_restoration_step_kept`: window F. Lee is never flagged and reads 65644.0 at 2022-10-07 23:15 (its real step 94,793 → 65,644); the only flags are 20 counties at 10-08 00:30, Charlotte among them (11,942 → 482 → 11,942).
  - `test_one_run_spike_is_not_a_level`: window E → no flags. Lee at 14:00 is 11399.0 (±0 to ±30 give 11,275.0). Lee reads 11,201–11,542 except a one-run spike at 13:00 (14,263) and a two-run rise at 14:45–15:00; one-run shoulders would flag it from 13:15 to 14:30.
  - `test_unrelated_churn_not_flagged`: window G → no flags. Florida's total falls from its held level of 7,696 to 1,648 and recovers, as Palm Beach is restored and Broward rises. Counties low at 13:45, the dip's first run, explain only 87 of that 6,048 fall.
  - `test_uri_restoration_blip_not_flagged`: window I → no flags; Harris (`48201`) at 2021-02-18 05:30 is 86820.0.
  - Synthetic frames: state 12, 33 runs every 15 minutes from 06:00 to 14:00 on one day; `12003` reads 1,000 in every run unless a test says otherwise.
    - `test_synthetic_90_minute_dropout` (replaces "returns NaN inside the dip"): `12001` reads 100,000 except 500 at 09:00–10:15 → those 6 runs are flagged; at 09:37:30 ±30 is NaN and ±60 is 100000.0 (500.0 without). The same flags and values come out with `12003` at 900,000, and with `12001` absent (no row) in the dip (then 0.0 without). With `12001` at 500 for 09:00–09:30 and 10:00–10:30 it is one dip: 6 flags, and 100000.0 at 09:45 ±60 (500.0 without).
    - `test_rider_not_flagged`: `12001` reads 100,000 except 500 at 09:00–09:45; `12003` reads 10,000 except 8,000 at 09:30–09:45; `12005` reads 1,000 → only `12001` is flagged, and `12003` at 09:30 with `window_minutes=0` is 8000.0 (code that skips step 5 flags `12003` too and gives NaN).
    - `test_thresholds_are_pinned`: (a) 9 runs from 08:00, `12001` at 7,500 except 0 at 09:00, `12003` at 92,500 → (`12001`, 09:00) is flagged, because the state falls to 0.925 of its level; with `12003` at 100,000 nothing is flagged (100,000 / 107,500 = 0.9302). This pins 0.93: 0.92 misses the first case and 0.94 flags the second. (b) `12001` at 100,000 except 500 from 09:15 to 11:45, back at 12:00, exactly 3 hours after 09:00 → 11 flags, and 10:30 ±60 is NaN; with 500 through 12:00 → no flags, and 10:30 ±60 is 500.0.
    - `test_ramp_and_step_not_flagged`: one frame with three more counties. `12001` falls in a straight line from 200,000 at 06:00 to 1,000 at 14:00; `12005` falls by the same factor each run from 400,000 to 2,000; `12007` is 100,000 until 08:45 and 60,000 from 09:00 → no flags. `12001` at 10:00 is 100500.0, and `12007` at 09:00 is 60000.0.
    - `test_walk_resumes_after_rejected_dip`: `12001` 6,000 at 06:00–06:15, then 1,000; `12003` 0 until 07:45, then 5,000; `12005` 1,500 except 0 at 07:00–07:15; `12007` 500 → no flags (resuming at `i+1` would flag `12005` at 07:00 and 07:15).
    - `test_states_are_independent`: state 22 is the 90-minute case (`22001`, `22003`). State 28: `28001` 5,000 except 0 at 12:00–12:15, `28003` 1,000, and no state-28 rows at all at 11:00 or 11:15 → 8 flags (`22001` × 6, `28001` at 12:00 and 12:15); `28001` at 11:07:30 with `window_minutes=8` → NaN (one pooled state gives 6 flags and 0.0).
  - `test_mcc_bom_and_padding`: `load_mcc(f)["01001"] == 24619`. `test_mcc_drops_grand_total`: no `Grand Total` key, and every key is 5 digits.
  - `test_coverage_fallback`: `coverage_for(f, "TX", 2024) == 0.93`, which is 2022's value, not 2021's 0.94 and not the 0.94 maximum of earlier years. `coverage_for(f, "TX", 2021) == 0.94`. Florida can't tell these apart: it reads 0.98 in both 2021 and 2022.
  - `test_coverage_before_first_year_raises`: `coverage_for(f, "FL", 2017)` raises `ValueError`.
- [ ] Run `uv run pytest tests/test_outages.py -v`. Expect a FAIL.
- [ ] Implement.
- [ ] Run the tests again and expect a PASS. Then run `uv run ruff check`.
- [ ] **Commit:** `feat: EAGLE-I loader with zero-vs-missing rule and dropout check`

### Task 3: Night-light reader and clear mask

**Files:**
- `src/blackout/nightlights.py`
- `tests/test_nightlights.py`
- `tests/fixtures/make_fake_tile.py`, which writes tiny VNP46A2 and VNP46A1 HDF5 files with the real layer paths, dtypes and file-name format:
  - radiance and `UTC_Time` are float32, `Mandatory_Quality_Flag` and `Snow_Flag` uint8, and `QF_Cloud_Mask` uint16;
  - write each `_FillValue` the way the real files store it, as a 1-element array in the layer's dtype, such as `np.array([-999.9], dtype=np.float32)`;
  - name files like `VNP46A2.A2022272.h09v06.002.2025134023553.h5`.

**Interfaces it produces:**
- `tile_ids_for_bbox(west, south, east, north) -> list[str]`, sorted, for example `"h09v06"`.
  - Tiles are `[west, east) × (south, north]`, matching the files' top-left pixel edges (`lat[0] = 30.0`, `lon[0] = −90.0` in h09v06).
  - `h` runs from `floor((west + 180) / 10)` to `max(that, ceil((east + 180) / 10) − 1)`, and `v` from `floor((90 − north) / 10)` to `max(that, ceil((90 − south) / 10) − 1)`, clamped to 0–35 and 0–17. An edge exactly on a 10° line adds no tile.
  - Raise `ValueError` if `west > east` or `south > north`. Boxes across the antimeridian are out of scope.
- `@dataclass TileNight`, with fields:
  - `tile_id: str`, `file_date: date`
  - `radiance: np.ndarray[float32]`, where fill becomes NaN
  - `quality: np.ndarray[uint8]`, `cloud_conf: np.ndarray[uint8]` (0–3), `snow: np.ndarray[uint8]` (from the `Snow_Flag` layer)
  - Pixel positions follow from `tile_id`: pixel (0, 0) has its top-left corner at `lon = h × 10 − 180`, `lat = 90 − v × 10`, and each pixel is 1/240°. Reading the file's lat/lon values as pixel centres would shift the grid by half a pixel.
- `read_tile(path: Path) -> TileNight`
  - `tile_id` and `file_date` come from the file name. In `VNP46A2.A2022272.h09v06.002.2025134023553.h5`, `A2022272` means 2022, day 272 counting January 1 as day 1, which is 2022-09-29. Accept `VNP46A2` and `VJ146A2` names, and raise `ValueError` for anything else.
  - Read the fill from the layer's `_FillValue` attribute, a 1-element array: use `attrs["_FillValue"][0]` (`float()` on it raises `TypeError` under NumPy 2.5). The dataset's own HDF5 fill value is 0.0, not −999.9.
  - Don't assume 2400 × 2400, so the fixture can stay tiny. A tiny tile is the top-left block of its tile, so Task 5 tests compare it with `county_label_grid(...)[:rows, :cols]`.
- `clear_mask(t: TileNight, allow_snow: bool = False) -> np.ndarray[bool]`. A pixel is clear when all of these hold:
  - quality is 0 (in Collection 2, 1 means poor: outlier or possible cloud, and 2 means twilight);
  - the cloud flag says "confident clear" or "probably clear";
  - `snow == 0` (255 is fill and never clear); with `allow_snow`, 1 is also accepted;
  - radiance isn't NaN.
- `night_of(file_date: date) -> date`, which returns `file_date − 1 day`.
- `pass_time_utc(file_date: date, lon: float, utc_hours: float | None = None) -> pd.Timestamp`, tz-aware UTC and rounded to the nearest second. It returns `file_date` 00:00 UTC plus `utc_hours` when that is given and finite, and otherwise 01:30 local mean solar time on `file_date` (UTC = 01:30 − lon/15 hours). Task 5 passes the county's median `UTC_Time`.
- `read_utc_time(a1_path: Path) -> np.ndarray[float32]`: VNP46A1's `UTC_Time` layer (decimal hours, same group path), with fill −999.9 as NaN. Find the A1 file for an A2 file by product, date and tile (`VNP46A1.A{YYYYDDD}.{tile}.*.h5` for `VNP46A2`, and `VJ146A1…` for `VJ146A2`), not by swapping the prefix, because the production stamps differ.

- [ ] **Write the tests:**
  - `test_tile_ids_lee_county`: `tile_ids_for_bbox(-82.3, 26.3, -81.6, 26.8) == ["h09v06"]`
  - `test_tile_ids_straddle`: `tile_ids_for_bbox(-85, 29.5, -84, 30.5) == ["h09v05", "h09v06"]`
  - `test_tile_ids_edge`: `tile_ids_for_bbox(-90, 20, -80, 30) == ["h09v06"]`, and a box with `west > east` raises `ValueError`
  - `test_name_gives_tile_and_date`: a fake file named `VNP46A2.A2022272.h09v06.002.2025134023553.h5` reads as `tile_id == "h09v06"` and `file_date == date(2022, 9, 29)`
  - `test_fill_becomes_nan`: a fill pixel in the fixture comes back as NaN in `read_tile(f).radiance`, and in `read_utc_time` on the fake VNP46A1 file
  - `test_never_reads_gap_filled`: the fixture's gap-filled layer is bright where the corrected layer is fill, and `read_tile` returns NaN there
  - `test_cloudy_masked`: a pixel with quality 0, snow 0, a valid radiance and `QF_Cloud_Mask` 242 (bits 6–7 = 3, confident cloudy) is False in `clear_mask`; the same pixel with 50 (bits 6–7 = 0) is True. A pixel with `Snow_Flag` 255 is False, even with `allow_snow`.
  - `test_night_of`: `night_of(date(2022, 9, 29)) == date(2022, 9, 28)`
  - `test_pass_time_utc`: `pass_time_utc(date(2022, 9, 29), -81.9)` is 2022-09-29 06:57:36 UTC, and with `utc_hours=7.78` it is 07:46:48 UTC
- [ ] Run the tests and expect a FAIL.
- [ ] Implement. Decode the cloud bits in `QF_Cloud_Mask` from Table 6 of the [Collection 2 User Guide](https://viirsland.gsfc.nasa.gov/PDF/BlackMarbleUserGuide_Collection2.0.pdf) (printed pp. 13–14), and cite that table in a comment.
- [ ] Run the tests and expect a PASS.
- [ ] **Commit:** `feat: Black Marble tile reader and clear mask`

## Week 3: Phase 1, the county × night table

### Task 4: Storms, wind bands, counties

**Files:**
- `config/storms.yaml`
- `src/blackout/{storms,winds,counties}.py` and their tests
- `tests/fixtures/hurdat2_small.txt`

**Interfaces it produces:**
- `@dataclass(frozen=True) Storm`, with fields:
  - `id: str`, for example `"ian2022"`
  - `name: str`
  - `atcf_id: str | None`, for example `"AL092022"` (Uri has none)
  - `landfall: date`, `baseline_start: date`, `baseline_end: date`, `window_end: date`
  - `role: Literal["main", "lockbox", "stress"]`
  - `states: tuple[str, ...]`, USPS codes such as `("FL",)`; `STATE_FIPS` (Task 2) turns them into the prefixes `load_outages` takes
  - `allow_snow: bool = False`
- `load_storms(path: Path) -> list[Storm]`
  - Defaults: `baseline_end = landfall − 3 days`, `baseline_start = baseline_end − 30 days`, `window_end = landfall + 21 days`.
  - YAML values override the defaults. Milton sets `baseline_end: 2024-09-23`.
  - Uri: role `stress`, states `("TX",)`, `allow_snow: true`, landfall `2021-02-15`.
- `parse_hurdat2(path: Path) -> pd.DataFrame`, one row per track point.
  - Columns: `atcf_id`, `time` (UTC), `record`, `lat`, `lon`, `vmax_kt`, plus the 34/50/64-kt radii per quadrant in nautical miles (−999 becomes NaN).
  - Use the real file [`hurdat2-1851-2025-02272026.txt`](https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-02272026.txt).
- `wind_band_by_county(track: pd.DataFrame, counties: gpd.GeoDataFrame) -> pd.Series`, mapping `fips` to 0, 34, 50 or 64.
  - A county's band is the strongest zone that contains `geometry.representative_point()`.
  - Interpolate the track to hourly points first, or the swath will have gaps.
  - Stress storms get −1, meaning "doesn't apply".
- `load_counties(states: tuple[str, ...]) -> gpd.GeoDataFrame`
  - Columns: `fips, name, state, geometry, housing_units, customers`.
  - Housing units come from ACS 5-year 2022 table B25001, using the keyless summary file `acsdt5y2022-b25001.dat` on www2.census.gov (`api.census.gov` now requires a key). Customers come from `load_mcc`.

- [ ] **Write the tests:**
  - `test_storm_ids_exist_in_hurdat2`: every `atcf_id` is in the real file, and each `landfall` is within 1 day of an `L` record
  - `test_milton_baseline_before_helene`: Milton's `baseline_end` is before Helene's `landfall`
  - `test_band_inside_64kt`: a synthetic county inside the 64-kt radius gets band 64
  - `test_quadrants`: with a large NE radius and a small SW radius, a county to the NE is in the zone and one to the SW is not
  - `test_states_cover_wind_zone`: every county in band 34 or higher is in one of the storm's listed `states`
  - `test_no_county_lost_in_join`: `load_counties(("FL",))` has 67 rows, and no `customers` value is null
- [ ] Run the tests and expect a FAIL. Implement, then run them again and expect a PASS.
- [ ] **Commit:** `feat: storms, wind bands, county table`

### Task 5: Aggregation and the build command

**Files:**
- `src/blackout/{aggregate,table,cli}.py` and their tests
- `.github/workflows/ci.yml`
- `data/sample/county_nights_ian_sample.parquet`: Lee, Charlotte and Collier counties, real extracted values

**Interfaces:**
- It consumes Tasks 2–4. For the official numbers, `build_storm`:
  - copies the storm's states and dates from `eaglei_outages_<year>.csv` into `data/interim/eaglei_<storm.id>.parquet` with DuckDB (download the CSV to `data/raw/`, extract, then delete it; Task 2 reads local files only);
  - loads once with `outages = load_outages(path, {STATE_FIPS[s] for s in storm.states}, start, end)`, from `baseline_start` 00:00 UTC to `window_end` + 2 days 00:00 UTC (far more than Task 2's 3 h 30 min margin), and raises an error if `outages` is empty;
  - flags once with `flags = flag_dropouts(outages)`;
  - reads each county-night at the pass on file date `night + 1`: `when = pass_time_utc(night + 1 day, lon, utc_hours)`, where `utc_hours` is the median `UTC_Time` from the same satellite's A1 file (`VNP46A1` for `VNP46A2`, `VJ146A1` for `VJ146A2`) over the county's pixels with a valid time (cloudy ones included, as in Phase 0) and `lon` is the longitude of the county's `representative_point()`; then `customers_out_at(outages, fips, when, w, flags)` for `w` = 30, 60 and 90.
  - Put that read in a small helper, `official_columns(outages, flags, fips, night, lon, utc_hours) -> dict`, so it can be tested without tiles.
  - On nights when two passes cover the county, the all-pixel median can sit more than 60 minutes from the clear pixels' median (Lee, file date 2022-09-07: 7.986 h against 6.313 h). Count those nights per storm in the build output.
- `county_label_grid(tile_id: str, counties: gpd.GeoDataFrame) -> np.ndarray[int32]`, where 0 means no county.
  - Build it with `rasterio.features.rasterize(all_touched=False)` and cache it in `data/interim/`.
- `baseline_median(tiles: list[TileNight], allow_snow: bool) -> np.ndarray[float32]`
  - The per-pixel median of clear values; NaN when fewer than 5 nights are clear.
- `county_night(t: TileNight, base: np.ndarray, labels: np.ndarray, allow_snow: bool) -> dict`
  - Returns arrays indexed by county label, built with `np.bincount` over pixels that are clear tonight and have a baseline value:
    - `tonight`: tonight's light;
    - `base_visible`: baseline light over those same pixels.
  - Also returns `base_total`: baseline light over every pixel that has a baseline value.
  - Add these arrays up across tiles before finalizing.
- `finalize(sums) -> pd.DataFrame`, with columns:
  - `fips`
  - `pct_darker = 1 − tonight / base_visible`
  - `visible_share = base_visible / base_total`
  - `status`: `"ok"`, `"cant_see"` (visible share under 0.5) or `"not_measurable"` (`base_total` under `DARK_MIN`)
  - You pick `DARK_MIN` in this task and log the choice.
- `build_storm(storm: Storm, satellite: str = "VNP46A2") -> pd.DataFrame`
  - Writes `data/processed/county_nights_<storm.id>.parquet`.
  - Saves three quicklook PNGs to `docs/img/`: the baseline, the peak night and +7 days.
  - Deletes the raw tiles once done.
  - Columns:
    - `storm_id, fips, night, satellite`
    - `pct_darker, visible_share, base_total, status`
    - `sensor_zenith, lunar_irradiance`: county medians from VNP46A1 and VNP46A2, needed for the angle and moon corrections in Task 6
    - `official_customers_out` (the ±60 median with dropout runs removed), `official_customers_out_30` and `official_customers_out_90` (the same at ±30 and ±90), `official_pct_out = official_customers_out / customers`, `official_pct_out_30` and `official_pct_out_90` (the ±30 and ±90 counts over `customers`), `customers, housing_units`
    - `pass_utc, pass_source` (the A1 product name, or `"formula"`)
    - `wind_band, coverage, covered`
- CLI: `uv run blackout build --storm ian2022` builds one storm; `--all` builds every storm.

- [ ] **Write the tests:**
  - `test_straddling_county_sums_both_tiles`: a fixture county split across two tiles gets the full sum (with tiny fixture tiles, give the county one part in each tile's top-left block)
  - `test_all_cloudy_is_cant_see`: an all-cloudy night gives `status == "cant_see"` and a NaN `pct_darker`
  - `test_dark_county_not_measurable`
  - `test_same_pixels_only`: a pixel clear tonight but with no baseline is left out of both sums
  - `test_brighter_than_baseline_kept`: a negative `pct_darker` passes through unchanged
  - `test_official_at_pass_time`: call `official_columns` for Lee (`12071`) on night 2022-09-29 with `utc_hours=7.4675` (07:28:03 on file date 2022-09-30, the VNP46A1 median), using flags from one `flag_dropouts` call on window B of the Task 2 fixture, so CI stays offline. It returns `pass_utc` 2022-09-30 07:28:03 UTC and 411615.0 (±60), 411676.0 (±30) and 411614.5 (±90). Phase 0's 409,085.5 had no dropout flags.
  - `test_sample_table_schema`: the sample parquet has exactly the columns above
- [ ] Run the tests and expect a FAIL. Implement, then run them again and expect a PASS.
- [ ] **Before building,** settle and log open questions 1–4 in the 2026-11-08 decision-log entry (Ida's long DEMCO dropouts, over-counts, the 0.8 coverage cutoff, riders). Then run only the copy step of `build_storm`, so the extracts exist. For every storm except Helene and Milton (the lockbox stays shut until the pass-bar commit), compute the share of empty counts that sit in runs with 10 or more empty counts. In 2021 it was 44% in Louisiana, 16% in Mississippi and 47% in Texas. If a storm is far below those, log it and tell Claude before changing step 1 of `flag_dropouts`.
- [ ] **Build every storm** with `uv run blackout build --all`.
  - Drop rule: drop any storm where fewer than half the hit counties get an `ok` night within 7 days. Log every drop.
  - Building Helene and Milton is fine, but don't plot their estimates against the official numbers until Task 9.
- [ ] **CI:** add a workflow that runs `uv sync`, `ruff check` and `pytest --cov` offline, using only the fixtures and the sample.
- [ ] **Commit:** `feat: county x night table and build command`

## Week 4: Phase 2, the estimator

### Task 6: Translation curve, simple guesses, lockbox guard

**Files:** `src/blackout/model.py` · `tests/test_model.py`

**Interfaces it produces:**
- `class LockboxError(Exception)`
- `check_no_lockbox(storm_ids: set[str], storms: list[Storm], final: bool = False) -> None`
  - Every `fit_*` function calls this first.
- `fit_translation(train: pd.DataFrame) -> Translator`
  - Uses `IsotonicRegression(increasing=True, out_of_bounds="clip", y_min=0, y_max=1)`.
  - Fits only on rows with `status == "ok"`, `covered` and a non-NaN `official_pct_out`.
  - `Translator.predict(df) -> np.ndarray`
- `fit_wind_only(train: pd.DataFrame) -> dict[int, float]`, the mean `official_pct_out` for each wind band, over the same rows as `fit_translation`.
- `predict_nothing(df) -> np.ndarray`, which returns zeros.
- Before fitting, correct `pct_darker` for viewing angle (a sec(zenith) term, or same-orbit baselines 16 days apart) and for moonlight. In Phase 0, angle explained most night-to-night noise (Spearman −0.87), and moonlit nights read 6–11% darker. Report leave-one-out noise beside in-sample noise.
- Before fitting, decide and log what to do with `official_pct_out` above 1. These are EAGLE-I over-counts, and Ian has them too (Highlands reads 1.2–1.3 at Lee's pass times on the nights of Sep 28 and 29). Never clip them silently.

- [ ] **Write the tests:**
  - `test_lockbox_guard_raises`: fitting on rows that include `milton2024` raises `LockboxError` unless `final=True`
  - `test_monotone`: predictions never fall as `pct_darker` rises
  - `test_cant_see_not_trained`: changing a `cant_see` row's `official_pct_out` leaves the fit unchanged
  - `test_wind_only_means`: on a toy table, `fit_wind_only(t)[64] == 0.8`
- [ ] Run the tests and expect a FAIL. Implement, then run them again and expect a PASS.
- [ ] **Commit:** `feat: translation curve, simple guesses, lockbox guard`
- [ ] **Optional experiment:** try `HistGradientBoostingRegressor` on `pct_darker`, `visible_share` and `log(base_total)`. Keep it only if it beats the isotonic curve in Task 7, and log the result either way.

### Task 7: Leave-one-storm-out scorecard

**Files:** `src/blackout/evaluate.py` · `tests/test_evaluate.py`

**Interfaces:**
- It consumes Task 6.
- `loso(df, fit: Callable) -> pd.DataFrame`
  - Adds `pred_pct_out` for each main storm, using a fit on the other main storms.
- `official_restore_day(series) -> float`
  - `series` is the county's nightly truth column from Task 5 (`official_pct_out`, or the ±30 or ±90 version when `scorecard` scores that window). NaN nights are skipped: they neither count as restored nor break a restored stretch.
  - The first time after the peak when official % out drops to 0.10 or below and stays there for 24 hours.
  - Measured in days after landfall.
- `scorecard(preds: pd.DataFrame, window: int = 60) -> pd.DataFrame`. The curve is always fit on `official_pct_out` (±60). `window` only picks the truth column (`official_pct_out`, `official_pct_out_30` or `official_pct_out_90`), and that column also feeds `official_restore_day` and the peak totals. ±60 is the headline; `blackout evaluate` also writes ±30 and ±90, as `docs/phase0.md` section 6 promised. One row per storm, with these columns:
  - `mae_pp`
  - `peak_total_est`, `peak_total_official`
  - `catch_rate_50`, `false_alarm_50`
  - `restore_day_err`
  - `measurable_share`
- CLI: `uv run blackout evaluate` writes a draft `docs/scorecard.md`.

- [ ] **Write the tests:**
  - `test_loso_never_sees_its_storm`: the fit function gets no rows from the held-out storm
  - `test_scorecard_toy`: values you computed by hand match, for example `mae_pp == 12.5`
  - `test_official_restore_day_needs_24h`: a dip below 10% that bounces back doesn't count
- [ ] Run the tests and expect a FAIL. Implement, then run them again and expect a PASS.
- [ ] **Score the main storms:** run the isotonic curve, the wind-only guess and nothing-happened, and write all three into the draft scorecard.
- [ ] **Commit:** `feat: leave-one-storm-out scorecard`

## Week 5: Phase 2, ranges, restoration, and the lockbox

### Task 8: Ranges, restoration intervals, hour brackets

**Files:** `src/blackout/ranges.py` · `tests/test_ranges.py`

**Interfaces it produces:**
- `fit_ranges(loso_preds, n_bins: int = 5) -> RangeModel`
  - Takes the 10th and 90th percentiles of `official − pred` within bins of predicted % out.
  - `RangeModel.interval(pred) -> (lo, hi)`, clipped to [0, 1].
- `restoration_interval(county_nights, landfall: date, threshold: float = 0.10) -> tuple[float, float | None]`
  - `hi` is the first `ok` night at or below the threshold.
  - `lo` is the last `ok` night before that.
  - `(last_night, None)` means the county wasn't restored within the window.
- `pct_out_bracket(county_nights, landfall: date, hours: int) -> tuple[float, float] | None`
  - `low` is the estimate from the first `ok` night after landfall + `hours`.
  - `high` is the estimate from the last `ok` night before that time.
  - `None` means the satellite can't see.

- [ ] **Write the tests:**
  - `test_range_coverage`: 70–90% of 1,000 synthetic truths fall inside `interval`
  - `test_interval_brackets_truth_with_cloud_gaps`
  - `test_never_restored_open_interval`
  - `test_bracket_none_when_blind`
- [ ] Run the tests and expect a FAIL. Implement, then run them again and expect a PASS.
- [ ] **Commit:** `feat: ranges, restoration intervals, hour brackets`

### Task 9: Pass bar, NOAA-20 check, open the lockbox

**Files:**
- `docs/decision-log.md`, `docs/scorecard.md`, `docs/failures.md`
- `nightlights.py`, plus a test for `download_laads`

**Interface:**
- `download_laads(product: str, tile_id: str, dates: list[date], token: str, out_dir: Path) -> list[Path]`
  - Sends the same `/api/v2/content/details` query `blackmarblepy` uses: `products`, `archiveSet=5200`, `temporalRanges`, `regions` and `page`.
  - Keep TLS verification on. `blackmarblepy` turns it off when listing files.

- [ ] **Commit the pass bar first:** `docs: pass bar before lockbox`. The commit time proves the bar came first. Include the agreement rule Phase 0 showed was needed: a detrended or first-difference statistic instead of plain Spearman, dropout masking (Task 2's `flag_dropouts`, with the 2026-11-08 open questions settled), and a recovery margin. Score at ±30, ±60 and ±90, with ±60 as the headline.
- [ ] Write `test_laads_query_params` against a mocked `httpx` transport. Run it and expect a FAIL. Implement, then run it again and expect a PASS.
- [ ] **NOAA-20 check:** build Ian, Ida and Beryl with `satellite="VJ146A2"`, taking pass times from `VJ146A1`. Report how well county `pct_darker` agrees between the two satellites on the same nights, and whether Lee's peak night and 2-night recovery gap hold on NOAA-20.
- [ ] **Open the lockbox:**
  - Fit the final curve and ranges on all main storms with `final=True`.
  - Score Helene and Milton once, and put the result in the scorecard.
  - Score Uri separately as the stress test, and say beside the score that the EAGLE-I dropout constants were tuned partly on Uri (decision log, 2026-11-08).
- [ ] **Stretch, the trigger view:** take the trigger "county above 50% out at 72 hours." Count where it paid correctly, paid wrongly or missed on the locked storms. That's the basis-risk number.
- [ ] **Failure page:** write `docs/failures.md` with real cases and quicklooks: clouds, rural counties, snow during Uri, generators, and EAGLE-I errors the dropout rule misses: feed dropouts over 3 hours (DEMCO on Ida) and over-counts (Wharton on Uri, Highlands on Ian).
- [ ] **Commit:** `docs: lockbox scorecard, NOAA-20 check, failures`

## Week 6: Phase 3, export and the map

### Task 10: Synthetic portfolio, claims, export

**Files:**
- `src/blackout/{portfolio,export}.py`
- `schema/export.schema.json`
- the tests for both

**Interfaces it produces:**
- `make_portfolio(counties, n: int = 100_000, business_share: float = 0.05, seed: int = 20261105) -> pd.DataFrame`
  - Columns: `policy_id, fips, kind`.
  - Policy counts per county follow `housing_units`, drawn with `np.random.default_rng(seed).multinomial`.
- `make_claims(portfolio, official_restore: dict[str, float], n: int = 200, inflated_share: float = 0.1, seed: int = 20261105) -> pd.DataFrame`
  - Columns: `claim_id, policy_id, fips, claimed_days_out`.
- `export_storm(storm_id: str, out: Path) -> None` writes these files to `app/public/data/<storm_id>/`:
  - `counties.geojson`, whose properties include `housing_units`.
  - `nights.json`: for each fips, a list of `{night, status, est, lo, hi, official}`.
  - `restoration.json`: `{est_lo, est_hi, official_day}`.
  - `exposure.json`: `{home, business, at: {"24": [lo, hi] | null, "48": …, "72": …}}`.
  - `claims.json` and `scorecard.json`.
- CLI: `uv run blackout export --storm milton2024`, and `--sample` for the bundled Ian sample.

- [ ] **Write the tests:**
  - `test_portfolio_deterministic`
  - `test_portfolio_follows_housing`: within 1% per county
  - `test_cant_see_exports_null_not_zero`: a `cant_see` `est` and a NaN `official` both export as `null`, never `0` or `NaN` (a browser's `JSON.parse` rejects a bare `NaN`)
  - `test_export_validates_schema`, using `jsonschema`
- [ ] Run the tests and expect a FAIL. Implement, then run them again and expect a PASS.
- [ ] Export Milton and Helene.
- [ ] **Commit:** `feat: synthetic book, claims, export`

### Task 11: App shell, storm map, county card

**Files:**
- `app/`, from the Vite React TypeScript template
- `app/src/types.ts`, which mirrors `export.schema.json`
- `app/src/data/load.ts`
- `app/src/components/{StormMap,CountyCard}.tsx`
- tests next to the code

**Interfaces:**
- `loadStorm(id: string): Promise<StormData>`
- `<StormMap data night showOfficial onSelect(fips)>`
- `<CountyCard county night>`

**Decisions:**
- No basemap tiles. Draw only county polygons and state lines, so no API keys are needed.
- Hatch counties marked can't-see or not-measurable. Never color them as 0%.
- Use a color-blind-safe sequential scale.
- The night slider works from the keyboard.
- The county card shows customers out and, labeled approximate, homes out (`est × housing_units`).

- [ ] **Write the tests** (vitest with happy-dom, not jsdom):
  - `loadStorm parses the Milton fixture`
  - `CountyCard shows "can't see" for null est`
  - `range text is "41–55%" for lo 0.41, hi 0.55`
- [ ] Run `npm test` and expect a FAIL. Implement, then run it again and expect a PASS. Finish with `npx tsc --noEmit`.
- [ ] **Commit:** `feat: storm map and county card`

## Week 7: Phase 3, the portfolio example

### Task 12: Portfolio panel, claim check, flag action

**Files:**
- `app/src/lib/{exposure,claims,flags}.ts`
- `app/src/components/{PortfolioPanel,ClaimCheck}.tsx`
- the tests for each

**Interfaces it produces:**
- `expectedPoliciesOut(exposure, hours: 24 | 48 | 72): { low: number; high: number; unknownPolicies: number }`
  - Policies in can't-see counties go into `unknownPolicies`, never counted as zero.
- `claimVerdict(claimedDays: number, county: CountyNights): { verdict: "fits" | "review"; shareRestoredBefore: number }`
  - Uses the high end of the range, so flags stay fair.
  - Returns `"review"` when `shareRestoredBefore >= 0.9`.
- `loadFlags(): string[]` and `saveFlag(claimId: string): void`
  - Store them under the `localStorage` key `"bfs.flags.v1"`, wrapped in try/catch.

- [ ] **Write the tests:**
  - `exposure matches the Python toy`, using the same hand-made toy as in Task 10
  - `can't-see counties go to unknown`
  - `claim beyond 90% restored is review`
  - `claim inside the curve fits`
  - `flags survive storage throwing`
- [ ] Run the tests and expect a FAIL. Implement, then run them again and expect a PASS.
- [ ] **Rehearse the Milton walkthrough:** the map, then a county card, then the portfolio at 72 hours, then flagging one claim. It should take about a minute. If Milton was dropped for clouds, use Helene.
- [ ] **Commit:** `feat: portfolio panel, claim check, flags`

## Week 8: Phase 4, ship

### Task 13: Fresh clone, write-up, video

- [ ] **Fresh-clone check.** In a temp folder, run:

  ```
  git clone
  uv sync
  uv run pytest
  uv run blackout export --sample
  cd app
  npm ci
  npm test
  npm run build
  ```

  Fix anything that only worked because of your machine's setup.
- [ ] **CI:** add an app job that runs `npm ci`, `tsc`, `vitest` and the build.
- [ ] **README**, with these parts:
  - one line on what it is;
  - a quickstart on the sample;
  - a full run, with the `EARTHDATA_TOKEN` setup;
  - the scorecard table;
  - the limits;
  - prior art, and credit to EAGLE-I under CC BY 4.0.
- [ ] **Write-up:** `docs/writeup.md` covers the problem, the data, the method, the lockbox result, the failures and the prior art.
- [ ] **Decision log:** finish `docs/decision-log.md` in your own words.
- [ ] **Video:** record the 3-minute video, following the Milton walkthrough.
- [ ] **Ask before going public:** get the OK before pushing the repo public or hosting the app.
- [ ] **Commit:** `docs: README, write-up, video link`

**Done when:** a stranger can rerun your numbers from a fresh clone.
