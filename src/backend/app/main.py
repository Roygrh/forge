"""Forge API — application entry point.

Phase 3.1 is the walking skeleton's foundation: the app starts, talks to PostgreSQL,
and exposes a health probe. The governance surface contracted in
``docs/02-architecture/api/openapi.yaml`` (agents, runs, approvals, knowledge, evals)
arrives in later phases, as does the agent runtime.
"""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app import __version__
from app.config import get_settings
from app.db import check_database, get_async_engine

# psycopg's async driver refuses Windows' default ProactorEventLoop. The deployment
# target is Linux (ADR-009), where this is a no-op; it exists so the API and the test
# suite also run natively on a Windows development machine. Process-wide runtime
# configuration belongs at the entry point, which is why it is here and not in app.db.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()


class HealthResponse(BaseModel):
    """Result of the liveness probe."""

    status: Literal["ok", "degraded"] = Field(
        description="ok when every dependency answered; degraded otherwise"
    )
    db: Literal["ok", "down"] = Field(description="Result of a real SELECT 1 round-trip")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release the connection pool on shutdown."""
    yield
    await get_async_engine().dispose()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url=f"{settings.api_prefix}/docs",
)


@app.get(
    f"{settings.api_prefix}/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Liveness probe with a real database round-trip",
)
async def health() -> HealthResponse:
    """Report service and database health.

    Always answers 200: the probe's job is to report the state of its dependencies,
    so a database outage reads as ``degraded``/``down`` rather than as a failure to
    answer. Callers gate on the fields, not on the status code.
    """
    db_ok = await check_database()
    return HealthResponse(status="ok" if db_ok else "degraded", db="ok" if db_ok else "down")
