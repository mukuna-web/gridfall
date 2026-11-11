import { describe, expect, it } from 'vitest'
import { readFixtureJson } from '../test/fixtureFetch'
import type { NightRecord, StormData } from '../types'
import { parseStormFiles } from '../data/validate'
import {
  buildCountyView,
  clearShareByNight,
  defaultNight,
  displayStatus,
  leadCounty,
  nightTotals,
  usableEstimate,
  visibilitySummary,
} from './nights'

function fixtureStorm(): StormData {
  return parseStormFiles('milton2024', {
    meta: readFixtureJson('milton/meta.json'),
    counties: readFixtureJson('milton/counties.geojson'),
    states: readFixtureJson('milton/states.geojson'),
    nights: readFixtureJson('milton/nights.json'),
    restoration: readFixtureJson('milton/restoration.json'),
    exposure: readFixtureJson('milton/exposure.json'),
    claims: readFixtureJson('milton/claims.json'),
    scorecard: readFixtureJson('milton/scorecard.json'),
  })
}

const OK: NightRecord = { night: '2024-10-09', status: 'ok', est: 0.4, lo: 0.3, hi: 0.5, official: null }

describe('night status', () => {
  it("never lets a can't-see night carry an estimate, even a stray one", () => {
    const stray: NightRecord = { ...OK, status: 'cant_see' }

    expect(usableEstimate(stray)).toBeNull()
    expect(displayStatus(stray)).toBe('cant_see')
  })

  it("reads a missing record, or an ok night with no estimate, as can't see", () => {
    expect(displayStatus(undefined)).toBe('cant_see')
    expect(displayStatus({ ...OK, est: null })).toBe('cant_see')
    expect(usableEstimate({ ...OK, est: null })).toBeNull()
  })

  it('keeps not measurable distinct from can’t see', () => {
    expect(displayStatus({ ...OK, status: 'not_measurable', est: null })).toBe('not_measurable')
  })

  it('passes a clear estimate through, including a real zero', () => {
    expect(usableEstimate(OK)).toBe(0.4)
    expect(usableEstimate({ ...OK, est: 0 })).toBe(0)
  })

  it('counts nights by status', () => {
    const storm = fixtureStorm()

    expect(visibilitySummary(storm.nights['99003'] ?? [])).toEqual({
      ok: 4,
      cantSee: 2,
      notMeasurable: 0,
      total: 6,
    })
  })
})

describe('storm-level views', () => {
  it('shares of counties seen clearly per night', () => {
    const storm = fixtureStorm()

    // Charlie is never measurable; Delta is cloudy on the 9th and 10th; Alpha and Bravo on the 11th.
    expect(clearShareByNight(storm.nights, storm.meta.nights)).toEqual([0.75, 0.5, 0.5, 0.25, 0.5, 0.75])
  })

  it('opens on the first pass after landfall', () => {
    expect(defaultNight({ landfall: '2024-10-09', nights: ['2024-10-08', '2024-10-09', '2024-10-10'] })).toBe(
      '2024-10-09',
    )
    expect(defaultNight({ landfall: '2024-10-20', nights: ['2024-10-08', '2024-10-09'] })).toBe('2024-10-09')
    expect(defaultNight({ landfall: '2024-10-20', nights: [] })).toBeNull()
  })

  it('picks the county with the most customers out as the lead', () => {
    expect(leadCounty(fixtureStorm(), '2024-10-09')).toBe('99001')
  })

  it("totals customers out over seen counties only and says how many it could not see", () => {
    const totals = nightTotals(fixtureStorm(), '2024-10-09')

    expect(totals.seen).toBe(2)
    expect(totals.total).toBe(4)
    expect(totals.customersOut?.est).toBeCloseTo(0.81 * 140000 + 0.48 * 50000, 6)
    expect(totals.customersOut?.lo).toBeCloseTo(0.72 * 140000 + 0.41 * 50000, 6)
    expect(totals.customersOut?.hi).toBeCloseTo(0.9 * 140000 + 0.55 * 50000, 6)
  })

  it('has no customer total when no seen county has a customer count', () => {
    // Only Delta (no customer count) is clear on 2024-10-11.
    const totals = nightTotals(fixtureStorm(), '2024-10-11')

    expect(totals.seen).toBe(1)
    expect(totals.customersOut).toBeNull()
  })

  it('builds a county view from the storm files', () => {
    const view = buildCountyView(fixtureStorm(), '99001')

    expect(view).toMatchObject({
      fips: '99001',
      name: 'Alpha',
      state: 'ZZ',
      customers: 140000,
      housingUnits: 120000,
      landfall: '2024-10-09',
      restoration: { est_lo: 3, est_hi: 4, official_day: 4 },
    })
    expect(view?.nights).toHaveLength(6)
    expect(buildCountyView(fixtureStorm(), '00000')).toBeNull()
  })
})
