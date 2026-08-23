"""Liveness and readiness — two different questions, deliberately split (Phase 5.1).

A hosting platform asks two things, and conflating them is how a healthy process gets
restarted for a problem it did not cause:

* **Liveness** (``GET /health``) — *is this process alive and able to answer?* It touches
  nothing: no database, no disk, no clock. A dependency outage must never read as "kill
  this container", because restarting the API does not fix PostgreSQL.
* **Readiness** (``GET /ready``) — *should traffic be sent here yet?* It answers only
  once the database is reachable, the schema is at the migration head this build expects,
  and the demonstration data the SPA's first screen needs is present. Anything short of
  that is ``503`` with a named check, which is what makes a cold start observable rather
  than a guess (``docker compose up`` polls this before declaring ``api`` healthy).

Readiness fails closed, like everything else here (golden rule 3): a check that cannot
be *proved* to pass — the migration head cannot be read, the tables are not there yet —
reports its own state and holds traffic back, rather than assuming the best.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.config import get_settings
from app.db import get_async_engine

router = APIRouter(tags=["Health"])

#: ``src/backend/alembic/`` — beside the package, both in the image (``/app/alembic``)
#: and in an editable install. The migration scripts travel with the artifact on purpose
#: (see the Dockerfile), which is what lets a running API state its own schema version.
#: Pointed at directly rather than via ``alembic.ini`` so the answer does not depend on
#: the process's working directory.
ALEMBIC_SCRIPTS = Path(__file__).resolve().parents[2] / "alembic"


class HealthResponse(BaseModel):
    """Result of the liveness probe. Always 200 while the process can answer at all."""

    status: Literal["ok"] = Field(description="Constant `ok`; reaching this route is the check")
    service: str = Field(description="Configured application name")
    version: str = Field(description="Backend build version")


class ReadinessChecks(BaseModel):
    """The individual verdicts behind :class:`ReadinessResponse`."""

    database: Literal["ok", "down"] = Field(description="A real `SELECT 1` round-trip")
    migrations: Literal["ok", "pending", "unknown"] = Field(
        description=(
            "`ok` when the database is stamped at this build's Alembic head; `pending` "
            "when it is behind or unstamped; `unknown` when the head could not be read"
        )
    )
    seed: Literal["ok", "missing", "unknown"] = Field(
        description=(
            "`ok` when at least one published agent version exists, so the catalog has "
            "something to show and run"
        )
    )


class ReadinessResponse(BaseModel):
    """Result of the readiness probe. 200 when ready, 503 when not."""

    status: Literal["ready", "not_ready"] = Field(
        description="`ready` only when every check below is `ok`"
    )
    checks: ReadinessChecks = Field(description="Per-dependency verdicts")
    detail: str = Field(description="One sentence a human can act on")
    schema_revision: str | None = Field(
        default=None, description="Alembic revision the database is stamped at, when readable"
    )
    expected_revision: str | None = Field(
        default=None, description="Alembic head this build expects, when readable"
    )


@lru_cache
def expected_head() -> str | None:
    """Return the Alembic head revision this build expects, or ``None`` if unreadable.

    Cached: the answer is a property of the image, and re-reading the script directory
    on every probe would make readiness the most expensive route in the service.
    """
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_SCRIPTS))
    try:
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception:
        # Any failure here means the head cannot be *proved*; readiness reports
        # `unknown` and holds traffic back rather than assuming the schema is current.
        return None
    # A single linear history is the invariant; branching heads would mean the migration
    # graph itself is ambiguous, which readiness must not paper over.
    return heads[0] if len(heads) == 1 else None


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe — the process is up",
)
async def health() -> HealthResponse:
    """Report that this process is alive.

    Deliberately dependency-free. If you want to know whether the platform can serve
    traffic, ask ``/ready`` — that is the question with an answer that can change.
    """
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe — database reachable, schema migrated, catalog seeded",
    responses={503: {"model": ReadinessResponse, "description": "Not ready to serve traffic"}},
)
async def ready(response: Response) -> ReadinessResponse:
    """Report whether this instance should receive traffic.

    Answers 200 only when all three checks pass; otherwise 503 with the check that
    failed named, so "it is still starting" and "it is broken" are distinguishable from
    the outside.
    """
    database: Literal["ok", "down"] = "down"
    migrations: Literal["ok", "pending", "unknown"] = "unknown"
    seed: Literal["ok", "missing", "unknown"] = "unknown"
    stamped: str | None = None
    head = expected_head()

    try:
        async with get_async_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
            database = "ok"

            # `to_regclass` answers NULL for a missing table instead of raising, so a
            # database that has never been migrated is a normal answer here rather than
            # an error that would poison the transaction.
            has_version_table = await connection.scalar(
                text("SELECT to_regclass('public.alembic_version')")
            )
            if has_version_table is None:
                migrations = "pending"
            else:
                stamped = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                # `unknown` when this build cannot name its own head: the comparison
                # could not be made, so the schema is not *proved* current.
                migrations = "unknown" if head is None else "ok" if stamped == head else "pending"

            if migrations == "ok":
                has_versions_table = await connection.scalar(
                    text("SELECT to_regclass('public.agent_versions')")
                )
                if has_versions_table is None:
                    seed = "missing"
                else:
                    published = await connection.scalar(
                        text("SELECT count(*) FROM agent_versions WHERE status = 'published'")
                    )
                    seed = "ok" if published else "missing"
    except SQLAlchemyError:
        # Reported, never raised: a probe that 500s tells a platform less than one that
        # says which dependency is down.
        database = "down"

    checks = ReadinessChecks(database=database, migrations=migrations, seed=seed)
    is_ready = database == "ok" and migrations == "ok" and seed == "ok"
    if not is_ready:
        response.status_code = 503

    return ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        checks=checks,
        detail=_detail(checks),
        schema_revision=stamped,
        expected_revision=head,
    )


def _detail(checks: ReadinessChecks) -> str:
    """Turn the check verdicts into the one sentence an operator needs."""
    if checks.database == "down":
        return "The database is not reachable. Check DATABASE_URL and that PostgreSQL is up."
    if checks.migrations == "pending":
        return (
            "The schema is not at this build's migration head. Run `alembic upgrade head` "
            "(the compose stack's `migrate` service does this)."
        )
    if checks.migrations == "unknown":
        return (
            "The expected migration head could not be read from the image, so the schema "
            "cannot be verified. Holding traffic back rather than assuming it is current."
        )
    if checks.seed != "ok":
        return (
            "No published agent version exists, so the catalog would be empty. Run "
            "`python -m scripts.seed` (the compose stack's `migrate` service does this)."
        )
    return "Database reachable, schema at head, and the agent catalog is populated."
