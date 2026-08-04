import { ACTING_ROLE, apiBaseUrl } from '../api/client'
import { humanize } from '../lib/format'

/**
 * The application chrome.
 *
 * The header states two things on every screen because both are part of the story
 * rather than debug output: which role this session is acting as (NFR-5 — segregation
 * of duties, made visible), and which API it is reading. A demo that cannot show where
 * its data came from is asking to be taken on trust.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-4">
          <a href="#/" className="group flex items-center gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-sm font-bold text-white">
              F
            </span>
            <span>
              <span className="block text-sm leading-tight font-semibold text-slate-900 group-hover:text-indigo-700">
                Forge
              </span>
              <span className="block text-xs leading-tight text-slate-500">
                Governed agent factory
              </span>
            </span>
          </a>

          <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-500">
            <span title="Sent as X-Forge-Role on every request. Segregation of duties, not authentication.">
              Acting as{' '}
              <span className="font-medium text-slate-700">{humanize(ACTING_ROLE)}</span>
            </span>
            <span title="Configured with VITE_API_BASE_URL">
              API <span className="font-mono text-slate-600">{apiBaseUrl}</span>
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">{children}</main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 py-4 text-xs text-slate-400">
          Phase 3.3 — the walking skeleton, end to end. Traces are projections of the
          append-only event log (ADR-008). Agent authoring, approvals, knowledge and evals
          arrive in Phase 4.
        </div>
      </footer>
    </div>
  )
}

/** A page title with an optional lead paragraph and trailing actions. */
export function PageHeading({
  eyebrow,
  title,
  lead,
  actions,
}: {
  eyebrow?: string
  title: string
  lead?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-2xl">
        {eyebrow !== undefined && (
          <p className="text-xs font-medium tracking-wider text-indigo-600 uppercase">{eyebrow}</p>
        )}
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {lead !== undefined && <p className="mt-2 text-sm leading-relaxed text-slate-600">{lead}</p>}
      </div>
      {actions !== undefined && <div className="flex items-center gap-3">{actions}</div>}
    </div>
  )
}

/** The one button style in the app: a primary action, or a quiet secondary one. */
export function Button({
  variant = 'primary',
  disabled = false,
  onClick,
  children,
}: {
  variant?: 'primary' | 'secondary'
  disabled?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  const base =
    'inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50'
  const variants = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-500 focus-visible:ring-indigo-500',
    secondary:
      'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 focus-visible:ring-slate-400',
  }
  return (
    <button type="button" disabled={disabled} onClick={onClick} className={`${base} ${variants[variant]}`}>
      {children}
    </button>
  )
}
