"""Database engines and sessions.

Two engines, one URL. The API uses an **async** engine because agent runs are
I/O-bound and FastAPI handlers are async-first (ADR-002); migrations, the seed
script, and tests use a **synchronous** engine because they are linear scripts.
Both share the same ``postgresql+psycopg://`` URL — psycopg 3 provides a sync and
an async driver behind one SQLAlchemy dialect, so there is nothing to keep in sync.

This module owns connectivity only: no models, no queries. The readiness probe
(:mod:`app.api.health`) opens its own connection, because the questions it asks —
``SELECT 1``, the stamped migration revision, whether anything is published — have to be
answered against one and the same connection to mean anything together.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_async_engine() -> AsyncEngine:
    """Return the process-wide async engine used by API handlers."""
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async session factory."""
    return async_sessionmaker(bind=get_async_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request."""
    async with get_async_session_factory()() as session:
        yield session


#: One session per request, for handlers that need the database.
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def create_sync_engine(url: str | None = None) -> Engine:
    """Create a synchronous engine for migrations, scripts, and tests."""
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sync_session_factory() -> sessionmaker[Session]:
    """Process-wide synchronous session factory, for synchronous call sites that live
    inside the running API — today, tool handlers.

    Tool handlers are synchronous by contract (:mod:`app.tools.contract`) and the
    knowledge-retrieval tool needs the database. Giving it a session from a cached
    engine (rather than a throwaway engine per call, as :func:`sync_session` does)
    keeps a retrieval from paying a connection-pool construction on every invocation.
    """
    return sessionmaker(
        bind=create_engine(get_settings().database_url, pool_pre_ping=True),
        expire_on_commit=False,
    )


@contextmanager
def sync_session(url: str | None = None) -> Iterator[Session]:
    """Yield a synchronous session, disposing its engine afterwards."""
    engine = create_sync_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            yield session
    finally:
        engine.dispose()
