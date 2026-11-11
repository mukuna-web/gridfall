/**
 * Types for the static files `blackout export` writes to public/data/.
 *
 * They mirror the export contract field for field, snake_case keys included,
 * so a pipeline/app mismatch fails loudly in data/validate.ts instead of
 * surfacing as a silent `undefined` on screen. Fractions are 0..1; `null`
 * always means "unknown" (can't see, no usable EAGLE-I run, no customer
 * count) and is never a stand-in for zero.
 */
import type { Feature, FeatureCollection, Geometry, MultiPolygon, Polygon } from 'geojson'

/** A calendar date, YYYY-MM-DD. Night dates are the evening of the night. */
export type IsoDate = string

export type StormRole = 'main' | 'lockbox' | 'stress'
export type NightStatus = 'ok' | 'cant_see' | 'not_measurable'
export type WaitingPeriod = 24 | 48 | 72
export type HourKey = '24' | '48' | '72'

/** public/data/index.json */
export interface StormIndexEntry {
  readonly id: string
  readonly name: string
  readonly landfall: IsoDate
  readonly role: StormRole
  readonly satellite: string
}

export interface StormIndex {
  readonly storms: readonly StormIndexEntry[]
}

/** public/data/<id>/meta.json */
export interface StormMeta extends StormIndexEntry {
  readonly nights: readonly IsoDate[]
  readonly waiting_periods: readonly WaitingPeriod[]
  readonly default_waiting_period: WaitingPeriod
  readonly generated: string
  readonly notes: readonly string[]
}

/** counties.geojson feature properties */
export interface CountyProperties {
  readonly fips: string
  readonly name: string
  readonly state: string
  readonly housing_units: number
  readonly customers: number | null
}

export type CountyGeometry = Polygon | MultiPolygon
export type CountyFeature = Feature<CountyGeometry, CountyProperties>
export type CountyCollection = FeatureCollection<CountyGeometry, CountyProperties>

/** states.geojson feature properties */
export interface StateProperties {
  readonly state: string
}

export type StateCollection = FeatureCollection<Geometry, StateProperties>

/** nights.json: one record per county per night */
export interface NightRecord {
  readonly night: IsoDate
  readonly status: NightStatus
  readonly est: number | null
  readonly lo: number | null
  readonly hi: number | null
  readonly official: number | null
}

export type NightsByCounty = Readonly<Record<string, readonly NightRecord[]>>

/** restoration.json: days after landfall; est_hi null = not restored within the window */
export interface RestorationRecord {
  readonly est_lo: number | null
  readonly est_hi: number | null
  readonly official_day: number | null
}

export type RestorationByCounty = Readonly<Record<string, RestorationRecord>>

/** A [lo, hi] share-out bracket at an hour mark. */
export type ShareBracket = readonly [lo: number, hi: number]

/** exposure.json: synthetic policies per county and their % out bracket per waiting period */
export interface CountyExposure {
  readonly home: number
  readonly business: number
  readonly at: Readonly<Record<HourKey, ShareBracket | null>>
}

export type ExposureByCounty = Readonly<Record<string, CountyExposure>>

/** claims.json */
export interface Claim {
  readonly claim_id: string
  readonly policy_id: string
  readonly fips: string
  readonly claimed_days_out: number
}

/** scorecard.json */
export interface MethodScore {
  readonly mae_pp: number | null
  readonly peak_total_est: number | null
  readonly peak_total_official: number | null
  readonly catch_rate_50: number | null
  readonly false_alarm_50: number | null
  readonly restore_day_err: number | null
  readonly measurable_share: number | null
}

/** The pre-registered curve and its two simple guesses: always in scorecard.json. */
export type CoreMethod = 'isotonic' | 'wind_only' | 'nothing'
/** Scored beside them since 2026-11-08 (decision log, "Model choice"); optional so older files still load. */
export type ExtraMethod = 'hybrid' | 'wind_timing'
export type MethodName = CoreMethod | ExtraMethod
export type MetricName = keyof MethodScore

export interface Scorecard {
  readonly storm_id: string
  readonly window: number
  readonly methods: Readonly<Record<CoreMethod, MethodScore>> & Readonly<Partial<Record<ExtraMethod, MethodScore>>>
  readonly note: string
}

/** Everything one storm needs, after validation. */
export interface StormData {
  readonly meta: StormMeta
  readonly counties: CountyCollection
  readonly states: StateCollection
  readonly nights: NightsByCounty
  readonly restoration: RestorationByCounty
  readonly exposure: ExposureByCounty
  readonly claims: readonly Claim[]
  readonly scorecard: Scorecard
}

/** The eight per-storm files, keyed the way StormData names them. */
export type StormFileKey = keyof StormData

export const STORM_FILES: Readonly<Record<StormFileKey, string>> = {
  meta: 'meta.json',
  counties: 'counties.geojson',
  states: 'states.geojson',
  nights: 'nights.json',
  restoration: 'restoration.json',
  exposure: 'exposure.json',
  claims: 'claims.json',
  scorecard: 'scorecard.json',
}

export const WAITING_PERIODS: readonly WaitingPeriod[] = [24, 48, 72]
export const CORE_METHODS: readonly CoreMethod[] = ['isotonic', 'wind_only', 'nothing']
export const EXTRA_METHODS: readonly ExtraMethod[] = ['hybrid', 'wind_timing']
/** Display order: the map's model first, then the pre-registered curve, then the guesses. */
export const METHOD_NAMES: readonly MethodName[] = ['hybrid', 'isotonic', 'wind_timing', 'wind_only', 'nothing']
export const METRIC_NAMES: readonly MetricName[] = [
  'mae_pp',
  'peak_total_est',
  'peak_total_official',
  'catch_rate_50',
  'false_alarm_50',
  'restore_day_err',
  'measurable_share',
]
