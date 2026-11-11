import { Component } from 'react'
import type { ReactNode } from 'react'

interface MapErrorBoundaryProps {
  readonly children: ReactNode
}

interface MapErrorBoundaryState {
  readonly error: Error | null
}

/**
 * Keeps a map failure (no WebGL, or the MapLibre chunk failing to load) from
 * taking the whole report down: everything else works without the map.
 */
export class MapErrorBoundary extends Component<MapErrorBoundaryProps, MapErrorBoundaryState> {
  state: MapErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: unknown): MapErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  render() {
    if (!this.state.error) return this.props.children
    // The same data-map-state the map itself reports, so a browser test can wait on either outcome.
    return (
      <div className="storm-map__failure" role="status" data-map-state="error">
        <p>
          The map could not start ({this.state.error.message}). The county list, county card, portfolio and claim check still
          work.
        </p>
      </div>
    )
  }
}
