/**
 * The operations dashboard: what every agent has done, what it costs, and whether the
 * platform has it contained (FR-G3, FR-G4).
 *
 * Every number on this screen is a projection of the append-only event log, computed by
 * the server at request time — there is no counters table that could drift from the
 * audit trail (ADR-008). The recent-runs table under each agent is the receipts: any
 * figure above it resolves to real traces at `#/runs/<id>`.
 *
 * The suspend and resume buttons send a request and nothing else. The **server** decides
 * whether the acting role may contain or un-contain an agent, and the refusal is real
 * and recorded — resuming needs the admin hat, which no configuring role can wear.
 */

import { useCallback, useState } from 'react'

import { api } from '../api/client'
import type {
  AgentMetrics,
  MetricsReport,
  MetricsSummary,
  ReasonCode,
  RunStatus,
  SuspensionRecord,
} from '../api/types'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { Mono } from '../components/Json'
import { Pill, ReasonCodePill, RunStatusPill, VersionStatusPill } from '../components/Pill'
import { Button, PageHeading } from '../components/Shell'
import {
  formatAverage,
  formatCost,
  formatDateTime,
  formatRate,
  formatSeconds,
  humanize,
} from '../lib/format'
import { useAsync } from '../lib/useAsync'

export function MetricsScreen({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const { state, reload } = useAsync(useCallback(() => api.getMetrics(), []))

  return (
    <>
      <PageHeading
        eyebrow="Operations"
        title="Metrics & containment"
        lead={
          <>
            Runs, rates, cost and latency per agent — every figure derived from the
            append-only event log at request time, never from a separate store. When an
            agent trips the circuit breaker it is suspended on the record, its new runs are
            refused with a reason code, and only the admin role can put it back.
          </>
        }
        actions={
          <Button variant="secondary" onClick={reload}>
            Refresh
          </Button>
        }
      />

      {state.status === 'loading' && <Loading label="Projecting metrics from the event log…" />}
      {state.status === 'error' && <ErrorNotice error={state.error} onRetry={reload} />}
      {state.status === 'ready' && (
        <Dashboard report={state.data} onOpenRun={onOpenRun} onChanged={reload} />
      )}
    </>
  )
}

function Dashboard({
  report,
  onOpenRun,
  onChanged,
}: {
  report: MetricsReport
  onOpenRun: (runId: string) => void
  onChanged: () => void
}) {
  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-slate-200 bg-white shadow-xs">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-100 px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">All agents</h2>
          <p className="text-sm text-slate-600">
            The same numbers over every run the platform has recorded.
          </p>
          <span className="ml-auto text-xs text-slate-400">
            as of {formatDateTime(report.generated_at)}
          </span>
        </div>
        <SummaryTiles metrics={report.overall} />
      </section>

      {report.agents.length === 0 ? (
        <Empty title="No agents yet">
          Seed the demonstration agents, run them, and their numbers appear here.
        </Empty>
      ) : (
        report.agents.map((agent) => (
          <AgentCard key={agent.agent_id} agent={agent} onOpenRun={onOpenRun} onChanged={onChanged} />
        ))
      )}
    </div>
  )
}

/** The FR-G3 numbers as one row of tiles — the same layout for an agent and for all. */
function SummaryTiles({ metrics }: { metrics: MetricsSummary }) {
  return (
    <dl className="grid grid-cols-2 gap-x-8 gap-y-4 px-6 py-5 sm:grid-cols-3 lg:grid-cols-5">
      <Tile label="Runs" value={String(metrics.runs)} hint="run.started events" />

      <Tile
        label="Auto-approval rate"
        value={formatRate(metrics.auto_approval_rate)}
        hint="Completed with no human in the loop, over finished runs"
      />
      <Tile
        label="Escalation rate"
        value={formatRate(metrics.escalation_rate)}
        hint="Runs the agent (or a guardrail) handed to a person"
      />
      <Tile
        label="Block rate"
        value={formatRate(metrics.block_rate)}
        hint="Runs the platform stopped for a fault — human vetoes are not faults"
      />
      <Tile
        label="Refused starts"
        value={String(metrics.runs_refused)}
        hint="Starts refused while suspended; they never became runs"
      />
      <Tile
        label="Avg cost / run"
        value={formatCost(metrics.avg_cost_usd_per_run)}
        hint="Exact decimals, averaged over finished runs"
      />
      <Tile
        label="Avg tokens / run"
        value={formatAverage(metrics.avg_tokens_per_run)}
        hint="Input + output tokens, averaged over finished runs"
      />
      <Tile
        label="Avg latency"
        value={formatSeconds(metrics.avg_latency_seconds)}
        hint="run.started to the terminal event, wall clock"
      />
      <Tile label="Total cost" value={formatCost(metrics.total_cost_usd)} />
      <Tile
        label="Finished runs"
        value={String(metrics.finished_runs)}
        hint="The denominator every rate is computed over"
      />
    </dl>
  )
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <dt className="text-xs tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-slate-900 tabular-nums">{value}</dd>
    </div>
  )
}

function AgentCard({
  agent,
  onOpenRun,
  onChanged,
}: {
  agent: AgentMetrics
  onOpenRun: (runId: string) => void
  onChanged: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  /**
   * Suspend the live version, or resume the suspended one. The dashboard row does not
   * carry version numbers, so the target is looked up fresh — and the server is the
   * one that decides whether this role may do it at all.
   */
  const transition = async (action: 'suspend' | 'resume') => {
    setBusy(true)
    setError(null)
    try {
      const versions = await api.listVersions(agent.agent_id)
      const wanted = action === 'suspend' ? 'published' : 'suspended'
      const target = versions.find((version) => version.status === wanted)
      if (target === undefined) {
        throw new Error(`No ${wanted} version of ${agent.slug} to ${action}.`)
      }
      if (action === 'suspend') {
        await api.suspendVersion(agent.agent_id, target.version, {
          reason: 'Suspended from the metrics dashboard',
        })
      } else {
        await api.resumeVersion(agent.agent_id, target.version, {
          note: 'Resumed from the metrics dashboard',
        })
      }
      onChanged()
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-xs">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-100 px-6 py-4">
        <h2 className="text-base font-semibold text-slate-900">{agent.name}</h2>
        <Mono>{agent.slug}</Mono>
        <VersionStatusPill status={agent.state} />
        <div className="ml-auto">
          {agent.state === 'published' && (
            <Button variant="reject" disabled={busy} onClick={() => void transition('suspend')}>
              {busy ? 'Working…' : 'Suspend'}
            </Button>
          )}
          {agent.state === 'suspended' && (
            <Button variant="approve" disabled={busy} onClick={() => void transition('resume')}>
              {busy ? 'Working…' : 'Resume (admin only)'}
            </Button>
          )}
        </div>
      </div>

      {agent.suspension !== null && <SuspensionBanner suspension={agent.suspension} />}

      {error !== null && (
        <div className="px-6 pt-4">
          <ErrorNotice error={error} />
        </div>
      )}

      <SummaryTiles metrics={agent.metrics} />

      {Object.keys(agent.metrics.blocks_by_reason).length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-6 py-3">
          <span className="text-xs tracking-wide text-slate-500 uppercase">Blocks by reason</span>
          {Object.entries(agent.metrics.blocks_by_reason).map(([reason, count]) => (
            <span key={reason} className="inline-flex items-center gap-1.5">
              <ReasonCodePill code={reason as ReasonCode} />
              <span className="text-xs font-semibold text-slate-600 tabular-nums">×{count}</span>
            </span>
          ))}
        </div>
      )}

      <RecentRuns agent={agent} onOpenRun={onOpenRun} />
    </section>
  )
}

/**
 * Why this agent is stopped — verbatim from the recorded `version.suspended` event.
 *
 * When the breaker tripped it, the numbers it was judged on are right here: the metric,
 * what was observed, the threshold it crossed, and the window. The explanation of a
 * suspension is the recorded fact of it, not a reconstruction.
 */
function SuspensionBanner({ suspension }: { suspension: SuspensionRecord }) {
  const breaker = suspension.breaker ?? null
  return (
    <div className="border-b border-rose-200 bg-rose-50 px-6 py-4" role="alert">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span aria-hidden="true" className="text-lg leading-none">
          ⛔
        </span>
        <h3 className="text-sm font-bold tracking-wide text-rose-900 uppercase">
          {suspension.trigger === 'circuit_breaker'
            ? 'Suspended by the circuit breaker'
            : 'Suspended manually'}
        </h3>
        <ReasonCodePill code="agent_suspended" />
        {suspension.occurred_at !== undefined && (
          <span className="text-xs text-rose-700">
            {formatDateTime(suspension.occurred_at)} · by{' '}
            <span className="font-mono">{suspension.actor}</span>
          </span>
        )}
      </div>
      {suspension.detail !== undefined && (
        <p className="mt-2 font-mono text-[12px] leading-relaxed text-rose-800">
          {suspension.detail}
        </p>
      )}
      {breaker !== null && (
        <p className="mt-1 text-xs text-rose-700">
          Tripped on <strong>{humanize(breaker.metric ?? 'threshold')}</strong>: observed{' '}
          <span className="font-mono">{breaker.observed}</span> against a threshold of{' '}
          <span className="font-mono">{breaker.threshold}</span> over the last{' '}
          {breaker.window_seconds}s ({breaker.faulted_in_window} of {breaker.runs_in_window}{' '}
          runs faulted).
        </p>
      )}
      <p className="mt-2 text-xs text-rose-700">
        New runs are refused with <span className="font-mono">agent_suspended</span> and each
        refusal is recorded. Nothing resumes by itself: only the admin role may put this agent
        back, and the resume is recorded too.
      </p>
    </div>
  )
}

/** The receipts: the runs behind the numbers, each opening its full trace. */
function RecentRuns({ agent, onOpenRun }: { agent: AgentMetrics; onOpenRun: (runId: string) => void }) {
  if (agent.recent_runs.length === 0) {
    return (
      <p className="border-t border-slate-100 px-6 py-4 text-sm text-slate-500">
        No runs recorded yet.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto border-t border-slate-100">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="text-xs tracking-wide text-slate-500 uppercase">
            <th className="px-6 py-2 font-medium">Run</th>
            <th className="px-3 py-2 font-medium">Version</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Reason</th>
            <th className="px-3 py-2 text-right font-medium">Cost</th>
            <th className="px-6 py-2 text-right font-medium">Started</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {agent.recent_runs.map((run) => (
            <tr key={run.run_id} className="hover:bg-slate-50">
              <td className="px-6 py-2">
                <button
                  type="button"
                  onClick={() => onOpenRun(run.run_id)}
                  className="font-mono text-[12px] text-indigo-700 underline-offset-2 hover:underline"
                  title="Open this run's full trace — the projection these numbers came from"
                >
                  {run.run_id.slice(0, 8)}…
                </button>
              </td>
              <td className="px-3 py-2">
                <Mono>{run.agent}</Mono>
              </td>
              <td className="px-3 py-2">
                <RunStatusPill status={run.status as RunStatus} />
              </td>
              <td className="px-3 py-2">
                {run.reason === null ? (
                  <span className="text-slate-400">—</span>
                ) : run.reason === 'agent_decision' ? (
                  <Pill tone="warn" title="The agent decided this case belongs with a person">
                    agent decision
                  </Pill>
                ) : (
                  <ReasonCodePill code={run.reason as ReasonCode} />
                )}
              </td>
              <td className="px-3 py-2 text-right font-mono text-[12px] tabular-nums">
                {formatCost(run.total_cost_usd)}
              </td>
              <td className="px-6 py-2 text-right text-xs whitespace-nowrap text-slate-500">
                {formatDateTime(run.started_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
