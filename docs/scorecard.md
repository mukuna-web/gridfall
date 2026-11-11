# Scorecard

*Written by `uv run blackout evaluate` on 2026-11-09. Every score is leave-one-storm-out: each main storm is predicted by a fit on the other main storms only. The numbers move as storm tables are added.*

How to read the opened lockbox, with the verdict tables laid out section by section: [docs/scorecard-reading.md](scorecard-reading.md).

- **Scored:** florence2018, michael2018, laura2020, isaias2020, ida2021, ian2022, idalia2023, beryl2024.
- **Not built yet, so not scored:** none.

## How to read it

- **Methods:** `isotonic` is the pre-registered night-light curve (angle- and moon-corrected % darker to % out); `wind_only` is the training storms' mean % out for the county's wind band; `nothing` says 0% out; `hybrid` adds the storm context (wind band, days since landfall) and each county's calm-night noise to the satellite reading; `wind_timing` is the same model with no satellite input, the test of what the satellite adds (decision log, "Model choice").
- **Scored county-nights:** landfall to window end (landfall + 21 days), counties with 34-kt winds or more, status `ok` (the satellite could see), states EAGLE-I covers (coverage ≥ 0.8), and a usable official count. Can't-see nights are left out, never scored as zero.
- **County error:** mean |estimate − official| in percentage points.
- **Peak out:** the largest one-night total of customers out over the scored counties, estimated and official, each at its own peak night.
- **Caught ≥50%:** share of county-nights officially at least half out that the method also put at least half out. **False alarms ≥50%:** share of the method's at-least-half calls that were officially under half.
- **Restore-day error:** median over hit counties of |estimated − official| restore day; restored means at or below 10% out after the peak and still there the next night.
- **Measurable:** share of hit-county nights in the window the satellite could see.
- **Over-counts:** official % out above 1.05 is dropped (EAGLE-I over-count or MCC under-count); 1.0–1.05 is clipped to 1.0.

## ±60 minutes (headline)

| Storm | Method | County error (pp) | Peak out, est. | Peak out, official | Caught ≥50% | False alarms ≥50% | Restore-day error (days) | Measurable | Rows scored | Over-counts dropped |
|---|---|---|---|---|---|---|---|---|---|---|
| florence2018 | isotonic | 0.9 | 58,596 | 136,535 | n/a | n/a | 5.0 | 57% | 1,328 | 0 |
| florence2018 | wind_only | 1.3 | 76,788 | 136,535 | n/a | n/a | 3.0 | 57% | 1,328 | 0 |
| florence2018 | nothing | 0.7 | 0 | 136,535 | n/a | n/a | 3.0 | 57% | 1,328 | 0 |
| florence2018 | hybrid | 1.6 | 463,561 | 136,535 | n/a | 100% | 3.0 | 57% | 1,328 | 0 |
| florence2018 | wind_timing | 1.6 | 259,099 | 136,535 | n/a | n/a | 3.0 | 57% | 1,328 | 0 |
| michael2018 | isotonic | 2.4 | 29,954 | 318,968 | 0% | n/a | 4.0 | 56% | 2,215 | 5 |
| michael2018 | wind_only | 2.6 | 37,474 | 318,968 | 0% | n/a | 1.0 | 56% | 2,215 | 5 |
| michael2018 | nothing | 2.3 | 0 | 318,968 | 0% | n/a | 1.0 | 56% | 2,215 | 5 |
| michael2018 | hybrid | 2.9 | 557,573 | 318,968 | 29% | 63% | 1.0 | 56% | 2,215 | 5 |
| michael2018 | wind_timing | 2.8 | 410,662 | 318,968 | 13% | 58% | 1.0 | 56% | 2,215 | 5 |
| laura2020 | isotonic | 4.9 | 17,061 | 210,617 | 0% | n/a | 6.0 | 52% | 937 | 9 |
| laura2020 | wind_only | 4.8 | 18,475 | 210,617 | 0% | n/a | 2.0 | 52% | 937 | 9 |
| laura2020 | nothing | 4.9 | 0 | 210,617 | 0% | n/a | 2.0 | 52% | 937 | 9 |
| laura2020 | hybrid | 4.1 | 180,215 | 210,617 | 18% | 12% | 2.0 | 52% | 937 | 9 |
| laura2020 | wind_timing | 3.6 | 168,024 | 210,617 | 8% | 25% | 2.0 | 52% | 937 | 9 |
| isaias2020 | isotonic | 1.5 | 135,545 | 1,367,368 | 0% | n/a | 5.0 | 44% | 1,697 | 1 |
| isaias2020 | wind_only | 2.0 | 245,594 | 1,367,368 | 0% | n/a | 2.0 | 44% | 1,697 | 1 |
| isaias2020 | nothing | 1.1 | 0 | 1,367,368 | 0% | n/a | 2.0 | 44% | 1,697 | 1 |
| isaias2020 | hybrid | 4.2 | 1,735,317 | 1,367,368 | 0% | n/a | 3.0 | 44% | 1,697 | 1 |
| isaias2020 | wind_timing | 3.5 | 2,436,836 | 1,367,368 | 0% | 100% | 3.0 | 44% | 1,697 | 1 |
| ida2021 | isotonic | 15.7 | 17,990 | 520,390 | 0% | n/a | 7.5 | 54% | 402 | 16 |
| ida2021 | wind_only | 15.1 | 32,670 | 520,390 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ida2021 | nothing | 15.9 | 0 | 520,390 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ida2021 | hybrid | 11.8 | 180,943 | 520,390 | 9% | 0% | 4.0 | 54% | 402 | 16 |
| ida2021 | wind_timing | 13.7 | 82,127 | 520,390 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ian2022 | isotonic | 1.3 | 88,572 | 1,431,863 | 0% | n/a | 9.0 | 62% | 2,428 | 1 |
| ian2022 | wind_only | 1.6 | 217,953 | 1,431,863 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| ian2022 | nothing | 1.0 | 0 | 1,431,863 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| ian2022 | hybrid | 1.6 | 1,811,172 | 1,431,863 | 71% | 47% | 3.0 | 62% | 2,428 | 1 |
| ian2022 | wind_timing | 1.5 | 1,251,690 | 1,431,863 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| idalia2023 | isotonic | 1.5 | 122,108 | 289,364 | 0% | n/a | 5.0 | 73% | 2,694 | 4 |
| idalia2023 | wind_only | 1.6 | 46,067 | 289,364 | 0% | n/a | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | nothing | 1.1 | 0 | 289,364 | 0% | n/a | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | hybrid | 2.1 | 391,137 | 289,364 | 5% | 0% | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | wind_timing | 2.2 | 1,202,964 | 289,364 | 10% | 33% | 2.0 | 73% | 2,694 | 4 |
| beryl2024 | isotonic | 5.8 | 192,471 | 2,167,400 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | wind_only | 6.1 | 186,048 | 2,167,400 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | nothing | 5.6 | 0 | 2,167,400 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | hybrid | 5.5 | 2,039,294 | 2,167,400 | 29% | 20% | 4.0 | 39% | 282 | 9 |
| beryl2024 | wind_timing | 5.2 | 1,971,221 | 2,167,400 | 29% | 20% | 4.0 | 39% | 282 | 9 |

## ±30 minutes

| Storm | Method | County error (pp) | Peak out, est. | Peak out, official | Caught ≥50% | False alarms ≥50% | Restore-day error (days) | Measurable | Rows scored | Over-counts dropped |
|---|---|---|---|---|---|---|---|---|---|---|
| florence2018 | isotonic | 0.9 | 58,596 | 136,446 | n/a | n/a | 4.5 | 57% | 1,327 | 0 |
| florence2018 | wind_only | 1.3 | 76,788 | 136,446 | n/a | n/a | 3.0 | 57% | 1,327 | 0 |
| florence2018 | nothing | 0.7 | 0 | 136,446 | n/a | n/a | 3.0 | 57% | 1,327 | 0 |
| florence2018 | hybrid | 1.6 | 463,561 | 136,446 | n/a | 100% | 3.0 | 57% | 1,327 | 0 |
| florence2018 | wind_timing | 1.6 | 259,099 | 136,446 | n/a | n/a | 3.0 | 57% | 1,327 | 0 |
| michael2018 | isotonic | 2.4 | 29,954 | 318,750 | 0% | n/a | 4.0 | 56% | 2,207 | 5 |
| michael2018 | wind_only | 2.6 | 37,474 | 318,750 | 0% | n/a | 1.0 | 56% | 2,207 | 5 |
| michael2018 | nothing | 2.3 | 0 | 318,750 | 0% | n/a | 1.0 | 56% | 2,207 | 5 |
| michael2018 | hybrid | 2.9 | 557,573 | 318,750 | 29% | 63% | 1.0 | 56% | 2,207 | 5 |
| michael2018 | wind_timing | 2.8 | 410,662 | 318,750 | 13% | 58% | 1.0 | 56% | 2,207 | 5 |
| laura2020 | isotonic | 4.9 | 17,061 | 210,616 | 0% | n/a | 6.0 | 52% | 937 | 9 |
| laura2020 | wind_only | 4.8 | 18,475 | 210,616 | 0% | n/a | 2.0 | 52% | 937 | 9 |
| laura2020 | nothing | 4.9 | 0 | 210,616 | 0% | n/a | 2.0 | 52% | 937 | 9 |
| laura2020 | hybrid | 4.1 | 180,215 | 210,616 | 18% | 12% | 2.0 | 52% | 937 | 9 |
| laura2020 | wind_timing | 3.6 | 168,024 | 210,616 | 8% | 25% | 2.0 | 52% | 937 | 9 |
| isaias2020 | isotonic | 1.5 | 135,545 | 1,365,518 | 0% | n/a | 5.0 | 44% | 1,697 | 1 |
| isaias2020 | wind_only | 2.0 | 245,594 | 1,365,518 | 0% | n/a | 2.0 | 44% | 1,697 | 1 |
| isaias2020 | nothing | 1.1 | 0 | 1,365,518 | 0% | n/a | 2.0 | 44% | 1,697 | 1 |
| isaias2020 | hybrid | 4.2 | 1,735,317 | 1,365,518 | 0% | n/a | 3.0 | 44% | 1,697 | 1 |
| isaias2020 | wind_timing | 3.5 | 2,436,836 | 1,365,518 | 0% | 100% | 3.0 | 44% | 1,697 | 1 |
| ida2021 | isotonic | 15.7 | 17,990 | 519,849 | 0% | n/a | 7.5 | 54% | 402 | 16 |
| ida2021 | wind_only | 15.1 | 32,670 | 519,849 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ida2021 | nothing | 15.9 | 0 | 519,849 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ida2021 | hybrid | 11.8 | 180,943 | 519,849 | 9% | 0% | 4.0 | 54% | 402 | 16 |
| ida2021 | wind_timing | 13.7 | 82,127 | 519,849 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ian2022 | isotonic | 1.3 | 88,572 | 1,431,914 | 0% | n/a | 9.0 | 62% | 2,428 | 1 |
| ian2022 | wind_only | 1.6 | 217,953 | 1,431,914 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| ian2022 | nothing | 1.0 | 0 | 1,431,914 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| ian2022 | hybrid | 1.6 | 1,811,172 | 1,431,914 | 71% | 47% | 3.0 | 62% | 2,428 | 1 |
| ian2022 | wind_timing | 1.5 | 1,251,690 | 1,431,914 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| idalia2023 | isotonic | 1.5 | 122,108 | 289,340 | 0% | n/a | 5.0 | 73% | 2,694 | 4 |
| idalia2023 | wind_only | 1.6 | 46,067 | 289,340 | 0% | n/a | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | nothing | 1.1 | 0 | 289,340 | 0% | n/a | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | hybrid | 2.1 | 391,137 | 289,340 | 5% | 0% | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | wind_timing | 2.2 | 1,202,964 | 289,340 | 10% | 33% | 2.0 | 73% | 2,694 | 4 |
| beryl2024 | isotonic | 5.8 | 192,471 | 2,167,213 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | wind_only | 6.1 | 186,048 | 2,167,213 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | nothing | 5.6 | 0 | 2,167,213 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | hybrid | 5.5 | 2,039,294 | 2,167,213 | 29% | 20% | 4.0 | 39% | 282 | 9 |
| beryl2024 | wind_timing | 5.2 | 1,971,221 | 2,167,213 | 29% | 20% | 4.0 | 39% | 282 | 9 |

## ±90 minutes

| Storm | Method | County error (pp) | Peak out, est. | Peak out, official | Caught ≥50% | False alarms ≥50% | Restore-day error (days) | Measurable | Rows scored | Over-counts dropped |
|---|---|---|---|---|---|---|---|---|---|---|
| florence2018 | isotonic | 0.9 | 59,998 | 136,664 | n/a | n/a | 4.0 | 57% | 1,329 | 0 |
| florence2018 | wind_only | 1.3 | 76,788 | 136,664 | n/a | n/a | 3.0 | 57% | 1,329 | 0 |
| florence2018 | nothing | 0.7 | 0 | 136,664 | n/a | n/a | 3.0 | 57% | 1,329 | 0 |
| florence2018 | hybrid | 1.6 | 463,561 | 136,664 | n/a | 100% | 3.0 | 57% | 1,329 | 0 |
| florence2018 | wind_timing | 1.6 | 259,099 | 136,664 | n/a | n/a | 3.0 | 57% | 1,329 | 0 |
| michael2018 | isotonic | 2.4 | 29,954 | 318,956 | 0% | n/a | 4.0 | 56% | 2,217 | 5 |
| michael2018 | wind_only | 2.6 | 37,474 | 318,956 | 0% | n/a | 1.0 | 56% | 2,217 | 5 |
| michael2018 | nothing | 2.3 | 0 | 318,956 | 0% | n/a | 1.0 | 56% | 2,217 | 5 |
| michael2018 | hybrid | 2.9 | 557,573 | 318,956 | 29% | 63% | 1.0 | 56% | 2,217 | 5 |
| michael2018 | wind_timing | 2.8 | 410,662 | 318,956 | 13% | 58% | 1.0 | 56% | 2,217 | 5 |
| laura2020 | isotonic | 4.9 | 17,061 | 210,616 | 0% | n/a | 6.0 | 52% | 937 | 9 |
| laura2020 | wind_only | 4.8 | 18,475 | 210,616 | 0% | n/a | 2.0 | 52% | 937 | 9 |
| laura2020 | nothing | 4.9 | 0 | 210,616 | 0% | n/a | 2.0 | 52% | 937 | 9 |
| laura2020 | hybrid | 4.1 | 180,215 | 210,616 | 18% | 12% | 2.0 | 52% | 937 | 9 |
| laura2020 | wind_timing | 3.6 | 168,024 | 210,616 | 8% | 25% | 2.0 | 52% | 937 | 9 |
| isaias2020 | isotonic | 1.5 | 135,545 | 1,367,978 | 0% | n/a | 5.0 | 44% | 1,698 | 1 |
| isaias2020 | wind_only | 2.0 | 245,594 | 1,367,978 | 0% | n/a | 2.0 | 44% | 1,698 | 1 |
| isaias2020 | nothing | 1.1 | 0 | 1,367,978 | 0% | n/a | 2.0 | 44% | 1,698 | 1 |
| isaias2020 | hybrid | 4.2 | 1,735,317 | 1,367,978 | 0% | n/a | 3.0 | 44% | 1,698 | 1 |
| isaias2020 | wind_timing | 3.4 | 2,436,836 | 1,367,978 | 0% | 100% | 3.0 | 44% | 1,698 | 1 |
| ida2021 | isotonic | 15.7 | 17,990 | 520,386 | 0% | n/a | 7.5 | 54% | 402 | 16 |
| ida2021 | wind_only | 15.1 | 32,670 | 520,386 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ida2021 | nothing | 15.9 | 0 | 520,386 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ida2021 | hybrid | 11.8 | 180,943 | 520,386 | 9% | 0% | 4.0 | 54% | 402 | 16 |
| ida2021 | wind_timing | 13.7 | 82,127 | 520,386 | 0% | n/a | 6.0 | 54% | 402 | 16 |
| ian2022 | isotonic | 1.3 | 88,572 | 1,431,318 | 0% | n/a | 8.0 | 62% | 2,428 | 1 |
| ian2022 | wind_only | 1.6 | 217,953 | 1,431,318 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| ian2022 | nothing | 1.0 | 0 | 1,431,318 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| ian2022 | hybrid | 1.6 | 1,811,172 | 1,431,318 | 71% | 47% | 3.0 | 62% | 2,428 | 1 |
| ian2022 | wind_timing | 1.5 | 1,251,690 | 1,431,318 | 0% | n/a | 3.0 | 62% | 2,428 | 1 |
| idalia2023 | isotonic | 1.5 | 122,108 | 289,493 | 0% | n/a | 5.0 | 73% | 2,694 | 4 |
| idalia2023 | wind_only | 1.6 | 46,067 | 289,493 | 0% | n/a | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | nothing | 1.1 | 0 | 289,493 | 0% | n/a | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | hybrid | 2.1 | 391,137 | 289,493 | 5% | 0% | 2.0 | 73% | 2,694 | 4 |
| idalia2023 | wind_timing | 2.2 | 1,202,964 | 289,493 | 10% | 33% | 2.0 | 73% | 2,694 | 4 |
| beryl2024 | isotonic | 5.8 | 192,471 | 2,167,402 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | wind_only | 6.1 | 186,048 | 2,167,402 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | nothing | 5.6 | 0 | 2,167,402 | 0% | n/a | 4.0 | 39% | 282 | 9 |
| beryl2024 | hybrid | 5.5 | 2,039,294 | 2,167,402 | 29% | 20% | 4.0 | 39% | 282 | 9 |
| beryl2024 | wind_timing | 5.2 | 1,971,221 | 2,167,402 | 29% | 20% | 4.0 | 39% | 282 | 9 |

## Diagnostics, all main storms pooled (±60)

Defined before the lockbox opened. County error rewards guessing zero because most scored nights have almost no outage; these columns show what it hides.

| Method | Rows | County error (pp) | Error where official ≥10% (pp) | Bias (pp) | AUC for ≥50% out | Night-to-night agreement (Spearman of changes) |
|---|---|---|---|---|---|---|
| isotonic | 11,983 | 2.42 | 38.8 | -1.76 | 0.747 | 0.065 |
| wind_only | 11,983 | 2.63 | 36.5 | -1.23 | 0.820 | n/a |
| nothing | 11,983 | 2.17 | 39.8 | -2.17 | 0.500 | n/a |
| hybrid | 11,983 | 2.95 | 24.1 | +0.69 | 0.955 | 0.189 |
| wind_timing | 11,983 | 2.84 | 25.7 | +0.37 | 0.934 | 0.215 |

## What the satellite adds: hybrid minus wind + timing (±60)

The two models share every input except the night-light reading. A negative error difference and a positive AUC difference mean the satellite helped. With eight storms the increment is small and not settled; the lockbox storms are its confirmatory test (decision log, "Model choice").

| Storm | Rows ≥10% out | Hybrid error ≥10% (pp) | Wind+timing error ≥10% (pp) | Difference | Hybrid AUC ≥50% | Wind+timing AUC ≥50% | Difference |
|---|---|---|---|---|---|---|---|
| florence2018 | 26 | 15.7 | 13.9 | +1.8 | n/a | n/a | n/a |
| michael2018 | 124 | 19.9 | 21.5 | -1.5 | 0.981 | 0.961 | +0.020 |
| laura2020 | 105 | 24.3 | 26.1 | -1.9 | 0.956 | 0.949 | +0.007 |
| isaias2020 | 58 | 16.1 | 16.6 | -0.5 | 0.729 | 0.708 | +0.021 |
| ida2021 | 129 | 35.0 | 41.1 | -6.1 | 0.968 | 0.936 | +0.032 |
| ian2022 | 57 | 13.6 | 15.7 | -2.2 | 0.995 | 0.991 | +0.004 |
| idalia2023 | 71 | 25.4 | 21.4 | +4.0 | 0.972 | 0.981 | -0.009 |
| beryl2024 | 29 | 33.5 | 33.1 | +0.4 | 0.896 | 0.913 | -0.017 |
| all storms pooled | 599 | 24.1 | 25.7 | -1.6 | 0.955 | 0.934 | +0.021 |
| pooled without Ida | 470 | 21.1 | 21.5 | -0.4 | 0.957 | 0.952 | +0.006 |

## Noise on calm nights

sd of % darker on baseline nights the satellite could see, where it should sit near zero: raw, after the angle and moon correction fit on the same storms (in-sample), and after a correction fit on the other main storms only (leave-one-storm-out).

| Storm | Calm county-nights | Raw sd | Corrected sd, in-sample | Corrected sd, leave-one-storm-out |
|---|---|---|---|---|
| All main storms | 61,942 | 0.431 | 0.342 | 0.344 |
| florence2018 | 7,219 | 0.344 | 0.232 | 0.232 |
| michael2018 | 8,205 | 0.329 | 0.228 | 0.228 |
| laura2020 | 8,903 | 0.666 | 0.579 | 0.581 |
| isaias2020 | 9,093 | 0.295 | 0.230 | 0.234 |
| ida2021 | 4,030 | 0.429 | 0.285 | 0.287 |
| ian2022 | 9,925 | 0.290 | 0.200 | 0.201 |
| idalia2023 | 7,504 | 0.304 | 0.202 | 0.205 |
| beryl2024 | 7,063 | 0.595 | 0.491 | 0.493 |

Correction fit on all main storms present: % darker = -0.0400 + -0.5010 × (sec(zenith) − 1) + 0.0055 × lunar irradiance, from 61,942 calm county-nights. The intercept is kept; only the two slopes are removed.

## Over-counts

County-nights (all statuses) whose official % out the over-count rule clipped to 1.0 or dropped, per truth window. The `Over-counts dropped` column above counts only rows that would otherwise be scored.

| Storm | With a value ±60 | Clipped ±60 | Dropped ±60 | Clipped ±30 | Dropped ±30 | Clipped ±90 | Dropped ±90 |
|---|---|---|---|---|---|---|---|
| florence2018 | 23,938 | 0 | 3 | 0 | 3 | 0 | 3 |
| michael2018 | 23,864 | 3 | 28 | 3 | 28 | 3 | 28 |
| laura2020 | 26,089 | 2 | 38 | 2 | 38 | 2 | 38 |
| isaias2020 | 29,179 | 0 | 3 | 0 | 3 | 0 | 3 |
| ida2021 | 11,711 | 1 | 36 | 1 | 36 | 1 | 36 |
| ian2022 | 27,775 | 0 | 2 | 0 | 2 | 0 | 2 |
| idalia2023 | 20,460 | 0 | 7 | 0 | 7 | 0 | 7 |
| beryl2024 | 17,490 | 1 | 15 | 1 | 15 | 1 | 15 |

## The curve

The isotonic curve fit on all main storms present (88,855 county-nights), for reading only: every score above comes from leave-one-storm-out fits.

| Corrected % darker | Estimated % out |
|---|---|
| 0% | 0% |
| 10% | 0% |
| 20% | 1% |
| 30% | 1% |
| 40% | 2% |
| 50% | 2% |
| 60% | 3% |
| 70% | 4% |
| 80% | 4% |
| 90% | 5% |

## Plain-language reading

- On the headline ±60-minute truth, the night-light curve's county error was lower than the wind-only guess in 6 of 8 storms, and lower than "nothing happened" in 1 of 8.
- Averaged over storms, county error was 4.3 pp for the curve, 4.4 pp for wind-only and 4.1 pp for nothing happened.
- On its peak night, the curve's total of customers out over the scored counties was a median 9% of the official peak total.
- Of county-nights officially at least half out, the curve also put 0% at least half out (mean over storms), and the curve made no at-least-half calls, so it raised no false alarms.
- Restore days were off by a median 5.0 days (the median over storms of each storm's median county error).
- The satellite could see 55% of hit-county nights in the event windows (mean over storms). Clouds and dark counties hide the rest, and those nights are left out, never counted as zero.
- These are leave-one-storm-out numbers on the main storms only, a draft for review rather than the lockbox test: the pass bar is committed before Helene and Milton are scored (Task 9).

## Lockbox: Helene and Milton, scored once

**Pass-bar verdict (pre-registered isotonic curve): FAIL.** The bar was committed before these storms were opened (decision log, "Pass bar, written before the lockbox opens"): beat wind-only on county error, night-to-night agreement of at least 0.3, and a median restore-day error of at most 2 days, at ±60.

**helene2024: the pre-registered curve**

| Window | Rows | Error: curve (pp) | Error: wind-only (pp) | Beats wind-only | Change agreement | ≥ 0.3 | Restore-day error (days) | ≤ 2 | Passes |
|---|---|---|---|---|---|---|---|---|---|
| ±60 | 3,715 | 6.77 | 7.00 | yes | 0.094 | no | 4.0 | no | **no** |
| ±30 | 3,716 | 6.78 | 7.01 | yes | 0.093 | no | 4.0 | no | **no** |
| ±90 | 3,715 | 6.77 | 7.00 | yes | 0.096 | no | 4.0 | no | **no** |

**milton2024: the pre-registered curve**

| Window | Rows | Error: curve (pp) | Error: wind-only (pp) | Beats wind-only | Change agreement | ≥ 0.3 | Restore-day error (days) | ≤ 2 | Passes |
|---|---|---|---|---|---|---|---|---|---|
| ±60 | 1,243 | 1.27 | 1.75 | yes | 0.094 | no | 3.0 | no | **no** |
| ±30 | 1,243 | 1.27 | 1.75 | yes | 0.096 | no | 3.0 | no | **no** |
| ±90 | 1,243 | 1.27 | 1.75 | yes | 0.089 | no | 3.0 | no | **no** |

### S1a Integrity of the recorded opening

The record is `docs/lockbox_result.json` (sha256 `db6cb77a81c2a784…`), written by one run of `blackout lockbox` at 2026-11-09 07:55:07 UTC on commit `7fd2732`. Its inputs are in `docs/lockbox_record.json`: 11 tables hashed, none rebuilt after the run; Python 3.13.12, numpy 2.5.4, pandas 2.3.3, scikit-learn 1.9.1, scipy 1.18.1, pyarrow 26.0.1. Each check is recomputed from those files and the git history; a failed check is disclosed in the decision log (D-20) and never fixed by a rerun (D-12).

| Check | Result | Detail |
|---|---|---|
| LB-45 the record is frozen | pass | `docs/lockbox_result.json` sha256 db6cb77a81c2a784… |
| LB-44 the inputs are recorded and none is newer than the run | pass | 11 tables hashed (2 lockbox, 8 main, 1 stress); none rebuilt after the run |
| LB-41a the recorded commit descends from the pass bar and the model choice | pass | git_head `7fd2732`; pass bar `2f534f9`, model choice `2187e37` |
| LB-41b the hashed model code is that commit's | pass | model.py 25605eb093a1e0f1, hybrid.py 3ab8524766cacbc3, ranges.py 5e2e75fcac3eadc1, evaluate.py 3c0f953ee364a16e, final.py f4b542333476c09b |
| LB-41c eight main training tables, each the storm's own, Beryl's from NOAA-20 | pass | 8 tables; beryl2024: county_nights_beryl2024.parquet VJ146A2 |
| LB-41d the working tree was clean at the run, or D-20 discloses it | pass | working_tree_dirty: True; disclosed in D-20 |
| LB-41e every predictions file was written within 30 minutes of the run | pass | 11 files, the farthest 0.05 min from run_at_utc |
| LB-36 the verdict comes from the curve; the hybrid is scored apart | pass | helene2024: curve 6.77 pp, hybrid 7.16 pp; milton2024: curve 1.27 pp, hybrid 2.2 pp |
| LB-37 the satellite test follows its edge rules | pass | recorded 'yes', recomputed 'yes' |
| LB-40 the verdict follows the committed rule, drop rule included | pass | recorded 'fail', under the committed rule 'fail'; clear-night shares helene2024 0.957, milton2024 0.986 |
| LB-43 locked truth uses the repaired customers | pass | helene2024: 0 of 787 counties differ; milton2024: 0 of 272 counties differ |

### The hybrid (secondary, post hoc): for information

The same three conditions, run on the hybrid. It was designed after the main storms were scored, so this is not its pre-registered test.

**helene2024: the hybrid**

| Window | Rows | Error: curve (pp) | Error: wind-only (pp) | Beats wind-only | Change agreement | ≥ 0.3 | Restore-day error (days) | ≤ 2 | Passes |
|---|---|---|---|---|---|---|---|---|---|
| ±60 | 3,715 | 7.16 | 7.00 | no | 0.181 | no | 5.0 | no | **no** |
| ±30 | 3,716 | 7.18 | 7.01 | no | 0.179 | no | 5.0 | no | **no** |
| ±90 | 3,715 | 7.16 | 7.00 | no | 0.181 | no | 5.0 | no | **no** |

**milton2024: the hybrid**

| Window | Rows | Error: curve (pp) | Error: wind-only (pp) | Beats wind-only | Change agreement | ≥ 0.3 | Restore-day error (days) | ≤ 2 | Passes |
|---|---|---|---|---|---|---|---|---|---|
| ±60 | 1,243 | 2.20 | 1.75 | no | 0.188 | no | 5.0 | no | **no** |
| ±30 | 1,243 | 2.20 | 1.75 | no | 0.184 | no | 4.0 | no | **no** |
| ±90 | 1,243 | 2.20 | 1.75 | no | 0.189 | no | 5.0 | no | **no** |

**uri2021: the hybrid**

| Window | Rows | Error: curve (pp) | Error: wind-only (pp) | Beats wind-only | Change agreement | ≥ 0.3 | Restore-day error (days) | ≤ 2 | Passes |
|---|---|---|---|---|---|---|---|---|---|
| ±60 | 2,505 | 2.11 | 2.34 | yes | 0.043 | no | 2.0 | yes | **no** |
| ±30 | 2,505 | 2.09 | 2.32 | yes | 0.043 | no | 2.0 | yes | **no** |
| ±90 | 2,505 | 2.10 | 2.33 | yes | 0.044 | no | 2.0 | yes | **no** |

### The hybrid's pre-registered test: does the satellite add to wind + timing?

**Verdict: YES.** On each locked storm the hybrid must beat `wind_timing` on error where the official count is at least 10% out and on AUC for at least half out (decision log, "Model choice" and its correction note: a storm needs 10 county-nights at least 10% out to count, and 10 at least half out for the AUC condition). The differences are the evidence; the label is a sign test on two storms.

| Storm | Rows ≥10% out | Error ≥10%: hybrid vs wind+timing (pp) | Lower | AUC ≥50%: hybrid vs wind+timing | Higher | Passes |
|---|---|---|---|---|---|---|
| helene2024 | 566 | 33.0 vs 35.1 (-2.1) | yes | 0.784 vs 0.784 (0.001) | yes | **yes** |
| milton2024 | 41 | 12.9 vs 15.0 (-2.0) | yes | n/a (4 rows >= 50% out) | rests on error | **yes** |

### Uri, the stress test (snow)

Scored separately. The EAGLE-I dropout constants were tuned partly on Uri, and snow makes counties read brighter than their baseline (docs/failures.md, section 4), so this is neither a clean test nor a fair one for the method.

**uri2021: the pre-registered curve**

| Window | Rows | Error: curve (pp) | Error: wind-only (pp) | Beats wind-only | Change agreement | ≥ 0.3 | Restore-day error (days) | ≤ 2 | Passes |
|---|---|---|---|---|---|---|---|---|---|
| ±60 | 2,505 | 2.26 | 2.34 | yes | -0.026 | no | 11.0 | no | **no** |
| ±30 | 2,505 | 2.24 | 2.32 | yes | -0.024 | no | 11.0 | no | **no** |
| ±90 | 2,505 | 2.26 | 2.33 | yes | -0.026 | no | 11.0 | no | **no** |

### Trigger view: "county above 50% out at 72 hours"

Basis risk for a parametric trigger on the locked storms: where an estimate-based trigger would have paid correctly, paid wrongly, or missed, against EAGLE-I at 72 hours after landfall.

| Storm | Model | Paid correctly | Paid wrongly | Missed | Correctly unpaid | Unknown (can't see) |
|---|---|---|---|---|---|---|
| helene2024 | hybrid | 5 | 12 | 47 | 195 | 10 |
| helene2024 | isotonic | 0 | 0 | 52 | 207 | 10 |
| milton2024 | hybrid | 0 | 1 | 1 | 71 | 1 |
| milton2024 | isotonic | 0 | 0 | 1 | 72 | 1 |

### Range calibration (leave-one-storm-out, main storms)

Share of held-out official values inside the 80% ranges; the target is about 80%.

| Model | All scored rows | Hit counties after landfall |
|---|---|---|
| hybrid | 0.807 (88,855 rows) | 0.705 (11,983 rows) |
| isotonic | 0.850 (88,855 rows) | 0.776 (11,983 rows) |

### NOAA-20 cross-check

The same counties and nights seen by both satellites, uncorrected % darker.

| Storm | County-nights both clear | Spearman | Storm nights | Spearman, storm nights | Median |difference| (pp) |
|---|---|---|---|---|---|
| ida2021 | 5,739 | 0.370 | 2,070 | 0.119 | 29.3 |
| ian2022 | 972 | 0.081 | 511 | 0.289 | 17.7 |
| beryl2024 | 7,588 | 0.625 | 1,284 | 0.709 | 22.0 |

Lee County on NOAA-20: darkest night 2022-09-29 (0.752 darker), official peak night 2022-09-29; half-recovery 2022-10-02 against EAGLE-I's 2022-10-04 (-2 nights).
