import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { parseExposure } from '../data/validate'
import type { ExposureByCounty, HourKey, WaitingPeriod } from '../types'
import { expectedPoliciesOut, exposureRows } from './exposure'

const APP_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
/**
 * The hand-made toy the Python twin (export.expected_policies_out) is checked
 * against in tests/test_export.py and tests/test_contract.py. It is read from
 * the repo, never skipped: the app job runs in the same checkout (CT-06).
 */
const PYTHON_TOY = join(APP_DIR, '..', 'tests', 'fixtures', 'exposure_toy.json')

interface ExpectedOut {
  readonly low: number
  readonly high: number
  readonly unknown_policies: number
}

interface Toy {
  readonly exposure: unknown
  readonly expected: Partial<Record<HourKey, ExpectedOut>>
}

/**
 * Inline copy of tests/fixtures/exposure_toy.json, kept here so the numbers
 * can be read beside the assertions; a test below fails if the two drift
 * apart. 12005 is unseen at 72 h and 12007 at 24 h: their policies land in
 * unknown_policies. 12003's [0, 0.125] at 72 h is a county the satellite saw
 * nearly restored, a real low of 0, not a blind spot.
 */
const SHARED_TOY: Toy = {
  exposure: {
    '12001': { home: 90, business: 10, at: { '24': [0.5, 0.75], '48': [0.25, 0.5], '72': [0.125, 0.25] } },
    '12003': { home: 190, business: 10, at: { '24': [0.25, 0.5], '48': [0.125, 0.25], '72': [0.0, 0.125] } },
    '12005': { home: 40, business: 10, at: { '24': [0.5, 1.0], '48': [0.5, 0.75], '72': null } },
    '12007': { home: 8, business: 2, at: { '24': null, '48': [1.0, 1.0], '72': [0.5, 0.5] } },
  },
  expected: {
    '24': { low: 125.0, high: 225.0, unknown_policies: 10 },
    '48': { low: 85.0, high: 147.5, unknown_policies: 0 },
    '72': { low: 17.5, high: 55.0, unknown_policies: 50 },
  },
}

/**
 * A second toy for the blind cases: 99003 is unseen at 48 h and 99005 is
 * never seen, so both land in unknown_policies.
 */
const EDGE_TOY: Toy = {
  exposure: {
    '99001': { home: 900, business: 100, at: { '24': [0.5, 0.7], '48': [0.3, 0.5], '72': [0.1, 0.2] } },
    '99003': { home: 450, business: 50, at: { '24': [0.2, 0.4], '48': null, '72': [0.0, 0.1] } },
    '99005': { home: 190, business: 10, at: { '24': null, '48': null, '72': null } },
  },
  expected: {
    '24': { low: 600, high: 900, unknown_policies: 200 },
    '48': { low: 300, high: 500, unknown_policies: 700 },
    '72': { low: 100, high: 250, unknown_policies: 200 },
  },
}

/**
 * Policies are counts, so agreeing to within half a policy is the contract:
 * it accepts a Python side that rounds to whole policies or keeps fractions.
 */
const HALF_POLICY = 0.5
const HOURS: readonly WaitingPeriod[] = [24, 48, 72]

function readPythonToy(): Toy {
  return JSON.parse(readFileSync(PYTHON_TOY, 'utf8')) as Toy
}

function toysToCheck(): ReadonlyArray<readonly [string, Toy]> {
  return [
    ['inline copy of the shared toy', SHARED_TOY],
    ['edge toy', EDGE_TOY],
    ['tests/fixtures/exposure_toy.json', readPythonToy()],
  ]
}

describe('expectedPoliciesOut', () => {
  it('exposure matches the Python toy', () => {
    for (const [label, toy] of toysToCheck()) {
      const exposure = parseExposure(toy.exposure, label)
      for (const hours of HOURS) {
        const want = toy.expected[String(hours) as HourKey]
        if (!want) throw new Error(`${label}: no expected values for ${hours} h`)

        const got = expectedPoliciesOut(exposure, hours)

        expect(Math.abs(got.low - want.low), `${label} low at ${hours} h`).toBeLessThanOrEqual(HALF_POLICY)
        expect(Math.abs(got.high - want.high), `${label} high at ${hours} h`).toBeLessThanOrEqual(HALF_POLICY)
        expect(got.unknownPolicies, `${label} unknown at ${hours} h`).toBe(want.unknown_policies)
      }
    }
  })

  // No fallback: the Python toy must be there, and the inline copy must be that same toy.
  it('keeps the inline copy identical to tests/fixtures/exposure_toy.json', () => {
    expect(readPythonToy()).toEqual(SHARED_TOY)
  })

  it("can't-see counties go to unknown", () => {
    const exposure: ExposureByCounty = {
      '99001': { home: 900, business: 100, at: { '24': [0.5, 0.7], '48': [0.3, 0.5], '72': [0.1, 0.2] } },
      '99005': { home: 950, business: 50, at: { '24': null, '48': null, '72': null } },
    }

    const out = expectedPoliciesOut(exposure, 72)

    expect(out.unknownPolicies).toBe(1000)
    expect(out.low).toBeCloseTo(100, 9)
    expect(out.high).toBeCloseTo(200, 9)
    // A county the satellite saw fully restored is the only way to add zero.
    const seenRestored: ExposureByCounty = {
      ...exposure,
      '99005': { home: 950, business: 50, at: { '24': [0, 0], '48': [0, 0], '72': [0, 0] } },
    }
    expect(expectedPoliciesOut(seenRestored, 72).unknownPolicies).toBe(0)
  })

  it('orders a reversed bracket so low never exceeds high', () => {
    const exposure: ExposureByCounty = {
      '99001': { home: 100, business: 0, at: { '24': [0.6, 0.2], '48': null, '72': null } },
    }

    const out = expectedPoliciesOut(exposure, 24)

    expect(out.low).toBeCloseTo(20, 9)
    expect(out.high).toBeCloseTo(60, 9)
  })

  it('does not change its input', () => {
    const exposure: ExposureByCounty = {
      '99001': { home: 100, business: 0, at: { '24': [0.6, 0.2], '48': null, '72': null } },
    }
    const before = JSON.stringify(exposure)

    expectedPoliciesOut(exposure, 24)
    exposureRows(exposure, 24)

    expect(JSON.stringify(exposure)).toBe(before)
  })
})

describe('exposureRows', () => {
  it('sorts seen counties by high end and puts blind counties last', () => {
    const rows = exposureRows(EDGE_TOY.exposure as ExposureByCounty, 48)

    expect(rows.map((r) => r.fips)).toEqual(['99001', '99003', '99005'])
    expect(rows[0]).toMatchObject({ policies: 1000, low: 300, high: 500, seen: true })
    expect(rows[1]).toMatchObject({ policies: 500, low: null, high: null, seen: false })
  })
})
