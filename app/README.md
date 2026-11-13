# Gridfall: the app

A static report on one storm at a time. It shows county outage estimates from
NASA Black Marble night lights, the official EAGLE-I numbers beside them and, as
a worked example, a synthetic policy portfolio and a claim check. There is no
server, no API key and no basemap: the
map draws only county polygons and state lines from the exported GeoJSON.

## Commands

```bash
npm ci
npm test            # vitest with happy-dom (jsdom hung vitest's workers on the machine this was built on)
npm run typecheck   # tsc over the app and tests, the Vite/Vitest configs, and the e2e specs
npm run build       # type-checks, then writes a static site to dist/
npm run dev         # local preview; needs exported data, see below
npm run e2e         # browser tests (Playwright, chromium): assembles e2e data, builds, runs
npm run e2e:prepare # just the first two steps of e2e (data into .e2e/public, build into dist-e2e)
```

Browser tests need `npx playwright install chromium` once. They run against a
build of their own (`dist-e2e`) whose `data/` folder `scripts/prepare-e2e-data.mjs`
assembles from the synthetic contract fixture `tests/fixtures/contract/synth2099`
(when present) and the committed `public/data/ian2022_sample`, never from a
lockbox or full-storm export. Specs wait on the map's `data-map-state`
attribute (`loading`, `ready` or `error`), never on timeouts.

## Data

The app reads files that `uv run blackout export` writes to `public/data/`:

```
public/data/index.json                 storms to list (the first is the default)
public/data/<id>/meta.json             nights, waiting periods, notes
public/data/<id>/counties.geojson      county shapes + fips, name, state, housing_units, customers
public/data/<id>/states.geojson        state lines
public/data/<id>/nights.json           per county: night, status, est, lo, hi, official
public/data/<id>/restoration.json      per county: est_lo, est_hi, official_day
public/data/<id>/exposure.json         per county: home, business, [lo, hi] at 24/48/72 h
public/data/<id>/claims.json           synthetic claims
public/data/<id>/scorecard.json        isotonic vs wind-only vs nothing
```

`src/types.ts` mirrors this contract and `src/data/validate.ts` checks every
file, so a renamed key fails with the file and field path instead of rendering
as a blank or a zero. With no `index.json`, the app shows an empty state with
the export commands.

## Rules the code keeps

- **Can't see is never zero.** Only a night with status `ok` and a number is
  colored, summed or plotted. Can't-see and not-measurable counties are hatched
  on the map, shown as words on the card, and counted as *unknown* policies.
- **The claim check stays fair.** It reads the high end of the estimate range,
  says "fits" or "longer than X% of the county: review", and never calls a claim
  fraud. A county it can't see leaves the claim at "fits".
- **Flags are browser-local and per storm.** Claim ids repeat across exports
  (every storm has a `C0001`), so "Flag for review" saves to the `localStorage`
  key `bfs.flags.v2` as `{ "<storm id>": ["C0001", …] }`. Flags written by the
  first release's flat list (`bfs.flags.v1`) are carried over under `"*"` and
  show in every storm, as they did, until removed. If storage is blocked or
  full, flags last for the session and the page says so; garbage in storage
  reads as no flags and is replaced by the next save.
- **The map says what it is doing.** The `.storm-map` container carries
  `data-map-state="loading|ready|error"`, and the error boundary's fallback
  carries `error`, so browser tests wait on state, not time.
- **Dates stay on the UTC calendar.** Night labels are formatted from fixed
  tables, never through the local time zone (tests run in America/Los_Angeles
  to catch slips).

## Layout

```
src/types.ts            the export contract
src/data/               load.ts (fetch + readable errors), validate.ts (shape checks)
src/lib/                pure logic: exposure, claims, flags, nights, dates, format, color, geo
src/components/         StormMap (lazy, MapLibre), CountyCard, PortfolioPanel, ClaimCheck, ...
src/styles/             tokens.css (palette, type, space) and per-area stylesheets
src/__fixtures__/       SYNTHETIC test data only; see its README
```

```
e2e/                    Playwright specs (morning-after.spec.ts, sample-smoke.spec.ts) and helpers.ts
scripts/                prepare-e2e-data.mjs
src/test/               the recording maplibre-gl stub, a small style-expression evaluator, ΔE2000
```

`maplibre-gl` needs WebGL, so tests alias it to `src/test/maplibre-stub.ts`,
which records the sources, layers, images and feature states StormMap sets so
`StormMap.test.tsx` can evaluate the fill colour an unseen county gets. The
exposure test also reads `../tests/fixtures/exposure_toy.json`, the toy the
Python side checks, so both languages agree on the same numbers. It keeps an
inline copy of that toy (so it still runs without the file) and fails if the
copy and the file drift apart.

EAGLE-I outage data is licensed CC BY 4.0. Fonts (IBM Plex, SIL Open Font
License 1.1) are self-hosted through `@fontsource`. The app's own code is
MIT-licensed: see [../LICENSE](../LICENSE), and the root README's "Licence and
data sources" section for the full credits.
