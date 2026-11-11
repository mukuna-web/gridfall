import { render, waitFor } from '@testing-library/react'
import type { FillLayerSpecification, CircleLayerSpecification } from 'maplibre-gl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RAMP } from '../lib/color'
import { evaluate } from '../test/maplibreExpression'
import { stub } from '../test/maplibre-stub'
import type { CountyFeature, MethodScore, NightRecord, StormData } from '../types'
import { MapErrorBoundary } from './MapErrorBoundary'
import StormMap from './StormMap'

const NIGHT = '2099-01-02'
const PAPER = '#f4efe4'
const HIDDEN = 'rgba(0, 0, 0, 0)'
const ZERO_COLOR = RAMP[0]?.color ?? ''
const NO_SCORE: MethodScore = {
  mae_pp: null,
  peak_total_est: null,
  peak_total_official: null,
  catch_rate_50: null,
  false_alarm_50: null,
  restore_day_err: null,
  measurable_share: null,
}

function county(fips: string, name: string, x: number): CountyFeature {
  return {
    type: 'Feature',
    geometry: { type: 'Polygon', coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]] },
    properties: { fips, name, state: 'ZZ', housing_units: 1000, customers: 2000 },
  }
}

function record(status: NightRecord['status'], est: number | null, lo: number | null, hi: number | null, official: number | null): NightRecord {
  return { night: NIGHT, status, est, lo, hi, official }
}

/** Five synthetic counties: one seen clearly, and four kinds of "no estimate". */
const DATA: StormData = {
  meta: {
    id: 'synth2099',
    name: 'Synth',
    landfall: NIGHT,
    role: 'main',
    satellite: 'VNP46A2',
    nights: [NIGHT],
    waiting_periods: [24, 48, 72],
    default_waiting_period: 72,
    generated: '2099-01-03T00:00:00Z',
    notes: [],
  },
  counties: {
    type: 'FeatureCollection',
    features: [county('99001', 'Seen', 0), county('99003', 'Clouds', 1), county('99005', 'Dark', 2), county('99007', 'Blank', 3), county('99009', 'Absent', 4)],
  },
  states: { type: 'FeatureCollection', features: [] },
  nights: {
    '99001': [record('ok', 0.5, 0.4, 0.6, 0.55)],
    // A stray range on a can't-see night, and a stray 0.0 on a not-measurable one.
    '99003': [record('cant_see', null, 0, 0.1, 0.2)],
    '99005': [record('not_measurable', 0, 0, 0, null)],
    // An "ok" night with no number at all; 99009 has no record for this night.
    '99007': [record('ok', null, null, null, 0.1)],
  },
  restoration: {},
  exposure: {},
  claims: [],
  scorecard: { storm_id: 'synth2099', window: 60, methods: { isotonic: NO_SCORE, wind_only: NO_SCORE, nothing: NO_SCORE }, note: '' },
}

const UNSEEN = ['99003', '99005', '99007', '99009'] as const

function renderMap(showOfficial = false) {
  const utils = render(<StormMap data={DATA} night={NIGHT} showOfficial={showOfficial} onSelect={() => undefined} />)
  const container = () => utils.container.querySelector('[data-map-state]')
  return { ...utils, container }
}

async function readyMap(showOfficial = false) {
  const utils = renderMap(showOfficial)
  await waitFor(() => expect(utils.container()?.getAttribute('data-map-state')).toBe('ready'))
  const map = stub.instances[0]
  if (!map) throw new Error('no map was created')
  return { ...utils, map }
}

function fillColor(map: NonNullable<(typeof stub.instances)[0]>, fips: string): unknown {
  const paint = (map.layer('county-fill') as FillLayerSpecification).paint ?? {}
  return evaluate(paint['fill-color'], map.stateOf('counties', fips))
}

describe('StormMap', () => {
  beforeEach(() => stub.reset())
  afterEach(() => stub.reset())

  it('reports loading, then ready, on its container', async () => {
    const { container } = renderMap()

    expect(container()?.getAttribute('data-map-state')).toBe('loading')
    await waitFor(() => expect(container()?.getAttribute('data-map-state')).toBe('ready'))
  })

  it('colours only ok counties and hatches the rest, one hatch layer per unseen status', async () => {
    const { map } = await readyMap()

    const seen = fillColor(map, '99001')
    expect(seen).toMatch(/^#[0-9a-f]{6}$/)
    expect(seen).not.toBe(PAPER)
    for (const fips of UNSEEN) expect(fillColor(map, fips), fips).toBe(PAPER)

    const hatches = map.layers.filter((l): l is FillLayerSpecification => l.type === 'fill' && 'fill-pattern' in (l.paint ?? {}))
    expect(hatches.map((l) => l.paint?.['fill-pattern'])).toEqual(['hatch-cant-see', 'hatch-not-measurable'])
    expect(map.images.map((i) => i.id)).toEqual(['hatch-cant-see', 'hatch-not-measurable'])
    const opacity = (layer: FillLayerSpecification, fips: string) => evaluate(layer.paint?.['fill-opacity'], map.stateOf('counties', fips))
    const [cantSee, dark] = hatches as [FillLayerSpecification, FillLayerSpecification]
    expect(['99001', '99003', '99005', '99007', '99009'].map((f) => opacity(cantSee, f))).toEqual([0, 1, 0, 1, 1])
    expect(['99001', '99003', '99005', '99007', '99009'].map((f) => opacity(dark, f))).toEqual([0, 0, 1, 0, 0])
  })

  it('never maps a missing or stray number to the 0% colour', async () => {
    const { map } = await readyMap()

    for (const fips of UNSEEN) {
      expect(map.stateOf('counties', fips).status, fips).not.toBe('ok')
      expect(fillColor(map, fips), fips).not.toBe(ZERO_COLOR)
    }
    // The ramp is only ever reached with a finite share in 0..1.
    for (const { source, state } of map.featureStates) {
      if (source !== 'counties' || state.status !== 'ok') continue
      expect(typeof state.pct === 'number' && state.pct >= 0 && state.pct <= 1, JSON.stringify(state)).toBe(true)
    }
  })

  it('draws from the exported GeoJSON only: no tiles, glyphs or sprite', async () => {
    const { map } = await readyMap()

    const style = map.options.style as Record<string, unknown>
    expect(style).not.toHaveProperty('sprite')
    expect(style).not.toHaveProperty('glyphs')
    expect(Object.keys(style.sources as object)).toEqual([])
    expect(Object.values(map.sources).map((s) => s.type)).toEqual(['geojson', 'geojson', 'geojson'])
    expect(map.layers.map((l) => l.type)).not.toContain('symbol')
  })

  it('shows official dots only with the toggle on', async () => {
    const { map, rerender } = await readyMap(false)
    const dots = map.layer('official-dots') as CircleLayerSpecification
    const dotColor = (fips: string) => evaluate(dots.paint?.['circle-color'], map.stateOf('county-points', fips))

    expect(map.stateOf('county-points', '99001').show).toBe(false)
    expect(dotColor('99001')).toBe(HIDDEN)

    rerender(<StormMap data={DATA} night={NIGHT} showOfficial onSelect={() => undefined} />)

    expect(map.stateOf('county-points', '99001')).toMatchObject({ show: true, official: 0.55 })
    expect(dotColor('99001')).toMatch(/^#[0-9a-f]{6}$/)
    // No official number, no dot, even with the toggle on.
    expect(map.stateOf('county-points', '99005').show).toBe(false)
    expect(dotColor('99005')).toBe(HIDDEN)
  })

  it('marks the container "error" and says so when the map fails before load', async () => {
    stub.failure = 'WebGL context lost'
    const { container, findByRole } = renderMap()

    await waitFor(() => expect(container()?.getAttribute('data-map-state')).toBe('error'))
    expect((await findByRole('status')).textContent).toMatch(/could not start \(WebGL context lost\)/)
  })

  it('the error boundary fallback carries the "error" state when the map cannot be created', async () => {
    stub.throwOnCreate = new Error('WebGL unavailable')
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    const { container } = render(
      <MapErrorBoundary>
        <StormMap data={DATA} night={NIGHT} showOfficial={false} onSelect={() => undefined} />
      </MapErrorBoundary>,
    )

    await waitFor(() => expect(container.querySelector('[data-map-state="error"]')).not.toBeNull())
    expect(container.textContent).toMatch(/WebGL unavailable/)
  })
})
