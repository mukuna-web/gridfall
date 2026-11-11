import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

/** The committed Ian sample (Lee, Charlotte, Collier): the storm every e2e run has. */
export const SAMPLE_STORM = 'ian2022_sample'

/** The map has either drawn or reported why it could not; specs wait on this, never on time. */
export const MAP_SETTLED = '[data-map-state="ready"], [data-map-state="error"]'

export interface PageErrors {
  readonly console: readonly string[]
  readonly pageErrors: readonly string[]
  readonly failedRequests: readonly string[]
}

/** Collects console errors, uncaught exceptions and failed requests from now on. */
export function watchErrors(page: Page): PageErrors {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const failedRequests: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('requestfailed', (request) => {
    const reason = request.failure()?.errorText ?? ''
    // An aborted fetch is the app cancelling a superseded load, not a failure.
    if (reason.includes('ERR_ABORTED')) return
    failedRequests.push(`${request.url()} ${reason}`)
  })
  return { console: consoleErrors, pageErrors, failedRequests }
}

export function expectNoErrors(errors: PageErrors, where: string): void {
  expect(errors.pageErrors, `${where}: uncaught exceptions`).toEqual([])
  expect(errors.console, `${where}: console errors`).toEqual([])
  expect(errors.failedRequests, `${where}: failed requests`).toEqual([])
}

/** Opens one storm's report and waits until the map has drawn or reported its failure. */
export async function openStorm(page: Page, stormId: string, query = ''): Promise<void> {
  await page.goto(`./?storm=${stormId}${query}`)
  await page.locator(MAP_SETTLED).first().waitFor()
}
