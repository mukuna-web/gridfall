import { describe, expect, it } from 'vitest'
import { parseUrlState, serializeUrlState } from './urlState'

describe('url state', () => {
  it('reads a shared link', () => {
    expect(parseUrlState('?storm=ian2022&night=2022-09-29&county=12071&hours=48&official=1')).toEqual({
      storm: 'ian2022',
      night: '2022-09-29',
      county: '12071',
      hours: 48,
      official: true,
    })
  })

  it('drops values that are not valid instead of trusting them', () => {
    expect(parseUrlState('?storm=../x&night=tomorrow&county=12&hours=36&official=yes')).toEqual({
      official: false,
    })
  })

  it('writes only what is set', () => {
    expect(serializeUrlState({ storm: 'ian2022', hours: 72, official: false })).toBe('?storm=ian2022&hours=72')
    expect(serializeUrlState({ official: false })).toBe('')
  })

  it('round-trips', () => {
    const state = { storm: 'beryl2024', night: '2024-07-08', county: '48201', hours: 24 as const, official: true }

    expect(parseUrlState(serializeUrlState(state))).toEqual(state)
  })
})
