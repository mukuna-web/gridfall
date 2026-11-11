/**
 * The % out color ramp, shared by the map, its legend and the tables.
 *
 * A cividis-like path (pale straw -> gray -> navy) whose lightness falls at
 * every step, so the value reads from lightness alone for every kind of
 * color vision, and it never borrows the signal red reserved for review
 * flags. More customers out = darker, like the lights going out.
 */

export interface RampStop {
  readonly at: number
  readonly color: string
}

export const RAMP: readonly RampStop[] = [
  { at: 0, color: '#ecdda0' },
  { at: 0.2, color: '#cdc596' },
  { at: 0.4, color: '#a3a285' },
  { at: 0.6, color: '#77807e' },
  { at: 0.8, color: '#4a5f78' },
  { at: 1, color: '#1d3557' },
]

type Rgb = readonly [number, number, number]

export function hexToRgb(hex: string): Rgb {
  const value = Number.parseInt(hex.replace('#', ''), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

function rgbToHex([r, g, b]: Rgb): string {
  return `#${[r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('')}`
}

/** WCAG relative luminance of a #rrggbb color. */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((c) => {
    const s = c / 255
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }) as unknown as Rgb
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/**
 * Ramp color for a share out; values outside 0..1 (EAGLE-I over-counts) clamp.
 * An unknown share (NaN) has no color: callers hatch it. Throwing here keeps
 * it from ever being painted with the 0% color by accident.
 */
export function colorForShare(share: number): string {
  if (!Number.isFinite(share)) throw new RangeError(`colorForShare needs a finite share, got ${share}; hatch unknowns instead`)
  const t = Math.min(1, Math.max(0, share))
  const upperIndex = RAMP.findIndex((stop) => stop.at >= t)
  const upper = RAMP[Math.max(upperIndex, 0)] ?? RAMP[RAMP.length - 1]
  const lower = RAMP[Math.max(upperIndex - 1, 0)] ?? upper
  if (!upper || !lower) return '#000000'
  if (upper === lower || upper.at === lower.at) return upper.color
  const f = (t - lower.at) / (upper.at - lower.at)
  const a = hexToRgb(lower.color)
  const b = hexToRgb(upper.color)
  return rgbToHex([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f])
}

/** CSS gradient for the legend bar, built from the same stops. */
export function rampGradientCss(direction = 'to right'): string {
  return `linear-gradient(${direction}, ${RAMP.map((s) => `${s.color} ${s.at * 100}%`).join(', ')})`
}

/** Flat [stop, color, stop, color, ...] list for a MapLibre interpolate expression. */
export function rampStops(): Array<number | string> {
  return RAMP.flatMap((s) => [s.at, s.color])
}
