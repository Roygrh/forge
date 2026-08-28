# ADR-002: Backend = Python 3.12 + FastAPI

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

The backend hosts the agent runtime, tool gateway, LLM adapter layer, knowledge
retrieval, and the HITL/eval APIs. Runs are I/O-bound (model calls, DB, simulated
ERP), and every boundary must be typed and schema-validated (FR-B4, FR-C2).

## Decision Drivers

- AI ecosystem gravity: SDKs, embeddings, eval tooling are Python-first.
- Async-first workloads: agent runs spend most wall-time awaiting model/tool I/O.
- Contract discipline: Pydantic v2 gives runtime validation + JSON Schema generation
  from one model definition — the DNA schema and API contracts stay executable.
- Single builder velocity.

## Considered Options

- Python 3.12 + FastAPI + Pydantic v2
- Node.js + TypeScript (NestJS/Fastify)
- Go

## Decision Outcome

Chosen option: **Python 3.12 + FastAPI + Pydantic v2**.

FastAPI is async-native, generates OpenAPI from the same Pydantic models that
validate requests, and keeps the type system aligned with the JSON Schema contracts
at the heart of Forge. Node would unify language with the frontend but loses the
Python AI ecosystem; Go's concurrency strengths are wasted on a single-node,
I/O-bound demo and its schema/validation story is weaker.

### Consequences

- Good: one model definition serves validation, serialization, and OpenAPI; async
  handlers match the workload; fastest path for LLM/embedding integration.
- Bad: two languages in the repo (Python + TypeScript); duplicated type definitions
  at the API boundary — mitigated by generating frontend types from OpenAPI.
- Bad: Python's runtime typing is opt-in; enforced via mypy + ruff in CI, and
  Pydantic at every boundary (convention in CLAUDE.md).

## Amendment — Phase 6.2 (2026-08-26)

The decision stands. Two consequences above named "CI" as the enforcement point; the
repository at close has **no CI pipeline**, by scope. What exists is the local, documented
equivalent, run before every phase commit and recorded in `docs/PROJECT-STATE.md`:
`ruff check .`, `ruff format --check .`, `mypy app scripts tests` (clean at close) and
`pytest` (247 tests) from `src/backend`, and `tsc --noEmit` from `src/frontend`, which
also runs inside the frontend image build so a type error fails the build. Frontend types
are hand-written and cite the backend module each shape mirrors (see the ADR-007
amendment) rather than generated from OpenAPI. Adding a pipeline that runs exactly those
commands is the first item for any continuation, and changes no decision here.
