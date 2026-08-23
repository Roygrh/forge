"""Forge API — application entry point.

Phase 3.2 completed the walking skeleton: the app starts, talks to PostgreSQL, and
serves the run surface — start a run, read its status, read its trace. Phase 3.3 added
the read-only agent catalog the SPA lists, and CORS so that SPA can reach the API.
Phase 4.3 adds the read-only knowledge surface: collections, citable chunks, and the
remediation queue. Phase 4.4 adds the human in the loop — the approval queue that
releases a parked action, cancels it, or lets it expire, plus the autonomy-promotion
report. Phase 4.5 adds the evaluation suite as the publish gate: draft authoring, the
eval endpoints, and a ``publish`` that answers 409 until the version's declared suite
has passed (FR-F2). Phase 4.6 adds observability and containment: per-agent metrics
derived from the event log (FR-G3), and the circuit breaker with its admin-only resume
(FR-G4). Phase 5.1 splits the single health route into a dependency-free **liveness**
probe and a **readiness** probe that gates on the database, the migration head, and the
seeded catalog (:mod:`app.api.health`) — the signal ``docker compose up`` waits on.
"""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import (
    agents_router,
    approvals_router,
    evals_router,
    health_router,
    install_error_handlers,
    knowledge_router,
    metrics_router,
    runs_router,
)
from app.config import get_settings
from app.db import get_async_engine

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

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(agents_router, prefix=settings.api_prefix)
app.include_router(runs_router, prefix=settings.api_prefix)
app.include_router(approvals_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(evals_router, prefix=settings.api_prefix)
app.include_router(metrics_router, prefix=settings.api_prefix)
