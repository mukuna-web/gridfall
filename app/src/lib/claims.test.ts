import { describe, expect, it } from 'vitest'
import type { NightRecord } from '../types'
import { claimVerdict, verdictText } from './claims'
import type { CountyNights } from './nights'

const NIGHTS: readonly NightRecord[] = [
  // The night before landfall never counts toward the peak.
  { night: '2024-10-08', status: 'ok', est: 0.02, lo: 0.0, hi: 0.06, official: 0.01 },
  { night: '2024-10-09', status: 'ok', est: 0.81, lo: 0.72, hi: 0.9, official: 0.85 },
  { night: '2024-10-10', status: 'ok', est: 0.64, lo: 0.55, hi: 0.74, official: 0.7 },
  { night: '2024-10-11', status: 'cant_see', est: null, lo: null, hi: null, official: 0.52 },
  { night: '2024-10-12', status: 'ok', est: 0.12, lo: 0.06, hi: 0.2, official: 0.15 },
  { night: '2024-10-13', status: 'ok', est: 0.03, lo: 0.0, hi: 0.08, official: 0.04 },
]

const COUNTY: CountyNights = { fips: '99001', landfall: '2024-10-09', nights: NIGHTS }

describe('claimVerdict', () => {
  it('claim beyond 90% restored is review', () => {
    // Day 6: the last clear night at or before it is day 4, hi 0.08 of a 0.90 peak.
    const result = claimVerdict(6, COUNTY)

    expect(result.verdict).toBe('review')
    expect(result.shareRestoredBefore).toBeCloseTo(1 - 0.08 / 0.9, 9)
  })

  it('claim inside the curve fits', () => {
    // Day 1: hi 0.74 of a 0.90 peak, so only ~18% was restored.
    const result = claimVerdict(1, COUNTY)

    expect(result.verdict).toBe('fits')
    expect(result.shareRestoredBefore).toBeCloseTo(1 - 0.74 / 0.9, 9)
  })

  it("skips a can't-see night and uses the last clear night before it", () => {
    expect(claimVerdict(2, COUNTY).shareRestoredBefore).toBeCloseTo(1 - 0.74 / 0.9, 9)
  })

  it('uses the high end of the range, so a wide range does not flag a claim', () => {
    const wide: CountyNights = {
      ...COUNTY,
      nights: [
        { night: '2024-10-09', status: 'ok', est: 0.8, lo: 0.7, hi: 0.9, official: null },
        // The estimate says 3% out, but the range allows 40%: not a review.
        { night: '2024-10-12', status: 'ok', est: 0.03, lo: 0.0, hi: 0.4, official: null },
      ],
    }

    expect(claimVerdict(5, wide).verdict).toBe('fits')
  })

  it('treats exactly 90% restored as review', () => {
    const edge: CountyNights = {
      ...COUNTY,
      nights: [
        { night: '2024-10-09', status: 'ok', est: 0.7, lo: 0.6, hi: 0.8, official: null },
        { night: '2024-10-12', status: 'ok', est: 0.05, lo: 0.0, hi: 0.08, official: null },
      ],
    }

    expect(claimVerdict(3, edge).verdict).toBe('review')
  })

  it('is 0 and fits when the satellite never saw the county clearly', () => {
    const blind: CountyNights = {
      ...COUNTY,
      nights: NIGHTS.map((n) => ({ ...n, status: 'cant_see' as const, est: null, lo: null, hi: null })),
    }

    expect(claimVerdict(6, blind)).toEqual({ verdict: 'fits', shareRestoredBefore: 0 })
  })

  it('is 0 when no clear night falls on or before the claimed day', () => {
    const late: CountyNights = {
      ...COUNTY,
      nights: [{ night: '2024-10-12', status: 'ok', est: 0.05, lo: 0.0, hi: 0.08, official: null }],
    }

    expect(claimVerdict(1, late)).toEqual({ verdict: 'fits', shareRestoredBefore: 0 })
  })

  it('is 0 when the county was never out', () => {
    const calm: CountyNights = {
      ...COUNTY,
      nights: [{ night: '2024-10-10', status: 'ok', est: 0, lo: 0, hi: 0, official: 0 }],
    }

    expect(claimVerdict(4, calm)).toEqual({ verdict: 'fits', shareRestoredBefore: 0 })
  })
})

describe('verdictText', () => {
  it('words a review without ever saying fraud', () => {
    const text = verdictText({ verdict: 'review', shareRestoredBefore: 0.944 })

    expect(text).toBe('longer than 94% of the county: review')
    expect(text).not.toMatch(/fraud/i)
  })

  it('says fits', () => {
    expect(verdictText({ verdict: 'fits', shareRestoredBefore: 0.2 })).toBe('fits')
  })
})
