import type { StormMeta } from '../types'

/** The honest small print: sources, licence, what is synthetic, what hatching means. */
export function DataNote({ meta }: { readonly meta: StormMeta | null }) {
  return (
    <footer className="data-note">
      <p>
        <span className="label">Data</span> Official outage counts: EAGLE-I (Oak Ridge National Laboratory), licensed CC BY 4.0.
        Night lights: NASA Black Marble. County shapes and housing units: U.S. Census Bureau.
      </p>
      <p>
        <span className="label">Read with care</span> Estimates are county-level; the policy portfolio and claims are synthetic.
        Hatched counties are ones the satellite can't see (clouds) or can't measure (too dark): unknown, never counted as 0%.
        A review flag asks for a closer look and is never a finding about a claimant.
      </p>
      {meta && meta.notes.length > 0 ? (
        <ul className="data-note__notes">
          {meta.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </footer>
  )
}
