/**
 * Shape checks for the JSON that `blackout export` writes.
 *
 * The app never trusts a file just because it parsed: a renamed key or a
 * string where a number belongs would otherwise render as a blank or, worse,
 * as 0% out. Each parser returns a new, typed object and throws a
 * DataShapeError naming the file and the exact field path.
 *
 * The checks follow schema/export.schema.json: its enums, its storm-id, date
 * and FIPS patterns, fractions in 0..1, whole policy and housing counts, and
 * est/lo/hi null unless the satellite saw the county (status "ok").
 * tests/fixtures/contract/cases.json records where the two still differ.
 *
 * Leniency is deliberate and narrow: a *missing* nullable number reads as
 * null (unknown) and unknown extra keys are ignored. A value of the wrong
 * type is always an error.
 */
import type {
  Claim,
  CountyCollection,
  CountyExposure,
  CountyFeature,
  ExposureByCounty,
  HourKey,
  MethodName,
  MethodScore,
  MetricName,
  NightRecord,
  NightsByCounty,
  NightStatus,
  RestorationByCounty,
  Scorecard,
  ShareBracket,
  StateCollection,
  StormData,
  StormFileKey,
  StormIndex,
  StormIndexEntry,
  StormMeta,
  StormRole,
  WaitingPeriod,
} from '../types'
import { CORE_METHODS, EXTRA_METHODS, METRIC_NAMES, STORM_FILES, WAITING_PERIODS } from '../types'

export class DataShapeError extends Error {
  readonly file: string

  constructor(file: string, detail: string) {
    super(`${file}: ${detail}`)
    this.name = 'DataShapeError'
    this.file = file
  }
}

type Json = Readonly<Record<string, unknown>>

export const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
export const FIPS = /^\d{5}$/
/**
 * Lowercase ids like "ian2022" or "ian2022_sample": nothing that could climb
 * out of data/. The schema's stormId (^[a-z0-9_]+$) also allows a leading
 * underscore; this parser does not, and no exported storm has one.
 */
export const STORM_ID = /^[a-z0-9][a-z0-9_]*$/
export const ROLES: readonly StormRole[] = ['main', 'lockbox', 'stress']
export const STATUSES: readonly NightStatus[] = ['ok', 'cant_see', 'not_measurable']
export const SATELLITES: readonly string[] = ['VNP46A2', 'VJ146A2']
/** EAGLE-I windows around the satellite pass, in minutes. */
export const WINDOWS: readonly number[] = [30, 60, 90]
const HOUR_KEYS: readonly HourKey[] = ['24', '48', '72']
const COUNTY_GEOMETRIES = ['Polygon', 'MultiPolygon'] as const
const STATE_GEOMETRIES = ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString'] as const
/** Estimates exist only where the satellite saw the county; elsewhere the pipeline writes null, never 0. */
const ESTIMATE_KEYS = ['est', 'lo', 'hi'] as const
/** How each scorecard metric is read: counts are zero or more, rates are fractions, an error in days is signed. */
const METRIC_KINDS: Readonly<Record<MetricName, 'count' | 'fraction' | 'days'>> = {
  mae_pp: 'count',
  peak_total_est: 'count',
  peak_total_official: 'count',
  catch_rate_50: 'fraction',
  false_alarm_50: 'fraction',
  restore_day_err: 'days',
  measurable_share: 'fraction',
}

function describeValue(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return 'nothing'
  if (Array.isArray(value)) return 'an array'
  if (typeof value === 'string') return JSON.stringify(value.length > 40 ? `${value.slice(0, 40)}…` : value)
  if (typeof value === 'object') return 'an object'
  return String(value)
}

type Read<T> = (value: unknown, path: string) => T

/** The same reader, with null and a missing key both reading as null (unknown). */
function nullable<T>(read: Read<T>): Read<T | null> {
  return (value, path) => (value === null || value === undefined ? null : read(value, path))
}

/** Field readers bound to one file, so every error names it. */
function reader(file: string) {
  const fail = (path: string, expected: string, value: unknown): never => {
    throw new DataShapeError(file, `${path} should be ${expected}, got ${describeValue(value)}`)
  }
  const record = (value: unknown, path: string): Json =>
    typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Json) : fail(path, 'an object', value)
  const array = (value: unknown, path: string): readonly unknown[] =>
    Array.isArray(value) ? value : fail(path, 'an array', value)
  const string = (value: unknown, path: string): string => (typeof value === 'string' ? value : fail(path, 'a string', value))
  const number = (value: unknown, path: string): number =>
    typeof value === 'number' && Number.isFinite(value) ? value : fail(path, 'a finite number', value)
  const count = (value: unknown, path: string): number => {
    const n = number(value, path)
    return n >= 0 ? n : fail(path, 'zero or more', value)
  }
  const whole = (value: unknown, path: string): number => {
    const n = count(value, path)
    return Number.isInteger(n) ? n : fail(path, 'a whole number', value)
  }
  const fraction = (value: unknown, path: string): number => {
    const n = number(value, path)
    return n >= 0 && n <= 1 ? n : fail(path, 'a fraction between 0 and 1', value)
  }
  const matching = (value: unknown, path: string, pattern: RegExp, what: string): string => {
    const s = string(value, path)
    return pattern.test(s) ? s : fail(path, what, value)
  }
  const date = (value: unknown, path: string): string => matching(value, path, ISO_DATE, 'a YYYY-MM-DD date')
  const fips = (value: unknown, path: string): string => matching(value, path, FIPS, 'a 5-digit FIPS string')
  const stormId = (value: unknown, path: string): string =>
    matching(value, path, STORM_ID, 'a lowercase storm id like "ian2022" (letters, digits and underscores)')
  function oneOf<T extends string | number>(value: unknown, path: string, options: readonly T[]): T {
    return options.includes(value as T) ? (value as T) : fail(path, `one of ${options.join(', ')}`, value)
  }
  return {
    fail, record, array, string, number, count, whole, fraction, date, fips, stormId, oneOf,
    nullableNumber: nullable(number), nullableCount: nullable(count),
    nullableWhole: nullable(whole), nullableFraction: nullable(fraction),
  }
}

type Reader = ReturnType<typeof reader>

/** "storms[0]" + "id" -> "storms[0].id"; a top-level field is just "id". */
function field(prefix: string, key: string): string {
  return prefix ? `${prefix}.${key}` : key
}

function parseEntry(r: Reader, raw: unknown, prefix: string): StormIndexEntry {
  const o = r.record(raw, prefix || 'the file')
  return {
    id: r.stormId(o.id, field(prefix, 'id')),
    name: r.string(o.name, field(prefix, 'name')),
    landfall: r.date(o.landfall, field(prefix, 'landfall')),
    role: r.oneOf(o.role, field(prefix, 'role'), ROLES),
    satellite: r.oneOf(o.satellite, field(prefix, 'satellite'), SATELLITES),
  }
}

export function parseIndex(raw: unknown, file = 'data/index.json'): StormIndex {
  const r = reader(file)
  const root = r.record(raw, 'the file')
  return { storms: r.array(root.storms, 'storms').map((s, i) => parseEntry(r, s, `storms[${i}]`)) }
}

export function parseMeta(raw: unknown, file: string): StormMeta {
  const r = reader(file)
  const o = r.record(raw, 'the file')
  const nights = r.array(o.nights, 'nights').map((n, i) => r.date(n, `nights[${i}]`))
  const waiting = r.array(o.waiting_periods, 'waiting_periods').map((w, i) =>
    r.oneOf<WaitingPeriod>(w, `waiting_periods[${i}]`, WAITING_PERIODS),
  )
  const fallback = r.oneOf<WaitingPeriod>(o.default_waiting_period, 'default_waiting_period', WAITING_PERIODS)
  if (!waiting.includes(fallback)) r.fail('default_waiting_period', `one of waiting_periods (${waiting.join(', ')})`, fallback)
  return {
    ...parseEntry(r, o, ''),
    // Sorted and de-duplicated so the night slider always runs forward in time.
    nights: [...new Set(nights)].sort(),
    waiting_periods: [...new Set(waiting)].sort((a, b) => a - b),
    default_waiting_period: fallback,
    generated: r.string(o.generated, 'generated'),
    notes: r.array(o.notes ?? [], 'notes').map((n, i) => r.string(n, `notes[${i}]`)),
  }
}

function featureList(r: Reader, raw: unknown): readonly unknown[] {
  const o = r.record(raw, 'the file')
  if (o.type !== 'FeatureCollection') r.fail('type', '"FeatureCollection"', o.type)
  return r.array(o.features, 'features')
}

function geometry<T extends string>(r: Reader, raw: unknown, path: string, types: readonly T[]) {
  const g = r.record(raw, path)
  return { type: r.oneOf(g.type, `${path}.type`, types), coordinates: r.array(g.coordinates, `${path}.coordinates`) }
}

export function parseCounties(raw: unknown, file: string): CountyCollection {
  const r = reader(file)
  const seen = new Set<string>()
  const features = featureList(r, raw).map((f, i): CountyFeature => {
    const path = `features[${i}]`
    const o = r.record(f, path)
    const p = r.record(o.properties, `${path}.properties`)
    const fips = r.fips(p.fips, `${path}.properties.fips`)
    if (seen.has(fips)) r.fail(`${path}.properties.fips`, 'unique', fips)
    seen.add(fips)
    return {
      type: 'Feature',
      geometry: geometry(r, o.geometry, `${path}.geometry`, COUNTY_GEOMETRIES) as CountyFeature['geometry'],
      properties: {
        fips,
        name: r.string(p.name, `${path}.properties.name`),
        state: r.string(p.state, `${path}.properties.state`),
        housing_units: r.whole(p.housing_units, `${path}.properties.housing_units`),
        customers: r.nullableWhole(p.customers, `${path}.properties.customers`),
      },
    }
  })
  return { type: 'FeatureCollection', features }
}

export function parseStates(raw: unknown, file: string): StateCollection {
  const r = reader(file)
  const features = featureList(r, raw).map((f, i) => {
    const path = `features[${i}]`
    const o = r.record(f, path)
    const p = r.record(o.properties, `${path}.properties`)
    return {
      type: 'Feature' as const,
      geometry: geometry(r, o.geometry, `${path}.geometry`, STATE_GEOMETRIES) as StateCollection['features'][number]['geometry'],
      properties: { state: r.string(p.state, `${path}.properties.state`) },
    }
  })
  return { type: 'FeatureCollection', features }
}

/** Maps a FIPS-keyed object through `parse`, checking every key is a FIPS code. */
function byFips<T>(r: Reader, raw: unknown, parse: (value: unknown, path: string) => T): Readonly<Record<string, T>> {
  const o = r.record(raw, 'the file')
  return Object.fromEntries(Object.entries(o).map(([key, value]) => [r.fips(key, `key ${JSON.stringify(key)}`), parse(value, key)]))
}

/** One county on one night. Where the satellite did not see the county, an estimate is a pipeline bug, not a 0. */
function nightRecord(r: Reader, item: unknown, path: string): NightRecord {
  const o = r.record(item, path)
  const status = r.oneOf(o.status, `${path}.status`, STATUSES)
  const parsed: NightRecord = {
    night: r.date(o.night, `${path}.night`),
    status,
    est: r.nullableFraction(o.est, `${path}.est`),
    lo: r.nullableFraction(o.lo, `${path}.lo`),
    hi: r.nullableFraction(o.hi, `${path}.hi`),
    official: r.nullableFraction(o.official, `${path}.official`),
  }
  if (status !== 'ok') {
    for (const key of ESTIMATE_KEYS) {
      if (parsed[key] !== null) r.fail(`${path}.${key}`, `null when status is "${status}" (can't see is never a number)`, parsed[key])
    }
  }
  return parsed
}

export function parseNights(raw: unknown, file: string): NightsByCounty {
  const r = reader(file)
  return byFips(r, raw, (list, fips) => r.array(list, fips).map((item, i) => nightRecord(r, item, `${fips}[${i}]`)))
}

export function parseRestoration(raw: unknown, file: string): RestorationByCounty {
  const r = reader(file)
  return byFips(r, raw, (value, fips) => {
    const o = r.record(value, fips)
    return {
      est_lo: r.nullableNumber(o.est_lo, `${fips}.est_lo`),
      est_hi: r.nullableNumber(o.est_hi, `${fips}.est_hi`),
      official_day: r.nullableNumber(o.official_day, `${fips}.official_day`),
    }
  })
}

function bracket(r: Reader, value: unknown, path: string): ShareBracket | null {
  if (value === null || value === undefined) return null
  const pair = r.array(value, path)
  if (pair.length !== 2) r.fail(path, '[lo, hi] or null', value)
  return [r.fraction(pair[0], `${path}[0]`), r.fraction(pair[1], `${path}[1]`)]
}

export function parseExposure(raw: unknown, file: string): ExposureByCounty {
  const r = reader(file)
  return byFips(r, raw, (value, fips): CountyExposure => {
    const o = r.record(value, fips)
    const at = r.record(o.at, `${fips}.at`)
    return {
      home: r.whole(o.home, `${fips}.home`),
      business: r.whole(o.business, `${fips}.business`),
      at: Object.fromEntries(HOUR_KEYS.map((h) => [h, bracket(r, at[h], `${fips}.at["${h}"]`)])) as CountyExposure['at'],
    }
  })
}

export function parseClaims(raw: unknown, file: string): readonly Claim[] {
  const r = reader(file)
  return r.array(raw, 'the file').map((item, i): Claim => {
    const path = `[${i}]`
    const o = r.record(item, path)
    return {
      claim_id: r.string(o.claim_id, `${path}.claim_id`),
      policy_id: r.string(o.policy_id, `${path}.policy_id`),
      fips: r.fips(o.fips, `${path}.fips`),
      claimed_days_out: r.count(o.claimed_days_out, `${path}.claimed_days_out`),
    }
  })
}

export function parseScorecard(raw: unknown, file: string): Scorecard {
  const r = reader(file)
  const o = r.record(raw, 'the file')
  const methods = r.record(o.methods, 'methods')
  const readers = { count: r.nullableCount, fraction: r.nullableFraction, days: r.nullableNumber } as const
  const parseMethod = (name: MethodName): MethodScore => {
    const m = r.record(methods[name], `methods.${name}`)
    return Object.fromEntries(
      METRIC_NAMES.map((metric) => [metric, readers[METRIC_KINDS[metric]](m[metric], `methods.${name}.${metric}`)]),
    ) as unknown as MethodScore
  }
  return {
    storm_id: r.stormId(o.storm_id, 'storm_id'),
    window: r.oneOf(o.window, 'window', WINDOWS),
    methods: Object.fromEntries([
      ...CORE_METHODS.map((name) => [name, parseMethod(name)] as const),
      ...EXTRA_METHODS.filter((name) => methods[name] !== undefined).map((name) => [name, parseMethod(name)] as const),
    ]) as Scorecard['methods'],
    note: o.note === undefined ? '' : r.string(o.note, 'note'),
  }
}

/** Label used in every message about a storm file, e.g. "data/ian2022/nights.json". */
export function stormFileLabel(id: string, key: StormFileKey): string {
  return `data/${id}/${STORM_FILES[key]}`
}

/** Parses all eight files of one storm and checks they belong to it. */
export function parseStormFiles(id: string, raw: Readonly<Record<StormFileKey, unknown>>): StormData {
  const label = (key: StormFileKey) => stormFileLabel(id, key)
  const meta = parseMeta(raw.meta, label('meta'))
  if (meta.id !== id) throw new DataShapeError(label('meta'), `describes storm "${meta.id}", expected "${id}"`)
  const scorecard = parseScorecard(raw.scorecard, label('scorecard'))
  if (scorecard.storm_id !== id) {
    throw new DataShapeError(label('scorecard'), `describes storm "${scorecard.storm_id}", expected "${id}"`)
  }
  return {
    meta,
    counties: parseCounties(raw.counties, label('counties')),
    states: parseStates(raw.states, label('states')),
    nights: parseNights(raw.nights, label('nights')),
    restoration: parseRestoration(raw.restoration, label('restoration')),
    exposure: parseExposure(raw.exposure, label('exposure')),
    claims: parseClaims(raw.claims, label('claims')),
    scorecard,
  }
}
