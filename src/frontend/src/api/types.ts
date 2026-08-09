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

/** The demonstration roles the API accepts in `X-Forge-Role` (NFR-5). */
export type Role = 'configurator' | 'approver' | 'viewer'

export const ROLES: readonly Role[] = ['configurator', 'approver', 'viewer']

export type AgentType = 'chatbot' | 'workflow' | 'autonomous'

export type VersionStatus = 'draft' | 'published' | 'suspended'

export type RunStatus =
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'escalated'
  | 'canceled'
  | 'error'

export type StepKind = 'reason' | 'tool' | 'decision' | 'governance'

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
  | 'no_rule_match'
  | 'knowledge_conflict'
  | 'low_confidence'
  | 'invalid_output'
  | 'step_limit'
  | 'timeout'
  | 'budget_exceeded'
  | 'daily_budget_exceeded'
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

export interface RunStep {
  step_no: number
  kind: StepKind
  model_call: ModelCall | null
  decision: DecisionRecord | null
  tool_invocation: ToolInvocation | null
  governance: GovernanceRecord | null
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

/** The platform's error body: every failure is `{code, message, details}`. */
export interface ApiErrorBody {
  code: string
  message: string
  details?: JsonObject
}
