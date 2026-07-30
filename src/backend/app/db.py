"""Database engines and sessions.

Two engines, one URL. The API uses an **async** engine because agent runs are
I/O-bound and FastAPI handlers are async-first (ADR-002); migrations, the seed
script, and tests use a **synchronous** engine because they are linear scripts.
Both share the same ``postgresql+psycopg://`` URL — psycopg 3 provides a sync and
an async driver behind one SQLAlchemy dialect, so there is nothing to keep in sync.

This module owns connectivity only: no models, no queries beyond the liveness probe.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


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


async def check_database() -> bool:
    """Round-trip a real ``SELECT 1``; return ``False`` on any database failure.

    The health probe reports rather than raises, so a database outage surfaces as
    ``db: down`` instead of an opaque 500.
    """
    try:
        async with get_async_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("database health check failed", exc_info=True)
        return False
    return True


def create_sync_engine(url: str | None = None) -> Engine:
    """Create a synchronous engine for migrations, scripts, and tests."""
    return create_engine(url or get_settings().database_url, pool_pre_ping=True)


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
