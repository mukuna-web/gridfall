import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Run every test in a zone west of UTC. The pipeline writes calendar dates
// (YYYY-MM-DD, UTC), so any code that slips into local time shows up here as
// an off-by-one night instead of passing silently on a UTC machine.
process.env.TZ = 'America/Los_Angeles'

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})
