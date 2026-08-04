import { formatJson } from '../lib/format'

/**
 * A JSON value shown verbatim.
 *
 * Verbatim is the point: args, results and event payloads are audit material, so they
 * are rendered as they were recorded rather than summarised into prose that could be
 * subtly wrong. Wide content scrolls inside the block; the page never scrolls sideways.
 */
export function JsonBlock({ value, label }: { value: unknown; label?: string }) {
  return (
    <div className="min-w-0">
      {label !== undefined && (
        <div className="mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase">
          {label}
        </div>
      )}
      <pre className="overflow-x-auto rounded-md bg-slate-900/95 px-3 py-2.5 font-mono text-[12px] leading-relaxed text-slate-100">
        {formatJson(value)}
      </pre>
    </div>
  )
}

/** A short inline identifier — a tool ref, a model id, a run id. */
export function Mono({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-slate-700"
    >
      {children}
    </span>
  )
}
