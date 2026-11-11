import type { CSSProperties, KeyboardEvent } from 'react'
import { dayOffset, describeDay, formatNightDate } from '../lib/dates'
import { sliderIndexAfterKey } from '../lib/slider'
import type { IsoDate } from '../types'

interface NightTimelineProps {
  readonly nights: readonly IsoDate[]
  readonly value: IsoDate
  readonly landfall: IsoDate
  /** Share of counties seen clearly on each night, same order as `nights`. */
  readonly clearShare: readonly number[]
  readonly onChange: (night: IsoDate) => void
}

/**
 * Where the landfall marker sits on the strip (0..1): at its own night when
 * it has one, otherwise at its place by date between the first and last nights.
 */
function landfallPosition(nights: readonly IsoDate[], landfall: IsoDate): number {
  const landfallIndex = nights.indexOf(landfall)
  if (landfallIndex >= 0 && nights.length > 1) return landfallIndex / (nights.length - 1)
  const firstDay = dayOffset(nights[0] ?? landfall, landfall)
  const lastDay = dayOffset(nights[nights.length - 1] ?? landfall, landfall)
  return lastDay > firstDay ? Math.min(1, Math.max(0, -firstDay / (lastDay - firstDay))) : 0
}

interface StripProps {
  readonly nights: readonly IsoDate[]
  readonly index: number
  readonly landfall: IsoDate
  readonly clearShare: readonly number[]
  readonly onChange: (night: IsoDate) => void
}

/** One bar per night, as tall as the share of counties seen clearly; a mouse shortcut beside the slider. */
function CloudStrip({ nights, index, landfall, clearShare, onChange }: StripProps) {
  const span = Math.max(1, nights.length - 1)
  return (
    <div className="timeline__strip" aria-hidden="true" style={{ '--count': nights.length } as CSSProperties}>
      <span className="timeline__landfall" style={{ '--pos': landfallPosition(nights, landfall) } as CSSProperties}>
        landfall
      </span>
      {nights.map((n, i) => (
        <span
          key={n}
          className={['timeline__bar', i === index ? 'is-current' : '', n < landfall ? 'is-before' : ''].join(' ').trim()}
          style={{ '--clear': clearShare[i] ?? 0, '--pos': nights.length > 1 ? i / span : 0.5 } as CSSProperties}
          title={`${formatNightDate(n, 'short')}: ${Math.round((clearShare[i] ?? 0) * 100)}% seen clearly`}
          onClick={() => onChange(n)}
        />
      ))}
    </div>
  )
}

/**
 * Previous / slider / next. Arrow keys and Home/End are stepped here, with
 * the default prevented so the browser does not step a second time; keys
 * this leaves alone (Page Up/Down, Tab) keep their native behaviour.
 */
function NightStepper({ count, index, valueText, go }: { count: number; index: number; valueText: string; go: (i: number) => void }) {
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const next = sliderIndexAfterKey(event.key, index, count)
    if (next === null) return
    event.preventDefault()
    go(next)
  }
  return (
    <div className="timeline__controls">
      <button type="button" className="icon-button" onClick={() => go(index - 1)} disabled={index === 0} aria-label="Previous night">
        ‹
      </button>
      <input
        className="timeline__range"
        type="range"
        min={0}
        max={count - 1}
        step={1}
        value={index}
        aria-label="Night"
        aria-valuetext={valueText}
        onChange={(e) => go(Number(e.target.value))}
        onKeyDown={onKeyDown}
      />
      <button type="button" className="icon-button" onClick={() => go(index + 1)} disabled={index === count - 1} aria-label="Next night">
        ›
      </button>
    </div>
  )
}

/**
 * The night slider under the map. A native range input with its own
 * arrow-key and Home/End handling, so it steps the same in every browser;
 * the strip above it shows how much of the storm the satellite could see
 * each night.
 */
export function NightTimeline({ nights, value, landfall, clearShare, onChange }: NightTimelineProps) {
  if (nights.length === 0) return <p className="empty-note">This export has no nights to show.</p>
  const index = Math.max(0, nights.indexOf(value))
  const day = dayOffset(value, landfall)
  const seen = `${Math.round((clearShare[index] ?? 0) * 100)}% of counties seen clearly`
  const go = (i: number) => {
    const next = nights[Math.min(nights.length - 1, Math.max(0, i))]
    if (next) onChange(next)
  }

  return (
    <div className="timeline">
      <div className="timeline__readout" aria-live="polite">
        <span className="label">Night</span>
        <span className="timeline__date num">{formatNightDate(value)}</span>
        <span className="timeline__day">
          {describeDay(day)} · {seen}
        </span>
      </div>
      <CloudStrip nights={nights} index={index} landfall={landfall} clearShare={clearShare} onChange={onChange} />
      <NightStepper count={nights.length} index={index} valueText={`${formatNightDate(value)}, ${describeDay(day)}, ${seen}`} go={go} />
      <p className="timeline__key">
        <span>{formatNightDate(nights[0] ?? value, 'short')}</span>
        <span>Bar height: share of counties seen clearly. Arrow keys, Home and End move the night.</span>
        <span>{formatNightDate(nights[nights.length - 1] ?? value, 'short')}</span>
      </p>
    </div>
  )
}
