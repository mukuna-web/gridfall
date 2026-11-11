/**
 * Number and text formats for the report.
 *
 * One rule runs through all of them: an unknown value prints as an em dash,
 * never as 0. A county the satellite can't see is not a county with no
 * outage, and the formatting layer is the last place that could blur them.
 */

export const UNKNOWN = '—'
const RANGE_DASH = '–'
const counts = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

export function isNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function wholePercent(share: number): number {
  // `+ 0` folds -0 into 0 so a tiny negative never prints as "-0%".
  return Math.round(share * 100) + 0
}

/** 0.481 -> "48%". */
export function formatPct(share: number | null | undefined): string {
  return isNumber(share) ? `${wholePercent(share)}%` : UNKNOWN
}

/** (0.41, 0.55) -> "41–55%"; ends that round together collapse to one value. */
export function formatRange(lo: number | null | undefined, hi: number | null | undefined): string {
  if (!isNumber(lo) || !isNumber(hi)) return UNKNOWN
  const low = wholePercent(Math.min(lo, hi))
  const high = wholePercent(Math.max(lo, hi))
  return low === high ? `${low}%` : `${low}${RANGE_DASH}${high}%`
}

/** 1234567.4 -> "1,234,567". */
export function formatCount(value: number | null | undefined): string {
  return isNumber(value) ? counts.format(Math.round(value)) : UNKNOWN
}

/** (9800, 15100) -> "9,800–15,100". */
export function formatCountRange(lo: number | null | undefined, hi: number | null | undefined): string {
  if (!isNumber(lo) || !isNumber(hi)) return UNKNOWN
  return `${formatCount(Math.min(lo, hi))}${RANGE_DASH}${formatCount(Math.max(lo, hi))}`
}

/** 4 -> "4", 4.5 -> "4.5". */
export function formatDay(day: number): string {
  return Number.isInteger(day) ? String(day) : day.toFixed(1).replace(/\.0$/, '')
}

/**
 * Days until a county was back under the restoration threshold, as an
 * interval: the last clear night still above it (lo) and the first clear
 * night at or below it (hi). Clouds in between widen the interval.
 */
export function formatDaysInterval(lo: number | null | undefined, hi: number | null | undefined): string {
  if (!isNumber(lo) && !isNumber(hi)) return 'unknown (never seen clearly)'
  if (!isNumber(hi)) return `still dark after day ${formatDay(lo as number)} (not restored within the window)`
  if (!isNumber(lo)) return `by day ${formatDay(hi)} (first clear look)`
  if (lo === hi) return `day ${formatDay(hi)}`
  return `between day ${formatDay(Math.min(lo, hi))} and day ${formatDay(Math.max(lo, hi))}`
}
