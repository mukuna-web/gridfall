import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { usePrefersReducedMotion } from '../hooks/usePrefersReducedMotion'
import { dayOffset, describeDay, formatNightDate } from '../lib/dates'
import { formatCount, formatCountRange } from '../lib/format'
import type { CountyIndex, NightTotals } from '../lib/nights'
import { buildCountyView, clearShareByNight, countyIndex, defaultNight, leadCounty, nightTotals } from '../lib/nights'
import type { UrlState } from '../lib/urlState'
import { serializeUrlState } from '../lib/urlState'
import type { IsoDate, StormData, WaitingPeriod } from '../types'
import { ClaimCheck } from './ClaimCheck'
import { CountyCard } from './CountyCard'
import { CountyPicker, OfficialToggle } from './MapControls'
import { MapErrorBoundary } from './MapErrorBoundary'
import { MapLegend } from './MapLegend'
import { NightTimeline } from './NightTimeline'
import { PanelHeader } from './PanelHeader'
import { PortfolioPanel } from './PortfolioPanel'
import { ScorecardTable } from './ScorecardTable'

// MapLibre is most of the JavaScript; load it in parallel with the report.
const StormMap = lazy(() => import('./StormMap'))

interface StormReportProps {
  readonly data: StormData
  /** View state from the URL; anything not valid for this storm is ignored. */
  readonly initial: UrlState
}

function startNight(data: StormData, initial: UrlState): IsoDate {
  if (initial.night && data.meta.nights.includes(initial.night)) return initial.night
  return defaultNight(data.meta) ?? ''
}

function startCounty(data: StormData, initial: UrlState, night: IsoDate): string | null {
  const known = (fips: string | undefined) => fips !== undefined && data.counties.features.some((f) => f.properties.fips === fips)
  if (known(initial.county)) return initial.county ?? null
  return leadCounty(data, night) ?? data.counties.features[0]?.properties.fips ?? null
}

/** Keeps the view shareable; history can be unavailable (sandboxed frames), and the view works without it. */
function replaceUrl(state: UrlState): void {
  try {
    const { pathname, hash } = window.location
    window.history.replaceState(null, '', `${pathname}${serializeUrlState(state)}${hash}`)
  } catch {
    // Not fatal: the URL just won't reflect the view.
  }
}

/** The opening sentence: what the satellite saw on this night, and what it could not. */
function Lede({ night, landfall, totals }: { night: IsoDate; landfall: IsoDate; totals: NightTotals }) {
  if (!night) return null
  const when = describeDay(dayOffset(night, landfall))
  return (
    <p className="lede">
      On the night of <strong>{formatNightDate(night)}</strong>, {when}, the satellite saw{' '}
      <strong className="num">
        {totals.seen} of {totals.total}
      </strong>{' '}
      counties clearly.{' '}
      {totals.customersOut ? (
        <>
          In those, an estimated{' '}
          <strong className="num">{formatCountRange(totals.customersOut.lo, totals.customersOut.hi)}</strong> customers were
          without power (80% range; point estimate{' '}
          <span className="num">{formatCount(totals.customersOut.est)}</span>).{' '}
        </>
      ) : (
        <>There is no customer total for this night. </>
      )}
      Counties it could not see are left out, never counted as zero.
    </p>
  )
}

/** The view a reader is on: night, county, waiting period and the official toggle. */
interface ReportView {
  readonly night: IsoDate
  readonly setNight: (night: IsoDate) => void
  readonly selectedFips: string | null
  readonly selectCounty: (fips: string) => void
  readonly showOfficial: boolean
  readonly setShowOfficial: (on: boolean) => void
  readonly hours: WaitingPeriod
  readonly setHours: (hours: WaitingPeriod) => void
}

/** Starts from the URL where it fits this storm, and mirrors every change back into it. */
function useReportView(data: StormData, initial: UrlState): ReportView {
  const { meta } = data
  const [night, setNight] = useState<IsoDate>(() => startNight(data, initial))
  const [selectedFips, selectCounty] = useState<string | null>(() => startCounty(data, initial, startNight(data, initial)))
  const [showOfficial, setShowOfficial] = useState(initial.official)
  const [hours, setHours] = useState<WaitingPeriod>(() =>
    initial.hours && meta.waiting_periods.includes(initial.hours) ? initial.hours : meta.default_waiting_period,
  )
  useEffect(() => {
    replaceUrl({ storm: meta.id, night: night || undefined, county: selectedFips ?? undefined, hours, official: showOfficial })
  }, [meta.id, night, selectedFips, hours, showOfficial])
  return { night, setNight, selectedFips, selectCounty, showOfficial, setShowOfficial, hours, setHours }
}

/** Panel 01: the map, its legend and county list, and the night timeline under it. */
function MapPanel({ data, view }: { readonly data: StormData; readonly view: ReportView }) {
  const { meta } = data
  const clearShare = useMemo(
    () => clearShareByNight(data.nights, meta.nights, data.counties.features.map((f) => f.properties.fips)),
    [data, meta.nights],
  )
  return (
    <section className="panel panel--map" id="map-panel" aria-labelledby="map-title">
      <PanelHeader index="01" id="map-title" title="Customers without power">
        <OfficialToggle checked={view.showOfficial} onChange={view.setShowOfficial} />
      </PanelHeader>
      <div className="map-frame">
        <MapErrorBoundary>
          <Suspense fallback={<p className="map-frame__loading">Loading map…</p>}>
            <StormMap data={data} night={view.night} showOfficial={view.showOfficial} selectedFips={view.selectedFips} onSelect={view.selectCounty} />
          </Suspense>
        </MapErrorBoundary>
      </div>
      <div className="map-foot">
        <MapLegend showOfficial={view.showOfficial} />
        <CountyPicker counties={data.counties} value={view.selectedFips} onChange={view.selectCounty} />
      </div>
      <NightTimeline nights={meta.nights} value={view.night} landfall={meta.landfall} clearShare={clearShare} onChange={view.setNight} />
    </section>
  )
}

/** Panels 02 and 03, the right-hand column: the county card and the portfolio. */
function SidePanels({ data, view, counties }: { readonly data: StormData; readonly view: ReportView; readonly counties: CountyIndex }) {
  const { selectedFips } = view
  const county = useMemo(() => (selectedFips ? buildCountyView(data, selectedFips) : null), [data, selectedFips])
  return (
    <div className="report__side">
      <section className="panel" id="county-panel" aria-labelledby="county-title">
        <PanelHeader index="02" id="county-title" title="County" />
        <CountyCard county={county} night={view.night} showOfficial={view.showOfficial} />
      </section>
      <section className="panel" aria-labelledby="portfolio-title">
        <PanelHeader index="03" id="portfolio-title" title="Portfolio" />
        <PortfolioPanel
          exposure={data.exposure}
          counties={counties}
          hours={view.hours}
          waitingPeriods={data.meta.waiting_periods}
          onHoursChange={view.setHours}
          onSelectCounty={view.selectCounty}
          selectedFips={selectedFips}
        />
      </section>
    </div>
  )
}

/** One storm's report: map and timeline, county card, portfolio, claim check, scorecard. */
export function StormReport({ data, initial }: StormReportProps) {
  const { meta } = data
  const view = useReportView(data, initial)
  const { night, selectCounty } = view
  const reducedMotion = usePrefersReducedMotion()
  const counties = useMemo(() => countyIndex(data), [data])
  const totals = useMemo(() => nightTotals(data, night), [data, night])

  const showOnMap = useCallback(
    (fips: string) => {
      selectCounty(fips)
      document.getElementById('map-panel')?.scrollIntoView?.({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
    },
    [reducedMotion, selectCounty],
  )

  return (
    <main className="report" id="main">
      <Lede night={night} landfall={meta.landfall} totals={totals} />
      <div className="report__grid">
        <MapPanel data={data} view={view} />
        <SidePanels data={data} view={view} counties={counties} />
        <section className="panel panel--claims" aria-labelledby="claims-title">
          <PanelHeader index="04" id="claims-title" title="Claim check" />
          <ClaimCheck
            stormId={meta.id}
            claims={data.claims}
            nights={data.nights}
            restoration={data.restoration}
            counties={counties}
            landfall={meta.landfall}
            showOfficial={view.showOfficial}
            onShowCounty={showOnMap}
          />
        </section>
        <section className="panel panel--score" aria-labelledby="score-title">
          <PanelHeader index="05" id="score-title" title="Scorecard" />
          <ScorecardTable scorecard={data.scorecard} role={meta.role} />
        </section>
      </div>
    </main>
  )
}
