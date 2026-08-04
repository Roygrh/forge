# Forge backend

Python 3.12 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 + pgvector ([ADR-002](../../docs/adr/002-backend-python-fastapi.md), [ADR-004](../../docs/adr/004-postgres-single-store.md))

**Phase 3.2–3.3 scope:** the walking skeleton end to end — the agent runtime loop, the
LLM gateway, the tool gateway, the run endpoints, and the read-only agent catalog the
SPA lists. No business rules, no knowledge retrieval, no HITL approvals, and no eval
runner yet; those are Phase 4.

## Quickstart (three commands)

From the repository root:

```bash
cd deploy && docker compose up -d --build        # 1. Postgres + API + SPA
docker compose exec api alembic upgrade head     # 2. schema
docker compose exec api python -m scripts.seed   # 3. tenant + skeleton agent
```

Then open <http://localhost:5173> and press **Run** ([`src/frontend`](../frontend/README.md)) —
or do the same from a terminal:

```bash
curl http://localhost:8000/api/v1/health         # {"status":"ok","db":"ok"}

AGENT=$(docker compose exec -T db psql -U forge -d forge -tA \
  -c "select id from agents where slug='skeleton-echo'")

RUN=$(curl -s -X POST http://localhost:8000/api/v1/runs \
  -H 'Content-Type: application/json' -H 'X-Forge-Role: configurator' \
  -d "{\"agent_id\":\"$AGENT\",\"version\":\"1.0.0\",\"input\":{\"topic\":\"governance\"}}" \
  | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')

curl -s "http://localhost:8000/api/v1/runs/$RUN/trace" -H 'X-Forge-Role: configurator'
```

The run completes with no API key and no network: the seeded agent's DNA names the
deterministic in-process provider (ADR-005). Point its `model` block at
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
| `app/models/` | The thirteen tables of [`data-model.md`](../../docs/02-architecture/data-model.md) as plain mappings |
| `app/dna/` | The DNA contract: vendored JSON Schema (write-time) + typed Pydantic view (read-time) |
| `app/llm/` | The LLM gateway ([ADR-005](../../docs/adr/005-llm-adapter-layer.md)): one `complete()` contract, budget enforcement, three adapters |
| `app/tools/` | The tool registry and gateway — the only path from an agent to a tool (FR-C1) |
| `app/runtime/` | The loop ([ADR-003](../../docs/adr/003-custom-agent-runtime.md)), structured-output validation ([ADR-006](../../docs/adr/006-structured-outputs.md)), and the trace writer/reader |
| `app/api/` | Agent-catalog and run endpoints, the error shape, and the gateway dependencies |
| `alembic/` | Migration environment; the URL comes from settings, never from `alembic.ini` |
| `scripts/seed.py` | Idempotent tenant + published skeleton agent seed |
| `tests/` | Health, config, models, append-only, DNA contract, both gateways, output validation, the agent catalog, and the runtime end to end |

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
  `SkeletonDemoAdapter` derives the skeleton's two turns from the request (so a fresh
  stack demos without a key), and `AnthropicAdapter` makes real calls. The runtime
  cannot tell which one answered it — that is [ADR-005](../../docs/adr/005-llm-adapter-layer.md)'s
  claim, made testable.
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
- **Publishing in the seed bypasses the eval gate, once and visibly.** The seeded
  version is published with `published_eval_run_id` left null, so a reviewer can tell a
  seeded version from one that earned its publish. The real gate (409 unless the suite
  passed, FR-F2) arrives with the eval runner in Phase 4.4.
