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
  AgentVersion,
  ApiErrorBody,
  Role,
  Run,
  RunTrace,
  StartRunRequest,
} from './types'

/**
 * Supplied by Vite from the environment — inlined by `vite build`, injected by the dev
 * server. Either way it names the API as the *browser* sees it, so a Docker service
 * name would be wrong here. The default matches the compose stack, which publishes the
 * API on the host at :8000 (deploy/docker-compose.yml).
 */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/+$/, '')

const API_PREFIX = '/api/v1'

/**
 * The demonstration role this SPA acts as. It is segregation of duties made visible
 * (NFR-5), not authentication — the header names an actor, the server records it on
 * every event, and no credential is involved. It is displayed in the UI for exactly
 * that reason: a viewer should be able to see which hat the screen is wearing.
 *
 * An unrecognised value falls back to `configurator` rather than being forwarded: the
 * API would reject it, and a misconfigured env var should not read as a broken backend.
 */
export const ACTING_ROLE: Role = isRole(import.meta.env.VITE_FORGE_ROLE)
  ? import.meta.env.VITE_FORGE_ROLE
  : 'configurator'

function isRole(value: string | undefined): value is Role {
  return value !== undefined && (ROLES as readonly string[]).includes(value)
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
        'X-Forge-Role': ACTING_ROLE,
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
}

export const apiBaseUrl = BASE_URL
