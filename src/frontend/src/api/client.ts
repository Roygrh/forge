/**
 * The single path from this SPA to the Forge API.
 *
 * Every call goes through `request()`, which means three things are true by
 * construction rather than by discipline: the base URL is configured in exactly one
 * place, `X-Forge-Role` is on every request (NFR-5), and a failure arrives as an
 * `ApiError` carrying the platform's `{code, message, details}` body instead of an
 * unhandled rejection.
 */

import { ROLES } from './types'
import type {
  Agent,
  AgentMetrics,
  AgentVersion,
  ApiErrorBody,
  Approval,
  ApprovalDecisionRequest,
  ApprovalStatus,
  AutonomyCandidate,
  EvalRun,
  EvalSuite,
  MetricsReport,
  ResumeVersionRequest,
  Role,
  Run,
  RunSuiteRequest,
  RunTrace,
  StartRunRequest,
  SuspendVersionRequest,
} from './types'

/**
 * Configuration served with the page, when there is any.
 *
 * The production image serves `/config.js` from its own environment at container
 * start-up, because Vite inlines `VITE_*` at *build* time and an image that had the API
 * address baked in would be environment-specific — exactly what ADR-009 says these
 * images must not be. In development the placeholder in `public/config.js` sets empty
 * values and `VITE_*` takes over.
 */
const runtime: ForgeRuntimeConfig = (typeof window === 'undefined' ? undefined : window.__FORGE_CONFIG__) ?? {}

/**
 * Where the API is, as the *browser* sees it — so a Docker service name like
 * `http://api:8000` would be wrong here; it resolves to nothing on the user's machine.
 *
 * Three sources, in order: what the server handed us, what the build inlined, and the
 * documented default, which matches the compose stack publishing the API on the host at
 * :8000 (deploy/docker-compose.yml). `||` rather than `??` on purpose — an unset
 * environment variable reaches `envsubst` as an empty string, and an empty base URL
 * would point every call at the page's own origin instead of falling back.
 */
const BASE_URL = (
  runtime.apiBaseUrl ||
  import.meta.env.VITE_API_BASE_URL ||
  'http://localhost:8000'
).replace(/\/+$/, '')

const API_PREFIX = '/api/v1'

/**
 * The demonstration role this SPA acts as. It is segregation of duties made visible
 * (NFR-5), not authentication — the header names an actor, the server records it on
 * every event, and no credential is involved. It is displayed in the UI for exactly
 * that reason: a viewer should be able to see which hat the screen is wearing.
 *
 * It is **switchable at runtime**, from the header, because the separation is the thing
 * being demonstrated: the configurator who publishes an agent is refused when they try
 * to approve what it proposes, and seeing that refusal happen is more convincing than
 * reading that it would. Switching changes only which role name is sent — the server
 * decides what that role may do, and answers 403 when it may not.
 *
 * Same three sources as the base URL above. An unrecognised value — a typo, or the empty
 * string an unset environment variable expands to — falls back to `configurator` rather
 * than being forwarded: the API would reject it, and a misconfigured env var should not
 * read as a broken backend.
 */
const CONFIGURED_ROLE = runtime.role || import.meta.env.VITE_FORGE_ROLE

const DEFAULT_ROLE: Role = isRole(CONFIGURED_ROLE) ? CONFIGURED_ROLE : 'configurator'

let actingRole: Role = DEFAULT_ROLE
const roleListeners = new Set<() => void>()

function isRole(value: string | undefined): value is Role {
  return value !== undefined && (ROLES as readonly string[]).includes(value)
}

/** The role every request is currently sent as. */
export function getActingRole(): Role {
  return actingRole
}

/** Act as a different role from now on, and tell every subscribed screen. */
export function setActingRole(role: Role): void {
  if (role === actingRole) return
  actingRole = role
  roleListeners.forEach((listener) => listener())
}

/** Subscribe to role changes — the store half of `useSyncExternalStore`. */
export function subscribeToRole(listener: () => void): () => void {
  roleListeners.add(listener)
  return () => roleListeners.delete(listener)
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: ApiErrorBody['details']

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details
  }
}

/** True when the API could not be reached at all — a different problem from a 4xx. */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super(
      `Could not reach the Forge API at ${BASE_URL}. Is the backend running, and does ` +
        `its CORS_ORIGINS allow this page's origin?`,
    )
    this.name = 'NetworkError'
    this.cause = cause
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${API_PREFIX}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        'X-Forge-Role': actingRole,
        ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
      },
    })
  } catch (cause) {
    throw new NetworkError(cause)
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorBody(response))
  }
  return (await response.json()) as T
}

/**
 * Read a failure as the contract's error shape, falling back when it is not one.
 *
 * FastAPI's own 422 (a malformed request that never reached a handler) has a different
 * body, and a proxy in front of the API may answer with no JSON at all. Both still have
 * to surface as something a person can read.
 */
async function readErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    const body: unknown = await response.json()
    if (
      typeof body === 'object' &&
      body !== null &&
      typeof (body as ApiErrorBody).code === 'string' &&
      typeof (body as ApiErrorBody).message === 'string'
    ) {
      return body as ApiErrorBody
    }
    return { code: `http_${response.status}`, message: JSON.stringify(body) }
  } catch {
    return { code: `http_${response.status}`, message: response.statusText || 'Request failed' }
  }
}

export const api = {
  /** The agent catalog. */
  listAgents: () => request<Agent[]>('/agents'),

  /** One agent's versions, newest first. */
  listVersions: (agentId: string) =>
    request<AgentVersion[]>(`/agents/${encodeURIComponent(agentId)}/versions`),

  /**
   * Start a run. The API executes it inline and answers 202 once it is terminal, so the
   * trace is complete the moment this resolves.
   */
  startRun: (body: StartRunRequest) =>
    request<Run>('/runs', { method: 'POST', body: JSON.stringify(body) }),

  getRun: (runId: string) => request<Run>(`/runs/${encodeURIComponent(runId)}`),

  /** The ordered trace, projected from this run's append-only events (ADR-008). */
  getTrace: (runId: string) => request<RunTrace>(`/runs/${encodeURIComponent(runId)}/trace`),

  /**
   * The approval queue, with the evidence to decide each item (FR-E1).
   *
   * The server expires anything past its deadline before answering, so nothing returned
   * as pending has already lapsed — this SPA never decides that question, and could not:
   * the browser's clock is not the one the deadline is measured against.
   */
  listApprovals: (status: ApprovalStatus = 'pending') =>
    request<Approval[]>(`/approvals?status=${encodeURIComponent(status)}`),

  getApproval: (approvalId: string) =>
    request<Approval>(`/approvals/${encodeURIComponent(approvalId)}`),

  /**
   * Release exactly this action; the run resumes and carries it out.
   *
   * The body is a note and nothing else. It carries no arguments on purpose — what runs
   * is the call the agent parked, with the parameters the gateway already validated
   * (FR-E2) — and there is deliberately no `extendApproval` beside this one: expiry is
   * enforced server-side and always cancels (FR-E3).
   */
  approve: (approvalId: string, body: ApprovalDecisionRequest = {}) =>
    request<Approval>(`/approvals/${encodeURIComponent(approvalId)}/approve`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Refuse the action and cancel its run. Nothing is executed. */
  reject: (approvalId: string, body: ApprovalDecisionRequest = {}) =>
    request<Approval>(`/approvals/${encodeURIComponent(approvalId)}/reject`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Approval rates per action category — read-only, and applied by nothing (FR-E5). */
  getApprovalReport: () => request<AutonomyCandidate[]>('/approvals/report'),

  /** The eval suite catalogue, each with its case count (FR-F1). */
  listEvalSuites: () => request<EvalSuite[]>('/eval/suites'),

  /**
   * Run a suite against an agent version. Executes inline: the 202 body already
   * carries the verdict — per-case results and the `passed` boolean the gate reads.
   */
  runEvalSuite: (suiteId: string, body: RunSuiteRequest) =>
    request<EvalRun>(`/eval/suites/${encodeURIComponent(suiteId)}/run`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Eval runs for one version, newest first — how the gate's state is learned. */
  listEvalRuns: (agentVersionId: string) =>
    request<EvalRun[]>(`/eval/runs?agent_version_id=${encodeURIComponent(agentVersionId)}`),

  getEvalRun: (evalRunId: string) => request<EvalRun>(`/eval/runs/${encodeURIComponent(evalRunId)}`),

  /**
   * Publish a version — the hard eval gate (FR-F2). The server answers 409 with
   * `publish_gate_unmet` unless this exact version has a completed, passing eval run
   * for the suite its DNA declares. There is deliberately no force flag to send.
   */
  publishVersion: (agentId: string, version: string) =>
    request<AgentVersion>(
      `/agents/${encodeURIComponent(agentId)}/versions/${encodeURIComponent(version)}/publish`,
      { method: 'POST' },
    ),

  /**
   * The dashboard (FR-G3): every agent's metrics plus the overall picture, projected
   * from the append-only event log at request time — never a counters table.
   */
  getMetrics: () => request<MetricsReport>('/metrics'),

  getAgentMetrics: (agentId: string) =>
    request<AgentMetrics>(`/agents/${encodeURIComponent(agentId)}/metrics`),

  /** Halt a published version, on the record. Needs `agent.suspend`. */
  suspendVersion: (agentId: string, version: string, body: SuspendVersionRequest = {}) =>
    request<AgentVersion>(
      `/agents/${encodeURIComponent(agentId)}/versions/${encodeURIComponent(version)}/suspend`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  /**
   * The one way out of a suspension (FR-G4). Needs `agent.resume`, which only the
   * admin role holds — the server refuses every other hat, and records the attempt.
   */
  resumeVersion: (agentId: string, version: string, body: ResumeVersionRequest = {}) =>
    request<AgentVersion>(
      `/agents/${encodeURIComponent(agentId)}/versions/${encodeURIComponent(version)}/resume`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
}

export const apiBaseUrl = BASE_URL
