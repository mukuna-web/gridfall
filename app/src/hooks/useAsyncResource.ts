import { useEffect, useState } from 'react'

export type Resource<T> =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly data: T }
  | { readonly status: 'error'; readonly error: Error }

interface Settled<T> {
  readonly token: string
  readonly resource: Resource<T>
}

const LOADING = { status: 'loading' } as const

function toError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value))
}

/**
 * Runs `load` whenever `key` changes (or on retry) and returns its state.
 * A superseded request is aborted and its result ignored, so switching
 * storms quickly can never show the previous storm's data.
 */
export function useAsyncResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  key: string,
): Resource<T> & { readonly retry: () => void } {
  const [attempt, setAttempt] = useState(0)
  const [settled, setSettled] = useState<Settled<T> | null>(null)
  const token = `${key}#${attempt}`

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ token, resource: { status: 'ready', data } })
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setSettled({ token, resource: { status: 'error', error: toError(error) } })
      },
    )
    return () => controller.abort()
    // `load` is derived from `key`, which `token` already tracks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const resource: Resource<T> = settled?.token === token ? settled.resource : LOADING
  return { ...resource, retry: () => setAttempt((n) => n + 1) }
}
