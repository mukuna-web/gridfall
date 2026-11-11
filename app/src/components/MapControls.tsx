import { useMemo } from 'react'
import type { CountyCollection } from '../types'

/** Switch between estimates only and estimates with official dots. */
export function OfficialToggle({ checked, onChange }: { readonly checked: boolean; readonly onChange: (on: boolean) => void }) {
  return (
    <label className="toggle">
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle__track" aria-hidden="true" />
      <span className="toggle__text">Official numbers</span>
    </label>
  )
}

/** Keyboard route to every county: the map canvas itself can't be tabbed through county by county. */
export function CountyPicker({
  counties,
  value,
  onChange,
}: {
  readonly counties: CountyCollection
  readonly value: string | null
  readonly onChange: (fips: string) => void
}) {
  const options = useMemo(
    () =>
      counties.features
        .map((f) => ({ fips: f.properties.fips, label: `${f.properties.name}, ${f.properties.state}` }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [counties],
  )
  return (
    <label className="picker picker--county">
      <span className="label">County</span>
      <select className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        {value === null ? <option value="">Choose a county</option> : null}
        {options.map((o) => (
          <option key={o.fips} value={o.fips}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}
