/**
 * Shareable view state in the query string: storm, night, county, waiting
 * period and the official toggle. Values come from a URL anyone can edit,
 * so each one is checked and dropped if it isn't valid.
 */
import type { IsoDate, WaitingPeriod } from '../types'
import { WAITING_PERIODS } from '../types'

export interface UrlState {
  readonly storm?: string
  readonly night?: IsoDate
  readonly county?: string
  readonly hours?: WaitingPeriod
  readonly official: boolean
}

const STORM = /^[a-z0-9][a-z0-9_-]*$/
const DATE = /^\d{4}-\d{2}-\d{2}$/
const FIPS = /^\d{5}$/

function valid(value: string | null, pattern: RegExp): string | undefined {
  return value !== null && pattern.test(value) ? value : undefined
}

export function parseUrlState(search: string): UrlState {
  const params = new URLSearchParams(search)
  const hours = Number(params.get('hours'))
  return {
    storm: valid(params.get('storm'), STORM),
    night: valid(params.get('night'), DATE),
    county: valid(params.get('county'), FIPS),
    hours: WAITING_PERIODS.includes(hours as WaitingPeriod) ? (hours as WaitingPeriod) : undefined,
    official: params.get('official') === '1',
  }
}

export function serializeUrlState(state: UrlState): string {
  const entries: Array<[string, string]> = []
  if (state.storm) entries.push(['storm', state.storm])
  if (state.night) entries.push(['night', state.night])
  if (state.county) entries.push(['county', state.county])
  if (state.hours) entries.push(['hours', String(state.hours)])
  if (state.official) entries.push(['official', '1'])
  const query = new URLSearchParams(entries).toString()
  return query ? `?${query}` : ''
}
