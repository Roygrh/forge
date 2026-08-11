/**
 * The badge vocabulary.
 *
 * Every state the API can report has exactly one colour here, and the mappings are
 * exhaustive `Record`s over the contract's unions — so adding a status to the backend
 * makes this file fail to compile rather than quietly rendering it grey.
 *
 * The compile-time check guards this codebase; `toneFor`/`meaningFor` guard the
 * runtime: a value served by a newer backend than this build still renders as itself
 * on a neutral badge instead of blanking the screen. Both layers on purpose — the
 * union catches drift in development, the fallback keeps audit material readable when
 * drift happens anyway.
 */

import type {
  ApprovalStatus,
  Autonomy,
  DecisionAction,
  EvalRunStatus,
  ReasonCode,
  RunStatus,
  ToolStatus,
  VersionStatus,
} from '../api/types'
import { humanize } from '../lib/format'

export type Tone = 'neutral' | 'accent' | 'good' | 'warn' | 'bad' | 'info'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'bg-slate-100 text-slate-700 ring-slate-200',
  accent: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  good: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  warn: 'bg-amber-50 text-amber-800 ring-amber-200',
  bad: 'bg-rose-50 text-rose-700 ring-rose-200',
  info: 'bg-sky-50 text-sky-700 ring-sky-200',
}

interface PillProps {
  tone?: Tone
  children: React.ReactNode
  title?: string
}

export function Pill({ tone = 'neutral', children, title }: PillProps) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE_CLASSES[tone] ?? TONE_CLASSES.neutral}`}
    >
      {children}
    </span>
  )
}

/** Runtime-safe lookup: an out-of-contract value renders neutral, never undefined. */
function toneFor<K extends string>(map: Record<K, Tone>, key: K): Tone {
  return map[key] ?? 'neutral'
}

/** Runtime-safe gloss: an out-of-contract value gets a generic sentence, not a crash. */
function meaningFor<K extends string>(map: Record<K, string>, key: K): string {
  return map[key] ?? `Reported by the API as "${key}" — a state this build has no gloss for.`
}

// --- Semantic mappings --------------------------------------------------------

const RUN_STATUS_TONE: Record<RunStatus, Tone> = {
  running: 'info',
  awaiting_approval: 'warn',
  completed: 'good',
  escalated: 'warn',
  canceled: 'neutral',
  error: 'bad',
}

/** Plain-language gloss, so the header reads to someone who has never seen the API. */
const RUN_STATUS_MEANING: Record<RunStatus, string> = {
  running: 'The agent is still working.',
  awaiting_approval: 'Paused: a human must approve the next action.',
  completed: 'The agent finished and decided within its own authority.',
  escalated: 'The agent handed the decision to a human — a working outcome, not a failure.',
  canceled: 'The run was stopped before it finished.',
  error: 'The run failed before reaching a decision.',
}

export function RunStatusPill({ status }: { status: RunStatus }) {
  return (
    <Pill tone={toneFor(RUN_STATUS_TONE, status)} title={meaningFor(RUN_STATUS_MEANING, status)}>
      {humanize(status)}
    </Pill>
  )
}

export function runStatusMeaning(status: RunStatus): string {
  return meaningFor(RUN_STATUS_MEANING, status)
}

const TOOL_STATUS_TONE: Record<ToolStatus, Tone> = {
  validated: 'warn',
  executed: 'good',
  blocked: 'bad',
  denied: 'bad',
}

const TOOL_STATUS_MEANING: Record<ToolStatus, string> = {
  validated:
    'Checked and held: this agent’s DNA grants the tool only with a human approval, so the call was validated and parked — it did not run.',
  executed: 'The gateway allowed the call and ran it.',
  blocked: 'The gateway refused: the call never reached the tool.',
  denied: 'The gateway refused: this version explicitly forbids that tool.',
}

export function ToolStatusPill({ status }: { status: ToolStatus }) {
  return (
    <Pill tone={toneFor(TOOL_STATUS_TONE, status)} title={meaningFor(TOOL_STATUS_MEANING, status)}>
      {humanize(status)}
    </Pill>
  )
}

export function toolStatusMeaning(status: ToolStatus): string {
  return meaningFor(TOOL_STATUS_MEANING, status)
}

const AUTONOMY_TONE: Record<Autonomy, Tone> = {
  autonomous: 'info',
  requires_approval: 'warn',
  forbidden: 'bad',
}

const AUTONOMY_MEANING: Record<Autonomy, string> = {
  autonomous: 'The DNA grants this tool without a human in the loop.',
  requires_approval: 'The DNA requires a human approval before this tool runs.',
  forbidden: 'The DNA forbids this tool outright.',
}

export function AutonomyPill({ autonomy }: { autonomy: Autonomy }) {
  return (
    <Pill tone={toneFor(AUTONOMY_TONE, autonomy)} title={meaningFor(AUTONOMY_MEANING, autonomy)}>
      {humanize(autonomy)}
    </Pill>
  )
}

const ACTION_TONE: Record<DecisionAction, Tone> = {
  auto_approve: 'good',
  priority_queue: 'info',
  escalate: 'warn',
  block_escalate: 'warn',
}

const ACTION_MEANING: Record<DecisionAction, string> = {
  auto_approve: 'Approved within the agent’s own authority.',
  priority_queue: 'Routed for priority handling.',
  escalate: 'Handed to a human to decide.',
  block_escalate: 'Blocked and handed to a human to decide.',
}

export function DecisionActionPill({ action }: { action: DecisionAction }) {
  return (
    <Pill tone={toneFor(ACTION_TONE, action)} title={meaningFor(ACTION_MEANING, action)}>
      {humanize(action)}
    </Pill>
  )
}

export function decisionActionMeaning(action: DecisionAction): string {
  return meaningFor(ACTION_MEANING, action)
}

const APPROVAL_STATUS_TONE: Record<ApprovalStatus, Tone> = {
  pending: 'warn',
  granted: 'good',
  rejected: 'bad',
  // Not neutral: an expiry canceled a run. It is a fail-closed outcome, and it reads
  // like one — an approval that ran out of time is never a quiet nothing-happened.
  expired: 'bad',
}

const APPROVAL_STATUS_MEANING: Record<ApprovalStatus, string> = {
  pending: 'Waiting for a person. The action has not run and will not run until it is released.',
  granted: 'A person released this exact action, and the run resumed and carried it out.',
  rejected: 'A person refused it. The run was canceled and nothing was carried out.',
  expired:
    'Nobody decided before the deadline, so the platform canceled the run. An approval that runs out of time is never treated as a yes, and there is no way to extend one.',
}

export function ApprovalStatusPill({ status }: { status: ApprovalStatus }) {
  return (
    <Pill tone={toneFor(APPROVAL_STATUS_TONE, status)} title={meaningFor(APPROVAL_STATUS_MEANING, status)}>
      {humanize(status)}
    </Pill>
  )
}

export function approvalStatusMeaning(status: ApprovalStatus): string {
  return meaningFor(APPROVAL_STATUS_MEANING, status)
}

const VERSION_STATUS_TONE: Record<VersionStatus, Tone> = {
  draft: 'neutral',
  published: 'good',
  suspended: 'bad',
}

export function VersionStatusPill({ status }: { status: VersionStatus }) {
  return <Pill tone={toneFor(VERSION_STATUS_TONE, status)}>{humanize(status)}</Pill>
}

/**
 * Authority levels of the knowledge hierarchy (FR-D2). The tone encodes the ranking:
 * the SME-validated tier reads strongest because on conflict it wins (R-090).
 * `authority_level` arrives as an open string (the scale can grow), so unknown levels
 * fall back to neutral instead of failing to render audit material.
 */
const AUTHORITY_LEVEL_TONE: Record<string, Tone> = {
  sme_validated: 'accent',
  policy_2023: 'info',
  policy_2019: 'neutral',
}

const AUTHORITY_LEVEL_MEANING: Record<string, string> = {
  sme_validated:
    'Highest authority: rules captured from and signed off by the subject-matter expert. Overrides every written policy document on conflict (R-090).',
  policy_2023: 'The current written policy document. Overrides the 2019 policy on conflict.',
  policy_2019: 'The outdated written policy document — lowest authority on the scale.',
}

export function AuthorityPill({ level }: { level: string }) {
  return (
    <Pill
      tone={AUTHORITY_LEVEL_TONE[level] ?? 'neutral'}
      title={AUTHORITY_LEVEL_MEANING[level] ?? 'Authority level on the knowledge ranking scale'}
    >
      {level}
    </Pill>
  )
}

/**
 * Eval run status (FR-F1). The union covers what the inline executor serves today;
 * `toneFor`'s neutral fallback covers whatever a future queued executor adds.
 */
const EVAL_RUN_STATUS_TONE: Record<string, Tone> = {
  running: 'info',
  completed: 'neutral',
}

export function EvalRunStatusPill({ status }: { status: EvalRunStatus }) {
  return (
    <Pill
      tone={toneFor(EVAL_RUN_STATUS_TONE, status)}
      title="Whether the suite has finished scoring — the verdict itself is the passed flag"
    >
      {humanize(status)}
    </Pill>
  )
}

/** The verdict of a case, a check, or a whole suite run: it passed, or it did not. */
export function VerdictPill({ passed, label }: { passed: boolean | null; label?: string }) {
  if (passed === null) {
    return <Pill tone="info" title="Still executing — no verdict yet">{label ?? 'Scoring…'}</Pill>
  }
  return (
    <Pill
      tone={passed ? 'good' : 'bad'}
      title={
        passed
          ? 'Every programmatic assert held.'
          : 'At least one assert failed — the detail names which.'
      }
    >
      {label ?? (passed ? 'Pass' : 'Fail')}
    </Pill>
  )
}

/**
 * Governance reason codes, shown as the code itself.
 *
 * Deliberately *not* prettified into sentence case: the code is what appears in the
 * audit log, in the API, and in a support conversation, so the screen shows the same
 * token rather than a friendly synonym nobody can search for. The sentence beside it
 * comes from the API.
 */
export function ReasonCodePill({ code }: { code: ReasonCode }) {
  return (
    <span
      title="Machine-readable reason code, as recorded in the audit log"
      className="rounded bg-white px-2 py-0.5 font-mono text-[12px] font-semibold text-rose-800 ring-1 ring-rose-300 ring-inset"
    >
      {code}
    </span>
  )
}
