/**
 * The Python–TypeScript contract, app side (test-plan B-09: CT-03, CT-04, CT-05).
 *
 * tests/fixtures/contract/synth2099 is written by the real Python exporter
 * (tests/fixtures/make_app_fixture.py) and pinned byte-for-byte by
 * tests/test_contract.py. Here the same files go through the real parsers,
 * the shared cases file is read by this side's validator, and the parser's
 * enums, patterns and required keys are compared with the schema itself.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { expectedPoliciesOut } from '../lib/exposure'
import type { HourKey, StormData, StormFileKey } from '../types'
import { CORE_METHODS, EXTRA_METHODS, METRIC_NAMES, STORM_FILES, WAITING_PERIODS } from '../types'
import {
  DataShapeError,
  FIPS,
  ISO_DATE,
  parseClaims,
  parseCounties,
  parseExposure,
  parseIndex,
  parseMeta,
  parseNights,
  parseRestoration,
  parseScorecard,
  parseStates,
  parseStormFiles,
  ROLES,
  SATELLITES,
  STATUSES,
  STORM_ID,
  WINDOWS,
} from './validate'

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const CONTRACT = join(REPO, 'tests', 'fixtures', 'contract')
const STORM = 'synth2099'
const FOLDER = join(CONTRACT, STORM)

interface ExpectedOut {
  readonly low: number
  readonly high: number
  readonly unknown_policies: number
}

interface SharedCase {
  readonly id: string
  readonly kind: string
  readonly valid: boolean
  readonly ts?: 'same' | 'lenient' | 'stricter'
  readonly document: unknown
}

type Parser = (raw: unknown, file: string) => unknown

const PARSERS: Readonly<Record<string, Parser>> = {
  index: parseIndex,
  meta: parseMeta,
  counties: parseCounties,
  states: parseStates,
  nights: parseNights,
  restoration: parseRestoration,
  exposure: parseExposure,
  claims: parseClaims,
  scorecard: parseScorecard,
}

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, 'utf8')) as unknown
}

/** Walks a parsed JSON document: at(schema, '$defs', 'role', 'enum'). */
function at(root: unknown, ...keys: string[]): unknown {
  return keys.reduce<unknown>((node, key) => (node as Record<string, unknown>)[key], root)
}

function sortedKeys(value: unknown): string[] {
  return Object.keys(value as object).sort()
}

const SCHEMA = readJson(join(REPO, 'schema', 'export.schema.json'))
const FILE_KEYS = Object.keys(STORM_FILES) as StormFileKey[]
const RAW = Object.fromEntries(FILE_KEYS.map((key) => [key, readJson(join(FOLDER, STORM_FILES[key]))])) as Record<
  StormFileKey,
  unknown
>
const DATA: StormData = parseStormFiles(STORM, RAW)

describe('the Python fixture export (CT-03)', () => {
  it('parses through every parser and comes out unchanged', () => {
    expect(DATA).toEqual(RAW)
  })

  it('is listed in index.json exactly as meta.json describes it', () => {
    const index = parseIndex(readJson(join(CONTRACT, 'index.json')), 'index.json')
    const { id, name, landfall, role, satellite } = DATA.meta

    expect(index.storms).toEqual([{ id, name, landfall, role, satellite }])
  })

  it('keys every per-county file by the counties and follows meta.nights', () => {
    const fips = DATA.counties.features.map((f) => f.properties.fips).sort()

    expect(sortedKeys(DATA.nights)).toEqual(fips)
    expect(sortedKeys(DATA.restoration)).toEqual(fips)
    expect(sortedKeys(DATA.exposure)).toEqual(fips)
    for (const records of Object.values(DATA.nights)) {
      expect(records.map((r) => r.night)).toEqual(DATA.meta.nights)
    }
    expect(DATA.meta.nights).toHaveLength(10)
  })

  it('covers every status and the nulls the contract allows', () => {
    const statuses = new Set(Object.values(DATA.nights).flatMap((records) => records.map((r) => r.status)))
    const blank = DATA.nights['99003']?.find((r) => r.night === '2099-09-14')
    const gap = DATA.nights['99011']?.find((r) => r.night === '2099-09-13')

    expect([...statuses].sort()).toEqual([...STATUSES].sort())
    expect(blank).toMatchObject({ status: 'ok', est: null, lo: null, hi: null })
    expect(gap?.official).toBeNull()
    expect(DATA.counties.features.find((f) => f.properties.fips === '99005')?.properties.customers).toBeNull()
    expect(DATA.counties.features.find((f) => f.properties.fips === '99011')?.geometry.type).toBe('MultiPolygon')
    expect(DATA.restoration['99011']).toEqual({ est_lo: 7, est_hi: null, official_day: null })
    expect(DATA.restoration['99005']).toEqual({ est_lo: null, est_hi: null, official_day: null })
    expect(DATA.exposure['99007']?.at).toEqual({ '24': null, '48': null, '72': null })
    expect(DATA.scorecard.methods.nothing.false_alarm_50).toBeNull()
    expect(DATA.scorecard.methods.hybrid?.mae_pp).toBe(9)
    expect(DATA.scorecard.methods.wind_timing).toBeDefined()
  })

  it('agrees with the Python twin on expected policies out', () => {
    const expected = readJson(join(FOLDER, 'expected_exposure.json')) as Record<HourKey, ExpectedOut>

    for (const hours of WAITING_PERIODS) {
      const want = expected[String(hours) as HourKey]
      const got = expectedPoliciesOut(DATA.exposure, hours)

      expect(got.low, `low at ${hours} h`).toBeCloseTo(want.low, 6)
      expect(got.high, `high at ${hours} h`).toBeCloseTo(want.high, 6)
      expect(got.unknownPolicies, `unknown at ${hours} h`).toBe(want.unknown_policies)
    }
    expect(expected['72'].unknown_policies).toBeGreaterThan(0)
  })

  it('round-trips claim ids into counties of the storm with an outage', () => {
    const ids = DATA.claims.map((c) => c.claim_id)
    const counties = new Set(DATA.counties.features.map((f) => f.properties.fips))

    expect(new Set(ids).size).toBe(ids.length)
    expect(ids.length).toBeGreaterThan(0)
    for (const claim of DATA.claims) {
      expect(counties.has(claim.fips), claim.claim_id).toBe(true)
      expect(DATA.restoration[claim.fips]?.official_day ?? 0, claim.claim_id).toBeGreaterThan(0)
    }
  })
})

describe('enums, required keys and patterns match the schema (CT-05)', () => {
  it('reads the same enums', () => {
    expect([...ROLES]).toEqual(at(SCHEMA, '$defs', 'role', 'enum'))
    expect([...STATUSES]).toEqual(at(SCHEMA, '$defs', 'status', 'enum'))
    expect([...SATELLITES]).toEqual(at(SCHEMA, '$defs', 'satellite', 'enum'))
    expect([...WAITING_PERIODS]).toEqual(at(SCHEMA, '$defs', 'waitingPeriod', 'enum'))
    expect([...WINDOWS]).toEqual(at(SCHEMA, '$defs', 'scorecard', 'properties', 'window', 'enum'))
    expect([...CORE_METHODS]).toEqual(at(SCHEMA, '$defs', 'scorecard', 'properties', 'methods', 'required'))
    expect(sortedKeys(at(SCHEMA, '$defs', 'scorecard', 'properties', 'methods', 'properties'))).toEqual(
      [...CORE_METHODS, ...EXTRA_METHODS].sort(),
    )
    expect([...METRIC_NAMES]).toEqual(at(SCHEMA, '$defs', 'metrics', 'required'))
  })

  it('reads every required key, and no other, of each file', () => {
    const required = (...keys: string[]) => [...(at(SCHEMA, '$defs', ...keys, 'required') as string[])].sort()

    expect(sortedKeys(DATA.meta)).toEqual(required('meta'))
    expect(sortedKeys(DATA.nights['99001']?.[0])).toEqual(required('nightEntry'))
    expect(sortedKeys(DATA.restoration['99001'])).toEqual(required('restorationEntry'))
    expect(sortedKeys(DATA.exposure['99001'])).toEqual(required('exposureEntry'))
    expect(sortedKeys(DATA.exposure['99001']?.at)).toEqual(required('exposureEntry', 'properties', 'at'))
    expect(sortedKeys(DATA.claims[0])).toEqual(required('claim'))
    expect(sortedKeys(DATA.scorecard)).toEqual(required('scorecard'))
    expect(sortedKeys(DATA.scorecard.methods.isotonic)).toEqual(required('metrics'))
    // a feature's own "properties" member is itself described under the schema's "properties" keyword
    expect(sortedKeys(DATA.counties.features[0]?.properties)).toEqual(required('countyFeature', 'properties', 'properties'))
    expect(sortedKeys(DATA.states.features[0]?.properties)).toEqual(required('stateFeature', 'properties', 'properties'))
  })

  it('gives the same verdict as the schema patterns', () => {
    const agree = (ours: RegExp, def: string, samples: readonly string[], stricterOn: readonly string[] = []) => {
      const theirs = new RegExp(at(SCHEMA, '$defs', def, 'pattern') as string)
      for (const sample of samples) {
        const schemaSays = theirs.test(sample)
        expect(ours.test(sample), `${def} on ${JSON.stringify(sample)}`).toBe(
          stricterOn.includes(sample) ? false : schemaSays,
        )
        if (stricterOn.includes(sample)) expect(schemaSays, `the schema accepts ${sample}`).toBe(true)
      }
    }

    agree(FIPS, 'fips', ['12071', '99001', '1207', '120711', 'ab071', ''])
    agree(ISO_DATE, 'date', ['2099-09-10', '2099-9-10', '20990910', 'yesterday', ''])
    agree(
      STORM_ID,
      'stormId',
      ['ian2022', 'ian2022_sample', 'synth2099', 'ian-2022', 'Ian2022', '', '../x', 'x', 'a_b_c', '_x'],
    )
  })
})

describe('shared cases (CT-04)', () => {
  const cases = (readJson(join(CONTRACT, 'cases.json')) as { cases: SharedCase[] }).cases

  it('has a parser for every kind', () => {
    expect(cases.length).toBeGreaterThan(20)
    for (const shared of cases) expect(PARSERS[shared.kind], shared.id).toBeDefined()
  })

  it.each(cases)('$id', (shared) => {
    const parse = PARSERS[shared.kind]
    if (!parse) throw new Error(`${shared.id}: no parser for ${shared.kind}`)
    const verdict = shared.ts ?? 'same'
    // lenient: the parser accepts a document the schema rejects; stricter: it rejects one the schema accepts
    const accepts = verdict === 'same' ? shared.valid : verdict === 'lenient'

    if (accepts) {
      expect(() => parse(shared.document, shared.id)).not.toThrow()
    } else {
      expect(() => parse(shared.document, shared.id)).toThrow(DataShapeError)
    }
  })
})

describe('tightened to the schema', () => {
  const night = (patch: Record<string, unknown>) => ({
    '99001': [{ night: '2099-09-10', status: 'ok', est: 0.5, lo: 0.4, hi: 0.6, official: 0.45, ...patch }],
  })
  const meta = RAW.meta as Record<string, unknown>
  const scorecard = RAW.scorecard as { methods: Record<string, Record<string, unknown>> }
  const withMetric = (metric: string, value: unknown) => ({
    ...scorecard,
    methods: { ...scorecard.methods, isotonic: { ...scorecard.methods.isotonic, [metric]: value } },
  })

  it('refuses a fraction outside 0..1 in nights.json', () => {
    expect(() => parseNights(night({ est: 1.5 }), 'n')).toThrow(/99001\[0\]\.est should be a fraction/)
    expect(() => parseNights(night({ hi: 1.0001 }), 'n')).toThrow(/99001\[0\]\.hi/)
    expect(() => parseNights(night({ official: -0.1 }), 'n')).toThrow(/99001\[0\]\.official/)
    expect(() => parseNights(night({ est: 0, lo: 0, hi: 1, official: 1 }), 'n')).not.toThrow()
  })

  it('refuses an estimate where the satellite cannot see', () => {
    expect(() => parseNights(night({ status: 'cant_see', est: 0, lo: null, hi: null }), 'n')).toThrow(
      /99001\[0\]\.est should be null when status is "cant_see"/,
    )
    expect(() => parseNights(night({ status: 'not_measurable', est: null, lo: null, hi: 0.2 }), 'n')).toThrow(
      /99001\[0\]\.hi/,
    )
    expect(() => parseNights(night({ status: 'cant_see', est: null, lo: null, hi: null }), 'n')).not.toThrow()
  })

  it('refuses a hyphen in a storm id, in the index, meta and scorecard alike', () => {
    const entry = { id: 'ian-2022', name: 'Ian', landfall: '2022-09-28', role: 'main', satellite: 'VNP46A2' }

    expect(() => parseIndex({ storms: [entry] }, 'i')).toThrow(/storms\[0\]\.id/)
    expect(() => parseMeta({ ...meta, id: 'ian-2022' }, 'm')).toThrow(/\bid should be/)
    expect(() => parseScorecard({ ...scorecard, storm_id: 'ian-2022' }, 's')).toThrow(/storm_id/)
    expect(() => parseMeta({ ...meta, id: 'ian2022_sample' }, 'm')).not.toThrow()
  })

  it('refuses a satellite outside the schema enum', () => {
    expect(() => parseMeta({ ...meta, satellite: 'MODIS' }, 'm')).toThrow(/satellite should be one of VNP46A2, VJ146A2/)
    expect(() => parseMeta({ ...meta, satellite: 'VJ146A2' }, 'm')).not.toThrow()
  })

  it('refuses a scorecard window outside 30, 60 and 90 minutes', () => {
    expect(() => parseScorecard({ ...scorecard, window: 45 }, 's')).toThrow(/window should be one of 30, 60, 90/)
    expect(() => parseScorecard({ ...scorecard, window: 30 }, 's')).not.toThrow()
  })

  it('refuses rates outside 0..1 and negative counts in the scorecard', () => {
    expect(() => parseScorecard(withMetric('catch_rate_50', 1.5), 's')).toThrow(/methods\.isotonic\.catch_rate_50/)
    expect(() => parseScorecard(withMetric('measurable_share', -0.2), 's')).toThrow(/measurable_share/)
    expect(() => parseScorecard(withMetric('mae_pp', -1), 's')).toThrow(/mae_pp should be zero or more/)
    expect(() => parseScorecard(withMetric('peak_total_est', -5), 's')).toThrow(/peak_total_est/)
    expect(() => parseScorecard(withMetric('restore_day_err', -2.5), 's')).not.toThrow() // a signed error in days
    expect(() => parseScorecard(withMetric('mae_pp', null), 's')).not.toThrow()
  })

  it('refuses a bracket end outside 0..1', () => {
    const county = (bracket: unknown) => ({ '99001': { home: 95, business: 5, at: { '24': bracket, '48': null, '72': null } } })

    expect(() => parseExposure(county([0.2, 1.2]), 'e')).toThrow(/99001\.at\["24"\]\[1\] should be a fraction/)
    expect(() => parseExposure(county([-0.1, 0.2]), 'e')).toThrow(/99001\.at\["24"\]\[0\]/)
    expect(() => parseExposure(county([0, 1]), 'e')).not.toThrow()
  })

  it('refuses fractional policy, housing and customer counts', () => {
    const feature = (patch: Record<string, unknown>) => ({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] },
          properties: { fips: '99001', name: 'Alpha', state: 'ZA', housing_units: 10, customers: 12, ...patch },
        },
      ],
    })

    expect(() => parseExposure({ '99001': { home: 95.5, business: 5, at: { '24': null, '48': null, '72': null } } }, 'e')).toThrow(
      /99001\.home should be a whole number/,
    )
    expect(() => parseCounties(feature({ housing_units: 10.5 }), 'c')).toThrow(/housing_units should be a whole number/)
    expect(() => parseCounties(feature({ customers: 1.5 }), 'c')).toThrow(/customers should be a whole number/)
    expect(() => parseCounties(feature({ customers: null }), 'c')).not.toThrow()
  })
})
