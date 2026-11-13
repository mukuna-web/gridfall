# Gridfall: Design

*Written on 2026-11-05, before anything was built, as planning notes addressed to the project's author ("you"); "my" refers to Claude, which did the planning. The [decision log](decision-log.md) records the calls made since.*

**One line:** After a hurricane, count how many customers lost power in each county from NASA's night-light photos. Then grade that count against the government's official outage numbers.

---

## 1. Why this exists

- **A personal project,** built out of curiosity about what night-light images can say about power outages.
- **What it involves:** three things.
  - Joining messy real-world data: satellite images, outage records and census counts.
  - Checking its own answers honestly.
  - Turning the result into a small web app.
- **What is different:** satellite outage maps are common, but almost none are graded against official counts. This one comes with a scorecard, including where it fails.
- **Why now:** Suomi NPP, the satellite behind most past work, stopped sending new data on Nov 1–2, 2026. This project is built on its archive and checks whether its replacement, NOAA-20, gives the same answer.

## 2. A worked example

As an illustration, the app joins the county estimates to a synthetic list of insured properties: a made-up policy portfolio and made-up claims. It is an example of what the numbers can answer, not the purpose of the project.

The example asks three questions:

1. **How many of the synthetic policies are without power, and for how long?** Duration matters because many business-interruption and utility-service covers only start paying after a waiting period, often 24–72 hours.
2. **Does this claim fit what happened in that county?**
   - Example: a claim says 10 days without power, but the county was 90% restored by day 4. The tool flags it for review.
   - It never calls a claim fraud. County numbers can't speak for one address.
3. **Stretch: would a satellite trigger have paid the right counties?** Imagine a policy that pays automatically when a county is dark for more than 72 hours. Insurers call the gap between a trigger and the real losses "basis risk".

## 3. Goals, non-goals, anti-goals

**Goals**

1. For every clear night after a storm, estimate customers out per county (and roughly homes out), each with a range.
2. Publish a scorecard on storms the model never saw, compared against a simple wind-only guess.
3. Build a small web app that shows the estimates and, as a worked example, answers questions 1 and 2 of section 2 in about a minute, using a made-up policy portfolio.
4. Leave a repo a stranger can rerun from a fresh clone.

**Non-goals for v1**

- A real-time service, alerts, or a 24/7 pipeline.
- Outage claims at street or address level. Numbers appear only where they can be checked, which is the county.
- Underwriting, pricing, or a claims system.
- Countries outside the US. Places with no outage reporting have no official count to grade against. At most, show one ungraded example, clearly labeled.
- Deep learning for its own sake.

**Anti-goals: these count as failure even if the code works**

- A pretty map with no scorecard.
- Tuning on the test storms, or hiding misses.
- Claiming accuracy finer than EAGLE-I can check.
- Real policyholder data. The policies and claims are synthetic, and every input is public.
- Code you can't explain line by line.

## 4. Constraints

- **Public data only.** A personal project; the policies and claims are synthetic.
- **You write the code.** Claude plans and reviews.
- **Free data and tools.** NASA data needs a free Earthdata login and token.
- **Laptop scale.**
  - Raw satellite files across all storms can reach tens of GB (my estimate).
  - Process one storm at a time, keep only the county numbers, and delete the raw tiles.
  - Keep the repo on a local disk, not in a cloud-synced folder.
- **Satellite coverage:**
  - Suomi NPP (`VNP46A2`) covers 2012 to Oct 2026.
  - NOAA-20 (`VJ146A2`) covers roughly 2018 onward.
  - `blackmarblepy` downloads only the Suomi NPP product, so get NOAA-20 files straight from NASA's LAADS archive.
- **Time:** about 8 weeks at roughly 10 hours a week. That's my guess; see Open questions.

## 5. Data

| What | Source | Used for |
|---|---|---|
| Night lights, daily | NASA Black Marble [`VNP46A2`](https://blackmarble.gsfc.nasa.gov/VNP46A2.html) (Suomi NPP, Collection 2), via [`blackmarblepy`](https://github.com/worldbank/blackmarblepy) | Main signal for the 2018–2024 storms |
| Night lights, daily | [`VJ146A2`](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VJ146A2) (NOAA-20) | Cross-check on 3 storms; future storms |
| Official outages | [EAGLE-I](https://figshare.com/articles/dataset/The_Environment_for_Analysis_of_Geo-Located_Energy_Information_s_Recorded_Electricity_Outages_2014-2022/24237376) county outages, every 15 min, 2014–2025 ([data paper](https://www.nature.com/articles/s41597-024-03095-5.pdf)) | The answer key |
| Customers per county | EAGLE-I's modeled customers-per-county file (same download) | Turning percentages into counts |
| County shapes, housing | [Census TIGER/Line](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) county shapes; ACS housing units | Adding up pixels per county; converting customers to homes; placing fake policies |
| Storm winds | [NOAA HURDAT2](https://www.nhc.noaa.gov/data/#hurdat) best track with wind radii | The simple guess to beat; deciding which counties were "hit" |
| Policies and claims | Synthetic, from a script with a fixed seed | The portfolio example |

**Starting storm list (my call):**

- **Main set:** Florence and Michael (2018), Laura and Isaias (2020), Ida (2021), Ian (2022), Idalia (2023), Beryl (2024).
- **Lockbox:** Helene and Milton (2024). They stay untouched until the final test.
- **Stress test:** Winter Storm Uri (2021), scored separately because snow confuses brightness.
- **Drop rule:** drop any storm where most hit counties get no clear night within a week.

**"Hit" counties:** those inside the storm's tropical-storm-force wind zone. Similar counties outside it serve as a no-storm comparison.

## 6. How it works

1. **Measure.** For each county on each night:
   - Keep only clear, good-quality pixels and add up their light.
   - Compare against the same pixels on normal nights, using the median of clear nights in the month before landfall.
   - The result is "% darker", plus "how much of the county we could see".
2. **Translate.** Learn from past storms how "% darker" turns into "% of customers out".
   - The answer key is EAGLE-I's count at the satellite's ~1:30 am pass.
   - Start with one simple curve. Add inputs (how urban, how much was visible, viewing angle) only if they help on held-out storms.
   - Customers out = % out × the county's customer count.
   - Homes out ≈ % out × the county's housing units.
3. **Range.** Give every number a range learned from past misses, for example the middle 80% of how wrong it was on similar counties.
4. **Duration.** "Days until 90% restored" comes back as an interval when clouds hide some nights, for example "between day 4 and day 6".

**Rules to write tests for:**

- **No gap-filled layer after a storm.** `Gap_Filled_DNB_BRDF-Corrected_NTL` fills cloudy spots with older, pre-storm lights, which hides the blackout. Use `DNB_BRDF-Corrected_NTL` with the cloud, snow and quality flags instead.
- **Visibility minimum.** Only estimate when enough of the county's normal light is visible. Otherwise show "can't see".
- **Dark rural counties** are marked "not measurable", never "zero out".
- **Back-to-back storms** (Helene, then Milton): take the baseline from before the first one.
- **Timezones.** Check EAGLE-I's timezone before lining its counts up with the 1:30 am pass.

## 7. How we'll know it works

- **Hold-outs:** train on all storms but one, test on the one left out, and repeat for each storm. Helene and Milton stay locked until the end.
- **Pass bar:** write it down before you open the lockbox. My suggested starting point: beat the wind-only guess on county error for both locked storms.
- **Scorecard, per storm:**
  - average county error in % out;
  - total customers out, estimated vs. official;
  - share of counties that were officially more than 50% out that the model caught, plus false alarms;
  - restoration-day error;
  - share of hit counties it could measure at all.
- **Simple guesses to beat:**
  - "wind only": the average % out for counties in each wind band (34, 50 or 64 kt winds), learned from the training storms;
  - "nothing happened".
- **NOAA-20 check:** rerun 3 storms on `VJ146A2` and report how closely the two satellites agree.
- **Failure page:** clouds, rural areas, snow and generators, shown as real cases with pictures.

## 8. The app

A static web app (TypeScript, React and MapLibre) that reads files the pipeline writes. No server.

1. **Storm map.** Pick a storm and slide through the nights.
   - Counties are shaded by estimated % out and hatched where the satellite can't see.
   - A toggle shows the official numbers beside the estimates.
2. **County card.** Shows the estimate and its range, the official count, days dark (as an interval), and visibility notes.
3. **Portfolio panel.** About 100k fake homeowner and small-business policies, placed by housing counts.
   - Headline: "expected policies without power at hour 72: N (range)".
   - A waiting-period setting (24, 48 or 72 h) and a county table.
4. **Claim check.** Pick a fake claim to see its claimed outage days against the county's restoration curve.
   - The tool says "fits" or "longer than X% of the county: review".
   - A "Flag for review" button saves the flag in the browser.

**Demo storm (my call):** Milton. The model never saw Milton, so the demo doubles as a test. If Milton turns out too cloudy, use Helene.

## 9. Data model

Name the tables as things:

- Storm
- County
- Night observation
- Official outage
- Estimate
- Restoration summary
- Policy (fake)
- Claim (fake)

The one action is "flag claim for review".

## 10. Phases

| Phase | Weeks | Done when |
|---|---|---|
| 0. Ian in Lee County, by hand | 1 | One chart of brightness vs. EAGLE-I % out, plus notes on the gap-filled trap and on whether the quality flags throw away real outages |
| 1. Pipeline for all storms | 2–3 | One command builds the county × night table, and tests pass on a small bundled sample |
| 2. Estimator and scorecard | 4–5 | Scorecard and failure page done, pass bar written before the lockbox opens, NOAA-20 check done |
| 3. The app | 6–7 | The Milton walkthrough takes about a minute of clicks |
| 4. Ship | 8 | Public repo with a fresh-clone README, CI, write-up, a decision log in your own words, and a 3-minute video. Pushing and hosting happen only with your OK |

## 11. Who decided what

**You decided:**

- the idea;
- Black Marble and EAGLE-I as the data;
- a synthetic insurance portfolio as the app's worked example;
- writing the code yourself.

**My calls (push back on any):**

- customers as the main number, with homes as a conversion;
- Ian in Lee County first;
- the storm list and the lockbox;
- a simple curve first;
- the stack;
- the size of the fake portfolio and the 72 h default;
- Milton as the demo;
- wind bands for the wind-only guess;
- a public repo;
- roughly 8 weeks.

**Left to you as the builder:**

- the exact model and how ranges are computed;
- the visibility and coverage cutoffs;
- libraries for adding up pixels per county;
- file formats;
- app styling;
- whether to send NOAA-20 support upstream to `blackmarblepy`.

## 12. Prior art to cite

- [NASA SPoRT](https://ntrs.nasa.gov/citations/20170011710) checked a satellite outage product against EAGLE-I for Hurricane Matthew.
- [Xu et al. 2023](https://doaj.org/article/0f63bb3628de43969fae48bb8937c2c6), *International Journal of Digital Earth*, mapped Winter Storm Uri outages from Black Marble.
- [GeoOutageKG](https://arxiv.org/pdf/2507.22878) (2025) pairs Black Marble with EAGLE-I for Ian and Milton.
- [NASA Earth Observatory](https://earthobservatory.nasa.gov/images/150431/power-outages-after-hurricane-ian) published outage images after Hurricane Ian.

## 13. Open questions

- Open when this was written: when it should be ready, and how many hours a week it gets (the 8-week pace in section 4 is a guess). Overtaken on 2026-11-08, when the author asked Claude to finish the whole plan as fast as possible (decision log, "Who writes Weeks 2–8").
