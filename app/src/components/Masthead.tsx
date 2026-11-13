import { formatNightDate } from '../lib/dates'
import type { StormIndexEntry, StormMeta, StormRole } from '../types'

const ROLE_SHORT: Record<StormRole, string> = {
  main: 'scored leave-one-out',
  lockbox: 'held-out test',
  stress: 'stress test',
}

const ROLE_LONG: Record<StormRole, string> = {
  main: 'Training storm, scored leave-one-storm-out',
  lockbox: 'Held-out test storm: the model never saw it',
  stress: 'Stress test: snow and ice confuse brightness',
}

const SATELLITES: Readonly<Record<string, string>> = {
  VNP46A2: 'Suomi NPP (VNP46A2)',
  VJ146A2: 'NOAA-20 (VJ146A2)',
}

function stormTitle(storm: StormIndexEntry): string {
  if (/^(hurricane|tropical|winter|storm)\b/i.test(storm.name)) return storm.name
  return storm.role === 'stress' ? `Winter Storm ${storm.name}` : `Hurricane ${storm.name}`
}

interface MastheadProps {
  readonly storms: readonly StormIndexEntry[]
  readonly storm: StormIndexEntry
  readonly meta: StormMeta | null
  readonly onStormChange: (id: string) => void
}

/** Report masthead: what this is, which storm, and the storm picker. */
export function Masthead({ storms, storm, meta, onStormChange }: MastheadProps) {
  return (
    <header className="masthead">
      <div className="masthead__top">
        <p className="masthead__kicker label">Gridfall · Storm outage report</p>
        <label className="picker">
          <span className="label">Storm</span>
          <select className="select" value={storm.id} onChange={(e) => onStormChange(e.target.value)}>
            {storms.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} {s.landfall.slice(0, 4)} · {ROLE_SHORT[s.role]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <h1 className="masthead__title">{stormTitle(storm)}</h1>
      <p className="masthead__meta">
        <span>Landfall {formatNightDate(storm.landfall)}</span>
        <span>{ROLE_LONG[storm.role]}</span>
        <span>{SATELLITES[storm.satellite] ?? storm.satellite}</span>
        {meta ? <span>Exported {meta.generated.slice(0, 10)}</span> : null}
      </p>
      <p className="masthead__model">
        Estimates come from the storm-context model (wind band and days since landfall, adjusted by the night-light
        reading), which is secondary to the pre-registered night-light curve. The scorecard below grades both.
      </p>
    </header>
  )
}
