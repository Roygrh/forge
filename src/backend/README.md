# Forge backend

Python 3.12 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 + pgvector ([ADR-002](../../docs/adr/002-backend-python-fastapi.md), [ADR-004](../../docs/adr/004-postgres-single-store.md))

**Phase 4.4 scope:** the human in the loop. A `requires_approval` tool call now opens a
pending approval with a **server-side deadline**, and the run waits in
`awaiting_approval` — the one state a run comes back from. It leaves that state in
exactly three ways: an approver releases it (the run resumes and executes *that* action,
with *those* arguments, through the same tool gateway), refuses it (the run is canceled),
or the deadline passes with nobody deciding — which also **cancels**, because an approval
that ran out of time is never a yes, and there is no operation anywhere in this API that
extends one. The queue serves the evidence to decide each item with the item itself, and
the autonomy-promotion report (FR-E5) measures approval rates per action category and
applies nothing. The eval publish gate (4.5) is still ahead; where this build cannot
honour something, it refuses rather than approximates.

Earlier phases still hold: the autonomy levels are enforced in one place and cannot be
bypassed (4.2); every refusal carries a machine-readable reason code, a plain-language
explanation, and a governance step in the trace; the DNA's hard limits are enforced; and
knowledge retrieval ranks conflicting sources by authority rather than averaging them
(4.3).

## Quickstart (three commands)

From the repository root:

```bash
cd deploy && docker compose up -d --build        # 1. Postgres + API + SPA
docker compose exec api alembic upgrade head     # 2. schema
docker compose exec api python -m scripts.seed   # 3. tenant + rules + agents
```

Then open <http://localhost:5173> and press **Run** ([`src/frontend`](../frontend/README.md)) —
or do the same from a terminal:

```bash
curl http://localhost:8000/api/v1/health         # {"status":"ok","db":"ok"}

AGENT=$(docker compose exec -T db psql -U forge -d forge -tA \
  -c "select id from agents where slug='invoice-validator'")

RUN=$(curl -s -X POST http://localhost:8000/api/v1/runs \
  -H 'Content-Type: application/json' -H 'X-Forge-Role: configurator' \
  -d "{\"agent_id\":\"$AGENT\",\"version\":\"1.2.0\",\"input\":{\"invoice_id\":\"inv-0001\"}}" \
  | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')

curl -s "http://localhost:8000/api/v1/runs/$RUN/trace" -H 'X-Forge-Role: configurator'
```

`inv-0001` is eval case E-01 and auto-approves citing R-001 and R-010. The other seeded
invoices exercise the rest of the rule set — `inv-0009` ($12,000: a threshold overrides
trust, R-020 resolved against R-001 by R-090), `inv-0015` (a duplicate invoice number:
blocked under R-040, and `approve_invoice` never called), `inv-0021` (nothing matches:
escalate under R-091). Every record in `app/erp/seed_data.py` names the eval case it
exists for.

To watch the platform **refuse** something, run `invoice-validator-restricted` against
the same `inv-0001`. It is the validator with one line changed — `approve_invoice`
granted as `forbidden` — so the rules still say auto-approve, the agent still asks, and
the gateway denies it:

```
12  TOOL      meridian-erp-approve-invoice@1.0.0  forbidden  -> DENIED [permission_denied]
13  BLOCKED   permission_denied  (run ends escalated)
            The agent asked for a tool its own definition does not permit it to use.
```

And to see segregation of duties bite, send the same request as `-H 'X-Forge-Role:
approver'`: 403 `permission_denied`, with the attempt recorded as a
`governance.permission_denied` event.

The run completes with no API key and no network: the seeded agents' DNA names the
deterministic in-process provider (ADR-005). Point a `model` block at
`{"provider": "anthropic", "model_id": "claude-haiku-4-5"}` and set `ANTHROPIC_API_KEY`
to run the same agent against a real model — that swap is the only change needed.

**On Windows, serve the API through compose rather than `uvicorn` directly.** uvicorn
installs its own event loop policy on Windows, which psycopg's async driver rejects; the
container is Linux, so the documented path is unaffected. The test suite runs natively.

Interactive docs: <http://localhost:8000/api/v1/docs>.

Migrations are a deliberate, separate step — the API never migrates on boot, so a
schema change is always an explicit, reviewable action.

## Tests

```bash
cd src/backend
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pytest
```

Tests need a reachable PostgreSQL — the compose `db` service is published on
`localhost:5432` for exactly this. They **do not** touch the dev database: the suite
creates a throwaway `forge_test` database in the same cluster, migrates it with
Alembic, and drops it at the end (`tests/conftest.py`). Point them at another cluster
with `DATABASE_URL`; the database name in that URL is replaced with `forge_test`.

Running the real migration in tests is deliberate: the append-only guarantee lives in
the migration, so a suite that built its tables with `create_all` would never test it.

Lint, format, and types:

```bash
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m mypy app scripts tests
```

## Layout

| Path | Purpose |
|---|---|
| `app/config.py` | Settings from the environment; `DATABASE_URL` required, `ANTHROPIC_API_KEY` optional |
| `app/db.py` | Async engine for the API, sync engine for migrations/scripts/tests |
| `app/main.py` | FastAPI app; health probe, CORS for the SPA, and the routers |
| `app/models/` | The fifteen tables of [`data-model.md`](../../docs/02-architecture/data-model.md) as plain mappings |
| `app/governance.py` | The governance vocabulary: every reason the platform refuses, its plain-language explanation, and the role/permission matrix that enforces NFR-5 |
| `app/erp/` | Simulated MeridianERP: vendors, POs, receipts, invoices, and the fact sheet the rules are evaluated against. An external system, not platform state |
| `app/rules/` | The governed rule set as data: the condition grammar, a general interpreter for it, the seed encoding of the tacit-rules document, and the loader |
| `app/dna/` | The DNA contract: vendored JSON Schema (write-time) + typed Pydantic view (read-time) |
| `app/llm/` | The LLM gateway ([ADR-005](../../docs/adr/005-llm-adapter-layer.md)): one `complete()` contract, budget enforcement, three adapters |
| `app/tools/` | The tool registry and gateway — the only path from an agent to a tool (FR-C1) — plus the eight MeridianERP and rule-lookup tools (FR-C4) |
| `app/runtime/` | The loop ([ADR-003](../../docs/adr/003-custom-agent-runtime.md)), structured-output validation ([ADR-006](../../docs/adr/006-structured-outputs.md)), the trace writer/reader, and the transcript a paused run is resumed from ([ADR-010](../../docs/adr/010-resume-by-replay.md)) |
| `app/approvals/` | The human-in-the-loop queue: parking, approve/reject, server-side expiry that cancels, the evidence an approver is shown, and the read-only autonomy-promotion report (FR-E1..E5) |
| `app/api/` | Agent-catalog, run, **approval** and knowledge endpoints, the error shape, and the gateway dependencies |
| `alembic/` | Migration environment; the URL comes from settings, never from `alembic.ini` |
| `scripts/seed.py` | Idempotent seed: tenant, the governed rule set, and the published agent definitions |
| `scripts/demo_hitl.py` | Drives the approval queue over the real HTTP surface and prints both traces: one parked-approved-resumed-executed, one parked-expired-canceled |
| `tests/` | Health, config, models, append-only, DNA contract, both gateways, output validation, the rule layer, **governance** (autonomy matrix, fail-closed matrix, hard limits, SoD), the AP agents end to end, the catalog, the runtime, and **approvals** (approve/reject/expire, granularity, segregation of duties, and the absence of any extend operation) |

## Notes for reviewers

- **`events` is append-only in the database, not by convention** ([ADR-008](../../docs/adr/008-append-only-audit.md)).
  The initial migration installs both layers: `INSERT`/`SELECT`-only grants for the
  `forge_app` role, *and* a trigger that raises on `UPDATE`/`DELETE`/`TRUNCATE` — because
  PostgreSQL exempts a table's owner from its own grants, and the demo connects as the
  owner. `tests/test_events_append_only.py` proves both.
- **Models carry no `relationship()` definitions.** Phase 3.1 needs plain table
  mappings; lazy relationship loading in async handlers is a footgun best introduced
  with the queries that actually need it.
- **`knowledge_chunks.embedding` is a dimensionless `vector`.** The width is fixed by
  the embedding model, chosen with the knowledge layer in Phase 4.3, along with its ANN
  index. Guessing a width now would bake a decision into the schema.
- **Two engines, one URL.** psycopg 3 serves sync and async behind one SQLAlchemy
  dialect, so migrations and the API cannot drift onto different databases.
- **Windows dev machines**: `app/main.py` selects the selector event loop, which
  psycopg's async driver requires. A no-op on the Linux container ([ADR-009](../../docs/adr/009-docker-compose-deployment.md)).
  It covers the test suite but *not* `uvicorn` on Windows — uvicorn installs its own
  policy after import. Serve through compose there.
- **The trace is a projection of events, not of the state tables.**
  `GET /runs/{id}/trace` reads `events` alone and derives the ordered steps from it, so
  "the screen shows exactly what happened" is true by construction ([ADR-008](../../docs/adr/008-append-only-audit.md)).
  The response carries the raw events too, so the projection can be checked against its
  source. `run_steps` and `tool_invocations` remain the queryable current-state tables,
  written in the same transaction as their event.
- **Every refusal is recorded.** A tool call that is blocked or denied still writes a
  `tool_invocations` row and a `tool.called` event: a reviewer must be able to see what
  the agent *tried* to do, not only what it was allowed to do (FR-C5).
- **The runtime refuses DNA it cannot honestly execute.** A definition declaring
  instruction blocks or knowledge collections is valid, but this build cannot resolve
  either — running it anyway would silently execute a less-informed agent than the one
  published, so the run escalates with `unsupported_definition` instead.
- **Three LLM adapters, one contract.** `FakeAdapter` replays a script (tests),
  `MeridianDemoAdapter` derives each turn from the conversation so far (so a fresh stack
  demos without a key), and `AnthropicAdapter` makes real calls. The runtime cannot tell
  which one answered it — that is [ADR-005](../../docs/adr/005-llm-adapter-layer.md)'s
  claim, made testable. The demo adapter stands in for the *model*: it plans, and it
  reasons over the rules it retrieved, but it holds no business rules of its own — it
  cannot say what R-020 means, only what `query_rules` told it.
- **The vendored `app/dna/dna-schema.json` is byte-identical to the docs original.**
  The image build context is `src/backend` and cannot reach `docs/`, so the schema is
  vendored; `tests/test_dna_schema.py` fails if the two ever diverge.
- **The agent catalog is read-only, and that is the governance answer.** `GET /agents`
  and `GET /agents/{id}/versions` exist so the SPA can find something published to run.
  The write half — create agent, create draft version, publish, suspend — is absent
  because publishing is eval-gated (FR-F2) and there is no eval runner yet; a publish
  endpoint that could not enforce its gate would be a hole, not a head start. Both
  endpoints implement `openapi.yaml` as already written, so no contract changed to add
  them.
- **`total_cost_usd` is an exact decimal string on the wire, not a JSON number.** That is
  what the implementation always did; `openapi.yaml` said `number` and was corrected to
  match in Phase 3.3 (golden rule 5). Rounding an audit figure through a float is not
  acceptable, so the SPA formats the string and never parses it.
- **CORS is explicit, not a wildcard.** The SPA is a separate origin (ADR-007), so the
  browser preflights every call — `X-Forge-Role` is a non-simple header. `CORS_ORIGINS`
  defaults to the documented dev ports and is set in the compose file next to the
  service it is about. Credentials stay off: the role header is a demonstration of
  segregation of duties, not authentication, and there is no cookie to send.
- **One enforcement point, proved by reading the source.** A tool handler is invoked in
  exactly one place — `ToolGateway._execute`. `tests/test_governance.py` parses every
  module in `app/` and fails if a second call site ever appears, so "nothing bypasses the
  gateway" is a property of the call graph rather than a rule people remember. The runtime
  cannot even look a tool up: it holds a gateway, not a registry.
- **Every refusal has a code, an explanation, and a step in the trace.** The reason codes
  live once in `app/governance.py` and are used unchanged by the runtime, the audit log,
  the API, and the SPA. A stopped run carries exactly one `governance` step —
  `record_governance` is called from a single `except FailClosedError` in
  `AgentRuntime.start_run`, so a stop that produced no record, or a record with no stop, is
  not reachable. The explanation travels with the code: the sentence a compliance officer
  reads is the sentence the platform recorded when it acted.
- **Autonomy is dispatched from a table, not from a chain of `if`s.** `AUTONOMY_EFFECT`
  maps each level in the DNA schema to deny / park / execute, and a test asserts the table
  and the schema's enum are the same set. A level added to the contract without a decision
  here fails loudly instead of defaulting to "execute" — fail-closed applies to the
  platform's own gaps too.
- **`confidence` is a required field, and the floor is per agent.** R-091 makes low
  confidence a fail-closed condition, and a threshold cannot be enforced against a number
  the model was free to omit. `guardrails.min_decision_confidence` is declared per
  definition — the validator sits at 0.85, intake at 0.6 — and a decision below its floor
  is **overridden**: the run escalates whatever action was proposed, and the trace keeps
  the decision the agent wanted beside the block that stopped it.
- **The daily ceiling is summed from the ledger, not held in memory.**
  `model.max_cost_usd_per_day` is enforced across runs, per *agent*, from committed `runs`
  rows — so it survives a restart and cannot be reset by publishing a new version. It is
  checked before the first model call: a run that cannot afford to finish does not start.
- **Segregation of duties is a matrix the build refuses to start without.**
  `ROLE_PERMISSIONS` grants permissions to roles, endpoints ask for permissions, and
  `INCOMPATIBLE_DUTIES` states the pairs no role may hold at once. It is checked at import
  time and raises `SegregationOfDutiesError` — not an `assert`, which `-O` strips. A
  control only a test enforces is one that ships broken the day someone skips the test.
- **An API-level refusal is recorded too.** A role denied `run.start` gets a 403 *and* a
  `governance.permission_denied` event carrying the tenant and the version it targeted.
  The permission is deliberately checked after the lookup: a denial that cannot name what
  it protected is not much of an audit record.
- **A change to a definition is a new version, every time.** `guardrails
  .min_decision_confidence` became required in 4.2, which makes every 1.0.0 definition
  invalid — and the runtime refuses to run one (`unsupported_definition`) rather than
  supplying a default nobody declared, so the shipped agents became **1.1.0**. The
  validator moved to **1.2.0** when it gained knowledge retrieval (4.3), and the comms
  agent to **1.2.0** when it declared its own `guardrails.approval_sla_seconds` (4.4).
  Every superseded row stays in the database exactly as it was: versions are immutable,
  and a historical run still resolves the DNA that produced it (FR-A3).
- **`invoice-validator-restricted` exists to be refused.** It is the validator with
  `approve_invoice` granted as `forbidden` and nothing else changed. It carries no new
  capability; it is shipped so that "the platform stops things, and shows you why" is one
  click away in the catalog rather than a paragraph here.
- **Publishing in the seed bypasses the eval gate, once and visibly.** The seeded
  versions are published with `published_eval_run_id` left null, so a reviewer can tell a
  seeded version from one that earned its publish. The real gate (409 unless the suite
  passed, FR-F2) arrives with the eval runner in Phase 4.5.
- **Business rules are rows, not branches.** R-001 … R-092 live in the `rules` table with
  their statements, authority levels, and machine-evaluable conditions. The validator
  agent retrieves them through the tool gateway (`query_rules`) and reasons over what it
  retrieved; `app/rules/engine.py` is a general interpreter for the condition grammar and
  holds no threshold of its own. **Changing a rule is an `UPDATE`** — the gateway loads
  the rule set per request, so the next run decides differently with nothing to invalidate
  and nothing to rebuild. `tests/test_ap_agents.py` proves it by lowering a threshold
  mid-suite and watching the same invoice change outcome.
- **Rule retrieval is a tool in this phase, and the C4 model says it will not stay one.**
  [`workspace.dsl`](../../docs/02-architecture/c4/workspace.dsl) has the runtime
  retrieving governed rules from the knowledge component; here it retrieves them through
  the tool gateway (`query_rules`), because the knowledge layer does not exist yet and a
  tool call is at least fully validated, authorised, and traced. Phase 4.3 replaces the
  tool with authority-ranked retrieval over the same rule ids plus the policy documents,
  and the C4 model becomes true rather than aspirational. The payload `query_rules`
  returns is already shaped like what that retrieval will hand back.
- **The rule encoding cannot drift from the document that owns it.**
  `app/rules/catalog.py` is the machine-readable form of
  [`04-tacit-rules.md`](../../docs/01-discovery/04-tacit-rules.md), and
  `tests/test_rules.py` parses that markdown: a rule present in one and not the other, or
  a statement that has been paraphrased, fails the suite (golden rule 5). It is *seed
  data* — nothing at run time imports it.
- **MeridianERP is not in Forge's database.** The C4 model puts it outside the platform,
  so `app/erp/` simulates it in-process with its own storage and its own ledger of what
  Forge posted to it. A vendor master is the client's state, not platform state; swapping
  the module for an HTTP client is the only change a real integration would need.
- **Facts and rules are kept apart on purpose.** The ERP states what it can observe
  ("the price variance is 4.50%", "an invoice with this number already exists"); a rule
  says what that means and what to do about it. Every threshold — 2%, $50, $10,000,
  7 days, ±15% — is a value in a rule row, never a constant in `app/erp/facts.py`.
- **A `requires_approval` tool parks the run; it does not fail it.** The gateway validates
  the call, records it as `validated`, opens a pending approval with its deadline, and the
  run waits in `awaiting_approval` with nothing executed. Argument validation happens
  *before* parking: a human is never asked to approve a call that was malformed anyway.
- **Expiry cancels. It never approves.** `expires_at` is written once when the action
  parks — from the agent's own `guardrails.approval_sla_seconds`, or the platform default
  — and is compared against the *server's* clock on every read of the queue and every
  attempted decision. Nothing extends it: there is no extend, snooze, or auto-approve
  operation in `app/approvals/`, in the API, or in the OpenAPI document, and
  `tests/test_approvals.py` asserts that against the served contract rather than trusting
  this paragraph (FR-E3, golden rule 3).
- **An approval covers one action instance, structurally.** One approval row per
  `tool_invocations` row (a unique constraint), the resume replays *that row's* stored
  arguments, and the approve request body carries a note and no arguments. There is no
  shape of request that approves one action and runs another (FR-E2).
- **A released call goes back through the gateway.** Approving does not open a side door:
  the resume re-runs every check against the *current* published DNA and adds one thing —
  an `ApprovalRelease` naming the approval, the approver, and the time. So an approval
  granted while a grant was being revoked is refused at the gateway, and MeridianERP
  records the write under the **person who released it** rather than under `forge-runtime`.
- **A paused run resumes from its own event log.** There is no checkpoint blob: the
  conversation, the budget, and the step count are all rebuilt from the run's rows and
  events ([ADR-010](../../docs/adr/010-resume-by-replay.md)), by the same functions that
  built them live. An approval buys a person's yes, not a second helping of the ceilings
  the definition declares.
- **Autonomy promotion is a report, not a mechanism.** `GET /approvals/report` names
  action categories whose approvals are being waved through — Rosa's fatigue risk, with
  evidence — and applies none of them. Raising an autonomy level means publishing a new
  DNA version through its eval gate (FR-E5, golden rule 1).
- **A DNA grant's `config` is enforced, not decorative.** The validator is granted
  `approve_invoice` with `{"max_amount_usd": 10000}`; the gateway validates that object
  against the tool's own config schema, and the tool refuses anything above the ceiling.
  A definition carrying config the tool cannot honour is refused outright rather than run
  with the configuration quietly ignored.
