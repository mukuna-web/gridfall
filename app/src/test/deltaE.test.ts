import { describe, expect, it } from 'vitest'
import { deltaE2000, deltaE2000Rgb, rgbToLab } from './deltaE'

describe('deltaE2000 (test helper)', () => {
  it('reproduces published CIEDE2000 test pairs (Sharma, Wu and Dalal 2005)', () => {
    // Pairs 1, 7 and 17 of the reference data, to four decimals.
    expect(deltaE2000([50, 2.6772, -79.7751], [50, 0, -82.7485])).toBeCloseTo(2.0425, 4)
    expect(deltaE2000([50, 0, 0], [50, -1, 2])).toBeCloseTo(2.3669, 4)
    expect(deltaE2000([50, 2.5, 0], [73, 25, -18])).toBeCloseTo(27.1492, 4)
  })

  it('white is L 100 with no chroma, and identical colours differ by zero', () => {
    const [l, a, b] = rgbToLab([255, 255, 255])
    expect(l).toBeCloseTo(100, 1)
    expect(Math.abs(a)).toBeLessThan(0.05)
    expect(Math.abs(b)).toBeLessThan(0.05)
    expect(deltaE2000Rgb([27, 26, 23], [27, 26, 23])).toBe(0)
  })
})
