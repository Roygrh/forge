"""Alembic environment.

The database URL is read from the application settings (``DATABASE_URL``), never from
``alembic.ini``, so migrations and the API cannot drift apart or hold separate
credentials. Migrations use a synchronous engine — they are linear scripts, and the
psycopg dialect serves both modes from the same URL (see ``app/db.py``).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from app.config import get_settings
from app.db import create_sync_engine

# Importing the package registers every table on Base.metadata.
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (``alembic upgrade --sql``)."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations on an open connection."""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the configured database."""
    engine = create_sync_engine()
    try:
        with engine.connect() as connection:
            do_run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
