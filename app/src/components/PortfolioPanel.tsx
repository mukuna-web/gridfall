import { useMemo, useState } from 'react'
import { colorForShare } from '../lib/color'
import { expectedPoliciesOut, exposureRows } from '../lib/exposure'
import type { ExposureRow, PoliciesOut } from '../lib/exposure'
import { formatCount, formatCountRange, formatRange, isNumber } from '../lib/format'
import type { CountyIndex } from '../lib/nights'
import { countyLabel } from '../lib/nights'
import type { ExposureByCounty, WaitingPeriod } from '../types'

interface PortfolioPanelProps {
  readonly exposure: ExposureByCounty
  readonly counties: CountyIndex
  readonly hours: WaitingPeriod
  readonly waitingPeriods: readonly WaitingPeriod[]
  readonly onHoursChange: (hours: WaitingPeriod) => void
  readonly onSelectCounty: (fips: string) => void
  readonly selectedFips: string | null
}

/** Rows shown before "show all": enough for the worst-hit counties. */
const COLLAPSED_ROWS = 8

function WaitingPeriodControl({
  hours,
  periods,
  onChange,
}: {
  hours: WaitingPeriod
  periods: readonly WaitingPeriod[]
  onChange: (hours: WaitingPeriod) => void
}) {
  return (
    <fieldset className="segmented">
      <legend className="label">Waiting period</legend>
      <div className="segmented__options">
        {periods.map((h) => (
          <label key={h} className="segmented__option">
            <input type="radio" name="waiting-period" value={h} checked={h === hours} onChange={() => onChange(h)} />
            <span>{h} h</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function CountyRow({
  row,
  label,
  selected,
  onSelect,
}: {
  row: ExposureRow
  label: string
  selected: boolean
  onSelect: (fips: string) => void
}) {
  return (
    <tr className={selected ? 'is-selected' : undefined}>
      <th scope="row">
        <button type="button" className="link-button" onClick={() => onSelect(row.fips)} aria-pressed={selected}>
          {label}
        </button>
      </th>
      <td className="num">{formatCount(row.policies)}</td>
      {row.seen ? (
        <>
          <td className="num">{formatCountRange(row.low, row.high)}</td>
          <td className="num">
            {isNumber(row.hiShare) ? (
              <span className="swatch" style={{ background: colorForShare(row.hiShare) }} aria-hidden="true" />
            ) : null}
            {formatRange(row.loShare, row.hiShare)}
          </td>
        </>
      ) : (
        <td className="cell--blind" colSpan={2}>
          <span className="swatch swatch--hatch" aria-hidden="true" />
          can't see
        </td>
      )}
    </tr>
  )
}

/** "Expected policies without power at hour 72: N (range)"; a dash, never 0, when no county is seen. */
function PortfolioHeadline({ hours, totals, anySeen }: { hours: WaitingPeriod; totals: PoliciesOut; anySeen: boolean }) {
  return (
    <h3 className="portfolio__headline">
      <span className="portfolio__lead">Expected policies without power at hour {hours}:</span>{' '}
      {anySeen ? (
        <>
          <strong className="figure figure--hero num">{formatCount((totals.low + totals.high) / 2)}</strong>{' '}
          <span className="portfolio__range num">({formatCountRange(totals.low, totals.high)})</span>
        </>
      ) : (
        <strong className="figure figure--hero">—</strong>
      )}
    </h3>
  )
}

interface CountyTableProps {
  readonly rows: readonly ExposureRow[]
  readonly counties: CountyIndex
  readonly hours: WaitingPeriod
  readonly selectedFips: string | null
  readonly onSelect: (fips: string) => void
}

/** The book by county, worst first, collapsed to the first few rows until asked. */
function CountyTable({ rows, counties, hours, selectedFips, onSelect }: CountyTableProps) {
  const [expanded, setExpanded] = useState(false)
  const book = rows.reduce((sum, r) => ({ home: sum.home + r.home, business: sum.business + r.business }), { home: 0, business: 0 })
  const shown = expanded ? rows : rows.slice(0, COLLAPSED_ROWS)
  return (
    <>
      {/* The table scrolls sideways on narrow screens, so the wrapper is a focusable region. */}
      <div className="table-wrap" role="region" aria-label="Portfolio by county" tabIndex={0}>
        <table className="data-table">
          <caption className="label">
            Book: {formatCount(book.home + book.business)} synthetic policies ({formatCount(book.home)} home,{' '}
            {formatCount(book.business)} business)
          </caption>
          <thead>
            <tr>
              <th scope="col">County</th>
              <th scope="col" className="num">
                Policies
              </th>
              <th scope="col" className="num">
                Out at {hours} h
              </th>
              <th scope="col" className="num">
                % out
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <CountyRow key={row.fips} row={row} label={countyLabel(counties, row.fips)} selected={row.fips === selectedFips} onSelect={onSelect} />
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > COLLAPSED_ROWS ? (
        <button type="button" className="text-button" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
          {expanded ? 'Show fewer counties' : `Show all ${rows.length} counties`}
        </button>
      ) : null}
    </>
  )
}

/** Synthetic book: expected policies without power past the waiting period. */
export function PortfolioPanel({
  exposure,
  counties,
  hours,
  waitingPeriods,
  onHoursChange,
  onSelectCounty,
  selectedFips,
}: PortfolioPanelProps) {
  const totals = useMemo(() => expectedPoliciesOut(exposure, hours), [exposure, hours])
  const rows = useMemo(() => exposureRows(exposure, hours), [exposure, hours])
  const blindCount = rows.filter((r) => !r.seen).length

  return (
    <div className="portfolio">
      <PortfolioHeadline hours={hours} totals={totals} anySeen={blindCount < rows.length} />
      <p className="portfolio__explain">
        Policies whose county was still out at hour {hours} after landfall, so a {hours}-hour waiting period has passed. The
        range runs between the clear nights on either side of hour {hours}.
      </p>
      <WaitingPeriodControl hours={hours} periods={waitingPeriods} onChange={onHoursChange} />
      <p className="portfolio__unknown" data-testid="unknown-policies">
        <span className="swatch swatch--hatch" aria-hidden="true" />
        {formatCount(totals.unknownPolicies)} policies in {blindCount} {blindCount === 1 ? 'county' : 'counties'} the
        satellite can't see at hour {hours}: unknown, not counted as zero.
      </p>
      <CountyTable rows={rows} counties={counties} hours={hours} selectedFips={selectedFips} onSelect={onSelectCounty} />
    </div>
  )
}
