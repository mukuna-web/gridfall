import { describe, expect, it } from 'vitest'
import { createFlagStore, FLAGS_KEY, LEGACY_FLAGS_KEY } from './flags'

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

function throwingStorage(): StorageLike {
  return {
    getItem: () => {
      throw new Error('SecurityError: storage is disabled')
    },
    setItem: () => {
      throw new Error('QuotaExceededError')
    },
  }
}

const browser = () => window.localStorage
const stored = () => JSON.parse(window.localStorage.getItem(FLAGS_KEY) ?? 'null') as unknown

describe('flags', () => {
  it('a flag in one storm does not flag the same claim id in another storm', () => {
    const ian = createFlagStore(browser, 'ian2022')
    const lock = createFlagStore(browser, 'lock2099')

    ian.saveFlag('C0001')

    expect(ian.loadFlags()).toEqual(['C0001'])
    expect(lock.loadFlags()).toEqual([])
    expect(stored()).toEqual({ ian2022: ['C0001'] })
  })

  it('persists per storm under bfs.flags.v2 without duplicates', () => {
    const store = createFlagStore(browser, 'ian2022')

    store.saveFlag('C0001')
    store.saveFlag('C0002')
    store.saveFlag('C0001')

    expect(FLAGS_KEY).toBe('bfs.flags.v2')
    expect(stored()).toEqual({ ian2022: ['C0001', 'C0002'] })
    // A fresh store (a page reload) reads the same flags back.
    expect(createFlagStore(browser, 'ian2022').loadFlags()).toEqual(['C0001', 'C0002'])
  })

  it('clears one flag and keeps the rest, in this storm only', () => {
    const ian = createFlagStore(browser, 'ian2022')
    const lock = createFlagStore(browser, 'lock2099')
    ian.saveFlag('C0001')
    ian.saveFlag('C0002')
    lock.saveFlag('C0001')

    ian.clearFlag('C0001')

    expect(ian.loadFlags()).toEqual(['C0002'])
    expect(lock.loadFlags()).toEqual(['C0001'])
  })

  it('carries flags saved by the old flat list over, showing in every storm as they did', () => {
    window.localStorage.setItem(LEGACY_FLAGS_KEY, JSON.stringify(['C0001', 'C0002']))

    const ian = createFlagStore(browser, 'ian2022')
    const lock = createFlagStore(browser, 'lock2099')

    expect(ian.loadFlags()).toEqual(['C0001', 'C0002'])
    expect(lock.loadFlags()).toEqual(['C0001', 'C0002'])

    ian.saveFlag('C0003')
    expect(ian.loadFlags()).toEqual(['C0001', 'C0002', 'C0003'])
    expect(lock.loadFlags()).toEqual(['C0001', 'C0002'])

    // Removing an old flag removes it everywhere, which is where it showed.
    ian.clearFlag('C0001')
    expect(lock.loadFlags()).toEqual(['C0002'])
    expect(stored()).toEqual({ '*': ['C0002'], ian2022: ['C0003'] })
  })

  it('shows a claim once when it is flagged both for this storm and in the old list', () => {
    window.localStorage.setItem(FLAGS_KEY, JSON.stringify({ '*': ['C0001'], ian2022: ['C0001', 'C0002'] }))

    expect(createFlagStore(browser, 'ian2022').loadFlags()).toEqual(['C0001', 'C0002'])
  })

  it('flags survive storage throwing, for this session, and say so', () => {
    const store = createFlagStore(() => throwingStorage(), 'ian2022')

    expect(() => store.saveFlag('C0001')).not.toThrow()
    expect(store.loadFlags()).toEqual(['C0001'])
    expect(store.isPersistent()).toBe(false)
    expect(() => store.clearFlag('C0001')).not.toThrow()
    expect(store.loadFlags()).toEqual([])
  })

  it('survives even reaching for storage throwing', () => {
    const store = createFlagStore(() => {
      throw new Error('SecurityError: access denied')
    }, 'ian2022')

    expect(() => store.saveFlag('C0002')).not.toThrow()
    expect(store.loadFlags()).toEqual(['C0002'])
    expect(store.isPersistent()).toBe(false)
  })

  it('reads malformed stored JSON as no flags without calling storage blocked', () => {
    window.localStorage.setItem(FLAGS_KEY, '{not json')
    const store = createFlagStore(browser, 'ian2022')

    expect(store.loadFlags()).toEqual([])
    // Storage works; only its contents were garbage. The next save replaces them.
    expect(store.isPersistent()).toBe(true)
    store.saveFlag('C0001')
    expect(stored()).toEqual({ ian2022: ['C0001'] })
  })

  it('ignores foreign shapes and non-string ids in storage', () => {
    window.localStorage.setItem(FLAGS_KEY, JSON.stringify(['C0001']))
    expect(createFlagStore(browser, 'ian2022').loadFlags()).toEqual([])

    window.localStorage.setItem(FLAGS_KEY, JSON.stringify({ ian2022: 'C0001' }))
    expect(createFlagStore(browser, 'ian2022').loadFlags()).toEqual([])

    window.localStorage.setItem(FLAGS_KEY, JSON.stringify({ ian2022: ['C0003', 7, null] }))
    expect(createFlagStore(browser, 'ian2022').loadFlags()).toEqual(['C0003'])

    window.localStorage.setItem(LEGACY_FLAGS_KEY, '{not json')
    window.localStorage.removeItem(FLAGS_KEY)
    expect(createFlagStore(browser, 'ian2022').loadFlags()).toEqual([])
  })

  it('returns a copy, so callers cannot change the stored list', () => {
    const store = createFlagStore(browser, 'ian2022')
    store.saveFlag('C0004')

    const flags = store.loadFlags()
    flags.push('C9999')

    expect(store.loadFlags()).toEqual(['C0004'])
  })
})
