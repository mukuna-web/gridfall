# Blackout from Space: test plan

> **Status, 2026-11-11.** This plan describes the repository as it stood at `966313a` on 2026-11-09; read it as a record. Some tests it lists as backlog were never written, and "the user" is the project's author. Three things have changed since: the project is on GitHub, where the `ci` workflow has run on pushes since 2026-11-09 (in the development repository until the public one was created); the `reproduce` workflow, added afterwards, reads the Earthdata token from a repository secret, which §6 rules out for the tests planned here; and the project has a public repository. That repository starts from one commit, so the commits this plan names are not in it: they are in the private development archive, and the tests that need them are skipped wherever that history is missing (README, project notes).

Revised 2026-11-09 at HEAD `966313a`, after a completeness review of the first draft (written at `88fd9e3`). It merges six audits (evaluation design, requirements trace, data, build, model and product layers) and the review. The review notes at the end say which review findings were accepted, adapted or rejected, and why.

**The lockbox has been opened.** Commit `50d572e` (2026-11-08 23:57 PST) records one run of `blackout lockbox` with the code of `7fd2732`, committed about two and a half minutes earlier. Commit `19b37e4` then wrote the results into the README, `docs/writeup.md` and `docs/failures.md`. The author of this revision did not read `data/processed/lockbox_result.json`, any locked table or export, or the lockbox parts of those docs or of `docs/scorecard.md`, as this workflow requires. So this plan does not state the verdict. It says how to check that the one opening was done as committed, how to read its result, and how to test everything else.

Most of the first draft's machinery for the run before the opening is now history: the readiness gate, `--confirm`, the dress rehearsal and the file tripwire. Two things replace it: §0.3 checks the integrity of the recorded run, and LB-13 and LB-39 make sure there is no second opening.

**State at `966313a`.**
- **Tables.** All eight main tables are built, plus uri2021 and the NOAA-20 cross-checks ian2022_vj146a2 and ida2021_vj146a2. Beryl's own table has been NOAA-20 since `06021bc`; its Suomi NPP table, `county_nights_beryl2024_vnp46a2.parquet`, is kept for the cross-check.
- **Scorecard.** `blackout evaluate` has run on all eight main storms, writing `loso_predictions.parquet` and `scorecard_loso.parquet`. `docs/scorecard.md` was committed in `50d572e` and now has a lockbox section.
- **Tests.** All 332 committed Python tests pass in 25 s. That count excludes `tests/test_lockbox.py`, which this revision did not run because it reads the tracked lockbox exports. Line and branch coverage of `src/blackout` is 92%; the lowest module is `final.py` at 77%. CI (`a51071b`) enforces `--cov-fail-under=80` on lines only and has an app job (npm ci, tsc, vitest, build). The repo still has no remote, so CI has never run. The app has 14 vitest files with about 93 cases.
- **Decision log.** The "Model choice" entry (`2187e37`) and its correction and edge rules (`7fd2732`) were committed before the opening. The verdict stays on the isotonic curve. The hybrid is post hoc and secondary, with its own pre-registered test against wind_timing. The hyperparameters in `hybrid.TREE_PARAMS` are frozen. `hybrid.py` and `model.py` did not change between `2187e37` and `7fd2732`.
- **Committed after the opening (`50d572e`).** `data/sample/predictions_ian_sample.parquet`, written by `scripts/make_sample_predictions.py` from `run_final`'s `predictions_ian2022.parquet`, and `app/public/data/` for every storm, the locked storms included. `966313a` then changed the export so every range contains its point, and relabelled the app. Both are product changes made after the opening (§0.2).

**What changed since the first draft** (each commit and its effect on this plan):
- `db246a9` made the final fits read each storm's own table: they had opened Beryl's Suomi NPP table, which lacks the week after landfall.
- `db246a9` also made LOSO drop the held-out storm's county-nights that sit in other tables. Michael's table held 1,206 of Florence's scored rows.
- `db246a9` turned the hybrid's early stopping off and made `predict` refuse a batch without baseline nights.
- `f00d683` added pooled diagnostics (`evaluate.diagnostics`).
- `7792285` and `38ff164` added the satellite increment (hybrid minus wind_timing).
- `c594d56` added static lockbox scans (`tests/test_lockbox.py`) and the export guard (`export.LockboxClosedError`).
- `7fd2732` added strict loading of the main tables, dropped training rows whose (fips, night) also appears in a locked or stress table, recorded provenance, and wrote `final.satellite_test` with the edge rules.

**Sections.** 0 Evaluation plan · 1 Purpose and principles · 2 Test layers · 3 Fixtures and data · 4 Traceability matrix · 5 Test catalog · 6 CI plan · 7 Backlog · 8 Risks and limits · Review notes.

**Test IDs.**
- **Areas:** LB lockbox, pass bar and `final.py`; EV evaluation diagnostics; RD real data; MD model layer; DL data layer; BL build layer; PX product (Python); CT Python–TypeScript contract; AU app unit; WB browser; RH repo, CI and docs.
- **Priorities:**
  - **P0-I (integrity):** a wrong number in the recorded verdict could stand unnoticed, or the lockbox could be opened twice.
  - **P0-R (release):** a wrong number could reach the app or the fresh-clone demo.
  - **P1** and **P2** follow.
- **Other labels:** decisions D-1 to D-20 (§0.15); scorecard sections S1 to S16 (§0.16); backlog items B-01 to B-34 (§7). IDs dropped since the first draft are listed in §5.11.

---

## 0. Evaluation plan: is the model any good?

### 0.1 The questions, and the evidence from before the opening

- **Q1 Accuracy.** On storms it never saw, does the estimated % of customers out per county-night track EAGLE-I better than guesses that use only the storm track and the calendar? Three aspects count: the level, the change from night to night, and the restoration timing.
- **Q2 Honest uncertainty.** Do the 80% ranges hold about 80% of held-out official values, including on rows where something is happening?
- **Q3 Duration.** Do restore days and restoration intervals match EAGLE-I?
- **Q4 Product.** Three questions:
  - Does "expected policies without power at hour 72" track what EAGLE-I implies for the same synthetic book?
  - Does the claim check separate inflated claims from honest ones?
  - Does the 72-hour trigger beat a wind trigger on basis risk?
- **Q5 Honesty.** Was anything fit, tuned or chosen with Helene or Milton in view, and was the one opening done as committed?

**Leave-one-storm-out (LOSO) on the eight main storms at ±60.** These figures come from `docs/scorecard.md` as `blackout evaluate` wrote it on 2026-11-08 at 23:41, before the lockbox section existed. They are pooled over 11,983 scored county-nights.

| Method | County error (pp) | Error where official ≥ 10% (pp) | Bias (pp) | AUC for ≥ 50% out | Change Spearman |
|---|---|---|---|---|---|
| isotonic (pre-registered) | 2.42 | 38.8 | −1.76 | 0.747 | 0.065 |
| wind_only | 2.63 | 36.5 | −1.23 | 0.820 | n/a |
| nothing | 2.17 | 39.8 | −2.17 | 0.500 | n/a |
| hybrid (shipped, post hoc) | 2.95 | 24.1 | +0.69 | 0.955 | 0.189 |
| wind_timing | 2.84 | 25.7 | +0.37 | 0.934 | 0.215 |

Per-storm facts from the same scorecard and from the "Model choice" entries:
- **Isotonic curve.**
  - Its restore-day error is 4.0–9.0 days on every main storm, so under LOSO it fails pass-bar condition 3 on all eight.
  - It beats wind_only's county error on 6 of 8 storms and "nothing" on 1 of 8.
  - Its largest estimate on a scored county-night is 9.5%, so it misses all 197 county-nights officially at least half out.
  - On its peak night it reaches a median 9% of the official peak total.
- **Restore errors of 2 days or less** (condition 3): the hybrid on 3 of 8 storms (Michael, Laura, Idalia); "nothing" on 4 of 8 (Michael, Laura, Isaias, Idalia). Condition 3 rewards counties that never lose power.
- **Hybrid peak totals:**
  - The estimate is 0.35× the official peak (Ida) to 3.40× (Florence), median 1.27×; it lies in [0.5, 2] on exactly 6 of 8 storms.
  - About half of its at-least-half calls are false alarms: 36 of 75.
- **Satellite increment** (hybrid minus wind_timing) on rows at least 10% out:
  - It favours the hybrid on 5 of 8 storms. Florence (+1.8 pp), Idalia (+4.0) and Beryl (+0.4) go the other way.
  - Pooled it is −1.6 pp, and −0.4 without Ida. AUC is +0.021.
- **Forward chaining** means each storm is predicted only from storms that landed earlier, as the lockbox fits were (decision log, 23:50). Under it the hybrid's error on rows at least 10% out rises to 28.7 pp (LOSO: 24.1). The increment shrinks to −0.6 pp and +0.014 AUC.
- **Calm-night noise:**
  - The raw standard deviation of % darker is 0.431 pooled, and 0.344 after the leave-one-storm-out correction (0.798 × raw).
  - Laura's is 0.666 and Beryl's 0.595. Within Texas it is 0.803 (Laura) and 0.625 (Beryl), against 0.27–0.32 in Ian's states.
  - |% darker| exceeds 1 on 8.2% and 9.2% of Texas calm nights, against 0.4–0.8% for Ian.
- **Data volume:**
  - Over-counts dropped at ±60: Ida 36 of 11,711 values (0.31%), Laura 38 of 26,089, Michael 28 of 23,864.
  - Measurable share of hit-county nights: 39% (Beryl) to 73% (Idalia).
  - 197 county-nights are officially at least half out, across 84 storm-counties; a third of them are Ida's.

What this means:
- The pre-registered curve was on course to fail before the opening. No expected-outcome entry was logged (the first draft's D-14 was never written). The "Model choice" entries are the closest record.
- Every main storm's hybrid row is in the design loop. The hybrid was designed after LOSO results on the first five main storms (`88fd9e3`). It changed at `db246a9`, after all eight were visible. LOSO numbers are therefore optimistic; forward chaining shows by how much. The locked storms, and Uri (first scored by committed code at the opening), are the only evidence from after the freeze.
- The bar has known weaknesses:
  - "Nothing" meets condition 3 more often than the hybrid does.
  - A perfect predictor can fail it: in the first draft's probe, official truth on ok nights gave restore errors of 2.0, 1.0 and 3.0 days on Florence, Michael and Ian.
  - Timing decay alone can meet condition 2, as the "Model choice" entry says.
  
  S8 prints these ceilings and nulls beside the verdict. The bar itself never changes.

### 0.2 What counts as evidence now

| Tier | What | Code | Status |
|---|---|---|---|
| (A) Pre-registered, scored once | Pass bar on the isotonic curve (`2f534f9`): per locked storm at ±60, (1) curve error strictly below wind-only's on the same rows; (2) pooled first-difference Spearman ≥ 0.3; (3) median restore-day error ≤ 2.0 days. Verdict: pass, partial or fail. A storm the drop rule removes leaves the other storm alone, and the verdict says so. Uri is scored apart. ±30 and ±90 are reported beside ±60 | `final.pass_bar_check`; the verdict is computed inline in `run_final` at `7fd2732` | Scored at `50d572e`; §0.3 checks it |
| (B) Pre-registered, scored once | The hybrid's satellite test against wind_timing (`2187e37`, edge rules in `7fd2732`). Per locked storm: (1) error on rows ≥ 10% out lower, and (2) AUC for ≥ 50% out higher. A storm is evaluable only with ≥ 10 rows at ≥ 10% out; the AUC condition needs ≥ 10 rows at ≥ 50% out. Verdict: yes, yes (on the evaluable storm only), partial, no, or not evaluable | `final.satellite_test` on `evaluate.satellite_increment` | Scored at `50d572e`; §0.3 checks it |
| Defined before the opening, descriptive | The Task 7 scorecard columns (`f3ebeeb`); the pooled diagnostics (`evaluate.diagnostics`, `f00d683`); the satellite increment (`7792285`); the hybrid run through the three bar conditions, "for information, not pre-registered" | `evaluate`, `final` | Reported as written, with no thresholds |
| In the design loop | Every LOSO number for the hybrid and wind_timing on the eight main storms | `evaluate.loso_predictions` | Optimistic: it can lower a claim but never support one alone |
| After the opening | Everything this plan adds in §0.4–§0.12, and any change to a model or to the export after `50d572e` (including `966313a`) | new code | Exploratory; labelled "defined after the opening"; never a new verdict |

Rules:
- **The recorded result is final.** If a §0.3 check finds a defect, the defect and the reading under the committed rule are disclosed beside the recorded numbers (D-20). The lockbox is not re-run to replace them; LB-13 and LB-39 enforce this.
- **A change after the opening makes a new model or product.** This covers model fixes this plan asks for (MD-45, D-11) and export changes such as `966313a`. Their numbers on Helene, Milton or Uri carry the label "after the opening, not held out" (EV-48). Their only clean test is a storm that has not been built yet (§8).
- **Ian's row is always labelled LOSO** (decision log, 2026-11-07).

### 0.3 Integrity of the recorded opening (P0-I)

| Check | How | Test |
|---|---|---|
| **The record is frozen** | Copy `data/processed/lockbox_result.json` to `docs/lockbox_result.json`, commit it, and pin its sha256 in a test. The local file must stay byte-identical | LB-45 |
| **The inputs are recorded** | Write `docs/lockbox_record.json` with: the sha256, as they are now, of every table the run read (8 main, 2 locked, Uri); the sha256 of `uv.lock`; and the Python, numpy, pandas, scikit-learn, scipy and pyarrow versions. Each table's mtime must be earlier than `provenance.run_at_utc`; otherwise it was rebuilt after the run, and the record says so | LB-44 |
| **Provenance** | `provenance.git_head` descends from `2f534f9`, `2187e37` and `7fd2732`. `working_tree_dirty` is false. Each `code_sha256_16` matches its file at that head. `training_tables` lists the 8 main storms, with beryl2024 as `county_nights_beryl2024.parquet` (VJ146A2). `run_at_utc` lies between the commit times of `7fd2732` and `50d572e` | LB-41 |
| **One run** | The code that ran writes predictions inside its loop and the JSON last, with no marker and no guard against reruns, so a crash and rerun would leave no trace. The evidence: every `predictions_*.parquet` mtime falls within minutes of `run_at_utc`, and the person who ran it states the number of invocations. Both go into D-20 | LB-41; D-20 |
| **Reproducible** | Refit at `provenance.git_head` in a git worktree, writing outputs to tmp. Every number in pass_bar, hybrid, stress, trigger, satellite_increment, satellite_test and verdict reproduces, exactly or to the JSON's rounding. This is a reproduction with the recorded code and data. It never replaces the record | LB-42 |
| **The verdict follows the committed rule** | The code computed "pass if both pass, partial if any passes, fail otherwise", with no drop rule and no "no verdict". Recompute with `final.verdict` (LB-08) and `table.drop_check` on each locked table | LB-40, LB-08, LB-10 |
| **The verdict comes from the curve** | `results["pass_bar"]` holds the isotonic curve's checks and `results["hybrid"]` the hybrid's | LB-36 |
| **Locked truth uses the repaired customers** | The customer repair (`c85da09`) came after the bar commit. `table.refresh_customers` has no callers, so refreshes were made by hand (michael2018 was found stale earlier). Helene's states include North Carolina, where every county was repaired. Compare each locked table's customers with `load_counties(storm.states).customers`. If any differ, recompute the three conditions with `table.with_customers` truth on LB-42's reproduced predictions, and show both readings | LB-43 |
| **The satellite test follows its edge rules** | Recompute (B) from the recorded `satellite_increment` rows; the keys it reads must exist (no `.get` default) | LB-37 |
| **Nights align** | Check that night-to-night changes in darkness and in official % out agree best at lag 0 on the main storms. An off-by-one night would void every number | RD-24 |
| **Deviations disclosed, not fixed** | Before the final fits, the run read the locked and Uri tables in full (`pd.read_parquet` without `columns=`) to take their (fips, night) keys; only the keys were used (`drop_shared_county_nights`). It also ran with no `--confirm`, no opening marker, no expected-outcome entry (D-14) and no frozen diagnostics entry (D-2 of the first draft) | D-20 |

**Disclosure rule.** A failed check stays red until two things are done:
- D-20 in the decision log names the defect.
- S1a prints the recorded number beside the reading under the committed rule (LB-40) and the repaired truth (LB-43).

The verdict line then leads with the committed-rule reading. It says that this reading differs from the recorded string, and why. No model is changed: LB-42 and LB-43 reuse the recorded code.

### 0.4 Methods and baselines, scored on identical rows

| Method | Code | What it knows | Role |
|---|---|---|---|
| nothing | `model.fit_nothing` | nothing: 0 on ok rows | The floor; it shows how much exact zeros reward a do-nothing guess |
| wind_only | `model.WindOnly.fit` | Wind band. Its means are taken over the plan's training rows, baseline nights included | The comparator the bar names for condition 1. It stays as specified (D-13), although baseline nights dilute it |
| wind_timing | `hybrid.fit_wind_timing` | wind band and days since landfall | The fair baseline with no satellite input |
| isotonic | `model.fit_translation` | corrected % darker | The pre-registered model; the verdict is judged on it |
| hybrid | `hybrid.fit_hybrid` | corrected % darker, the county's calm-night noise, wind band, days since landfall, brightness, moon, view angle, visible share | Shipped and secondary; the app shows it |
| persistence (P2) | `diagnostics.persistence` (new) | the previous scored night's official value | A reference only, since it uses EAGLE-I itself; it never enters a reading |

Rules:
- **One implementation.** `evaluate.diagnostics` and `evaluate.satellite_increment` move into `src/blackout/diagnostics.py`; `evaluate` imports them, so they are moved, not copied. Every method is scored on `diagnostics.common_rows(preds, methods)`: the pass bar's scored rows where every compared method is finite. Today `diagnostics` scores each method on its own finite rows. Condition 2 statistics always come from `final.first_difference_agreement`. AUC uses ranks with ties averaged and must equal `sklearn.metrics.roc_auc_score` (EV-45).
- **Paired differences.** Differences are taken per row, then aggregated (§0.7).
- **What the satellite adds** is the difference between the hybrid and wind_timing. "Beats wind-only" alone is not evidence of skill.
- **Three ways to hold storms out:** LOSO (design loop), forward chaining (EV-47: only earlier storms train, like the lockbox), and the recorded run on the locked storms.

### 0.5 Headline diagnostics

**Defined before the opening** (`evaluate.diagnostics`, `f00d683`):
- county error (pp);
- error where official ≥ 10% (`mae_big_pp`);
- bias;
- AUC for official ≥ 0.5;
- pooled Spearman of night-to-night changes.

**Added after the opening, descriptive:**
- RMSE, and MSE skill = 1 − MSE / MSE_ref against nothing and against wind_timing (P1). Isotonic regression estimates a conditional mean, whose consistent score is squared error; MAE rewards the conditional median, which is 0 on about three quarters of rows.
- The plan's catch and false-alarm rates with their denominators: n_pos_50 for the catch rate (a recall) and n_calls_50 for false alarms (a share of calls). Both are NaN, never 0, when the denominator is 0 (P1).
- Outage-weighted measurable share: the official customers out on ok rows divided by the same sum over all hit, covered event rows (P1).
- Customer-weighted error, totals ratio, within-night AUC, average precision, reliability and expected calibration error (ECE), and false darkening on wind band 0 (all P2).

**Constants**, pinned by LB-03 and EV-01: ACTIVE_CUT 0.10 (= `evaluate.RESTORE_THRESHOLD`); OUT_CUT 0.5; HIT_BAND 34; CAL_BINS [0, .01), [.01, .05), [.05, .10), [.10, .25), [.25, .50), [.50, 1]; MIN_ROWS 30; MIN_COUNTIES 5; MIN_POSITIVES 10; BOOTSTRAP_B 2,000; SEED 20261105; CI_LEVEL 0.90.

### 0.6 Slices (exploratory)

- **P1:** storm; state; night after landfall (0–3, 4–7, 8–21); wind band 34, 50 and 64, with band 0 as the control. The state slice is where the Texas noise shows.
- **P2:** brightness quartile; visible share; customers source (mcc vs housing); moonlit vs dark; sensor zenith; cloud gaps; a "shadow" table of uncovered states.
- **Reporting:** each slice reports rows, counties, county error, error where official ≥ 10%, bias and AUC at 0.1 (where n_pos ≥ 10), on identical rows. Cells under MIN_ROWS or MIN_COUNTIES print n only.

### 0.7 Uncertainty

- **Storm level (P1).** For the 8 main storms: the mean over storms with a t-interval (df 7), and a storm-cluster bootstrap percentile interval (B 2,000, seed 20261105). For paired method differences: wins k of n and a one-sided sign test (7 of 8 gives p = 0.035; 6 of 8 gives 0.145).
- **Within one storm (P1).** A county-cluster bootstrap that resamples whole counties with all their nights, one resample shared by every method. This is the only interval available for each locked storm, and those intervals are descriptive and computed after the opening.
- **P2:** a two-stage bootstrap (storms, then counties) and a state-cluster bootstrap.
- **Credibility rule.** A comparative claim ("beats X") needs at least 7 of 8 storms and a 90% storm-level interval that excludes 0, and it is still labelled "design loop". Two locked storms can show gross failure; they cannot establish significance alone.

### 0.8 Range and duration calibration

- **Ranges.** `ranges.fit_ranges` takes the 10th and 90th percentiles of official − pred within prediction bins. Report:
  - coverage = mean(lo ≤ official ≤ hi);
  - mean width;
  - the interval score at alpha 0.2: (hi − lo) + 10 × max(lo − y, 0) + 10 × max(y − hi, 0).
  
  Break these out pooled and by range bin, storm, night bucket and active rows. Main storms use nested LOSO: storm S's ranges come only from the other storms' LOSO residuals. The ranges `run_final` writes for main storms (and so `predictions_ian_sample.parquet`) are fit on all main storms' residuals. Their coverage is in-sample and is labelled so (MD-33). Active-row coverage always prints beside pooled coverage. Targets: pooled 0.75–0.90, active rows ≥ 0.60.
- **Restore day.** Print the bar's statistic (`evaluate.official_restore_day`) beside a split into "out" counties and "never-out" counties (EV-21); the decision log promises this split and `evaluate.py` does not compute it yet. Add the nulls of §0.9, and a note that Laura's and Uri's first pass after landfall is filed under the night before landfall (DL-57, D-16).
- **Restoration intervals and hour brackets** at 24, 48 and 72 h from `Storm.landfall_time`: interval coverage, closed width, open and unknown shares, and bracket coverage.

### 0.9 How strong is the bar: ceilings and nulls

Run `final.pass_bar_check` itself (one code path) on predictors with no satellite skill (EV-10, S8):
- the **perfect predictor**: cleaned official truth on ok rows;
- **nothing**, **wind_only** and **wind_timing**;
- a **time-only decay** fit on the other storms;
- **county and night shuffles** of the satellite inputs (P2).

Run these LOSO on the main storms. Then, after the opening and labelled so, run the same ceilings on each locked storm (RD-20). That shows how much of the recorded result the bar's structure explains. A pass that the nulls also achieve is not evidence of skill. LOSO dry runs of the curve and the hybrid (RD-21) go in the same table.

### 0.10 Sensitivity and ablations (main storms; after the opening)

Change one knob at a time, refit LOSO, and report the change (variant − shipped) with paired storm-level intervals and rows_scored (`ablations.run_ablations`, `blackout ablate`, S13). Never on a locked or stress storm (EV-35).

| Knob | Priority | Note |
|---|---|---|
| Suomi NPP only (drop Beryl) | P1 | The final fits trained on 7 Suomi storms and 1 NOAA-20 storm and scored Suomi locked storms (D-19) |
| Training population: all nights (as shipped), event window only, hit counties only | P1 | The "Model choice" entry says the curve's refits on event nights only did no better |
| Truth window ±30 / ±90 | P1 | Already in the tables |
| Dropout rule off; customer repair off; angle and moon correction off; over-count variants; stricter visible-share or DARK_MIN cutoffs; rebuilds with a looser cutoff or a different baseline length under a separate storm id | P2 | as in the first draft |

### 0.11 Robustness

- **Uri (stress).** The final fits scored it once at the opening, after the freeze. It is printed with three caveats: the EAGLE-I dropout constants were tuned partly on Uri; snow is allowed; and Texas calm-night noise is high (0.80 and 0.63 in Laura's and Beryl's tables). It never enters a fit or the verdict (LB-16).
- **NOAA-20 and Suomi NPP.**
  - Beryl's own table is NOAA-20. Its cross-check is the kept Suomi table, which lacks the week after landfall, so Beryl has few event-night pairs. Ian (tile h09v06) and Ida (four tiles) are cross-checked on NOAA-20 core-tile builds.
  - `fit_angle_moon` and the hybrid pool both satellites' calm nights. The final fits mixed 7 Suomi storms with 1 NOAA-20 storm and scored Helene and Milton, which stay on Suomi (D-19).
  - Checks:
    - agreement of corrected % darker, each satellite corrected by its own `fit_angle_moon` on its own calm nights (Bland-Altman bias and 95% limits);
    - Lee's darkest night and half-recovery gap (`final.lee_on_noaa20`);
    - the downstream score, using a Suomi-only fit (§0.10);
    - Beryl's calm-night standard deviation on shared baseline nights in its own table and in the `_vnp46a2` table (S14).
  - Suomi NPP stopped sending data on 2026-11-01/02.
- **Clouds.** Metrics by nights since the county's previous ok night and by ok nights in days 0–7 (P2).
- **Data design** (D-16, D-17):
  - Laura's first post-landfall pass (07:50 UTC on Aug 27, 1 h 50 min after landfall) is filed under night 2020-08-26 and scored nowhere. At that pass 296,252 customers were out in hit counties, and 6.5% of hit counties were seen. Uri's first pass after onset (07:24–09:07 UTC on Feb 15) is filed under night 2021-02-14.
  - Other tropical storms crossed project storms' counties at 34 kt or more:
    - **In baselines:** Hanna in Laura's (16 TX counties, Jul 25–26 2020); Fay in Isaias's (37 counties in CT, DE, MD, NJ, NY, VA); Fred in Ida's (6 AL counties); Alberto in Beryl's (19 TX counties, Jun 19–20 2024).
    - **Inside event windows:** Sally in Laura's (4 LA and MS counties, Sep 12–17 2020) and Nicholas in Ida's (4 LA parishes, Sep 12–14 2021).
    
    DL-58 computes the same check for the locked storms from config and HURDAT2 only.

### 0.12 Product-level evaluation (descriptive; no product target was logged before the opening)

Everything runs on the synthetic book (`portfolio.make_portfolio`: 100,000 policies, 5% business, seed 20261105), using `src/blackout/product_eval.py` (S15). LOSO rows are labelled design loop. Locked-storm rows use the recorded `predictions_<storm>.parquet`, labelled "recorded run". The ranges in exports after `966313a` are the export's own clamp of those predictions, and the scorecard says so.

- **Portfolio headline.** Compare `export.expected_policies_out` at 24, 48 and 72 h from `Storm.landfall_time` with the same book scored by official fractions at the same two passes. Report:
  - whether the official total lies inside [low, high];
  - whether it lies inside the factor-of-two band [low / 2, 2 × high];
  - the midpoint relative error;
  - the share of policies in counties the satellite could not see;
  - officially-out policies in those unseen counties.
- **Claim check.** Run a Python twin of `claimVerdict` on the labelled synthetic claims. Report inflated recall, the honest false-review rate and the unverifiable share. Repeat with an **oracle** that uses official values in place of the range's high end; the oracle separates estimate error from the mismatch between the labels' absolute 10% rule and the verdict's relative 90%-of-peak rule.
- **Trigger.** "County above 50% out at 72 h" (`final.trigger_view`). Report paid correctly, paid wrongly, missed, correctly unpaid and unknown, against a wind trigger that pays every band-64 county. Truth follows the bar's over-count rule and is read at the same two looks (D-6).
- **Days dark.** The share of hit counties whose official restore day lies in the card's interval (lo, hi].

### 0.13 Leakage guards after the opening

| Guard | Why it still matters | Tests |
|---|---|---|
| No fit trains on locked rows (`check_no_lockbox`; an allowlist of fit functions) | A new model trained on Helene or Milton and then scored on them would pass for a held-out result | LB-18, LB-19, LB-32 |
| No second opening; the first result is immutable | A rerun after a "fix" is a second look | LB-13, LB-39, LB-45 |
| Scores of post-opening models on locked or stress storms are labelled | So they cannot pass for held-out results | EV-48 |
| LOSO folds never see their own storm, including its county-nights filed under another storm (`test_loso_drops_the_held_out_storms_county_nights_from_other_tables`), and never receive truth columns | LOSO is the design-loop evidence | LB-20, MD-05, MD-15 |
| The bar's text and constants are the committed ones | No editing of the bar after the fact | LB-02, LB-03 |
| The app shows the frozen hybrid, or says it does not | The claim "the app shows the tested model" | LB-21, MD-46 |
| Static scans: `tests/test_lockbox.py` (`c594d56`), extended to `scripts/`, `tests/` and wildcard patterns | Regression | LB-23 |
| The next holdout | A file tripwire, self-tested with a canary id, for any future held-out storm | LB-01 (P2) |

### 0.14 Acceptance definition

Written without reading the locked results, but after the opening. It is a reading guide, not a pre-registered test, and it is logged as D-2.

The **verdict** (A) is the committed pass bar's, under the committed rule (LB-40) and the repaired truth (LB-43). The **satellite test** (B) is the committed edge rules' result. The reading maps the two:

| (A) pass bar on the curve | (B) satellite test (hybrid vs wind_timing) | Reading |
|---|---|---|
| pass | yes | **WORKING**: the pre-registered curve passed, and the shipped model's satellite input added value on the locked storms |
| pass | partial, no or not evaluable | **WORKING** for the curve; the satellite's part in the shipped model is not shown |
| partial | any | **PARTIAL**: say which storm passed, which condition failed, and the (B) result |
| fail | yes | **NOT WORKING as pre-registered**. Say plainly that the secondary, post hoc model's satellite increment held up on the locked storms |
| fail | partial, no or not evaluable | **NOT WORKING** |
| no verdict (both storms dropped or unscorable) | any | **INCONCLUSIVE** |

Preconditions and wording rules:
- **Integrity.** The reading stands only if every §0.3 check passes, or every failure is disclosed (D-20) and the reading uses the corrected values.
- **Descriptive numbers qualify the wording but never move a row.** Examples: the forward-chaining error, the hybrid's county error being worse than "nothing" (2.95 against 2.17 pp under LOSO), and the nulls in S8. If a null also meets a condition that the curve met, the write-up says so.
- **Labels.** Any statement about a slice says "exploratory". Any number from after the opening says "defined after the opening". Any LOSO number says "design loop".
- **Code.** `diagnostics.reading(verdict, satellite_test, integrity)` implements the table (EV-30).

### 0.15 Decisions, and the post-opening checklist

**Decisions** (entries in `docs/decision-log.md`):
- **D-1 Model choice.** Done in `2187e37`; corrected, with edge rules, in `7fd2732`.
- **D-2 Reading rules after the opening.** §0.2, the disclosure rule of §0.3, the §0.14 table and the EV-48 labels.
- **D-3 Restore-day conventions.** Correct the 2026-11-08 sentence: under `official_restore_day`, a county never above 10% is back at the first reading after its first maximum. The county card's `export.official_restore` dates it to the first reading instead. Decide whether `restoration_interval` adopts the rule of "after the peak, held 24 hours", or the card labels the two differently. Add the error for counties that were out (EV-21).
- **D-4 Michael's baseline.** It holds 22 nights of Florence's event window in GA, NC and SC. LOSO drops those county-nights since `db246a9` (an effect of 0.2 pp or less). The calm-night sets used by `fit_angle_moon` and `county_noise` still include them. Disclose this.
- **D-5 Helene's window contains Milton's landfall.** Disclose it, and print a pre-Milton Helene number in S14, labelled as defined after the opening.
- **D-6 Trigger truth.** Official at the same two looks as the estimate, after the over-count rule; the wind trigger is the comparator.
- **D-7 Definitions.** Use "at least half"; false_alarm_50 is a share of calls; measurable_share counts hit county-nights.
- **D-8** `claimVerdict` reads the range's high end both at the peak and on the claimed day.
- **D-9** `app/public/data` is committed (`50d572e`). Exports are regenerated with a fixed clock.
- **D-10** The index names a default demo storm.
- **D-11 Ranges.** The fix for exact-zero inflation and the training population. This is a product change made after the opening.
- **D-12 No second opening.** The first result is immutable. A reopen needs a decision-log entry giving the reason, and writes a new file.
- **D-13** wind_only stays the plan's comparator.
- **D-14** Record that no expected-outcome entry was logged before the opening, although the LOSO dry run (the curve fails condition 3 on all 8 main storms) was visible.
- **D-15 Corrections.** Virginia's repaired counties include Norton, and Hamilton NY (36041) was repaired too. Add the empty-count bunching rows for Ian 2022, Idalia 2023 and Beryl 2024, computed from the per-storm extracts and never from the 2024 yearly file. The 2022–2024 files have no empty counts at all.
- **D-16** The first post-landfall pass of Laura and of Uri is filed under the night before landfall.
- **D-17** Other storms inside baselines and event windows (§0.11).
- **D-18** Texas calm-night noise. Likely causes are industrial lights and gas flares in whole-state tables, and Hanna and Alberto in the baselines. The per-state bounds of RD-07.
- **D-19** Mixed satellites in the training data; the Suomi-only ablation.
- **D-20** Findings about the opening's integrity: whatever LB-40 to LB-44 find, the deviations in §0.3, and the single-run statement.

**Post-opening checklist (milestone M-AUDIT)**, which replaces the first draft's readiness checklist:
1. Freeze the record and its inputs (LB-45, LB-44) before anything else touches `data/processed`.
2. Add the guard against a second opening (LB-13, LB-39) before anyone edits `final.py` again.
3. Run the integrity checks locally (LB-36, LB-37, LB-40 to LB-43, RD-24) with `uv run pytest -m lockbox --run-lockbox`. Reading the locked tables in tests is allowed now; they still never feed a fit. Log D-20.
4. Render S1, S1a, S2 and S3 per §0.14, and commit.
5. Log D-2 to D-19 (D-1 is done).
6. Pass the P0-R release gate before the app, README or write-up is shown to anyone.

### 0.16 What `docs/scorecard.md` must contain

| § | Contents | Produced by | Priority |
|---|---|---|---|
| S1 | Verdict (A): per locked storm and window (60/30/90), rows_scored, mae_pp_curve, mae_pp_wind_only, first_difference_spearman, change_pairs, restore_day_median_error, restore_counties, the three checks and passes; the verdict line with drop notes | `final.render_lockbox` from `docs/lockbox_result.json` | P0-I |
| S1a | Integrity of the opening: every §0.3 check, with the recorded and corrected readings where they differ | `final.render_integrity` (new), from LB-40 to LB-44 | P0-I |
| S2 | The shipped model: satellite test (B) per storm with its edge-rule flags; the hybrid on the three conditions, "for information" | `render_lockbox` | P0-I |
| S3 | The reading (§0.14) and the conditions behind it | `diagnostics.reading` | P0-I |
| S4 | The plan scorecard under LOSO, for 8 storms × 5 methods × 3 windows. Beside each rate: n_pos_50, n_calls_50 and the outage-weighted measurable share. Every hybrid and wind_timing row is tagged design loop. Notes give D-16's first-pass and D-17's intrusions | `evaluate.score_all` | P1 |
| S5 | Headline diagnostics (§0.5) with storm-level intervals, wins k of n and the sign test. Forward chaining sits beside LOSO, with the satellite increment | `diagnostics`, EV-47 | P1 |
| S8 | How strong the bar is: nulls and ceilings under LOSO; the same on the locked storms, labelled as computed after the opening; LOSO dry runs | `diagnostics.null_passbar` through `final.pass_bar_check` | P1 |
| S9 | Range calibration: nested coverage, width and interval score; in-sample coverage labelled | `diagnostics.range_metrics`, `nested_range_coverage` | P1 |
| S10 | Duration: the bar statistic with the out and never-out split and the nulls; interval and bracket coverage; the D-16 note | `diagnostics.restore_split`, `interval_coverage` | P1 |
| S14 | Robustness: Uri with its caveats; NOAA-20 corrected agreement and Lee; Beryl's calm-night sd on both satellites; Texas noise | `run_final`, `diagnostics.noaa20_report` | P1 |
| S15 | Portfolio example: headline against official at 24/48/72 h; claim-check confusion with the oracle; trigger against the wind trigger | `product_eval` | P1 |
| S16 | Data quality: over-counts per window, drops, repaired customers, hit counties EAGLE-I never reported, uncovered states, noise by state, D-17 intrusions | `evaluate.overcount_table`, `diagnostics.data_quality`, `model.noise_report` | P1 |
| S6, S7, S11, S12, S13 | Extra detection and calibration, extra visibility, other slices, other ablations. S7's paired differences are folded into S5 | as in the first draft | P2 |

`src/blackout/report.py` (new) takes over the rendering once `evaluate.py` (now 593 lines) would pass 800. Every table starts with a one-line definition, prints denominators beside rates, and prints n beside every headline number.

---

## 1. Purpose and principles

- **Evaluation first.** The first deliverable is S1–S3: the recorded verdict and satellite test, checked for integrity and read per §0.14. The code tests exist to make those numbers, and the app's, trustworthy.
- **Test pyramid for this repo:**
  - hand-computed unit tests on small toys, using binary fractions so that float ties survive;
  - seeded property tests for rules with many edges (restore days, ranges, county noise);
  - offline integration tests on fake tiles (`tests/fixtures/make_fake_tile.py`) and synthetic tables;
  - contract tests on fixtures shared by pytest and vitest;
  - data validation on the real tables, run locally;
  - a few end-to-end browser flows, then visual, accessibility and performance checks on the built app.
- **Offline-first CI.** CI never touches the network or `data/raw`, `data/interim` or `data/processed`; it uses `tests/fixtures/`, `data/sample/` and committed docs only. Tests that need more carry a marker (`realdata`, `lockbox`, `network`, `slow`) and are deselected in CI. Every skip is counted and reported (RH-02).
- **Local runs are faithful to CI.** `scripts/ci_local.sh` runs the CI commands in a temporary clone, so local data cannot quietly turn skipped tests into passing ones (RH-03). On the author's machine `data/raw` exists, and the Census tests run instead of skipping.
- **Lockbox discipline after the opening:**
  - Locked tables may be read by `lockbox`-marked tests and by report code, never by fits (`check_no_lockbox`).
  - Unit tests use fake lockbox ids (`lock2024`, `lock2025`, `lock2099`, `box2024`).
  - Tests never hard-code a locked number; `tests/test_lockbox.py` scans for this.
  - Tests write only under `tmp_path`, never into `docs/` or `data/`.
- **TDD.** Write the test first and watch it fail (§7 lists those red at `966313a`). Fix the code, not the test, unless the test contradicts a logged decision.
- **Coverage.**
  - Python: 80% on lines and branches (`--cov-branch`), with per-module floors. `outages`, `nightlights`, `winds`, `model`, `ranges`, `portfolio`, `evaluate`, `hybrid` and `export` ≥ 90; `final` ≥ 85 once the P0-I tests land, then 90; `table`, `counties` and `laads` ≥ 80.
  - App (`app/src`): 80% on lines, functions and statements, and 75% on branches to start.
- **Determinism.** Seeds (`SEED = 20261105`), a fixed clock for exports (`SOURCE_DATE_EPOCH`) and no sleeps. Playwright waits on locators and on a `data-map-state` attribute (`ready` or `fallback`), never on timeouts.
- **Immutability.** Every public function is checked not to modify its inputs (MD-42).
- **Style.** Arrange / Act / Assert, one behaviour per test, names that state the behaviour.

## 2. Test layers and where each runs

| Layer | Tools | Location | Runs in CI? | Runtime budget |
|---|---|---|---|---|
| Unit | pytest | `tests/test_<module>.py` | yes | whole Python CI suite < 3 min (25 s today) |
| Property | pytest + seeded numpy (Hypothesis optional, derandomized) | inside the module test files | yes | < 60 s |
| Integration (offline) | pytest, fake HDF5 tiles, synthetic tables in `tmp_path` | `test_build_offline.py`, `test_final.py`, `test_cli.py`, `test_export*.py` | yes | < 60 s |
| Contract (Python ↔ TS) | jsonschema, vitest, shared fixtures, a golden export | `tests/test_contract.py`, `app/src/data/contract.test.ts`, `tests/fixtures/contract/` | yes, in both jobs, plus a freshness step | < 10 s |
| Data validation (real tables) | pytest `-m realdata` | `tests/realdata/test_tables.py`, `test_truth.py` | no: local, before committing scorecard numbers and after every rebuild | < 10 min |
| Evaluation report (real) | pytest `-m realdata`, `blackout evaluate` | `tests/realdata/test_gates.py`, `test_report.py`, `test_product.py`, `test_sample.py` | no: local | < 20 min |
| Integrity of the opening | pytest `-m lockbox --run-lockbox` | `tests/realdata/test_after_opening.py` | no: local, once, then after any change to `data/processed` | < 15 min (LB-42 is `slow`) |
| Regression / golden | pytest | Phase 0 Lee values; pass-bar hash; frozen lockbox result; golden predictions; golden export | yes | < 10 s |
| App unit | vitest, happy-dom, Testing Library | `app/src/**/*.test.ts(x)` | yes | < 60 s |
| End to end | @playwright/test | `app/e2e/*.spec.ts` | chromium on every push; firefox and webkit locally before release, nightly once a remote exists | chromium < 5 min |
| Visual | `toHaveScreenshot` in the pinned Playwright Linux container | `app/e2e/visual.spec.ts` (`@visual`) | chromium | < 2 min |
| Accessibility | @axe-core/playwright, keyboard specs | `app/e2e/axe.spec.ts`, `keyboard.spec.ts`, `reduced-motion.spec.ts` | chromium | < 2 min |
| Performance | `app/scripts/check-bundle.mjs`, `app/e2e/perf.spec.ts`, Lighthouse CI (`upload.target: "filesystem"`) | as named | bundle and perf spec in CI; Lighthouse nightly | < 3 min |
| Smoke (network) | pytest `-m network` | `tests/test_network_smoke.py` | no: by hand only, with the user's token in the local environment | < 2 min |
| Fresh clone | shell | `scripts/fresh_clone_check.sh` | locally before release; on main once a remote exists | < 10 min |

## 3. Fixtures and data strategy

**Committed fixtures (keep):**
- `tests/fixtures/eaglei_small.csv`: real EAGLE-I rows for windows A–I (7,496 rows, LF).
- `mcc_small.csv` (BOM, CRLF, no final newline) and `coverage_small.csv` (CRLF), kept byte-exact. DL-53 pins the bytes and adds `.gitattributes` with `tests/fixtures/** -text`.
- `tests/fixtures/hurdat2_small.txt`, `exposure_toy.json` (shared with the app), `make_fake_tile.py` and `build_eaglei_fixtures.py`.
- `data/sample/county_nights_ian_sample.parquet` and `counties_ian_sample.geojson` (Lee, Charlotte, Collier; identical to the real Ian rows).
- `data/sample/predictions_ian_sample.parquet`, committed in `50d572e` from `run_final`'s `predictions_ian2022.parquet`: the hybrid's LOSO estimates with ranges fit on all main LOSO residuals, so they are in-sample for Ian. PX-01 and RD-35 check that it is genuine and current.
- `app/src/__fixtures__/`: synthetic. It is named `milton` today; rename it `synth2099` (CT-07) so no reader mistakes it for lockbox data.
- `app/public/data/`: exports of every storm, committed under D-9 and regenerated with a fixed clock.

**New committed fixtures:**
- `docs/lockbox_result.json` and `docs/lockbox_record.json` (LB-45, LB-44).
- `tests/synthetic_world.py`: one seeded builder, `make_world(storms, counties, seed, cloud_rate, signal, zero_share, overcounts)`, returning frames in `table.TABLE_COLUMNS`. It replaces the per-file `world()` and `storm_table()` builders, and it carries the golden-prediction world for MD-46.
- `tests/fixtures/county_points.csv`: fips, state and the representative-point lon/lat for every storm state (public Census).
- `tests/fixtures/hurdat2_small.txt`, extended with the tracks of storms outside the roster that DL-58 needs (Hanna AL082020, Fay AL062020, Fred AL062021, Alberto AL012024, Sally AL192020, Nicholas AL142021). They are written from `data/raw/hurdat2` by `tests/fixtures/build_hurdat2_fixture.py`.
- `tests/fixtures/contract/golden/<toy id>/` plus `expected.json`, and `app/e2e/fixtures/data/synth2099/`, both written through `export.write_export` with a fixed clock; `--check` regenerates them and diffs (RH-12).
- `tests/fixtures/contract/cases.json` and `tests/fixtures/claims_toy.json`.

**Isolation.**
- Every test writes under `tmp_path`.
- Monkeypatch `table.PROCESSED`, `table.INTERIM`, `table.IMG`, `export.PROCESSED` and `export.APP_DATA`.
- `aggregate.county_label_grid` must resolve its cache directory at call time. BL-04 fails today: the default is bound at import, so the offline build writes `data/interim/labels/` inside the repo.
- Use the real `table.table_path` with a monkeypatched `PROCESSED`, never a lambda that ignores `satellite`. `test_run_final_scores_the_lockbox_once` still uses such a lambda; LB-35 removes it.
- Token tests `chdir` into `tmp_path` first, so the repo's `.env` is never read.

**Never committed:**
- `data/raw/`, `data/interim/`, `data/processed/`;
- `.env` or any token;
- real EAGLE-I rows beyond the fixtures;
- coverage output, `dist-e2e/`, Playwright reports and traces. Screenshot baselines from the Linux container are committed;
- files over 1 MB under `data/sample/` (RH-20).

**Locked tables after the opening.** `lockbox`-marked tests and report code may read them. They never reach a fit or a training frame (LB-18). Their exports exist (`50d572e`); any change to them after the opening, such as `966313a`'s clamp, is labelled in S15.

---

## 4. Traceability matrix

Each new test's file, kind and Arrange/Act/Assert are in §5 under its ID.

### 4.1 Review Focus

| Req | Source | Requirement | Existing tests | New tests |
|---|---|---|---|---|
| RF-1 | Review Focus 1; Task 2 | Zero, missing and dropout are different | test_empty_count_is_nan_and_skipped, test_absent_county_in_live_run_is_zero, test_missing_state_run_is_nan, test_feed_dropout_is_missing, test_partial_dropout_dropped and the other dropout tests (17) | DL-02, DL-06, DL-07, DL-10, DL-11 (P1); BL-13 to BL-15, RD-09, RD-11, RD-12 (P1/P2); DL-39 to DL-41 (P2) |
| RF-2 | Review Focus 2; Tasks 2, 4, 5 | FIPS joins fail silently | test_load_types_and_whole_state, test_parquet_with_integer_codes_rejected, test_mcc_bom_and_padding, test_sample_table_schema; test_no_county_lost_in_join and test_connecticut_keeps_old_counties (skip in CI) | RD-01 (CI), RD-02, RD-03, DL-12, DL-14, DL-15, DL-17, DL-18 (P1); DL-53 (P2) |
| RF-3 | Review Focus 3; Tasks 2, 3, 5 | Nights and timezones can be off by one | test_window_filter, test_night_of, test_pass_time_utc, test_official_at_pass_time, test_landfall_times_match_hurdat2, test_bracket_counts_hours_from_the_landfall_time, app format.test.ts | RD-24 (P0-I); DL-57 first pass after landfall, DL-13, RD-04, PX-13, LB-25, WB-17 (P1); DL-26, DL-43, DL-44 (P2) |
| RF-4 | Review Focus 4; Tasks 5, 6, 10, 11, 12 | Can't see never becomes zero | test_all_cloudy_is_cant_see, test_missing_night_is_unseen_not_zero, test_cant_see_not_trained, test_predict_nothing_only_where_the_satellite_sees, test_cant_see_rows_give_nan_and_are_not_trained, test_predictions_frame_blanks_unseen_rows, test_cant_see_exports_null_not_zero, CountyCard "can't see" | AU-01 to AU-04 (P0-R); EV-05, BL-03, BL-09 to BL-12, MD-11, PX-03, AU-06, DL-05 (P1) |
| RF-5 | Review Focus 5; Task 6; decision log "Lockbox" | The lockbox must not leak; after the opening, no second look | test_lockbox_guard_raises, test_lockbox_rows_refused_unless_final, test_loso_never_sees_its_storm, test_loso_drops_the_held_out_storms_county_nights_from_other_tables, test_shared_county_nights_are_dropped_from_final_training, hybrid test_lockbox_guard, tests/test_lockbox.py (4 static scans), test_lockbox_storm_export_waits_for_the_lockbox_run | LB-13, LB-39, LB-45, LB-21, MD-46 (P0-I); LB-17 extension, LB-18, LB-19, LB-20, LB-23, LB-24, EV-48, MD-05, MD-15 (P1); LB-01, LB-12, LB-32 (P2) |

### 4.2 The two pre-registered tests and the integrity of the opening

| Req | Requirement | Existing tests | New tests |
|---|---|---|---|
| PB-0 | Final curve and ranges fit on all eight main storms with `final=True`; each locked storm scored once | test_run_final_scores_the_lockbox_once, test_strict_load_refuses_a_missing_main_table, test_load_tables_uses_each_storms_own_satellite | LB-41, LB-42 (P0-I); LB-09, LB-11, LB-35 (P1) |
| PB-R | Scored rows: hit counties at ≥ 34 kt (every county for the stress storm), landfall to landfall + 21, status ok, covered, usable official after the over-count rule | test_pass_bar_check_reads_each_condition | LB-04, LB-05; LB-03 checks window_end − landfall == 21 for every main and lockbox storm (P0-I) |
| PB-T | Official = EAGLE-I ±60 median at the pass with `flag_dropouts` runs removed; ±30 and ±90 beside | test_official_at_pass_time | LB-05(f) (P0-I); LB-43 (P0-I); BL-13, BL-15, RD-09 (P1) |
| PB-1 | Curve error strictly below wind-only's on the same rows | test_pass_bar_check_reads_each_condition | LB-04, LB-05(a) (P0-I); MD-39 (P1) |
| PB-2 | Pooled first-difference Spearman ≥ 0.3 | test_first_difference_agreement_ignores_shared_decay | LB-04, LB-05(e, g), LB-06 (P0-I); EV-12, EV-45 (P1) |
| PB-3 | Median restore-day error ≤ 2 days (10%, held 24 h) where both restore days exist | test_official_restore_day_needs_24h, test_official_restore_day_skips_nan_nights | LB-07, MD-27 (P0-I); MD-28, EV-21, MD-44 (P1) |
| PB-V | Pass if both pass, partial if one does, fail if neither | none | LB-08, LB-36, LB-40 (P0-I) |
| PB-D | A storm the drop rule removes leaves the other alone, and the verdict says so | test_drop_rule | LB-08, LB-10, LB-40 (P0-I); BL-16 (P1) |
| PB-U | Uri scored separately with the tuning caveat; not in the verdict | none | LB-16 (P1) |
| PB-E | Every number reported whatever the verdict | test_strict_json_writes_null_for_nan | LB-45 (P0-I); LB-34 (P2) |
| PB-C | The bar was committed before any lockbox estimate; its text is unchanged | test_pass_bar_was_committed_before_any_lockbox_score (mtime) | LB-02, LB-41 (P0-I) |
| PB-O | Score Helene and Milton once (Task 9) | none | LB-13, LB-39, LB-41 (P0-I) |
| PB-K | Thresholds exactly as written (0.3, 2 days, 10%, 34 kt, 1.05, windows) | none | LB-03 (P0-I) |
| SB-1 | The hybrid's satellite test: error on rows ≥ 10% out lower than wind_timing's and AUC for ≥ 50% out higher, on both storms (`2187e37`) | test_satellite_test_edge_rules, test_satellite_increment_hand_computed | LB-37 (P0-I); EV-45 (P1) |
| SB-2 | Edge rules: ≥ 10 rows at ≥ 10% out to be evaluable; ≥ 10 rows at ≥ 50% for the AUC condition; a missing or dropped storm leaves the other (`7fd2732`) | test_satellite_test_edge_rules | LB-37 (P0-I) |
| SB-3 | The hybrid is frozen as logged (`TREE_PARAMS`, features at `2187e37`) | test_deterministic | LB-21, MD-46 (P0-I) |
| IN-1 | The opening's record is frozen and its inputs recorded | none | LB-44, LB-45 (P0-I) |
| IN-2 | The recorded numbers reproduce from the recorded commit and tables | none | LB-42 (P0-I) |
| IN-3 | The locked truth used the repaired customers, or both readings are shown | none | LB-43 (P0-I) |

### 4.3 Evaluation requirements

| Req | Source | Requirement | Existing tests | New tests |
|---|---|---|---|---|
| EQ-A | design §7 Hold-outs; Task 7 | Leave-one-storm-out isolation | test_loso_never_sees_its_storm, test_loso_needs_two_main_storms, test_loso_drops_the_held_out_storms_county_nights_from_other_tables | LB-20, MD-05, MD-15, MD-16, MD-17, RD-36 (P1) |
| EQ-B | Task 7; design §7 | The scorecard columns, checked by hand | test_scorecard_toy and 4 more | MD-13, MD-18, MD-19, MD-24 (P1); MD-20 to MD-23 (P2) |
| EQ-C | design §7; Task 6 | wind_only and nothing scored on the same rows as the curve | test_every_method_scores_the_same_rows, test_wind_only_* (4) | MD-13, EV-45, MD-14, MD-39 (P1); MD-40 (P2) |
| EQ-D | design §1, §3; the user's request | Skill beyond the baselines on unseen storms, labelled by tier | test_diagnostics_hand_computed, test_satellite_increment_hand_computed | EV-30 (P1, the reading); EV-02, EV-03, EV-05, EV-06, EV-10, EV-12, EV-13 to EV-16, EV-45 to EV-48, RD-20 to RD-23, RD-31 (P1); EV-04, EV-07 to EV-09, EV-11, EV-17, RD-26 (P2) |
| EQ-E | Task 8; design §6 Range | 80% ranges hold about 80% of held-out truth | test_range_coverage and 13 more (synthetic) | MD-31, MD-32, MD-33, EV-18, EV-19, EV-20, RD-25 (P1) |
| EQ-F | Tasks 7, 8; design §6 Duration | Restore days, intervals and brackets match EAGLE-I | the interval and bracket tests in test_ranges.py | EV-21, EV-22, MD-34, MD-36 (P1); EV-23, EV-24, RD-28 (P2) |
| EQ-G | Task 9; decision log "NOAA-20 cross-check scope", "Beryl is built from NOAA-20" | NOAA-20 agreement; Lee's timing; mixed satellites | test_cross_check_keeps_only_counties_inside_the_tiles | LB-28, LB-29, EV-49, RD-01 (P1); LB-30 (P2) |
| EQ-H | Task 9 | Uri stress score with the caveat | none | LB-16 (P1) |
| EQ-I | Task 9 stretch; design §2 Q3 | Trigger basis risk | none | LB-25, LB-26 (P1); LB-27 (P2) |
| EQ-J | Task 9; design §7 | A failures page with real cases | none | LB-35 (failure_facts on the right table, P1); RH-19 (P2) |
| EQ-K | decision log "Model choice" | The hybrid ships as secondary and frozen; LOSO rows tagged design loop | test_hybrid_* (8) | LB-21, MD-46 (P0-I); EV-33, EV-46, EV-47, MD-41, MD-45 (P1); MD-43, RH-21 (P2) |
| EQ-L | evaluation audit; review finding 11 | One-knob ablations on main storms only | test_partial_dropout_dropped | EV-35, EV-49, RD-32 (P1); EV-36 to EV-38, RD-33 (P2) |
| EQ-M | design §2, §8; Task 12 | The portfolio and claim-check outputs are right, not just computed | test_exposure_toy, exposure.test.ts, claims.test.ts | EV-39, EV-40, EV-42 to EV-44, CT-08, RD-29, RD-30 (P1); EV-41 (P2) |
| EQ-N | evaluation audit | Bar strength: ceilings and nulls | none | EV-10, EV-12, RD-20, RD-21 (P1); EV-11 (P2) |
| EQ-O | ECC data; evaluation audit | Real tables are valid | test_sample_table_schema, test_offline_build_table | RD-01 to RD-10, RD-12 to RD-15 (P1); RD-11, RD-16 to RD-19 (P2) |
| EQ-P | evaluation audit | Headline numbers carry an interval and n | none | EV-13 to EV-16 (P1); EV-17 (P2) |
| EQ-Q | design §5, §7 | Data design: first pass after landfall, other storms in windows, Texas noise | none | DL-57, DL-58, RD-07 (P1) |

### 4.4 Plan tasks, global constraints and ECC web rules

| Req | Source | Requirement | Existing tests | New tests |
|---|---|---|---|---|
| T2-a | Task 2 | `load_outages`: local csv or parquet, VARCHAR fips, 2-digit prefixes, naive-UTC bounds | test_load_types_and_whole_state, test_window_filter, test_bad_inputs_rejected | DL-13, DL-14 (P1); DL-36 to DL-38 (P2) |
| T2-b | Task 2; decision log "EAGLE-I dropout rule" | `flag_dropouts` steps 1–7, constants 0.93 / 3 h / 0.5 / 2 | 17 rule tests incl. test_thresholds_are_pinned | DL-06, DL-07, RD-12 (P1); DL-39 to DL-42, RD-11 (P2) |
| T2-c | Task 2 | `customers_out_at` / `OutageIndex` | test_absent_county_in_live_run_is_zero, test_missing_state_run_is_nan | DL-02, DL-10, DL-11, DL-12 (P1) |
| T2-d | Task 2 | `load_mcc`, `coverage_for`, `STATE_FIPS` | 5 tests in test_outages.py | RD-16, DL-53 (P2) |
| T2-e | Task 5 copy step; `scripts/fetch_eaglei.py` | Extracts keep VARCHAR codes, the renamed `sum` column, the storm's states and dates | none | BL-21, RD-10 (P1); DL-35 (P2) |
| T3-a | Task 3 | Tile ids are half-open; file names map to dates | 5 tests in test_nightlights.py | DL-26 (P2) |
| T3-b | Task 3; Global "Satellite data" | Corrected layer only; fill becomes NaN; clear-pixel rule | test_fill_becomes_nan, test_never_reads_gap_filled, test_cloudy_masked, test_quality_and_snow_rules | DL-01, DL-05 (P1); DL-46 (P2) |
| T3-c | Tasks 3, 5 | Pass time from the A1 median, with the solar formula as fallback | test_pass_time_utc, test_find_a1_by_date_and_tile | BL-07, BL-12, RD-04 (P1); DL-44 (P2) |
| T4-a | Task 4 | Storm defaults, roster, landfall dates and times; each storm's satellite | test_defaults_and_uri, test_storm_ids_exist_in_hurdat2, test_landfall_times_match_hurdat2 | DL-15, DL-16 (P1); DL-30, DL-54 (P2) |
| T4-b | design §6; Global "Storms and baselines" | Baselines from before the first of two storms; no other storm in a baseline or event window | test_milton_baseline_before_helene | DL-04, DL-58, DL-25 (P1) |
| T4-c | Task 4 | Wind bands: strongest zone, quadrants, hourly track, tropical fixes | test_band_inside_64kt, test_quadrants, test_hourly_interpolation_closes_gaps, test_storm_track_keeps_tropical_fixes | DL-03, DL-20, RD-13 (P1); DL-28, DL-29, DL-47 to DL-49 (P2) |
| T4-d | Task 4; decision log customer repair | Counties, Connecticut's old counties, customer repair | test_repair_customers_rules and 2 more (Census tests skip in CI) | DL-17, DL-18, DL-19, RD-05, RD-14 (P1); DL-52 (P2) |
| T5-a | Task 5 | Label grid on pixel centres; cache | test_label_grid_top_left_and_cache | BL-01 to BL-04 (P1); BL-24 to BL-26 (P2) |
| T5-b | Task 5 | Baseline median of ≥ 5 clear nights; same pixels; sums across tiles | 3 tests in test_aggregate_table.py | BL-05, BL-06, BL-07 (P1); BL-27 to BL-31 (P2) |
| T5-c | Task 5; decision log DARK_MIN | Status thresholds (visible 0.5, DARK_MIN 2,000) | test_dark_county_not_measurable, test_half_hidden_is_cant_see_and_snow_rule | RD-01, RD-02, BL-08, BL-09 (P1); BL-32 (P2) |
| T5-d | Task 5 | `official_columns` and the mixed-pass count | test_official_at_pass_time | BL-13, BL-14, BL-15 (P1); BL-35, BL-36 (P2) |
| T5-e | Task 5; design §5 | Drop rule; every drop logged | test_drop_rule | LB-10 (P0-I); BL-16, BL-17, RD-15 (P1) |
| T5-f | Task 5 | Build outputs, no tiles on disk, `--all` continues, summaries hold no official values | 4 tests | BL-10, BL-11, BL-20 to BL-22, BL-48 (P1); BL-33, BL-34, BL-37 to BL-44, BL-47 (P2) |
| T5-g | Task 5 | The committed Ian sample | test_sample_table_schema | BL-23, RD-01 (P1); RD-17, RH-20 (P2) |
| T5-h | decision log customer repair; `table.refresh_customers` | Repaired customers in every table | test_with_customers_recomputes_pct_out | LB-43 (P0-I); BL-18, BL-19, RD-05 (P1) |
| T6-a | Task 6 | Isotonic spec | test_monotone and 2 more | MD-08, MD-09 (P1); MD-10, MD-12 (P2) |
| T6-b | Task 6; decision log model details | Angle and moon correction on training calm nights; leave-one-out noise | 5 tests in test_model.py | MD-04, MD-05, MD-06, MD-07, RD-27 (P1) |
| T6-c | decision log "Before building" Q2 | Over-count rule | test_overcount_rule_drops_above_105_and_clips_the_rest, test_overcounts_follow_the_curve_rule | MD-01, MD-02, MD-03, RD-06 (P1) |
| T6-d | decision log "Model choice"; `hybrid.py` | The hybrid's county noise uses calm nights only and gives the same answer whatever else is in the batch | test_county_noise_uses_only_calm_nights_and_no_truth, test_predict_refuses_a_batch_without_baseline_nights | MD-45 (P1) |
| T7-a | Task 7 | `official_restore_day`: 10%, 24 h, NaN nights skipped | 2 tests | MD-27 (P0-I); MD-28, MD-29 (P1); MD-30 (P2) |
| T7-b | Task 7 | The window picks the truth column; the curve is fit on ±60 | test_scorecard_window_picks_the_truth_column | MD-24, MD-25 (P1); MD-26 (P2) |
| T7-c | Task 7 | `blackout evaluate` writes the scorecard from main storms opened by exact name | test_write_scorecard_on_two_synthetic_tables | RD-31, EV-31, EV-32 (P1) |
| T8-a | Task 8 | `fit_ranges` | 14 tests | MD-31, MD-32, MD-33 (P1) |
| T8-b | Task 8 | `restoration_interval` | 9 tests | MD-34, MD-36 (P1); MD-35 (P2) |
| T8-c | Task 8; decision log waiting periods | `pct_out_bracket` from `Storm.landfall_time` | test_bracket_* (5) | PX-13 (P1); MD-37, MD-38 (P2) |
| T9-a | Task 9 | `download_laads`: query, MD5, TLS on | 6 tests | DL-21 to DL-24 (P1); DL-31 to DL-34, DL-50, DL-51, DL-55, DL-56 (P2) |
| T10-a | Task 10; Global "Portfolio example" | Portfolio: 100k policies, 5% business, seed, follows housing | test_portfolio_deterministic, test_portfolio_follows_housing | PX-05, PX-07 (P1); PX-16 (P2) |
| T10-b | Task 10 | Claims: 200, 10% inflated, only where EAGLE-I shows an outage | 2 tests | PX-08, EV-43 (P1); PX-15 (P2) |
| T10-c | Task 10 | Export files, schema, null not zero, quickstart sample | test_export_validates_schema, test_cant_see_exports_null_not_zero, test_export_sample_is_offline, test_range_always_contains_the_point (`966313a`) | PX-01, PX-02, RD-35, CT-01, CT-02 (P0-R); PX-03, PX-04, PX-06, PX-10, LB-31 (P1); PX-17 (P2) |
| T10-d | Task 10 (lockbox exports only after Task 9) | Exports of a locked storm wait for the opening | test_lockbox_storm_export_waits_for_the_lockbox_run | LB-17 extension (P1) |
| T10-e | Task 10 | CLI `export --storm`, `--sample`; saved scorecards feed scorecard.json | test_evaluate_export_and_lockbox_dispatch | PX-09, PX-11, PX-12 (P1) |
| T11-a | Task 11 | `loadStorm` parses the fixture, with readable errors | load.test.ts (9) | CT-03, CT-04, CT-05 (P0-R); AU-20 (P2) |
| T11-b | Task 11 Decisions | No basemap tiles; unseen counties hatched; a colour-blind-safe ramp | color.test.ts (3) | AU-03, AU-04 (P0-R); AU-07, WB-03 (P1) |
| T11-c | Task 11 Decisions | The night slider works from the keyboard | App.test.tsx | AU-10, WB-06 (P1) |
| T11-d | Task 11; design §8.2 | County card: can't see, range text, homes approximate, range first (`966313a`) | CountyCard.test.tsx (8) | AU-01 (P0-R) |
| T11-e | ECC web/patterns; app README | Loading, shared links and a map failure never break the report | urlState.test.ts (4), App.test.tsx | AU-11, AU-14, AU-15, WB-14 to WB-16 (P1); AU-18, AU-19 (P2) |
| T11-f | design §7, §8 | Restoration chart, scorecard table, portfolio wording, model labels | ScorecardTable.test.tsx (2), PortfolioPanel.test.tsx (4) | AU-08, AU-09 (P1); AU-17, AU-24 (P2) |
| T12-a | Task 12 | `expectedPoliciesOut`, unknown policies, the Python toy | exposure.test.ts | CT-06 (P0-R); AU-12 (P1) |
| T12-b | Task 12; design §8.4 | `claimVerdict`: high end, review at ≥ 0.9, never "fraud" | claims.test.ts (10), ClaimCheck.test.tsx (6) | CT-08, AU-13 (P1); AU-22 (P2) |
| T12-c | Task 12 | Flags under `bfs.flags.v1` | flags.test.ts (6) | AU-05 (P0-R); AU-16, WB-07, WB-24 (P1); AU-21 (P2) |
| T12-d | Task 12; design §3 goal 3 | The Milton walkthrough in about a minute | App.test.tsx | WB-01 (P0-R); WB-23 (P1) |
| T13-a | Task 13 | A stranger reruns everything from a fresh clone | none | PX-01, WB-02, RH-03 (P0-R); RH-05 (P1) |
| T13-b | Task 13 | CI app job | `.github/workflows/ci.yml` app job (`a51071b`) | RH-06 (P1) |
| T13-c | Task 13 | README parts, EAGLE-I credit, write-up | none | RH-11 (P1); RH-21 (P2) |
| T13-d | Task 13; ground rules | Nothing public without the user's OK; no credential uploads | none | WB-03 (P1); RH-16 (P2) |
| GC-1 | Code standards | Functions never modify their inputs | spot checks in 5 tests | MD-42 (P1) |
| GC-2 | Code standards; ECC testing | Coverage ≥ 80% | `--cov-fail-under=80` (lines) | RH-01 (P0-R); RH-06 (P1) |
| GC-3 | Code standards | County-level numbers; FIPS is a 5-character string | test_load_types_and_whole_state, test_bad_tables_are_refused | RD-01, RD-02, DL-12, DL-14 (P1) |
| GC-4 | Repo and data handling | The token lives only in EARTHDATA_TOKEN; fail fast; never printed or saved | test_missing_token_fails_fast, test_secrets_and_data_stay_untracked | RH-04 (P0-R); DL-21, DL-22, DL-24, BL-20, BL-22, RH-08 (P1) |
| GC-5 | Repo and data handling | Data and build folders gitignored; tiles never saved | test_secrets_and_data_stay_untracked | RH-09 (P1); BL-44 (P2) |
| GC-6 | Global "Satellite data" | Collection 2, corrected layer, quality 0 | test_never_reads_gap_filled, test_laads_query_params | DL-01, DL-23 (P1) |
| GC-7 | Global "Starting cutoffs" | Cutoffs pinned and logged | test_thresholds_are_pinned | BL-08, RD-08, EV-37 (P1/P2) |
| GC-8 | Global "Portfolio example" | 24/48/72 h with 72 as default; 100k policies; 5% business; seed | load.test.ts | PX-05 (P1); PX-16 (P2) |
| GC-9 | Ground rules | Public data only, no tracking, no hosting without OK | none | WB-03, WB-09 (P1); RH-16 (P2) |
| GC-10 | Global "Portfolio example" | Credit EAGLE-I under CC BY 4.0 | none | RH-11 (P1); AU-23 (P2) |
| WEB-1 | ECC web/testing 1 | Visual regression at 320 / 768 / 1024 / 1440 | none | WB-10 (P1); WB-26 (P2) |
| WEB-2 | ECC web/testing 2 | Automated accessibility checks, keyboard, reduced motion, contrast | none | WB-05, WB-06, WB-12, WB-13, AU-07 (P1); WB-25 (P2) |
| WEB-3 | ECC web/performance | Core Web Vitals targets and bundle budgets | none | WB-08, WB-20 (P1); WB-27 (P2) |
| WEB-4 | ECC web/testing 4 | Chrome, Firefox, Safari | none | WB-22 (P1: one local Firefox and WebKit run before release) |
| WEB-5 | ECC web/testing 5 | Responsive 320–1920 px; touch | none | WB-04, WB-11 (P1) |
| WEB-6 | ECC web/testing, E2E shape | Deterministic waits | none | every WB spec waits on locators and `data-map-state` |
| WEB-7 | ECC web/security | A production CSP | none | WB-29 (P2) |
| CI-1 | Task 5 (offline CI), Task 13 (app job) | CI runs offline, counts its skips, keeps generated fixtures fresh; local runs are faithful | `.github/workflows/ci.yml` (never run when this plan was revised) | RH-02 (P0-I); RH-03 (P0-R); RH-07, RH-12 (P1) |
| DOC-1 | decision-log header; ECC coding style | Docs agree with the code and the log; code-size limits | none | RH-10, RH-13 (P1); RH-14, RH-15, RH-17 (P2) |

---

## 5. Test catalog

Format: **ID** · priority · kind · file::name — Arrange … Act … Assert …. "Fails today" means red at `966313a`. Tests marked `lockbox` run only with `--run-lockbox` and `docs/lockbox_result.json` present. They read the locked tables, which is allowed after the opening, and never pass them to a fit.

### 5.1 Lockbox, pass bar, satellite test and `final.py`

**Integrity of the recorded opening (P0-I)**
- **LB-45** · P0-I · regression · `tests/test_lockbox.py::test_lockbox_result_is_frozen` — Arrange: `docs/lockbox_result.json`, committed as the first step of M-AUDIT. Act: sha256 of its bytes; read the bytes of `data/processed/lockbox_result.json` if it exists. Assert: the hash equals the value pinned in the test; the local file is byte-identical. Runs in CI on the committed copy. Fails today: no committed copy.
- **LB-44** · P0-I · smoke (`lockbox`) · `tests/realdata/test_after_opening.py::test_lockbox_inputs_are_recorded`, with `scripts/record_lockbox_inputs.py` — Arrange: `docs/lockbox_record.json`, written once by the script: the sha256 of each table the run read (8 main, 2 locked, uri2021), the sha256 of `uv.lock`, the Python, numpy, pandas, scikit-learn, scipy and pyarrow versions, and each table's mtime. Act: rehash the current files. Assert: every hash matches, so any later rebuild is visible; every recorded mtime is earlier than `provenance.run_at_utc`, otherwise the record carries `rebuilt_after_run: true` and D-20 says so. Fails today: no record.
- **LB-41** · P0-I · data-validation (`lockbox`) · `test_after_opening.py::test_recorded_run_provenance` — Arrange: `docs/lockbox_result.json["provenance"]` and full git history. Act: `git merge-base --is-ancestor` from each of `2f534f9`, `2187e37` and `7fd2732` to `git_head`; hash the five code files at `git_head`. Assert:
  - every ancestry check passes;
  - `working_tree_dirty` is false, or D-20 discloses it;
  - each `code_sha256_16` equals the first 16 hex digits of sha256 of `model.py`, `hybrid.py`, `ranges.py`, `evaluate.py` and `final.py` at `git_head`;
  - `training_tables` holds exactly the 8 main ids, with beryl2024 → `county_nights_beryl2024.parquet` and VJ146A2;
  - `run_at_utc` lies between the commit times of `7fd2732` and `50d572e`;
  - every `predictions_<storm>.parquet` mtime lies within 30 minutes of `run_at_utc`.
- **LB-42** · P0-I · integration (`lockbox`, `slow`) · `test_after_opening.py::test_recorded_numbers_reproduce_at_the_recorded_commit` — Arrange: `git worktree add <tmp>/wt <git_head>`; hash `data/processed` before. Act: inside the worktree, `uv run python -c "from blackout.final import run_final; run_final(processed='<tmp>/out')"`. That code reads through `table.PROCESSED`, the real folder, and writes only to tmp. Assert:
  - pass_bar, hybrid, stress, trigger, satellite_increment, satellite_test and verdict equal the recorded JSON (strings and integers exactly; floats as rounded in the JSON);
  - the real `data/processed` is byte-identical afterwards;
  - the per-row predictions of every method for the locked storms are saved under tmp for LB-43.
  
  This is a reproduction, never a replacement.
- **LB-40** · P0-I · data-validation (`lockbox`) · `test_after_opening.py::test_recorded_verdict_follows_the_committed_rule` — Arrange: the recorded `pass_bar[id]["60"]["passes"]` per locked storm; `table.drop_check` on each locked table. Act: `final.verdict(passes, dropped)` (LB-08). Assert: it equals the recorded `verdict`; otherwise D-20 names the difference and S1 leads with the committed-rule verdict.
- **LB-43** · P0-I · data-validation (`lockbox`) · `test_after_opening.py::test_locked_truth_uses_the_repaired_customers` — Arrange: each locked table; `load_counties(storm.states)` (needs `data/raw/census` and MCC). Act: compare customers per fips. Assert: equal for every fips. Otherwise:
  - the test recomputes the three conditions with `table.with_customers` truth on LB-42's saved predictions;
  - it reports how many rows changed and both readings;
  - it stays red until D-20 and S1a show both.
- **LB-36** · P0-I · unit · `tests/test_final.py::test_verdict_follows_the_isotonic_curve_and_hybrid_is_separate` — Arrange: synthetic tables for 3 fake main and 2 fake locked storms. Monkeypatch `fit_translation` and `fit_hybrid` with stub predictors: "perfect" returns official on ok rows; "flat" returns 0.3, so condition 2 is NaN. Act: `run_final` with (isotonic perfect, hybrid flat), then (isotonic flat, hybrid perfect). Assert:
  - the verdict is "pass", then "fail";
  - `results["hybrid"][id][60]["passes"]` is False, then True;
  - `satellite_increment` is computed from `pred_hybrid` in both runs.
- **LB-37** · P0-I · integration · `tests/test_final.py::test_satellite_test_reads_real_increment_rows` — Arrange: two fake locked storms, each with ≥ 10 rows at ≥ 10% out and ≥ 10 at ≥ 50% out; stub fits. Act: `run_final`; then `satellite_test(results["satellite_increment"], locked)`. Assert:
  - `per_storm[id]["auc_evaluable"]` is True for both storms;
  - recomputing from the recorded rows reproduces the verdict;
  - a row missing `rows_half` raises KeyError instead of silently dropping the AUC condition. Fails today: `r.get("rows_half", 0)`.
- **LB-21** · P0-I · regression · `tests/test_lockbox.py::test_the_frozen_hybrid_is_the_shipped_hybrid` — Assert:
  - `hybrid.TREE_PARAMS == {"max_iter": 300, "learning_rate": 0.05, "min_samples_leaf": 40, "l2_regularization": 1.0, "random_state": 0, "early_stopping": False}`, as logged in "Model choice";
  - `git diff --quiet 2187e37 <provenance.git_head> -- src/blackout/hybrid.py src/blackout/model.py src/blackout/ranges.py` (local; skipped with a reason on a shallow clone);
  - any commit after `50d572e` that touches those files is paired with a decision-log entry dated after the opening, and with an updated MD-46 hash.

**No second opening (P0-I)**
- **LB-13** · P0-I · unit · `tests/test_final.py::test_lockbox_refuses_a_second_opening` — Arrange: a tmp processed folder holding `lockbox_result.json` (or only `lockbox_opened.json`); heavy steps replaced by spies; a `pandas.read_parquet` spy. Act: `run_final(processed=tmp)`; `run_final(processed=tmp, reopen="reason")` with and without a decision-log entry containing the reason (`final.DECISION_LOG` monkeypatched). Assert:
  - the first call refuses before any table read;
  - with a logged reason, it writes `lockbox_result_reopen_<UTC>.json` and leaves `lockbox_result.json` byte-identical;
  - on a first run, `lockbox_opened.json` (head sha, UTC time) is written before the first read of a locked table.
  
  Fails today. This merges the first draft's LB-13 and LB-14.
- **LB-39** · P0-I · e2e · `tests/test_cli.py::test_lockbox_ceremony_end_to_end` — Arrange: synthetic tables for fake main storms a2020, b2021, c2022, locked storms lock2024, lock2025 and a stress storm, in tmp; `table.PROCESSED`, `export.PROCESSED` and `load_storms` monkeypatched; the git helper satisfied. Act: `cli.main(["lockbox"])` twice; `export_storm("lock2024", out=tmp/app)` before and after. Assert:
  - the first call exits 0 and writes the marker, `lockbox_result.json` and predictions for every storm;
  - the second call exits non-zero, prints the reopen instructions and changes no file (hashes);
  - the export fails before the first call and succeeds after it.
  
  Fails today: no refusal.

**Pass-bar fidelity (P0-I: the code that produced the verdict)**
- **LB-02** · P0-I · regression · `tests/test_lockbox.py::test_pass_bar_text_unchanged` — Arrange: cut `docs/decision-log.md` from `## 2026-11-08: Pass bar, written before the lockbox opens` to the line before the next `## `; rstrip and add one newline. Act: sha256 (UTF-8). Assert: `1770dda222c98b879502343e319db7dc052a015a0f7040d4e600f55926e38f81`, the value at `2f534f9` and at HEAD. Needs no git history.
- **LB-03** · P0-I · regression · `tests/test_lockbox.py::test_constants_match_the_committed_entries` — Assert:
  - `final.AGREEMENT_MIN == 0.3` and `final.RESTORE_MARGIN_DAYS == 2.0`;
  - `final.HIT_BAND == evaluate.HIT_BAND == 34`, and `scored_rows`, `restore_day_errors` and `trigger_view` use it;
  - `evaluate.RESTORE_THRESHOLD == 0.10` and `evaluate.OUT_CUT == 0.5`;
  - `model.OVERCOUNT_DROP == 1.05` and `model.FULL_OUTAGE == 1.0`;
  - pass-bar windows are `(60, 30, 90)`;
  - `final.TRIGGER_SHARE == 0.5` and `final.TRIGGER_HOURS == 72`;
  - `final.MIN_BIG_ROWS == final.MIN_HALF_ROWS == 10` (the 23:50 entry);
  - every main and lockbox storm has `window_end − landfall == 21` days. Only config is read.
- **LB-04** · P0-I · unit · `tests/test_final.py::test_pass_bar_check_hand_computed_toy` — Arrange: a lockbox-role `Storm("lock2024")`, days 0–4, all ok and covered.
  - County X (band 64): truth 0.75, 0.5, 0.25, 0.0625, 0; curve 0.625, 0.5, 0.375, 0.0625, 0.0625; wind 0.375.
  - County Y (band 50): truth 0.5, 0.375, 0.0625, 0.0625, 0; curve 0.375, 0.4375, 0.125, 0, 0; wind 0.25.
  
  Act: `pass_bar_check(df, storm, 60)`. Assert: rows_scored 10; mae_pp_curve 6.25; mae_pp_wind_only 23.12; first_difference_spearman 0.550 over change_pairs 8 (checked with scipy); restore errors X 0 and Y 1, median 0.5 over 2 counties; all three checks and passes True; input unchanged.
- **LB-05** · P0-I · unit · `tests/test_final.py::test_pass_bar_check_edges` (parametrized on the LB-04 toy):
  - (a) wind-only with the same error as the curve → beats_wind_only False;
  - (b) Y's day-0 truth 1.2 leaves the error and the change pairs, while 1.03 is scored as 1.0;
  - (c) X's day 1 cant_see with a leftover prediction of 0.0 is excluded, and X's changes pair day 0 with day 2;
  - (d) a row at window_end + 1 and a band-0 county are ignored;
  - (e) a constant curve → spearman None, agreement_ok False;
  - (f) window 30 reads official_pct_out_30; window 45 raises;
  - (g) monkeypatched agreement 0.3 passes and 0.2999 fails; a restore median of 2.0 passes and 2.01 fails;
  - (h) nothing scored → passes False, and `json.dumps(final._strict(result), allow_nan=False)` succeeds.
- **LB-06** · P0-I · property · `tests/test_final.py::test_first_difference_agreement_pools_within_counties` — Arrange: 50 seeded counties whose truth and estimate share a linear decay plus independent noise. Act: `first_difference_agreement` and Spearman on levels. Assert:
  - the levels correlation exceeds 0.9 while the statistic is within ±0.15 of 0;
  - est = truth + small noise gives > 0.8;
  - a one-row county adds no pair, and shuffling the rows gives the same value;
  - fewer than 3 pairs, or constant changes, give NaN.
- **LB-07** · P0-I · unit · `tests/test_final.py::test_restore_day_errors_counts_only_counties_with_both_days` — Arrange: hit covered counties restored in both series (estimate day 5, official day 3), never restored officially, never seen ok after landfall, and one holding a 0.0 prediction on a cant_see night; plus an uncovered county, a band-0 county and a stress-storm copy. Act: `restore_day_errors`. Assert:
  - exactly one error, 2.0;
  - the 0.0 on the cant_see night never restores the estimate;
  - the official series uses cloudy nights;
  - the stress copy keeps every county.
- **LB-08** · P0-I · unit · `tests/test_final.py::test_verdict_table` — Arrange: extract a pure `final.verdict(passes, dropped) -> (verdict, note)` from `run_final`. Assert:
  - (pass, pass) → pass; (pass, fail) → partial; (fail, fail) → fail;
  - (pass, dropped) → pass with the note "covers <A> alone; <B> dropped by the drop rule", and (fail, dropped) → fail with the note;
  - (dropped, dropped) or both missing → "no verdict";
  - stress results never change the output.
  
  Fails today: the verdict is computed inline, with no drop rule.
- **LB-10** · P0-I · integration · `tests/test_final.py::test_run_final_applies_drop_rule` — Arrange: one fake locked table gives only 40% of hit counties an ok night in days 0–7. Act: `run_final`. Assert: that storm is recorded as dropped, with drop_check's share; it is left out of the verdict; the verdict note names it. Fails today.

**Hardening and the rest of `final.py`**
- **LB-09** · P1 · integration · `tests/test_final.py::test_future_runs_refuse_missing_or_malformed_locked_tables` — Arrange: a fake locked table deleted, or missing a `TABLE_COLUMNS` column. Act: `run_final`. Assert: it raises before any fit and before any file is written, checking the schema with `pyarrow.parquet.read_schema` only. Main tables are already strict (test_strict_load_refuses_a_missing_main_table).
- **LB-11** · P1 · integration · `tests/test_final.py::test_run_final_fits_see_main_storms_only` — Arrange: spies on `fit_translation`, `WindOnly.fit`, `fit_hybrid`, `fit_wind_timing`, `fit_angle_moon`, `fit_ranges` and `evaluate.loso` record the training storm ids. Act: `run_final`. Assert:
  - each final fit is called exactly once and `loso` exactly twice (no vacuous pass);
  - every recorded set is a subset of the main ids;
  - `final=True` appears only on the final fits.
- **LB-12** · P2 · integration · `tests/test_final.py::test_locked_tables_read_only_by_key_before_the_last_fit` — Arrange: one event log shared by the fit spies and a `pandas.read_parquet` spy that records `columns`. Assert:
  - before the last fit, every read of a locked or stress table passes `columns` ⊆ {fips, night};
  - the spy sees at least one locked read.
  
  Fails today: `pd.read_parquet(table_path(s))[["fips", "night"]]` reads every column. D-20 discloses this for the recorded run.
- **LB-15** · P2 · integration · `tests/test_final.py::test_run_final_reads_and_writes_one_directory` — Arrange: synthetic tables only in tmp; `table.PROCESSED` at its default. Act: `run_final(processed=tmp)`. Assert: nothing is read outside tmp. Fails today: reads go through `table_path`.
- **LB-16** · P1 · unit · `tests/test_final.py::test_uri_never_trains_or_counts` — Arrange: a fake stress table; fit spies; two runs, with the stress storm passing and failing. Assert:
  - fits were called (count ≥ 1) and none received a stress row;
  - `results["stress"][id]["note"]` contains "dropout constants were tuned partly on";
  - the verdict is identical in both runs.
  
  Fails today: the JSON has no note, although `render_lockbox` prints one.
- **LB-17** · P1 · unit · `tests/test_export.py::test_lockbox_export_requires_the_storm_in_the_result` — extends test_lockbox_storm_export_waits_for_the_lockbox_run (`c594d56`). Arrange: a `lockbox_result.json` whose `pass_bar` lacks lock2099. Assert: `export_storm("lock2099")` still raises `LockboxClosedError`; with lock2099 listed, it succeeds.
- **LB-18** · P1 · contract · `tests/test_lockbox.py::test_every_fit_function_guards_the_lockbox` — Arrange: discover the module-level `fit_*` functions in `blackout.model`, `blackout.ranges` and `blackout.hybrid`, plus `WindOnly.fit` and `model.noise_report`. Use a 40-row synthetic frame with fake-lockbox rows, including rows the training filter would drop. Assert:
  - each raises `LockboxError`;
  - with `final=True`, none does except `noise_report`, which always refuses;
  - the discovered set equals an explicit allowlist.
- **LB-19** · P1 · unit · `tests/test_ranges.py::test_fit_ranges_requires_storm_id` — a toy LOSO frame without `storm_id` → `ValueError` naming storm_id. Fails today: the guard is skipped when the column is absent.
- **LB-20** · P1 · unit · `tests/test_evaluate.py::test_all_folds_exclude_heldout_lockbox_and_stress` — Arrange: extend the `SpyPredictor` to wrap `fit_hybrid`, `fit_wind_timing`, the nested range fits, forward chaining (EV-47), the null runner and `ablations.run_ablations`. Assert: every wrapped function was called, and no fold trains on its held-out storm, a lockbox id or a stress id.
- **LB-23** · P1 · unit · `tests/test_lockbox.py::test_no_code_or_test_globs_data_or_names_locked_files` — extends `test_no_code_or_test_reads_a_lockbox_table_directly` to `scripts/` and `tests/`. Act: AST and regex scans for glob, rglob, iterdir, listdir and `pyarrow.dataset` over `data/`, for wildcard strings (`county_nights_*`, `eaglei_*`), and for a whole-folder `read_parquet(PROCESSED)`. Assert: none outside the allowlist.
- **LB-24** · P1 · unit · `tests/test_lockbox.py::test_final_true_only_in_run_final` — an AST scan of `src/blackout` finds every `final=True` call inside `final.run_final`.
- **LB-25** · P1 · unit · `tests/test_final.py::test_trigger_view_outcomes_edges_and_clock` — Arrange: hit counties with looks either side of `storm.landfall_time + 72 h`, one each of paid correctly, paid wrongly, missed, correctly unpaid and unknown; an uncovered and a band-0 county; midpoints of exactly 0.5. Assert:
  - counts 1/1/1/1/1;
  - the ignored counties are absent;
  - exactly 0.5 is neither paid nor truly out;
  - shifting `landfall_utc` by 6 h shifts the target by 6 h.
- **LB-26** · P1 · unit · `tests/test_final.py::test_trigger_truth_follows_bar_rules` — Arrange: official 0.8 at the look before the hour and 0.4 after; separately, official 1.2 and 1.03. Assert under D-6: truth 0.6 (out); 1.2 → unknown; 1.03 → 1.0. Fails today: it reads the first raw official value after the hour.
- **LB-27** · P2 · unit · `tests/test_final.py::test_wind_trigger_baseline` — a new `final.wind_trigger_view` pays band 64 only and returns the same outcome keys as `trigger_view`.
- **LB-28** · P1 · unit · `tests/test_final.py::test_noaa20_agreement_toy` — Arrange, in tmp with the real `table_path`: a Suomi-own fake storm with VNP46A2 and VJ146A2 tables, identical pct_darker on 6 ok nights and one night cant_see on NOAA-20 only; plus a VJ146A2-own fake storm (Beryl's case: own file and `_vnp46a2` file). Assert:
  - pairs 5, pearson 1.0, spearman 1.0, median_abs_diff_pp 0.0;
  - the VJ146A2-own storm pairs its own file with the `_vnp46a2` file;
  - a missing table gives "table missing"; 2 pairs give no correlation keys.
- **LB-29** · P1 · unit · `tests/test_final.py::test_lee_on_noaa20_toy` — Lee's ok nights, days 0–4: pct_darker 0.2, 0.6, 0.5, 0.25, 0.1; official 0.9, 0.8, 0.5, 0.3, 0.1. Assert: darkest night day 1; half_recovery_dark day 3; official peak day 0; half_recovery_official day 3; gap 0; the matching note when there is no table or no clear night.
- **LB-30** · P2 · unit · `tests/test_final.py::test_noaa20_corrected_and_downstream` — the new `diagnostics.noaa20_report` corrects each satellite with its own `fit_angle_moon` on its own calm nights and returns the Bland-Altman bias and limits. The downstream score uses a Suomi-only fit; a spy shows no fit on NOAA-20 rows.
- **LB-31** · P1 · contract · `tests/test_final.py::test_predictions_frame_round_trips_through_export` — `predictions_frame` output → `export.read_predictions` accepts it; est, lo and hi lie in [0, 1] with lo ≤ est ≤ hi (`966313a`'s rule); NaN wherever status ≠ ok.
- **LB-34** · P2 · integration · `tests/test_final.py::test_lockbox_result_is_strict_json` — `json.loads(text, parse_constant=<raise>)` on a synthetic run; range bounds that were ±inf are null.
- **LB-35** · P1 · integration · `tests/test_final.py::test_final_reads_each_storms_own_table` — Arrange: a tmp `PROCESSED` with a fake main storm `n2024` (satellite VJ146A2) and a `county_nights_n2024_vnp46a2.parquet` decoy whose official and pct_darker columns hold 9.9. Delete the lambda that ignores `satellite` in test_run_final_scores_the_lockbox_once. Add a `read_parquet` spy. Act: `run_final(processed=tmp)` with stub fits; `failure_facts(n2024)`. Assert:
  - only `noaa20_agreement` opens the decoy;
  - `run_final`'s main rows equal `evaluate.load_main_tables`'s rows;
  - `failure_facts` reads the storm's own table. Fails today: its default is `satellite="VNP46A2"`.
- **LB-38** · P1 · integration · `tests/test_final.py::test_gitinfo_against_a_temp_repo` — Arrange: `git init` in tmp, two commits, then one dirty file. Act: the new `blackout.gitinfo` (`head_sha`, `is_ancestor`, `tree_is_clean`, `committed_at`). Assert: the true sha; the ancestry answer both ways; dirty, then clean after committing. This uses real git, not a mock, and `provenance` uses the helper.

**For the next holdout**
- **LB-01** · P2 · contract · `tests/conftest.py` (tripwire) + `tests/test_lockbox.py::test_tripwire_blocks_holdout_paths` — Arrange: a fixture wraps the pandas, pyarrow, duckdb, geopandas and numpy readers and `open`. It expands globs and directory arguments, and raises `HoldoutPeek` for any path naming an id in `HOLDOUT_IDS`. In tests that id is the canary `canary2099`. Act: read `data/processed/county_nights_canary2099.parquet`, which does not exist; read the folder `data/processed`; run a duckdb glob `county_nights_*`. Assert: all three raise before any I/O. A broken wrapper reads nothing real.
- **LB-32** · P2 · unit · `tests/test_model.py::test_guard_reads_roles_through_load_storms` — `check_no_lockbox` takes roles from the union of the passed list and `storms.load_storms()`, one injectable source. Monkeypatching `load_storms` to relabel a storm as lockbox makes every fit refuse it.

### 5.2 Evaluation diagnostics, uncertainty, ablations and product evaluation

New modules: `src/blackout/diagnostics.py` holds the moved `evaluate.diagnostics` and `satellite_increment` plus the new metrics and the uncertainty helpers; `ablations.py`; `product_eval.py`; `report.py`. TOY is `toy_frame()` from `tests/test_evaluate.py`: 10 scored rows; county A has 1,000 customers and B 2,000.

- **EV-45** · P1 · unit · `tests/test_diagnostics.py::test_one_implementation_on_common_rows` — Arrange: TOY with every method's column, and `pred_wind_only` NaN on A4 only. Act: `diagnostics.pooled(preds, storms)` and `satellite_increment`. Assert:
  - rows is 9 for every method;
  - per storm, `change_spearman` equals `final.first_difference_agreement` on the same rows;
  - `auc_50` equals `sklearn.metrics.roc_auc_score` with ties;
  - `evaluate.diagnostics` is the same object as `diagnostics.pooled`, imported rather than copied.
  
  Fails today: each method is scored on its own finite rows.
- **EV-01** · P1 · regression · `tests/test_diagnostics.py::test_diagnostic_constants_are_pinned` — sha256 of the §0.5 constants' repr equals a pinned value. The failure message says "constants defined after the opening changed: log it".
- **EV-02** · P1 · unit · `test_active_row_and_event_mae_toy` — active rows A0, A2, A4, B0, B1: curve 23.4 pp, nothing 38.8 pp on the same rows; event rows A0, A2, B0, B1: 21.25 pp.
- **EV-03** · P1 · unit · `test_mse_skill_and_rmse_toy` — on TOY: MSE 0.03989; nothing 0.11154; skill against nothing 0.6424; RMSE 19.97 pp; skill NaN when every official value is 0.
- **EV-04** · P2 · unit · `test_customer_weighted_mae_bias_and_totals_toy` — customer-weighted error 13.57 pp; bias +5.5 pp; day-0 totals ratio 2.0.
- **EV-05** · P1 · unit · `test_diagnostics_ignore_blind_rows` — TOY with 0.0 and with NaN on every cant_see row → identical results from every metric.
- **EV-06** · P1 · unit · `test_event_auc_toy` — positives A0, A2, B1: AUC 17.5 / 21 = 0.8333 with ties scored half; a constant predictor gives 0.5; the default MIN_POSITIVES gives NaN with n_pos 3; n_calls_50 is 3; catch and false-alarm rates are NaN, never 0, when their denominator is 0.
- **EV-07** · P2 · property · `test_within_night_auc_removes_storm_level_shift` — night 1 has every county 0.6–0.9 out and night 2 none; a predictor that knows only the night → pooled AUC ≈ 1 and within-night AUC NaN. With mixed nights and an informative predictor → > 0.9.
- **EV-08** · P2 · property · `test_reliability_bins_ece_and_slope` — calibrated ECE < 0.02 and slope 1 ± 0.1; doubled estimates give slope 0.5 ± 0.1.
- **EV-09** · P2 · unit · `test_band_zero_false_darkening` — 10 band-0 ok event rows, 2 with est 0.3 and official 0.02 → 0.2; cant_see and baseline rows ignored.
- **EV-10** · P1 · unit · `test_null_passbar_uses_pass_bar_check` — Arrange: a LOSO frame for 3 fake storms; a spy on `final.pass_bar_check`. Assert: it runs once per storm × predictor, perfect and time-only included; nothing and wind_only report spearman None.
- **EV-11** · P2 · property · `test_permutation_nulls_preserve_marginals` — the county shuffle keeps each night's multiset and the night shuffle each county's; non-ok rows never get a value; the same seed gives the same permutation.
- **EV-12** · P1 · property · `test_time_only_null_clears_condition_2_in_a_decaying_world` — 150 seeded counties restoring as U(0.2, 0.95) × exp(−t / U(1.5, 6)) + N(0, 0.05), with 40% cloudy nights; the predictor 0.55 × exp(−t / 3.5) → `first_difference_agreement` ≥ 0.3. This pins the weakness that the "Model choice" entry states.
- **EV-13** · P1 · unit · `tests/test_diagnostics.py::test_storm_bootstrap_resamples_whole_storms` — 8 storms with per-storm error 1–8 and 10 to 10,000 rows → the result equals bootstrapping the 8 values with the same seed, and does not change when one storm's rows are duplicated 10 times.
- **EV-14** · P1 · unit · `test_county_bootstrap_keeps_county_nights_together` — 50 counties × 20 nights, one county carrying all the error → the interval is ≥ 3 × as wide as a row bootstrap's; deterministic for a seed.
- **EV-15** · P1 · unit · `test_paired_bootstrap_uses_one_resample` — B's error = A's + 0.02 on every row → the interval is exactly [2.0, 2.0] pp.
- **EV-16** · P1 · unit · `test_sign_test_and_t_interval` — `sign_test(7, 8)` gives one-sided p = 0.0352; ties leave n; `t_interval([1..8], 0.95)` = [2.452, 6.548].
- **EV-17** · P2 · unit · `test_two_stage_and_state_cluster_bootstraps` — the two-stage interval is wider than the county-only one and reduces to it with one storm; the state-cluster version groups by fips[:2].
- **EV-18** · P1 · unit · `test_range_metrics_toy` — (lo, hi, y) = (0, .2, .1), (0, .2, .3), (.1, .3, .05), (0, 0, 0), (.4, .8, .6) → coverage 0.6; mean width 0.2; interval scores 0.2, 1.2, 0.7, 0, 0.4, mean 0.5.
- **EV-19** · P1 · unit · `test_nested_range_fit_excludes_scored_storm` — a `fit_ranges` spy: storm S's residuals never include S's rows.
- **EV-20** · P1 · unit · `test_zero_rows_counted_separately` — 80 zero rows covered and 20 active rows all outside → pooled 0.8, active 0.0, both reported.
- **EV-21** · P1 · unit · `test_restore_split_out_vs_never_out` — 2 out counties with errors 1 and 3, and 4 never-out counties with 0, 0, 5 and 6 → all 2.0, out 2.0, never-out 2.5, n per group. Fails today: not computed, although the decision log promises it.
- **EV-22** · P1 · unit · `test_interval_coverage_rules` — (3, 5, 4) covered; (4, 6, 4) not; (6, None, 9) and (6, None, NaN) covered; (0, 0, 3) not; (NaN, NaN, 3) unknown → coverage 3/5, open 0.4, unknown 1/6, closed width 1.33.
- **EV-23** · P2 · unit · `test_restore_definitions_agree_on_a_clean_series` — 0.8, 0.6, 0.3, 0.05, 0.02 → restore day 3; interval (2, 3).
- **EV-24** · P2 · unit · `test_bracket_coverage_of_official_at_hour` — looks with 0.4 and 0.2 → 0.3 inside, 0.1 outside; a blind side is unknown.
- **EV-25** · P1 · unit · `test_outage_weighted_measurable_share_toy` — A (1,000 customers): 0.8 out on a cant_see night, 0.1 on an ok night; B (2,000): 0.05, ok on both nights → 300 / 1,100 = 0.273; the county-night share is 0.75.
- **EV-26** · P2 · unit · `test_peak_totals_all_vs_visible_and_offset`.
- **EV-27** · P2 · unit · `test_first_look_day` — ok shares 0.25, 0.0, 0.5, 0.75 → day 2; NaN if 50% is never reached.
- **EV-28** · P1 · unit · `test_slice_scores_partition_and_suppress` — slices by storm, state, bucket and band: counts sum to rows_scored; no row falls in two slices; cells under MIN_ROWS or MIN_COUNTIES print n only; input unchanged.
- **EV-29** · P2 · unit · `test_slice_labels_use_frozen_cut_points` — zenith 25.0 is "≤ 25"; lunar 0.5 is dark; visible share 0.5 is in the first bin; an unknown fips is "missing", never "mcc".
- **EV-30** · P1 · unit · `test_reading_table` — the pure function `reading(verdict, satellite_test, integrity)` covers every row of §0.14:
  - (pass, yes) → WORKING; (pass, no) → WORKING with "the satellite's part is not shown";
  - (partial, any) → PARTIAL; (fail, yes) → NOT WORKING with the secondary-model sentence; (fail, no) → NOT WORKING;
  - no verdict → INCONCLUSIVE;
  - an integrity failure without D-20 → refuses to render;
  - the verdict string is never altered.
- **EV-31** · P1 · unit · `tests/test_report.py::test_scorecard_sections_and_labels` — S1, S1a, S2, S3, S4, S5, S8, S9, S10, S14, S15 and S16 appear in order; each table starts with its definition; every rate prints its denominator; every method has a "How to read it" line; numbers defined after the opening carry the label.
- **EV-32** · P1 · unit · `test_report.py::test_scorecard_states_mae_vs_nothing_caveat` — when the curve beats wind-only but loses to nothing, the reading says so and gives the share of exact-zero official rows.
- **EV-33** · P1 · property · `tests/test_hybrid.py::test_satellite_increment_detects_real_signal_only` — 4 seeded storms with official = f(band, days) + g(pct_darker), and a copy where pct_darker is noise → the hybrid's MSE skill over wind_timing is > 0.1 with signal and within ±0.02 of 0 without.
- **EV-34** · P2 · unit · `test_persistence_reference_is_labelled_and_excluded_from_reading`.
- **EV-46** · P1 · unit · `tests/test_report.py::test_rows_are_tagged_by_how_the_storm_was_held_out` — every hybrid and wind_timing row in S4 and S5 carries "design loop"; forward-chaining rows carry "earlier storms only"; locked rows carry "recorded run" or "after the opening, not held out"; the reading uses only (A), (B) and the integrity flags.
- **EV-47** · P1 · unit · `tests/test_diagnostics.py::test_forward_chain_trains_on_earlier_storms_only` — Arrange: 4 synthetic main storms landing in 2018, 2019, 2020 and 2021, given in shuffled order; a spy fit. Act: `forward_chain(df, fit, storms)`. Assert:
  - storm k's fit sees exactly the storms that landed earlier, by date;
  - the first storm is skipped and listed as skipped;
  - lockbox and stress ids are never used;
  - the output rows carry n_training_storms.
  
  The real-data companion prints forward chaining beside LOSO in S5 (decision log: 28.7 against 24.1 pp).
- **EV-48** · P1 · unit · `tests/test_diagnostics.py::test_scores_on_locked_or_stress_storms_are_labelled` — Arrange: rows of a fake lockbox storm and a fake stress storm. Act: `pooled`, `satellite_increment`, `run_ablations` and `product_eval.*`. Assert:
  - without `after_opening=True` each raises, naming the storms;
  - with it, every output row carries `evidence`: "recorded run" when the predictions' hash matches `docs/lockbox_record.json`, otherwise "after the opening, not held out".
- **EV-35** · P1 · unit · `tests/test_ablations.py::test_ablation_runner_refuses_lockbox_and_excludes_stress` — write it before `ablations.py`. Assert: `LockboxError` for a lockbox id; stress rows are left out and listed.
- **EV-49** · P1 · unit · `tests/test_ablations.py::test_suomi_only_and_population_ablations` — Arrange: 3 synthetic main storms, one with satellite VJ146A2. Act: the `suomi_only` and `population` knobs. Assert:
  - `suomi_only` drops exactly the VJ146A2 storm from every training fold, and still scores it, labelled;
  - `population="event"` trains only on landfall–window_end rows and `"hit"` only on band ≥ 34 rows;
  - the output rows hold the change, a paired interval and rows_scored.
- **EV-36** · P2 · unit · `test_official_without_flags_matches_task2_values` — window B, Lee at 07:28:03 → 409085.5 (±60) and 325973.0 (±30) without flags, against 411615.0 and 411676.0 with them.
- **EV-37** · P2 · unit · `test_restatus_only_tightens` — visible 0.6 and base 2,500 with `restatus(0.7, 3000)` → not_measurable with NaN; loosening raises; input unchanged.
- **EV-38** · P2 · unit · `test_unrepaired_customers_change_only_housing_counties`.
- **EV-39** · P1 · unit · `tests/test_product_eval.py::test_official_book_equals_estimate_book_when_estimates_are_perfect` — est = official on ok nights → the estimated low and high equal the official ones at 24, 48 and 72 h; est + 0.2 gives the hand-computed error.
- **EV-40** · P1 · unit · `test_portfolio_truth_toy` — `exposure_toy.json` with official fractions at 72 h of {12001: 0.2, 12003: 0.05, 12005: 0.6, 12007: 0.5} → official 65.0; estimate [17.5, 55.0] with 50 unknown; not inside; the factor-of-two band [8.75, 110] holds it; 30.0 officially-out policies (46%) sit in the unknown county.
- **EV-41** · P2 · property · `test_official_inside_bracket_when_estimates_exact` — 200 seeded books → the official total always lies in [low, high].
- **EV-42** · P1 · unit · `test_claim_confusion_toy`, over days 0–6:
  - County P: est hi 0.9, 0.7, blind, 0.3, 0.08, 0.05, 0.05; official restore day 4; claims of 1.5 and 3.0 days (honest) and 7.0 (inflated).
  - County R: est hi 0.35, 0.2, 0.1, then 0.08; restore day 2; claims of 1.0 (honest) and 6.0 (inflated).
  - County Q: blind; claims of 2.0 and 9.0.
  
  Assert: P gives fits, fits, review; R gives fits, fits (share 0.771); Q is unverifiable; recall 1/2, honest false-review 0/3, unverifiable 2/7; the oracle also misses R's 6.0 (share 0.833).
- **EV-43** · P1 · unit · `test_claim_labels_rederived_from_official_day` — `make_claims` on the test book: claimed_days_out > the official day marks exactly the 20 inflated claims.
- **EV-44** · P1 · unit · `test_claim_check_with_perfect_estimates` — hi = est = official → honest false-review 0; the inflated review rate is reported.

### 5.3 Real data: validation and evaluation

Everything below except RD-01 carries the `realdata` marker. It opens main-storm tables by exact name (`evaluate.load_main_tables`) and writes only to `tmp_path`. `tests/realdata/conftest.py` caches the tables and one set of LOSO predictions.

- **RD-01** · P1 · unit (runs in CI) · `tests/test_validate_table.py::test_validate_table_accepts_the_sample_and_names_each_violation` — Arrange: the committed sample with `get_storm("ian2022")`, then one corruption per check:
  - a duplicate (fips, night);
  - pct_darker on a cant_see row;
  - an ok row with visible_share 0.4;
  - a not_measurable row with base_total 2,500;
  - covered ≠ (coverage ≥ 0.8);
  - a pass at 03:00 UTC, or a pass date ≠ night + 1;
  - wind band 40;
  - a 4-digit fips;
  - official_pct_out ≠ count / customers;
  - a usable ±30 value with a NaN ±60;
  - a `satellite` column ≠ `storm.satellite` (the other satellite for a cross-check table);
  - a `pass_source` other than that satellite's A1 product or "formula".
  
  Act: the new `table.validate_table(table, storm, cross_check=False)`. Assert: the sample passes; each corruption is named with its row count.
- **RD-02** · P1 · `tests/realdata/test_tables.py::test_built_tables_pass_validate_table` — every built table other than the locked ones, cross-checks included with `cross_check=True`: no violation, exact columns and dtypes.
- **RD-03** · P1 · `test_keys_nights_and_county_set_are_complete` — (fips, night) unique; nights == `storm.nights`; rows == counties × nights; the fips set equals `load_counties(states)`, or the `cross_check_counties` subset for a cross-check table.
- **RD-04** · P1 · `test_pass_times_line_up_with_the_night` — pass date == night + 1, hour between 04:00 and 11:00 UTC; within 4 h of the solar formula; formula rows equal the formula to the second.
- **RD-05** · P1 · `test_customers_match_the_repair_in_every_table` — customers > 0; customers / housing_units in [1/3, 3] unless North Carolina's scaling applies; the same fips has the same customers in every table; equal to `load_counties(states).customers`. Locked tables are covered by LB-43.
- **RD-06** · P1 · `test_overcounts_are_rare_and_listed` — per storm, over-counts dropped are ≤ 0.5% of rows with a value (Ida 0.31%, Laura 0.15%, Michael 0.12% at ±60); none infinite; listed for S16. This bound for data quality was set from the 8 storms.
- **RD-07** · P1 · `test_calm_nights_read_near_zero_per_state` — per storm and state, ok rows with night ≤ baseline_end have median pct_darker in [−0.10, 0.10] and sd ≤ 0.5. Exceptions are allowed only if listed in D-18: Texas in laura2020 (0.80) and beryl2024 (0.63). The share with |pct_darker| > 1 is printed per state (Texas 8.2% and 9.2%; Ian's states 0.4–0.8%). The table goes to S16.
- **RD-08** · P1 · `test_wind_and_coverage_columns_are_consistent` — wind_band is in {0, 34, 50, 64} (−1 for the stress storm) and constant per fips; coverage equals `coverage_for`; covered == (coverage ≥ 0.8).
- **RD-09** · P1 · data-validation, slow · `tests/realdata/test_truth.py::test_official_values_recompute_from_the_extract` — 60 seeded rows per storm other than the locked ones; `customers_out_at` at pass_utc for 30, 60 and 90 equals the stored values.
- **RD-10** · P1 · `test_truth.py::test_non_lockbox_extracts_are_well_formed` — `data/interim/eaglei_<id>.parquet` for ids whose role is not lockbox: VARCHAR fips with the storm's prefixes; a 15-minute grid; DOUBLE counts, never negative; no duplicates; the span covers [baseline_start, window_end + 2 days).
- **RD-11** · P2 · `test_truth.py::test_fixture_windows_match_full_extract_flags`.
- **RD-12** · P1 · regression · `test_truth.py::test_decision_log_dropout_catalogue` — the Lee, Pinellas, 12057, 12101 and 12105 flags on Ian; Lee at 07:28:03 reads 411,676 / 411,615 / 411,614.5; nothing is flagged on Uri on 2021-02-15; Harris is flagged in all 8 CenterPoint dips.
- **RD-13** · P1 · `test_tables.py::test_hit_counties_reported_and_pinned` — every county with band ≥ 34 appears in its storm's extract; hit-county counts are pinned after re-deriving them; Lee is band 64 in Ian.
- **RD-14** · P1 · `test_tables.py::test_repaired_counties_match_decision_log` — customers_source "housing" for all 100 NC counties, the 19 Texas counties, Virginia {51195, 51530, 51678, 51720, 51750, 51820} and 36041. Then apply D-15.
- **RD-15** · P1 · `test_tables.py::test_summary_json_matches_its_table_and_drops_are_logged`.
- **RD-16** · P2 · `test_state_fips_and_coverage_match_real_files`. **RD-17** · P2 · `test_sample_is_an_exact_subset_of_the_ian_table`. **RD-18** · P2 · `test_lunar_irradiance_peaks_near_full_moon`. **RD-19** · P2 · `test_never_reported_hit_counties_are_listed`.
- **RD-20** · P1 · evaluation · `tests/realdata/test_gates.py::test_perfect_predictor_ceiling_reported` — the perfect predictor through `pass_bar_check` (via `null_passbar`) at 60, 30 and 90, LOSO on every main storm. After the opening it also runs on each locked storm (`lockbox` marker, labelled). Values go to S8.
- **RD-21** · P1 · evaluation · `test_gates.py::test_pass_bar_dry_run_on_main_storms` — LOSO isotonic and hybrid through `pass_bar_check` per storm → S8. Assert integrity only: rows_scored > 0, and change_pairs ≥ 3 where counties have ≥ 2 ok nights.
- **RD-22** · P1 · evaluation · `test_gates.py::test_shipped_model_calibration_in_the_large` — per storm: peak est / official, maximum prediction, and mean truth per CAL_BINS bin (MIN_ROWS 30; quantile bins collapse on the zeros), plus the least-squares slope. Reported, not gated. The first draft's bounds stay: peak ratio in [0.5, 2] on ≥ 75% of storms, which holds at exactly 6 of 8 today.
- **RD-23** · P1 · evaluation · `test_gates.py::test_shipped_model_against_permutation_and_nothing` — the RMSE of the hybrid, of nothing, and of 5 seeded joint permutations of (pct_darker, sensor_zenith, lunar_irradiance) among readable rows; the pooled change Spearman. Reported, not gated. It is expected to show no margin, because wind_timing's change Spearman (0.215) already exceeds the hybrid's (0.189).
- **RD-24** · P0-I · evaluation · `test_gates.py::test_night_alignment_peaks_at_lag_zero` — Arrange: hit counties with official peak ≥ 0.3, event nights, ok rows, LOSO-corrected pct_darker. Act: the within-county Spearman of changes at night N against official changes at N + k, for k in {−1, 0, +1}. Assert: pooled, lag 0 is the largest; per-storm values are printed.
- **RD-25** · P1 · evaluation · `test_gates.py::test_nested_loso_range_coverage_on_real_storms` — `fit_ranges` on the other storms' hybrid residuals → pooled, active-row and per-storm coverage, labelled nested; in-sample coverage beside it.
- **RD-26** · P2 · `test_darkness_separates_out_from_quiet`. **RD-28** · P2 · `test_estimated_restoration_interval_contains_official_day`.
- **RD-27** · P1 · `test_gates.py::test_correction_reduces_calm_night_noise_out_of_sample` — the LOSO sd is below the raw sd for every storm; the pooled ratio is printed (0.798 today; the first draft's bound of ≤ 0.8 stays and is reported).
- **RD-29** · P1 · `tests/realdata/test_product.py::test_portfolio_headline_vs_official` — LOSO main storms (design loop) and, after the opening, locked storms from the recorded predictions → S15, low ≤ high, the same counties on both sides.
- **RD-30** · P1 · `test_product.py::test_claim_check_discrimination` — `claim_confusion` with the estimates and with the oracle, rates with n → S15.
- **RD-31** · P1 · integration · `tests/realdata/test_report.py::test_scorecard_report_on_real_data` — the report writer into `tmp_path`: every section exists; rows_scored is identical across methods; no lockbox or stress id in the LOSO outputs.
- **RD-32** · P1 · `test_report.py::test_ablations_report_main_storms_only`. **RD-33** · P2 · `test_rebuild_ablations_use_a_separate_storm_id`.
- **RD-34** · P1 · data-validation (`lockbox`) · `test_after_opening.py::test_locked_storm_rows_after_opening` — `validate_table` on the locked tables, then the descriptive diagnostics and product rows once per locked storm, labelled "recorded run" (EV-48).
- **RD-35** · P0-R · regression · `tests/realdata/test_sample.py::test_sample_predictions_are_the_ian_loso_rows` — `data/sample/predictions_ian_sample.parquet` equals evaluate's `loso_predictions.parquet` `pred_hybrid` for 12071, 12015 and 12021 on every (fips, night) (NaN where not ok); lo ≤ est ≤ hi.
- **RD-36** · P1 · regression · `tests/realdata/test_sample.py::test_final_and_evaluate_loso_agree` — `run_final`'s `predictions_<main>.parquet` `est` equals evaluate's `pred_hybrid` per (storm_id, fips, night) on ok rows, so both paths train on the same tables.

### 5.4 Model layer (`model.py`, `hybrid.py`, `evaluate.py`, `ranges.py`)

- **MD-46** · P0-I · regression · `tests/test_hybrid.py::test_golden_predictions` — Arrange: the seeded golden world in `tests/synthetic_world.py` (seed 20261105). Act: sha256 of `np.round(pred, 12).tobytes()` for `fit_hybrid`, `fit_wind_timing`, `fit_translation` and `WindOnly.fit`, and of `json.dumps` of `pass_bar_check` on the LB-04 toy. Assert:
  - each equals its pinned hash; scikit-learn's version is recorded beside the hashes;
  - a mismatch fails with "a model's behaviour changed: log it as a change made after the opening and update the hash".
  
  This covers what a constants hash misses: `_features`, the brightness bands, `clip(lower=0)` and the defaults of `HistGradientBoostingRegressor`. Two fits giving identical predictions is already `test_deterministic`.
- **MD-45** · P1 · property · `tests/test_hybrid.py::test_county_noise_ignores_the_rest_of_the_batch` — Arrange: synthetic storms with counties of varied brightness, some with fewer than `MIN_CALM_NIGHTS` calm nights. Act: `county_noise` and `HybridModel.predict` on the full frame, on a shuffled frame, with another storm added, and with other counties of the same storm removed. Assert:
  - every row of one county gets one brightness band;
  - a county's z and prediction do not change with row order or with other storms;
  - a county with ≥ 5 calm nights does not change when other counties are removed.
  
  Fails today: bands come from `pd.qcut(v.rank(method="first"), 5)` over rows, so one county's nights can fall in two bands; 4 of 7 counties split in a 7-county toy. The fix changes the hybrid, so it is a change after the opening (log it, update MD-46).
- **MD-01** · P1 · unit · `tests/test_evaluate.py::test_overcount_night_is_skipped_by_restore_day` — official 0.8, 0.05, 1.3, 0.05, 0.04 → restore_day_err 0.0.
- **MD-02** · P1 · unit · `test_overcount_rule_is_per_window_column` — official_pct_out_30 of 1.2 on A day 2 → overcount_dropped 2 / 1 / 1; rows 9 / 10 / 10.
- **MD-03** · P1 · contract · `tests/test_overcount_contract.py::test_every_truth_consumer_applies_the_overcount_rule` — official 7.0 and 1.03 against NaN and 1.0 → identical outputs from `fit_translation`, `fit_wind_only`, `fit_hybrid`, `scorecard`, `fit_ranges`, `pass_bar_check`, `trigger_view` and `satellite_increment`.
- **MD-04** · P1 · property · `tests/test_model.py::test_correction_ignores_every_non_calm_row` — random values on every row after baseline_end → equal `AngleMoonCorrection`.
- **MD-05** · P1 · integration · `tests/test_evaluate.py::test_loso_fold_correction_never_sees_held_out_calm_nights` — calm pct_darker of ccc2022 × 10 → its fold's correction is unchanged for both isotonic and hybrid.
- **MD-06** · P1 · `test_calm_nights_follow_each_rows_own_storm`. **MD-07** · P1 · `test_correction_at_real_magnitudes` (b_sec within 0.03 of −0.45; b_moon within 0.001 of 0.005).
- **MD-08** · P1 · property · `test_known_curve_is_recovered` — abs(predict(x) − x / 0.8) ≤ 0.05 for corrected x of 0.16–0.64.
- **MD-09** · P1 · `test_curve_clips_outside_training_range`. **MD-10** · P2 · `test_monotone_at_every_view_geometry`.
- **MD-11** · P1 · `test_blind_rows_never_reach_any_scorecard_column` — pred 0.95 on every non-ok row → error 12.5, peak est 1,800, official 1,000, catch 2/3, false alarm 1/3, restore 1.0, rows 10; measurable 15/23.
- **MD-12** · P2 · `test_unknown_status_strings_fail_closed`.
- **MD-13** · P1 · unit · `test_all_methods_scored_on_identical_rows` — extends test_every_method_scores_the_same_rows: `pred_wind_only` NaN on A4 → `score_all` through `common_rows` gives rows_scored 9 for every method at every window.
- **MD-14** · P1 · `test_nothing_mae_equals_mean_truth`.
- **MD-15** · P1 · contract · `tests/test_evaluate.py::test_predictions_ignore_truth_columns` — a spy predictor inside `loso` never sees a column starting with "official_"; predictions with randomized or dropped truth columns are array-equal. Fails today: `loso` passes the held-out storm's truth columns to `predict`.
- **MD-16** · P1 · `test_loso_equals_direct_refit`. **MD-17** · P1 · `test_loso_predictions_align_by_key_after_shuffle`.
- **MD-18** · P1 · `test_each_scorecard_column_on_its_own_toy`. **MD-19** · P1 · `test_half_out_cut_is_inclusive` (D-7).
- **MD-20** to **MD-23** · P2 — false alarm as a share of calls; peak totals skip rows without customers; the measurable-share definition; restore error NaN when no county has both days.
- **MD-24** · P1 · `test_window_column_feeds_restore_day`. **MD-25** · P1 · `test_fits_use_only_the_60_minute_truth` (isotonic, wind-only, hybrid). **MD-26** · P2 · `test_score_all_reuses_one_prediction_per_method`.
- **MD-27** · P0-I · regression · `tests/test_evaluate.py::test_restore_day_rule_pinned_for_the_pass_bar` — [0.05, 0.08, 0.02, 0.01, 0] → 2.0; a blip of 0.03 on day 19 of an otherwise zero series → 20.0; [0.8, 0.6, 0.3, 0.05, 0.02] → 3.0; [0.8, 0.05] → NaN. This pins the rule condition 3 of the recorded verdict used. D-3 corrects the decision-log sentence.
- **MD-28** · P1 · contract · `tests/test_restore_contract.py::test_restore_day_conventions_are_documented` — one-county cases (all zero, never out with a blip, out then back, a bounce back, NaN gaps) through `official_restore_day`, `export.official_restore`, `restoration_interval`, `restore_day_errors` and `scorecard` agree, or differ exactly as D-3 logs.
- **MD-29** · P1 · `test_restore_day_rejects_date_like_index`. **MD-30** · P2 · `test_restore_threshold_is_inclusive`.
- **MD-31** · P1 · property · `tests/test_ranges.py::test_range_coverage_zero_inflated_step_predictions` — fold A at levels {0.002, 0.010, 0.050} and fold B at {0.003, 0.012, 0.060}; truth 0 with p 0.85 → coverage on B in [0.70, 0.90], and ≥ 0.5 on truth ≥ 0.1. Fails today (0.22). The fix is a change to the app's ranges after the opening (D-11).
- **MD-32** · P1 · `test_ranges_population_matches_the_app`. **MD-33** · P1 · `tests/test_final.py::test_main_storm_ranges_are_labelled_in_sample` — `predictions_<main>.parquet` carries `in_sample_ranges`, and the export shows it, unless the ranges are nested. Fails today.
- **MD-34** · P1 · `test_interval_brackets_hidden_crossing_under_random_clouds`. **MD-35** · P2 · `test_interval_edges`. **MD-36** · P1 · `test_estimated_interval_brackets_estimated_restore_day` (fails on bounce backs; resolved by D-3).
- **MD-37**, **MD-38** · P2 — aware pass times and bool hours; stale looks.
- **MD-39** · P1 · `test_wind_only_population_is_the_plan_rows` (0.32 in the toy; D-13). **MD-40** · P2 · `test_wind_only_unseen_band_convention_is_shared`.
- **MD-41** · P1 · property · `test_realistic_snr_world_power` — calm sd 0.22 and about 80% zeros → hybrid peak ratio ≥ 0.5 and maximum ≥ 0.5; the isotonic values are recorded.
- **MD-42** · P1 · property · `tests/test_immutability.py::test_public_functions_do_not_mutate_inputs` — parametrized over the data, build, model, product and `final` public functions, `county_noise` and `satellite_test` included.
- **MD-43** · P2 · `test_hybrid_is_monotone_in_wind_band`. **MD-44** · P1 · `test_perfect_predictor_meets_restore_bar_in_a_clean_world`.

### 5.5 Data layer (`outages.py`, `nightlights.py`, `laads.py`, `storms.py`, `winds.py`, `counties.py`, `scripts/fetch_eaglei.py`)

Line coverage here is 86–98%, but the data-layer audit found 13 of 15 targeted mutants surviving. DL-01, DL-02, DL-03, DL-05, DL-06, DL-07 and DL-20 kill the ones that matter.

- **DL-57** · P1 · unit · `tests/test_storms_winds_counties.py::test_first_pass_after_landfall_is_inside_the_event_window` — Arrange: every storm's `landfall` and `landfall_utc` from config, and `tests/fixtures/county_points.csv`. Act: for each storm, the first pass after `landfall_time` per county from `pass_time_utc(night + 1, lon)` (no table read), and its night label. Assert:
  - the night is ≥ landfall for every pass at least 1.5 h after landfall;
  - passes within ±1.5 h are listed for review;
  - laura2020 and uri2021 are allowed only through an allowlist citing D-16.
  
  The real-data companion uses stored pass_utc: Laura's night-2020-08-26 pass is at 07:50 UTC on Aug 27, with 296,252 customers out in hit counties.
- **DL-58** · P1 · unit · `tests/test_storms_winds_counties.py::test_no_other_storm_blows_through_a_baseline_or_event_window` — Arrange: the extended `hurdat2_small.txt` and `county_points.csv`. Act: `band_at_points` of each tropical-storm or hurricane track outside the roster over each project storm's counties, during [baseline_start, baseline_end] and [landfall, window_end]. Assert: no county reaches ≥ 34 kt unless the (storm, intruder, window) triple is allowlisted with D-17. Today's allowlist:
  - laura2020 / Hanna / baseline (16 TX counties);
  - isaias2020 / Fay / baseline (37);
  - ida2021 / Fred / baseline (6 AL);
  - beryl2024 / Alberto / baseline (19 TX);
  - laura2020 / Sally / event (4 LA and MS);
  - ida2021 / Nicholas / event (4 LA).
  
  Lockbox storms are computed from config and HURDAT2 only. The real-data companion lists the counties in S16, says whether they are hit counties of the host storm, and gives the calm-night sd with and without the intruder's nights.
- **DL-01** · P1 · unit · `tests/test_nightlights.py::test_clear_mask_truth_table` — 192 pixels covering quality × cloud bits 6–7 × snow × radiance → mask == (quality 0) & (confidence ≤ 1) & (snow 0, or snow 1 with allow_snow) & finite; 128 ("probably cloudy") is never clear.
- **DL-02** · P1 · regression · `tests/test_outages.py::test_county_of_unloaded_state_is_nan_not_zero` — "13121" against window B (Florida only) → NaN from `customers_out_at` and `OutageIndex`; an empty index → NaN.
- **DL-03** · P1 · unit · `test_band_50_between_radii` — r34 150, r50 80, r64 40 nm; boxes about 20, 60, 120 and 200 nm east → 64, 50, 34, 0.
- **DL-04** · P1 · contract · `test_no_baseline_overlaps_an_earlier_event_in_shared_states` — empty unless allowlisted with a log entry. Fails today for michael2018 against florence2018 (22 nights; GA, NC, SC) until D-4 is logged.
- **DL-05** · P1 · `test_zero_radiance_is_dark_not_fill`.
- **DL-06** · P1 · `tests/test_outages.py::test_dropout_rule_exact_boundaries` — S exactly 0.93 × B; recovery to exactly 93,000; a county exactly 0.93 × its shoulder; county loss exactly 0.5 × state loss; the four constants equal the decision log.
- **DL-07** · P1 · `test_empty_cells_in_dip_are_flagged` (and Jefferson 22051 at 17:30 in window H).
- **DL-10** · P1 · `test_outage_index_matches_customers_out_at` (300 seeded triples). **DL-11** · P1 · `test_absent_rows_equal_explicit_zero_rows`.
- **DL-12** · P1 · `test_malformed_fips_and_window_rejected` ("1207", the integer 12071, "12071 ", −15; fails today). **DL-13** · P1 · `test_window_across_dst_transitions_is_exact`. **DL-14** · P1 · `test_unpadded_varchar_codes_rejected` (fails today).
- **DL-15** · P1 · `test_state_prefixes_map_usps_to_fips`. **DL-16** · P1 · `test_storm_roster_matches_plan`, which also checks satellites: beryl2024 is VJ146A2, every other storm VNP46A2.
- **DL-17** · P1 · `test_states_cover_wind_zone_offline` (`county_points.csv`; runs in CI). **DL-18** · P1 · `tests/test_counties_offline.py::test_load_counties_offline_tiny_census`. **DL-19** · P1 · `test_repair_customers_boundaries`.
- **DL-20** · P1 · `test_quadrant_boundaries_at_cardinal_bearings`.
- **DL-21** · P1 · `tests/test_laads.py::test_token_sources_and_precedence` (chdir to tmp first). **DL-22** · P1 · `test_token_not_forwarded_on_cross_origin_redirect`. **DL-23** · P1 · `test_tls_verification_stays_on`. **DL-24** · P1 · `test_errors_never_contain_the_token`.
- **DL-25** · P1 · `test_overlapping_lockbox_windows_are_documented` (D-5).
- **DL-26** · P2 · `test_parse_name_rejects_impossible_day_of_year` (fails today). **DL-28** · P2 · `test_parse_hurdat2_quirks`. **DL-29** · P2 · `test_quadrant_index_never_exceeds_3` (fails today: IndexError). **DL-30** · P2 · `test_storm_record_validation`.
- **DL-31** to **DL-34** · P2 — LAADS: gives up after retries with backoff; listing fails loudly and filters; the cloud tried first; reuses valid files and replaces corrupt ones.
- **DL-35** · P2 · `tests/test_fetch_eaglei.py::test_fetch_eaglei_converts_sum_column`. **DL-36** to **DL-42** · P2 — naive end and empty window; tz-aware parquet; unsupported sources; missing state runs inside a dip; dips cut by load edges; the flag output contract; bad frames.
- **DL-43**, **DL-44**, **DL-46** to **DL-54** · P2 — as in the first draft: name round trip, pass-time contract, layer-reader edges, tropical-track gaps, a one-fix track, distance and NaN radii, newest granule version, `read_remote` dispatch, Census downloads, fixture bytes, load-window margin.
- **DL-55**, **DL-56** · P2 · smoke (network) · `tests/test_network_smoke.py` — run by hand only, with the user's token in the local environment, never as a repository secret.

### 5.6 Build layer (`aggregate.py`, `table.py`, `cli.py`)

- **BL-01** · P1 · `tests/test_aggregate_table.py::test_label_grid_counts_a_pixel_only_when_its_centre_is_inside`. **BL-02** · P1 · `test_label_grid_puts_a_tiny_polygon_on_the_right_pixel`. **BL-03** · P1 · `test_county_with_no_pixel_centre_is_not_measurable`.
- **BL-04** · P1 · integration · `tests/test_build_offline.py::test_offline_build_label_cache_stays_inside_tmp` — every path given to `np.load` and `np.savez_compressed` lies under `tmp_path`. Fails today.
- **BL-05** · P1 · `test_baseline_skips_cloudy_and_snowy_nights`. **BL-06** · P1 · `test_build_uses_only_the_storms_baseline_nights`. **BL-07** · P1 · `test_combine_medians_uses_the_tile_with_most_valid_pixels`.
- **BL-08** · P1 · `test_dark_min_and_visible_min_are_inclusive`. **BL-09** · P1 · `test_finalize_never_gives_unseen_counties_a_number`.
- **BL-10** · P1 · `test_corrupt_a2_file_makes_the_night_unseen_and_reported`. **BL-11** · P1 · `test_night_missing_from_archive_is_unseen`. **BL-12** · P1 · `test_missing_a1_falls_back_to_the_formula_and_is_reported` (fails today).
- **BL-13** · P1 · `test_official_columns_shared_index_matches_one_off_reads`. **BL-14** · P1 · `test_official_columns_nan_for_a_state_without_runs`. **BL-15** · P1 · `test_official_windows_nest`.
- **BL-16** · P1 · `test_drop_rule_boundaries`. **BL-17** · P1 · `test_offline_main_storm_build_uses_hurdat_wind_bands`.
- **BL-18** · P1 · `test_refresh_customers_rewrites_only_customer_columns`. **BL-19** · P1 · `test_with_customers_zero_or_missing_never_gives_zero`.
- **BL-20** · P1 · `test_missing_token_fails_before_slow_work` (fails today). **BL-21** · P1 · `test_extract_eaglei_filters_states_and_dates`. **BL-22** · P1 · `test_token_never_logged_or_saved`. **BL-23** · P1 · `test_lee_sample_reproduces_phase0_timing`.
- **BL-48** · P1 · integration · `tests/test_build_offline.py::test_build_writes_provenance_metadata` — Act: the offline build. Assert: the parquet's key-value metadata holds `code_sha256` (`table.py` and `aggregate.py`), `customers_sha256` (the MCC, coverage and ACS inputs) and `satellite`; `pyarrow.parquet.read_schema` returns them without reading any value; `refresh_customers` updates `customers_sha256`.
- **BL-24** to **BL-46** · P2 — as in the first draft: the label cache key and its hit; a corrupt cache; baseline chunking and medians; sums across a tile split and in any pixel order; county_night length; dark and hidden counties; unexpected read errors; quicklooks; formula labels; mixed-pass counts; the summary matching the table; tiles without counties; a crash after the table write; CLI failure lists and argument errors; code bugs not reported as network failures; extract-only; no tile files; tracked imports; speed of the shared index.
- **BL-47** · P2 · integration · `tests/test_build_offline.py::test_summary_log_and_quicklooks_carry_no_official_values` — Act: build twice, the second time with every `official_*` column replaced by poison values; capture stderr. Assert: identical quicklook paths, peak night and summary JSON; no `official` key in the summary; the log never prints a customers-out total. This restores the audit's R-LOCK-8 for the next holdout.

### 5.7 Product (Python) and the Python–TypeScript contract

- **PX-01** · P0-R · smoke · `tests/test_export_integrity.py::test_committed_sample_exports_a_usable_demo` — Arrange: the committed `data/sample/` including `predictions_ian_sample.parquet` (`50d572e`). Act: `export_sample(out=tmp)`. Assert:
  - Lee (12071) has a non-null est on at least one night from 2022-09-28;
  - at least one 72 h bracket is not null;
  - the claims include a "review" and a "fits" under the claim-verdict twin;
  - the predictions parquet's metadata holds `hybrid_sha256` and `source_commit`, and `hybrid_sha256` equals sha256(`src/blackout/hybrid.py`) at HEAD. Otherwise: "regenerate the sample locally with scripts/make_sample_predictions.py".
  
  Fails today on the metadata: the script writes none. This catches a sample built from garbage or from a stale model, and RD-35 checks its values locally.
- **PX-02** · P0-R · contract · `test_export_cross_file_integrity` — the new `export.verify_export(folder)`:
  - the keys of nights, restoration and exposure equal the county fips;
  - claim fips are a subset of counties with an outage;
  - claim policy ids are unique and present in `make_portfolio`;
  - home + business == 100,000;
  - the index entry equals meta;
  - every nights list follows meta.nights;
  - lo ≤ est ≤ hi wherever present.
  
  Run it on the toy export and after every real export, locked storms included.
- **PX-03** · P1 · property · `test_export_never_writes_numbers_where_it_cannot_see`. **PX-04** · P1 · `test_serialize_refuses_nan_and_infinity`.
- **PX-05** · P1 · `tests/test_portfolio.py::test_portfolio_and_claims_golden_digest`. **PX-06** · P1 · `test_export_is_byte_reproducible_with_a_fixed_clock`. **PX-07** · P1 · `test_portfolio_invariants`. **PX-08** · P1 · `test_claims_invariants`.
- **PX-09** · P1 · `tests/test_cli.py::test_cli_export_sample_writes_only_to_out` (a new `--out`). **PX-10** · P1 · `test_export_with_the_real_modules_is_mandatory`. **PX-11** · P1 · `test_main_storm_export_does_not_need_the_lockbox`. **PX-12** · P1 · `test_cli_export_writes_scored_scorecard`. **PX-13** · P1 · `test_hour_marks_count_from_the_landfall_time_in_export`.
- **PX-15** · P2 · `test_claims_small_book_uses_bankers_rounding`. **PX-16** · P2 · `test_portfolio_defaults_match_plan`. **PX-17** · P2 · `test_failed_write_keeps_the_previous_export`.
- **CT-01** · P0-R · contract · `tests/test_contract.py::test_app_fixture_validates_against_export_schema` — every file under `app/src/__fixtures__/`, `app/e2e/fixtures/data/` and `app/public/data/` validates against its `$def` with `Draft202012Validator`.
- **CT-02** · P0-R · contract · `test_golden_export_is_current` — the toy world exported with `SOURCE_DATE_EPOCH` is byte-identical to `tests/fixtures/contract/golden/<id>/`; `expected.json` holds `expected_policies_out` at 24/48/72.
- **CT-03** · P0-R · contract · `app/src/data/contract.test.ts` 'parses the Python golden export' — `parseStormFiles` accepts the golden files; nights follow meta; `expectedPoliciesOut` equals expected.json; claim ids round-trip.
- **CT-04** · P0-R · contract · `tests/fixtures/contract/cases.json` — about 30 valid and invalid documents, read by both validators: cant_see with est 0.0; est 1.5; official 1.25; fips "1207"; status "cloudy"; brackets of 1 or 3 values; window 45; satellite "MODIS"; state "Florida"; storm ids "ian-2022" and "_x"; claimed_days_out −1; lo > est. The two may disagree only on cases marked ts-lenient.
- **CT-05** · P0-R · contract · `contract.test.ts` 'enums, required keys and patterns match the schema'. Fails today: TS `STORM_ID` is `/^[a-z0-9][a-z0-9_-]*$/` and the schema's is `^[a-z0-9_]+$`.
- **CT-06** · P0-R · contract · `app/src/lib/exposure.test.ts` 'exposure matches the Python toy', made strict: no inline fallback.
- **CT-07** · P1 · data-validation · `test_app_fixtures_are_synthetic` — every fixture storm's meta notes contain "SYNTHETIC", every fips starts with "99", no real USPS state code appears; rename `milton` to `synth2099`.
- **CT-08** · P1 · contract · `tests/test_product_eval.py::test_claim_verdict_matches_shared_toy` + `claims.test.ts` 'claimVerdict matches the Python toy' (`tests/fixtures/claims_toy.json`).

### 5.8 App unit tests (vitest, happy-dom)

Today there are 14 test files with about 93 cases. StormMap, patterns.ts, RestorationChart, NightTimeline, MapErrorBoundary and the hooks have no direct tests. ScorecardTable has 2 cases (`a654655`, edited in `966313a`).

- **AU-01** · P0-R · regression · `CountyCard.test.tsx` 'shows no numbers on a can't-see night even with stray lo/hi' — {cant_see, est null, lo 0, hi 0.1} → no digit in the headline; customers out "—"; homes out "—". Re-check after `966313a`, which changed CountyCard.
- **AU-02** · P0-R · contract · `validate.test.ts` 'parseNights rejects numbers on a non-ok night' — {not_measurable, est 0.0} → DataShapeError naming "<fips>[i].est". Fails today.
- **AU-03** · P0-R · unit · `StormMap.test.tsx` 'colors only ok counties and hatches the rest' — a recording maplibre stub. The fill expression returns paper unless the status is ok; there is one hatch layer per unseen status; no tiles, glyphs or sprite URL; official dots only with the toggle on.
- **AU-04** · P0-R · unit · `patterns.test.ts` 'hatch tiles' — 16 × 16 RGBA tiles; ink exactly where (x + y) % 16 < 2; ink against paper ≥ 3:1; the mean colour ≥ ΔE2000 10 from RAMP[0].
- **AU-05** · P0-R · regression · `flags.test.ts` 'a flag in one storm does not flag the same claim id in another storm' — flags are namespaced by storm and the existing `bfs.flags.v1` data migrates. Fails today: claim ids C0001–C0200 repeat in every storm.
- **AU-06** to **AU-16** · P1, as in the first draft:
  - unknown never renders as 0; the ramp under colour-vision deficiency;
  - RestorationChart; NightTimeline;
  - ScorecardTable, extending its existing file: one winner per metric, none on ties, and hybrid and wind_timing labelled as not the pre-registered model;
  - a map failure leaves the report working; the PortfolioPanel dash and "Show all";
  - focus after flagging (fails today); a superseded load ignored; a valid shared link; the flag count per storm.
- **AU-25** · P1 · unit · `Masthead.test.tsx` 'the verdict shown is the curve's and the map's model is labelled secondary' — with a fixture scorecard holding the verdict and the satellite-test fields, the masthead shows the pass-bar verdict string unchanged, and the map's estimates are labelled as the storm-context model (`966313a`).
- **AU-17** to **AU-24** · P2 — `colorForShare` refuses NaN; retry; `replaceState` throwing; 1e999; storage recovering; never "fraud"; the CC BY credit on every screen; the landfall-time clock in the copy.

### 5.9 Browser: end to end, visual, accessibility, performance (Playwright)

Setup:
- `app/playwright.config.ts` with the chromium project only in CI.
- `vite build --mode e2e` into `dist-e2e`.
- `app/scripts/prepare-e2e-data.mjs` copies the synthetic `app/e2e/fixtures/data/` and the sample artifact. It refuses any other storm without the SYNTHETIC marker.
- Every spec waits on `[data-map-state="ready"]` or `[data-map-state="fallback"]`, never on timeouts.
- New dev dependencies (@playwright/test, @axe-core/playwright) and the browser download (about 0.6–1 GB for three engines) need the user's OK.

- **WB-01** · P0-R · e2e · `app/e2e/morning-after.spec.ts` 'storm walkthrough: map, county card, portfolio at 72 h, flag a claim' — open `./?storm=synth2099`, accept the defaults, flag the default review claim, reload. Assert:
  - the h1;
  - the slider says "first pass after landfall";
  - the card leads with the range;
  - the hour-72 headline equals the golden `expected_policies_out`;
  - the verdict reads "longer than X% of the county: review";
  - the flag survives the reload;
  - at most 6 user actions, no console errors, no failed requests.
- **WB-02** · P0-R · smoke · `sample-smoke.spec.ts` 'the quickstart sample renders estimates' — data from `uv run blackout export --sample --out <artifact>` → a county card shows a numeric estimate and the portfolio figure is not "—".
- **WB-03** · P1 · `offline.spec.ts` 'makes no third-party requests and sets no cookies'.
- **WB-04** · P1 · `responsive.spec.ts` 'no horizontal overflow from 320 to 1920 px' — at 320, 375, 759, 761, 768, 1024, 1079, 1081, 1440 and 1920 px (the CSS breaks at 760 and 1080).
- **WB-05** · P1 · a11y · `axe.spec.ts` 'no WCAG 2.2 AA violations' — the default report, a can't-see county, a flagged claim, the empty state and an error notice, at 1440 and 375 px.
- **WB-06** · P1 · a11y · `keyboard.spec.ts` 'keyboard-only storm walkthrough' (give `main#main` tabindex −1 for WebKit).
- **WB-07** · P1 · `flags.spec.ts` 'flag survives reload and stays in its storm'.
- **WB-08** · P1 · performance · `app/scripts/check-bundle.mjs` 'bundle stays inside the gzip budget' — initial JS ≤ 150 KB, CSS ≤ 50 KB, the StormMap + MapLibre chunk ≤ 300 KB, the worker ≤ 160 KB, all JS ≤ 560 KB, fonts (woff2) ≤ 130 KB. The MapLibre exception to ECC's 300 KB app budget is logged.
- **WB-09** · P1 · `check-bundle.mjs` 'built app references no third-party origins'.
- **WB-10** · P1 · visual · `visual.spec.ts` (@visual) — at 320, 768, 1024 and 1440 px, two states: the default report and a can't-see county, so 8 baselines. Frozen meta.generated, masked map canvas, maxDiffPixelRatio 0.002. Baselines come from the pinned Linux container only.
- **WB-11** · P1 · e2e · `responsive.spec.ts` 'touch: tap selects a county row and moves the slider' — a chromium context with `hasTouch: true, isMobile: true` at 375 × 812 (ECC's touch check without separate mobile projects).
- **WB-12** · P1 · a11y · 'focus is always visible'. **WB-13** · P1 · a11y · `reduced-motion.spec.ts`. **WB-14** · P1 · `errors.spec.ts`. **WB-15**, **WB-16**, **WB-17** · P1 · `deep-link.spec.ts` — a deep link restores the view; a storm switch mid-load; night labels in UTC−8 and UTC+14.
- **WB-20** · P1 · performance · `perf.spec.ts` (chromium) 'LCP, FCP and CLS within targets' (LCP < 2.5 s, FCP < 1.5 s, CLS < 0.1).
- **WB-22** · P1 · e2e · `smoke.spec.ts` on firefox and webkit — the report, card, portfolio and claim flow, with the map or its fallback. One local run is a Task 13 release gate, after the user approves the browser download. It runs nightly only once a remote exists.
- **WB-23** · P1 · 'opening with no link lands on the demo storm' (D-10; fails today). **WB-24** · P1 · 'storage blocked: the flag works for the session and says so'.
- **WB-25** · P2 · a11y · announcements. **WB-26** · P2 · visual · the map canvas in chromium only. **WB-27** · P2 · Lighthouse CI (`app/lighthouserc.json`, `upload.target: "filesystem"`; LCP ≤ 2,500 ms, CLS ≤ 0.1, TBT ≤ 200 ms, FCP ≤ 1,500 ms). **WB-29** · P2 · 'built index.html carries a CSP'.

### 5.10 Repo, CI and docs

- **RH-01** · P0-R · smoke · `tests/test_repo_hygiene.py::test_coverage_gate_configured` — `pyproject.toml` has `[tool.coverage.run] branch = true` and `[tool.coverage.report] fail_under = 80`; `ci.yml` runs `--cov-branch --cov-fail-under=80` and the per-module floors of §1. Today the gate covers lines only, with no floors.
- **RH-02** · P0-I · smoke · `tests/conftest.py` + `test_skips_are_registered_and_counted`:
  - the `realdata`, `lockbox`, `network` and `slow` markers are registered, and `--run-lockbox` requires `docs/lockbox_result.json`;
  - allowed skip reasons live in one table, and the terminal summary prints the counts;
  - with `BLACKOUT_CI=1`, an unregistered skip reason fails the run;
  - `-m realdata` or `-m lockbox` collecting zero tests fails.
- **RH-03** · P0-R · smoke · `scripts/ci_local.sh` — `git clone --no-local . "$tmp"` (so `data/raw`, `data/interim` and `data/processed` are absent, as in CI), then the python job, the app unit job and, when the browsers are installed, the chromium e2e job, with exactly the commands in `ci.yml`. Exits non-zero on any failure. While there is no remote, it is the only CI.
- **RH-04** · P0-R · unit · `test_env_is_gitignored_and_never_committed` — extends test_secrets_and_data_stay_untracked with `git log --all --name-only` (fetch-depth 0) and a `.env.example` with empty values.
- **RH-05** · P1 · e2e · `scripts/fresh_clone_check.sh` — the Task 13 commands in a temp clone; each exits 0; nights.json has non-null est values.
- **RH-06** · P1 · smoke · the `ci.yml` app job — add `npm run lint` (oxlint), `npx vitest run --coverage` (v8; lines, functions and statements 80, branches 75) and `node scripts/check-bundle.mjs` to the existing job. Needs @vitest/coverage-v8.
- **RH-07** · P1 · smoke · a `ci.yml` e2e job in the pinned Playwright container, chromium only, uploading reports on failure.
- **RH-08** · P1 · `test_no_token_like_strings_in_tracked_files` (JWT, "Bearer " followed by 20 or more characters).
- **RH-09** · P1 · `test_data_and_build_outputs_are_gitignored` — `data/raw`, `data/interim`, `data/processed`, `.env`, `node_modules`, `app/dist-e2e`, `app/playwright-report`, `app/test-results`, `htmlcov`, `coverage.xml` and `app/coverage` are ignored; `data/sample` and `app/public/data` are tracked (D-9). Fails today: the build and test outputs are not ignored.
- **RH-10** · P1 · `tests/test_docs.py::test_markdown_links_resolve_to_tracked_files`.
- **RH-11** · P1 · `test_readme_has_required_sections_and_cc_by_credit`.
- **RH-12** · P1 · the contract freshness step in `ci.yml` — `make_app_fixture.py --check` with `SOURCE_DATE_EPOCH`, then `git diff --exit-code`.
- **RH-13** · P1 · `test_bunching_table_lists_every_non_lockbox_storm` — Ian, Idalia and Beryl are added from the per-storm extracts, never the 2024 yearly file (D-15). Fails today.
- **RH-14** · P2 · `test_decision_log_mentions_required_judgment_calls` — keywords for D-2 to D-20 (for example "first pass", "Hanna", "Alberto", "Sally", "Texas", "mixed satellites", "integrity").
- **RH-15** · P2 · code-size limits. **RH-16** · P2 · no deploy, publish, push or credential steps in workflows. **RH-17** · P2 · declared dependencies cover imports (scipy is not declared today).
- **RH-18** · P2 · smoke · `.github/workflows/nightly.yml` — only once a remote exists: firefox and webkit smoke, Lighthouse CI with `upload.target: "filesystem"`, and the fresh-clone job. No network tests, no repository secrets, no macOS runner, no mobile projects.
- **RH-19** · P2 · `test_failures_page_covers_required_cases`. **RH-20** · P2 · `test_sample_files_stay_small`. **RH-21** · P2 · `test_writeup_names_the_shipped_model_and_the_tiers` — `docs/writeup.md` names the hybrid as secondary and post hoc beside the pre-registered curve, and labels LOSO as design loop.

### 5.11 Dropped since the first draft

- **Overtaken by the opening:**
  - LB-14: merged into LB-13.
  - LB-22, the dress rehearsal: its equivalence check moves to RD-36 and its run to the LB-42 reproduction.
  - LB-33: merged into LB-35.
  - The first draft's readiness gate and its gate-only uses of RD-22, RD-23 and RD-25: these are now reported.
- **Cut for size (review finding 16):** DL-08 and DL-09 (the dropout rule's metamorphic and oracle checks; 17 rule tests on real rows remain), DL-27, DL-45, PX-14, PX-18, PX-19, CT-09, WB-18 and WB-19 (pixel hatch check and its test hook), WB-21, WB-28, the Mobile Chrome and Mobile Safari projects, and the macOS WebKit runner.

---

## 6. CI plan

When this plan was revised the repo had no remote, so GitHub Actions had never run. Since the first push, on 2026-11-09, the `ci` workflow runs there on every push and pull request; `scripts/ci_local.sh` (RH-03) runs the same jobs with the same commands in a temporary clone.

| Job | Runs on | Steps | Caching | Artifacts |
|---|---|---|---|---|
| `python` (exists; extend) | ubuntu-latest | `actions/checkout@v4` with `fetch-depth: 0`; `astral-sh/setup-uv@v5` (Python 3.13); `uv sync --locked`; `uv run ruff check src tests scripts`; `uv run pytest -m "not realdata and not lockbox and not network" --cov=blackout --cov-branch --cov-report=xml --cov-report=term-missing --cov-fail-under=80 -rs`; per-module floors (`coverage report --include=<module> --fail-under=<floor>`); contract freshness (RH-12); `uv run blackout export --sample --out $RUNNER_TEMP/sample-data` | setup-uv cache keyed on `uv.lock` | `coverage.xml`, `htmlcov/`, `sample-data/` |
| `app` (exists; extend) | ubuntu-latest | Node 24; `npm ci`; `npx tsc --noEmit`; `npm run lint`; `npx vitest run --coverage`; `npm run build`; `node scripts/check-bundle.mjs` | npm cache keyed on `app/package-lock.json` | coverage summary |
| `app-e2e` (new; needs both) | container `mcr.microsoft.com/playwright:<pinned>` | download `sample-data`; `npm ci`; `npx vite build --mode e2e --outDir dist-e2e`; `node scripts/prepare-e2e-data.mjs`; `npx playwright test --project=chromium` (E2E, `@visual`, axe, keyboard, responsive, touch, perf) | npm cache; browsers in the container | on failure: `playwright-report/`, traces, screenshot diffs (14 days) |
| `nightly` (P2, only with a remote) | ubuntu container | firefox and webkit smoke; Lighthouse CI with `upload.target: "filesystem"`; `scripts/fresh_clone_check.sh` | as above | reports |

**Local-only gates:**
- Before committing scorecard numbers: `uv run pytest -m realdata`.
- For M-AUDIT, and again after any change under `data/processed`: `uv run pytest -m lockbox --run-lockbox`.
- Before release: one local `npx playwright test --project=firefox --project=webkit` of WB-22, after the user approves the download.
- Network smoke tests run by hand only, with the user's token in the local environment. Uploading `EARTHDATA_TOKEN` as a repository secret would be a credential upload, so the plan never does it. (The on-demand `reproduce` workflow, added after this plan, does read the token from a repository secret: see `docs/reproduce/plan.md`.)

**What may skip, and how skips are reported.** Allowed skip reasons live in one table in `tests/conftest.py`:
- built tables absent (`realdata`);
- `data/raw/census` absent, until DL-17 and DL-18 replace the four Census-dependent tests in CI;
- `docs/lockbox_result.json` absent (`lockbox`);
- network not requested (`network`);
- shallow clone (git-history tests);
- the Playwright map fallback off chromium (`webgl`).

The terminal summary prints counts per reason, and `-rs` lists them. With `BLACKOUT_CI=1`, any other skip reason fails the job. `xfail` is allowed only with `strict=True`, for doc tests waiting on a named decision.

**Determinism in CI.** `SEED = 20261105`; `SOURCE_DATE_EPOCH` for exports; Playwright retries 0 on pull requests and traces on failure.

---

## 7. Ordered implementation backlog

Sizes: S is up to 2 hours; M is half a day to a day; L is two to three days. P0-I is about 4–5 working days for one engineer; P0-R about 5; P1 about 20; P2 about 8.

**Expected red at the start** (fail at `966313a` until the named fix lands):
- **P0-I:** LB-08, LB-10, LB-13, LB-39, LB-37, LB-44, LB-45, MD-46 (no hashes pinned yet).
- **P0-R:** PX-01 (metadata), CT-05, AU-02, AU-05, RH-01 (branch coverage and floors), and AU-01 until it is re-checked after `966313a`.
- **P1:** LB-16, LB-19, LB-26, LB-35, MD-15, MD-31, MD-33, MD-36, MD-45, DL-04, DL-12, DL-14, DL-57, DL-58, RD-07, EV-21, EV-45, BL-04, BL-12, BL-20, AU-13, WB-23, RH-09, RH-13.
- **P2:** LB-12, LB-15, RH-17, DL-26, DL-29, BL-26.

LB-40 to LB-43 are unknown until run: their outcome depends on the recorded result, which this revision did not read.

### P0-I: integrity of the recorded opening, and no second opening

| # | Work item | Tests | Files to edit or add | Size |
|---|---|---|---|---|
| B-01 | Freeze the record and its inputs (M-AUDIT step 1) | LB-45, LB-44 | `docs/lockbox_result.json`, `docs/lockbox_record.json`, `scripts/record_lockbox_inputs.py`, `tests/test_lockbox.py`, `tests/realdata/test_after_opening.py` | S |
| B-02 | Markers, skip accounting, `--run-lockbox` | RH-02 | `pyproject.toml`, `tests/conftest.py`, `tests/realdata/conftest.py` | S |
| B-03 | No second opening: an opening marker, refusal, a reopen protocol that never overwrites | LB-13, LB-39 | `src/blackout/final.py`, `src/blackout/cli.py`, `tests/test_final.py`, `tests/test_cli.py`, `docs/decision-log.md` (D-12) | M |
| B-04 | Pass-bar fidelity and a pure verdict function with the drop rule | LB-02 to LB-08, LB-10, LB-36, LB-37, MD-27 | `src/blackout/final.py` (`verdict`; `satellite_test` reads keys strictly), `tests/test_final.py`, `tests/test_lockbox.py`, `tests/test_evaluate.py` | M |
| B-05 | Integrity of the recorded run, and disclosure | LB-40, LB-41, LB-42, LB-43, RD-24 | `tests/realdata/test_after_opening.py`, `tests/realdata/test_gates.py`, `src/blackout/final.py` (`render_integrity`), `docs/decision-log.md` (D-20), `docs/scorecard.md` (S1a) | M |
| B-06 | The frozen model is the shipped model | LB-21, MD-46 | `tests/test_lockbox.py`, `tests/test_hybrid.py`, `tests/synthetic_world.py` | S |
| M-AUDIT | Render S1–S3 per §0.14 (EV-30 lands in B-12) and log D-2 to D-19 | — | `docs/scorecard.md`, `docs/decision-log.md` | S |

### P0-R: before the app, README or write-up is shown to anyone

| # | Work item | Tests | Files to edit or add | Size |
|---|---|---|---|---|
| B-07 | Coverage gate completed, a faithful local CI, secret hygiene | RH-01, RH-03, RH-04 | `pyproject.toml`, `.github/workflows/ci.yml`, `scripts/ci_local.sh`, `tests/test_repo_hygiene.py` | S |
| B-08 | The sample is genuine and current; export integrity | PX-01, PX-02, RD-35 | `scripts/make_sample_predictions.py` (write metadata), `data/sample/predictions_ian_sample.parquet`, `src/blackout/export.py` (`verify_export`), `tests/test_export_integrity.py`, `tests/realdata/test_sample.py` | M |
| B-09 | Python–TypeScript contract | CT-01 to CT-06 | `tests/test_contract.py`, `tests/fixtures/contract/`, `tests/fixtures/make_app_fixture.py`, `app/src/data/contract.test.ts`, `app/src/lib/exposure.test.ts`, `app/src/data/validate.ts` | M |
| B-10 | App fixes for unseen counties and flags | AU-01 to AU-05 | `app/src/components/CountyCard.tsx`, `app/src/data/validate.ts`, `app/src/test/maplibre-stub.ts`, `StormMap.test.tsx`, `patterns.test.ts`, `app/src/lib/flags.ts`, `ClaimCheck.tsx` | M |
| B-11 | First browser tests | WB-01, WB-02 | `app/playwright.config.ts`, `app/e2e/`, `app/scripts/prepare-e2e-data.mjs`, `StormMap.tsx` (`data-map-state`), `app/package.json` (after the user's OK) | M |

### P1: complete the evaluation, then harden each layer

| # | Work item | Tests | Files | Size |
|---|---|---|---|---|
| B-12 | One diagnostics module, the reading, labels | EV-45, EV-01 to EV-03, EV-05, EV-06, EV-30, EV-46, EV-48, MD-13 | `src/blackout/diagnostics.py` (moved from `evaluate.py`), `src/blackout/evaluate.py`, `tests/test_diagnostics.py`, `tests/test_report.py` | M |
| B-13 | Uncertainty, forward chaining, bar strength | EV-10, EV-12 to EV-16, EV-47, RD-20, RD-21 | `src/blackout/diagnostics.py`, `tests/test_diagnostics.py`, `tests/realdata/test_gates.py` | M |
| B-14 | Ranges, duration and the report on real data | EV-18 to EV-22, EV-25, EV-28, EV-31, EV-32, RD-22, RD-23, RD-25, RD-27, RD-31, RD-34, RD-36 | `src/blackout/diagnostics.py`, `src/blackout/report.py`, `tests/realdata/test_gates.py`, `test_report.py`, `test_after_opening.py` | L |
| B-15 | Data design: first pass, other storms, Texas noise, mixed satellites | DL-57, DL-58, RD-07, EV-49, RD-01 | `tests/test_storms_winds_counties.py`, `tests/fixtures/build_hurdat2_fixture.py`, `tests/fixtures/hurdat2_small.txt`, `tests/fixtures/county_points.csv`, `src/blackout/table.py` (`validate_table`), `src/blackout/ablations.py`, `docs/decision-log.md` (D-16 to D-19) | M |
| B-16 | Ablations | EV-35, RD-32 | `src/blackout/ablations.py`, `src/blackout/cli.py` (`blackout ablate`), `tests/test_ablations.py` | M |
| B-17 | Product evaluation | EV-39, EV-40, EV-42 to EV-44, CT-08, RD-29, RD-30, EV-33 | `src/blackout/product_eval.py`, `tests/test_product_eval.py`, `tests/fixtures/claims_toy.json`, `app/src/lib/claims.test.ts` | M |
| B-18 | `final.py` hardening, trigger and NOAA-20 | LB-09, LB-11, LB-16, LB-18 to LB-20, LB-23 to LB-26, LB-28, LB-29, LB-31, LB-35, LB-38 | `src/blackout/final.py` (`failure_facts(satellite=None)`, D-6 trigger truth, the Uri note), `src/blackout/gitinfo.py`, `src/blackout/ranges.py`, `tests/test_final.py`, `tests/test_lockbox.py` | L |
| B-19 | Real-data validation, remainder | RD-02 to RD-06, RD-08 to RD-10, RD-12 to RD-15 | `tests/realdata/test_tables.py`, `test_truth.py`; `docs/decision-log.md` (D-15) | M |
| B-20 | Model layer | MD-01 to MD-09, MD-11, MD-14 to MD-19, MD-24, MD-25, MD-28, MD-29, MD-31 to MD-34, MD-36, MD-39, MD-41, MD-42, MD-44, MD-45 | `tests/test_model.py`, `test_evaluate.py`, `test_ranges.py`, `test_hybrid.py`, `test_overcount_contract.py`, `test_immutability.py`; `src/blackout/hybrid.py` (one band per county: a change after the opening), `src/blackout/ranges.py` (D-11), `src/blackout/evaluate.py` (strip truth before predict) | L |
| B-21 | Data layer | DL-01 to DL-07, DL-10 to DL-25 | `tests/test_outages.py`, `test_nightlights.py`, `test_storms_winds_counties.py`, `test_counties_offline.py`, `test_laads.py`; `src/blackout/outages.py` | L |
| B-22 | Build layer | BL-01 to BL-23, BL-48 | `tests/test_aggregate_table.py`, `test_build_offline.py`, `test_cli.py`; `src/blackout/aggregate.py`, `src/blackout/table.py` | L |
| B-23 | Product, Python | PX-03 to PX-13, CT-07, LB-17 | `tests/test_export_integrity.py`, `test_portfolio.py`, `test_portfolio_properties.py`, `test_export.py`, `test_cli.py`; `src/blackout/export.py`, `src/blackout/cli.py` | M |
| B-24 | App unit tests and app coverage | AU-06 to AU-16, AU-25, RH-06 | `app/src/**`, `app/vitest.config.ts`, `app/package.json` | M |
| B-25 | Browser suite | WB-03 to WB-17, WB-20, WB-22 to WB-24, RH-07 | `app/e2e/*.spec.ts`, `app/scripts/check-bundle.mjs`, `app/playwright.config.ts` | L |
| B-26 | Fresh clone and docs | RH-05, RH-08 to RH-13 | `scripts/fresh_clone_check.sh`, `tests/test_docs.py`, `tests/test_repo_hygiene.py`, `.gitignore`, `app/.gitignore` | M |

### P2: edges, extras and the next holdout

| # | Work item | Tests | Size |
|---|---|---|---|
| B-27 | The next holdout and lockbox extras | LB-01, LB-12, LB-15, LB-27, LB-30, LB-32, LB-34, BL-47 | M |
| B-28 | Diagnostics extras | EV-04, EV-07 to EV-09, EV-11, EV-17, EV-23, EV-24, EV-26, EV-27, EV-29, EV-34, EV-36 to EV-38, EV-41 | M |
| B-29 | Real-data extras | RD-11, RD-16 to RD-19, RD-26, RD-28, RD-33 | S |
| B-30 | Model-layer edges | MD-10, MD-12, MD-20 to MD-23, MD-26, MD-30, MD-35, MD-37, MD-38, MD-40, MD-43 | M |
| B-31 | Data-layer edges and network smoke | DL-26, DL-28 to DL-44, DL-46 to DL-56; move `test_storm_track_keeps_tropical_fixes` off Helene's track (AL092024) to AL092022 | L |
| B-32 | Build-layer edges | BL-24 to BL-46 | L |
| B-33 | Product, contract and app edges | PX-15 to PX-17, AU-17 to AU-24 | S |
| B-34 | Browser extras, nightly, docs and hygiene | WB-25 to WB-27, WB-29, RH-14 to RH-21 | M |

---

## 8. Open risks and what tests cannot cover

| Risk or limit | Why tests cannot settle it | Mitigation |
|---|---|---|
| **The lockbox is spent.** Every change after `50d572e` makes a new model or product whose numbers on Helene, Milton or Uri are not held out: the hybrid band fix (MD-45), the ranges fix (D-11), `966313a`'s clamp in the export | A one-shot test cannot be repeated | EV-48 labels; the recorded predictions stay the lockbox numbers; the next honest test is a storm not yet built (a 2025 or later landfall, built from NOAA-20), held out with LB-01's tripwire and BL-47's clean summaries |
| **The opening's code had gaps:** no opening marker, no `--confirm`, no guard against reruns; a verdict without the drop rule or "no verdict"; full locked tables read before the fits; locked truth not recomputed from the repaired customers; no expected-outcome entry | They happened before these tests existed | §0.3 checks (LB-40 to LB-44) and disclosure under D-20; the recorded verdict is never replaced by a rerun |
| **This revision did not read the result** | It follows the workflow's rule | The reading follows §0.14 mechanically; S3 is rendered by code (EV-30) |
| **EAGLE-I is an imperfect answer key.** Dropouts over 3 hours slip through (DEMCO on Ida). Over-counts remain (Ida 0.31% of values). MCC is modelled and repaired for 226 hit county-storm pairs. Uncovered states are left out. The 2022–2024 files have no empty counts. A county EAGLE-I never reports reads 0 | The truth's own errors are invisible to any comparison against it | The over-count rule; ±30 and ±90; ablations; RD-12; RD-13; S16 and `docs/failures.md` |
| **Clouds decide which nights are scored.** Scores exist only on clear nights, mostly after the storm. Measurable shares run from 39% to 73%. Laura's first pass after landfall, with 296,252 customers out, is scored nowhere (D-16) | Weather, not code | S4's outage-weighted share; S10's note; restoration intervals; can't-see never becomes zero |
| **The committed bar is weak in known ways.** Condition 1's comparator is diluted. Condition 2 can be met by timing decay. Condition 3 is set by never-out counties: "nothing" meets it on 4 of 8 storms under LOSO, the hybrid on 3 of 8 | The bar cannot change after its commit, and should not | S8's nulls and ceilings, including on the locked storms after the opening; the reading's wording rules |
| **The shipped model is post hoc** and every LOSO row is in the design loop. Forward chaining raises the hybrid's error on rows ≥ 10% out from 24.1 to 28.7 pp | Multiplicity is a reporting question | (B) was pre-registered before the opening; tiers in §0.2; EV-46 and EV-47 |
| **Few events, clustered errors.** 197 county-nights are at least half out, across 84 storm-counties, a third of them Ida's; two locked storms | Statistics, not code | Storm-level intervals and county bootstraps; two locked storms show gross failure only |
| **Overlapping storms.** Michael's baseline holds Florence's event nights; Helene's window holds Milton's landfall; other storms fall in Laura's, Isaias's, Ida's and Beryl's baselines and inside Laura's and Ida's event windows | A data-design choice; the scored storms' windows cannot change now | D-4, D-5, D-17; DL-04, DL-25, DL-58; S14 and S16 |
| **Texas is noisy.** Calm-night sd is 0.80 and 0.63, and 8–9% of calm nights read beyond ±100%. Uri is Texas-only | Light sources (flares, industry) and the storms in the baselines | RD-07 per state with D-18; the state slice; Uri's caveat |
| **Mixed satellites.** The final fits trained on 7 Suomi storms and 1 NOAA-20 storm and scored Suomi locked storms. Suomi NPP stopped on 2026-11-01/02, so future storms need NOAA-20 | Instrument physics | D-19; the Suomi-only ablation; NOAA-20 corrected agreement; Beryl's calm sd on both satellites |
| **No git remote** when this plan was revised; CI had never run (it has run on GitHub since 2026-11-09) | Pushing needed the user's OK | `scripts/ci_local.sh` in a temporary clone |
| **Browsers and WebGL.** Playwright browsers are not installed (about 0.6–1 GB, and the disk has filled before); headless Firefox and WebKit may fall back from WebGL | Environment | Chromium in CI; one local Firefox and WebKit run before release, after approval; specs accept the map fallback |
| **Real-data and lockbox tests are local** and could silently skip | They need gitignored data | RH-02 fails a marked run that collects nothing; M-AUDIT requires a green lockbox run |
| **Product semantics.** Claim labels use an absolute 10% restore day while the verdict uses 90% of the county's peak; the book and the claims are synthetic | A demo on synthetic data | The oracle (EV-42, EV-44); the write-up says the book is synthetic |
| **Light is not customers.** Generators, rural darkness, lights on separate circuits, snow | Physics | The failures page; slices; NOAA-20 |
| **Code in flux.** Other agents committed `c594d56` to `966313a` while this plan was being revised | Plans age | Tests target public functions; contract, golden and frozen-record tests catch drift; rerun the §7 red list when implementing |
| **New dependencies and downloads need the user's OK**: @playwright/test, @axe-core/playwright, @vitest/coverage-v8, the browsers; optionally Hypothesis | Policy | Seeded numpy loops; chromium-only CI; manual network smoke |
| **Many analyses after the opening invite cherry-picking** | Judgment | Only (A) and (B) support claims; everything else carries its tier label; slices are exploratory |

---

## Review notes

How each review finding was handled. "The opening" means `50d572e`, which landed while this revision was being written.

1. **Wrong Beryl table in `run_final`.** Accepted. It was mostly fixed before the opening by `db246a9`: `load_tables` now uses each storm's own table, and `test_load_tables_uses_each_storms_own_satellite` checks it. Three parts remain:
   - `failure_facts` still defaults to `satellite="VNP46A2"`;
   - `test_run_final_scores_the_lockbox_once` still stubs `table_path` with a lambda that ignores `satellite`;
   - the LOSO paths of `run_final` and `evaluate` are not checked against each other.
   
   These are LB-35 (with the poisoned `_vnp46a2` decoy) and RD-36 (which replaces the LB-22 assertion, since the dress rehearsal is overtaken). LB-41 confirms the recorded run read `county_nights_beryl2024.parquet`.
2. **Plan pinned to old results; gates break.** Partly accepted.
   - §0.1 and §8 are rebaselined on the eight-storm LOSO scorecard. The numbers moved slightly after `db246a9`: the review's hybrid figures of 2.81 / 0.200 / 24.5 / 0.957 are now 2.95 / 0.189 / 24.1 / 0.955.
   - Writing D-14 now, and replacing gate #6, are overtaken. The lockbox was opened before an expected-outcome entry existed; D-14 now records that fact.
   - Re-deriving thresholds from eight storms: accepted for bounds on data quality (RD-06 per storm, RD-07 per state with a logged Texas exception). Rejected for skill thresholds that judge the LOSO rows already seen (RD-22, RD-23, RD-27, the first draft's grade). A threshold set after seeing the numbers it judges passes by construction. They keep the first draft's values and are reported, not gated.
3. **The hybrid's LOSO rows are not held out.** Accepted and adapted.
   - D-1 was committed before the opening (`2187e37`) and corrected (`7fd2732`).
   - All eight main storms are tagged design loop. The hybrid changed at `db246a9` after all eight were visible, so the review's point that Beryl was scored after the freeze no longer holds.
   - The reading (§0.14) rests on the two pre-registered results; LOSO can only lower a claim (EV-46, EV-47).
   - The Uri guard is overtaken: committed code first scored Uri at the opening. Any later score on Uri or the locked storms carries EV-48's label. Whether ad-hoc probes scored Uri earlier is asked in D-20.
4. **The leakage guard only matches file names.** Mostly overtaken. The tripwire extensions (globs and directories, other readers, runs outside pytest), the window guard in `load_outages` and `extract_eaglei`, and chmod 000 all protect a lockbox that is shut. After the opening they would guard nothing.
   
   Kept:
   - LB-23 extends the static scans to `scripts/`, `tests/` and wildcard patterns.
   - LB-01 becomes a P2 tripwire for the next holdout, self-tested with a canary id, which removes the self-test hazard.
   - The Beryl bunching row comes from `data/interim/eaglei_beryl2024.parquet`, never the 2024 yearly file (D-15, RH-13).
5. **The one-shot opening can be retried and cannot be reproduced.** Accepted and adapted.
   - (a) The retry hole is real in the code that ran. Whether a retry happened is now a question of evidence (LB-41's mtimes, and D-20). Going forward, LB-13 writes an opening marker before the first read of a locked table, refuses reruns, and makes any reopen write a new file.
   - (b) LB-44 records table hashes, `uv.lock` and versions after the fact. The run itself recorded the git head, the dirty flag, code hashes and table names and row counts.
   - (c) LB-38 tests the git helper against a real temporary repo.
   - (d) LB-39 is the end-to-end ceremony test.
6. **Locked tables may hold stale customer counts.** Accepted and adapted to the recorded run: LB-43 compares, and shows both readings if they differ. For future builds, BL-48 adds parquet metadata (code sha, a hash of the customer inputs, satellite) that the preflight reads with `read_schema`.
7. **Nothing proves the verdict comes from the curve; the freeze covers only constants.** Accepted.
   - (a) LB-36.
   - (b) `early_stopping` was pinned in `db246a9`, and `test_deterministic` already checks that two fits match. MD-46 adds golden prediction hashes for `fit_hybrid`, `fit_wind_timing`, `fit_translation`, `WindOnly` and `pass_bar_check`, at P0-I. LB-21 checks the logged `TREE_PARAMS` and that `hybrid.py` did not change between the freeze and the run.
8. **Laura's first pass after landfall is outside every window.** Accepted and verified: the pass is at 07:50 UTC with 296,252 customers out in hit counties, and 6.5% of those counties were seen. DL-57 checks every storm; D-16 logs the call; S4 and S10 carry notes.
9. **Other storms inside baselines.** Accepted and extended. DL-58 reproduces Hanna, Fay and Fred. It also found Alberto in Beryl's baseline (19 TX counties), and Sally and Nicholas inside Laura's and Ida's event windows (4 counties each). D-17 logs them.
10. **Texas noise.** Accepted and verified: Texas calm-night sd is 0.803 in Laura's table and 0.625 in Beryl's, with 8.2% and 9.2% of calm nights beyond ±100%. Covered by RD-07 per state, the state slice, S14, S16 and D-18.
11. **Mixed satellites.** Accepted: RD-01's satellite and pass_source checks; the Suomi-only ablation (EV-49); LB-28's case of a storm whose own satellite is VJ146A2; Beryl's calm sd on both satellites in S14; D-19. §0.11 is rewritten.
12. **A second implementation of the diagnostics.** Accepted. `evaluate.diagnostics` and `satellite_increment` move into `diagnostics.py`, scored on common rows, with condition 2 through `final.first_difference_agreement` and AUC checked against scikit-learn (EV-45). `OUT_CUT` is pinned in LB-03.
13. **Tests that would pass with a wrong implementation.** Accepted: PX-01's metadata hash plus RD-35's value check; minimum call counts in LB-11, LB-16 and LB-20; and RD-22's bins moved to CAL_BINS with MIN_ROWS.
14. **Hybrid predictions depend on the batch.** Accepted. The refusal half was fixed in `db246a9`. MD-45 adds the invariance property. While checking it, this revision found that `county_noise` builds brightness bands per row with `rank(method="first")`, so one county's nights can fall in two bands (4 of 7 counties in a 7-county toy). Fixing it changes the hybrid after the opening, so it must be logged and labelled.
15. **CI and gating.** Accepted. The P0 split is now P0-I and P0-R rather than lockbox and release, because the opening has happened. `ci_local.sh` runs in a temporary clone. There is no network job and no repository secret. Lighthouse uses `upload.target: "filesystem"`. One local Firefox and WebKit run of WB-22 gates the release. RH-09 adds the build and test outputs. CI already has `--cov-fail-under=80` and an app job (`a51071b`); RH-01 and RH-06 extend them.
16. **Over-engineered.** Accepted, with two changes:
    - Touch checks stay, because ECC requires them, but through a chromium `hasTouch` context (WB-11) instead of the mobile projects.
    - The uncertainty helpers merge into `diagnostics.py`, not into `product_eval.py`. Bootstrap statistics and portfolio checks are unrelated concerns, and ECC organizes code by feature.
    
    The other cuts are listed in §5.11. The lean sets are P0-I (about 4–5 days) and P0-R (about 5 days).
17. **Small items.** Accepted:
    - LB-32 reads roles through `storms.load_storms`, one source that tests can inject;
    - BL-47 restores R-LOCK-8 at P2;
    - RH-14 covers D-16 to D-20.

Not done by this revision: reading any lockbox table, export or result, or the parts of `docs/scorecard.md`, README, `docs/writeup.md` and `docs/failures.md` written after `50d572e`. Probes here read only main-storm tables (laura2020, beryl2024, ian2022, ida2021), config dates, HURDAT2 tracks and the scorecard as it stood before its lockbox section existed.
