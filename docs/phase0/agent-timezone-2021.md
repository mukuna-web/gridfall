# EAGLE-I clock check on the 2021 file

*Phase 0 agent note (Claude), 2026-11-05. This is an independent cross-check of the 2022 timezone tests. It uses a different year and different events. All times in the tables are the file's own `run_start_time` stamps (the "file clock").*

**Verdict: `run_start_time` is UTC. Confidence: high.**

All five tests agree. Tests (a) and (b) rule out any US wall clock, whether one zone for everyone or each county's own zone. Tests (c) to (e) put the offset from UTC at 0 hours. Uri pins it to within one 15-minute run.

## Source

- `eaglei_outages_2021.csv` from figshare article 24237376 (`https://ndownloader.figshare.com/files/42547891`), 1,141,058,232 bytes. The MD5 `b5a5912be793ca22dddcc73ca2c3379d` matches the article's file list. I read it with DuckDB, with `fips_code` as VARCHAR, and deleted it after cutting the extracts.
- The file has 24,826,102 rows and 34,926 runs (2021 has 35,040 15-minute slots). The first stamp is 2021-01-01 00:00. The last is 2021-12-31 00:00. There are 3,045 FIPS codes, all 5 digits, in 53 states and territories. No `(fips_code, run_start_time)` key appears twice anywhere in the file.
- Every stamp is plain `YYYY-MM-DD HH:MM:SS` (19 characters), with no offset, `Z` or zone name. So the clock can only be found from the data.

## Results

The three hypotheses are:

- **UTC**
- **US Eastern**: one EST/EDT wall clock for all counties.
- **County local**: CST/CDT for Texas and Louisiana.

| Test | Local wall clock would show | File shows | Points to |
|---|---|---|---|
| (a) DST start, 2021-03-14 | no runs at 02:00–02:59 | 4 runs (02:00, :15, :30, :45) with 1,884 rows from 548 counties in 50 states. 1,840 of those rows are in DST-observing states. | not local |
| (b) DST end, 2021-11-07 | 01:00–01:59 repeated, so duplicate keys and about 8 rows per county | 0 duplicate pairs, 4 runs, 3.42 rows per county (3.35 and 3.63 on the days either side) | not local |
| (c) Uri, Texas | onset near 01:25 (CST) or 02:25 (EST) | flat until 07:15, then +1.15 M in the 2 h after 07:25 | UTC |
| (d) Ida, Orleans | fully dark at 18:00–19:30 (CDT) or 19:00–20:30 (EDT) | 48% or 61% of peak at those times; 99% of peak by 00:30 | UTC |
| (e) July diurnal, Eastern states | peak at 17–20 | peak at 22–00 (18–20 EDT if UTC) | UTC |

### (a) and (b): DST days

- **Every hour has its 4 runs.** All 24 hours on 2021-03-13/14/15 and 2021-11-06/07/08 have 4 runs each, so each of those days has 96 runs.
- **No hour is skipped or repeated anywhere on those days.** This also rules out local stamps that were converted to UTC with one fixed offset. That conversion would leave a gap at 07:00 on 03-14 and duplicates at 06:00 on 11-07.

| Day | 02:00–02:59 runs | Rows | States |
|---|---|---|---|
| 2021-03-13 | 4 | 2,009 | 51 |
| **2021-03-14** | **4** | **1,884** | **50** |
| 2021-03-15 | 4 | 2,419 | 53 |

| Day | 01:00–01:59 rows | Duplicate pairs | Rows per county |
|---|---|---|---|
| 2021-11-06 | 2,098 | 0 | 3.35 |
| **2021-11-07** | **1,865** | **0** | **3.42** |
| 2021-11-08 | 3,129 | 0 | 3.63 |

### (c) Winter Storm Uri: total Texas `customers_out` (FIPS 48)

The window is 2021-02-14 18:00 to 2021-02-15 18:00. There are 97 slots and none is missing. Each run has 148 to 222 Texas counties.

- **Before the order.** From 18:00 to 23:45 the total is 53,217–77,670 (median 62,660). From 00:45 to 07:15 it holds at 97,650–152,242.
- **The order.** ERCOT ordered rotating outages at 01:25 CST, which is 07:25 UTC.

| Hypothesis | Onset in file clock | Value at onset | 2 h later | Change |
|---|---|---|---|---|
| **UTC** | 07:25 | 136,038 | 1,289,854 | **+1,153,816** |
| US Eastern | 02:25 | 113,106 | 129,431 | +16,325 |
| County local | 01:25 | 118,855 | 127,845 | +8,990 |

Runs on 02-15:

| Run | 07:00 | 07:15 | 07:30 | 07:45 | 08:00 | 08:15 | 08:30 | 08:45 |
|---|---|---|---|---|---|---|---|---|
| Texas out | 135,659 | 136,038 | 151,110 | 263,493 | 371,525 | 729,331 | 982,732 | 1,346,195 |

- **Onset.** The first 15-minute step above 50,000 is 07:30 → 07:45 (+112,383). The steepest hour is 07:45 → 08:45 (+1,082,702). All five of the largest 1-hour rises end between 08:15 and 09:15.
- **Lag.** The rise starts in the 07:30 run, the first after 07:25 UTC (+15,072, after +379 in the run before). The first big step comes in the next run, 07:45. So any reporting lag behind ERCOT's order is at most about 20 minutes.
- **Peak.** The window peaks at 2,799,858 at 17:30.

### (d) Hurricane Ida: Orleans Parish (22071)

The window is 2021-08-29 00:00 to 2021-08-30 12:00.

- **Gaps.** One run is missing (08-29 23:00). In 17 slots, from 00:00 to 04:15 on 08-29, Orleans has no row while Louisiana reports, so those count as 0. No Orleans row has an empty `customers_out`.
- **Peak.** The window peak is 177,546, at 08-30 07:15.

| Run | 12:00 | 12:45 | 15:00 | 16:45 | 18:00 | 19:30 | 20:30 | 22:45 | 23:15 | 23:30 | 23:45 | 00:30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Orleans out | 478 | 2,428 | 18,735 | 29,078 | 52,629 | 84,432 | 107,903 | 147,721 | 158,113 | 162,827 | 175,435 | 176,127 |

- **The count climbs and then levels off.** Orleans climbs steadily from 12:45 and levels off at 23:45. It first reaches 50% of peak at 19:45, 90% at 23:30 and 98% at 23:45.
- **Under UTC the timeline fits the reports.** Read as UTC, the climb starts at 07:45 CDT, about 4 hours before the 11:55 CDT landfall. The city is fully out by 18:45 CDT, which matches the early-evening loss of all power.
- **Share of peak in each hypothesis's dark window** (the reported 23:00–00:30 UTC, shifted):

| Hypothesis | Dark window in file clock | Share of peak at start | Share of peak at end |
|---|---|---|---|
| **UTC** | 23:00–00:30 | 0.83 (from the 22:45 run; 23:00 is missing) | **0.99** |
| US Eastern (EDT) | 19:00–20:30 | 0.44 | 0.61 |
| County local (CDT) | 18:00–19:30 | 0.30 | 0.48 |

### (e) July 2021 diurnal cycle: GA, SC, NC, VA, NY, PA, OH

All counties in these states are on Eastern time, so "US Eastern" and "county local" predict the same thing here. The data has 2,975 runs, with one run missing in hour 19, and 662,689 rows.

| Measure | Peak hour (file clock) | Low hour |
|---|---|---|
| Total `customers_out` by hour | **00** | 17 |
| Mean per run | **00** (35,334) | 17 (16,064) |
| Median day | **22** | 08 |
| Without Tropical Storm Elsa (Jul 7–10) | **23** | 17 |
| Hour of each day's peak | **00** on 10 days, 22 on 7, 23 on 6, 20 on 3 (26 of 31 days fall in 20–00) | — |

- **The cycle.** The mean per run rises steeply from 17,135 at hour 18 to 35,334 at hour 00.
- **Read as UTC,** that is a climb from 14:00 to 20:00 EDT and a peak at 18–20 EDT, which is the usual pattern of afternoon thunderstorm outages.
- **Read as Eastern time,** outages would bottom out at 5 pm and peak around midnight.

## Data notes for later weeks

- **Empty counts.** 1,104,738 rows (4.4%) have an empty `customers_out`. DuckDB reads these as NULL. They are spread across all months and many states, with Texas, North Dakota and Minnesota highest. They must stay "unknown", never 0. The windows tested here are barely affected:
  - Uri, Texas: 143 of 18,058 rows
  - Ida, Orleans: 0 rows
  - July, Eastern states: 7,706 of 662,689 rows
- **End of year.** The file ends at 2021-12-31 00:00, so 2021-12-31 00:15–23:45 (95 slots) is missing. Another 20 slots are missing across the rest of the year.
- **Off-grid run.** One run is stamped off the 15-minute grid, at 2021-10-21 05:16 (498 rows).
- **Matching the ~01:30 local pass.** Convert local time to UTC for each county. For example, 01:30 EDT in Lee County is 05:30 in the file, 01:30 CDT in Louisiana is 06:30, and 01:30 CST in Texas in February is 07:30.

## Files

- `scripts/phase0/tz2021_checks.py` runs tests (a) to (e).
- `scripts/phase0/tz2021_extract.py` cuts the two extracts and checks them against the CSV: rows, NULL count, `customers_out` sum, counties, runs, first and last stamps, 5-digit FIPS and duplicate keys. Both passed.
- The extracts keep the stamps exactly as in the file (UTC, per the verdict above). Empty `customers_out` stays NULL. The Parquet key-value metadata records the source URL, MD5 and filter.

| Extract (in `data/interim/`) | Filter (file clock) | Rows | NULL counts | Counties | Runs |
|---|---|---|---|---|---|
| `eaglei_2021_uri_TX_2021-01-20_2021-03-10.parquet` | FIPS 48; [2021-01-20, 2021-03-11) | 372,792 | 8,325 | 253 | 4,796 |
| `eaglei_2021_ida_LA_MS_2021-08-01_2021-09-30.parquet` | FIPS 22 or 28; [2021-08-01, 2021-10-01) | 300,494 | 2,270 | 143 (LA 64, MS 79) | 5,854 |

The Uri and Ida numbers above can be recomputed from these extracts, and I checked that they match. Tests (a), (b) and (e) need the national file. To rerun them, download it again (URL and MD5 above) into `data/raw/eaglei_2021/` and run the checks script:

```
uv run python -I scripts/phase0/tz2021_checks.py --json-out <path>
```

## Limits

- I took the reference times (ERCOT 01:25 CST; Ida landfall 16:55 UTC; New Orleans dark about 23:00–00:30 UTC) from the task brief. I did not re-check them against primary sources.
- The conclusion does not depend on their exact values. The Texas series is flat around both local-time onsets. In the windows the local-time hypotheses predict, Orleans is at most 61% of its peak.
