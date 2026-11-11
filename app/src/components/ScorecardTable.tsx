import { formatCount, formatPct, isNumber } from '../lib/format'
import type { MethodName, MetricName, Scorecard, StormRole } from '../types'
import { METHOD_NAMES } from '../types'

const METHOD_LABEL: Record<MethodName, string> = {
  hybrid: 'Storm context + night lights (the map)',
  isotonic: 'Night lights only (pre-registered)',
  wind_timing: 'Storm context only (no satellite)',
  wind_only: 'Wind only',
  nothing: 'Nothing happened',
}

/** The methods this storm's file actually scored, in display order. */
function presentMethods(scorecard: Scorecard): readonly MethodName[] {
  return METHOD_NAMES.filter((name) => scorecard.methods[name] !== undefined)
}

type Better = 'lower' | 'higher' | 'closest' | 'none'

interface MetricRow {
  readonly key: MetricName
  readonly label: string
  readonly better: Better
  readonly format: (value: number | null) => string
}

const fixed = (digits: number, unit: string) => (value: number | null) =>
  isNumber(value) ? `${value.toFixed(digits)} ${unit}` : '—'

const ROWS: readonly MetricRow[] = [
  { key: 'mae_pp', label: 'Average county error', better: 'lower', format: fixed(1, 'pp') },
  { key: 'peak_total_est', label: 'Peak customers out', better: 'closest', format: formatCount },
  { key: 'catch_rate_50', label: 'Caught counties over 50% out', better: 'higher', format: formatPct },
  { key: 'false_alarm_50', label: 'False alarms at 50%', better: 'lower', format: formatPct },
  { key: 'restore_day_err', label: 'Restoration-day error', better: 'lower', format: fixed(1, 'days') },
  // Wind-only and nothing "measure" every county by construction, so no winner here.
  { key: 'measurable_share', label: 'Hit counties measurable', better: 'none', format: formatPct },
]

const ROLE_NOTE: Record<StormRole, string> = {
  main: 'Leave-one-storm-out: the curve was fit on the other main storms, never this one.',
  lockbox: 'Held-out test: this storm stayed locked until the pass bar was committed.',
  stress: 'Stress test (snow and ice), scored on its own. The EAGLE-I dropout constants were tuned partly on this storm.',
}

function winner(scorecard: Scorecard, row: MetricRow): MethodName | null {
  if (row.better === 'none') return null
  const official = scorecard.methods.isotonic.peak_total_official
  const candidates = presentMethods(scorecard).flatMap((name) => {
    const value = scorecard.methods[name]?.[row.key]
    if (!isNumber(value)) return []
    if (row.better === 'closest') return isNumber(official) ? [{ name, score: Math.abs(value - official) }] : []
    return [{ name, score: row.better === 'lower' ? value : -value }]
  })
  if (candidates.length < 2) return null
  const best = candidates.reduce((a, b) => (b.score < a.score ? b : a))
  return candidates.filter((c) => c.score === best.score).length === 1 ? best.name : null
}

/** How the estimate scored against EAGLE-I, beside the two simple guesses it must beat. */
export function ScorecardTable({ scorecard, role }: { readonly scorecard: Scorecard; readonly role: StormRole }) {
  const official = scorecard.methods.isotonic.peak_total_official
  return (
    <div className="scorecard">
      {/* The table scrolls sideways on narrow screens, so the wrapper is a focusable region. */}
      <div className="table-wrap" role="region" aria-label="Scorecard table" tabIndex={0}>
        <table className="data-table data-table--score">
          <caption className="scorecard__caption">
            Graded against EAGLE-I within ±{scorecard.window} minutes of the satellite pass. Bold marks the best method.
          </caption>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              {presentMethods(scorecard).map((name) => (
                <th key={name} scope="col" className="num">
                  {METHOD_LABEL[name]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => {
              const best = winner(scorecard, row)
              return (
                <tr key={row.key}>
                  <th scope="row">
                    {row.label}
                    {row.key === 'peak_total_est' && isNumber(official) ? (
                      <span className="scorecard__sub">official {formatCount(official)}</span>
                    ) : null}
                  </th>
                  {presentMethods(scorecard).map((name) => (
                    <td key={name} className={name === best ? 'num is-best' : 'num'}>
                      {row.format(scorecard.methods[name]?.[row.key] ?? null)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="scorecard__note">{ROLE_NOTE[role]}</p>
      {scorecard.note ? <p className="scorecard__note">{scorecard.note}</p> : null}
    </div>
  )
}
