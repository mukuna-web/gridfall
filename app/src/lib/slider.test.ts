import { describe, expect, it } from 'vitest'
import { sliderIndexAfterKey } from './slider'

describe('sliderIndexAfterKey', () => {
  const count = 6

  it('moves one step later on ArrowRight and ArrowUp', () => {
    expect(sliderIndexAfterKey('ArrowRight', 2, count)).toBe(3)
    expect(sliderIndexAfterKey('ArrowUp', 2, count)).toBe(3)
  })

  it('moves one step earlier on ArrowLeft and ArrowDown', () => {
    expect(sliderIndexAfterKey('ArrowLeft', 2, count)).toBe(1)
    expect(sliderIndexAfterKey('ArrowDown', 2, count)).toBe(1)
  })

  it('jumps to the ends on Home and End', () => {
    expect(sliderIndexAfterKey('Home', 3, count)).toBe(0)
    expect(sliderIndexAfterKey('End', 3, count)).toBe(count - 1)
  })

  it('returns null when nothing would change, so the ends are quiet', () => {
    expect(sliderIndexAfterKey('ArrowLeft', 0, count)).toBeNull()
    expect(sliderIndexAfterKey('Home', 0, count)).toBeNull()
    expect(sliderIndexAfterKey('ArrowRight', count - 1, count)).toBeNull()
    expect(sliderIndexAfterKey('End', count - 1, count)).toBeNull()
  })

  it('returns null for keys it does not handle and for an empty slider', () => {
    expect(sliderIndexAfterKey('a', 2, count)).toBeNull()
    expect(sliderIndexAfterKey('PageUp', 2, count)).toBeNull()
    expect(sliderIndexAfterKey('Tab', 2, count)).toBeNull()
    expect(sliderIndexAfterKey('End', 0, 0)).toBeNull()
  })
})
