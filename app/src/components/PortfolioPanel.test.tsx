import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { parseExposure } from '../data/validate'
import { readFixtureJson } from '../test/fixtureFetch'
import { PortfolioPanel } from './PortfolioPanel'

const EXPOSURE = parseExposure(readFixtureJson('milton/exposure.json'), 'exposure.json')
const COUNTIES = {
  '99001': { name: 'Alpha', state: 'ZZ' },
  '99003': { name: 'Bravo', state: 'ZZ' },
  '99005': { name: 'Charlie', state: 'ZZ' },
  '99007': { name: 'Delta', state: 'ZZ' },
}

function renderPanel(hours: 24 | 48 | 72 = 72) {
  const onHoursChange = vi.fn()
  const onSelectCounty = vi.fn()
  render(
    <PortfolioPanel
      exposure={EXPOSURE}
      counties={COUNTIES}
      hours={hours}
      waitingPeriods={[24, 48, 72]}
      onHoursChange={onHoursChange}
      onSelectCounty={onSelectCounty}
      selectedFips={null}
    />,
  )
  return { onHoursChange, onSelectCounty }
}

describe('PortfolioPanel', () => {
  it('leads with expected policies without power at the waiting period', () => {
    renderPanel(72)

    // 72 h: 1,200 × [0.03, 0.12] + 400 × [0.09, 0.40] + 30 × [0.20, 0.35] = 78 to 314.5.
    const headline = screen.getByRole('heading', { name: /Expected policies without power at hour 72/ })
    expect(headline.textContent).toMatch(/196/)
    expect(headline.textContent).toMatch(/78–315/)
  })

  it("shows can't-see policies separately instead of counting them as zero", () => {
    renderPanel(72)

    expect(screen.getByTestId('unknown-policies').textContent).toMatch(/100 policies/)
  })

  it('switches the waiting period from the 24/48/72 h control', () => {
    const { onHoursChange } = renderPanel(72)

    fireEvent.click(screen.getByLabelText('24 h'))

    expect(onHoursChange).toHaveBeenCalledWith(24)
  })

  it('lists counties and selects one from the table', () => {
    const { onSelectCounty } = renderPanel(72)

    fireEvent.click(screen.getByRole('button', { name: /Alpha, ZZ/ }))

    expect(onSelectCounty).toHaveBeenCalledWith('99001')
  })
})
