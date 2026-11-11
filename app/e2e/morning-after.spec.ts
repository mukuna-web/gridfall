import { existsSync, readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { expectNoErrors, MAP_SETTLED, openStorm, SAMPLE_STORM, watchErrors } from './helpers'

/** The synthetic contract fixture, copied in by prepare-e2e-data.mjs when the repo has it. */
const SYNTH_STORM = 'synth2099'
const SYNTH_GOLDEN = new URL(`../.e2e/public/data/${SYNTH_STORM}/expected_exposure.json`, import.meta.url)

interface ExpectedExposureFile {
  readonly [hour: string]: { readonly low: number; readonly high: number; readonly unknown_policies: number }
}

interface ExposureFile {
  readonly [fips: string]: {
    readonly home: number
    readonly business: number
    readonly at: { readonly [hour: string]: readonly [number, number] | null }
  }
}

/**
 * The portfolio headline at an hour mark, computed by hand from the exposure
 * file the page is served (policies × bracket, seen counties only), so the
 * test does not borrow the app's own arithmetic.
 */
function policiesOutAt(hour: string): { readonly low: number; readonly high: number } {
  const file = new URL(`../.e2e/public/data/${SAMPLE_STORM}/exposure.json`, import.meta.url)
  const exposure = JSON.parse(readFileSync(file, 'utf8')) as ExposureFile
  return Object.values(exposure).reduce(
    (sum, county) => {
      const bracket = county.at[hour]
      if (!bracket) return sum
      const policies = county.home + county.business
      return { low: sum.low + policies * Math.min(...bracket), high: sum.high + policies * Math.max(...bracket) }
    },
    { low: 0, high: 0 },
  )
}

const count = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

test('storm walkthrough: map, county card, portfolio at 72 h, flag a claim, reload', async ({ page }) => {
  const errors = watchErrors(page)
  await openStorm(page, SAMPLE_STORM)

  // The map drew, the report names the storm, and the slider opens on the first pass after landfall.
  await expect(page.locator('[data-map-state]').first()).toHaveAttribute('data-map-state', 'ready')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Hurricane Ian/)
  const slider = page.getByRole('slider', { name: 'Night' })
  await expect(slider).toHaveAttribute('aria-valuetext', /first pass after landfall/)

  // Pick a county from the list. On the landfall night the sample is under
  // cloud, so the card says so in words with no figure at all...
  await page.getByRole('combobox', { name: 'County', exact: true }).selectOption({ label: 'Lee, FL' })
  await expect(page.getByRole('heading', { level: 3, name: /Lee, FL/ })).toBeVisible()
  const headline = page.getByTestId('county-headline')
  await expect(headline).toContainText("can't see")
  await expect(headline).not.toContainText(/\d/)
  // ...and one night later it leads with the range, then the point estimate.
  await slider.focus()
  await page.keyboard.press('ArrowRight')
  await expect(slider).toHaveAttribute('aria-valuetext', /day 1 after landfall/)
  await expect(headline).toContainText(/^\d+–\d+%/)
  await expect(headline).toContainText(/point estimate \d+%/)

  // Portfolio: set the waiting period to 72 h and read the headline range.
  await page.getByLabel('48 h').check()
  await page.getByLabel('72 h').check()
  const { low, high } = policiesOutAt('72')
  const portfolio = page.getByRole('heading', { name: /Expected policies without power at hour 72/ })
  await expect(portfolio).toContainText(count.format(Math.round((low + high) / 2)))
  await expect(portfolio).toContainText(`(${count.format(Math.round(low))}–${count.format(Math.round(high))})`)

  // Claim check: it opens on the first claim that needs a look, worded as a
  // comparison with the county, never as an accusation; then pick a claim and flag it.
  await expect(page.getByTestId('claim-verdict')).toHaveText(/^longer than \d+% of the county: review$/)
  const claimPicker = page.getByRole('combobox', { name: 'Claim', exact: true })
  await claimPicker.selectOption('C0003')
  await page.getByRole('button', { name: 'Flag for review' }).click()
  await expect(page.getByText('Flagged for review')).toBeVisible()
  await expect(page.getByText(/1 flagged for this storm/)).toBeVisible()

  // Reload: the flag survives, kept under this storm's id.
  await page.reload()
  await page.locator(MAP_SETTLED).first().waitFor()
  await claimPicker.selectOption('C0003')
  await expect(page.getByText('Flagged for review')).toBeVisible()
  const stored = await page.evaluate(() => window.localStorage.getItem('bfs.flags.v2'))
  expect(JSON.parse(stored ?? 'null')).toEqual({ [SAMPLE_STORM]: ['C0003'] })

  expectNoErrors(errors, 'storm walkthrough')
})

test('the hour-72 headline equals the golden expected policies out for the synthetic storm', async ({ page }) => {
  test.skip(!existsSync(SYNTH_GOLDEN), `${SYNTH_STORM} is not in the e2e data set (tests/fixtures/contract/${SYNTH_STORM} absent)`)
  const golden = (JSON.parse(readFileSync(SYNTH_GOLDEN, 'utf8')) as ExpectedExposureFile)['72']
  if (!golden) throw new Error('expected_exposure.json has no "72" entry')

  await openStorm(page, SYNTH_STORM, '&hours=72')

  const portfolio = page.getByRole('heading', { name: /Expected policies without power at hour 72/ })
  await expect(portfolio).toContainText(count.format(Math.round((golden.low + golden.high) / 2)))
  await expect(portfolio).toContainText(`(${count.format(Math.round(golden.low))}–${count.format(Math.round(golden.high))})`)
  await expect(page.getByTestId('unknown-policies')).toContainText(`${count.format(golden.unknown_policies)} policies`)
})
