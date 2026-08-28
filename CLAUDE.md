# CLAUDE.md — Forge

Forge is a governed agent factory: business agents are declarative JSON artifacts
("DNA") executed by one runtime, with governance embedded structurally — least-privilege
tools, HITL approvals, eval-gated publishing, full traceability. Demonstrated end-to-end
with accounts-payable automation for a simulated client (Meridian Supply Co.).

## Frozen tech stack (see docs/adr/ for rationale)

| Layer | Choice | ADR |
|---|---|---|
| Backend | Python 3.12 + FastAPI + Pydantic v2 | ADR-002 |
| Agent runtime | Custom lightweight loop (no LangGraph/CrewAI) | ADR-003 |
| Persistence | PostgreSQL 16 (relational + append-only events + pgvector) | ADR-004 |
| LLM access | Internal adapter layer ("LLM gateway"), Anthropic first | ADR-005 |
| Model I/O | Structured outputs validated against JSON Schema | ADR-006 |
| Frontend | React 18 + Vite + TypeScript + Tailwind (SPA) | ADR-007 |
| Audit | Append-only events table, no UPDATE/DELETE grants | ADR-008 |
| Deployment | Docker Compose reference deployment; same images for cloud | ADR-009 |

## Repo layout (ADR-001)

```
docs/                  Source of truth: charter, discovery, architecture, ADRs
  00-charter.md        Vision, scope, frozen decisions D-01..D-05, phase plan + status
  01-discovery/        Client profile, tacit rules (R-xxx), requirements, eval cases
  02-architecture/     DNA schema + examples, C4 model, diagrams, data model, openapi.yaml
  adr/                 Architecture decision records (MADR), amended never rewritten
  demo-script.md       The verified 10-minute demo, technical + business versions
  PROJECT-STATE.md     The handoff document: read this first in a fresh session
src/backend/           Python 3.12 FastAPI service (runtime, gateways, API, seed, evals)
src/frontend/          React 18 + Vite + TypeScript SPA
deploy/                docker-compose.yml + .env.example (seed data lives in src/backend)
```

## Project status

All build phases (0–4.6, 5.1, 6.1, 6.2) are complete; 5.2 (public instance) is deferred by
decision. **No new features.** Work on this repository is now maintenance and coherence:
if code and docs diverge, fix one explicitly. `docs/PROJECT-STATE.md` holds the current
numbers, where every capability lives, and the verification sequence.

## Operating rules (learned the hard way — do not relearn them)

- **Python runs from `src/backend/.venv`.** Use `src/backend/.venv/Scripts/python` (Windows)
  or `.venv/bin/python`. Never the system interpreter.
- **Run `pytest` from `src/backend`**, not from the repo root. Tests need the compose `db`
  service reachable on `localhost:5432`; they create and drop their own `forge_test` database
  and never touch the demo data. Same directory for `ruff`, `mypy app scripts tests`,
  `python -m scripts.run_evals`.
- **Run `docker compose` from `deploy/`.** `docker compose up -d --build --wait` is the whole
  cold start. **Rebuild after any backend or frontend change** — the images are built, not
  mounted — and `docker compose down -v` when a migration or the seed changed.
- **`docker compose restart api` after every rehearsal or live run of beat 1.** The simulated
  ERP is stateful and in-process: an approved invoice stays approved, and approving it again
  is refused (correctly). Restarting `api` rebuilds it from seed. The audit log in Postgres is
  untouched.
- **On Windows, serve the API through compose, never `uvicorn` directly** — uvicorn's event
  loop policy is rejected by psycopg's async driver. The test suite runs natively.
- **One browser tab.** The SPA's acting role is page state; two tabs with different roles make
  403s look like bugs.
- **Mermaid: no semicolons inside labels or notes.** They break GitHub's renderer.
- **Vendored copies must stay byte-identical:** `app/dna/dna-schema.json` and
  `app/dna/agents/*.json` mirror `docs/02-architecture/`; `tests/test_dna_schema.py` fails if
  they drift. `app/rules/catalog.py` mirrors `04-tacit-rules.md` the same way
  (`tests/test_rules.py`). The five demo beats are defined in `app/demo_story.py`, mirrored
  in `src/frontend/src/lib/story.ts` and `docs/demo-script.md` — change all three or none.
- **A change to a definition is a new semver version.** Never edit a published DNA in place.
- **The seed's direct publish is the one documented exception to the eval gate** — visible by
  `published_eval_run_id` being null. Do not add another.

## Coding conventions

- **Python**: 3.12, full type hints (mypy-clean), `ruff` for lint + format, `pytest`
  for tests. Pydantic v2 models at every boundary. Async-first in FastAPI handlers.
- **TypeScript**: `strict: true`, no `any` without a comment justifying it.
- Tests live next to the layer they test; eval cases live in `docs/01-discovery/06-eval-cases.md`
  and are the publish gate — never weaken a case to make it pass.

## Golden rules

1. **The agent DNA JSON Schema is the central contract; nothing bypasses it.**
   The runtime executes only what a valid, versioned definition declares.
2. **All tool calls go through the tool gateway. All model calls go through the
   LLM adapter layer. No exceptions — not in tests, not in demos.**
3. **Fail closed.** On doubt, ambiguity, or missing permission → escalate.
   Never guess, never execute. Expiring approvals cancel; they never auto-approve.
4. **Every decision an agent makes must cite rule IDs (R-xxx) and be traced.**
   A decision without citations is a bug, not a style issue.
5. **docs/ is source of truth.** If code and docs diverge, fix one explicitly —
   never let them drift silently.
