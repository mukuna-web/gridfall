/**
 * Does a claimed outage fit what happened in the claim's county?
 *
 * County numbers can't speak for one address, so the check only ever says
 * "fits" or "review" and never accuses. It is built to stay fair: it reads
 * the HIGH end of the estimate range (the most outage the data allows), and
 * anything it can't see counts in the claimant's favour (share 0, "fits").
 */
import type { NightRecord } from '../types'
import { dayOffset } from './dates'
import { isNumber } from './format'
import type { CountyNights } from './nights'
import { usableEstimate } from './nights'

export type Verdict = 'fits' | 'review'

export interface ClaimResult {
  readonly verdict: Verdict
  /** Share of the county's peak outage (high end) restored by the claimed day, 0..1. */
  readonly shareRestoredBefore: number
}

export interface ClearNight {
  readonly night: string
  readonly day: number
  readonly hi: number
}

export interface ClaimEvidence {
  /** Clear nights from landfall on, oldest first. */
  readonly clearNights: readonly ClearNight[]
  /** Highest hi over those nights, or null when there are none. */
  readonly peakHi: number | null
  /** The last clear night at or before landfall + claimed days. */
  readonly used: ClearNight | null
}

/** Review once this share of the peak was restored before the claimed day. */
export const REVIEW_SHARE = 0.9
/** Float slack so a share of exactly 90% lands on review, as the rule says. */
const EPSILON = 1e-9

function isClear(n: NightRecord): boolean {
  return usableEstimate(n) !== null && isNumber(n.hi)
}

/**
 * The nights behind a verdict. The night labeled with the landfall date is
 * day 0: its pass is the morning after landfall, so it counts as after.
 */
export function claimEvidence(claimedDays: number, county: CountyNights): ClaimEvidence {
  const clearNights = county.nights
    .filter(isClear)
    .map((n) => ({ night: n.night, day: dayOffset(n.night, county.landfall), hi: n.hi as number }))
    .filter((n) => n.day >= 0)
    .sort((a, b) => a.day - b.day)
  const peakHi = clearNights.length > 0 ? Math.max(...clearNights.map((n) => n.hi)) : null
  const used = Number.isFinite(claimedDays) ? (clearNights.filter((n) => n.day <= claimedDays).at(-1) ?? null) : null
  return { clearNights, peakHi, used }
}

export function claimVerdict(claimedDays: number, county: CountyNights): ClaimResult {
  const { peakHi, used } = claimEvidence(claimedDays, county)
  if (used === null || peakHi === null || peakHi <= 0) return { verdict: 'fits', shareRestoredBefore: 0 }
  const share = Math.min(1, Math.max(0, 1 - used.hi / peakHi))
  return { verdict: share >= REVIEW_SHARE - EPSILON ? 'review' : 'fits', shareRestoredBefore: share }
}

/** "fits", or "longer than 94% of the county: review". Never the word fraud. */
export function verdictText(result: ClaimResult): string {
  if (result.verdict === 'fits') return 'fits'
  return `longer than ${Math.round(result.shareRestoredBefore * 100)}% of the county: review`
}
