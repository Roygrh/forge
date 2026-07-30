# Forge backend

Python 3.12 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 + pgvector ([ADR-002](../../docs/adr/002-backend-python-fastapi.md), [ADR-004](../../docs/adr/004-postgres-single-store.md))

**Phase 3.1 scope:** project skeleton, schema, and a health check. No agent runtime, no
LLM calls, no endpoints beyond `GET /api/v1/health`.

## Quickstart (three commands)

From the repository root:

```bash
cd deploy && docker compose up -d --build        # 1. Postgres + API
docker compose exec api alembic upgrade head     # 2. schema
docker compose exec api python -m scripts.seed   # 3. Meridian tenant
```

Then:

```bash
curl http://localhost:8000/api/v1/health         # {"status":"ok","db":"ok"}
```

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
| `app/config.py` | Settings from the environment; `DATABASE_URL` is the only required value |
| `app/db.py` | Async engine for the API, sync engine for migrations/scripts/tests |
| `app/main.py` | FastAPI app; `GET /api/v1/health` with a real `SELECT 1` |
| `app/models/` | The thirteen tables of [`data-model.md`](../../docs/02-architecture/data-model.md) as plain mappings |
| `alembic/` | Migration environment; the URL comes from settings, never from `alembic.ini` |
| `scripts/seed.py` | Idempotent Meridian Supply Co. tenant seed |
| `tests/` | Health, model round-trip, and the ADR-008 append-only guarantee |

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
