import { describe, expect, it } from 'vitest'
import { deltaE2000Rgb } from '../test/deltaE'
import type { Rgb } from '../test/deltaE'
import { hexToRgb, RAMP, relativeLuminance } from './color'
import type { HatchKind, PatternImage } from './patterns'
import { hatchPattern } from './patterns'

const INK = '#1b1a17'
const PAPER = '#f4efe4'
const TILE = 16
const KINDS: readonly HatchKind[] = ['cant_see', 'not_measurable']

function pixel(tile: PatternImage, x: number, y: number): Rgb {
  const offset = (y * tile.width + x) * 4
  return [tile.data[offset] ?? -1, tile.data[offset + 1] ?? -1, tile.data[offset + 2] ?? -1]
}

function isInk(tile: PatternImage, x: number, y: number): boolean {
  const paper = hexToRgb(PAPER)
  return pixel(tile, x, y).some((channel, i) => channel !== paper[i])
}

function inkedPixels(tile: PatternImage): Array<[number, number]> {
  const inked: Array<[number, number]> = []
  for (let y = 0; y < tile.height; y += 1) for (let x = 0; x < tile.width; x += 1) if (isInk(tile, x, y)) inked.push([x, y])
  return inked
}

function meanColor(tile: PatternImage): Rgb {
  const sum = [0, 0, 0]
  for (let y = 0; y < tile.height; y += 1) {
    for (let x = 0; x < tile.width; x += 1) pixel(tile, x, y).forEach((channel, i) => (sum[i] = (sum[i] ?? 0) + channel))
  }
  const n = tile.width * tile.height
  return [(sum[0] ?? 0) / n, (sum[1] ?? 0) / n, (sum[2] ?? 0) / n]
}

function toHex([r, g, b]: Rgb): string {
  return `#${[r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('')}`
}

/** WCAG contrast ratio between two #rrggbb colours. */
function contrast(a: string, b: string): number {
  const [light, dark] = [relativeLuminance(a), relativeLuminance(b)].sort((p, q) => q - p) as [number, number]
  return (light + 0.05) / (dark + 0.05)
}

describe('hatchPattern', () => {
  it('draws 16 × 16 fully opaque RGBA tiles', () => {
    for (const kind of KINDS) {
      const tile = hatchPattern(kind, INK, PAPER)

      expect(tile.width).toBe(TILE)
      expect(tile.height).toBe(TILE)
      expect(tile.data.length).toBe(TILE * TILE * 4)
      for (let i = 3; i < tile.data.length; i += 4) expect(tile.data[i]).toBe(255)
    }
  })

  it("puts can't-see ink exactly where (x + y) % 16 < 2", () => {
    const tile = hatchPattern('cant_see', INK, PAPER)

    for (let y = 0; y < TILE; y += 1) {
      for (let x = 0; x < TILE; x += 1) expect(isInk(tile, x, y), `pixel (${x}, ${y})`).toBe((x + y) % TILE < 2)
    }
  })

  it('draws not-measurable as one centred dot that stays clear of the tile edge', () => {
    const tile = hatchPattern('not_measurable', INK, PAPER)
    const inked = inkedPixels(tile)

    expect(inked.length).toBeGreaterThan(0)
    for (const [x, y] of inked) {
      // Inside the middle of the tile, so tiled dots stay apart...
      expect(Math.abs(x - 7.5)).toBeLessThanOrEqual(3)
      expect(Math.abs(y - 7.5)).toBeLessThanOrEqual(3)
      // ...and mirror-symmetric about the centre, so it reads as a dot.
      expect(isInk(tile, TILE - 1 - x, y)).toBe(true)
      expect(isInk(tile, x, TILE - 1 - y)).toBe(true)
    }
  })

  it('inks at a contrast of 3:1 or better against paper', () => {
    for (const kind of KINDS) {
      const tile = hatchPattern(kind, INK, PAPER)
      const [first] = inkedPixels(tile)
      if (!first) throw new Error(`${kind} tile has no ink`)

      expect(contrast(toHex(pixel(tile, first[0], first[1])), PAPER)).toBeGreaterThanOrEqual(3)
    }
  })

  it('blurs to a colour at least ΔE2000 10 away from the 0% ramp colour', () => {
    const zero = RAMP[0]
    if (!zero) throw new Error('RAMP has no first stop')

    for (const kind of KINDS) {
      const tile = hatchPattern(kind, INK, PAPER)

      // Seen from afar a hatched county is its mean colour; it must not pass for 0% out.
      expect(deltaE2000Rgb(meanColor(tile), hexToRgb(zero.color)), kind).toBeGreaterThanOrEqual(10)
    }
  })

  it('returns a fresh buffer every call', () => {
    const a = hatchPattern('cant_see', INK, PAPER)
    const b = hatchPattern('cant_see', INK, PAPER)

    expect(a.data).not.toBe(b.data)
    expect(Array.from(a.data)).toEqual(Array.from(b.data))
  })
})
