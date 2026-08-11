import { apiBaseUrl, setActingRole } from '../api/client'
import { ROLES } from '../api/types'
import type { Role } from '../api/types'
import { humanize } from '../lib/format'
import { useActingRole } from '../lib/useActingRole'

/**
 * The application chrome.
 *
 * The header states three things on every screen because all three are part of the story
 * rather than debug output: where you are, which role this session is acting as (NFR-5 —
 * segregation of duties, made visible), and which API it is reading. A demo that cannot
 * show where its data came from is asking to be taken on trust.
 */
export function Shell({
  active,
  children,
}: {
  active: 'agents' | 'approvals' | 'evals' | 'metrics' | 'run'
  children: React.ReactNode
}) {
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

          <nav className="flex items-center gap-1" aria-label="Main">
            <NavLink href="#/" label="Agents" current={active === 'agents' || active === 'run'} />
            <NavLink href="#/approvals" label="Approvals" current={active === 'approvals'} />
            <NavLink href="#/evals" label="Evals" current={active === 'evals'} />
            <NavLink href="#/metrics" label="Metrics" current={active === 'metrics'} />
          </nav>

          <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-500">
            <RoleSwitch />
            <span title="Configured with VITE_API_BASE_URL">
              API <span className="font-mono text-slate-600">{apiBaseUrl}</span>
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">{children}</main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 py-4 text-xs text-slate-400">
          Phase 4.6 — observability and containment. Metrics are projections of the append-only
          event log, never a parallel store (FR-G3, ADR-008); the circuit breaker suspends an
          agent on the record and its refusals are recorded too (FR-G4); nothing resumes by
          itself — only the admin role can, and no configuring role may ever hold that power.
        </div>
      </footer>
    </div>
  )
}

function NavLink({ href, label, current }: { href: string; label: string; current: boolean }) {
  return (
    <a
      href={href}
      aria-current={current ? 'page' : undefined}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
        current
          ? 'bg-slate-100 text-slate-900'
          : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'
      }`}
    >
      {label}
    </a>
  )
}

/**
 * Which hat this session is wearing, and a way to change it.
 *
 * Switching sends a different `X-Forge-Role` and nothing else — this control grants no
 * permission of its own. The **server** decides what a role may do and answers 403 when
 * it may not, which is the point: segregation of duties is a matrix in the platform, not
 * a disabled button in a browser. Try to approve something as the configurator and the
 * refusal (and its audit record) is real.
 */
function RoleSwitch() {
  const role = useActingRole()
  return (
    <label
      className="flex items-center gap-2"
      title="Sent as X-Forge-Role on every request. Segregation of duties, not authentication — the server enforces what each role may do."
    >
      Acting as
      <select
        value={role}
        onChange={(event) => setActingRole(event.target.value as Role)}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:outline-none"
      >
        {ROLES.map((option) => (
          <option key={option} value={option}>
            {humanize(option)}
          </option>
        ))}
      </select>
    </label>
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

/** The one button style in the app: a primary action, a quiet secondary, or a refusal. */
export function Button({
  variant = 'primary',
  disabled = false,
  onClick,
  children,
}: {
  variant?: 'primary' | 'secondary' | 'approve' | 'reject'
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
    // The two decisions look different from each other and from everything else on the
    // page: an approver about to release a payment should never be one muscle-memory
    // click away from the wrong verb.
    approve: 'bg-emerald-600 text-white hover:bg-emerald-500 focus-visible:ring-emerald-500',
    reject:
      'border border-rose-300 bg-white text-rose-700 hover:bg-rose-50 focus-visible:ring-rose-400',
  }
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`${base} ${variants[variant]}`}
    >
      {children}
    </button>
  )
}
