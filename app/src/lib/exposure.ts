/**
 * Expected policies without power after a waiting period.
 *
 * Each county carries a [lo, hi] bracket of % out at the hour mark (from the
 * clear nights either side of it). Policies times the bracket gives a low and
 * high count. A county with no bracket is one the satellite can't see: its
 * policies go to `unknownPolicies` and are never counted as zero out.
 */
import type { CountyExposure, ExposureByCounty, HourKey, WaitingPeriod } from '../types'
import { isNumber } from './format'

export interface PoliciesOut {
  readonly low: number
  readonly high: number
  readonly unknownPolicies: number
}

export interface ExposureRow {
  readonly fips: string
  readonly home: number
  readonly business: number
  readonly policies: number
  /** False when the satellite can't see the county at this hour. */
  readonly seen: boolean
  readonly loShare: number | null
  readonly hiShare: number | null
  readonly low: number | null
  readonly high: number | null
}

function hourKey(hours: WaitingPeriod): HourKey {
  return String(hours) as HourKey
}

/** The bracket ordered low to high, or null when the county is unseen. */
function bracketAt(county: CountyExposure, hours: WaitingPeriod): readonly [number, number] | null {
  const pair = county.at[hourKey(hours)]
  if (!pair || !isNumber(pair[0]) || !isNumber(pair[1])) return null
  return [Math.min(pair[0], pair[1]), Math.max(pair[0], pair[1])]
}

function toRow(fips: string, county: CountyExposure, hours: WaitingPeriod): ExposureRow {
  const policies = county.home + county.business
  const bracket = bracketAt(county, hours)
  return {
    fips,
    home: county.home,
    business: county.business,
    policies,
    seen: bracket !== null,
    loShare: bracket ? bracket[0] : null,
    hiShare: bracket ? bracket[1] : null,
    low: bracket ? policies * bracket[0] : null,
    high: bracket ? policies * bracket[1] : null,
  }
}

/** Seen counties first, most policies out (high end) first; blind counties last, largest first. */
function compareRows(a: ExposureRow, b: ExposureRow): number {
  if (a.seen !== b.seen) return a.seen ? -1 : 1
  const byOut = a.seen ? (b.high ?? 0) - (a.high ?? 0) : b.policies - a.policies
  return byOut !== 0 ? byOut : a.fips.localeCompare(b.fips)
}

/** One row per county for the portfolio table, in a new array. */
export function exposureRows(exposure: ExposureByCounty, hours: WaitingPeriod): ExposureRow[] {
  return Object.entries(exposure)
    .map(([fips, county]) => toRow(fips, county, hours))
    .sort(compareRows)
}

export function expectedPoliciesOut(exposure: ExposureByCounty, hours: WaitingPeriod): PoliciesOut {
  return Object.entries(exposure).reduce<PoliciesOut>(
    (total, [fips, county]) => {
      const row = toRow(fips, county, hours)
      if (row.low === null || row.high === null) {
        return { ...total, unknownPolicies: total.unknownPolicies + row.policies }
      }
      return { ...total, low: total.low + row.low, high: total.high + row.high }
    },
    { low: 0, high: 0, unknownPolicies: 0 },
  )
}
