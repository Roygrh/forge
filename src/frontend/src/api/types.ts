/**
 * The API shapes this SPA consumes.
 *
 * Mirrored from `docs/02-architecture/api/openapi.yaml` and its executable form,
 * `src/backend/app/api/schemas.py` + `app/runtime/trace.py`. Nothing here is invented:
 * if a field is absent below it is because the backend does not send it, and if a union
 * is narrow it is because the backend narrows it too.
 *
 * ADR-007 notes these types should eventually be generated from the OpenAPI document in
 * CI. Hand-written for now, deliberately: the surface is five shapes, and a generator in
 * the build is a thing to maintain before there is anything to keep in sync.
 */

// --- Vocabularies -------------------------------------------------------------
// Each of these is an enum in the contract, so it is a union here rather than `string`.

/**
 * The demonstration roles the API accepts in `X-Forge-Role` (NFR-5). `admin` is the
 * containment operator: the only role that can resume a suspended agent, and
 * structurally never the one who configured or published it.
 */
export type Role = 'configurator' | 'approver' | 'viewer' | 'admin'

export const ROLES: readonly Role[] = ['configurator', 'approver', 'viewer', 'admin']

export type AgentType = 'chatbot' | 'workflow' | 'autonomous'

export type VersionStatus = 'draft' | 'published' | 'suspended'

export type RunStatus =
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'escalated'
  | 'canceled'
  | 'error'

export type StepKind = 'reason' | 'tool' | 'decision' | 'governance' | 'approval'

/** Where one parked action stands. Only `granted` ever leads to an execution (FR-E3). */
export type ApprovalStatus = 'pending' | 'granted' | 'rejected' | 'expired'

/**
 * Why the platform stopped, blocked, or refused — the machine-readable half of a
 * governance step. Mirrors `GovernanceReason` in `app/governance.py`, which is the one
 * place these are defined. Kept as a union so a new code shows up as a type error here
 * rather than as an unstyled string on the screen.
 */
export type ReasonCode =
  | 'tool_unknown'
  | 'permission_denied'
  | 'args_invalid'
  | 'tool_config_invalid'
  | 'tool_failed'
  | 'approval_required'
  | 'approval_rejected'
  | 'approval_expired'
  | 'no_rule_match'
  | 'knowledge_conflict'
  | 'low_confidence'
  | 'invalid_output'
  | 'step_limit'
  | 'timeout'
  | 'budget_exceeded'
  | 'daily_budget_exceeded'
  | 'agent_suspended'
  | 'provider_unavailable'
  | 'unsupported_definition'
  | 'agent_decision'

/** What the tool gateway did with a call. `blocked`/`denied` never executed (FR-C5). */
export type ToolStatus = 'validated' | 'executed' | 'blocked' | 'denied'

/** The least-privilege level a version's DNA grants for one tool. */
export type Autonomy = 'autonomous' | 'requires_approval' | 'forbidden'

/** The platform's four final actions — an agent chooses one, it does not invent its own. */
export type DecisionAction = 'auto_approve' | 'escalate' | 'block_escalate' | 'priority_queue'

/** An opaque JSON object as the API serves it (event payloads, tool args, results). */
export type JsonObject = Record<string, unknown>

// --- Knowledge retrieval --------------------------------------------------------
// The result shape of the `search_knowledge` tool (`app/tools/knowledge.py`). The
// trace viewer renders it as evidence — sources, authority, conflicts — rather than
// as an opaque JSON dump, because "these disagreed and this one governed" is the
// entire point of the retrieval step (FR-D2).

/** The authority scale documents and rules share; highest wins (R-090). */
export type AuthorityLevel = 'sme_validated' | 'policy_2023' | 'policy_2019'

/** How a retrieved chunk stands after authority-based conflict resolution. */
export type RetrievedChunkStatus = 'authoritative' | 'superseded' | 'contested'

/** One side of a detected conflict, with everything needed to open the source. */
export interface ConflictParty {
  citation: string
  source_ref: string
  document: string
  section: string | null
  rule_id: string | null
  authority_level: string
  declared_value: string | null
  effective_date: string | null
  owner: string | null
}

/** Two or more retrieved sources answering the same question differently (FR-D2). */
export interface RetrievalConflict {
  topic: string
  resolved: boolean
  /** R-090 when authority resolved it; R-091 when it could not and the run fails closed. */
  resolution_rule: string
  winner: ConflictParty | null
  superseded: ConflictParty[]
  explanation: string
}

/** One retrieved chunk as the agent (and this viewer) received it. */
export interface RetrievedChunk {
  chunk_id: string
  citation: string
  source_ref: string
  section: string | null
  rule_id: string | null
  authority_level: string
  owner: string | null
  effective_date: string | null
  topic: string | null
  declared_value: string | null
  content: string
  status: RetrievedChunkStatus
  superseded_by: string | null
  lexical_rank: number | null
  semantic_rank: number | null
  score: number
}

/** The full `search_knowledge` result carried in a tool step of the trace. */
export interface RetrievalResult {
  query: string
  collections: string[]
  retrieval_mode: string
  authority_order: string[]
  chunks: RetrievedChunk[]
  conflicts: RetrievalConflict[]
}

/**
 * Narrow an arbitrary tool result to a retrieval result. Structural, not nominal:
 * the wire format types tool results as opaque JSON, so the trace viewer recognises
 * a retrieval by its shape.
 */
export function isRetrievalResult(result: JsonObject | null): result is JsonObject & RetrievalResult {
  return (
    result !== null &&
    Array.isArray(result.chunks) &&
    Array.isArray(result.conflicts) &&
    Array.isArray(result.authority_order)
  )
}

// --- Catalog ------------------------------------------------------------------

export interface Agent {
  id: string
  tenant_id: string
  slug: string
  name: string
  type: AgentType
  description: string | null
  created_at: string
}

/**
 * The parts of a DNA document this screen reads.
 *
 * `dna-schema.json` is the authority on the whole structure (golden rule 1); this is a
 * partial view of the blocks the catalog renders, not a second definition of DNA. Every
 * field is optional because the schema — not this interface — decides what is required.
 */
export interface DnaView {
  identity?: {
    name?: string
    slug?: string
    description?: string
  }
  tools?: { ref: string; autonomy: Autonomy }[]
  model?: {
    provider?: string
    model_id?: string
    max_tokens_per_run?: number
    max_cost_usd_per_run?: number
  }
  guardrails?: {
    max_steps?: number
    timeout_seconds?: number
    require_citations?: boolean
  }
}

export interface AgentVersion {
  id: string
  tenant_id: string
  agent_id: string
  /** semver */
  version: string
  status: VersionStatus
  dna: DnaView
  /** The passing eval run that satisfied the publish gate. Null for a seeded version. */
  published_eval_run_id: string | null
  published_at: string | null
  created_at: string
}

// --- Runs ---------------------------------------------------------------------

export interface StartRunRequest {
  agent_id: string
  version: string
  input: JsonObject
}

export interface Run {
  id: string
  tenant_id: string
  agent_version_id: string
  status: RunStatus
  trigger: string | null
  total_tokens: number | null
  /**
   * Exact decimal as a **string**, never a JSON number: an audit figure rounded through
   * a float is not an audit figure. Format it, do not do arithmetic on it.
   */
  total_cost_usd: string | null
  started_at: string
  finished_at: string | null
}

/** One trip through the tool gateway — including one the gateway refused to make. */
export interface ToolInvocation {
  id: string
  /** slug@semver, as named in the version's DNA grant. */
  tool_ref: string
  autonomy: Autonomy | null
  args: JsonObject | null
  result: JsonObject | null
  status: ToolStatus
  /** Why the gateway refused, when status is blocked or denied. Null when it executed. */
  error: string | null
  /** The governance code the gateway assigned. Null for a call that executed. */
  reason_code: ReasonCode | null
  /**
   * Set when this call ran only because a person released it. Null for an autonomous
   * execution — an action a human signed for must never read like one the agent took
   * on its own (FR-E4).
   */
  approval_id: string | null
  released_by: string | null
}

/**
 * One platform refusal: the code, the sentence that explains it to a non-technical
 * reader, and the specific circumstance behind it.
 *
 * `explanation` is served by the API rather than written here on purpose — the words a
 * reviewer reads are the words the platform recorded when it acted, not a second
 * vocabulary maintained in the UI that could drift from it.
 */
export interface GovernanceRecord {
  reason_code: ReasonCode
  explanation: string
  detail: string | null
  terminal_status: RunStatus
}

/**
 * A model call, as recorded in the `model.called` event payload.
 *
 * `cost_usd` is a string for the same reason `Run.total_cost_usd` is. `attempt` is 0 for
 * the first try and 1 for the single permitted schema correction (ADR-006), so a retry
 * reads as a retry rather than as two unrelated calls.
 */
export interface ModelCall {
  provider?: string
  model_id?: string
  attempt?: number
  outcome?: string
  input_tokens?: number
  output_tokens?: number
  cost_usd?: string
  budget?: {
    tokens_used?: number
    max_tokens?: number
    cost_usd?: string
    max_cost_usd?: string
  }
}

/** The agent's final decision. `citations` is non-empty by contract (R-092). */
export interface DecisionRecord {
  action: DecisionAction
  citations: string[]
  reasoning: string
  /**
   * How sure the agent was, 0–1. Required by the decision contract: below the floor the
   * agent's DNA declares, the runtime overrides the action and escalates (R-091).
   */
  confidence: number
  /**
   * Agent-specific structured result, present only when the agent produced one — the
   * normalised invoice from intake, for example. Optional in the contract and omitted
   * rather than nulled, so a decision that adjudicates carries no empty field.
   */
  output?: JsonObject
}

/**
 * One state of one approval, as a step of the run.
 *
 * It carries the tool ref and the exact arguments being decided, because that is the
 * *scope* of the approval — one action instance, its parameters, and nothing else
 * (FR-E2). A reader can see what was authorised without joining anything.
 */
export interface ApprovalRecord {
  approval_id: string
  status: ApprovalStatus
  tool_ref: string
  args: JsonObject | null
  expires_at: string
  decided_by: string | null
  decided_at: string | null
  note: string | null
  /** `approval_rejected` or `approval_expired` when the approval ended the run. */
  reason_code: ReasonCode | null
}

export interface RunStep {
  step_no: number
  kind: StepKind
  model_call: ModelCall | null
  decision: DecisionRecord | null
  tool_invocation: ToolInvocation | null
  governance: GovernanceRecord | null
  approval: ApprovalRecord | null
  created_at: string
}

/** One raw append-only event (ADR-008). `event_id` is the monotonic audit ordering. */
export interface RunEvent {
  event_id: number
  type: string
  /** `system`, `seed-script`, or `role:<role>`. */
  actor: string
  occurred_at: string
  payload: JsonObject
}

export interface RunTrace {
  run_id: string
  /** The reasoning view, projected from `events` below. */
  steps: RunStep[]
  /** The log the steps were projected from, including lifecycle events that are not steps. */
  events: RunEvent[]
}

// --- Approvals (FR-E1..E5) -----------------------------------------------------

/**
 * The action a run parked, exactly as the tool gateway validated it.
 *
 * `status` is always `validated` while pending: checked, permitted in form, and
 * deliberately not run.
 */
export interface ProposedAction {
  tool_invocation_id: string
  tool_ref: string
  autonomy: Autonomy
  args: JsonObject | null
  status: ToolStatus
}

/** One tool call the agent executed before it asked for a human. */
export interface ApprovalObservation {
  tool_invocation_id: string
  tool_ref: string
  tool_name: string
  args: JsonObject | null
  result: JsonObject | null
}

/**
 * Everything the agent gathered before it asked (FR-E1).
 *
 * Kevin Osei: *"Show me: what it wants to do, the invoice, the PO next to it, which rule
 * fired, and what's off. If I have to open the ERP in another tab, that's two more
 * minutes each."* This arrives with the queue, not behind a second request, for exactly
 * that reason.
 */
export interface ApprovalEvidence {
  agent: string
  agent_description: string | null
  run_input: JsonObject
  observations: ApprovalObservation[]
  /** Governed rule ids present in what the agent gathered — the rules in play. */
  rule_ids: string[]
}

export interface Approval {
  id: string
  tenant_id: string
  run_id: string
  /** State of the run this approval is holding: `awaiting_approval` while pending. */
  run_status: RunStatus
  status: ApprovalStatus
  proposed_action: ProposedAction
  evidence: ApprovalEvidence
  /** The sentence the platform recorded when it parked the action. */
  why_approval_required: string
  /**
   * Server-side deadline. On expiry the run is **canceled**, never approved, and no
   * operation in the API moves this value (FR-E3) — which is why there is no `extend`
   * anywhere in this file.
   */
  expires_at: string
  /** Whole seconds left; 0 once the deadline has passed. */
  seconds_remaining: number
  decision: 'approve' | 'reject' | null
  /** `role:<role>` for a human decision, `system` for an expiry. */
  decided_by: string | null
  decided_at: string | null
  note: string | null
  created_at: string
}

/**
 * One action category in the autonomy-promotion report (FR-E5).
 *
 * Read-only, and there is no call in `api` that applies one: autonomy lives in a
 * published DNA document, so raising it means authoring a new version through the eval
 * gate — never a statistic crossing a line.
 */
export interface AutonomyCandidate {
  agent: string
  agent_version_id: string
  tool_ref: string
  pending: number
  granted: number
  rejected: number
  /** Approvals nobody answered. Each canceled its run; none counts as consent. */
  expired: number
  decided: number
  /** granted / decided; null when nothing has been decided. */
  approval_rate: number | null
  candidate: boolean
  recommendation: string
  fatigue_note: string | null
}

/** The body of approve and reject: a note, and deliberately no arguments (FR-E2). */
export interface ApprovalDecisionRequest {
  note?: string
}

// --- Evals & the publish gate (FR-F1..F3) ----------------------------------------

/**
 * Where one eval run stands. Typed as an open string on purpose: the run executes
 * inline today so only these two values are served, but a queued executor would add
 * states, and an unmapped one must render as itself rather than blank the screen.
 */
export type EvalRunStatus = 'running' | 'completed' | (string & {})

/** One versioned set of eval cases — the suite a DNA's `evals.suite_ref` names. */
export interface EvalSuite {
  id: string
  tenant_id: string
  slug: string
  name: string
  /** semver of the case set */
  version: string
  case_count: number
  created_at: string
}

/** One programmatic assert of one case (FR-F3). */
export interface EvalCheckResult {
  name: string
  passed: boolean
  detail: string
}

/**
 * One scored case: expected vs actual, and every check behind the verdict.
 *
 * `run_id` names a real run of the version under test — the trace screen can open it,
 * because the runner executes cases through the same runtime as everything else.
 */
export interface EvalCaseResult {
  /** Case code, e.g. E-14. */
  code: string
  scenario: string
  passed: boolean
  expected_action: string
  /** Null when the run reached no decision (e.g. the platform refused a tool). */
  actual_action: string | null
  expected_citations: string[]
  actual_citations: string[]
  must_not_call: string[]
  tools_called: string[]
  run_id: string
  run_status: string
  /** Why the case failed, or `ok`. */
  detail: string
  checks: EvalCheckResult[]
}

/** One scoring of one suite against one agent version — the publish gate's evidence. */
export interface EvalRun {
  id: string
  tenant_id: string
  suite_id: string
  agent_version_id: string
  status: EvalRunStatus
  /** The publish-gate verdict (FR-F2). Null while still executing. */
  passed: boolean | null
  total: number | null
  passed_count: number | null
  case_results: EvalCaseResult[] | null
  created_at: string
}

/** The body of `POST /eval/suites/{suiteId}/run`: which version to score. */
export interface RunSuiteRequest {
  agent_id: string
  version: string
}

// --- Metrics & containment (FR-G3, FR-G4) ----------------------------------------

/**
 * The FR-G3 numbers over one population of runs (one agent's, or everyone's).
 *
 * Every figure is a projection of the append-only event log computed at read time —
 * there is no counters table behind this, so a number here is always recomputable from
 * the audit trail. Rates are over finished runs and are **null, not zero**, when
 * nothing has finished: "no data" and "never happens" must not read the same.
 */
export interface MetricsSummary {
  runs: number
  runs_by_status: Record<string, number>
  finished_runs: number
  /** Starts refused outright (suspended agent) — they never became runs. */
  runs_refused: number
  auto_approval_rate: number | null
  escalation_rate: number | null
  /** Platform faults only: human vetoes (approvals) are the control working. */
  block_rate: number | null
  /** `governance.blocked` events per reason code — the unfiltered truth. */
  blocks_by_reason: Record<string, number>
  avg_tokens_per_run: number | null
  /** Exact decimal as a string, like every money field. */
  avg_cost_usd_per_run: string | null
  avg_latency_seconds: number | null
  total_cost_usd: string
}

/** One recent run on the dashboard — `run_id` opens the full trace at `#/runs/<id>`. */
export interface MetricsRunRef {
  run_id: string
  agent: string
  status: string
  reason: string | null
  total_cost_usd: string | null
  started_at: string
}

/**
 * The latest `version.suspended` event's payload, verbatim from the log — what tripped
 * the breaker (or who suspended by hand). Open beyond the named fields because the
 * payload is the recorded event, not a shape this build invents.
 */
export interface SuspensionRecord {
  trigger?: 'circuit_breaker' | 'manual'
  detail?: string
  explanation?: string
  actor?: string
  occurred_at?: string
  breaker?: {
    metric?: 'failure_rate' | 'cost'
    observed?: string
    threshold?: string
    window_seconds?: number
    runs_in_window?: number
    faulted_in_window?: number
  } | null
  [key: string]: unknown
}

/** One agent's dashboard row: identity, lifecycle state, numbers, recent runs. */
export interface AgentMetrics {
  agent_id: string
  slug: string
  name: string
  /** Suspended if any version is; else published if any is; else draft. */
  state: VersionStatus
  suspension: SuspensionRecord | null
  metrics: MetricsSummary
  recent_runs: MetricsRunRef[]
}

/** The whole dashboard: every agent in the catalog, and the same numbers overall. */
export interface MetricsReport {
  generated_at: string
  overall: MetricsSummary
  agents: AgentMetrics[]
}

/** Body of the manual suspend: why, recorded verbatim in the event. */
export interface SuspendVersionRequest {
  reason?: string
}

/** Body of resume: a note, recorded with the actor who overrode the suspension. */
export interface ResumeVersionRequest {
  note?: string
}

/** The platform's error body: every failure is `{code, message, details}`. */
export interface ApiErrorBody {
  code: string
  message: string
  details?: JsonObject
}
