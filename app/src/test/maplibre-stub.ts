/**
 * Recording stand-in for maplibre-gl, which needs WebGL.
 *
 * It draws nothing. It records what StormMap asks of it (the style it was
 * created with, every source, layer, image and feature state) so tests can
 * read the colour expressions and states back, and it fires "load" on the
 * next microtask, or "error" when a test asks for a failing map.
 */
import type { LayerSpecification, SourceSpecification } from 'maplibre-gl'

type Handler = (event: unknown) => void

interface Listener {
  readonly type: string
  readonly layer: string | null
  readonly fn: Handler
}

export type FeatureState = Readonly<Record<string, unknown>>

export interface RecordedFeatureState {
  readonly source: string
  readonly id: string | number
  readonly state: FeatureState
}

export interface RecordedImage {
  readonly id: string
  readonly image: unknown
  readonly options: unknown
}

interface StubControls {
  /** Every map created since the last reset, oldest first. */
  readonly instances: Map[]
  /** When set, the next maps fire "error" with this message instead of "load". */
  failure: string | null
  /** When set, the constructor throws it (no WebGL): the error boundary's path. */
  throwOnCreate: Error | null
  reset(): void
}

export const stub: StubControls = {
  instances: [],
  failure: null,
  throwOnCreate: null,
  reset() {
    this.instances.length = 0
    this.failure = null
    this.throwOnCreate = null
  },
}

const noop = () => undefined

export class Map {
  readonly options: Readonly<Record<string, unknown>>
  readonly sources: Readonly<Record<string, SourceSpecification>> = {}
  readonly layers: readonly LayerSpecification[] = []
  readonly images: readonly RecordedImage[] = []
  readonly featureStates: readonly RecordedFeatureState[] = []
  readonly keyboard = { disableRotation: noop }
  readonly touchZoomRotate = { disableRotation: noop }
  readonly fitBoundsCalls: unknown[] = []
  private readonly listeners: Listener[] = []
  private readonly canvas = { style: { cursor: '' } }
  private removed = false

  constructor(options: Record<string, unknown>) {
    if (stub.throwOnCreate) throw stub.throwOnCreate
    this.options = options
    stub.instances.push(this)
    const failure = stub.failure
    queueMicrotask(() => {
      if (this.removed) return
      if (failure !== null) this.fire('error', { error: new Error(failure) })
      else this.fire('load', {})
    })
  }

  on(type: string, layerOrHandler: string | Handler, handler?: Handler): this {
    if (typeof layerOrHandler === 'function') this.listeners.push({ type, layer: null, fn: layerOrHandler })
    else if (handler) this.listeners.push({ type, layer: layerOrHandler, fn: handler })
    return this
  }

  /** Fires a map-level event, the way a test drives "load" or "error". */
  fire(type: string, event: unknown): void {
    for (const listener of this.listeners) if (listener.type === type && listener.layer === null) listener.fn(event)
  }

  addControl(): this {
    return this
  }

  addImage(id: string, image: unknown, options?: unknown): void {
    ;(this.images as RecordedImage[]).push({ id, image, options })
  }

  addSource(id: string, spec: SourceSpecification): this {
    ;(this.sources as Record<string, SourceSpecification>)[id] = spec
    return this
  }

  addLayer(layer: LayerSpecification): this {
    ;(this.layers as LayerSpecification[]).push(layer)
    return this
  }

  setFeatureState(target: { source: string; id?: string | number }, state: FeatureState): void {
    ;(this.featureStates as RecordedFeatureState[]).push({ source: target.source, id: target.id ?? '', state })
  }

  /** The merged state of one feature, as MapLibre would hold it after every call so far. */
  stateOf(source: string, id: string | number): FeatureState {
    return this.featureStates
      .filter((s) => s.source === source && s.id === id)
      .reduce<FeatureState>((merged, s) => ({ ...merged, ...s.state }), {})
  }

  layer(id: string): LayerSpecification {
    const found = this.layers.find((l) => l.id === id)
    if (!found) throw new Error(`stub map has no layer ${id}; it has ${this.layers.map((l) => l.id).join(', ')}`)
    return found
  }

  fitBounds(bounds: unknown, options?: unknown): this {
    this.fitBoundsCalls.push({ bounds, options })
    return this
  }

  getCanvas() {
    return this.canvas
  }

  remove(): void {
    this.removed = true
  }
}

export class NavigationControl {
  constructor(_options?: unknown) {}
}

export function setWorkerUrl(_url: string): void {}
