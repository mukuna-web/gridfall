# Phase 0, agent `eaglei`: EAGLE-I 2022 checks (Hurricane Ian, Lee County)

Run on 2026-11-05. Source: EAGLE-I county outages for 2022 (figshare file 42547897, `eaglei_outages_2022.csv`). The download returned HTTP 200 and 1,187,596,176 bytes. I deleted the file after extracting what we need. Every query on it used DuckDB, with `fips_code` read as VARCHAR.

## Bottom line

- **`run_start_time` is naive UTC.** Confidence is high, about 95%. All the evidence comes from the data itself; I did not check EAGLE-I's documentation. Suggested value: `EAGLEI_TZ = "UTC"`.
- **A county with no outage is usually left out of a run, but sometimes appears with an explicit 0.** About 5% of rows are 0. Treat a missing county and a 0 row the same way.
- **Runs come every 15 minutes.** Only 3 national runs are missing in all of 2022, all on Oct 18–19. Between Sep 20 and Oct 20 there is no run where Florida alone is missing.
- **Lee County at 01:30 EDT** peaks at **69.13%** on local date **2022-09-29** (night of Sep 28). It first drops below 10% on **2022-10-09**, at 8.70%.
- **New risk for Task 2:** some runs drop part of a utility's feed. Florida still has rows in those runs, but its counts are about halved. The state-level "missing run" rule can't catch this (see Other observations).

## T1 Schema

- Header: `fips_code,county,state,customers_out,run_start_time`, with LF line endings and no quoting.
- DuckDB-sniffed types (`fips_code` forced to VARCHAR):
  - county, state: VARCHAR
  - customers_out: BIGINT
  - run_start_time: TIMESTAMP with no timezone, written `YYYY-MM-DD HH:MM:SS`
- Size: 25,796,465 rows, 3,057 FIPS codes, 53 state names and 35,037 run stamps. Stamps run from 2022-01-01 00:00 to 2022-12-31 23:45.
- `customers_out` runs from **min 0** to **max 456,573**. The max is Lee at stamp 2022-09-29 00:00. There are no negatives and no nulls.
- **1,280,476 rows (4.96%) have `customers_out = 0`.** They appear in every month and many states (KY 119,657; SC 119,358; GA 88,192). In the Florida extract, 15,738 of 237,276 rows (6.6%) are 0, and 10 of them are Lee rows.
- A run lists 255 to 2,548 counties (median 707) out of about 3,057. So a county with no outage is **usually just absent**, but explicit zero rows also exist. Both mean 0.
- Every `fips_code` is a 5-digit string with leading zeros kept (for example `01005`). The `12` prefix and `state = 'Florida'` mark exactly the same 1,133,359 rows.
- No `(fips_code, run_start_time)` pair appears twice anywhere in 2022.

## T2 Cadence

- **Yes, every 15 minutes.**
  - 35,037 of the 35,040 expected stamps are present, all exactly on :00, :15, :30 or :45.
  - Gaps between consecutive runs: 35,034 of 15 minutes, one of 30 minutes and one of 45 minutes.
- **Missing nationally in 2022-09-20 00:00 – 2022-10-20 23:45** (2,976 stamps expected): `2022-10-18 23:15`, `2022-10-19 00:15`, `2022-10-19 00:30`. These are the only 3 missing stamps in all of 2022.
- **Missing for Florida only** (no Florida rows while other states have rows): **none**. All 2,973 national runs in the window have 15 to 63 Florida rows (median 39).

## T3 Timezone: UTC

**a) DST start, 2022-03-13.** There are **4 runs stamped 02:00, 02:15, 02:30 and 02:45**, with 770, 762, 739 and 730 rows. They continue smoothly from 01:45 (785 rows) to 03:00 (716 rows). That day has 96 runs, the same as Mar 12 and Mar 14. A US wall-clock time would skip this hour, so the stamps are not US local time.

**b) DST end, 2022-11-06.** **No** `(fips_code, run_start_time)` pair repeats between 01:00 and 01:59, or anywhere else that day. Nov 5, 6 and 7 each have 96 runs, and row counts move smoothly (1,011 → 968). This fits UTC. It is weaker evidence than (a), because the file has no repeated pairs anywhere, so it may have been deduplicated upstream.

**c) July 2022 diurnal cycle.**
- Group: FL, GA, SC, NC, VA, NY, PA and OH. From Florida I dropped the Central-time panhandle: 12005, 12013, 12033, 12045 (Gulf, which is split between zones), 12059, 12063, 12091, 12113, 12131 and 12133.
- Every stamp hour has 124 runs.
- **The sum peaks at stamp hour 22**: 5.14 M customer-runs, or 41,484 per run. The trough is at hour 10 (18,594 per run), and the steepest rise is at hour 20.
- Read as UTC, that is a **peak at 18:00 EDT**, a trough at 06:00 and the steepest rise at 16:00, which is typical afternoon-thunderstorm timing. Read as local time, the peak would be at 22:00.
- Check across time zones: other regions peak later in stamp hours the further west they are. Central peaks at 01, Mountain at 01 and Arizona at 04. As UTC those are 20:00 CDT, 19:00 MDT and 21:00 MST, all evenings. As local time they would be peaks at 1–4 am, which is implausible. The Pacific group (stamp 17) isn't driven by thunderstorms and tells us nothing.

**d) Ian in Lee County.**
- Inputs: MCC count 628,635. Sep 27–29 has 288 Florida runs, none missing, and Lee appears in all of them.

| Threshold | First stamp | Customers out | Read as UTC (EDT) |
|---|---|---|---|
| 10% | 2022-09-28 15:15 | 72,761 | 11:15, 3.8 h before landfall |
| 50% | 2022-09-28 18:45 | 328,648 | 14:45, 20 min before landfall |
| 80% | never reached | – | the peak is 456,573 (72.63%) at stamp 09-29 00:00, 20:00 EDT |

- Read as UTC, the surge matches hurricane-force winds arriving from late morning to early afternoon, with landfall at 15:05 EDT.
- Read as local time, Lee would cross 10% only after landfall, about 4 hours too late. The plan's own test says a surge about 4 hours late means UTC.

**Conclusion: UTC, about 95% confidence.**
- (a) rules out a wall-clock US time.
- (c) and (d) each rule out a fixed Eastern offset (EDT or EST) and fit UTC.

## T4 MCC.csv

- The file starts with the bytes **EF BB BF (a UTF-8 BOM)**, uses CRLF line endings, and its header is `County_FIPS,Customers`.
  - Python's `csv` module reading it as `utf-8` returns the header `'﻿County_FIPS'`.
  - `utf-8-sig`, pandas and DuckDB all strip the BOM.
- The file has 3,234 rows: 3,233 counties plus a final **`Grand Total,154451840`** row. That total equals the sum of the county rows. Drop this row before `zfill`.
- **County_FIPS is unpadded:** 312 codes have 4 characters (for example `1001`) and 2,921 have 5. No codes repeat after `zfill(5)`.
- Customer counts: **Lee 12071 = 628,635; Charlotte 12015 = 129,889; Collier 12021 = 288,895.**
- **All 67 Florida counties are present** after padding. The set matches the expected one exactly: the odd codes 12001–12133 without 12025, plus 12086. There are no extra codes.
  - Florida's MCC total is 11,192,057.
  - All 67 codes also appear in the Florida outage extract.

## T5 Coverage

- `coverage_history.csv` stores the year as `1/1/YY` and only covers **2018–2022**.

Florida rows:

| Year | total_customers | min_covered | max_covered | min_pct | max_pct |
|---|---|---|---|---|---|
| 2018 | 10,166,667 | 8,784,000 | 9,867,767 | 0.86 | 0.97 |
| 2019 | 10,505,702 | 9,557,234 | 10,171,381 | 0.91 | 0.97 |
| 2020 | 10,648,830 | 10,069,752 | 10,365,852 | 0.95 | 0.97 |
| 2021 | 10,845,961 | 9,602,281 | 10,593,085 | 0.89 | 0.98 |
| 2022 | 10,989,517 | 10,562,475 | 10,768,409 | 0.96 | 0.98 |

`DQI.csv` rows for FEMA region 4:

| Year | success_rate | percent_enabled | spatial_precision | cust_coverage | max_covered | total_customers | DQI |
|---|---|---|---|---|---|---|---|
| 2018 | 98.86 | 98.12 | 78.19 | 85.27 | 27,610,605 | 32,378,544 | 74.67 |
| 2019 | 98.79 | 86.90 | 71.37 | 89.22 | 29,304,643 | 32,846,895 | 65.05 |
| 2020 | 98.70 | 99.56 | 76.82 | 90.14 | 30,044,515 | 33,332,659 | 77.49 |
| 2021 | 99.46 | 99.06 | 76.92 | 90.77 | 30,614,057 | 33,726,323 | 85.16 |
| 2022 | 98.93 | 98.15 | 76.74 | 91.24 | 31,073,335 | 34,058,092 | 79.17 |

Notes:
- The 2023 and 2024 storms (Idalia, Beryl, Helene, Milton) will need the 2022 fallback.
- The coverage file's Florida customer total for 2022 (10,989,517) is 1.8% lower than MCC's Florida total (11,192,057). The two files use different denominators.

## T6 Lee County % out at 01:30 local, Sep 20 – Oct 20

- **Method.**
  - Target: 01:30 EDT, which is **05:30 UTC**, on each local date D. The night label is D − 1.
  - Pick the latest run at or before the target that has Florida rows. If Lee is absent from that run, count it as 0.
  - Every one of the 31 days had an exact 05:30 run with Florida rows and a Lee row, so no lag, zero-fill or NaN was needed.
- **Peak: 69.13% (434,591 customers) on 2022-09-29**, the night of Sep 28.
  - Before the storm, Sep 20–28, the value stays below 0.11% (0.103% on Sep 28).
  - The day-by-day series after the peak: 65.49 → 56.61 → 49.93 → 46.22 → 35.12 → 31.78 → 23.50 → 17.99 → 10.09 (Oct 8).
- **First date below 10%: 2022-10-09, at 8.70% (54,683 customers).** By Oct 20 the value is 1.89%.
- **Robustness.**
  - Taking the median of the Florida runs within ±30 minutes changes no day by more than 0.006 points.
  - If the stamps were Eastern time instead, no day would move by more than 3.51 points (Oct 2), and the peak and recovery dates would stay the same.

## Other observations

1. **Some runs drop part of a utility's feed.**
   - Between stamps 2022-09-29 09:15 and 10:45 UTC (7 runs), Florida's total fell from 2.36 M to 1.16–1.25 M. Over the same runs:
     - Lee: 421,246 → 175,4xx
     - Charlotte: 117,128 → 808
     - Collier: 202,817 → 26,707
     - Manatee: 137,760 → 0 (an explicit zero row), then 34,315
   - Everything was back at 11:00.
   - There was also a one-run dip at 2022-09-28 21:00: Lee went 414,811 → 343,844 → 402,780.
   - Florida had rows in all of these runs, so the state-missing → NaN rule doesn't catch them. The T6 picks at 05:30 UTC are not affected. Task 2 may want a guard for this, such as the median of nearby runs.
2. Florida rows in the extract are stamped in UTC, from Aug 20 00:00 to Oct 25 23:45 (Aug 19 20:00 to Oct 25 19:45 EDT).

## Unverified

- I did not check EAGLE-I's documentation of `run_start_time`. The UTC conclusion comes from the data alone.
- That the Sep 29 drop is a lost utility feed is an inference, not something I confirmed.
- The times hurricane-force winds reached Lee come from the task brief, not from NHC.

## Files and reruns

All paths are relative to the repo root.

| File | What it is |
|---|---|
| `scripts/phase0/eaglei_extract.py` | Writes the two parquet files. Checks the header first. |
| `scripts/phase0/eaglei_checks_fullcsv.py` | T1 and T3a–c. Needs the CSV. Writes `data/interim/eaglei_fullcsv_checks.json`. |
| `scripts/phase0/eaglei_checks_extracts.py` | T2, T3d, T4, T5 and T6. Writes `data/interim/eaglei_lee_0130_series.csv` and `data/interim/eaglei_extract_checks.json`. |
| `data/interim/eaglei_fl_2022-08-20_2022-10-25.parquet` | 237,276 rows covering 67 counties |
| `data/interim/eaglei_2022_runs.parquet` | 35,037 runs: `run_start_time`, `n_rows`, `n_counties`, `total_customers_out` (BIGINT) |

Before deleting the CSV, I checked the extracts against it:
- The CSV's 25,796,465 rows, summing to 4,971,843,138 customers out, match the run summary's `sum(n_rows)` and `sum(total_customers_out)`.
- The Florida filter applied straight to the CSV gives 237,276 rows, a sum of 837,639,545 and 67 FIPS codes. That matches the Florida parquet exactly.

`uv run ruff check` passes on all three scripts.

To rerun, download the CSV again, then:

```
uv run python -I scripts/phase0/eaglei_extract.py
uv run python -I scripts/phase0/eaglei_checks_fullcsv.py
uv run python -I scripts/phase0/eaglei_checks_extracts.py
```

---
**Update 2026-11-06 (orchestrator): T6 is superseded.**
- T6 read Lee's outages at 01:30 EDT (05:30 UTC). The satellite actually passes near 01:30 local *solar* time, about 07:00 UTC over Lee.
- `scripts/phase0/ian_lee.py` now takes EAGLE-I at each night's real pass time: VNP46A1 `UTC_Time`, or the solar-time fallback.
- So `data/interim/eaglei_lee_0130_series.csv` is only a historical check. The T1–T5 findings (UTC clock, explicit zeros, `MCC.csv` quirks, coverage, feed dropout) still hold.

**Update 2026-11-07 (verification workflow): T3d overstates.**
- Read as New York time, Lee's 10% crossing (stamp 15:15) is 10 minutes after the 15:05 EDT landfall, not "about 4 hours late".
- The UTC call still holds, because of the runs inside the skipped daylight-saving hour and the Uri onset at 07:25 UTC.
- The verification also found a second, partial feed dropout at 07:00–07:15 UTC on 2022-09-30, with Lee at 240,270 against about 411,600 on either side.
