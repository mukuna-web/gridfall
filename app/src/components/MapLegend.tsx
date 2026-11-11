import { rampGradientCss } from '../lib/color'

const TICKS = [0, 25, 50, 75, 100]

/** Ramp, hatch keys and (when on) the official-dot key, drawn from the map's own stops. */
export function MapLegend({ showOfficial }: { readonly showOfficial: boolean }) {
  return (
    <div className="legend">
      <div className="legend__ramp">
        <span className="label">Estimated customers out</span>
        <span className="legend__bar" style={{ background: rampGradientCss() }} aria-hidden="true" />
        <span className="legend__ticks num" aria-hidden="true">
          {TICKS.map((t) => (
            <span key={t}>{t}%</span>
          ))}
        </span>
      </div>
      <ul className="legend__keys">
        <li>
          <span className="swatch swatch--hatch" aria-hidden="true" /> can't see (clouds)
        </li>
        <li>
          <span className="swatch swatch--dots" aria-hidden="true" /> not measurable (too dark)
        </li>
        {showOfficial ? (
          <li>
            <span className="swatch swatch--official" aria-hidden="true" /> official, same scale
          </li>
        ) : null}
      </ul>
    </div>
  )
}
