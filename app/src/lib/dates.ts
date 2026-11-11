/**
 * Calendar-date helpers that never touch the local time zone.
 *
 * The pipeline labels each night with the UTC calendar date of its evening
 * (YYYY-MM-DD). `new Date("2024-10-10")` is UTC midnight, which a browser in
 * Florida or California prints as Oct 9: an off-by-one night. Everything
 * here works on Date.UTC values and formats from fixed name tables.
 */
import type { IsoDate } from '../types'

const DAY_MS = 86_400_000
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const
const ISO = /^(\d{4})-(\d{2})-(\d{2})$/

/** Milliseconds at UTC midnight of an ISO date, or NaN if it isn't one. */
export function utcMillis(iso: IsoDate): number {
  const match = ISO.exec(iso)
  if (!match) return Number.NaN
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
}

/** Whole days from `landfall` to `night` (negative before landfall). */
export function dayOffset(night: IsoDate, landfall: IsoDate): number {
  return Math.round((utcMillis(night) - utcMillis(landfall)) / DAY_MS)
}

/** "Thu 10 Oct 2024" (or "10 Oct" when short). */
export function formatNightDate(iso: IsoDate, style: 'long' | 'short' = 'long'): string {
  const ms = utcMillis(iso)
  if (Number.isNaN(ms)) return iso
  const d = new Date(ms)
  const day = d.getUTCDate()
  const month = MONTHS[d.getUTCMonth()] ?? ''
  if (style === 'short') return `${day} ${month}`
  return `${WEEKDAYS[d.getUTCDay()] ?? ''} ${day} ${month} ${d.getUTCFullYear()}`
}

/** "the first pass after landfall", "day 3 after landfall", "2 days before landfall". */
export function describeDay(day: number): string {
  if (day === 0) return 'the first pass after landfall'
  if (day > 0) return `day ${day} after landfall`
  return `${-day} day${day === -1 ? '' : 's'} before landfall`
}
