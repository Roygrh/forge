"""Forge API — application entry point.

Phase 3.2 completed the walking skeleton: the app starts, talks to PostgreSQL, and
serves the run surface — start a run, read its status, read its trace. Phase 3.3 added
the read-only agent catalog the SPA lists, and CORS so that SPA can reach the API.
Phase 4.3 adds the read-only knowledge surface: collections, citable chunks, and the
remediation queue. Phase 4.4 adds the human in the loop — the approval queue that
releases a parked action, cancels it, or lets it expire, plus the autonomy-promotion
report. The rest of the governance surface contracted in
``docs/02-architecture/api/openapi.yaml`` (agent authoring, evals) arrives in later
phases.
"""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import __version__
from app.api import (
    agents_router,
    approvals_router,
    install_error_handlers,
    knowledge_router,
    runs_router,
)
from app.config import get_settings
from app.db import check_database, get_async_engine

# psycopg's async driver refuses Windows' default ProactorEventLoop. The deployment
# target is Linux (ADR-009), where this is a no-op; it exists so the **test suite** runs
# natively on a Windows development machine, where the client creates its own loop and
# honours this policy. Process-wide runtime configuration belongs at the entry point,
# which is why it is here and not in app.db.
#
# It does NOT cover `uvicorn app.main:app` on Windows: uvicorn installs its own event
# loop policy after importing this module, and psycopg then fails to connect. Serve the
# API on Windows through `docker compose up` (the documented path, and Linux inside the
# container) rather than natively.
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

install_error_handlers(app)

# The SPA runs on its own origin, so every one of its calls is cross-origin and every
# one of them carries X-Forge-Role — a non-simple header, which means the browser
# preflights it. Credentials stay off: the role header is a demonstration of
# segregation of duties (NFR-5), not authentication, and there is no cookie to send.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Forge-Role"],
)

app.include_router(agents_router, prefix=settings.api_prefix)
app.include_router(runs_router, prefix=settings.api_prefix)
app.include_router(approvals_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)


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
