"""Test fixtures.

Tests run against a **real PostgreSQL**: what is under test here is largely the
schema itself — append-only grants and triggers, ``jsonb``, ``pgvector``, identity
columns — none of which an SQLite stand-in would prove. The suite therefore creates a
throwaway ``forge_test`` database in the same cluster as the compose database,
migrates it with Alembic, and drops it afterwards. Nothing touches the dev database.

Point the suite at a different cluster by setting ``DATABASE_URL``; the database name
in that URL is replaced with ``forge_test``.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "forge_test"
DEFAULT_URL = "postgresql+psycopg://forge:forge@localhost:5432/forge"

_base_url = make_url(os.environ.get("DATABASE_URL") or DEFAULT_URL)
TEST_DATABASE_URL: URL = _base_url.set(database=TEST_DB_NAME)
# `postgres` is the maintenance database used to CREATE/DROP the test database.
ADMIN_DATABASE_URL: URL = _base_url.set(database="postgres")

# Set before any app module imports its settings, so the application under test and
# the migrations both target the throwaway database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def _run_admin_statements(*statements: str) -> None:
    """Run statements outside a transaction (CREATE/DROP DATABASE cannot be in one)."""
    engine = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            for statement in statements:
                connection.execute(text(statement))
    finally:
        engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Create the test database, run every migration, drop it at the end."""
    _run_admin_statements(
        f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)',
        f'CREATE DATABASE "{TEST_DB_NAME}"',
    )
    # Exercising the real migration is deliberate: the append-only guarantee lives in
    # the migration, so a test suite that built tables with create_all would skip it.
    command.upgrade(_alembic_config(), "head")
    yield
    _run_admin_statements(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')


@pytest.fixture(scope="session")
def engine(migrated_database: None) -> Iterator[Engine]:
    """Synchronous engine bound to the migrated test database."""
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """One test, one transaction, always rolled back — tests never leak rows.

    ``join_transaction_mode="create_savepoint"`` lets a test call ``commit()`` (needed
    to make a row visible to a later statement) without ending the outer transaction.
    """
    connection = engine.connect()
    transaction = connection.begin()
    try:
        with Session(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
    finally:
        transaction.rollback()
        connection.close()
