/**
 * Fetches and validates the static files the pipeline exports.
 *
 * There is no server: everything is a plain file under public/data/. A
 * missing file is the most common failure (the pipeline hasn't exported that
 * storm yet), so it gets its own error type and a message that says which
 * file and how to make it, rather than a JSON parse error about "<".
 */
import type { StormData, StormFileKey, StormIndex } from '../types'
import { STORM_FILES } from '../types'
import { DataShapeError, parseIndex, parseStormFiles, STORM_ID, stormFileLabel } from './validate'

export { DataShapeError } from './validate'

export type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

export interface LoadOptions {
  /** Defaults to the global fetch, looked up at call time. */
  readonly fetcher?: Fetcher
  /** Folder that holds index.json and one folder per storm. */
  readonly baseUrl?: string
  readonly signal?: AbortSignal
}

/** A data file that isn't there (404, or a dev server's HTML fallback page). */
export class MissingDataError extends Error {
  readonly file: string

  constructor(file: string, detail: string) {
    super(`Missing data file ${file}: ${detail}`)
    this.name = 'MissingDataError'
    this.file = file
  }
}

/** The network or server failed for a reason other than a missing file. */
export class DataLoadError extends Error {
  readonly file: string

  constructor(file: string, detail: string) {
    super(`Could not load ${file}: ${detail}`)
    this.name = 'DataLoadError'
    this.file = file
  }
}

const EXPORT_HINT = 'run `uv run blackout export --storm <id>` (or `--sample`) to write it'

function defaultBaseUrl(): string {
  return `${import.meta.env.BASE_URL}data/`
}

function withTrailingSlash(url: string): string {
  return url.endsWith('/') ? url : `${url}/`
}

async function fetchJson(url: string, label: string, options: LoadOptions): Promise<unknown> {
  const fetcher: Fetcher = options.fetcher ?? ((u, init) => fetch(u, init))
  let response: Response
  try {
    // Asking for JSON only also stops Vite's dev server from answering a
    // missing file with index.html.
    response = await fetcher(url, { signal: options.signal, headers: { Accept: 'application/json' } })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new DataLoadError(label, error instanceof Error ? error.message : String(error))
  }
  if (response.status === 404) throw new MissingDataError(label, `not found (HTTP 404); ${EXPORT_HINT}`)
  if (!response.ok) throw new DataLoadError(label, `HTTP ${response.status}`)
  if ((response.headers.get('content-type') ?? '').includes('text/html')) {
    throw new MissingDataError(label, `the server sent a web page instead of JSON, so the file is probably missing; ${EXPORT_HINT}`)
  }
  const text = await response.text()
  try {
    return JSON.parse(text) as unknown
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    throw new DataShapeError(label, `not valid JSON (${reason}); a bare NaN or Infinity from Python is the usual cause`)
  }
}

/** Reads index.json, the list of exported storms. */
export async function loadIndex(options: LoadOptions = {}): Promise<StormIndex> {
  const base = withTrailingSlash(options.baseUrl ?? defaultBaseUrl())
  const label = 'data/index.json'
  return parseIndex(await fetchJson(`${base}index.json`, label, options), label)
}

/** Fetches a storm's eight files in parallel and validates them together. */
export async function loadStorm(id: string, options: LoadOptions = {}): Promise<StormData> {
  if (!STORM_ID.test(id)) throw new Error(`Not a valid storm id: ${JSON.stringify(id)}`)
  const base = withTrailingSlash(options.baseUrl ?? defaultBaseUrl())
  const keys = Object.keys(STORM_FILES) as StormFileKey[]
  const values = await Promise.all(
    keys.map((key) => fetchJson(`${base}${id}/${STORM_FILES[key]}`, stormFileLabel(id, key), options)),
  )
  const raw = Object.fromEntries(keys.map((key, i) => [key, values[i]])) as Record<StormFileKey, unknown>
  return parseStormFiles(id, raw)
}
