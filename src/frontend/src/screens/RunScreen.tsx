/**
 * One run, end to end: what it cost, what it did, and the log it was derived from.
 *
 * The page is three layers, and the order is the argument. The header is the outcome. The
 * timeline is the projection — the ordered steps a reviewer reads. The raw-events panel
 * underneath is the append-only source that projection came from, so the screen is not
 * asking to be believed (ADR-008).
 */

import { useCallback } from 'react'

import { api } from '../api/client'
import type { Run, RunTrace } from '../api/types'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { Mono } from '../components/Json'
import { RunStatusPill, runStatusMeaning } from '../components/Pill'
import { RawEventsPanel } from '../components/RawEvents'
import { Button, PageHeading } from '../components/Shell'
import { Timeline } from '../components/Timeline'
import { formatCost, formatDateTime, formatDuration, formatTokens } from '../lib/format'
import { useAsync } from '../lib/useAsync'

interface RunView {
  run: Run
  trace: RunTrace
}

export function RunScreen({ runId, onBack }: { runId: string; onBack: () => void }) {
  const load = useCallback(
    async (): Promise<RunView> => ({
      run: await api.getRun(runId),
      trace: await api.getTrace(runId),
    }),
    [runId],
  )
  const { state, reload } = useAsync(load)

  return (
    <>
      <PageHeading
        eyebrow="Run trace"
        title="What the agent did"
        lead="Every model call, every trip through the tool gateway, and the final decision with the rules it cited — in the order they were recorded."
        actions={
          <Button variant="secondary" onClick={onBack}>
            ← Agents
          </Button>
        }
      />

      {state.status === 'loading' && <Loading label="Loading the trace…" />}
      {state.status === 'error' && <ErrorNotice error={state.error} onRetry={reload} />}
      {state.status === 'ready' && <RunDetail view={state.data} />}
    </>
  )
}

function RunDetail({ view }: { view: RunView }) {
  const { run, trace } = view

  return (
    <div className="space-y-6">
      <RunSummary run={run} steps={trace.steps.length} />

      {trace.steps.length === 0 ? (
        <Empty title="No steps were recorded">
          The run ended before the loop took a step. The raw events below still say why.
        </Empty>
      ) : (
        <Timeline steps={trace.steps} runStartedAt={run.started_at} />
      )}

      <RawEventsPanel events={trace.events} />
    </div>
  )
}

function RunSummary({ run, steps }: { run: Run; steps: number }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-xs">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-100 px-6 py-4">
        <RunStatusPill status={run.status} />
        <p className="text-sm text-slate-600">{runStatusMeaning(run.status)}</p>
        <Mono title="Run id — this page is at #/runs/<id> and can be reloaded or shared">
          {run.id}
        </Mono>
      </div>

      <dl className="grid grid-cols-2 gap-x-8 gap-y-4 px-6 py-5 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Steps" value={String(steps)} />
        <Stat label="Total tokens" value={formatTokens(run.total_tokens)} />
        <Stat
          label="Total cost"
          value={formatCost(run.total_cost_usd)}
          hint="Exact decimal, never a rounded float"
        />
        <Stat label="Duration" value={formatDuration(run.started_at, run.finished_at)} />
        <Stat label="Trigger" value={run.trigger ?? '—'} />
        <Stat label="Started" value={formatDateTime(run.started_at)} />
      </dl>
    </section>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <dt className="text-xs tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-slate-900 tabular-nums">{value}</dd>
    </div>
  )
}
