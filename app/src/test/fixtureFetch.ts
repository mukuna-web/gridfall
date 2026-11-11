import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), '..', '__fixtures__')

/** Reads a synthetic fixture file (path relative to src/__fixtures__). */
export function readFixture(relativePath: string): string {
  return readFileSync(join(FIXTURES, relativePath), 'utf8')
}

/** Parses a synthetic fixture file as JSON. */
export function readFixtureJson<T>(relativePath: string): T {
  return JSON.parse(readFixture(relativePath)) as T
}

export function jsonResponse(body: string, status = 200): Response {
  return new Response(body, { status, headers: { 'content-type': 'application/json' } })
}

export function notFound(): Response {
  return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain' } })
}

/** Factories, because a Response body can only be read once. */
export type Overrides = Readonly<Record<string, () => Response>>

/**
 * A fetch stand-in serving `<anything>/data/index.json` and
 * `<anything>/data/milton2024/<file>` from src/__fixtures__, so loader and
 * app tests never touch the network or real exports.
 */
export function makeFixtureFetcher(overrides: Overrides = {}) {
  const calls: string[] = []
  const fetcher = async (input: string | URL | Request): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    calls.push(url)
    const name = url.replace(/^.*?data\//, '')
    const override = overrides[name]
    if (override) return override()
    const local = name === 'index.json' ? 'index.json' : name.replace(/^milton2024\//, 'milton/')
    try {
      return jsonResponse(readFixture(local))
    } catch {
      return notFound()
    }
  }
  return { fetcher, calls }
}
