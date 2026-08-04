/**
 * A collapsible section, built on `<details>`.
 *
 * Native rather than state-driven: it stays keyboard-accessible and findable by the
 * browser's own in-page search with no code of ours to get wrong.
 */
export function Disclosure({
  summary,
  hint,
  defaultOpen = false,
  children,
}: {
  summary: React.ReactNode
  hint?: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  return (
    <details open={defaultOpen} className="group">
      <summary className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-sm font-medium text-slate-600 transition-colors select-none hover:text-slate-900 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:outline-none">
        <svg
          viewBox="0 0 20 20"
          aria-hidden="true"
          className="h-3.5 w-3.5 shrink-0 fill-current transition-transform group-open:rotate-90"
        >
          <path d="M7 4l6 6-6 6z" />
        </svg>
        <span>{summary}</span>
        {hint !== undefined && <span className="font-normal text-slate-400">{hint}</span>}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  )
}
