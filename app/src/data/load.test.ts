import { describe, expect, it } from 'vitest'
import { jsonResponse, makeFixtureFetcher, readFixtureJson } from '../test/fixtureFetch'
import { DataShapeError, loadIndex, loadStorm, MissingDataError } from './load'

const OPTIONS = { baseUrl: '/data/' }

describe('loadStorm', () => {
  it('loadStorm parses the Milton fixture', async () => {
    const { fetcher, calls } = makeFixtureFetcher()

    const data = await loadStorm('milton2024', { ...OPTIONS, fetcher })

    expect(data.meta.id).toBe('milton2024')
    expect(data.meta.role).toBe('lockbox')
    expect(data.meta.nights).toEqual([
      '2024-10-08',
      '2024-10-09',
      '2024-10-10',
      '2024-10-11',
      '2024-10-12',
      '2024-10-13',
    ])
    expect(data.meta.default_waiting_period).toBe(72)
    expect(data.counties.features.map((f) => f.properties.fips)).toEqual(['99001', '99003', '99005', '99007'])
    expect(data.counties.features[3]?.geometry.type).toBe('MultiPolygon')
    expect(data.counties.features[3]?.properties.customers).toBeNull()
    expect(data.states.features[0]?.properties.state).toBe('ZZ')
    expect(data.nights['99003']?.[3]).toEqual({
      night: '2024-10-11',
      status: 'cant_see',
      est: null,
      lo: null,
      hi: null,
      official: 0.31,
    })
    expect(data.restoration['99001']).toEqual({ est_lo: 3, est_hi: 4, official_day: 4 })
    expect(data.exposure['99005']?.at['72']).toBeNull()
    expect(data.exposure['99001']?.at['24']).toEqual([0.64, 0.81])
    expect(data.claims.map((c) => c.claim_id)).toEqual(['CLM-0001', 'CLM-0002', 'CLM-0003'])
    expect(data.scorecard.window).toBe(60)
    expect(data.scorecard.methods.isotonic.mae_pp).toBe(11.1)
    expect(data.scorecard.methods.wind_only.restore_day_err).toBeNull()
    expect(calls).toContain('/data/milton2024/nights.json')
    expect(calls).toHaveLength(8)
  })

  it('names the missing file in a readable error', async () => {
    const { fetcher } = makeFixtureFetcher({
      'milton2024/nights.json': () => new Response('Not found', { status: 404 }),
    })

    const result = loadStorm('milton2024', { ...OPTIONS, fetcher })

    await expect(result).rejects.toBeInstanceOf(MissingDataError)
    await expect(loadStorm('milton2024', { ...OPTIONS, fetcher })).rejects.toThrow(/milton2024\/nights\.json/)
  })

  it('treats an HTML fallback page as a missing file', async () => {
    const { fetcher } = makeFixtureFetcher({
      'milton2024/claims.json': () =>
        new Response('<!doctype html><title>app</title>', {
          status: 200,
          headers: { 'content-type': 'text/html' },
        }),
    })

    await expect(loadStorm('milton2024', { ...OPTIONS, fetcher })).rejects.toThrow(/claims\.json/)
  })

  it('reports a bare NaN as invalid JSON instead of crashing later', async () => {
    const { fetcher } = makeFixtureFetcher({
      'milton2024/exposure.json': () => jsonResponse('{"99001": {"home": NaN}}'),
    })

    await expect(loadStorm('milton2024', { ...OPTIONS, fetcher })).rejects.toThrow(/exposure\.json.*not valid JSON/)
  })

  it('rejects a bad shape with the file and field path', async () => {
    const nights = readFixtureJson<Record<string, Array<Record<string, unknown>>>>('milton/nights.json')
    const broken = {
      ...nights,
      '99001': [{ ...nights['99001']?.[0], status: 'zero' }, ...(nights['99001'] ?? []).slice(1)],
    }
    const { fetcher } = makeFixtureFetcher({
      'milton2024/nights.json': () => jsonResponse(JSON.stringify(broken)),
    })

    const result = loadStorm('milton2024', { ...OPTIONS, fetcher })

    await expect(result).rejects.toBeInstanceOf(DataShapeError)
    await expect(loadStorm('milton2024', { ...OPTIONS, fetcher })).rejects.toThrow(
      /nights\.json.*99001\[0\]\.status/,
    )
  })

  it('rejects meta.json written for a different storm', async () => {
    const meta = readFixtureJson<Record<string, unknown>>('milton/meta.json')
    const { fetcher } = makeFixtureFetcher({
      'milton2024/meta.json': () => jsonResponse(JSON.stringify({ ...meta, id: 'ian2022' })),
    })

    await expect(loadStorm('milton2024', { ...OPTIONS, fetcher })).rejects.toThrow(/ian2022/)
  })

  it('refuses storm ids that could escape the data folder', async () => {
    const { fetcher, calls } = makeFixtureFetcher()

    await expect(loadStorm('../secrets', { ...OPTIONS, fetcher })).rejects.toThrow(/storm id/)
    expect(calls).toHaveLength(0)
  })
})

describe('loadIndex', () => {
  it('reads the storm list', async () => {
    const { fetcher } = makeFixtureFetcher()

    const index = await loadIndex({ ...OPTIONS, fetcher })

    expect(index.storms).toEqual([
      { id: 'milton2024', name: 'Milton', landfall: '2024-10-09', role: 'lockbox', satellite: 'VNP46A2' },
    ])
  })

  it('reports a missing index as MissingDataError so the app can show its empty state', async () => {
    const { fetcher } = makeFixtureFetcher({
      'index.json': () => new Response('Not found', { status: 404 }),
    })

    await expect(loadIndex({ ...OPTIONS, fetcher })).rejects.toBeInstanceOf(MissingDataError)
  })
})
