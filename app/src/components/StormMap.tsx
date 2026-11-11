import 'maplibre-gl/dist/maplibre-gl.css'
import type { ExpressionSpecification, MapLayerMouseEvent, StyleSpecification } from 'maplibre-gl'
import { Map as MapLibreMap, NavigationControl, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { usePrefersReducedMotion } from '../hooks/usePrefersReducedMotion'
import { rampStops } from '../lib/color'
import { formatPct, formatRange, isNumber } from '../lib/format'
import { bboxOf, labelPoints } from '../lib/geo'
import { displayStatus, findNight, usableEstimate } from '../lib/nights'
import { hatchPattern } from '../lib/patterns'
import type { IsoDate, StormData } from '../types'

// MapLibre 6 looks for its worker next to its own module, which the bundler
// moves. Point it at the copy Vite emits instead.
setWorkerUrl(workerUrl)

export interface StormMapProps {
  readonly data: StormData
  readonly night: IsoDate
  readonly showOfficial: boolean
  readonly onSelect: (fips: string) => void
  /** County to outline as selected; none when omitted. */
  readonly selectedFips?: string | null
}

const SOURCE = { counties: 'counties', states: 'states', points: 'county-points' } as const
const LAYER = {
  fill: 'county-fill',
  cantSee: 'county-hatch-cant-see',
  dark: 'county-hatch-not-measurable',
  outline: 'county-outline',
  states: 'state-lines',
  hover: 'county-hover',
  selected: 'county-selected',
  officialHalo: 'official-halo',
  official: 'official-dots',
} as const
const IMAGE = { cantSee: 'hatch-cant-see', dark: 'hatch-not-measurable' } as const
const FIT_PADDING = 28
const HIDDEN = 'rgba(0, 0, 0, 0)'
const HEX = /^#[0-9a-f]{6}$/i

interface Colors {
  readonly paper: string
  readonly ink: string
  /** Everything that isn't a county: a shade deeper than paper, so hatched counties still read as land. */
  readonly field: string
}

/** Paper and ink come from the CSS tokens so the map matches the page. */
function readColors(): Colors {
  const css = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => {
    const value = css.getPropertyValue(name).trim()
    return HEX.test(value) ? value : fallback
  }
  return { paper: read('--paper', '#f4efe4'), ink: read('--ink', '#1b1a17'), field: read('--map-field', '#e8e0cf') }
}

function baseStyle(colors: Colors): StyleSpecification {
  return { version: 8, sources: {}, layers: [{ id: 'field', type: 'background', paint: { 'background-color': colors.field } }] }
}

const status = ['feature-state', 'status'] as ExpressionSpecification
const whenState = (key: string, on: number): ExpressionSpecification => ['case', ['boolean', ['feature-state', key], false], on, 0]
const rampOf = (key: string): ExpressionSpecification =>
  ['interpolate', ['linear'], ['feature-state', key], ...rampStops()] as unknown as ExpressionSpecification

function addStormLayers(map: MapLibreMap, data: StormData, colors: Colors): void {
  map.addImage(IMAGE.cantSee, hatchPattern('cant_see', colors.ink, colors.paper), { pixelRatio: 2 })
  map.addImage(IMAGE.dark, hatchPattern('not_measurable', colors.ink, colors.paper), { pixelRatio: 2 })
  map.addSource(SOURCE.counties, { type: 'geojson', data: data.counties, promoteId: 'fips' })
  map.addSource(SOURCE.states, { type: 'geojson', data: data.states })
  map.addSource(SOURCE.points, { type: 'geojson', data: labelPoints(data.counties), promoteId: 'fips' })
  // Only an "ok" county is colored; everything else is paper under a hatch, never the 0% color.
  map.addLayer({
    id: LAYER.fill,
    type: 'fill',
    source: SOURCE.counties,
    paint: { 'fill-color': ['case', ['==', status, 'ok'], rampOf('pct'), colors.paper] },
  })
  for (const [id, image, value] of [
    [LAYER.cantSee, IMAGE.cantSee, 'cant_see'],
    [LAYER.dark, IMAGE.dark, 'not_measurable'],
  ] as const) {
    map.addLayer({
      id,
      type: 'fill',
      source: SOURCE.counties,
      paint: { 'fill-pattern': image, 'fill-opacity': ['case', ['==', status, value], 1, 0] },
    })
  }
  map.addLayer({ id: LAYER.outline, type: 'line', source: SOURCE.counties, paint: { 'line-color': colors.ink, 'line-opacity': 0.3, 'line-width': 0.6 } })
  map.addLayer({ id: LAYER.states, type: 'line', source: SOURCE.states, paint: { 'line-color': colors.ink, 'line-opacity': 0.85, 'line-width': 1.4 } })
  map.addLayer({ id: LAYER.hover, type: 'line', source: SOURCE.counties, paint: { 'line-color': colors.ink, 'line-width': 1.6, 'line-opacity': whenState('hover', 0.9) } })
  map.addLayer({ id: LAYER.selected, type: 'line', source: SOURCE.counties, paint: { 'line-color': colors.ink, 'line-width': 3, 'line-opacity': whenState('selected', 1) } })
  // Official dots: an ink-and-paper halo under a ramp-colored center, so a dot
  // reads even on a fill of the same value. Colors are guarded by "show" so
  // the ramp is never evaluated on a missing value.
  const shown = ['boolean', ['feature-state', 'show'], false] as ExpressionSpecification
  map.addLayer({
    id: LAYER.officialHalo,
    type: 'circle',
    source: SOURCE.points,
    paint: {
      'circle-radius': 9,
      'circle-color': ['case', shown, colors.paper, HIDDEN],
      'circle-stroke-width': 1.25,
      'circle-stroke-color': ['case', shown, colors.ink, HIDDEN],
    },
  })
  map.addLayer({
    id: LAYER.official,
    type: 'circle',
    source: SOURCE.points,
    paint: { 'circle-radius': 6, 'circle-color': ['case', shown, rampOf('official'), HIDDEN] },
  })
}

/** Pushes tonight's status and numbers into feature state; no geometry is re-sent. */
function applyNight(map: MapLibreMap, data: StormData, night: IsoDate, showOfficial: boolean): void {
  for (const feature of data.counties.features) {
    const fips = feature.properties.fips
    const record = findNight(data.nights[fips] ?? [], night)
    const est = usableEstimate(record)
    // -1 is never read: the fill only looks at pct when status is "ok".
    map.setFeatureState({ source: SOURCE.counties, id: fips }, { status: displayStatus(record), pct: est ?? -1 })
    const official = record && isNumber(record.official) ? record.official : null
    map.setFeatureState({ source: SOURCE.points, id: fips }, { show: showOfficial && official !== null, official: official ?? 0 })
  }
}

function fipsOf(event: MapLayerMouseEvent): string | null {
  const value: unknown = event.features?.[0]?.properties?.fips
  return typeof value === 'string' ? value : null
}

function hoverText(data: StormData, night: IsoDate, fips: string): string {
  const feature = data.counties.features.find((f) => f.properties.fips === fips)
  const name = feature ? `${feature.properties.name}, ${feature.properties.state}` : fips
  const record = findNight(data.nights[fips] ?? [], night)
  const state = displayStatus(record)
  if (state === 'cant_see') return `${name}: can't see`
  if (state === 'not_measurable') return `${name}: not measurable`
  return `${name}: ${formatPct(usableEstimate(record))} out (${formatRange(record?.lo, record?.hi)})`
}

function createMap(container: HTMLElement, data: StormData, colors: Colors): MapLibreMap {
  const box = bboxOf(data.counties)
  const map = new MapLibreMap({
    container,
    style: baseStyle(colors),
    attributionControl: false,
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
    maxPitch: 0,
    renderWorldCopies: false,
    ...(box ? { bounds: box, fitBoundsOptions: { padding: FIT_PADDING } } : {}),
  })
  // A flat county map: no rotation, so the keyboard and touch gestures only pan and zoom.
  map.touchZoomRotate.disableRotation()
  map.keyboard.disableRotation()
  map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
  return map
}

interface MapHandlers {
  readonly onLoad: () => void
  readonly onFailure: (message: string) => void
  readonly onSelect: (fips: string) => void
  readonly onHover: (fips: string | null) => void
}

/** Load, failure, click-to-select and hover outline; hover state lives in the closure, not React. */
function bindInteractions(map: MapLibreMap, handlers: MapHandlers): void {
  let loaded = false
  let hoverFips: string | null = null
  const setHover = (fips: string | null) => {
    if (fips === hoverFips) return
    if (hoverFips) map.setFeatureState({ source: SOURCE.counties, id: hoverFips }, { hover: false })
    if (fips) map.setFeatureState({ source: SOURCE.counties, id: fips }, { hover: true })
    hoverFips = fips
    map.getCanvas().style.cursor = fips ? 'pointer' : ''
    handlers.onHover(fips)
  }
  map.on('load', () => {
    loaded = true
    handlers.onLoad()
  })
  map.on('error', (event) => {
    // Before load nothing would draw, so say so on the page. Later errors are
    // per-tile and recover, but having any 'error' listener switches off
    // MapLibre's own console report, so report them rather than drop them.
    if (!loaded) handlers.onFailure(event.error instanceof Error ? event.error.message : 'the map failed to start')
    else console.error('StormMap:', event.error)
  })
  map.on('click', LAYER.fill, (event) => {
    const fips = fipsOf(event)
    if (fips) handlers.onSelect(fips)
  })
  map.on('mousemove', LAYER.fill, (event) => setHover(fipsOf(event)))
  map.on('mouseleave', LAYER.fill, () => setHover(null))
}

interface MapInstance {
  readonly containerRef: RefObject<HTMLDivElement | null>
  readonly mapRef: RefObject<MapLibreMap | null>
  /** True once this map's sources and layers exist; false again when it is removed. */
  readonly ready: boolean
  readonly failure: string | null
  readonly hovered: string | null
}

/** Creates the map once per mount (the parent remounts it for a new storm) and tracks load, failure and hover. */
function useMapInstance(data: StormData, onSelect: (fips: string) => void): MapInstance {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const onSelectRef = useRef(onSelect)
  const [ready, setReady] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const colors = readColors()
    // Throws without WebGL; MapErrorBoundary in the parent shows the fallback.
    const map = createMap(container, data, colors)
    bindInteractions(map, {
      onLoad: () => {
        addStormLayers(map, data, colors)
        setReady(true)
      },
      onFailure: setFailure,
      onSelect: (fips) => onSelectRef.current(fips),
      onHover: setHovered,
    })
    mapRef.current = map
    return () => {
      mapRef.current = null
      setReady(false)
      map.remove()
    }
  }, [data])

  return { containerRef, mapRef, ready, failure, hovered }
}

/** Pushes tonight's numbers into the map whenever the night or the official toggle changes. */
function useNightState(map: MapInstance, data: StormData, night: IsoDate, showOfficial: boolean): void {
  const { mapRef, ready } = map
  useEffect(() => {
    const instance = mapRef.current
    if (ready && instance) applyNight(instance, data, night, showOfficial)
  }, [mapRef, ready, data, night, showOfficial])
}

/** Moves the selected-county outline; a new map instance starts with nothing outlined. */
function useSelectedOutline(map: MapInstance, selectedFips: string | null): void {
  const { mapRef, ready } = map
  const selectedRef = useRef<string | null>(null)
  useEffect(() => {
    const instance = mapRef.current
    if (!ready || !instance) {
      selectedRef.current = null
      return
    }
    if (selectedRef.current) instance.setFeatureState({ source: SOURCE.counties, id: selectedRef.current }, { selected: false })
    if (selectedFips) instance.setFeatureState({ source: SOURCE.counties, id: selectedFips }, { selected: true })
    selectedRef.current = selectedFips
  }, [mapRef, ready, selectedFips])
}

/** What the map is doing, for styling and for browser tests to wait on instead of a timeout. */
type MapState = 'loading' | 'ready' | 'error'

function mapState({ ready, failure }: MapInstance): MapState {
  if (failure) return 'error'
  return ready ? 'ready' : 'loading'
}

/** County choropleth with no basemap: county polygons and state lines only, so no keys or tiles. */
export default function StormMap({ data, night, showOfficial, onSelect, selectedFips = null }: StormMapProps) {
  const map = useMapInstance(data, onSelect)
  useNightState(map, data, night, showOfficial)
  useSelectedOutline(map, selectedFips)
  const { containerRef, mapRef, ready, failure, hovered } = map
  const reducedMotion = usePrefersReducedMotion()

  const refit = () => {
    const instance = mapRef.current
    const box = bboxOf(data.counties)
    if (instance && box) instance.fitBounds(box, { padding: FIT_PADDING, duration: reducedMotion ? 0 : 500 })
  }

  return (
    <div className="storm-map" data-map-state={mapState(map)}>
      <div
        ref={containerRef}
        className="storm-map__canvas"
        role="region"
        aria-label={`Map of ${data.counties.features.length} counties shaded by estimated customers out. Pick a county with the county list below the map.`}
      />
      {hovered ? (
        <p className="storm-map__readout num" aria-hidden="true">
          {hoverText(data, night, hovered)}
        </p>
      ) : null}
      {ready ? (
        <button type="button" className="storm-map__refit text-button" onClick={refit}>
          Fit storm
        </button>
      ) : null}
      {failure ? (
        <div className="storm-map__failure" role="status">
          <p>The map could not start ({failure}). The county card, portfolio and claim check still work.</p>
        </div>
      ) : null}
    </div>
  )
}
