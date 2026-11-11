import type { ReactNode } from 'react'
import { dayOffset, describeDay, formatNightDate } from '../lib/dates'
import { formatCount, formatCountRange, formatDay, formatDaysInterval, formatPct, formatRange, isNumber } from '../lib/format'
import type { CountyView } from '../lib/nights'
import { findNight, usableEstimate, visibilitySummary } from '../lib/nights'
import type { IsoDate, NightRecord, NightStatus, RestorationRecord } from '../types'

interface CountyCardProps {
  readonly county: CountyView | null
  readonly night: IsoDate
  /** Official (EAGLE-I) numbers beside the estimate; off unless the toggle is on. */
  readonly showOfficial?: boolean
}

/** Why there is no figure tonight: the two satellite statuses, or a night with no estimate written at all. */
type BlindKind = Exclude<NightStatus, 'ok'> | 'no_estimate'

// Words only, no digits: a reader scanning the card for the figure must not
// find "0%" in the explanation and take it for the estimate.
const BLIND_COPY: Record<BlindKind, { word: string; why: string; tonight: string }> = {
  cant_see: {
    word: "can't see",
    why: "Clouds or haze hid too much of this county's normal light. Unknown, not zero.",
    tonight: 'clouds or haze hid more than half of its normal light',
  },
  not_measurable: {
    word: 'not measurable',
    why: 'Too little light here on normal nights to read a change (a dark, rural county). Unknown, not zero.',
    tonight: 'too dark on normal nights to measure',
  },
  no_estimate: {
    word: 'no estimate',
    why: 'No estimate was exported for this county on this night. Unknown, not zero.',
    tonight: 'no estimate was exported',
  },
}

/** Null when the satellite saw the county clearly and an estimate was written; otherwise why not. */
function blindKind(record: NightRecord | undefined): BlindKind | null {
  if (record?.status === 'cant_see' || record?.status === 'not_measurable') return record.status
  return usableEstimate(record) === null ? 'no_estimate' : null
}

function Fact({ label, children, note, wide = false }: { label: string; children: ReactNode; note?: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'fact fact--wide' : 'fact'}>
      <dt className="label">{label}</dt>
      <dd className="fact__value">{children}</dd>
      {note ? <dd className="fact__note">{note}</dd> : null}
    </div>
  )
}

function scaled(share: number | null, base: number | null): number | null {
  return share === null || base === null ? null : share * base
}

function Headline({ record, blind }: { record: NightRecord | undefined; blind: BlindKind | null }) {
  if (blind !== null || !record) {
    const copy = BLIND_COPY[blind ?? 'no_estimate']
    return (
      <div className="county-card__headline county-card__headline--blind" data-testid="county-headline">
        <span className="figure figure--status">{copy.word}</span>
        <span className="county-card__why">{copy.why}</span>
      </div>
    )
  }
  return (
    <div className="county-card__headline" data-testid="county-headline">
      <span className="figure figure--xl num">{formatRange(record.lo, record.hi)}</span>
      <span className="county-card__why">
        estimated out (80% range) · point estimate <span className="num">{formatPct(record.est)}</span>
      </span>
    </div>
  )
}

function OfficialFact({ record, customers }: { record: NightRecord | undefined; customers: number | null }) {
  const official = record && isNumber(record.official) ? record.official : null
  if (official === null) {
    // Two different unknowns: EAGLE-I has no customer count for the county
    // (so no share on any night), or it has no usable run for this night.
    return (
      <Fact label="Official (EAGLE-I)" wide>
        {customers === null ? 'No EAGLE-I customer count for this county, so no official share' : 'No usable EAGLE-I run for this night'}
      </Fact>
    )
  }
  const out = scaled(official, customers)
  return (
    <Fact
      label="Official (EAGLE-I)"
      wide
      note={official > 1 ? 'Above 100%: an EAGLE-I over-count, shown as reported.' : null}
    >
      <span className="num">{formatPct(official)}</span>
      {out !== null ? <span className="fact__aside"> · {formatCount(out)} customers</span> : null}
    </Fact>
  )
}

function visibilityText(county: CountyView, blind: BlindKind | null): string {
  const v = visibilitySummary(county.nights)
  const tonight = blind === null ? 'seen clearly' : BLIND_COPY[blind].tonight
  return `Seen clearly on ${v.ok} of ${v.total} nights; can't see on ${v.cantSee}; not measurable on ${v.notMeasurable}. Tonight: ${tonight}.`
}

/**
 * The estimate and its range, but only from a night the satellite saw
 * clearly: a stray lo/hi on a can't-see night must not read as customers out.
 */
function usableRange(record: NightRecord | undefined): { est: number | null; lo: number | null; hi: number | null } {
  const est = usableEstimate(record)
  if (est === null || !record) return { est: null, lo: null, hi: null }
  return { est, lo: isNumber(record.lo) ? record.lo : est, hi: isNumber(record.hi) ? record.hi : est }
}

function DaysDarkFact({ restoration, showOfficial }: { restoration: RestorationRecord | null; showOfficial: boolean }) {
  const official = showOfficial ? (
    <span>
      {restoration && isNumber(restoration.official_day)
        ? `Official: day ${formatDay(restoration.official_day)}`
        : 'Official: no restoration day'}
    </span>
  ) : null
  return (
    <Fact label="Days dark (back to 10% out or less)" wide note={official}>
      {formatDaysInterval(restoration?.est_lo ?? null, restoration?.est_hi ?? null)}
    </Fact>
  )
}

function CountyFacts({ county, record, showOfficial }: { county: CountyView; record: NightRecord | undefined; showOfficial: boolean }) {
  const { est, lo, hi } = usableRange(record)
  const range =
    county.customers === null ? 'No customer count for this county.' : (
      <span className="num">{formatCountRange(scaled(lo, county.customers), scaled(hi, county.customers))}</span>
    )
  return (
    <dl className="facts">
      <Fact label="Customers out" note={range}>
        <span className="num">{formatCount(scaled(est, county.customers))}</span>
      </Fact>
      <Fact label="Homes out (approximate)" note="estimate × housing units">
        {est === null ? (
          <span className="num">{formatCount(null)}</span>
        ) : (
          <>
            <span className="fact__approx" aria-hidden="true">≈</span>
            <span className="num">{formatCount(est * county.housingUnits)}</span>
          </>
        )}
      </Fact>
      {showOfficial ? <OfficialFact record={record} customers={county.customers} /> : null}
      <DaysDarkFact restoration={county.restoration} showOfficial={showOfficial} />
    </dl>
  )
}

/** The selected county on the selected night: estimate, range, counts, official, days dark. */
export function CountyCard({ county, night, showOfficial = false }: CountyCardProps) {
  if (!county) {
    return <p className="empty-note">Select a county on the map, in the county list or in the portfolio table.</p>
  }
  const record = findNight(county.nights, night)
  const blind = blindKind(record)
  const titleId = `county-${county.fips}-title`

  return (
    <article className="county-card" aria-labelledby={titleId}>
      <header className="county-card__head">
        <h3 className="county-card__title" id={titleId}>
          {county.name}, {county.state}
        </h3>
        <span className="label">FIPS {county.fips}</span>
      </header>
      <p className="county-card__night">
        Night of {formatNightDate(night)}, {describeDay(dayOffset(night, county.landfall))}
      </p>
      <Headline record={record} blind={blind} />
      <CountyFacts county={county} record={record} showOfficial={showOfficial} />
      <p className="county-card__visibility">{visibilityText(county, blind)}</p>
    </article>
  )
}
