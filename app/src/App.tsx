import { useState } from 'react'
import type { ReactNode } from 'react'
import { DataNote } from './components/DataNote'
import { EmptyState } from './components/EmptyState'
import { Masthead } from './components/Masthead'
import { Notice } from './components/Notice'
import { StormReport } from './components/StormReport'
import { loadIndex, loadStorm, MissingDataError } from './data/load'
import { useAsyncResource } from './hooks/useAsyncResource'
import type { UrlState } from './lib/urlState'
import { parseUrlState } from './lib/urlState'
import type { StormIndexEntry } from './types'

function Loading({ label }: { readonly label: string }) {
  return (
    <p className="loading" role="status">
      {label}
    </p>
  )
}

/** Frame for the states before a storm is chosen: loading, empty, or a broken index. */
function Shell({ children }: { readonly children: ReactNode }) {
  return (
    <div className="page">
      <header className="masthead masthead--bare">
        <p className="masthead__kicker label">Gridfall · Storm outage report</p>
      </header>
      <main className="report" id="main">
        {children}
      </main>
      <DataNote meta={null} />
    </div>
  )
}

interface View {
  readonly stormId: string
  /** URL view state to start the storm's report from. */
  readonly initial: UrlState
}

function Report({ storms, first }: { readonly storms: readonly StormIndexEntry[]; readonly first: StormIndexEntry }) {
  const [view, setView] = useState<View>(() => {
    const initial = parseUrlState(window.location.search)
    return { stormId: storms.some((s) => s.id === initial.storm) ? (initial.storm as string) : first.id, initial }
  })
  const storm = storms.find((s) => s.id === view.stormId) ?? first
  const resource = useAsyncResource((signal) => loadStorm(storm.id, { signal }), storm.id)
  const meta = resource.status === 'ready' ? resource.data.meta : null
  // The URL holds the last view when the storm changes, so a county, waiting
  // period or toggle that also fits the new storm carries over.
  const changeStorm = (stormId: string) => setView({ stormId, initial: parseUrlState(window.location.search) })

  return (
    <div className="page">
      <Masthead storms={storms} storm={storm} meta={meta} onStormChange={changeStorm} />
      {resource.status === 'ready' ? (
        <StormReport key={storm.id} data={resource.data} initial={view.initial} />
      ) : (
        <main className="report" id="main">
          {resource.status === 'error' ? (
            <Notice title={`Could not load ${storm.name}`} error={resource.error} onRetry={resource.retry} />
          ) : (
            <Loading label={`Loading ${storm.name}…`} />
          )}
        </main>
      )}
      <DataNote meta={meta} />
    </div>
  )
}

/** Reads the storm list, then shows the first (or the linked) storm's report. */
export default function App() {
  const index = useAsyncResource((signal) => loadIndex({ signal }), 'index')

  if (index.status === 'loading') {
    return (
      <Shell>
        <Loading label="Loading the storm list…" />
      </Shell>
    )
  }
  if (index.status === 'error') {
    return (
      <Shell>
        {index.error instanceof MissingDataError ? (
          <EmptyState />
        ) : (
          <Notice title="Could not read the storm list" error={index.error} onRetry={index.retry} />
        )}
      </Shell>
    )
  }
  const first = index.data.storms[0]
  if (!first) {
    return (
      <Shell>
        <EmptyState />
      </Shell>
    )
  }
  return <Report storms={index.data.storms} first={first} />
}
