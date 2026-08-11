/**
 * The agent catalog: what exists, what it is allowed to reach, and one button to run it.
 *
 * Each card is deliberately a governance summary rather than a name and a button — the
 * model the version is pinned to, the tools its DNA grants and at what autonomy, and its
 * step ceiling. Those are read from the version's DNA, which is the same document the
 * runtime executes, so the card cannot describe an agent that differs from the one that
 * will run (golden rule 1).
 */

import { useCallback, useState } from 'react'

import { api } from '../api/client'
import type { Agent, AgentVersion } from '../api/types'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { Mono } from '../components/Json'
import { AutonomyPill, Pill, VersionStatusPill } from '../components/Pill'
import { Button, PageHeading } from '../components/Shell'
import { useAsync } from '../lib/useAsync'
import { humanize } from '../lib/format'

/**
 * What the Run button sends, per agent.
 *
 * The three accounts-payable agents are triggered with an invoice id from the seeded
 * MeridianERP. `inv-0001` is eval case E-01 — a trusted vendor, a valid PO, and a 0.8%
 * price variance — which is the story the demo opens with: a routine invoice that flows
 * without a human and says exactly which rules let it.
 *
 * Anything else falls back to the skeleton agent's payload, so a catalog containing an
 * older agent still has a working button rather than a broken one.
 */
const DEMO_INVOICE_ID = 'inv-0001'
const FALLBACK_INPUT = { topic: 'governance' }

const DEMO_INPUT_BY_SLUG: Record<string, Record<string, string>> = {
  'invoice-intake': { invoice_id: DEMO_INVOICE_ID },
  'invoice-validator': { invoice_id: DEMO_INVOICE_ID },
  // The comms agent asks the vendor something — and its one tool needs a human, so this
  // run is expected to stop in `awaiting_approval` rather than complete, and to appear
  // in the Approvals queue. Nothing reaches the vendor until somebody releases it there.
  'invoice-comms': {
    invoice_id: 'inv-0005',
    question: 'Which purchase order covers the price difference on this invoice?',
  },
  // The same invoice as the validator, against a definition that forbids approving it.
  // Expected to be BLOCKED — that is what it is for.
  'invoice-validator-restricted': { invoice_id: DEMO_INVOICE_ID },
}

function demoInputFor(slug: string): Record<string, string> {
  return DEMO_INPUT_BY_SLUG[slug] ?? FALLBACK_INPUT
}

interface CatalogEntry {
  agent: Agent
  versions: AgentVersion[]
}

async function loadCatalog(): Promise<CatalogEntry[]> {
  const agents = await api.listAgents()
  return Promise.all(
    agents.map(async (agent) => ({ agent, versions: await api.listVersions(agent.id) })),
  )
}

export function AgentsScreen({ onRunStarted }: { onRunStarted: (runId: string) => void }) {
  const { state, reload } = useAsync(useCallback(loadCatalog, []))

  return (
    <>
      <PageHeading
        eyebrow="Catalog"
        title="Agents"
        lead={
          <>
            Every agent is a versioned, declarative definition — its “DNA”. One runtime executes
            all of them, and a version may only run once it has been published. Meridian’s three
            accounts-payable agents differ only in what their definitions grant them: intake may
            read an invoice and nothing else, the validator may approve one up to a declared
            ceiling, and comms may not contact a vendor without a human. Start a run to watch the
            runtime work and read the trace it leaves behind.
          </>
        }
      />

      {state.status === 'loading' && <Loading label="Loading the catalog…" />}
      {state.status === 'error' && <ErrorNotice error={state.error} onRetry={reload} />}
      {state.status === 'ready' &&
        (state.data.length === 0 ? (
          <Empty title="No agents yet">
            Seed the demonstration agents with{' '}
            <code className="font-mono text-[12px]">
              docker compose exec api python -m scripts.seed
            </code>
            .
          </Empty>
        ) : (
          <div className="space-y-4">
            {state.data.map((entry) => (
              <AgentCard key={entry.agent.id} entry={entry} onRunStarted={onRunStarted} />
            ))}
          </div>
        ))}
    </>
  )
}

function AgentCard({
  entry,
  onRunStarted,
}: {
  entry: CatalogEntry
  onRunStarted: (runId: string) => void
}) {
  const { agent, versions } = entry
  const runnable = versions.find((version) => version.status === 'published')
  const input = demoInputFor(agent.slug)

  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const start = async () => {
    if (runnable === undefined) return
    setStarting(true)
    setError(null)
    try {
      // The API executes the run inline and answers once it is terminal, so by the time
      // this resolves the trace on the next screen is already complete.
      const run = await api.startRun({
        agent_id: agent.id,
        version: runnable.version,
        input,
      })
      onRunStarted(run.id)
    } catch (cause) {
      setError(cause)
      setStarting(false)
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-xs">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-4 px-6 py-5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-slate-900">{agent.name}</h2>
            <Mono>{agent.slug}</Mono>
            <Pill tone="neutral">{humanize(agent.type)}</Pill>
            {runnable === undefined ? (
              <Pill tone="warn" title="Only a published version may run">
                No published version
              </Pill>
            ) : (
              <>
                <VersionStatusPill status={runnable.status} />
                <Mono title="The exact version a run binds to">v{runnable.version}</Mono>
              </>
            )}
          </div>
          {agent.description !== null && (
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-600">
              {agent.description}
            </p>
          )}
        </div>

        <div className="flex flex-col items-end gap-1">
          <Button onClick={() => void start()} disabled={runnable === undefined || starting}>
            {starting ? 'Running…' : 'Run'}
          </Button>
          <span className="max-w-xs text-right text-xs break-all text-slate-400">
            input <span className="font-mono">{JSON.stringify(input)}</span>
          </span>
        </div>
      </div>

      {runnable !== undefined && <DnaSummary version={runnable} />}

      {error !== null && (
        <div className="px-6 pb-5">
          <ErrorNotice error={error} />
        </div>
      )}
    </section>
  )
}

/** What this version is permitted to do, read straight from its DNA. */
function DnaSummary({ version }: { version: AgentVersion }) {
  const model = version.dna.model
  const tools = version.dna.tools ?? []
  const guardrails = version.dna.guardrails

  return (
    <div className="grid gap-x-8 gap-y-4 border-t border-slate-100 bg-slate-50/60 px-6 py-4 sm:grid-cols-3">
      <div>
        <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">Model</h3>
        <p className="mt-1.5 text-sm text-slate-700">
          <Mono>
            {model?.provider ?? 'unset'} · {model?.model_id ?? 'unset'}
          </Mono>
        </p>
      </div>

      <div>
        <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">
          Tools granted
        </h3>
        {tools.length === 0 ? (
          <p className="mt-1.5 text-sm text-slate-500">None — least privilege by default.</p>
        ) : (
          <ul className="mt-1.5 space-y-1.5">
            {tools.map((tool) => (
              <li key={tool.ref} className="flex flex-wrap items-center gap-2">
                <Mono>{tool.ref}</Mono>
                <AutonomyPill autonomy={tool.autonomy} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">Guardrails</h3>
        <p className="mt-1.5 text-sm text-slate-700">
          Max {guardrails?.max_steps ?? '—'} steps · {guardrails?.timeout_seconds ?? '—'}s timeout
          {guardrails?.require_citations === true && ' · citations required'}
        </p>
        {version.published_eval_run_id === null && (
          <p
            className="mt-1.5 text-xs text-amber-700"
            title="scripts/seed.py publishes this version directly so a fresh stack has something to execute — the one documented exception to the eval gate. Versions authored through the API earn their publish on the Evals screen."
          >
            Published by the seed script — the documented exception to the eval gate.
          </p>
        )}
      </div>
    </div>
  )
}
