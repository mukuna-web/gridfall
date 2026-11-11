import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { APIRequestContext } from '@playwright/test'
import { expectNoErrors, openStorm, SAMPLE_STORM, watchErrors } from './helpers'

interface IndexFile {
  readonly storms: ReadonlyArray<{ readonly id: string; readonly name: string }>
}

interface MetaFile {
  readonly landfall: string
  readonly nights: readonly string[]
}

async function readIndex(request: APIRequestContext): Promise<IndexFile> {
  const response = await request.get('./data/index.json')
  expect(response.ok(), `index.json answered ${response.status()}`).toBe(true)
  return (await response.json()) as IndexFile
}

test.describe('the e2e data set', () => {
  test('index.json loads and holds only the sample and synthetic storms', async ({ request }) => {
    const index = await readIndex(request)

    const ids = index.storms.map((s) => s.id)
    expect(ids).toContain(SAMPLE_STORM)
    // Never a lockbox or full-storm export: the suite must not depend on them.
    for (const id of ids) expect(id).toMatch(/^(ian2022_sample|synth[a-z0-9_-]*)$/)
  })

  test('every storm in the index opens with its map and county card and no console error', async ({ page, request }) => {
    const index = await readIndex(request)
    const errors = watchErrors(page)

    for (const storm of index.storms) {
      await openStorm(page, storm.id)

      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await expect(page.locator('[data-map-state]').first()).toHaveAttribute('data-map-state', 'ready')
      await expect(page.getByTestId('county-headline')).toBeVisible()
      expectNoErrors(errors, storm.id)
    }
  })

  test('the quickstart sample renders estimates: a numeric county range and a portfolio figure', async ({ page, request }) => {
    // The night after landfall: the first the satellite could see through Ian's cloud.
    const meta = (await (await request.get(`./data/${SAMPLE_STORM}/meta.json`)).json()) as MetaFile
    const nextNight = meta.nights[meta.nights.indexOf(meta.landfall) + 1]
    if (!nextNight) throw new Error('the sample has no night after landfall')

    await openStorm(page, SAMPLE_STORM, `&night=${nextNight}`)

    await expect(page.getByTestId('county-headline')).toContainText(/^\d+–\d+%/)
    const portfolio = page.getByRole('heading', { name: /Expected policies without power at hour/ })
    await expect(portfolio).toContainText(/\d/)
    await expect(portfolio).not.toContainText('—')
  })

  test('no horizontal overflow at 375 px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await openStorm(page, SAMPLE_STORM)

    const widths = await page.evaluate(() => {
      // Name what sticks out, so a failure says which element to fix.
      const offenders = [...document.querySelectorAll('body *')]
        .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
        .map((el) => `${el.tagName.toLowerCase()}.${el.className} right=${Math.round(el.getBoundingClientRect().right)}`)
      return {
        document: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
        viewport: window.innerWidth,
        offenders: offenders.slice(0, 8),
      }
    })

    expect(widths.document, JSON.stringify(widths, null, 1)).toBeLessThanOrEqual(widths.viewport)
    expect(widths.body, JSON.stringify(widths, null, 1)).toBeLessThanOrEqual(widths.viewport)
  })

  test('the night slider works from the keyboard: End, Home and the arrows', async ({ page, request }) => {
    const meta = (await (await request.get(`./data/${SAMPLE_STORM}/meta.json`)).json()) as MetaFile
    await openStorm(page, SAMPLE_STORM)
    const slider = page.getByRole('slider', { name: 'Night' })
    const last = String(meta.nights.length - 1)

    await slider.focus()
    await page.keyboard.press('End')
    await expect(slider).toHaveValue(last)
    await expect(page).toHaveURL(new RegExp(`night=${meta.nights[meta.nights.length - 1]}`))

    await page.keyboard.press('Home')
    await expect(slider).toHaveValue('0')
    await expect(page).toHaveURL(new RegExp(`night=${meta.nights[0]}`))

    await page.keyboard.press('ArrowRight')
    await expect(slider).toHaveValue('1')
    await page.keyboard.press('ArrowLeft')
    await expect(slider).toHaveValue('0')
  })

  test('axe-core finds no serious or critical violations on the report', async ({ page }) => {
    await openStorm(page, SAMPLE_STORM)

    const results = await new AxeBuilder({ page }).analyze()

    const blocking = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(blocking.map((v) => `${v.id} (${v.impact}): ${v.help}; ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
  })
})
