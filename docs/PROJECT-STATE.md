# Forge — Project State (handoff)

> Written to be pasted into a fresh context, human or AI. It contains project state only:
> what Forge is, what is built and where, what was decided and must not be casually
> revisited, the operating rules that were learned the hard way, what remains, and how to
> verify that everything still works. Last verified **2026-08-26** at the close of Phase 6.2.

---

## 1. What Forge is

Forge is a **governed agent factory**: business agents are declarative JSON documents (their
"DNA", valid against `docs/02-architecture/dna-schema.json`) executed by **one runtime**, with
governance embedded structurally — least-privilege tool grants with an autonomy level each,
human-in-the-loop approvals that expire into cancellation, eval-gated publishing, and an
append-only audit log every decision is reconstructable from. It is demonstrated end to end
with accounts-payable invoice approval for a simulated client, Meridian Supply Co.

The thesis in one line: **agents are configuration, not code; one runtime executes N of
them; and an agent can only ever do what its document declares.** The root `README.md` is
the front door; `CLAUDE.md` holds the golden rules and the operating rules for a session.

---

## 2. Current state — complete, phase by phase

**Every build phase is closed.** Verified 2026-08-26: `pytest` **247 passed** (25.6 s);
`python -m scripts.run_evals` **20/20**; `ruff check`, `ruff format --check`, `mypy app
scripts tests`, `tsc --noEmit` all clean; five demo beats asserted end to end by
`tests/test_demo_story.py`; cold `docker compose up -d --build --wait` from an empty volume
leaves a ready stack (`GET /api/v1/ready` → `{"status":"ready", …, "schema_revision":"0006"}`).

What the seed installs (`docker compose logs migrate`): 1 tenant (`meridian-supply-co`),
**22** rules (R-001…R-092, `rules v1.0.0`), **32** knowledge chunks over three collections
(`meridian-ap-tacit-rules`, `ap-policy-2023`, `ap-policy-2019`), **20** eval cases
(`meridian-ap-eval-suite@1.0.0`), and **4** published agent versions: `invoice-intake@1.1.0`,
`invoice-validator@1.2.0`, `invoice-comms@1.2.0`, `invoice-validator-restricted@1.1.0`.
Schema: 6 Alembic migrations (`0001`…`0006`), 15 tables.

| Phase | Commit | What exists | Where it lives |
|---|---|---|---|
| 0 Planning | `c8f570b` 2026-07-20 | Charter with frozen decisions D-01..D-05 and the phase plan; status at close in §10 | `docs/00-charter.md` |
| 1 Discovery | `c8f570b` | Client profile, stakeholders, interview notes, **22 tacit rules** R-xxx, MoSCoW requirements FR-A..G / NFR-1..6, **20 eval cases** E-01..E-20 written before any code | `docs/01-discovery/01…06` |
| 2 Architecture | `c8f570b`, `fa3bc07` 2026-07-29 | Ten ADRs; DNA JSON Schema (draft 2020-12) with `const`-locked governance fields; four DNA examples; C4 model (Structurizr DSL); four Mermaid diagrams; ER data model; OpenAPI contract | `docs/adr/`, `docs/02-architecture/{dna-schema.json,dna-README.md,dna-examples/,c4/workspace.dsl,diagrams/,data-model.md,api/openapi.yaml}` |
| 3 Walking skeleton | `ef03f41`, `12267e2`, `46d44b4` 2026-07-29 → 08-03 | FastAPI service, SQLAlchemy models, initial migration with the append-only `events` grants **and trigger**; the runtime loop; LLM gateway with three adapters (`fake`, `meridian-demo`, `anthropic`); tool gateway; trace as a projection of events; first SPA | `src/backend/app/{main,db,config}.py`, `app/models/`, `alembic/versions/20260729_0001_initial_schema.py`, `app/runtime/`, `app/llm/`, `app/tools/{contract,registry,gateway}.py`, `src/frontend/` |
| 4.1 AP domain | `69398cc` 2026-08-06 | Simulated MeridianERP (in-process, own storage, own ledger), 7 ERP tools + rule-lookup tool, **rules as data** (`rules` table, condition grammar, general interpreter), three agents + the restricted one | `app/erp/`, `app/tools/meridian.py`, `app/rules/`, `app/dna/agents/*.json`, migration `0002` |
| 4.2 Governance | `898666d` 2026-08-06 | Autonomy dispatch table (`AUTONOMY_EFFECT`), fail-closed reason codes with explanations, `governance` trace steps, hard limits (`max_steps`, tokens, cost per run and per day, timeout, confidence floor), role/permission matrix with `INCOMPATIBLE_DUTIES` checked at import, single enforcement point proved by a source-tree test | `app/governance.py`, `app/tools/gateway.py`, `app/runtime/loop.py`, `app/api/deps.py`, `tests/test_governance.py`, migration `0003` |
| 4.3 Knowledge | `8995eb6` 2026-08-09 | Chunking + ingestion, hashing embedder (offline), hybrid retrieval (tsvector + pgvector, RRF), authority hierarchy `sme_validated > policy_2023 > policy_2019`, conflict detection with `remediation_items`, verifiable citations, `meridian-knowledge-retrieve` tool scoped by the DNA's collections | `app/knowledge/`, `app/tools/knowledge.py`, `app/api/knowledge.py`, migration `0004` |
| 4.4 HITL | `8515e8e` 2026-08-10 | Approval queue with server-side expiry that **cancels**, evidence served with each item, approve/reject as recorded events, **resume by replaying the event log** (ADR-010), `Released by` on the executed call, autonomy-promotion report (read-only) | `app/approvals/`, `app/runtime/transcript.py`, `app/api/approvals.py`, `scripts/demo_hitl.py`, migration `0005` |
| 4.5 Evals gate | `f043f0f` 2026-08-10 | 20 cases as data, deterministic offline runner (one real run per case against a private per-case ERP), `eval_runs` row as evidence, `POST …/publish` → **409** until the declared suite passed, Evals screen | `app/evals/`, `app/api/evals.py`, `app/api/agents.py` (publish), `scripts/run_evals.py`, `scripts/demo_publish_gate.py`, migration `0006` |
| 4.6 Observability | `36bb539` 2026-08-10 | Per-agent metrics projected from `events` at read time (no metrics table), circuit breaker over a trailing window that suspends a version and refuses its next start, admin-only recorded resume, Metrics screen | `app/observability/`, `app/api/metrics.py`, `app/api/agents.py` (suspend/resume), `scripts/demo_observability.py` |
| 5.1 Deployment | `eff7981` 2026-08-23 | One-command cold start: one-shot `migrate` container (`scripts/init_db.py`), TCP DB healthcheck, `api` gated on `service_completed_successfully`; `/health` (liveness) vs `/ready` (readiness, 503 naming the failed check); production SPA build behind nginx with `/config.js` served at start; every variable documented in `.env.example` files | `deploy/docker-compose.yml`, `deploy/.env.example`, `src/backend/.env.example`, `app/api/health.py`, `src/frontend/{Dockerfile,nginx/}` |
| 5.2 Public instance | — | **Deferred by decision** (see §5) | ADR-009 amendment, charter §10 |
| 6.1 Demo packaging | `b1e815a` 2026-08-26 | Five beats as data with expected outcomes, mirrored in the SPA's **Case to run** picker, asserted by tests; the ten-minute script in technical and business versions with pre-flight and recovery | `app/demo_story.py`, `src/frontend/src/lib/story.ts`, `tests/test_demo_story.py`, `docs/demo-script.md` |
| 6.2 README & coherence | this commit, 2026-08-26 | The root README as a product front page; every status-bearing document made true; dated ADR amendments; this file | `README.md`, `CLAUDE.md`, `docs/00-charter.md`, `docs/adr/00{1,2,7,8,9}`, `docs/02-architecture/*`, `src/*/README.md`, `docs/PROJECT-STATE.md` |

### The served API (26 operations, prefix `/api/v1`; all but the two probes take `X-Forge-Role`)

`GET /health` · `GET /ready` · `GET /agents` · `GET|POST /agents/{id}/versions` ·
`GET /agents/{id}/versions/{v}` · `POST …/{v}/publish` · `POST …/{v}/suspend` · `POST …/{v}/resume` ·
`GET /agents/{id}/metrics` · `POST /runs` · `GET /runs/{id}` · `GET /runs/{id}/trace` ·
`GET /approvals` · `GET /approvals/report` · `GET /approvals/{id}` · `POST /approvals/{id}/approve` ·
`POST /approvals/{id}/reject` · `GET /knowledge/collections` · `GET /knowledge/chunks/{id}` ·
`GET /knowledge/remediation` · `GET /eval/suites` · `POST /eval/suites/{id}/run` · `GET /eval/runs` ·
`GET /eval/runs/{id}` · `GET /metrics`.

Declared in `openapi.yaml` but **not served** (marked `x-forge-status: not-implemented`):
`POST /agents`, `POST /knowledge/collections/{id}/ingest`, `GET /tools`.

### Roles and permissions (`app/governance.py`)

| Role | Holds |
|---|---|
| `configurator` | `read`, `agent.configure`, `agent.publish`, `run.start`, `agent.suspend` |
| `approver` | `read`, `approval.decide` |
| `viewer` | `read` |
| `admin` | `read`, `agent.suspend`, `agent.resume` |

Incompatible pairs, refused at import: configure/approve, publish/approve, configure/resume,
publish/resume.

### The SPA (five hash routes)

`#/` catalog with **Case to run** picker · `#/runs/<id>` trace (header, timeline, raw events) ·
`#/approvals` queue + promotion report · `#/evals` suite + publish gate · `#/metrics` dashboard
with suspend/resume. Acting role switchable in the header; the server decides, the UI never
disables by role.

---

## 3. Frozen decisions — NOT to be revisited without cause

Each ADR lives in `docs/adr/` with context, alternatives and consequences. Amendments are
dated sections appended to the record; history is never rewritten.

| ADR | Decision (one line) | Amended |
|---|---|---|
| 001 | Monorepo: `docs/` + `src/backend/` + `src/frontend/` + `deploy/`; contract changes and consumers land in one commit | 6.2: seed data lives in `src/backend`, not `deploy/` |
| 002 | Backend = Python 3.12 + FastAPI + Pydantic v2; one model definition serves validation, serialization and OpenAPI | 6.2: no CI pipeline exists; the checks run locally and are documented |
| 003 | Agent runtime = custom lightweight loop, not LangGraph/CrewAI; governance is first-class code; no framework type in any persisted artifact | — |
| 004 | Persistence = PostgreSQL 16 alone (relational + append-only events + pgvector); revisit thresholds stated | — |
| 005 | LLM access = internal adapter layer with one `complete()` contract; per-agent model and budgets from the DNA; keys only in the gateway | — |
| 006 | Model responses = structured outputs validated against JSON Schema; exactly one corrective retry, then escalate | — |
| 007 | Frontend = React 18 + Vite + TypeScript strict + Tailwind SPA; no SSR | 6.2: API types are hand-written, not generated |
| 008 | Audit = append-only `events` table; immutability by database grant | 6.2 (recording 3.1): a trigger enforces it for the owner connection too |
| 009 | Deployment = Docker Compose reference deployment; same images everywhere | 5.1: self-migrating one-shot container, production SPA build, liveness/readiness split · 6.2: public instance deferred |
| 010 | A paused run resumes by replaying its own event log; no checkpoint blob; per-run ceilings survive the pause | — |

Charter decisions (`docs/00-charter.md` §7):

| # | Decision |
|---|---|
| D-01 | Business vertical: accounts payable / invoice approval |
| D-02 | Diagrams: Structurizr DSL (C4) for structure + Mermaid for behaviour |
| D-03 | Decision log: ADRs in MADR format |
| D-04 | Repository language: English |
| D-05 | Simulated client: Meridian Supply Co. |

Structural invariants that are tested, not remembered: the four `const` governance fields
in the DNA schema; the `events` grant + trigger; a tool handler invoked in exactly one place
(`ToolGateway._execute`); `INCOMPATIBLE_DUTIES` checked at import; no extend operation on
approvals anywhere in the served contract; the vendored schema and agent JSON byte-identical
to `docs/`; `app/rules/catalog.py` in lockstep with `04-tacit-rules.md`.

---

## 4. Operating rules — learned the hard way

- **Python is `src/backend/.venv`.** `src/backend/.venv/Scripts/python` on Windows,
  `.venv/bin/python` elsewhere. Install with `python -m pip install -e ".[dev]"` from `src/backend`.
- **`pytest` runs from `src/backend`**, needs the compose `db` on `localhost:5432`, creates and
  drops its own `forge_test` database (real Alembic migration, not `create_all`), and never
  touches demo data. Same directory for `ruff`, `mypy app scripts tests`, and every `scripts.*`.
- **`docker compose` runs from `deploy/`.** `docker compose up -d --build --wait` is the whole
  cold start (~2–3 min cold, ~40 s warm). **Rebuild after any code change** — images are
  built, not mounted. `docker compose down -v` when a migration or the seed changed.
- **`docker compose restart api` after every rehearsal** and after any live run of beat 1. The
  simulated ERP is in-process and stateful: an approved invoice stays approved and a second
  approval is refused (the duplicate-payment control, working). Restarting `api` rebuilds the
  ERP from seed; the audit log in Postgres is untouched.
- **On Windows, never run `uvicorn` directly** — its event-loop policy is rejected by psycopg's
  async driver. Serve through compose; the test suite runs natively.
- **One browser tab.** The acting role is page state; two tabs with different roles make 403s
  look like bugs.
- **Mermaid: no semicolons inside labels or notes** — they break GitHub's renderer.
- **Change a definition → new semver version.** Never edit a published DNA. Every 1.0.0
  definition became invalid when `min_decision_confidence` became required (4.2), which is
  why the shipped versions are 1.1.0 / 1.2.0.
- **Vendored copies and mirrors:** `app/dna/dna-schema.json` and `app/dna/agents/*.json` mirror
  `docs/02-architecture/` (tested); `app/rules/catalog.py` mirrors `04-tacit-rules.md`
  (tested); the five beats live in `app/demo_story.py`, `src/frontend/src/lib/story.ts` and
  `docs/demo-script.md` — change all three or none; `src/frontend/src/api/types.ts` mirrors
  `app/api/schemas.py` by hand.
- **The seed's direct publish is the one documented exception to the eval gate** (visible:
  `published_eval_run_id` is null). Do not add another.
- **Running the validator on the same invoice twice** escalates the second time (ERP refuses
  the re-approval). `python -m scripts.run_evals` writes a real `eval_runs` row to the demo
  database, so the Evals screen stops reading *No eval run for this version yet* — `down -v`
  before a demo that wants the empty-screen moment.
- **Beat 5's recorded action is `auto_approve`** (a successfully answered question maps to the
  permissive action; documented in `app/evals/catalog.py`). **Beat 4, after approval, ends
  `escalated` citing R-091** with a `no_rule_match` banner — correct: the invoice is unresolved
  until the vendor answers.

---

## 5. What remains

| Item | Status | Detail |
|---|---|---|
| **Phase 5.2 — public hosted instance** | **Deferred by decision** (ADR-009 amendment, charter §10) | A public instance with a trusted `X-Forge-Role` header and env-file secrets would be a standing liability for a governance demo. The local one-command start plus a demo video cover the need. **Revisit when:** real authentication exists in front of the SPA and API, or an evaluator cannot run Docker. The change is environment values (`FORGE_API_BASE_URL`, `CORS_ORIGINS`, `POSTGRES_*`), not a rebuild. |
| **Demo video** | Pending — a human task | Record the technical version of `docs/demo-script.md` against a fresh stack (`down -v`, `up --build --wait`, pre-flight table). The appendix has every beat as an API call for a headless take. |
| **Screenshots in the README** | Pending — a human task | The `<!-- SCREENSHOT: … -->` placeholders in `README.md` list each screen and what must be visible. |
| Agent-authoring UI | Out of scope, by decision | `POST /agents/{id}/versions` admits a schema-validated draft; the eval gate stands in front of publishing it. The form adds no governance. |
| Real authentication | Out of scope, by charter | The permission matrix, 403s and audit of refusals are real; the header is trusted. First hardening item. |
| Real ERP | Out of scope, by charter | `app/erp/store.py` becomes an HTTP client behind the same seven tool contracts. |
| Operational multi-tenancy | Out of scope, by charter | `tenant_id` on every business table; one tenant seeded. |
| `POST /agents`, ingest endpoint, `GET /tools` | Declared, not served | Marked in `openapi.yaml`. Agents come from the seed; ingestion runs at seed time; the registry is code. |
| Instruction `system_blocks` (FR-A5) | Declared in the schema, refused by the runtime (`unsupported_definition`) | The one declared DNA capability the build does not resolve; refusing beats executing less-informed than published. |
| CI pipeline | None | The local check sequence in §6 is the equivalent; a pipeline running exactly it is the first continuation item (ADR-002 amendment). |

**No new features are planned.** Any continuation is maintenance, coherence, or the items above.

---

## 6. Verify everything still works

Copy-paste, in order, from the repository root. Windows paths shown; use `.venv/bin/python`
on Linux/macOS.

```bash
# 1. Cold start from nothing (destroys demo state; ~2-3 min first time)
cd deploy
docker compose down -v
docker compose up -d --build --wait
curl http://localhost:8000/api/v1/ready
#    {"status":"ready","checks":{"database":"ok","migrations":"ok","seed":"ok"},...,"schema_revision":"0006","expected_revision":"0006"}
docker compose logs migrate
#    22 rules, 32 chunks, 20 cases, four agents published, "demo story: 5 beats"
cd ..

# 2. Backend: tests, lint, types (needs the compose db on localhost:5432)
cd src/backend
.venv/Scripts/python -m pytest                      # expect: 247 passed
.venv/Scripts/python -m ruff check .                # expect: All checks passed!
.venv/Scripts/python -m ruff format --check .       # expect: N files already formatted
.venv/Scripts/python -m mypy app scripts tests      # expect: Success: no issues found

# 3. The publish gate and the demo scripts, over the real HTTP surface
.venv/Scripts/python -m scripts.run_evals           # expect: PASSED: 20/20 cases passed
.venv/Scripts/python -m scripts.demo_publish_gate   # 409, then 20/20, then published with evidence
.venv/Scripts/python -m scripts.demo_hitl           # parked-approved-resumed, parked-expired-canceled
.venv/Scripts/python -m scripts.demo_observability  # metrics, breaker trips, admin resumes
cd ../..

# 4. Frontend types
cd src/frontend
npm install
npm run typecheck                                   # expect: no output (clean)
cd ../..

# 5. Reset before showing anything. The scripts above approved invoices in the simulated
#    ERP, recorded an eval run, and demo_publish_gate published an extra validator version
#    (next free patch) into the catalog. `restart api` alone only resets the ERP; to return
#    to the seeded state, repeat the cold start:
cd deploy && docker compose down -v && docker compose up -d --build --wait && cd ..

# 6. The five beats, in the browser: http://localhost:5173, role Configurator,
#    "Case to run" 1..5 per docs/demo-script.md. Expected outcomes are in the table there.
#    After any live run of beat 1: `docker compose restart api` (from deploy/).
```

If step 1 fails, `docker compose logs migrate` and `curl …/ready` name the failing check;
`docs/demo-script.md` → *Recovery* has the thirty-second answer to each symptom.
