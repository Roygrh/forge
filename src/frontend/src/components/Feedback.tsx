import { ApiError, NetworkError } from '../api/client'
import { Mono } from './Json'

/** A quiet in-place loading state. */
export function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-5 py-6 text-sm text-slate-500">
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-500"
      />
      {label}
    </div>
  )
}

/**
 * A failure, rendered as what it is.
 *
 * The platform's error body is `{code, message, details}`, so the code is shown next to
 * the message: "the screen shows exactly what happened" is not a claim that stops being
 * true when something goes wrong.
 */
export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const code = error instanceof ApiError ? error.code : error instanceof NetworkError ? 'unreachable' : 'unexpected'
  const message = error instanceof Error ? error.message : String(error)
  const details = error instanceof ApiError ? error.details : undefined

  return (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-5 py-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-semibold text-rose-900">Request failed</span>
        <Mono>{code}</Mono>
      </div>
      <p className="mt-1.5 text-sm text-rose-800">{message}</p>
      {details !== undefined && (
        <pre className="mt-2 overflow-x-auto font-mono text-[12px] text-rose-900/80">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
      {onRetry !== undefined && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border border-rose-300 bg-white px-3 py-1.5 text-sm font-medium text-rose-800 transition-colors hover:bg-rose-100 focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none"
        >
          Try again
        </button>
      )}
    </div>
  )
}

/** Nothing to show, said calmly. */
export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {children !== undefined && <div className="mt-1.5 text-sm text-slate-500">{children}</div>}
    </div>
  )
}
