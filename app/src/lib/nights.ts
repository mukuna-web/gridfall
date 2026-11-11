/**
 * Read-only views over a storm's night records.
 *
 * The one rule that matters most lives here: only a night with status "ok"
 * and a real number carries an estimate. Can't-see and not-measurable nights
 * yield null, so they can never slip into a sum, a fit or a color as 0.
 */
import type { IsoDate, NightRecord, NightsByCounty, NightStatus, RestorationRecord, StormData } from '../types'
import { isNumber } from './format'

/** What claimVerdict needs: one county's nights and the storm's landfall. */
export interface CountyNights {
  readonly fips: string
  readonly landfall: IsoDate
  readonly nights: readonly NightRecord[]
}

/** Everything the county card shows about one county. */
export interface CountyView extends CountyNights {
  readonly name: string
  readonly state: string
  readonly customers: number | null
  readonly housingUnits: number
  readonly restoration: RestorationRecord | null
}

export interface CountyLabel {
  readonly name: string
  readonly state: string
}

export type CountyIndex = Readonly<Record<string, CountyLabel>>

export interface VisibilitySummary {
  readonly ok: number
  readonly cantSee: number
  readonly notMeasurable: number
  readonly total: number
}

export interface NightTotals {
  /** Counties with a clear estimate tonight. */
  readonly seen: number
  readonly total: number
  /** Customers out over seen counties that have a customer count; null if none. */
  readonly customersOut: { readonly est: number; readonly lo: number; readonly hi: number } | null
}

export function findNight(nights: readonly NightRecord[], night: IsoDate): NightRecord | undefined {
  return nights.find((n) => n.night === night)
}

/** The estimate, only when the satellite saw the county clearly. */
export function usableEstimate(record: NightRecord | undefined): number | null {
  return record?.status === 'ok' && isNumber(record.est) ? record.est : null
}

/** A missing record, or an "ok" night with no number, reads as can't see. */
export function displayStatus(record: NightRecord | undefined): NightStatus {
  if (record?.status === 'not_measurable') return 'not_measurable'
  return usableEstimate(record) === null ? 'cant_see' : 'ok'
}

export function visibilitySummary(nights: readonly NightRecord[]): VisibilitySummary {
  const statuses = nights.map(displayStatus)
  const countOf = (status: NightStatus) => statuses.filter((s) => s === status).length
  return { ok: countOf('ok'), cantSee: countOf('cant_see'), notMeasurable: countOf('not_measurable'), total: nights.length }
}

/** Share of counties seen clearly on each night (the timeline's cloud strip). */
export function clearShareByNight(
  byCounty: NightsByCounty,
  dates: readonly IsoDate[],
  fipsList: readonly string[] = Object.keys(byCounty),
): number[] {
  if (fipsList.length === 0) return dates.map(() => 0)
  return dates.map((date) => {
    const clear = fipsList.filter((fips) => displayStatus(findNight(byCounty[fips] ?? [], date)) === 'ok').length
    return clear / fipsList.length
  })
}

/**
 * The first pass after landfall: the night labeled with the landfall date is
 * the ~01:30 pass the next morning, i.e. "the morning after".
 */
export function defaultNight(meta: { readonly landfall: IsoDate; readonly nights: readonly IsoDate[] }): IsoDate | null {
  return meta.nights.find((n) => n >= meta.landfall) ?? meta.nights[meta.nights.length - 1] ?? null
}

/** The county with the most customers out tonight, among clearly seen ones. */
export function leadCounty(data: StormData, night: IsoDate): string | null {
  let best: { fips: string; out: number } | null = null
  for (const feature of data.counties.features) {
    const { fips, customers } = feature.properties
    const est = usableEstimate(findNight(data.nights[fips] ?? [], night))
    if (est === null || customers === null) continue
    const out = est * customers
    if (!best || out > best.out) best = { fips, out }
  }
  return best?.fips ?? null
}

export function nightTotals(data: StormData, night: IsoDate): NightTotals {
  let seen = 0
  let counted = 0
  let est = 0
  let lo = 0
  let hi = 0
  for (const feature of data.counties.features) {
    const { fips, customers } = feature.properties
    const record = findNight(data.nights[fips] ?? [], night)
    const share = usableEstimate(record)
    if (share === null || !record) continue
    seen += 1
    if (customers === null) continue
    counted += 1
    est += share * customers
    lo += (isNumber(record.lo) ? record.lo : share) * customers
    hi += (isNumber(record.hi) ? record.hi : share) * customers
  }
  return { seen, total: data.counties.features.length, customersOut: counted > 0 ? { est, lo, hi } : null }
}

export function buildCountyView(data: StormData, fips: string): CountyView | null {
  const feature = data.counties.features.find((f) => f.properties.fips === fips)
  if (!feature) return null
  const p = feature.properties
  return {
    fips,
    name: p.name,
    state: p.state,
    customers: p.customers,
    housingUnits: p.housing_units,
    landfall: data.meta.landfall,
    nights: data.nights[fips] ?? [],
    restoration: data.restoration[fips] ?? null,
  }
}

/** fips -> name and state, for tables and pickers. */
export function countyIndex(data: StormData): CountyIndex {
  return Object.fromEntries(
    data.counties.features.map((f) => [f.properties.fips, { name: f.properties.name, state: f.properties.state }]),
  )
}

/** "Alpha, ZZ", or the bare FIPS when the county isn't in the shapes file. */
export function countyLabel(index: CountyIndex, fips: string): string {
  const county = index[fips]
  return county ? `${county.name}, ${county.state}` : fips
}
