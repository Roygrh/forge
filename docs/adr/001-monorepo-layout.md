# ADR-001: Monorepo layout

- Status: accepted
- Date: 2026-07-19
- Deciders: Jorge Enrique Quiroz

## Context and Problem Statement

Forge spans documentation (the primary evaluation artifact), a Python backend, a
TypeScript frontend, and deployment assets. A single builder maintains all of it,
and evaluators must be able to walk the whole system — decisions, contracts, code,
deployment — from one clone. How should the repository be organized?

## Decision Drivers

- One evaluator journey: charter → ADRs → contracts → code → `docker compose up`.
- Single builder; cross-cutting changes (e.g., a DNA schema change touching backend,
  frontend, and docs) should be one atomic commit.
- Docs are source of truth and must version together with the code they describe.

## Considered Options

- Monorepo: `docs/` + `src/backend/` + `src/frontend/` + `deploy/`
- Polyrepo (separate repos for backend, frontend, docs)

## Decision Outcome

Chosen option: **monorepo**, laid out as:

```
docs/           charter, discovery, architecture (DNA schema, C4), adr/
src/backend/    Python 3.12 FastAPI service
src/frontend/   React 18 + Vite + TypeScript SPA
deploy/         Docker Compose, seed data
```

Contract changes and their consumers land in one commit; a git tag pins docs, schema,
and code to the same state — essential when the DNA schema is the central contract.

### Consequences

- Good: atomic cross-cutting changes; one clone tells the whole story; trivially
  portable CI (one pipeline, path filters).
- Bad: mixed toolchains (pip/ruff vs npm/vite) in one repo require per-directory
  tooling config; no independent release cadence for frontend vs backend — acceptable
  because Forge ships as one product with one version.
- Bad: repo size grows with docs and seed data; mitigated by keeping generated
  artifacts out of git.

## Amendment — Phase 6.2 (2026-08-26)

The layout stands. One correction to the sketch above: **seed data does not live in
`deploy/`**. The governed rule set, the knowledge corpus, the eval cases, the simulated
ERP's records and the agent definitions are all Python and JSON under `src/backend/`
(`app/rules/catalog.py`, `app/knowledge/documents.py`, `app/evals/catalog.py`,
`app/erp/seed_data.py`, `app/dna/agents/`), applied by `scripts/seed.py`, which the
compose `migrate` container runs. `deploy/` holds `docker-compose.yml` and `.env.example`
only. The reason is the one the image build forced: the backend image's build context is
`src/backend`, so anything the seed needs has to travel inside the package — which is
also why `app/dna/` vendors byte-identical copies of the schema and the example
definitions from `docs/`, with a test that fails if they drift.
