/**
 * Raw RGBA hatch tiles for MapLibre's fill-pattern.
 *
 * Built from arithmetic rather than a canvas so they work in any browser
 * (and in tests) and stay crisp: tiles are drawn at 2x and registered with
 * pixelRatio 2. Diagonal lines mean "can't see" (clouds); dots mean "not
 * measurable" (too dark on normal nights to read a change).
 */
import { hexToRgb } from './color'

export type HatchKind = 'cant_see' | 'not_measurable'

export interface PatternImage {
  readonly width: number
  readonly height: number
  readonly data: Uint8Array
}

/** Tile edge in device pixels (8 CSS px at pixelRatio 2). */
const TILE = 16
const LINE = 2
const DOT_RADIUS = 2.2

function inkAt(kind: HatchKind, x: number, y: number): boolean {
  if (kind === 'cant_see') return (x + y) % TILE < LINE
  const dx = x + 0.5 - TILE / 2
  const dy = y + 0.5 - TILE / 2
  return dx * dx + dy * dy <= DOT_RADIUS * DOT_RADIUS
}

export function hatchPattern(kind: HatchKind, ink: string, paper: string, inkAlpha = 0.62): PatternImage {
  const inkRgb = hexToRgb(ink)
  const paperRgb = hexToRgb(paper)
  const data = new Uint8Array(TILE * TILE * 4)
  for (let y = 0; y < TILE; y += 1) {
    for (let x = 0; x < TILE; x += 1) {
      const mix = inkAt(kind, x, y) ? inkAlpha : 0
      const offset = (y * TILE + x) * 4
      for (let c = 0; c < 3; c += 1) {
        data[offset + c] = Math.round((paperRgb[c] ?? 0) * (1 - mix) + (inkRgb[c] ?? 0) * mix)
      }
      data[offset + 3] = 255
    }
  }
  return { width: TILE, height: TILE, data }
}
