import { describe, expect, it } from 'vitest'
import { dayOffset, formatNightDate } from './dates'
import {
  formatCount,
  formatCountRange,
  formatDay,
  formatDaysInterval,
  formatPct,
  formatRange,
} from './format'

describe('formatRange', () => {
  it('range text is "41–55%" for lo 0.41, hi 0.55', () => {
    expect(formatRange(0.41, 0.55)).toBe('41–55%')
  })

  it('collapses a range that rounds to one value', () => {
    expect(formatRange(0.412, 0.414)).toBe('41%')
  })

  it('orders a reversed pair instead of printing a negative range', () => {
    expect(formatRange(0.55, 0.41)).toBe('41–55%')
  })

  it('shows a dash, never 0%, when either end is unknown', () => {
    expect(formatRange(null, 0.5)).toBe('—')
    expect(formatRange(0.5, null)).toBe('—')
  })
})

describe('number formats', () => {
  it('formats shares as whole percents and unknowns as a dash', () => {
    expect(formatPct(0.481)).toBe('48%')
    expect(formatPct(0)).toBe('0%')
    expect(formatPct(null)).toBe('—')
    expect(formatPct(Number.NaN)).toBe('—')
  })

  it('formats counts with thousands separators', () => {
    expect(formatCount(1234567.4)).toBe('1,234,567')
    expect(formatCount(null)).toBe('—')
    expect(formatCountRange(9800, 15100)).toBe('9,800–15,100')
  })

  it('formats days without trailing zeros', () => {
    expect(formatDay(4)).toBe('4')
    expect(formatDay(4.5)).toBe('4.5')
  })
})

describe('formatDaysInterval', () => {
  it('reads a closed interval', () => {
    expect(formatDaysInterval(2, 4)).toBe('between day 2 and day 4')
  })

  it('reads an exact day', () => {
    expect(formatDaysInterval(3, 3)).toBe('day 3')
  })

  it('reads an open interval as not restored within the window', () => {
    expect(formatDaysInterval(9, null)).toBe('still dark after day 9 (not restored within the window)')
  })

  it('reads a restore seen on the first clear look', () => {
    expect(formatDaysInterval(null, 2)).toBe('by day 2 (first clear look)')
  })

  it('says unknown when the county was never seen clearly', () => {
    expect(formatDaysInterval(null, null)).toBe('unknown (never seen clearly)')
  })
})

describe('dates stay on the UTC calendar', () => {
  it('formats a night without slipping a day west of UTC', () => {
    // setup.ts runs tests in America/Los_Angeles, where a naive Date shows Oct 9.
    expect(formatNightDate('2024-10-10')).toBe('Thu 10 Oct 2024')
  })

  it('counts days after landfall', () => {
    expect(dayOffset('2024-10-13', '2024-10-09')).toBe(4)
    expect(dayOffset('2024-10-08', '2024-10-09')).toBe(-1)
    expect(dayOffset('2024-03-11', '2024-03-09')).toBe(2)
  })
})
