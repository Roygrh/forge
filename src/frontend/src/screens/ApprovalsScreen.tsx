/**
 * The approval queue: what an agent wants to do, why, and one minute to decide.
 *
 * Kevin Osei, discovery interview 2: *"Show me: what it wants to do, the invoice, the PO
 * next to it, which rule fired, and what's off. If I have to open the ERP in another tab,
 * that's two more minutes each."* Every layout decision below is that sentence:
 *
 * 1. **The proposed action first**, in words, with its arguments spelled out as labelled
 *    fields rather than as JSON to decode. It is the thing being decided.
 * 2. **The rules in play** as badges, immediately under it — the third thing he asks for,
 *    and the one that usually settles it.
 * 3. **The evidence** — the invoice, the PO, the receipts, whatever the agent actually
 *    retrieved — rendered inline. No second tab, no second request: it arrives with the
 *    queue.
 * 4. **Approve and Reject**, visibly different from each other, with an optional note.
 *
 * The countdown is prominent because it is doing real work: the deadline is enforced
 * server-side, and when it passes the run is **canceled**, never approved (FR-E3). The
 * clock shown here is a courtesy — this screen never decides whether an approval is still
 * live, because the browser's clock is not the one that counts.
 */

import { useCallback, useState } from 'react'

import { ApiError, api } from '../api/client'
import type {
  Approval,
  ApprovalObservation,
  AutonomyCandidate,
  JsonObject,
} from '../api/types'
import { Disclosure } from '../components/Disclosure'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { JsonBlock, Mono } from '../components/Json'
import { ApprovalStatusPill, Pill } from '../components/Pill'
import { Button, PageHeading } from '../components/Shell'
import { formatDateTime } from '../lib/format'
import { useActingRole } from '../lib/useActingRole'
import { useAsync } from '../lib/useAsync'

interface QueueView {
  approvals: Approval[]
  report: AutonomyCandidate[]
}

async function loadQueue(): Promise<QueueView> {
  return {
    approvals: await api.listApprovals('pending'),
    report: await api.getApprovalReport(),
  }
}

export function ApprovalsScreen({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  // The role is part of the load key: switching who you are acting as re-reads the queue,
  // because the answer the server gives is the answer for *that* role.
  const role = useActingRole()
  const { state, reload } = useAsync(useCallback(() => loadQueue(), [role]))

  return (
    <>
      <PageHeading
        eyebrow="Human in the loop"
        title="Approvals"
        lead={
          <>
            Every action here was checked by the tool gateway and deliberately{' '}
            <strong>not carried out</strong>: the agent’s published definition grants the tool
            only with a person in the loop. Each item carries what the agent gathered before it
            asked, so a decision needs no second tab. Nobody has to do anything for the safe
            outcome — an approval that runs out of time cancels its run, and there is no way to
            extend one.
          </>
        }
        actions={
          <Button variant="secondary" onClick={reload}>
            Refresh
          </Button>
        }
      />

      {state.status === 'loading' && <Loading label="Loading the queue…" />}
      {state.status === 'error' && <ErrorNotice error={state.error} onRetry={reload} />}
      {state.status === 'ready' && (
        <div className="space-y-8">
          {state.data.approvals.length === 0 ? (
            <Empty title="Nothing is waiting on a person">
              Run the <span className="font-mono text-[12px]">invoice-comms</span> agent from the
              catalog: its only tool is granted <em>requires approval</em>, so the run parks here
              instead of contacting the vendor.
            </Empty>
          ) : (
            <div className="space-y-5">
              {state.data.approvals.map((approval) => (
                <ApprovalCard
                  key={approval.id}
                  approval={approval}
                  onDecided={reload}
                  onOpenRun={onOpenRun}
                />
              ))}
            </div>
          )}

          <AutonomyReport rows={state.data.report} />
        </div>
      )}
    </>
  )
}

// --- One item -----------------------------------------------------------------

function ApprovalCard({
  approval,
  onDecided,
  onOpenRun,
}: {
  approval: Approval
  onDecided: () => void
  onOpenRun: (runId: string) => void
}) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [outcome, setOutcome] = useState<Approval | null>(null)

  const decide = async (verdict: 'approve' | 'reject') => {
    setBusy(verdict)
    setError(null)
    try {
      const body = note.trim() === '' ? {} : { note: note.trim() }
      const decided = verdict === 'approve' ? await api.approve(approval.id, body) : await api.reject(approval.id, body)
      setOutcome(decided)
      onDecided()
    } catch (cause) {
      // Including a 403 from a role that may not decide, and a 409 from an approval whose
      // deadline passed while this card was on screen. Both are real answers from the
      // server and both are shown as given (see DecisionError).
      setError(cause)
    } finally {
      setBusy(null)
    }
  }

  if (outcome !== null) {
    return <DecidedCard approval={outcome} onOpenRun={onOpenRun} />
  }

  return (
    <section className="overflow-hidden rounded-lg border-2 border-amber-300 bg-white shadow-sm">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-amber-200 bg-amber-50 px-6 py-4">
        <span aria-hidden="true" className="text-xl leading-none">
          ⏸
        </span>
        <h2 className="text-base font-bold text-amber-900">Waiting on you</h2>
        <ApprovalStatusPill status={approval.status} />
        <Mono title="The agent version that proposed this">{approval.evidence.agent}</Mono>
        <div className="ml-auto">
          <Countdown approval={approval} />
        </div>
      </header>

      <div className="space-y-5 px-6 py-5">
        <ProposedActionBlock approval={approval} />

        {approval.evidence.rule_ids.length > 0 && (
          <RulesInPlay ruleIds={approval.evidence.rule_ids} />
        )}

        <EvidenceBlock approval={approval} />

        <div className="rounded-lg border border-slate-200 bg-slate-50/70 px-4 py-4">
          <label className="block">
            <span className="text-xs font-medium tracking-wide text-slate-500 uppercase">
              Note (optional, recorded with your decision)
            </span>
            <input
              type="text"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="e.g. PO confirmed by phone — go ahead"
              className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:outline-none"
            />
          </label>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="approve" disabled={busy !== null} onClick={() => void decide('approve')}>
              {busy === 'approve' ? 'Approving…' : '✓ Approve'}
            </Button>
            <Button variant="reject" disabled={busy !== null} onClick={() => void decide('reject')}>
              {busy === 'reject' ? 'Rejecting…' : '✕ Reject'}
            </Button>
            <p className="text-xs text-slate-500">
              Approving runs <em>this</em> action with <em>these</em> arguments and nothing else.
              Rejecting cancels the run.
            </p>
          </div>

          {error !== null && <DecisionError error={error} />}
        </div>
      </div>
    </section>
  )
}

/** What the agent wants to do, in words and in fields — never as raw JSON to decode. */
function ProposedActionBlock({ approval }: { approval: Approval }) {
  const action = approval.proposed_action
  return (
    <div>
      <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">
        Proposed action
      </h3>
      <div className="mt-2 rounded-lg border border-slate-300 bg-white px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-slate-900">
            {toolTitle(action.tool_ref)}
          </span>
          <Mono title="Tool reference as granted in the version's DNA">{action.tool_ref}</Mono>
          <Pill tone="warn" title={approval.why_approval_required}>
            not carried out
          </Pill>
        </div>
        <ArgumentList args={action.args} />
      </div>
      <p className="mt-2 text-xs text-slate-500">{approval.why_approval_required}</p>
    </div>
  )
}

/**
 * The arguments as a definition list.
 *
 * Deliberately not a JSON block: this is the text that will be sent and the amount that
 * will be posted, and someone deciding in under a minute should read it, not parse it.
 * The verbatim payload is still one disclosure away in the evidence below.
 */
function ArgumentList({ args }: { args: JsonObject | null }) {
  const entries = Object.entries(args ?? {})
  if (entries.length === 0) {
    return <p className="mt-2 text-sm text-slate-500">No arguments.</p>
  }
  return (
    <dl className="mt-3 space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[10rem_1fr] gap-3">
          <dt className="text-xs tracking-wide text-slate-500 uppercase">{key}</dt>
          <dd className="text-sm break-words text-slate-900">{renderValue(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function renderValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return '—'
  return JSON.stringify(value)
}

/** The rules that were in front of the agent when it asked. */
function RulesInPlay({ ruleIds }: { ruleIds: string[] }) {
  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 px-4 py-3">
      <h3 className="text-xs font-medium tracking-wide text-emerald-800 uppercase">
        Rules in play
      </h3>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {ruleIds.map((ruleId) => (
          <span
            key={ruleId}
            title="A governed rule id present in what the agent retrieved"
            className="rounded bg-white px-2 py-0.5 font-mono text-[12px] font-medium text-emerald-800 ring-1 ring-emerald-200 ring-inset"
          >
            {ruleId}
          </span>
        ))}
      </div>
    </div>
  )
}

/** Everything the agent gathered, inline — the "no second tab" requirement (FR-E1). */
function EvidenceBlock({ approval }: { approval: Approval }) {
  const { observations, run_input } = approval.evidence
  return (
    <div>
      <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">
        What the agent looked at
      </h3>
      <div className="mt-2 space-y-2">
        <div className="rounded-md border border-slate-200 bg-white px-3.5 py-2.5">
          <div className="text-xs font-medium text-slate-500">Run input</div>
          <ArgumentList args={run_input} />
        </div>

        {observations.length === 0 ? (
          <p className="rounded-md border border-dashed border-slate-300 px-3.5 py-2.5 text-sm text-slate-500">
            Nothing — the agent asked for this action before retrieving anything else.
          </p>
        ) : (
          observations.map((observation) => (
            <ObservationCard key={observation.tool_invocation_id} observation={observation} />
          ))
        )}
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Read back from the run’s append-only event log, so this is what the agent saw — not a
        fresh lookup that may have moved since.
      </p>
    </div>
  )
}

function ObservationCard({ observation }: { observation: ApprovalObservation }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3.5 py-2.5">
      <Disclosure
        summary={<span className="font-medium">{toolTitle(observation.tool_ref)}</span>}
        hint={observation.tool_name}
        defaultOpen
      >
        <JsonBlock value={observation.result ?? {}} />
      </Disclosure>
    </div>
  )
}

/**
 * Time left, and what happens when it runs out.
 *
 * The wording is the governance statement: a deadline that "expires" could mean anything;
 * this one cancels the run. Shown from the server's own `seconds_remaining`, not computed
 * from the browser's clock — the deadline is not this page's to judge.
 */
function Countdown({ approval }: { approval: Approval }) {
  const seconds = approval.seconds_remaining
  const urgent = seconds < 60 * 30
  return (
    <div
      className={`rounded-md px-3 py-1.5 text-right ${
        urgent ? 'bg-rose-100 text-rose-900' : 'bg-white text-amber-900'
      }`}
      title={`Deadline ${formatDateTime(approval.expires_at)}. When it passes the run is canceled — never approved — and there is no way to extend it.`}
    >
      <div className="text-sm font-semibold tabular-nums">{formatRemaining(seconds)}</div>
      <div className="text-[11px]">then the run is canceled</div>
    </div>
  )
}

function formatRemaining(seconds: number): string {
  if (seconds <= 0) return 'deadline passed'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m left`
  if (minutes > 0) return `${minutes}m left`
  return `${seconds}s left`
}

/** The card after a decision: what happened, and a way into the trace that proves it. */
function DecidedCard({
  approval,
  onOpenRun,
}: {
  approval: Approval
  onOpenRun: (runId: string) => void
}) {
  const approved = approval.status === 'granted'
  return (
    <section
      className={`rounded-lg border-2 px-6 py-5 ${
        approved ? 'border-emerald-300 bg-emerald-50/70' : 'border-slate-300 bg-slate-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <ApprovalStatusPill status={approval.status} />
        <span className="text-sm font-medium text-slate-800">
          {approved
            ? 'Released. The run resumed and carried the action out.'
            : 'Refused. The run was canceled and nothing was carried out.'}
        </span>
        <Button variant="secondary" onClick={() => onOpenRun(approval.run_id)}>
          Open the trace →
        </Button>
      </div>
      <p className="mt-2 text-xs text-slate-600">
        Recorded as {approval.decided_by} at{' '}
        {approval.decided_at === null ? 'now' : formatDateTime(approval.decided_at)} — the run is
        now <span className="font-medium">{approval.run_status.replace(/_/g, ' ')}</span>.
      </p>
    </section>
  )
}

/**
 * A refused decision, shown as the server gave it.
 *
 * A 403 here is the segregation-of-duties matrix doing its job, and it says which
 * permission was needed — so the screen never has to keep its own copy of who may decide
 * what. A 409 is an approval that stopped being pending while this card was open, which
 * for an expiry means the run has already been canceled.
 */
function DecisionError({ error }: { error: unknown }) {
  const denied = error instanceof ApiError && error.status === 403
  return (
    <div className="mt-3">
      <ErrorNotice error={error} />
      {denied && (
        <p className="mt-2 text-xs text-slate-600">
          Segregation of duties (NFR-5): the role that decides what an agent may do is never
          the role that approves what it proposes. Switch to <strong>Approver</strong> in the
          header to decide this one — the refusal above is recorded in the audit log either way.
        </p>
      )}
    </div>
  )
}

// --- The autonomy-promotion report (FR-E5) ------------------------------------

/**
 * Rosa Delgado's approval-fatigue risk, measured — and applied by nothing.
 *
 * The section is deliberately quiet and deliberately read-only: there is no button here,
 * because raising an autonomy level means publishing a new DNA version through its eval
 * gate. A platform that widened an agent's permissions from a screen would be exactly the
 * thing the rest of this project argues against.
 */
function AutonomyReport({ rows }: { rows: AutonomyCandidate[] }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-xs">
      <header className="border-b border-slate-100 px-6 py-4">
        <h2 className="text-base font-semibold text-slate-900">Autonomy-promotion report</h2>
        <p className="mt-1 text-sm text-slate-600">
          What approvers actually did, per agent version and tool — the pair a DNA grant names.
          A long run of approvals with no refusals is a sign the queue is costing attention it
          does not need. <strong>Read-only:</strong> promotion means publishing a new version
          through its eval gate, never a number crossing a line here.
        </p>
      </header>

      {rows.length === 0 ? (
        <p className="px-6 py-5 text-sm text-slate-500">
          No approvals have been recorded yet, so there is nothing to report.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[52rem] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs tracking-wide text-slate-500 uppercase">
                <th className="px-6 py-2.5 font-medium">Action category</th>
                <th className="px-3 py-2.5 text-right font-medium">Granted</th>
                <th className="px-3 py-2.5 text-right font-medium">Refused</th>
                <th className="px-3 py-2.5 text-right font-medium">Expired</th>
                <th className="px-3 py-2.5 text-right font-medium">Rate</th>
                <th className="px-6 py-2.5 font-medium">Finding</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.agent_version_id}-${row.tool_ref}`} className="border-b border-slate-50 align-top">
                  <td className="px-6 py-3">
                    <div className="font-medium text-slate-800">{row.agent}</div>
                    <Mono>{row.tool_ref}</Mono>
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums text-slate-700">{row.granted}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-slate-700">{row.rejected}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-slate-700">{row.expired}</td>
                  <td className="px-3 py-3 text-right tabular-nums text-slate-700">
                    {row.approval_rate === null ? '—' : `${Math.round(row.approval_rate * 100)}%`}
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      {row.candidate && (
                        <Pill tone="accent" title="Worth a reviewer's attention — not an action">
                          promotion candidate
                        </Pill>
                      )}
                      <span className="text-slate-600">{row.recommendation}</span>
                    </div>
                    {row.fatigue_note !== null && (
                      <p className="mt-1 text-xs text-rose-700">{row.fatigue_note}</p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** `meridian-erp-request-info-from-vendor@1.0.0` → `Request info from vendor`. */
function toolTitle(toolRef: string): string {
  const slug = toolRef.split('@')[0] ?? toolRef
  const words = slug.replace(/^meridian-(erp|ap)-/, '').replace(/-/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
