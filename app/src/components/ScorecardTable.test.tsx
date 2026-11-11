import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MethodScore, Scorecard } from '../types'
import { ScorecardTable } from './ScorecardTable'

const score = (mae: number, peak: number): MethodScore => ({
  mae_pp: mae,
  peak_total_est: peak,
  peak_total_official: 1000,
  catch_rate_50: 0.5,
  false_alarm_50: 0.2,
  restore_day_err: 2,
  measurable_share: 0.8,
})

const base: Scorecard = {
  storm_id: 'x2024',
  window: 60,
  methods: { isotonic: score(3, 200), wind_only: score(4, 100), nothing: score(2.5, 0) },
  note: '',
}

describe('ScorecardTable', () => {
  it('shows only the three core methods when the file has no hybrid row', () => {
    render(<ScorecardTable scorecard={base} role="lockbox" />)
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['Metric', 'Night lights only (pre-registered)', 'Wind only', 'Nothing happened'])
  })

  it('puts the map model first and marks the closest peak total as best', () => {
    const card = { ...base, methods: { ...base.methods, hybrid: score(3.5, 900), wind_timing: score(3.2, 700) } }
    render(<ScorecardTable scorecard={card} role="main" />)
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers[1]).toBe('Storm context + night lights (the map)')
    const peakRow = screen.getByText('Peak customers out').closest('tr') as HTMLElement
    const best = within(peakRow).getAllByRole('cell').find((cell) => cell.className.includes('is-best'))
    expect(best?.textContent).toBe('900')
  })
})
