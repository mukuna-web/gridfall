import { defineConfig, devices } from '@playwright/test'

// Not vite's default preview port (4173): `npm run preview` serves dist/ with
// every storm there, and reuseExistingServer would run the suite against it.
const PORT = 4188
const BASE_URL = `http://127.0.0.1:${PORT}/`

/**
 * Browser tests run against the built app: `npm run e2e:prepare` assembles a
 * small data set (the synthetic fixture and the committed Ian sample, never
 * a lockbox export) and builds it into dist-e2e, which `vite preview` serves
 * on a fixed port of its own. Chromium only; firefox and webkit are a
 * release-time local run (test plan WB-22). Specs wait on [data-map-state],
 * never on timeouts. No retries, and a trace is kept for every failure
 * (test plan §6), so a red run can be replayed.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx vite preview --outDir dist-e2e --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
