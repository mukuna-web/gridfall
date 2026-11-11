import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CountyView } from '../lib/nights'
import type { NightRecord } from '../types'
import { CountyCard } from './CountyCard'

const COUNTY: CountyView = {
  fips: '99003',
  name: 'Bravo',
  state: 'ZZ',
  customers: 50000,
  housingUnits: 42000,
  landfall: '2024-10-09',
  nights: [
    { night: '2024-10-09', status: 'ok', est: 0.48, lo: 0.41, hi: 0.55, official: 0.52 },
    { night: '2024-10-10', status: 'ok', est: 0.4, lo: 0.33, hi: 0.47, official: null },
    { night: '2024-10-11', status: 'cant_see', est: null, lo: null, hi: null, official: 0.31 },
    { night: '2024-10-12', status: 'not_measurable', est: null, lo: null, hi: null, official: 0.2 },
  ],
  restoration: { est_lo: 2, est_hi: 4, official_day: 3 },
}

describe('CountyCard', () => {
  it('CountyCard shows "can\'t see" for null est', () => {
    // The plan's interface: <CountyCard county night>, official numbers off by default.
    render(<CountyCard county={COUNTY} night="2024-10-11" />)

    expect(screen.getByTestId('county-headline').textContent).toMatch(/can't see/)
    // Never a zero: the customers-out figure is unknown, not 0.
    expect(screen.queryByText('0%')).toBeNull()
    expect(screen.queryByText('0')).toBeNull()
    expect(screen.queryByText(/EAGLE-I/)).toBeNull()
  })

  it("ignores a stray range on a can't-see night instead of showing customers out", () => {
    const stray: CountyView = {
      ...COUNTY,
      nights: [{ night: '2024-10-11', status: 'cant_see', est: null, lo: 0.31, hi: 0.47, official: null }],
    }

    render(<CountyCard county={stray} night="2024-10-11" showOfficial={false} />)

    // 0.31 × 50,000 and 0.47 × 50,000 would read as a real customers-out range.
    expect(screen.queryByText(/15,500/)).toBeNull()
    expect(screen.queryByText(/23,500/)).toBeNull()
    expect(screen.getByTestId('county-headline').textContent).toMatch(/can't see/)
  })

  it('blames the missing customer count, not EAGLE-I runs, when the county has none', () => {
    const uncounted: CountyView = { ...COUNTY, customers: null }

    render(<CountyCard county={uncounted} night="2024-10-10" showOfficial />)

    expect(screen.getByText(/no EAGLE-I customer count/i)).toBeTruthy()
    expect(screen.queryByText(/no usable EAGLE-I run/i)).toBeNull()
  })

  it('range text is "41–55%" for lo 0.41, hi 0.55', () => {
    render(<CountyCard county={COUNTY} night="2024-10-09" showOfficial={false} />)

    expect(screen.getByText('41–55%')).toBeTruthy()
    expect(screen.getByTestId('county-headline').textContent).toMatch(/48%/)
  })

  it('shows customers out and, labeled approximate, homes out', () => {
    render(<CountyCard county={COUNTY} night="2024-10-09" showOfficial={false} />)

    expect(screen.getByText('24,000')).toBeTruthy() // 0.48 × 50,000 customers
    expect(screen.getByText('20,160')).toBeTruthy() // 0.48 × 42,000 housing units
    expect(screen.getByText(/homes out \(approximate\)/i)).toBeTruthy()
  })

  it('shows the official number only when the toggle is on', () => {
    const { rerender } = render(<CountyCard county={COUNTY} night="2024-10-09" showOfficial={false} />)
    expect(screen.queryByText(/EAGLE-I/)).toBeNull()

    rerender(<CountyCard county={COUNTY} night="2024-10-09" showOfficial />)

    expect(screen.getByText(/EAGLE-I/)).toBeTruthy()
    expect(screen.getByText('52%')).toBeTruthy()
    expect(screen.getByText(/official: day 3/i)).toBeTruthy()
  })

  it('says when EAGLE-I has no usable number instead of showing zero', () => {
    render(<CountyCard county={COUNTY} night="2024-10-10" showOfficial />)

    expect(screen.getByText(/no usable EAGLE-I run/i)).toBeTruthy()
  })

  it('shows days dark as an interval and the visibility notes', () => {
    render(<CountyCard county={COUNTY} night="2024-10-09" showOfficial={false} />)

    expect(screen.getByText(/between day 2 and day 4/)).toBeTruthy()
    expect(screen.getByText(/seen clearly on 2 of 4 nights/i)).toBeTruthy()
  })

  it('explains a not-measurable night', () => {
    render(<CountyCard county={COUNTY} night="2024-10-12" showOfficial={false} />)

    expect(screen.getByTestId('county-headline').textContent).toMatch(/not measurable/)
  })

  it('asks for a county when none is selected', () => {
    render(<CountyCard county={null} night="2024-10-09" showOfficial={false} />)

    expect(screen.getByText(/select a county/i)).toBeTruthy()
  })
})

/** The value cell of one fact, found from its label. */
function factValue(label: string): string {
  return screen.getByText(label).closest('.fact')?.querySelector('.fact__value')?.textContent ?? ''
}

describe('CountyCard on a night without an estimate', () => {
  const NIGHT = '2024-10-11'
  const cases: ReadonlyArray<{ readonly name: string; readonly record: NightRecord; readonly word: RegExp }> = [
    {
      name: "a can't-see night with a stray lo/hi",
      record: { night: NIGHT, status: 'cant_see', est: null, lo: 0, hi: 0.1, official: null },
      word: /can't see/,
    },
    {
      name: 'a not-measurable night with a stray estimate of 0',
      record: { night: NIGHT, status: 'not_measurable', est: 0, lo: 0, hi: 0.05, official: null },
      word: /not measurable/,
    },
    {
      name: 'an ok night with no estimate written',
      record: { night: NIGHT, status: 'ok', est: null, lo: null, hi: null, official: null },
      word: /no estimate/,
    },
  ]

  for (const { name, record, word } of cases) {
    it(`shows words, never a number, on ${name}`, () => {
      render(<CountyCard county={{ ...COUNTY, nights: [record] }} night={NIGHT} showOfficial={false} />)

      const headline = screen.getByTestId('county-headline').textContent ?? ''
      expect(headline).toMatch(word)
      // Not even "0%" in the explanation: a reader scanning for the figure must find none.
      expect(headline).not.toMatch(/\d/)
      expect(factValue('Customers out')).toBe('—')
      expect(factValue('Homes out (approximate)')).toBe('—')
    })
  }

  it('says no reading was exported when the night is missing from the county', () => {
    render(<CountyCard county={{ ...COUNTY, nights: [] }} night={NIGHT} showOfficial={false} />)

    const headline = screen.getByTestId('county-headline').textContent ?? ''
    expect(headline).toMatch(/no estimate/)
    expect(headline).not.toMatch(/\d/)
    expect(factValue('Customers out')).toBe('—')
  })
})
