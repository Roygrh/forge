import { useCallback, useEffect, useState } from 'react'

/**
 * Load something once, with a retry.
 *
 * Deliberately not a data-fetching library: this SPA makes four calls in total and none
 * of them caches, so a hook that tracks three states and cancels a stale response is the
 * whole requirement. The `cancelled` flag matters under React 18 StrictMode, where
 * effects run twice in development.
 */

export type AsyncState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: unknown }
  | { status: 'ready'; data: T }

export function useAsync<T>(load: () => Promise<T>): {
  state: AsyncState<T>
  reload: () => void
} {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })

    load().then(
      (data) => {
        if (!cancelled) setState({ status: 'ready', data })
      },
      (error: unknown) => {
        if (!cancelled) setState({ status: 'error', error })
      },
    )

    return () => {
      cancelled = true
    }
    // `load` must be a stable callback from the caller (useCallback); `attempt` is what
    // reload() bumps to run this again.
  }, [load, attempt])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  return { state, reload }
}
