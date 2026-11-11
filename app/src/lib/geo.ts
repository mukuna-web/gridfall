/**
 * Small geometry helpers for the map: the extent to fit, and one label
 * point per county for the official-number dots.
 */
import type { Feature, FeatureCollection, Geometry, Point, Position } from 'geojson'
import type { CountyCollection, CountyGeometry } from '../types'

export type Bbox = [west: number, south: number, east: number, north: number]

function eachPosition(coordinates: unknown, visit: (p: Position) => void): void {
  if (!Array.isArray(coordinates)) return
  if (typeof coordinates[0] === 'number') {
    visit(coordinates as Position)
    return
  }
  for (const child of coordinates) eachPosition(child, visit)
}

export function bboxOf(collection: FeatureCollection<Geometry | null>): Bbox | null {
  let box: Bbox | null = null
  for (const feature of collection.features) {
    const geometry = feature.geometry
    if (!geometry || !('coordinates' in geometry)) continue
    eachPosition(geometry.coordinates, ([x, y]) => {
      if (x === undefined || y === undefined) return
      box = box ? [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)] : [x, y, x, y]
    })
  }
  return box
}

interface RingStats {
  readonly area: number
  readonly x: number
  readonly y: number
}

/** Signed area and centroid of one ring (shoelace formula, planar lon/lat); null if degenerate. */
function ringCentroid(ring: readonly Position[]): RingStats | null {
  if (ring.length < 3) return null
  let twiceArea = 0
  let cx = 0
  let cy = 0
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [x0 = 0, y0 = 0] = ring[i] ?? []
    const [x1 = 0, y1 = 0] = ring[i + 1] ?? []
    const cross = x0 * y1 - x1 * y0
    twiceArea += cross
    cx += (x0 + x1) * cross
    cy += (y0 + y1) * cross
  }
  if (twiceArea === 0) return null
  return { area: twiceArea / 2, x: cx / (3 * twiceArea), y: cy / (3 * twiceArea) }
}

/**
 * Centroid of the largest outer ring: good enough to anchor a dot. No seed
 * value in the comparison: county areas are mostly far below one square
 * degree, so any fixed starting area can silently beat them all.
 */
function labelPoint(geometry: CountyGeometry): Position | null {
  const outerRings = geometry.type === 'Polygon' ? [geometry.coordinates[0] ?? []] : geometry.coordinates.map((p) => p[0] ?? [])
  let best: RingStats | null = null
  for (const ring of outerRings) {
    const stats = ringCentroid(ring)
    if (stats && (best === null || Math.abs(stats.area) > Math.abs(best.area))) best = stats
  }
  return best ? [best.x, best.y] : null
}

/** One point per county for the official-number dots; counties with no usable ring are skipped. */
export function labelPoints(counties: CountyCollection): FeatureCollection<Point, { fips: string }> {
  const features = counties.features.flatMap((f): Array<Feature<Point, { fips: string }>> => {
    const point = labelPoint(f.geometry)
    return point ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: point }, properties: { fips: f.properties.fips } }] : []
  })
  return { type: 'FeatureCollection', features }
}
