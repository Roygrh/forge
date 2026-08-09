/**
 * The run trace as a vertical timeline.
 *
 * Each step is rendered for what it *is*, not as a JSON dump with a label: a reason step
 * shows which model was called and what it cost, a tool step shows the gateway's verdict
 * before it shows the payload, and a decision step leads with the action and the rule it
 * cites. The order is the event log's order — this component adds none of its own.
 */

import type { ModelCall, RunStep, StepKind, ToolInvocation } from '../api/types'
import type { DecisionRecord, GovernanceRecord } from '../api/types'
import type { ConflictParty, RetrievalConflict, RetrievalResult, RetrievedChunk } from '../api/types'
import { isRetrievalResult } from '../api/types'
import { formatCost, formatOffset, formatTokens, humanize } from '../lib/format'
import { Disclosure } from './Disclosure'
import { JsonBlock, Mono } from './Json'
import {
  AuthorityPill,
  AutonomyPill,
  DecisionActionPill,
  Pill,
  ReasonCodePill,
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
  governance: {
    label: 'Blocked',
    dot: 'bg-rose-600 ring-rose-100',
    icon: 'text-rose-700',
    gloss: 'The platform refused to go further, and recorded why.',
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
  // A refusal is the one step that must not read as one more row in a list: it is the
  // moment the platform stopped the agent, and the card says so before anything else.
  const blocked = step.kind === 'governance'

  return (
    <li className="relative pl-10">
      <span
        aria-hidden="true"
        className={`absolute top-4 left-[7px] h-3.5 w-3.5 rounded-full ring-4 ${style.dot}`}
      />
      <article
        className={
          blocked
            ? 'rounded-lg border-2 border-rose-400 bg-rose-50/70 shadow-sm'
            : 'rounded-lg border border-slate-200 bg-white shadow-xs'
        }
      >
        <header
          className={`flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-5 py-3 ${
            blocked ? 'border-rose-200' : 'border-slate-100'
          }`}
        >
          <span
            className={`text-xs font-semibold tracking-wide ${
              blocked ? 'text-rose-500' : 'text-slate-400'
            }`}
          >
            Step {step.step_no}
          </span>
          <span className={`text-sm font-semibold ${style.icon}`}>
            {blocked ? '⛔ BLOCKED' : style.label}
          </span>
          <span
            className={`hidden text-xs sm:inline ${blocked ? 'text-rose-700' : 'text-slate-500'}`}
          >
            {style.gloss}
          </span>
          <span
            className={`ml-auto font-mono text-xs ${blocked ? 'text-rose-400' : 'text-slate-400'}`}
          >
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
  if (step.kind === 'governance' && step.governance !== null) {
    return <GovernanceStep block={step.governance} />
  }
  return <p className="text-sm text-slate-500">Recorded with no further detail.</p>
}

// --- Governance ---------------------------------------------------------------

/**
 * The platform refusing, rendered so a non-technical reader gets it at a glance.
 *
 * Three layers, in the order someone reads them: the reason code (what to quote in a
 * ticket), the explanation in plain English (what actually happened), and the specific
 * circumstance (which tool, which ceiling, which number). All three come from the API —
 * the words on the screen are the words in the audit log.
 */
function GovernanceStep({ block }: { block: GovernanceRecord }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ReasonCodePill code={block.reason_code} />
        <Pill tone="bad">Run ended {humanize(block.terminal_status)}</Pill>
      </div>

      <p className="text-sm leading-relaxed font-medium text-rose-900">{block.explanation}</p>

      {block.detail !== null && (
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-rose-700 uppercase">
            What triggered it
          </div>
          <p className="rounded-md border border-rose-200 bg-white px-3.5 py-2.5 font-mono text-[12px] leading-relaxed text-rose-900">
            {block.detail}
          </p>
        </div>
      )}
    </div>
  )
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
        {invocation.reason_code !== null && (
          <span className="mt-1.5 block">
            <ReasonCodePill code={invocation.reason_code} />
          </span>
        )}
        {invocation.error !== null && (
          <span className="mt-1 block font-mono text-[12px] text-rose-900">{invocation.error}</span>
        )}
      </div>

      {isRetrievalResult(invocation.result) ? (
        <RetrievalBody result={invocation.result} args={invocation.args} />
      ) : (
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
      )}
    </div>
  )
}

// --- Knowledge retrieval --------------------------------------------------------

/**
 * A retrieval step rendered as evidence, not as a JSON dump.
 *
 * Order matters: conflicts come **before** the chunk list, because "these sources
 * disagreed, and this one governed" is the fact a reviewer must not be able to miss
 * (FR-D2) — a superseded source buried at the bottom of a payload is a silent
 * resolution with extra steps. The raw result stays available underneath, verbatim.
 */
function RetrievalBody({ result, args }: { result: RetrievalResult; args: unknown }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
        <span className="font-medium text-slate-700">Query:</span>
        <span className="italic">“{result.query}”</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <Mono title="How this retrieval ran">{result.retrieval_mode}</Mono>
        <span title="The authority scale applied to the results, highest first (R-090)">
          authority: {result.authority_order.join(' > ')}
        </span>
      </div>

      {result.conflicts.map((conflict) => (
        <ConflictBanner key={conflict.topic} conflict={conflict} />
      ))}

      <div className="space-y-2">
        <div className="text-xs font-medium tracking-wide text-slate-500 uppercase">
          Retrieved sources ({result.chunks.length})
        </div>
        {result.chunks.map((chunk) => (
          <ChunkCard key={chunk.chunk_id} chunk={chunk} />
        ))}
      </div>

      <Disclosure summary="Retrieval as recorded" hint="arguments and full result, verbatim">
        <div className="grid gap-3 md:grid-cols-2">
          <JsonBlock label="Arguments" value={args ?? {}} />
          <JsonBlock label="Result" value={result} />
        </div>
      </Disclosure>
    </div>
  )
}

/**
 * The conflict, stated before anything else — with who disagreed, who governed, and
 * who was superseded. An unresolved conflict (equal authority) renders harder: nothing
 * won, and the platform fails the run closed rather than letting anyone pick (R-091).
 */
function ConflictBanner({ conflict }: { conflict: RetrievalConflict }) {
  const resolved = conflict.resolved
  return (
    <div
      className={
        resolved
          ? 'rounded-lg border-2 border-amber-300 bg-amber-50/80 px-4 py-3'
          : 'rounded-lg border-2 border-rose-400 bg-rose-50/80 px-4 py-3'
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`text-sm font-bold ${resolved ? 'text-amber-800' : 'text-rose-800'}`}
        >
          {resolved ? '⚖ SOURCES DISAGREED' : '⚖ CONFLICT — EQUAL AUTHORITY'}
        </span>
        <Mono title="The question the sources answer differently">{conflict.topic}</Mono>
        <Pill
          tone={resolved ? 'warn' : 'bad'}
          title={
            resolved
              ? 'Resolved by the authority hierarchy: the higher-authority source governs.'
              : 'No authority outranks the other, so nothing chose: the run fails closed for a human.'
          }
        >
          {resolved ? `resolved by authority (${conflict.resolution_rule})` : `unresolved — fail closed (${conflict.resolution_rule})`}
        </Pill>
      </div>

      <p
        className={`mt-2 text-sm leading-relaxed ${resolved ? 'text-amber-900' : 'text-rose-900'}`}
      >
        {conflict.explanation}
      </p>

      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {conflict.winner !== null && <PartyCard party={conflict.winner} role="governed" />}
        {conflict.superseded.map((party) => (
          <PartyCard
            key={party.citation}
            party={party}
            role={resolved ? 'superseded' : 'contested'}
          />
        ))}
      </div>
    </div>
  )
}

/** One side of a conflict: its citation, authority, declared answer, and date. */
function PartyCard({
  party,
  role,
}: {
  party: ConflictParty
  role: 'governed' | 'superseded' | 'contested'
}) {
  const frame = {
    governed: 'border-emerald-300 bg-emerald-50/70',
    superseded: 'border-slate-300 bg-white opacity-80',
    contested: 'border-rose-300 bg-white',
  }[role]
  const badge = {
    governed: <Pill tone="good" title="This source wins under the authority hierarchy (R-090)">✓ governed</Pill>,
    superseded: (
      <Pill tone="neutral" title="Outranked by a higher authority — kept visible, and flagged to its owner for remediation (FR-D5)">
        superseded
      </Pill>
    ),
    contested: <Pill tone="bad" title="Equal authority — no source governs">contested</Pill>,
  }[role]

  return (
    <div className={`rounded-md border px-3 py-2.5 text-sm ${frame}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        <CitationBadge citation={party.citation} />
        <AuthorityPill level={party.authority_level} />
        {badge}
      </div>
      {party.declared_value !== null && (
        <p className="mt-1.5 text-slate-800">
          declares: <span className="font-semibold">{party.declared_value}</span>
        </p>
      )}
      <p className="mt-1 text-xs text-slate-500">
        {party.section !== null && <>{party.section} · </>}
        {party.effective_date !== null && <>effective {party.effective_date} · </>}
        {party.owner !== null && <>owner: {party.owner}</>}
      </p>
    </div>
  )
}

/** One retrieved chunk: citation, authority, standing, and the content on demand. */
function ChunkCard({ chunk }: { chunk: RetrievedChunk }) {
  const superseded = chunk.status === 'superseded'
  const contested = chunk.status === 'contested'
  return (
    <div
      className={`rounded-md border px-3 py-2 ${
        superseded
          ? 'border-slate-200 bg-slate-50 opacity-75'
          : contested
            ? 'border-rose-200 bg-rose-50/50'
            : 'border-slate-200 bg-white'
      }`}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <CitationBadge citation={chunk.citation} />
        <AuthorityPill level={chunk.authority_level} />
        {superseded && (
          <Pill
            tone="neutral"
            title="This source lost to a higher authority. It is shown struck through — kept, not dropped — so the disagreement stays visible."
          >
            superseded by {chunk.superseded_by}
          </Pill>
        )}
        {contested && (
          <Pill tone="bad" title="Part of an unresolved equal-authority conflict">
            contested
          </Pill>
        )}
        <span className="ml-auto text-xs text-slate-400" title="Where each retriever ranked this chunk (lexical / semantic)">
          rank {chunk.lexical_rank ?? '—'} / {chunk.semantic_rank ?? '—'}
        </span>
      </div>
      <Disclosure
        summary={<span className={superseded ? 'line-through decoration-slate-400' : ''}>{chunk.section ?? chunk.source_ref}</span>}
        {...(chunk.effective_date !== null ? { hint: `effective ${chunk.effective_date}` } : {})}
      >
        <p className="text-sm leading-relaxed whitespace-pre-line text-slate-700">
          {chunk.content}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          {chunk.source_ref} · owner: {chunk.owner ?? 'unknown'}
        </p>
      </Disclosure>
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
        {/*
          Stated by the agent, enforced by the platform: below the floor this version's
          DNA declares, the action is overridden and the run escalates (R-091). Shown
          beside the action because the two only mean something together.
        */}
        <Pill
          tone={decision.confidence >= 0.85 ? 'neutral' : 'warn'}
          title="How sure the agent said it was. A decision below its DNA's floor is overridden and escalated."
        >
          confidence {decision.confidence.toFixed(2)}
        </Pill>
      </div>

      {/*
        Citations are the load-bearing part of this card: a decision without them is a
        bug, not a style issue (golden rule 4), and `require_citations` is const-locked
        true in the DNA schema. So they get their own labelled block rather than a line
        of small print.
      */}
      <div className="rounded-md border border-emerald-200 bg-emerald-50/60 px-3.5 py-3">
        <div className="text-xs font-medium tracking-wide text-emerald-800 uppercase">
          Citations
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {decision.citations.map((citation) => (
            <CitationBadge key={citation} citation={citation} />
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

/** A rule citation is `R-xxx`; anything else is a document citation. */
const RULE_CITATION = /^R-\d{3}$/

/**
 * One citation, rendered so a reader can tell a governed rule from a document
 * section at a glance (FR-D4): rules are the emerald `R-xxx` badges the platform has
 * always used; document citations carry a § mark and name the exact section a human
 * can open — that is what makes them verifiable rather than decorative.
 */
function CitationBadge({ citation }: { citation: string }) {
  if (RULE_CITATION.test(citation)) {
    return (
      <span
        title="Rule ID from the governed rule set"
        className="rounded bg-white px-2 py-0.5 font-mono text-[12px] font-medium text-emerald-800 ring-1 ring-emerald-200 ring-inset"
      >
        {citation}
      </span>
    )
  }
  return (
    <span
      title="Document citation — names the exact document section this claim rests on"
      className="rounded bg-white px-2 py-0.5 font-mono text-[12px] font-medium text-sky-800 ring-1 ring-sky-300 ring-inset"
    >
      § {citation}
    </span>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-0.5 font-medium text-slate-800 tabular-nums">{value}</dd>
    </div>
  )
}
