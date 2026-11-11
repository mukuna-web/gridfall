/**
 * "Flag for review", saved in the browser, per storm.
 *
 * Claim ids repeat across storms (C0001 exists in every export), so flags
 * are kept under the storm id: `bfs.flags.v2` holds `{ "<storm id>": [ids] }`.
 * The first release wrote one flat list under `bfs.flags.v1` with no storm;
 * those ids are carried over under the key "*" and show in every storm, as
 * they did then, until they are removed.
 *
 * localStorage can throw on read or write (private mode, disabled cookies,
 * a full quota), and even touching `window.localStorage` can throw. A flag
 * must still work, so the store keeps a session copy in memory, tries
 * storage inside try/catch, and reports whether the last attempt persisted.
 * Garbage in storage is not a storage failure: it reads as no flags and the
 * next save replaces it.
 */

export const FLAGS_KEY = 'bfs.flags.v2'
/** The flat list the first release wrote; its ids had no storm. */
export const LEGACY_FLAGS_KEY = 'bfs.flags.v1'
/** Bucket for carried-over flags: they show in every storm. */
const EVERY_STORM = '*'

export type FlagStorage = Pick<Storage, 'getItem' | 'setItem'>

type FlagsByStorm = Readonly<Record<string, readonly string[]>>

export interface FlagStore {
  loadFlags(): string[]
  saveFlag(claimId: string): void
  clearFlag(claimId: string): void
  /** False when the browser refused storage: flags last for this session only. */
  isPersistent(): boolean
}

function stringList(value: unknown): readonly string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
}

/** Parsed JSON, or null for nothing stored or text that is not JSON. */
function parseJson(raw: string | null): unknown {
  if (raw === null) return null
  try {
    return JSON.parse(raw) as unknown
  } catch {
    return null
  }
}

/** The per-storm record, or the old flat list carried over when there is no record yet. */
function readStored(storage: FlagStorage): FlagsByStorm {
  const record = parseJson(storage.getItem(FLAGS_KEY))
  if (typeof record === 'object' && record !== null && !Array.isArray(record)) {
    return Object.fromEntries(Object.entries(record).map(([storm, ids]) => [storm, stringList(ids)]))
  }
  const legacy = stringList(parseJson(storage.getItem(LEGACY_FLAGS_KEY)))
  return legacy.length > 0 ? { [EVERY_STORM]: legacy } : {}
}

/** One storm's flags: the carried-over ones first, then its own, each once. */
function flagsFor(all: FlagsByStorm, stormId: string): readonly string[] {
  return [...new Set([...(all[EVERY_STORM] ?? []), ...(all[stormId] ?? [])])]
}

/** A new record with `claimId` added to this storm. */
function withFlag(all: FlagsByStorm, stormId: string, claimId: string): FlagsByStorm {
  return { ...all, [stormId]: [...(all[stormId] ?? []), claimId] }
}

/**
 * A new record without `claimId` in this storm or in the carried-over
 * bucket (where it showed everywhere); other storms keep theirs.
 */
function withoutFlag(all: FlagsByStorm, stormId: string, claimId: string): FlagsByStorm {
  const entries = Object.entries(all)
    .map(([storm, ids]): [string, readonly string[]] =>
      storm === stormId || storm === EVERY_STORM ? [storm, ids.filter((id) => id !== claimId)] : [storm, ids],
    )
    .filter(([, ids]) => ids.length > 0)
  return Object.fromEntries(entries)
}

export function createFlagStore(getStorage: () => FlagStorage | null | undefined, stormId: string): FlagStore {
  let memory: FlagsByStorm = {}
  let readFailed = false
  // After a failed write, storage no longer holds this session's flags, so
  // memory stays the source of truth until a write succeeds again.
  let writeFailed = false

  const read = (): FlagsByStorm => {
    if (writeFailed) return memory
    try {
      const storage = getStorage()
      if (!storage) throw new Error('no storage')
      memory = readStored(storage)
      readFailed = false
    } catch {
      // Unreadable storage: keep serving this session's flags.
      readFailed = true
    }
    return memory
  }

  const write = (next: FlagsByStorm): void => {
    memory = next
    try {
      const storage = getStorage()
      if (!storage) throw new Error('no storage')
      storage.setItem(FLAGS_KEY, JSON.stringify(next))
      writeFailed = false
    } catch {
      // The flag still holds for this session; isPersistent() tells the UI.
      writeFailed = true
    }
  }

  return {
    loadFlags: () => [...flagsFor(read(), stormId)],
    saveFlag: (claimId) => {
      const all = read()
      if (!flagsFor(all, stormId).includes(claimId)) write(withFlag(all, stormId, claimId))
    },
    clearFlag: (claimId) => write(withoutFlag(read(), stormId, claimId)),
    isPersistent: () => !readFailed && !writeFailed,
  }
}

/** The store the app uses: this storm's flags in the browser's localStorage. */
export function createBrowserFlagStore(stormId: string): FlagStore {
  return createFlagStore(() => window.localStorage, stormId)
}
