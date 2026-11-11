# Blackout from Space: write-up

*Results from `docs/scorecard.md`, 2026-11-08. The leave-one-storm-out numbers can be rerun from a fresh clone (README); the lockbox numbers are a one-time record, frozen in `docs/lockbox_result.json` and not recomputed.*

## The problem

After a hurricane, how many electricity customers in each county are without power, and for how long? Duration matters as well as the outage itself: as one example, many business-interruption and utility-service insurance covers start paying only after a 24–72 hour waiting period.

Utilities publish outage maps, but each covers only its own territory and none keeps a history. The US Department of Energy's EAGLE-I system scrapes those maps every 15 minutes, which makes it the best official record. It is still a scrape: feeds drop out, and some counties read above their customer count. NASA's Black Marble night-light product sees every county from orbit about once a night, when the sky is clear. This project asks whether the satellite alone can estimate customers out per county well enough to be useful, and grades that answer honestly against EAGLE-I on storms the model never saw.

## The data

- **Night lights:** NASA Black Marble VNP46A2 (Suomi NPP, Collection 2), daily, about 500 m pixels in 10° tiles. Only the BRDF-corrected radiance is used. The gap-filled layer is never read, because on cloudy nights it pastes in older, pre-storm light and hides the blackout. VNP46A1 supplies each pixel's view time (`UTC_Time`) and sensor zenith.
- **Answer key:** EAGLE-I county outage counts, 2018–2024 (CC BY 4.0), with its modeled customers-per-county file.
- **Storm winds:** NOAA's HURDAT2 best tracks with wind radii by quadrant, used for the wind-only guess and to decide which counties were hit.
- **Counties and homes:** Census cartographic boundaries and ACS housing units.
- **Storms:** eight main storms (Florence, Michael, Laura, Isaias, Ida, Ian, Idalia, Beryl), two locked storms (Helene and Milton, 2024) and one stress test (Winter Storm Uri, 2021).

## The method

1. **Measure.** For each county and night, add up the light of pixels that are clear tonight and also have a baseline, the per-pixel median of clear nights in the month ending three days before landfall. "% darker" is one minus tonight's light over the baseline light of those same pixels. A county is "can't see" when less than half its normal light is visible, and "not measurable" when it has almost no light to lose. Neither ever counts as zero.
2. **Line up the answer key.** A file dated D holds the pass at about 01:30 local solar time on D, labeled night D − 1. The official count is EAGLE-I's median over its 15-minute runs within ±60 minutes of the county's actual pass time, from VNP46A1. Runs where the scraper lost one utility's feed are found and dropped first, because a lost feed reads as power coming back. The rule finds the short V that a lost feed makes in the state's total (decision log, 2026-11-08).
3. **Correct for viewing angle and moonlight.** On normal nights before landfall, light reads brighter at steep viewing angles and darker on moonlit nights. A linear correction is fit on the training storms' baseline nights only.
4. **Translate.** One monotone curve (isotonic regression) maps corrected "% darker" to "% of customers out". It is learned on past storms only.
5. **Range and duration.** Ranges come from the middle 80% of held-out misses in bands of the prediction. Restoration days come back as intervals when clouds hide nights.

## Results

**The pre-registered test failed.** The pass bar, committed before Helene and Milton were opened, asked the night-light curve to beat a wind-only guess on county error, to agree with EAGLE-I on night-to-night changes (Spearman ≥ 0.3), and to get restoration day right to within two days. On both locked storms the curve beat wind-only (Helene 6.8 vs 7.0 percentage points, Milton 1.3 vs 1.8) and failed the other two conditions (agreement 0.09 on both; restore-day error 4 and 3 days).

**Why it failed.** The curve learned from every county-night, and most county-nights, even in a hurricane's wind zone, have almost no outage. Fit that way, corrected "% darker" separates calm counties from dark ones but does not size an outage: the curve never estimates more than about 10% out, and it put all 197 heavily hit county-nights of the eight main storms below 10%. The reason is noise. On calm nights a county's "% darker" swings with a standard deviation of about 0.2 after correcting for viewing angle and moonlight, and the viewing-angle effect alone is worth 50 points at a 60° look. A single night's reading cannot tell a 60% outage from a bad angle.

**A second model, after the fact.** With storm context added (wind band and days since landfall, plus each county's own calm-night noise), a gradient-boosted model finds the outages the curve misses: on held-out main storms its error on county-nights at least 10% out is 24 points against the curve's 39, better in 8 of 8 storms, and it ranks the half-out county-nights with an AUC of 0.96 against 0.75. But the same model with no satellite input gets about 90% of that gain. The satellite's own contribution is about two points of error on heavily hit county-nights, confirmed in the same direction on both locked storms (−2.1 and −2.0), with no improvement in ranking. Because this model was built after the main storms were scored, it is reported as secondary, and the app labels its estimates as a storm-context model with a night-light adjustment.

| Leave-one-storm-out, eight main storms, ±60 | Curve (pre-registered) | Hybrid | Wind + timing (no satellite) | Wind only | Nothing |
|---|---|---|---|---|---|
| County error, all scored nights (pp) | 2.42 | 2.95 | 2.84 | 2.63 | 2.17 |
| Error where official ≥ 10% out (pp) | 38.8 | 24.1 | 25.7 | 36.5 | 39.8 |
| AUC for "at least half out" | 0.75 | 0.96 | 0.93 | 0.82 | 0.50 |
| Night-to-night agreement (Spearman of changes) | 0.07 | 0.19 | 0.22 | n/a | n/a |

**The trigger example.** For a trigger that pays a county above 50% out at 72 hours, Helene is the honest answer: the hybrid would have paid 17 counties, 5 of them correctly, and missed 47 of the 52 that qualified; the curve would have paid none. Restoration days come back as intervals because about half the post-landfall nights are cloudy, and the 80% ranges covered 78% (curve) and 71% (hybrid) of official values on hit counties.

**Uri and NOAA-20.** Under snow, Texas counties read 83% brighter than their baseline, so Uri cannot be estimated with this method. NOAA-20 reproduces Lee County's Ian result (darkest night, two-night recovery lead), but county by county the two satellites agree weakly on calm nights (Spearman 0.08 to 0.63), which is the viewing-angle effect again.

## Where it fails

`docs/failures.md` has the cases: cloud cover hiding the first week (Beryl: 11% of hit-county nights measurable), rural counties with too little light to lose (Florence: 92 counties), the viewing-angle effect, snow, EAGLE-I's own feed dropouts and over-counts, the broken customer counts for North Carolina, and the two satellites' disagreement.

## Prior art

- NASA SPoRT checked a satellite outage product against EAGLE-I for Hurricane Matthew.
- Xu et al. (2023) mapped Winter Storm Uri outages from Black Marble.
- GeoOutageKG (2025) pairs Black Marble with EAGLE-I for Ian and Milton.
- What this project adds: a scorecard across eight storms with held-out testing, a locked test on two storms against a bar written down first, two baselines that must be beaten (wind only; wind and timing), and a worked example (a synthetic insurance portfolio and a claim check) built on the result, with its failures listed.

## What I would do next

1. Fix the viewing angle at the pixel level, not the county level, or restrict to passes within 40° of nadir. The 50-point angle effect is the largest error in the chain.
2. Use the two satellites together: with Suomi NPP and NOAA-20 both passing each night, a county gets two looks at different angles, which is a direct test of the angle correction.
3. Treat the first clear night after landfall as the measurement and everything else as recovery; most of the signal is there, and most of the noise is in the long tail of calm nights.
