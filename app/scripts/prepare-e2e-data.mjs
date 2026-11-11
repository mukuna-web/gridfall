#!/usr/bin/env node
/**
 * Assembles the data the browser tests run against, into app/.e2e/public/.
 *
 * `vite build --mode e2e` serves that folder as its public dir instead of
 * public/, so the e2e suite reads only:
 *   - tests/fixtures/contract/synth2099, the synthetic contract fixture, when it exists;
 *   - app/public/data/ian2022_sample, the committed Ian sample (Lee, Charlotte, Collier).
 * It never copies a lockbox or full-storm export, and it refuses any storm
 * that is neither the sample nor marked synthetic by a "synth" id.
 *
 * Usage: node scripts/prepare-e2e-data.mjs
 */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const APP = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const REPO = resolve(APP, '..')
const OUT = join(APP, '.e2e', 'public')
const SAMPLE_ID = 'ian2022_sample'
const STORM_FILES = [
  'meta.json',
  'counties.geojson',
  'states.geojson',
  'nights.json',
  'restoration.json',
  'exposure.json',
  'claims.json',
  'scorecard.json',
]
const SOURCES = [
  { id: 'synth2099', dir: join(REPO, 'tests', 'fixtures', 'contract', 'synth2099'), required: false },
  { id: SAMPLE_ID, dir: join(APP, 'public', 'data', SAMPLE_ID), required: true },
]

/** Only the sample and synthetic fixtures may feed the browser tests. */
function isAllowed(id) {
  return id === SAMPLE_ID || /^synth[a-z0-9_-]*$/.test(id)
}

/** Reads and checks one storm folder; returns its index entry. */
function indexEntry(dir, id) {
  const missing = STORM_FILES.filter((file) => !existsSync(join(dir, file)))
  if (missing.length > 0) throw new Error(`${dir} is missing ${missing.join(', ')}`)
  const meta = JSON.parse(readFileSync(join(dir, 'meta.json'), 'utf8'))
  if (meta.id !== id) throw new Error(`${join(dir, 'meta.json')} describes "${meta.id}", expected "${id}"`)
  if (!isAllowed(id)) throw new Error(`refusing ${id}: only ${SAMPLE_ID} and synth* fixtures may feed the browser tests`)
  for (const key of ['name', 'landfall', 'role', 'satellite']) {
    if (typeof meta[key] !== 'string') throw new Error(`${join(dir, 'meta.json')} has no string "${key}"`)
  }
  return { id: meta.id, name: meta.name, landfall: meta.landfall, role: meta.role, satellite: meta.satellite }
}

function main() {
  rmSync(OUT, { recursive: true, force: true })
  mkdirSync(join(OUT, 'data'), { recursive: true })
  const storms = []
  for (const source of SOURCES) {
    if (!existsSync(source.dir)) {
      if (source.required) throw new Error(`${source.dir} is missing; it is committed, so this checkout is incomplete`)
      console.log(`prepare-e2e-data: ${source.id} is not present at ${source.dir}; skipped`)
      continue
    }
    storms.push(indexEntry(source.dir, source.id))
    cpSync(source.dir, join(OUT, 'data', source.id), { recursive: true })
  }
  writeFileSync(join(OUT, 'data', 'index.json'), `${JSON.stringify({ storms }, null, 2)}\n`)
  const favicon = join(APP, 'public', 'favicon.svg')
  if (existsSync(favicon)) cpSync(favicon, join(OUT, 'favicon.svg'))
  console.log(`prepare-e2e-data: wrote ${OUT} with ${storms.map((s) => s.id).join(', ')}`)
}

try {
  main()
} catch (error) {
  console.error(`prepare-e2e-data: ${error instanceof Error ? error.message : String(error)}`)
  process.exit(1)
}
