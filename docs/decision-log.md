# Decision log

One entry per call that shapes the project, newest last. Write the reason, not just the choice.

*Claude drafted the first two entries from the planning chat. An entry whose heading names Claude ("Claude's call", "Claude's notes", "Claude's findings") is Claude's, made on the author's behalf and logged here for the author to review; "override any" in a heading is addressed to the author (see "Who writes Weeks 2–8"). The commits this log cites are in the private development archive, not in the public repository: see the entry of 2026-11-11.*

## 2026-11-05: Project setup

- **A worked example.** The app joins the county estimates to a synthetic insurance portfolio and synthetic claims, as an illustration of what the numbers can answer. (Chosen by me.)
- **Customers are the main unit.** EAGLE-I counts meters, so homes are only a conversion through Census housing units.
- **Satellites.** Suomi NPP (`VNP46A2`) is the main source for 2018–2024. NOAA-20 (`VJ146A2`) is the cross-check, because Suomi NPP stopped sending data on Nov 1–2, 2026.
- **Lockbox.** Helene and Milton (2024) stay untouched until the pass bar is committed.

## 2026-11-05: Who wrote the Week 1 code

- I asked Claude to run Week 1 (Phase 0) autonomously. The scripts in `scripts/phase0/` and the Phase 0 notes were written by Claude.
- They are a throwaway by-hand check. From Week 2 on, I write the tested code in `src/blackout/` myself, and Claude reviews it.

## 2026-11-06: Phase 0 calls, made before any satellite file was downloaded (Claude's calls; override any)

**What "the two lines move together" means.** This was decided before looking at the data.

- Use only nights after landfall where the county is visible (status `ok`, file dates Sep 29 – Oct 19).
- **Peak timing:** the darkest night is within one night of the night with the highest official % out.
- **Recovery timing:** the first night "% darker" falls below half its peak is within 2 nights of the first night the official % out falls below half its peak.
- **Same direction:** with at least 5 visible nights after landfall, the rank correlation (Spearman) between the two series is at least 0.6. Pearson's r would overstate agreement, because both series simply decay over time.
- **Verdict:**
  - *Pass* if peak timing and recovery timing hold, and same direction holds whenever it can be computed.
  - *Inconclusive, too cloudy* if fewer than 3 nights after landfall are visible.
  - *Fail* otherwise.
- **Noise check:** report "% darker" on the visible baseline nights before the storm, where it should sit near 0.
- The two lines are not expected to match in size. "% darker" measures light and "% out" measures meters. This rule compares timing and direction, not size.

**Pass time.**
- Suomi NPP passes near 01:30 local *mean solar* time, which is about 07:00 UTC over Lee County. The plan's original "01:30 on the clock" was about 1.5 hours early.
- The exact per-night time comes from the `UTC_Time` layer in VNP46A1. The fallback is 01:30 local solar time at the county's longitude.

**Other choices.**
- **EAGLE-I clock = UTC.** Evidence:
  - The data paper says so.
  - The 2022 and 2021 files both have runs during the missing daylight-saving hour.
  - Texas's rolling blackouts appear at 07:25, matching ERCOT's 01:25 CST order.
  - Summer storm outages peak at about 18:00 Eastern.
- **EAGLE-I value** = the median of the runs within ±60 minutes of the pass. Scrapers time out during storms; Florida had a feed dropout on 2022-09-29, 09:15–10:45 UTC.
- **Baseline** = file dates Aug 26 – Sep 25, 2022, both ends included (31 files: the 30-night window ending 3 days before landfall, counted inclusively).
- **"Dark" threshold for check 4** = % darker above 0.3.
- **Clear pixel** = `Mandatory_Quality_Flag` 0, cloud bits "confident" or "probably" clear, and no snow. In Collection 2, flag 1 means poor quality, not good.

## 2026-11-07: After the Phase 0 run (Claude's notes; the logged rule above is unchanged)

- **Result: PASS under the logged rule, but marginal.**
  - The recovery gap is exactly 2 nights.
  - A ±30-minute EAGLE-I window fails, because of an unrecorded feed dropout at 07:00–07:15 UTC on 2022-09-30.
  - Details are in `docs/phase0.md`.
- **Correction to the Spearman reasoning.**
  - Rank correlation does not avoid the shared-decay problem: EAGLE-I against time alone scores 0.996.
  - After removing each series' decay, the correlation is −0.06.
  - For future storms, use a detrended or first-difference agreement statistic.
- **Baseline wording.**
  - "30 nights ending 3 days before landfall" was implemented as file dates Aug 26 – Sep 25 (31 files, inclusive).
  - Read as nights instead, the verdict still passes (Spearman 0.789).
- **Before opening the lockbox (Task 9), log the replacement rule here.** It should cover:
  - a detrended or first-difference agreement statistic;
  - dropout masking;
  - angle and moon correction;
  - a recovery margin.

  Ian must not be re-scored under the new rule and called a new pass.

## 2026-11-08: EAGLE-I dropout rule (Claude's call; override any)

**Rule.** When EAGLE-I's scraper loses one utility's feed, that utility's counties drop in the same run and come back a few runs later, so the state's total makes a short V. `flag_dropouts` (Task 2) looks for that V in each state's 15-minute runs:
- the total falls below 0.93 of a level held for two runs;
- it recovers to 0.93 or more within 3 hours of the run before the dip, and stays there one more run;
- a county takes part only if it is already below 0.93 of its shoulder in the V's first run (its shoulder is its smallest value in the two runs before the V and the two after);
- if those counties explain at least half the state's fall, their low runs are dropped before the median; otherwise nothing is;
- the walk then continues after the V.

Absent counties read 0. Empty counts read 0 only while looking for dips and never enter the median. This replaces the plan's one-line rule, which flagged none of Lee's 7 bad runs on 2022-09-29 because its hour medians sat inside the dip (175,437 and 175,478.5 at 10:00).

The utility names below (TECO, Duke, CenterPoint, DEMCO, CTEC) are inferred from which counties drop together. EAGLE-I rows have no utility field (see `utility_attribution` in the census file).

**How it was chosen.** Three designs were tried on the full Ian, Ida and Uri extracts, and a judge merged them. An adversarial check then found two problems. First, the merge dropped real changes: during one Uri dip caused by Houston's feed, it also flagged 20 counties far from Houston. Second, at 0.92 it missed three short DEMCO dips on Ida and Houston's dip at 2021-02-16 14:45. The first-run test (step 5) fixed the first problem, and 0.93 in place of 0.92 fixed the second, at the cost of six new riders at 14:45 (see `DIP_RATIO`). Two independent rebuilds written from the Task 2 text alone then reproduced every Task 2 test value exactly, and a second adversarial check found the final rule sound, with the limits listed below. The 100 labelled dip events behind the counts are in `docs/phase0/eaglei-dip-census.json`.

**Parameters.** "Fixes" and "unexplained changes" are county ±60 medians that the flags move by at least 1,000 customers and 10%, or turn to NaN. They were counted in five windows:
- Ian's ramp, 2022-09-28 18:00 to 09-29 06:00;
- Ian's restoration, 09-30 00:00 to 10-10 23:45;
- Ida in Louisiana and in Mississippi, 2021-08-29 10:00 to 08-31 23:45;
- Uri's rotating outages, 2021-02-15 07:25 to 02-19 12:00.

A change counts as a fix if every flag within ±60 minutes of it sits on one of three things: an absent or empty cell; a stuck reading (Hillsborough 1,210 or 1,214; Harris 2,908–2,915; St. Helena 1,684–1,705 or 1,120; Charlotte 125,478); or a county named in one of the 100 labelled events, while that event lasts (81 feed artifacts, 7 real, 12 unclear). The windows skip 2022-09-29 06:00 to 09-30 00:00, Ian's busiest day for feed failures. "Quiet time" below means outside Ian 2022-09-27 to 10-15, Ida 2021-08-28 to 09-10 and Uri 2021-02-13 to 02-21.

- `DIP_RATIO = 0.93`.
  - It sits just above the shallowest short dropout found. Ida's five DEMCO dips (the same stuck St. Helena reading each time) take Louisiana to 0.915–0.923 of its level, and Uri's CenterPoint dip at 2021-02-16 14:45 takes Texas to 0.921. 0.92 missed three of those dips and 14:45.
  - At 0.94, Ian's ramp gets 2 unexplained changes (0 at 0.93), its restoration 2 (1 at 0.93), and Ida Mississippi's fixes vanish (4 → 0). At 0.95 the recoveries of Sep 30 (0.947) and Uri's 2.5-hour CenterPoint pair (0.941) fail.
  - Cost: 0.93 also flags six rotating counties far from Houston at 2021-02-16 14:45. That takes Uri's unexplained changes from 21 (the first-run rule at 0.92) to 28. It also loses dips that recover only to 0.92–0.93, such as CTEC on 2021-02-19 21:15 (0.9266).
- `MAX_DIP = 3 h`, from the run before the dip to the first recovered run, exactly 3 hours included.
  - Ian's dropout 1 needs 2 h (it is lost at 1.5 h).
  - Uri's back-to-back CenterPoint dropouts on 02-16 (15:45–17:45, with a one-run recovery at 16:45) need 2.5 h. At 2 h, Uri's fixes fall from 63 to 31.
  - Longer limits only add unexplained changes in quiet times (Louisiana: 27 at 3 h, 65 at 4 h).
- `FEED_SHARE = 0.5`. Values from 0.5 to 0.8 give identical storm-window results. Much lower values let unrelated churn through, as in window G of the Task 2 fixture, and 0.9 loses Harris at 02-16 06:00.
- `HOLD_RUNS = 2`, a fixed definition. With 1, one-run spikes count as levels (Uri's unexplained changes 28 → 97). With 3, TECO at 2022-09-29 11:30, the Uri pair and nearly all Ida fixes are lost.
- First-run test (step 5). The earlier draft flagged every county that was low anywhere in the V, so it also dropped real changes in the middle of the V. In Uri's 15:45–17:45 dip it flagged 26 counties, 20 of them far from Houston (Garza, Williamson, Blanco and others); the final rule flags 7, all around Houston. At 0.93 the test cuts Uri's unexplained changes from 36 to 28, and quiet-time Florida's from 33 to 11. Its costs are under "Missed" below.

**Uri was used for tuning.** The plan says to tune cutoffs on training storms only. But Uri, the stress test, helped pick all four constants; for example, 0.93 was chosen partly to catch the 14:45 dip. Task 9's Uri score must say so. Only three storms were used: Ian 2022 (Florida, Aug 20 – Oct 25), Ida 2021 (Louisiana and Mississippi, Aug–Sep) and Uri 2021 (Texas, Jan 20 – Mar 10). No 2024 EAGLE-I or Black Marble data was opened.

**What it catches.**
- Both known Ian dropouts: Lee in all 7 runs of 09-29 09:15–10:45, and Lee and Collier at 09-30 07:00–07:15.
- Other Ian dropouts: TECO at 09-29 11:30; Lee at 09-30 13:45, 10-01 13:45–14:00, 10-01 20:45–21:30, 10-04 07:45 and 10-16 03:45; Pinellas at 09-29 19:45–21:15.
- All 8 CenterPoint-type Harris dips on Uri.
- Nothing is flagged on 2021-02-15, the first day of rotating outages.
- At Lee's 57 Phase 0 pass times, only two passes change. File date 2022-09-27 (night Sep 26) moves by half a customer at ±90 (118.5 → 119.0). File date 2022-09-30 (night Sep 29) moves from 325,973 to 411,676 at ±30, from 409,085.5 to 411,615 at ±60 and from 409,094 to 411,614.5 at ±90. The earlier draft gives the same values at all 57 passes.

**Known limits.**
- *Missed:*
  - Dropouts over 3 hours:
    - TECO 2022-09-29 15:15–21:45 (Hillsborough stuck at 1,210–1,214);
    - Lee 2022-10-03 20:15–23:30;
    - DEMCO 2021-08-30 02:15–11:30 (38 runs) and 08-31 17:15 to 09-01 22:15 (117 runs, St. Helena stuck at 1,694). The DEMCO pair covers Ida's passes on file dates 2021-08-30 and 09-01. There Livingston reads about 20,200 and 20,700, against 43,827 before the first dropout and 46,213 after it.
  - Dropouts in a steep ramp, or too small to move the state's total: TECO 2022-09-28 18:30–23:30 (Hillsborough's ±60 stays 1,214); Hardee's zeros at 2022-09-30 05:45 and 07:45; Seminole's share of dropout 1.
  - A second feed failing inside a V that another feed opened.
    - If it is the smaller loss, only it is missed: TECO at 2022-09-30 14:00–14:15, inside the dip Lee and Collier opened at 13:45.
    - If it is the larger, the whole V fails the share test and both feeds are missed. On 2022-09-29 22:30–23:00, TECO opens the V and Duke fails at 23:00 (share 0.33), so Hillsborough's ±60 at 22:15 stays at the stuck 1,214 instead of about 148,900.
  - Counties not yet low in the V's first run: Dixie, Gilchrist and Levy (a separate one-run drop at 09-29 10:45), and Suwannee, all in dropout 1. Of dropout 1's 162 deep county-runs (below 75% of min(09:00, 11:00)), 154 are flagged; the 8 misses move a ±60 value by at most 9.5 customers.
- *Wrongly flagged (riders):* real changes that happen to dip in a V's first run.
  - Citrus, 2022-09-29 09:15–09:45: its ±60 at 10:07:30 moves from 1,986 to 4,279.
  - About 20 rotating Texas counties during Uri's CenterPoint dips on 02-16 (06:00, 12:45–13:00, 14:45, 18:30–18:45). For example, ±60 values move by 1,183 for Hopkins and 979 for Grimes.
- *Side effects:*
  - Over-counts. From Uri 02-16 19:00, Wharton, Austin, Waller and Brazoria read 2–8 times their MCC customers, so dropping their true 18:30–18:45 runs puts the ±60 median on the over-count (Wharton at 18:45: 4,640 → 121,949). Ian has over-counts too: Highlands reads 1.2–1.3 times its MCC customers at Lee's pass times on 2022-09-29 and 09-30.
  - A small state with no outages anywhere has no rows in a run, so that run reads as missing, not 0. These extracts never hit it (fewest rows in a live run: Florida 15, Louisiana 6, Mississippi 5, Texas 13).
  - Reading empty counts as 0 while looking for dips was checked only on 2021. Some empties bunch in failed runs (Louisiana 2021-08-30 16:00–19:00: all 82 fall at 17:30 and 18:30), but across the extracts only 44% of Louisiana's, 47% of Texas's and 16% of Mississippi's empty counts sit in runs with 10 or more empties. Before relying on it, compute the same share for the 2018–2020 and 2023 files and Beryl's 2024 rows, and compare (Task 5).

**Open questions for you** (settle and log before Task 5 builds the storms, unless noted):
1. Ida's long DEMCO dropouts sit on two pass nights. Mark the DEMCO parishes unusable on those nights, add a stuck-value check later, or accept and log?
2. Over-counts (Uri's Wharton, Ian's Highlands): accept, or exclude county-nights where EAGLE-I reads above MCC? A plain cap at MCC is not simple: 3,513 Louisiana and 6,334 Texas county-runs in these extracts exceed MCC.
3. The 0.8 coverage cutoff leaves out Mississippi (0.77), Texas in 2020 (0.63), Alabama in 2018 (0.79) and Tennessee in every year. Keep it, or lower it for those states and log why?
4. Riders: accept them as logged? Requiring each county to come back near its pre-dip level would remove them, but it also wipes out Uri's 2.5-hour Houston pair and cuts dropout 1's flagged deep runs from 154 to 133.
5. Week 2 grew from 16 to 34 tests. Keep them all in Week 2, or move the six tests under "Synthetic frames" to Week 3, where they must pass before Task 5 builds the storms? (Decide now.)
   - **Answer (2026-11-08, Claude's call under the entry below):** all 34 stay in Week 2. They are short, and they are the only tests that pin the rule's edges.

## 2026-11-08: Who writes Weeks 2–8

- I asked Claude to finish the whole plan autonomously, as fast as possible, without stopping for approvals. So from Week 2 on, Claude writes the code in `src/blackout/`, `tests/` and `app/`, and I review it. This reverses the 2026-11-05 entry above.
- The limits that still hold: nothing is pushed or hosted without my OK, the Earthdata token is never printed or saved by Claude, the lockbox stays shut until the pass bar is committed, and every call Claude makes on my behalf is logged here as "Claude's call".

## 2026-11-08: Storms, wind zones and counties (Claude's calls; override any)

- **Landfall dates** are the local calendar date of the US landfall record in HURDAT2. Isaias (23:10 EDT), Helene (23:10 EDT) and Milton (20:30 EDT) carry the evening date, a day before their UTC stamps, so "the night of landfall" is the first dark night.
- **Wind zones use the tropical track only** (HURDAT2 status TS or HU). With every fix, the post-tropical remnants pull in states far from the damage: Helene's would add IL, IN, OH and WV, and Ida's would add NJ, NY, PA and New England.
- **States per storm** are every state with a county in that zone, so no hit county is left out (`test_states_cover_wind_zone`). This makes Isaias 11 states and Helene 8, and adds states such as AR to Laura.
- **Connecticut uses its old 8 counties.** In 2022 the Census replaced them with 9 planning regions, but EAGLE-I (2020 and 2024 files) and MCC.csv still use 09001–09015. So Connecticut's shapes come from the 2021 cartographic boundaries and its housing units from the 2021 ACS.
- **EAGLE-I's customer counts are repaired against Census housing units** (`counties.repair_customers`). MCC.csv adds up to about 100% of EAGLE-I's own state totals (`coverage_history.csv`, 2022) in every storm state except North Carolina, where it reaches only 34%: 1.8M of 5.3M customers. That makes Wake read 0.10 customers per housing unit, and New Hanover (Wilmington) 0.02, so its Florence outage read 44 times its customers. Two rules:
  - Every county of a state whose MCC rows sum to under 80% of the state total gets housing units scaled to that total. This is North Carolina only.
  - Elsewhere, a county with no MCC row, or one outside 1/3–3 customers per housing unit, gets housing units times the ratio of its state's plausible counties. This hits 19 Texas counties (Zavala reads 17), 6 in Virginia (Buena Vista: 1 customer) and Norton.
  - The median county has 1.1 customers per housing unit. Each county's source is kept as `customers_source`.

## 2026-11-08: Before building the storms (Claude's calls; override any)

**Open questions 1–4 of the dropout entry, settled:**
1. *Ida's long DEMCO dropouts:* accepted and logged, with no hand edits. They go on the failure page (Task 9). A hand-made exclusion list would itself be tuning on known cases.
2. *Over-counts:* an official % out above 1.05 is dropped from fitting and scoring, and values in (1.00, 1.05] are clipped to 1.00. MCC is a modeled count, so a few percent over is slack; more than that is an error. Both counts are reported per storm (`model.apply_overcount_rule`).
3. *Coverage cutoff:* kept at 0.8, unchanged. Mississippi, Texas in 2020, Alabama in 2018 and Tennessee stay out of training and scoring.
4. *Riders:* accepted as logged.

**Empty-count bunching check** (share of empty counts in state-runs with 10 or more empty counts; Helene and Milton not opened):

| Storm | State shares |
|---|---|
| Florence 2018 | GA 19%, NC 53%, SC 100%, VA 99% |
| Michael 2018 | AL 1%, FL 34%, GA 28%, NC 64%, SC 81% |
| Laura 2020 | AR 61%, LA 44%, MS 32%, TX 68% |
| Isaias 2020 | FL 32%, MD 8%, NJ 10%, NY 63%, NC 93%, PA 28%, SC 98%, VA 95%; CT, DE, DC under 100 empty counts each |
| Ida 2021 | AL 31%, LA 44%, MS 20% |
| Uri 2021 | TX 43% |

Several states sit far below 2021's 44/16/47% (Georgia in Florence, Alabama in Michael, Maryland and New Jersey in Isaias). Step 1 of `flag_dropouts` stays as it is: an empty count is unusable in the median either way, so reading it as 0 only matters for finding dips. The cost is a possible extra dip that flags a few riders or skips past a nearby real dropout. Revisit if the failure page shows it.

**`DARK_MIN = 2,000`** (baseline light summed over a county's pixels, in nW/(cm² sr) × pixels). That is about 4,000 pixels at the Black Marble noise floor of ~0.5. In Ian's table it marks 32 of 505 counties not measurable, mostly small Virginia independent cities.

**Data access.** LAADS serves this account at 3–4 MB/s in total, however many connections are open. The same files on Earthdata Cloud (CloudFront) come at about 18 MB/s, so the build fetches whole files into memory from there, checks each MD5 from the LAADS listing, and never writes a tile to disk. Range requests that skip unneeded layers were tried and were slower, because each of h5py's metadata reads becomes a round trip.

**Pass time for counties split across tiles:** the median `UTC_Time` from the tile holding most of the county's valid pixels. It is exact for counties inside one tile. On Ian, 963 of 27,775 county-nights had a mixed pass, where the all-pixel median sat more than an hour from the clear-pixel median.

## 2026-11-08: Pass bar, written before the lockbox opens (Claude's call)

This is committed before any Helene or Milton estimate is fit, scored or plotted. The commit time is the proof. Helene's and Milton's tables may already exist (building them is allowed), but nothing reads their official numbers against estimates until after this commit.

**What gets scored.** The final isotonic curve and ranges are fit on all eight main storms with `final=True`, then scored once on each locked storm. Scored rows are hit counties (34-kt zone or stronger) on event nights (landfall to landfall + 21 days) with status `ok`, a covered state, and a usable official count after the over-count rule. The official count is EAGLE-I's ±60-minute median at the pass, with `flag_dropouts` runs removed; ±30 and ±90 are reported beside it.

**The bar.** A locked storm passes when all three hold at ±60:
1. **County error:** the curve's mean absolute error in percentage points is lower than the wind-only guess's on the same rows (the plan's suggested bar).
2. **Agreement that is not just shared decay** (the Phase 0 lesson): over all scored counties, pool the night-to-night changes between consecutive scored nights. The Spearman correlation between estimated and official changes must be at least 0.3. Plain Spearman on levels is not used: on Lee in Phase 0 it was 0.77 raw but −0.06 detrended.
3. **Recovery margin:** across hit counties where both restore days exist, the median absolute error in restore day (10% threshold, held 24 hours) is at most 2 days.

**Verdict.** "Pass" if both storms pass; "partial" if one does; "fail" if neither does. If the drop rule removes a storm for clouds, the verdict covers the other storm alone and says so. Uri is scored separately as the stress test, with the caveat that the dropout constants were tuned partly on it, and does not count toward the verdict. Every number is reported whatever the verdict.

## 2026-11-08: NOAA-20 cross-check scope (Claude's call)

The cross-check builds Ian on tile h09v06 only (38 counties, Lee included) and Beryl on h08v06 only (44 counties around Houston and Matagorda). Ida keeps all four of its tiles, because the 30°N tile edge runs through southern Louisiana and only 4 parishes lie wholly south of it. Only counties wholly inside the chosen tiles are built (`table.cross_check_counties`), so no county is summed from half its pixels. This cuts the cross-check download from 13 tiles to 6. The comparison is the two satellites on the same counties and nights, so it does not need full state coverage.

## 2026-11-08: Model, scorecard and export details (Claude's calls; override any)

- **Angle and moon correction** (`model.fit_angle_moon`): one least-squares fit on the training storms' calm nights only (baseline nights, status `ok`). The intercept is kept. A feature that does not vary there gets slope 0, a missing feature contributes 0, fewer than 10 calm rows means no correction, and a sensor zenith of 90° or more is an error. On Ian's baseline nights it cut the night-to-night spread of "% darker" from 0.29 to 0.20 (standard deviation).
- **Same rows for every method.** The curve, wind-only and "nothing happened" all give NaN wherever the status is not `ok`, so all three are scored on identical rows. Wind-only's guess for a band it never saw (Uri's −1) is the row-weighted mean of its training rows.
- **Restore day** (`evaluate.official_restore_day`): the peak is the first maximum, NaN nights are skipped, and a night counts as restored only when the next reading at least a day later is also at or below 10%. A county never above 10% is "back" at its first reading, so constant guesses score well on this column. The pass bar keeps it as written. The scorecard also shows it on counties officially above 10% out.
- **Waiting periods count from the landfall time** in HURDAT2 (`Storm.landfall_time`), not from midnight UTC. Uri starts at 07:25 UTC, when rotating outages began.
- **Exports** carry only nights after the baseline. A county EAGLE-I never showed above 10% after landfall is "back" at its first official reading. Synthetic claims go only to counties where EAGLE-I shows a real outage.

## 2026-11-08: Beryl is built from NOAA-20 (Claude's call)

NASA's catalog (CMR) has no Suomi NPP VNP46A2 or VNP46A1 files for file dates 2024-07-10 to 07-16 or 07-24 to 07-29. That is Beryl's whole first week after landfall: the nights of July 9–15 and 23–28. NOAA-20's VJ146A2 has every day. So Beryl's table is built from VJ146A2 and VJ146A1, baseline and nights alike, and its `satellite` column says so (`config/storms.yaml`, `Storm.satellite`). Mixing satellites inside one storm would compare tonight with a baseline from a different instrument. The Suomi NPP table, with its gaps, is kept as `county_nights_beryl2024_vnp46a2.parquet` for the cross-check.

The same catalog check found two other gaps:
- Helene's landfall night (file dates 2024-09-26 and 09-27). Its next night is present.
- Two of Ida's baseline nights (2021-08-03 and 08-04).

Both stay on Suomi NPP. The missing nights are marked unseen, never zero.

## 2026-11-08: Model choice, written before the lockbox opens (Claude's call; override any)

**What stands.** The pass-bar verdict is judged on the pre-registered isotonic curve, exactly as committed in the entry above. Nothing in this entry changes that bar or that model.

**What was learned on the eight main storms, leave-one-storm-out.** The curve barely predicts any outage: its largest estimate on a scored county-night is 9.5% out, so it misses all 197 county-nights that were officially at least half out, and it reaches 16% of each storm's official peak. This comes from the signal, not from which rows it is fit on (refits on event nights only, or hit counties only, do no better). Corrected "% darker" separates calm counties from dark ones, but on its own it does not size an outage: steep viewing angles (section 3 of `docs/failures.md`) and each county's calm-night spread (standard deviation about 0.2) swamp it.

**The hybrid, and why it is secondary.** After seeing those results, a second model was built (`src/blackout/hybrid.py`): gradient-boosted trees, constrained to rise with darkening and wind band, on the corrected darkening, the county's darkening scaled by its own calm-night noise, wind band, days since landfall, brightness, moon, view angle and visibility. Its twin `wind_timing` has the same trees with no satellite input. Because the hybrid was designed after the leave-one-storm-out results were visible, it is post hoc. It is reported beside the curve, never in its place, and it gets its own pre-registered test below. Four independent checks ran before this entry (an independent rebuild, a leakage audit with 80 perturbation cases, a storm bootstrap with 2,000 draws, and a skeptic); their findings and the fixes they forced are summarised at the end of this entry.

What the checks agree on:
- The hybrid's gains over the curve on outage measures are real: error on county-nights at least 10% out falls from 38.8 to 24.1 percentage points (better in 8 of 8 storms), AUC for "at least half out" rises from 0.75 to 0.96, and its peak totals land near the official ones (1.4× on average, against 0.16×).
- It pays for that on calm nights: its county error over all scored nights (2.95 pp pooled) is worse than the curve's (2.42) and than "nothing happened" (2.17). Averaged per storm its lead is not robust and comes from Ida alone.
- Most of its gain comes from wind band and timing, not from the satellite. `wind_timing` already gets 87–95% of the hybrid's improvement. The satellite's own increment (hybrid minus `wind_timing`) is −1.6 pp on nights at least 10% out and +0.02 AUC, favourable in 6 of 8 storms on error and in a 90% storm-bootstrap interval that crosses zero. With eight storms it is not settled.
- About half of its "at least half out" calls are false alarms (35 of 73), and its estimates above 50% are over-confident.

**The hybrid's own pre-registered test, scored once on Helene and Milton after this commit.** On each locked storm's scored county-nights (the pass bar's rows), the satellite adds value if, against `wind_timing`: (1) error on county-nights officially at least 10% out is lower, and (2) AUC for "at least half out" is higher. Both must hold on both storms for a "yes"; one storm for "partial"; otherwise "no". This is the confirmatory test of the satellite increment, and its result is reported whatever it is. The hybrid is also run through the three pass-bar conditions for information, labelled as not pre-registered.

**What the app shows.** The hybrid's estimates with their ranges, because the curve's estimates never exceed 10% and would show a reader nothing. Every screen that shows them says they come from the secondary model, the county card leads with the range rather than the point, and the scorecard panel puts `wind_timing` beside the hybrid so the satellite's share is visible. The pass-bar verdict shown in the app is the curve's.

**Fixes made because of the checks, before this commit:** the final fits read each storm's own table (they had opened Beryl's Suomi NPP table with its missing week); leave-one-storm-out now drops the held-out storm's own county-nights from the other storms' tables (Michael's baseline held 1,206 of Florence's scored rows; the effect was 0.2 pp or less); the hybrid's early stopping is off, so its fit no longer depends on a random split; and predicting on rows without their baseline nights now raises an error instead of silently using a default noise level.

**Frozen for the lockbox:** `hybrid.TREE_PARAMS` = max_iter 300, learning_rate 0.05, min_samples_leaf 40, l2_regularization 1.0, random_state 0, early_stopping False; features as listed in `hybrid.py` at this commit; the over-count rule and the angle/moon correction as logged.

**Known weaknesses to carry into the write-up:** the heavy-outage sample is 197 county-nights across 84 storm-counties, a third of them Ida's; Beryl is the only NOAA-20 storm and there the hybrid loses to `wind_timing`; the pass bar's second condition (night-to-night agreement) can be met by timing decay alone, so it does not isolate satellite skill; peak totals can look right while county errors cancel.

## 2026-11-08, 23:50: Correction and edge rules for the Model choice entry (Claude's call; before the lockbox opens)

A judge re-ran the four checks on the current code after the fixes above regenerated the leave-one-storm-out predictions, and found these numbers in the Model choice entry stale. The entry is left as written; this note corrects it.
- The satellite increment (hybrid minus `wind_timing`) is favourable on error where at least 10% out in **5 of 8** storms, not 6 (Florence +1.8 pp, Idalia +4.0 and Beryl +0.5 go the other way), and in 5 of 7 on AUC; over all rows the hybrid is better in 2 of 8. `wind_timing` gets **89–90%** of the hybrid's gain over the curve, not 87–95%.
- False alarms: **36 of 75** half-out calls, not 35 of 73. On those calls the hybrid predicts 0.66 against 0.51 official.
- Peak totals: the mean ratio 1.4× hides a range from **0.35× (Ida) to 3.40× (Florence)**; the median is 1.27×, and `wind_timing` averages 1.48×.
- Current pooled numbers: hybrid county error 2.95 pp (worst of the five methods; curve 2.42, nothing 2.17), error where at least 10% out 24.1 pp, AUC 0.955, change agreement 0.19. Trained only on earlier storms, which is how the lockbox works, the hybrid's error where at least 10% out rises to 28.7 pp and its increment over `wind_timing` shrinks to −0.6 pp and +0.014 AUC. The leave-one-storm-out numbers are optimistic.

**Edge rules for the hybrid's pre-registered test**, decided now without looking at the lockbox (`final.satellite_test`):
- A locked storm needs at least **10 scored county-nights at least 10% out** to be evaluable. A storm with fewer, or one dropped by the cloud rule or with no table, is not evaluable, and the verdict covers the remaining storm and says so, as the pass bar does.
- The AUC condition needs at least **10 county-nights at least half out** and a defined AUC. With fewer, that storm's test rests on the error condition alone.
- The verdict is "yes" when every evaluable storm passes (marked "on the evaluable storm only" if one was not evaluable), "partial" when one of two passes, "no" otherwise. The differences themselves are reported beside the label: a sign test on two storms with no margin is weak evidence either way.

**Hardening before the run:** the final fits refuse to start with a main table missing; training rows whose (fips, night) key appears in a locked storm's table are dropped before the final fits, as leave-one-storm-out does, reading only the keys; and `lockbox_result.json` records the commit, the model code's hashes, each training table's name, satellite and row count, and the run time.

**App labels:** estimates are labelled a storm-context model (wind band and days since landfall with a night-light adjustment), not night-light estimates; the county card leads with the range; the verdict shown is the curve's.

## 2026-11-09: D-12, no second opening (Claude's call; override any)

The lockbox was opened once, on 2026-11-08 at 23:52 PST, by one run of `uv run blackout lockbox` with the code of `7fd2732`. Its result, `data/processed/lockbox_result.json`, is the record. It is copied byte for byte to `docs/lockbox_result.json`, its sha256 is pinned in `tests/test_lockbox.py` (LB-45), and the inputs it read are recorded in `docs/lockbox_record.json` (LB-44). That record is immutable: no run, fix or rebuild replaces it, and a defect found in it is disclosed beside the recorded numbers (D-20), never corrected by rerunning.

**The guard.** `final.run_final` refuses to run (`LockboxOpenedError`) when `lockbox_result.json` or the opening marker `lockbox_opened.json` exists in its output folder; the marker is written before the first locked table is read, so even a run that crashes afterwards leaves a trace. `blackout lockbox` prints why it refused and exits non-zero.

**A reopen.** A second look needs a reason, given as `blackout lockbox --reopen "<reason>"` (`run_final(reopen_reason=...)`). The run then writes `lockbox_result_<UTC time>.json` beside the first result, its predictions and `scorecard_final.parquet` under `reopen_<UTC time>/`, and the reason inside the new file; it never overwrites, and refuses an empty reason. The reason must also be entered here, dated, with what the second look is for. The scorecard keeps rendering the first result; a reopened result is labelled "after the opening, not held out" wherever it is shown (test plan §0.2).

## 2026-11-09: D-20, integrity of the recorded opening (Claude's findings; override any)

Checked with `uv run pytest tests/realdata --run-lockbox` (LB-36, LB-37, LB-40, LB-41, LB-43, LB-44) and `tests/test_lockbox.py` (LB-45) on 2026-11-09, reading the locked tables for facts only. The reproduction at the recorded commit (LB-42) has not been run yet.

**One run.** The orchestrator states that `uv run blackout lockbox` was run exactly once, launched at 23:52 PST on 2026-11-08. The files agree: `predictions_<main storm>.parquet` for all eight main storms were written at 23:55:04, Helene's at 23:55:07, Milton's at 23:55:08, Uri's at 23:55:09, and `lockbox_result.json` and `scorecard_final.parquet` at 23:55:10; `provenance.run_at_utc` is 2026-11-09T07:55:07Z (23:55:07 PST). Everything the run wrote falls within six seconds. No second result file exists.

**Provenance (LB-41).** `git_head` is `7fd2732`, which descends from `2f534f9` (the pass bar, 21:21:34 PST) and `2187e37` (the model choice, 23:45:20). Each `code_sha256_16` equals the file at that commit; `hybrid.py`, `model.py` and `ranges.py` did not change between `2187e37` and `7fd2732`, nor since. `training_tables` lists the eight main storms, each from its own table, with Beryl's from NOAA-20 (`county_nights_beryl2024.parquet`, VJ146A2). `run_at_utc` lies between the commits `7fd2732` (23:54:45) and `50d572e` (23:57:13), which committed the exports.

**Chronology, disclosed.** The commit `7fd2732` was made 22 seconds before `run_at_utc` and 19 seconds before the main storms' predictions were written. The process had started at 23:52, before that commit existed, so it imported the working tree's code of that moment; the file hashes taken at 23:55:07 equal the commit's. What the record cannot show is that no source file changed between 23:52 and 23:54:45; the orchestrator's account is that the code was finished, the run started, and the commit made while it ran.

**`working_tree_dirty: true`, disclosed.** The tree had uncommitted changes when the provenance was taken. The record does not say which files; the five hashed modules matched the commit. The run's own outputs are gitignored and cannot be the cause. `.claude/launch.json` was tracked at `7fd2732` and deleted in `19b37e4` (23:58), so a local deletion is one candidate; the generated files that `50d572e` committed two minutes later were not yet written. Unknown, and not recoverable.

**The inputs (LB-44).** `docs/lockbox_record.json` holds the sha256 of the 11 tables the fits and scores read (8 main, Helene, Milton, Uri) and of the 3 NOAA-20 cross-check tables read for the `noaa20` and `lee_noaa20` sections, the sha256 of `uv.lock` (unchanged since 20:45), and the versions: Python 3.13.12, numpy 2.5.4, pandas 2.3.3, scikit-learn 1.9.1, scipy 1.18.1, pyarrow 26.0.1. Every table is older than the run; the newest input, Uri's table, was built 33 minutes before it (23:21:42). Nothing was rebuilt after the run.

**The verdict rule (LB-40).** The code that ran computed "pass if both pass, partial if any, fail otherwise", with no drop rule and no "no verdict". The drop rule, recomputed with `table.drop_check` on each locked table: Helene 265 of 277 hit counties had a clear night within 7 days of landfall (share 0.957), Milton 73 of 74 (0.986). Neither storm is dropped, so under the committed rule, now implemented as `final.verdict`, the verdict is "fail", the recorded string. `run_final` applies the drop rule from now on.

**The verdict comes from the curve (LB-36).** `pass_bar` holds the isotonic curve (county error 6.77 pp on Helene against wind-only's 7.00; 1.27 against 1.75 on Milton) and `hybrid` the hybrid (7.16 and 2.20 pp), on the same 3,715 and 1,243 scored rows; each matches `scorecard_final.parquet`'s row for that method at ±60 to the JSON's rounding.

**The satellite test (LB-37).** Recomputed from the recorded `satellite_increment` rows under the edge rules of 2026-11-08 23:50: Helene is evaluable on both conditions (566 county-nights at least 10% out, 175 at least half out; error 2.08 pp lower, AUC 0.0006 higher) and passes; Milton has 41 rows at least 10% out but 4 at least half out, so its test rests on the error condition alone (2.04 pp lower) and passes. The verdict is "yes", as recorded, with the same per-storm flags. The AUC margin on Helene is a rounding error of a margin; the differences, not the label, are the evidence.

**Locked truth (LB-43).** Every county's customers in Helene's table (787 counties) and Milton's (272) equal `load_counties(storm.states).customers`, so the locked tables carry the repaired counts and no second reading is needed.

**The record is frozen (LB-45).** `docs/lockbox_result.json` is byte-identical to `data/processed/lockbox_result.json`; sha256 `db6cb77a81c2a784bfe5107a8fd9668f57db2aa032e51c37a92cba0d346e1965`.

**Deviations from the plan, disclosed and not fixed in the record.** Before the final fits, the run read the locked and Uri tables in full (`pd.read_parquet(table_path(s))[["fips", "night"]]`, every column) to take their (fips, night) keys; only the keys were used (`drop_shared_county_nights`), and the keys drop was 0 rows. It ran with no `--confirm` flag, no opening marker (added by D-12), no expected-outcome entry (D-14 still to be written: the leave-one-storm-out dry run showed the curve failing condition 3 on all eight main storms, and no expected outcome was logged), no frozen diagnostics entry, and no drop rule in the verdict (above). The working tree was dirty (above). None of these changes a recorded number.

**Reading.** Every §0.3 check that can run on this machine passes or is disclosed here; the recorded verdict "fail" and satellite test "yes" stand as computed. `final.render_integrity` renders these checks as the scorecard's S1a block; on 2026-11-09 `evaluate.write_scorecard` does not call it yet, so `docs/scorecard.md` shows no S1a until that is wired.

## 2026-11-09: How to read the opened lockbox (D-2; Claude's call; override any)

The lockbox was opened once (`50d572e`, run at 2026-11-08 23:55:07 PST with the code of `7fd2732`). These are the reading rules from here on. They were drafted in `docs/test-plan.md` (§0.2, §0.3, §0.14) by a revision that had not read the result; this entry applies them to the result as recorded in `data/processed/lockbox_result.json`.

- **Two things count as evidence.** (A) The pass bar on the pre-registered isotonic curve (`2f534f9`), scored once. (B) The hybrid's registered satellite test against `wind_timing` (`2187e37`, edge rules `7fd2732`), scored once. Everything else is descriptive: it can lower a claim, never support one on its own.
- **Labels.** Every leave-one-storm-out number for the hybrid or `wind_timing` is "design loop" (the hybrid was built after those rows were seen). Every number on Helene, Milton or Uri from a model or export changed after `50d572e` (for example `966313a`'s range clamp, the ranges fix of D-11, the hybrid band fix MD-45) is "after the opening, not held out". Rows read from the recorded `predictions_<storm>.parquet` are "recorded run". Any slice is "exploratory". Ian's row is always "LOSO" (§0.2, resting on the 2026-11-07 entry: Ian is never re-scored under the new rule and called a new pass).
- **The recorded result is final.** A defect found by the §0.3 integrity checks is disclosed beside the recorded numbers (D-20) and read under the committed rule; the lockbox is not rerun to replace them (D-12). A rerun after any change is a new model, not a second look.
- **The reading table (§0.14)** maps (A) × (B) to one of WORKING, PARTIAL, NOT WORKING, INCONCLUSIVE. Applied to the record: (A) = "fail" (both storms fail conditions 2 and 3 at ±60, ±30 and ±90), (B) = "yes" (both storms evaluable on error; Milton's AUC condition not evaluable, 4 rows at least half out). Row: **NOT WORKING as pre-registered**, and the write-up says plainly that the secondary, post hoc model's satellite increment held up on the locked storms (−2.1 pp and −2.0 pp on rows at least 10% out; AUC +0.001 on Helene). The reading stands only once every §0.3 check passes or is disclosed under D-20; see S3 for what is checked and what is open.
- **Descriptive numbers qualify wording, never move a row.** Under LOSO the hybrid's county error (2.95 pp) is worse than "nothing" (2.17); forward chaining raises its error on rows at least 10% out from 24.1 to 28.7 pp; on the locked storms it fails condition 1 (7.16 vs 7.00 pp on Helene, 2.20 vs 1.75 on Milton). These go next to the reading, not into it.

## 2026-11-09: Restore-day conventions (D-3; Claude's call; override any)

**Correction to the 2026-11-08 "Model, scorecard and export details" entry.** It said a county never above 10% is "back" at its first reading under `evaluate.official_restore_day`. Not so. That function scans the nights after the county's first maximum, so a never-out county is "back" at the first reading *after its first maximum*: a county whose tiny peak falls on day 19 restores on day 20. `export.official_restore` (the county card's official day) deliberately dates such a county to its first reading instead (day 0 when EAGLE-I reported the landfall night), and its docstring says why: under evaluate's rule hundreds of Ian counties would show an outage that never happened. The pass bar keeps evaluate's rule as written; this entry only states what the two functions do.

**Three rules exist today** (read from `evaluate.py`, `export.py`, `ranges.py`):
1. `evaluate.official_restore_day` (the bar, condition 3, both for the estimate and the official series through `final.restore_day_errors`): after the first maximum, the first night at or below 10% whose readings up to the next one at least a day later are all at or below 10%; NaN nights skipped; NaN if never confirmed.
2. `export.official_restore`: rule 1 for a county that went above 10% after landfall; the first known reading (confirmed by any reading a day or more later) for one that never did.
3. `ranges.restoration_interval` (the card's estimated interval): no 24-hour hold and no peak; `hi` is the first counted night at or below the threshold after the *first* night above it, `lo` the counted night before; never out gives (0, first counted night). On a bounce back (0.3, 0.05, 0.4, 0.05, 0.05 on days 0–4) rule 1 says day 3 (the first maximum is day 2, and day 4 confirms day 3's drop) while rule 3 says (0, 1); with no reading after day 3, rule 1 says NaN instead. That is why MD-36 fails.

**Decision.** `restoration_interval` adopts rule 1's shape: after the estimate's first maximum over counted nights, `hi` is the first counted night at or below the threshold that the next counted night at least a day later confirms, `lo` the counted night before `hi`; no confirming night gives an open interval. The never-out convention stays as it is ((0, first counted night), which matches `export.official_restore`). Then the card's two numbers share one definition and MD-36 passes. This is a product change after the opening and is labelled so; the recorded exports (`50d572e`, `966313a`) keep today's rule 3 until the change lands.

**The error for counties that were out (EV-21), computed now from `loso_predictions.parquet`** (hit, covered counties in the event window; a county is "out" when EAGLE-I shows it above 10% on some event night). Median |estimated − official| restore day, pooled over the eight main storms: isotonic 5.0 days on out counties (304) and 6.0 on never-out (509); hybrid 2.0 and 3.0; "nothing" 1.0 and 2.0. So the bar's statistic is short for every method mainly because the official restore day under rule 1 is short: for never-out counties it is day 1 in most cases (the first maximum sits on the landfall night), and for out counties half the hit counties are back within a few days. With the recorded hybrid predictions (after the opening, not held out): Helene 5.0 days on out counties (119 of 129 counted) and 2.5 on never-out; Milton 2.0 (33) and 7.0 (40); Uri 2.0 (136) and 3.5 (62). The curve's split on the locked storms needs the LB-42 reproduction, since the run saved only the hybrid's per-row predictions. Why the hybrid has fewer counted counties than the curve on Helene (129 against 252): rule 1 needs the next counted night at least a day later to confirm the drop, and the hybrid's estimates bounce. Of Helene's 269 hit covered counties, 118 drop to 10% or below but are never confirmed (a later clear night reads above 10% again, or there is no later clear night), 12 never drop after their maximum, 10 have fewer than two clear nights; on average only 14% of a county's clear event nights read above 10%, so it is the bouncing and the clouds, not estimates that stay high.

## 2026-11-09: Overlapping storms (D-4, D-5, D-17; Claude's call; override any)

Checked against `config/storms.yaml`, the built tables and HURDAT2 (`data/raw/hurdat2`, TS and HU fixes only, `winds.band_at_points` over Census county points).

**D-4, Michael's baseline holds Florence's event window.** Michael's baseline runs 2018-09-07 to 10-07; Florence's event window 09-14 to 10-05, so 22 of Florence's event nights sit inside it in GA, NC and SC. In Michael's table that is 6,710 baseline county-nights (GA 3,498, NC 2,200, SC 1,012), 3,820 of them status `ok`, with Florence's outage in them (mean official 0.9% out; 2% of the rows above 10%). Florence's own track put 95 Michael counties at 34 kt or more between Sep 7 and 16 (10 at 64 kt), 63 of them Michael hit counties. Since `db246a9`, `evaluate.loso` drops a training row whose (fips, night) belongs to the held-out storm: 1,207 of Florence's 1,328 scored rows have a twin in Michael's table by this check (the "Model choice" entry said 1,206; the one-row difference is the filter, which here does not require a finite prediction). What still includes them: the final fits' calm-night set for `fit_angle_moon` (Michael's baseline nights are calm nights there, Florence or not), `hybrid.county_noise` for Michael's GA, NC and SC counties (a county's spread is taken from its own storm's baseline nights, also at prediction time), and `model.noise_report`. Accepted and disclosed; the windows of a scored storm cannot change now. S16 carries the count.

**D-5, Helene's window holds Milton's landfall.** Helene: landfall 2024-09-26, window to 10-17. Milton: landfall 10-09. Milton's tropical track put 74 Helene hit counties in FL, GA and SC at 34 kt or more (8 at 64 kt). Of Helene's 3,715 scored county-nights at ±60, 1,911 fall on or after Milton's landfall night and 1,527 of those are in FL, GA or SC; the mean official % out on Helene's FL/GA/SC scored rows is 12.5% before that night and 1.4% from it on, so Helene's verdict rows there mix a mostly-recovered Helene with Milton's arrival. Two things the plan did not say: the two locked storms have the *same* baseline, 2024-08-24 to 09-23 (Milton's `baseline_end` was set to 09-23 so Helene's damage stays out of it, and the default 30-day start coincides with Helene's), and Milton's event nights in Helene-hit counties carry Helene's residual darkness against a pre-Helene baseline; 459 of Milton's 1,243 scored rows are nights 10-09 to 10-17 that Helene's table also holds. Disclosed; S14 prints Helene's three conditions on its 1,804 pre-Milton scored rows, labelled "defined after the opening" (it needs the LB-42 reproduction for the curve).

**D-17, other systems inside baselines and event windows** (counties at 34 kt or more; "host hit" means also a hit county of the project storm):
- Laura 2020, baseline: Hanna (AL082020), Jul 25–26: 16 TX counties (2 at 64 kt), 0 host hit.
- Laura 2020, event: Sally (AL192020), Sep 12–17: 4 LA and MS counties, 0 host hit.
- Isaias 2020, baseline: Fay (AL062020), Jul 9–11: 37 counties in CT, DE, MD, NJ, NY, VA, 35 host hit.
- Ida 2021, baseline: Fred (AL062021), Aug 11–17: 6 AL counties, 0 host hit.
- Ida 2021, event: Nicholas (AL142021), Sep 12–14: 4 LA parishes, 0 host hit.
- Beryl 2024, baseline: Alberto (AL012024), Jun 19–20: 19 TX counties, 5 host hit.
- Michael 2018, baseline: Florence (D-4 above). Helene 2024, event: Milton (D-5 above).
- None for Florence, Ian, Idalia, Milton or Uri.

The plan's counts (16, 4, 37, 6, 4, 19) all reproduce. Accepted as the DL-58 allowlist; S16 lists the counties. None of the intrusions changes a scored window; the Texas ones do not explain the Texas noise (D-18).

## 2026-11-09: Trigger truth and the wind trigger (D-6; Claude's call; override any)

**What the recorded trigger view did** (`final.trigger_view` at `7fd2732`): the estimate is the midpoint of `ranges.pct_out_bracket`'s two looks around landfall + 72 h; the truth is the *first raw* official % out at or after that time, before the over-count rule and from one look only. The recorded counts (Helene: hybrid 5 paid correctly, 12 wrongly, 47 missed, 195 correctly unpaid, 10 unknown; curve 0/0/52/207/10; Milton: hybrid 0/1/1/71/1, curve 0/0/1/72/1) stand as the recorded run.

**Decision.** Truth is the official % out at EAGLE-I's two nightly readings around landfall + 72 h (the last pass before that hour and the first at or after it), after the over-count rule: a value above 1.05 is not a reading, so the next usable one is taken, as `restore_day` skips NaN nights, and (1.0, 1.05] reads 1.0. A county is "out" when the midpoint of the two exceeds 50%. These are the estimate's own two looks whenever the satellite saw both nights; when clouds push the satellite's looks days away from the hour, the truth stays at the hour, so the comparator, a wind trigger that pays every band-64 hit county, is judged on the same truth and carries no unknowns of its own. Both are "defined after the opening".

**What changes, on the locked tables and the recorded hybrid predictions** (labelled after the opening, not held out): on Helene the recorded raw rule and this rule disagree on 18 of 269 hit covered counties (54 out under the raw rule, 50 under this one); an over-count sits at one of the raw looks in 26 counties, where the next usable reading is taken. Hybrid against this truth: 4 paid correctly, 13 wrongly, 44 missed, 198 correctly unpaid, 10 unknown. Wind trigger: 4, 19, 46, 200, 0. On Milton: 1 disagreement (1 county out under the raw rule, 0 under this one; 1 over-count at a look); hybrid 0/1/0/72/1; wind trigger 0/8/0/66/0. So on these two storms the hybrid's basis risk is no better than a band-64 wind trigger: of the Helene counties it could judge that were half out at 72 h, it misses 44 of 48 (10 counties unknown to it); the wind trigger misses 46 of 50.

**The plan's wording, "the same two looks as the estimate", taken literally** (the satellite's two `ok` nights either side of the hour, official read there): the truth is then known for 236 of Helene's 269 counties and only 24 are out, because under cloud the looks drift days from the hour and their midpoint no longer describes it. Hybrid 3/11/21/201/33, wind trigger 3/15/21/197/33; Milton 72 known, none out, hybrid 0/1/0/71/2, wind trigger 0/8/0/64/2. That version asks whether the county was half out on the nights the satellite happened to see, and hands the satellite's clouds to the wind trigger, so it is reported beside the truth above and not used as it.

## 2026-11-09: Definitions behind the scorecard columns (D-7; Claude's call; override any)

Read from `evaluate._score_storm` and `evaluate.diagnostics`, as they ran:
- "At least half out" means official % out ≥ 0.5 (`OUT_CUT`, inclusive), and a call means an estimate ≥ 0.5. Wording everywhere is "at least half", not "above half".
- `catch_rate_50` is a recall: of scored county-nights officially at least half out, the share the method also put at least half out. NaN, never 0, when there is nothing to catch.
- `false_alarm_50` is a share of the method's own calls: of scored county-nights the method put at least half out, the share officially under half. NaN when the method made no call.
- `measurable_share` counts hit county-nights (wind band ≥ 34; every county for Uri) from landfall to window end, whatever the coverage, and gives the share with status `ok`. It is a count of nights, not of customers; S4 adds the outage-weighted share.
- AUC "for at least half out" ranks the method's estimates with ties averaged; it is NaN when a storm has no positive or no negative row.
- Error "where official ≥ 10%" uses `RESTORE_THRESHOLD`, the same 10% as the restore day.

## 2026-11-09: The app: claim check, committed exports, default storm (D-8, D-9, D-10; Claude's call; override any)

**D-8, `claimVerdict`** (`app/src/lib/claims.ts`): confirmed as the plan says. It reads the *high* end of the range (`hi`) on two nights: the peak `hi` over clear nights from landfall on, and the `hi` of the last clear night at or before landfall + claimed days. The share restored is 1 − used/peak; "review" needs 90% or more (`REVIEW_SHARE`, with float slack so exactly 90% reviews). Anything it cannot see counts for the claimant ("fits", share 0). The synthetic claim labels (`portfolio.make_claims`) use an absolute 10% restore day, so the product evaluation needs the oracle of EV-42 and EV-44 to separate estimate error from the two rules' mismatch.

**D-9, exports are committed.** `app/public/data/` (97 files, every storm including Helene and Milton, plus `ian2022_sample`) is tracked and was first committed in `50d572e`, then regenerated in `966313a`; `data/processed`, `data/interim` and `data/raw` stay ignored. **The plan's claim that exports "are regenerated with a fixed clock" was not true for any committed export:** at `966313a`, `export.meta_json` wrote `generated` from `datetime.now(UTC)` (the committed stamps read 2026-11-09T08:00:16Z to 08:01:10Z) and nothing read `SOURCE_DATE_EPOCH`, so every regeneration changed the 12 `meta.json` files for no reason. During this audit the B-08 builder added `export.generated_stamp`, which honours `SOURCE_DATE_EPOCH` (whole seconds since 1970, UTC; anything else is an error) and falls back to the wall clock; it is in the working tree and uncommitted as this entry is written. Decision: the regeneration command sets `SOURCE_DATE_EPOCH`, the committed exports are regenerated once under it, and a freshness step beside RH-12's (which covers the contract fixtures) regenerates the exports and diffs them, so a drifting export fails CI.

**D-10, the default storm.** **The plan's claim that "the index names a default demo storm" is not true yet:** `index.json` has only the sorted storm list (by landfall, then id), and `App.tsx` opens `storms[0]` when the URL carries no `?storm=`, which today is Florence 2018, the storm where the hybrid's peak estimate is 3.4 times the official peak. Decision: `index.json` gets a `default` id, the app opens it and falls back to the first entry when it is absent (WB-23). The default is **ian2022**: the Phase 0 storm, 62% of hit county-nights measurable, the hybrid's peak 1.26 times the official, and the bundled offline sample is its subset. Not a locked storm, so the demo never leads with a held-out result; its row is labelled LOSO (§0.2; the 2026-11-07 entry says Ian is never re-scored and called a new pass).

## 2026-11-09: Ranges after the opening (D-11; Claude's call; override any)

**What `ranges.fit_ranges` does.** Bins are quantiles of the prediction (5 asked for; tied quantiles collapse; a bin under 20 rows merges), and each bin's range is the 10th and 90th percentiles of official − predicted over the training rows: every `ok`, covered row with a usable truth, baseline nights included. `run_final` fit the shipped ranges on all eight main storms' LOSO residuals, 88,855 rows, of which 78.2% have an official value of exactly 0 and 0.8% are at least 10% out (`loso_predictions.parquet`).

**What that produced** (`lockbox_result.json`, "ranges"): the hybrid collapsed to 2 bins (71,084 and 17,771 rows); its upper bin's offsets are −0.043 and −0.003, so every estimate above 0.3% sits *above* its own range, which is what `966313a` patched in the export by folding the point into the range. The isotonic ranges have negative high offsets in all 5 bins. Coverage on hit counties after landfall was 0.705 (hybrid) and 0.776 (curve) against about 0.80 on all rows; recomputed here on the 11,983 scored rows, the hybrid's mean width is 1.1 percentage points and its coverage on rows at least 10% out (599) is 2.7%; the curve's is 0.0%. The ranges are honest about calm nights and say nothing where a range matters most. MD-31's toy fails the same way (0.22).

**Decision, a product change after the opening.** (1) Ranges are fit on the scored population: hit counties on event nights, status `ok`, covered, after the over-count rule, nested leave-one-storm-out for main storms so a storm's ranges never see its own residuals (MD-33). (2) The point stays folded into its range. (3) Active-row coverage (official ≥ 10%) always prints beside pooled coverage, with the interval score at alpha 0.2. Recomputed here with the saved LOSO hybrid residuals: the scored-population ranges give pooled coverage 0.818, active-row coverage 0.379, mean width 6.0 pp and interval score 0.155, against 0.707, 0.028, 1.3 pp and 0.204 for the shipped population under the same nested protocol. That meets the pooled target (0.75–0.90) and misses the active-row target (≥ 0.60), so (4) a range model that conditions on more than the prediction level (wind band and days since landfall, or quantile trees beside the hybrid) is the next step, also after the opening. Every range number on Helene, Milton or Uri from the new fit carries "after the opening, not held out"; the recorded exports keep the recorded ranges.

## 2026-11-09: wind_only stays the plan's comparator (D-13; Claude's call; override any)

Condition 1 of the committed bar names the wind-only guess, so it stays. What it is: `model.WindOnly.fit` takes the mean cleaned official % out per wind band over the plan's training rows, which are every `ok`, covered night with a usable truth, baseline nights included (`model.training_rows`). Pooled over the eight main storms, band 64 averages 6.1 pp over all nights against 16.4 pp on event nights only, band 50 1.2 against 3.0, band 34 0.3 against 0.5; baseline nights sit at 0.02–0.11 pp. So the comparator's guesses are about a third of what the same bands show after landfall, and beating it says little: the curve beat it on 6 of 8 main storms under LOSO and on both locked storms (6.77 vs 7.00 pp; 1.27 vs 1.75), while never estimating more than 9.5% out. `wind_timing` (the same trees as the hybrid, wind band and days since landfall, no satellite) is the fair no-satellite baseline and is reported beside every hybrid row; the satellite's contribution is hybrid minus `wind_timing`, never "beats wind-only".

## 2026-11-09: No expected-outcome entry was logged before the opening (D-14; Claude's call; override any)

Recorded as a fact. The leave-one-storm-out scorecard (`docs/scorecard.md` before its lockbox section, written by `blackout evaluate` after `db246a9` at 23:39 on 2026-11-08 and cited by the "Model choice" entry at 23:45; the plan dates that run 23:41, which the file itself cannot confirm, since the lockbox run rewrote it at 23:55) showed the pre-registered curve failing condition 3 on all eight main storms (median restore-day error 4.0 to 9.0 days: Florence 5.0, Michael 4.0, Laura 6.0, Isaias 5.0, Ida 7.5, Ian 9.0, Idalia 5.0, Beryl 4.0) and a pooled night-to-night Spearman of 0.065 against the required 0.3. The "Model choice" entry (`2187e37`, 23:45) recorded that the curve "barely predicts any outage" but no entry stated the expected lockbox outcome, and the opening followed at 23:55. The result (fail on conditions 2 and 3 on both storms) is what the dry run pointed to. The curve was therefore not falsified by surprise; it failed as expected, and the write-up says so rather than presenting the fail as news. Decision: before the next holdout's first locked table is read, an expected-outcome entry citing the LOSO dry run goes into this log; the reopen protocol (D-12) should carry the same requirement.

## 2026-11-09: Corrections to earlier entries (D-15; Claude's call; override any)

Checked with `counties.load_counties` over every storm state (`customers_source`) and the per-storm extracts in `data/interim`:
- **Repaired customer counts: 126 counties, not "19 Texas, 6 Virginia and Norton".** North Carolina 100 (all of them, the state rule), Texas 19, Virginia 6 (Wise 51195, Buena Vista 51530, Lexington 51678, Norton 51720, Radford 51750, Waynesboro 51820), and New York 1: Hamilton 36041. Norton is one of the six Virginia counties, not an extra; the 2026-11-08 "Storms, wind zones and counties" entry double-counted it, and `docs/failures.md`'s "26 counties elsewhere (19 in Texas, 6 in Virginia, Norton city)" has the right total and the wrong list: the 26th is Hamilton NY, which no entry had mentioned. RD-14 pins this set.
- **Empty-count bunching for the storms the 2026-11-08 table left out**, computed from `eaglei_<storm>.parquet` with the same rule (share of empty counts that sit in state-runs with 10 or more empty counts), never from the yearly file: **Ian 2022, Idalia 2023 and Beryl 2024 have no empty counts at all** (0 of 780,288, 748,060 and 676,053 rows), nor do Helene and Milton (0 of 1,433,378 and 765,014). The rule's step 1 (empties read as 0 while looking for dips) therefore cannot fire on any 2022–2024 storm. Recomputed from today's extracts, the 2018–2021 shares are close to the logged table (Florence GA 19%, NC 53%, SC 100%, VA 99%; Michael AL 1%, FL 34%, GA 27%, NC 64%, SC 80%; Laura AR 63%, LA 44%, MS 31%, TX 69%; Isaias FL 28%, MD 8%, NJ 10%, NY 63%, NC 93%, PA 27%, SC 98%, VA 95%; Ida AL 18%, LA 44%, MS 20%; Uri TX 46%); the differences of a few points, Ida's Alabama most (18% against the logged 31%), most likely come from the extracts' date spans, which differ from the pre-build check's (that check's inputs were not logged, so this is a presumption). The conclusion is unchanged.

## 2026-11-09: The first pass after landfall is sometimes filed under the night before (D-16; Claude's call; override any)

A night is labelled by the evening's date; its pass is the next morning (about 07:00 UTC in the eastern states). A storm that comes ashore after the evening date changes but before the pass gets its first post-landfall look under the night *before* the landfall date, which the scoring windows (landfall to landfall + 21 days) never include. Checked with `pass_utc` in every table:
- **Laura:** landfall 2020-08-27 06:00 UTC; the next passes are 07:50–09:32 UTC that morning (1 h 50 min later), filed under night 2020-08-26. 93 hit counties, 6.5% of them seen, 296,252 customers out summed over them. Scored nowhere.
- **Uri:** onset 2021-02-15 07:25 UTC; the passes of 07:24–09:08 UTC that morning are filed under night 2021-02-14. 254 counties, 15% seen, 851,403 customers out. Scored nowhere.
- **Beryl, not in the plan:** landfall 2024-07-08 08:40 UTC; 14 of its 34 hit counties were passed at 08:59–09:01 UTC that morning, 20 minutes after landfall, filed under night 2024-07-07. None was seen (cloud), 1,615 customers out, so nothing is lost in practice.
- Isaias, Helene and Milton came ashore late in the evening and carry the evening date as `landfall`, so their first passes (3.5, 3.4 and 7.0 hours after landfall) fall on the landfall night and are inside the window. Florence, Michael, Ida, Ian and Idalia came ashore in daytime; their first passes are 11–20 hours later on the landfall night.

Decision: no window moves. The three cases are the DL-57 allowlist; S4 and S10 carry a note; the restoration intervals' day 0 is the landfall night for every storm.

## 2026-11-09: Texas calm-night noise (D-18; Claude's call; override any)

Checked on every table's baseline `ok` nights (raw `pct_darker`; corrected with the shipped `fit_angle_moon` fit on the eight main storms, applied to locked rows, never fit on them):
- **Texas is the noisy state.** Raw calm-night sd 0.803 in Laura's table (4,629 county-nights), 0.625 in Beryl's (5,715), 0.571 in Uri's (2,862); corrected 0.736, 0.525, 0.492. Ian's states run 0.27–0.32 raw and 0.15–0.24 corrected. |% darker| exceeds 1 on 8.2% (Laura) and 9.2% (Beryl) of Texas calm nights raw, 4.8% and 5.8% corrected, against 0.4–0.8% raw in Ian's states. The plan's numbers reproduce exactly.
- **It is not only Texas.** Laura's other states are also noisy (Arkansas 0.50 raw, 7.1% beyond ±100%; Louisiana 0.46, 5.2%; Mississippi 0.43, 4.7%), as are Ida's Alabama, Louisiana and Mississippi (0.41–0.44) and Beryl's Louisiana (0.44 raw). Every other storm-state sits at 0.39 or below raw (most 0.26–0.37; the small CT, DC, DE and NJ samples lower). Gulf states in late summer are the pattern; Texas is its extreme.
- **The plan's suggested causes.** Hanna (Laura's baseline) and Alberto (Beryl's) are **not** the cause: dropping their nights (Jul 24–27, 2020; Jun 18–21, 2024) moves the Texas sd by less than 0.01 (0.803 to 0.794; 0.625 to 0.626). Industrial lights and flares were not tested here (it needs pixel data) and stay a hypothesis. What the tables do show: a few nights carry the spread (Laura's Texas on 2020-08-12, 08-10 and 08-05 has corrected sd 1.65, 1.36 and 1.04 over 159–195 counties each), 12 of Laura's 208 and 8 of Beryl's 249 Texas counties have a calm sd above 1 while the median county sits at 0.25 and 0.34, and the dimmest brightness quintile is noisy but not alone (Laura's second quintile is the worst at 1.10).
- **RD-07 bounds** apply to the corrected values: per storm and state, median in [−0.10, 0.10] and sd ≤ 0.5. Exceptions, logged here: Texas in laura2020 (sd 0.74), beryl2024 (0.53) and uri2021 (median −0.16). Every other storm-state passes (Arkansas in Laura at 0.35 is the next highest sd). Read on raw `pct_darker`, as the plan words RD-07, the exceptions would instead be Texas in laura2020 (sd 0.80, median −0.135), beryl2024 (sd 0.63) and uri2021 (sd 0.57, median −0.144), plus Mississippi in ida2021 (median −0.110), with Arkansas in Laura at the bound (sd 0.50); the test must say which column it reads, and this entry picks the corrected one. The share beyond ±100% is printed per state in S16. Uri's stress score carries the Texas caveat.

## 2026-11-09: Mixed satellites in the training data (D-19; Claude's call; override any)

The final fits (`lockbox_result.json`, provenance) trained on seven Suomi NPP tables (VNP46A2) and one NOAA-20 table (Beryl, VJ146A2, 17,490 rows of 181,060), and scored Helene and Milton, both Suomi NPP. The angle and moon correction and the hybrid pool both satellites' calm nights as if they were one instrument. What the record says about that: Beryl is one of three main storms where the hybrid loses to `wind_timing` on rows at least 10% out under LOSO (+0.4 pp; Florence +1.8 and Idalia +4.0 are the others), its AUC is lower there too (−0.017), and the uncorrected NOAA-20 cross-check gives Spearman 0.625 on Beryl's 7,588 shared county-nights (0.370 on Ida's, 0.081 on Ian's h09v06 build). Decision: this stays as it is for the recorded result and is disclosed. Future work, after the opening: the Suomi-only ablation (drop Beryl, refit LOSO, report the change with storm-level intervals; EV-49 in `ablations.py`, which does not exist yet), each satellite corrected by its own `fit_angle_moon` on its own calm nights before the cross-check, and Beryl's calm-night sd on both satellites in S14. Suomi NPP stopped sending data on 2026-11-01/02, so every future storm is NOAA-20 and a mixed training set is the normal case from now on, which is why the ablation matters.

## 2026-11-10: Wording edits ahead of publishing (Claude's notes)

Ahead of publishing, the wording of the documents was revised, and instructions written for a private repository were changed to read correctly for a public one. An MIT licence and fuller data credits were added. These edits change wording, not behaviour: no rule, number, threshold or code logic changed. Text held in code and settings files changed as well: the app's page title, its description tag and its masthead line (`app/index.html`, `app/src/App.tsx`, `app/src/components/Masthead.tsx`), the names of two app tests, comments in five files, the description field of `pyproject.toml`, and the new licence fields of `pyproject.toml` and `app/package.json` (repeated in `app/package-lock.json`).

Earlier entries of this log were reworded in place in three spots, and the note at the top of the log was rewritten: the first bullet of "Project setup", one sentence of "What the app shows" in "Model choice, written before the lockbox opens", and the last sentence of "What that produced" in D-11. The pass-bar entry is untouched. Docstrings were reworded in `src/blackout/ranges.py` (a frozen model file under LB-21) and in `src/blackout/portfolio.py`; with the docstrings set aside, both files parse to the same code as before.

## 2026-11-11: The public repository starts from one commit (Claude's notes)

The author chose to publish the project as it stands and to keep its development history private. That history holds the earlier committed versions of the files; the public repository holds the current versions only. So the public repository starts from a single commit, and the history stays in a private archive (the development repository, renamed). The first public commit's message names the archive's final commit, and the two commits hold the same files, so anyone who is shown the archive can check that its final commit matches the first public commit.

What this changes for a reader. The commit hashes cited in this log, the README, the test plan, the scorecard and its reading guide, the frozen record and the record of its inputs (`docs/lockbox_result.json`, `docs/lockbox_record.json`), the note beside the bundled sample (`data/sample/predictions_ian_sample.json`), `src/blackout/final.py` and the tests (`2f534f9`, `2187e37`, `7fd2732`, `50d572e` and the others) are commits of the archive and cannot be looked up in the public repository. So the order they establish (the pass bar, then the model choice, then the one opening) rests on the author's record. It was checked against the history during development, and the scorecard's S1a block shows the result (rows LB-41a and LB-41b), but the public repository cannot prove it on its own. Three checks read the history and are skipped there, each with its reason: `test_pass_bar_was_committed_before_any_lockbox_score`, the history half of LB-21 (`test_the_frozen_hybrid_is_the_shipped_hybrid`) and the history half of LB-41 (`test_recorded_run_provenance`). Rows LB-41a and LB-41b of the scorecard need the history as well. When the scorecard is rebuilt in the public repository they say "not checked", and the test that runs them, `test_every_offline_integrity_check_passes_on_the_record`, still passes. So a scorecard rebuilt there must not replace the committed S1a block. The reproduction at the recorded commit (LB-42, not run yet: D-20) needs that commit's files and can be made only from the archive. The three checks still run in a checkout of the archive that also holds the recorded run's own files in `data/processed`: its result and its predictions files, with the times they were written. Those files exist only on the machine that made the run. Without them LB-41 is skipped, as it always was, and the pass-bar test checks only that the pass-bar commit is in the log.

What can be checked without the history. The frozen result still hashes as recorded (LB-45). The run recorded a hash of five of its code files (`provenance.code_sha256_16` in `docs/lockbox_result.json`: `model.py`, `hybrid.py`, `ranges.py`, `evaluate.py` and `final.py`). Two of them, `src/blackout/model.py` and `src/blackout/hybrid.py`, still hash to those values: they hold the curve and its angle and moon correction, the wind-only guess, the hybrid and its twin without the satellite. LB-21 now asserts this, with or without the history. `src/blackout/ranges.py` no longer matches its recorded hash, because its module docstring was reworded in two places on 2026-11-10 (the entry above). `final.py` and `evaluate.py` changed on 2026-11-09, after the opening: `final.py` when the record was frozen and the guard against a second opening was added, `evaluate.py` when the scorecard gained its S1a block. Those two files as they were at the run are in the archive only.

What changed in the files on 2026-11-11. In the tests: the pass-bar ordering test and the history half of LB-21 are skipped where HEAD does not descend from the pinned commits (before, the pass-bar test skipped only on a shallow clone and would have failed in a repository of one commit); LB-21 gained the hash assertion above; LB-41 now makes the assertions that need no history before it skips; and the two tests that scan the tracked files are skipped in a folder git does not manage, such as an unpacked ZIP download. A `.gitattributes` file keeps every file byte for byte on checkout, so that the hash checks hold on a system that would otherwise convert line endings. `.gitignore` covers more names of secret files and the reproducibility report. The `ci` workflow now asks for read-only access to the repository, and comments were reworded in both workflow files (the tests read the development history where the checkout has it; the two timed runs were made in the development repository). Notes saying where the cited commits are were added to the README and the test plan, and one sentence each to the note at the top of this log and to the first line of the scorecard's reading guide. The reproducibility plan now says that its secret and its two GitHub runs belong to the development repository, and gives the test counts with and without the history. The write-up's opening note no longer says that everything in it can be rerun from a fresh clone: the leave-one-storm-out numbers can, and the lockbox numbers are a one-time record. The README's full-run steps no longer end with an export that cannot work on a fresh build. The first paragraph of the entry above (2026-11-10) was rewritten: its first and third sentences were reworded, and a new last sentence lists the text that changed inside code and settings files, which the paragraph had left out when it said that no line of code changed. No rule, number or threshold changed, and no file under `src/` changed. The two GitHub Actions runs cited in `docs/reproduce/plan.md` were made in the development repository, so they are to be repeated in the public one.

The runs in the public repository. The two GitHub Actions runs were repeated there later the same day (US Pacific time), at the repository's first commit and with a secret of its own: level 1 (run 43123990314) passed in about 3 minutes and level 2 (run 43124409121) in about 5. Level 0, which needs no token, had passed there earlier that day, before the secret was added (run 43054704975). Anyone can open these runs on the repository's Actions page. The files changed once more for this: the reproducibility plan lists the runs and gives the test counts of a fresh clone, and the README and the comment in the `reproduce` workflow say that levels 1 and 2 were each timed twice. No code, rule, number or threshold changed.

The runs on Colab. Later the same day (US Pacific time) the notebook was opened in Google Colab from the public repository and run once at level 1 and once at level 2, on the free CPU runtime (12.7 GB of memory): level 1 passed in about 4.5 minutes, and level 2, in the same session right after it, in about 5.5. Both times are far below the estimates written before anything had been timed there (15 to 25 and 35 to 60 minutes), so the README's table, the notebook's table and the title of its second cell, and the two usage lines at the top of `scripts/reproduce.py` now give the measured times. A Colab run leaves no public record, so the reproducibility plan's note is the record of these two. No rule, number or threshold changed, and no code beyond comments: those two lines of the script's docstring, which `--help` prints, and the title line of the notebook's second code cell, which had said about 2 minutes for a step that took 14 seconds.
