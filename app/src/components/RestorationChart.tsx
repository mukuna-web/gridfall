import { dayOffset } from '../lib/dates'
import { formatDay, isNumber } from '../lib/format'
import { displayStatus, usableEstimate } from '../lib/nights'
import { useElementWidth } from '../hooks/useElementWidth'
import type { IsoDate, NightRecord, RestorationRecord } from '../types'
import type { Verdict } from '../lib/claims'

interface RestorationChartProps {
  readonly title: string
  readonly nights: readonly NightRecord[]
  readonly landfall: IsoDate
  readonly claimedDays: number
  readonly verdict: Verdict
  /** Highest hi after landfall; the 90%-restored line sits at a tenth of it. */
  readonly peakHi: number | null
  readonly restoration: RestorationRecord | null
  readonly showOfficial: boolean
}

const HEIGHT = 230
const PAD = { top: 26, right: 14, bottom: 40, left: 40 }
const Y_TICKS = [0, 0.25, 0.5, 0.75, 1]
const CLAIM_OVERHANG_DAYS = 3

interface Point {
  readonly day: number
  readonly est: number
  readonly lo: number
  readonly hi: number
}

/** Day and share to pixels, plus the sizes every layer needs. */
interface Scale {
  readonly minDay: number
  readonly maxDay: number
  readonly plotW: number
  readonly plotH: number
  /** Width of one night's hatched column. */
  readonly column: number
  readonly x: (day: number) => number
  readonly y: (share: number) => number
}

function chartScale(days: readonly number[], claimedDays: number, width: number): Scale {
  const lastDay = Math.max(1, ...days)
  const minDay = Math.min(0, ...days)
  // A very long claim would squash the curve, so the axis stops a few days
  // past the data and the claim marker pins to the edge with an arrow.
  const maxDay = Math.max(lastDay, Math.min(claimedDays, lastDay + CLAIM_OVERHANG_DAYS))
  const plotW = Math.max(120, width - PAD.left - PAD.right)
  const plotH = HEIGHT - PAD.top - PAD.bottom
  return {
    minDay,
    maxDay,
    plotW,
    plotH,
    column: Math.max(3, plotW / Math.max(1, maxDay - minDay) - 2),
    x: (day) => PAD.left + ((day - minDay) / (maxDay - minDay)) * plotW,
    y: (share) => PAD.top + (1 - Math.min(1.05, Math.max(0, share))) * plotH,
  }
}

function clearPoints(nights: readonly NightRecord[], landfall: IsoDate): Point[] {
  return nights
    .map((n) => {
      const est = usableEstimate(n)
      if (est === null) return null
      return { day: dayOffset(n.night, landfall), est, lo: isNumber(n.lo) ? n.lo : est, hi: isNumber(n.hi) ? n.hi : est }
    })
    .filter((p): p is Point => p !== null)
    .sort((a, b) => a.day - b.day)
}

function dayTicks(min: number, max: number, width: number): number[] {
  const span = Math.max(1, max - min)
  const step = [1, 2, 3, 5, 7, 10].find((s) => (span / s) * 34 <= width) ?? 14
  const first = Math.ceil(min / step) * step
  return Array.from({ length: Math.floor((max - first) / step) + 1 }, (_, i) => first + i * step)
}

function YGrid({ scale }: { scale: Scale }) {
  return Y_TICKS.map((t) => (
    <g key={t}>
      <line x1={PAD.left} x2={PAD.left + scale.plotW} y1={scale.y(t)} y2={scale.y(t)} className="chart__grid" />
      <text x={PAD.left - 6} y={scale.y(t) + 3} className="chart__tick" textAnchor="end">
        {Math.round(t * 100)}%
      </text>
    </g>
  ))
}

/** Hatched columns on nights the satellite couldn't see: a gap, never a zero. */
function BlindColumns({ nights, landfall, scale }: { nights: readonly NightRecord[]; landfall: IsoDate; scale: Scale }) {
  return nights.map((n) => {
    const status = displayStatus(n)
    if (status === 'ok') return null
    const cx = scale.x(dayOffset(n.night, landfall))
    return (
      <rect key={n.night} x={cx - scale.column / 2} y={PAD.top} width={scale.column} height={scale.plotH} fill="url(#chart-hatch)" className={`chart__blind chart__blind--${status}`}>
        <title>{status === 'cant_see' ? "can't see" : 'not measurable'}</title>
      </rect>
    )
  })
}

function DayAxis({ scale }: { scale: Scale }) {
  const { x, plotW, plotH } = scale
  return (
    <>
      {dayTicks(scale.minDay, scale.maxDay, plotW).map((d) => (
        <text key={d} x={x(d)} y={PAD.top + plotH + 16} className="chart__tick" textAnchor="middle">
          {d}
        </text>
      ))}
      <text x={PAD.left + plotW} y={HEIGHT - 6} className="chart__axis-label" textAnchor="end">
        days after landfall
      </text>
      <line x1={x(0)} x2={x(0)} y1={PAD.top} y2={PAD.top + plotH} className="chart__landfall" />
    </>
  )
}

/** The range band, the estimate line and a dot per clear night. */
function EstimateMarks({ points, scale }: { points: readonly Point[]; scale: Scale }) {
  const { x, y } = scale
  const band = points.length > 1 ? [...points.map((p) => `${x(p.day)},${y(p.hi)}`), ...[...points].reverse().map((p) => `${x(p.day)},${y(p.lo)}`)].join(' ') : ''
  const line = points.map((p) => `${x(p.day)},${y(p.est)}`).join(' ')
  return (
    <>
      {band ? <polygon points={band} className="chart__band" /> : null}
      {line ? <polyline points={line} className="chart__line" /> : null}
      {points.map((p) => (
        <circle key={p.day} cx={x(p.day)} cy={y(p.est)} r={2.6} className="chart__dot" />
      ))}
    </>
  )
}

function OfficialMarks({ nights, landfall, scale }: { nights: readonly NightRecord[]; landfall: IsoDate; scale: Scale }) {
  return nights
    .filter((n) => isNumber(n.official))
    .map((n) => (
      <rect key={`o-${n.night}`} x={scale.x(dayOffset(n.night, landfall)) - 3} y={scale.y(n.official as number) - 3} width={6} height={6} className="chart__official" />
    ))
}

/** The 90%-restored line the verdict uses and the estimated restoration interval under the axis. */
function RestorationMarks({ peakHi, restoration, scale }: { peakHi: number | null; restoration: RestorationRecord | null; scale: Scale }) {
  const { x, y, plotW, plotH } = scale
  const threshold = peakHi && peakHi > 0 ? peakHi * 0.1 : null
  return (
    <>
      {threshold !== null ? (
        <g>
          <line x1={PAD.left} x2={PAD.left + plotW} y1={y(threshold)} y2={y(threshold)} className="chart__threshold" />
          <text x={PAD.left + plotW} y={y(threshold) - 5} className="chart__note" textAnchor="end">
            90% of peak restored (high end)
          </text>
        </g>
      ) : null}
      {restoration && isNumber(restoration.est_lo) && isNumber(restoration.est_hi) ? (
        <line x1={x(restoration.est_lo)} x2={x(restoration.est_hi)} y1={PAD.top + plotH + 3} y2={PAD.top + plotH + 3} className="chart__restore" />
      ) : null}
    </>
  )
}

function ClaimMarker({ claimedDays, verdict, scale }: { claimedDays: number; verdict: Verdict; scale: Scale }) {
  const claimX = scale.x(Math.min(claimedDays, scale.maxDay))
  return (
    <>
      <line x1={claimX} x2={claimX} y1={PAD.top - 4} y2={PAD.top + scale.plotH} className={`chart__claim chart__claim--${verdict}`} />
      <text x={claimX} y={PAD.top - 10} className={`chart__claim-label chart__claim-label--${verdict}`} textAnchor={claimX > PAD.left + scale.plotW * 0.7 ? 'end' : 'start'}>
        claimed {formatDay(claimedDays)} days{claimedDays > scale.maxDay ? ' →' : ''}
      </text>
    </>
  )
}

/**
 * The county's estimated % out night by night: a band for the range, a line
 * for the estimate, hatched columns where the satellite couldn't see, the
 * 90%-restored line the verdict uses, and the claim's last day.
 */
export function RestorationChart(props: RestorationChartProps) {
  const { title, nights, landfall, claimedDays, verdict, peakHi, restoration, showOfficial } = props
  const [ref, width] = useElementWidth<HTMLDivElement>(560)
  const scale = chartScale(
    nights.map((n) => dayOffset(n.night, landfall)),
    claimedDays,
    width,
  )
  const summary = `${title}. Estimated share of customers out by night after landfall, with a claim of ${formatDay(claimedDays)} days marked.`

  return (
    <div className="chart" ref={ref}>
      <svg className="chart__svg" width={width} height={HEIGHT} role="img" aria-label={summary}>
        <defs>
          <pattern id="chart-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" className="chart__hatch-line" />
          </pattern>
        </defs>
        <YGrid scale={scale} />
        <BlindColumns nights={nights} landfall={landfall} scale={scale} />
        <DayAxis scale={scale} />
        <EstimateMarks points={clearPoints(nights, landfall)} scale={scale} />
        {showOfficial ? <OfficialMarks nights={nights} landfall={landfall} scale={scale} /> : null}
        <RestorationMarks peakHi={peakHi} restoration={restoration} scale={scale} />
        <ClaimMarker claimedDays={claimedDays} verdict={verdict} scale={scale} />
      </svg>
    </div>
  )
}
