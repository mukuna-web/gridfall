import { describe, expect, it } from 'vitest'
import { colorForShare, RAMP, rampGradientCss, relativeLuminance } from './color'

describe('color ramp', () => {
  it('maps 0 and 1 to the ends of the ramp and clamps outside them', () => {
    expect(colorForShare(0)).toBe(RAMP[0]?.color)
    expect(colorForShare(1)).toBe(RAMP[RAMP.length - 1]?.color)
    expect(colorForShare(-0.2)).toBe(colorForShare(0))
    // EAGLE-I over-counts can exceed 100%: they take the darkest color.
    expect(colorForShare(1.3)).toBe(colorForShare(1))
  })

  it('gets darker as more customers are out, so it reads without hue (color-blind safe)', () => {
    const steps = Array.from({ length: 21 }, (_, i) => relativeLuminance(colorForShare(i / 20)))

    for (let i = 1; i < steps.length; i += 1) {
      expect(steps[i]).toBeLessThan(steps[i - 1] ?? Number.POSITIVE_INFINITY)
    }
  })

  it('refuses an unknown share instead of painting it with the 0% color', () => {
    expect(() => colorForShare(Number.NaN)).toThrow(RangeError)
    expect(() => colorForShare(Number.POSITIVE_INFINITY)).toThrow(RangeError)
  })

  it('builds the legend gradient from the same stops', () => {
    const css = rampGradientCss()

    for (const stop of RAMP) expect(css).toContain(stop.color)
  })
})
