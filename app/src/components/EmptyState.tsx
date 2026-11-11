const COMMANDS = ['uv run blackout export --sample        # bundled Ian sample', 'uv run blackout export --storm ian2022'].join('\n')

/** Shown until the pipeline has exported at least one storm. */
export function EmptyState() {
  return (
    <section className="empty-state" aria-labelledby="empty-title">
      <p className="label">Nothing to report yet</p>
      <h2 className="empty-state__title" id="empty-title">
        No storms exported yet
      </h2>
      <p className="empty-state__body">
        This app reads static files from <code>app/public/data/</code>. Write them with the pipeline from the repo root, then
        reload this page:
      </p>
      <pre className="empty-state__code">
        <code>{COMMANDS}</code>
      </pre>
    </section>
  )
}
