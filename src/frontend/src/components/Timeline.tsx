/**
 * The run trace as a vertical timeline.
 *
 * Each step is rendered for what it *is*, not as a JSON dump with a label: a reason step
 * shows which model was called and what it cost, a tool step shows the gateway's verdict
 * before it shows the payload, and a decision step leads with the action and the rule it
 * cites. The order is the event log's order — this component adds none of its own.
 */

import type { ModelCall, RunStep, StepKind, ToolInvocation } from '../api/types'
import type { DecisionRecord } from '../api/types'
import { formatCost, formatOffset, formatTokens } from '../lib/format'
import { Disclosure } from './Disclosure'
import { JsonBlock, Mono } from './Json'
import {
  AutonomyPill,
  DecisionActionPill,
  Pill,
  ToolStatusPill,
  decisionActionMeaning,
  toolStatusMeaning,
} from './Pill'

/** Per-kind chrome: the rail dot, the icon, and the one-line gloss under the title. */
const KIND_STYLE: Record<StepKind, { label: string; dot: string; icon: string; gloss: string }> = {
  reason: {
    label: 'Reason',
    dot: 'bg-violet-500 ring-violet-100',
    icon: 'text-violet-600',
    gloss: 'The runtime called the model through the LLM gateway.',
  },
  tool: {
    label: 'Tool',
    dot: 'bg-sky-500 ring-sky-100',
    icon: 'text-sky-600',
    gloss: 'The agent asked for a tool. The gateway decided whether it could have it.',
  },
  decision: {
    label: 'Decision',
    dot: 'bg-emerald-500 ring-emerald-100',
    icon: 'text-emerald-600',
    gloss: 'The agent committed to an action and cited the rules behind it.',
  },
}

export function Timeline({ steps, runStartedAt }: { steps: RunStep[]; runStartedAt: string }) {
  return (
    <ol className="relative space-y-4">
      {/* The rail. Decorative, so it is hidden from assistive technology. */}
      <span aria-hidden="true" className="absolute top-2 bottom-2 left-[13px] w-px bg-slate-200" />
      {steps.map((step) => (
        <TimelineStep key={step.step_no} step={step} runStartedAt={runStartedAt} />
      ))}
    </ol>
  )
}

function TimelineStep({ step, runStartedAt }: { step: RunStep; runStartedAt: string }) {
  const style = KIND_STYLE[step.kind]

  return (
    <li className="relative pl-10">
      <span
        aria-hidden="true"
        className={`absolute top-4 left-[7px] h-3.5 w-3.5 rounded-full ring-4 ${style.dot}`}
      />
      <article className="rounded-lg border border-slate-200 bg-white shadow-xs">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-100 px-5 py-3">
          <span className="text-xs font-semibold tracking-wide text-slate-400">
            Step {step.step_no}
          </span>
          <span className={`text-sm font-semibold ${style.icon}`}>{style.label}</span>
          <span className="hidden text-xs text-slate-500 sm:inline">{style.gloss}</span>
          <span className="ml-auto font-mono text-xs text-slate-400">
            {formatOffset(runStartedAt, step.created_at)}
          </span>
        </header>
        <div className="px-5 py-4">
          <StepBody step={step} />
        </div>
      </article>
    </li>
  )
}

/**
 * Dispatch on `kind`, then fall through to the payload.
 *
 * The fallback is not decoration: `kind` and the populated field are independent in the
 * wire format, so a step whose body is missing renders as "recorded, nothing to show"
 * rather than as an empty card that looks like a rendering bug.
 */
function StepBody({ step }: { step: RunStep }) {
  if (step.kind === 'reason' && step.model_call !== null) {
    return <ReasonStep call={step.model_call} />
  }
  if (step.kind === 'tool' && step.tool_invocation !== null) {
    return <ToolStep invocation={step.tool_invocation} />
  }
  if (step.kind === 'decision' && step.decision !== null) {
    return <DecisionStep decision={step.decision} />
  }
  return <p className="text-sm text-slate-500">Recorded with no further detail.</p>
}

// --- Reason -------------------------------------------------------------------

function ReasonStep({ call }: { call: ModelCall }) {
  const retried = call.attempt !== undefined && call.attempt > 0
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Mono title="Provider and model, resolved from the version's DNA">
          {call.provider ?? 'unknown'} · {call.model_id ?? 'unknown'}
        </Mono>
        {call.outcome !== undefined && <Pill tone="neutral">{call.outcome}</Pill>}
        {retried && (
          <Pill tone="warn" title="Schema validation failed once; ADR-006 allows exactly one correction.">
            Correction attempt {call.attempt}
          </Pill>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <Field label="Input tokens" value={formatTokens(call.input_tokens)} />
        <Field label="Output tokens" value={formatTokens(call.output_tokens)} />
        <Field label="Cost" value={formatCost(call.cost_usd)} />
        <Field
          label="Budget used"
          value={
            call.budget?.tokens_used === undefined
              ? '—'
              : `${formatTokens(call.budget.tokens_used)} / ${formatTokens(call.budget.max_tokens)} tokens`
          }
        />
      </dl>
    </div>
  )
}

// --- Tool ---------------------------------------------------------------------

function ToolStep({ invocation }: { invocation: ToolInvocation }) {
  const refused = invocation.status === 'blocked' || invocation.status === 'denied'
  const parked = invocation.status === 'validated'

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Mono title="Tool reference as granted in the version's DNA">{invocation.tool_ref}</Mono>
        {invocation.autonomy !== null && <AutonomyPill autonomy={invocation.autonomy} />}
        <ToolStatusPill status={invocation.status} />
      </div>

      {/*
        The governance line. Every tool call passes the gateway, and the gateway's
        verdict is stated in words before any payload is shown — including for a call
        that was refused, which is recorded precisely so it can be seen (FR-C5).
      */}
      <div
        className={`rounded-md border px-3.5 py-2.5 text-sm ${
          refused
            ? 'border-rose-200 bg-rose-50 text-rose-800'
            : parked
              ? 'border-amber-200 bg-amber-50 text-amber-900'
              : 'border-slate-200 bg-slate-50 text-slate-600'
        }`}
      >
        <span className="font-medium">Tool gateway:</span> {toolStatusMeaning(invocation.status)}
        {invocation.error !== null && (
          <span className="mt-1 block font-mono text-[12px] text-rose-900">{invocation.error}</span>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <JsonBlock label="Arguments" value={invocation.args ?? {}} />
        {invocation.result === null ? (
          <div className="min-w-0">
            <div className="mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase">
              Result
            </div>
            <p className="rounded-md border border-dashed border-slate-300 px-3 py-2.5 text-sm text-slate-500">
              {parked
                ? 'None — the call is waiting on a human approval.'
                : 'None — the call never ran.'}
            </p>
          </div>
        ) : (
          <JsonBlock label="Result" value={invocation.result} />
        )}
      </div>
    </div>
  )
}

// --- Decision -----------------------------------------------------------------

function DecisionStep({ decision }: { decision: DecisionRecord }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <DecisionActionPill action={decision.action} />
        <span className="text-sm text-slate-600">{decisionActionMeaning(decision.action)}</span>
      </div>

      {/*
        Citations are the load-bearing part of this card: a decision without them is a
        bug, not a style issue (golden rule 4), and `require_citations` is const-locked
        true in the DNA schema. So they get their own labelled block rather than a line
        of small print.
      */}
      <div className="rounded-md border border-emerald-200 bg-emerald-50/60 px-3.5 py-3">
        <div className="text-xs font-medium tracking-wide text-emerald-800 uppercase">
          Rules cited
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {decision.citations.map((rule) => (
            <span
              key={rule}
              title="Rule ID from the governed rule set"
              className="rounded bg-white px-2 py-0.5 font-mono text-[12px] font-medium text-emerald-800 ring-1 ring-emerald-200 ring-inset"
            >
              {rule}
            </span>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase">
          Reasoning
        </div>
        <p className="text-sm leading-relaxed text-slate-700">{decision.reasoning}</p>
      </div>

      {/*
        Only some agents produce one: the intake agent's job is to *structure* an
        invoice, not to adjudicate it, so its normalised fields are the substance of
        its decision rather than a footnote to it.
      */}
      {decision.output !== undefined && (
        <JsonBlock label="Structured output" value={decision.output} />
      )}

      <Disclosure summary="Decision as recorded">
        <JsonBlock value={decision} />
      </Disclosure>
    </div>
  )
}

// --- Shared -------------------------------------------------------------------

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-0.5 font-medium text-slate-800 tabular-nums">{value}</dd>
    </div>
  )
}
