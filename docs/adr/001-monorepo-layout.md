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
