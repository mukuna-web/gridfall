import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { parseClaims, parseNights, parseRestoration } from '../data/validate'
import { createFlagStore, FLAGS_KEY } from '../lib/flags'
import { readFixtureJson } from '../test/fixtureFetch'
import type { Claim } from '../types'
import { ClaimCheck } from './ClaimCheck'

// A fake lockbox id (test plan §1): the flag store only needs a storm key, and no
// test should carry a real locked storm's id.
const STORM = 'lock2099'
const CLAIMS = parseClaims(readFixtureJson('milton/claims.json'), 'claims.json')
const NIGHTS = parseNights(readFixtureJson('milton/nights.json'), 'nights.json')
const RESTORATION = parseRestoration(readFixtureJson('milton/restoration.json'), 'restoration.json')
const COUNTIES = {
  '99001': { name: 'Alpha', state: 'ZZ' },
  '99003': { name: 'Bravo', state: 'ZZ' },
  '99005': { name: 'Charlie', state: 'ZZ' },
  '99007': { name: 'Delta', state: 'ZZ' },
}

function renderCheck(claims: readonly Claim[] = CLAIMS, injectStore = true) {
  const onShowCounty = vi.fn()
  render(
    <ClaimCheck
      stormId={STORM}
      claims={claims}
      nights={NIGHTS}
      restoration={RESTORATION}
      counties={COUNTIES}
      landfall="2024-10-09"
      showOfficial={false}
      flagStore={injectStore ? createFlagStore(() => window.localStorage, STORM) : undefined}
      onShowCounty={onShowCounty}
    />,
  )
  return { onShowCounty }
}

const stored = () => JSON.parse(window.localStorage.getItem(FLAGS_KEY) ?? 'null') as unknown

describe('ClaimCheck', () => {
  it('opens on a claim that needs review and words it without blame', () => {
    renderCheck()

    // CLM-0001: 6 days in Alpha, where the high end fell from 0.90 to 0.08 by day 4.
    expect(screen.getByTestId('claim-verdict').textContent).toBe('longer than 91% of the county: review')
    expect(document.body.textContent).not.toMatch(/fraud/i)
  })

  it('says fits for a claim inside the curve', () => {
    renderCheck()

    fireEvent.change(screen.getByLabelText('Claim'), { target: { value: 'CLM-0002' } })

    expect(screen.getByTestId('claim-verdict').textContent).toBe('fits')
  })

  it('stays neutral when the satellite could not measure the county', () => {
    renderCheck()

    fireEvent.change(screen.getByLabelText('Claim'), { target: { value: 'CLM-0003' } })

    expect(screen.getByTestId('claim-verdict').textContent).toBe('fits')
    expect(screen.getByText(/not enough clear nights/i)).toBeTruthy()
  })

  it('flags a claim for review, under this storm, and shows the flagged state', () => {
    renderCheck()

    fireEvent.click(screen.getByRole('button', { name: 'Flag for review' }))

    expect(screen.getByText('Flagged for review')).toBeTruthy()
    expect(screen.getByText(/1 flagged/)).toBeTruthy()
    expect(stored()).toEqual({ [STORM]: ['CLM-0001'] })
  })

  it("uses the browser's per-storm store when none is injected", () => {
    renderCheck(CLAIMS, false)

    fireEvent.click(screen.getByRole('button', { name: 'Flag for review' }))

    expect(stored()).toEqual({ [STORM]: ['CLM-0001'] })
  })

  it('draws the claim against the county restoration curve', () => {
    renderCheck()

    expect(screen.getByRole('img', { name: /restoration curve for Alpha, ZZ/i })).toBeTruthy()
  })

  it('shows the claim county on the map on request', () => {
    const { onShowCounty } = renderCheck()

    // The visible "Show on map" stays inside the accessible name (WCAG 2.5.3, label in name).
    fireEvent.click(screen.getByRole('button', { name: /show on map: Alpha, ZZ/i }))

    expect(onShowCounty).toHaveBeenCalledWith('99001')
  })

  it('disables "Show on map" for a claim whose county is not in this storm', () => {
    const stray: Claim = { claim_id: 'CLM-0009', policy_id: 'P-000999', fips: '99099', claimed_days_out: 3 }
    const { onShowCounty } = renderCheck([stray])

    const button = screen.getByRole('button', { name: /show on map: 99099/i })
    fireEvent.click(button)

    expect(button).toHaveProperty('disabled', true)
    expect(onShowCounty).not.toHaveBeenCalled()
    expect(screen.getByTestId('claim-verdict').textContent).toBe('fits')
  })

  it('offers nothing to pick or flag when the storm has no claims', () => {
    renderCheck([])

    expect(screen.getByText(/no synthetic claims/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /flag for review/i })).toBeNull()
    expect(screen.queryByLabelText('Claim')).toBeNull()
  })
})
