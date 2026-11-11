import { describe, expect, it } from 'vitest'
import { parseCounties } from '../data/validate'
import { readFixtureJson } from '../test/fixtureFetch'
import type { CountyCollection } from '../types'
import { bboxOf, labelPoints } from './geo'

const COUNTIES = parseCounties(readFixtureJson('milton/counties.geojson'), 'counties.geojson')

describe('geo', () => {
  it('fits the extent of every county', () => {
    expect(bboxOf(COUNTIES)).toEqual([-82, 27, -81, 28])
  })

  it('has no extent for an empty collection', () => {
    expect(bboxOf({ type: 'FeatureCollection', features: [] })).toBeNull()
  })

  it('puts each official dot at the centre of a county smaller than one square degree', () => {
    // Real counties are mostly well under 1 square degree; a sentinel area of
    // -1 once beat every one of them and sent all dots to [0, 0].
    const points = labelPoints(COUNTIES)

    expect(points.features.map((f) => f.properties.fips)).toEqual(['99001', '99003', '99005', '99007'])
    const [x, y] = points.features[0]?.geometry.coordinates ?? []
    expect(x).toBeCloseTo(-81.75, 9)
    expect(y).toBeCloseTo(27.25, 9)
  })

  it('anchors a multi-part county on its largest part', () => {
    const [x, y] = labelPoints(COUNTIES).features[3]?.geometry.coordinates ?? []

    // Delta's main part spans -81.5..-81.2; the island at -81.15..-81.0 is smaller.
    expect(x).toBeCloseTo(-81.35, 9)
    expect(y).toBeCloseTo(27.75, 9)
  })

  it('skips a county with no usable ring instead of dropping a dot at [0, 0]', () => {
    const broken: CountyCollection = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [] },
          properties: { fips: '99009', name: 'Echo', state: 'ZZ', housing_units: 1, customers: 1 },
        },
      ],
    }

    expect(labelPoints(broken).features).toEqual([])
  })
})
