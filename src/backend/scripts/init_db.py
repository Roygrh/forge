"""Bring an empty database to a ready state: wait, migrate, seed.

This is the whole of "step 2" in a cold start. The compose stack (ADR-009) runs it as a
one-shot ``migrate`` service that must exit 0 before the API is allowed to start, which
is what makes ``docker compose up`` on a fresh volume a single command with no manual
follow-up. It is equally usable by hand::

    python -m scripts.init_db

**Idempotent, deliberately.** Every step is safe to re-run: ``alembic upgrade head`` is
a no-op on a current schema, and :mod:`scripts.seed` leaves existing rows alone (an
operator's edited rule is hers, not the seed's). Re-running is the normal case — a
restarted container, a second ``docker compose up``, CI — so it must never be
destructive and never duplicate.

**It does not race the database.** Compose gates this service on the ``db``
healthcheck, but a healthcheck is a statement about the server, not about this
process's ability to connect through it, so the wait below is a real ``SELECT 1``
retried until it succeeds or the budget runs out. Belt and braces is the correct
posture for the one command an evaluator runs once.

**It migrates and seeds; it never guesses.** If the migration fails, the seed does not
run and the process exits non-zero, so the API never starts against a half-built
schema — fail closed (golden rule 3) applied to deployment.
"""

import argparse
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import create_sync_engine
from scripts import seed

#: Location of the migration scripts, resolved from this file so the process's working
#: directory is irrelevant (``/app`` in the image, ``src/backend`` locally).
ALEMBIC_SCRIPTS = Path(__file__).resolve().parents[1] / "alembic"

DEFAULT_TIMEOUT_SECONDS = 90.0
RETRY_INTERVAL_SECONDS = 1.0


def wait_for_database(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    """Block until a real ``SELECT 1`` succeeds, or raise once ``timeout`` elapses.

    Connection failures are expected and quiet for the first few seconds — PostgreSQL
    accepting TCP and PostgreSQL being ready to answer are not the same instant. Any
    failure still standing at the deadline is re-raised with its original cause, because
    "could not connect" and "authentication failed" want different fixes and a generic
    timeout message would hide which one happened.
    """
    url = get_settings().database_url
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        engine = create_sync_engine()
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print(f"database reachable after {attempt} attempt(s)")
            return
        except SQLAlchemyError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"database at {_safe(url)} was not reachable within {timeout:.0f}s "
                    f"({attempt} attempts): {exc}"
                ) from exc
            if attempt == 1:
                print(f"waiting for the database at {_safe(url)} ...")
            time.sleep(RETRY_INTERVAL_SECONDS)
        finally:
            engine.dispose()


def migrate() -> None:
    """Run ``alembic upgrade head`` in-process against the configured database."""
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_SCRIPTS))
    # env.py reads the URL from app settings, never from alembic.ini, so migrations and
    # the API cannot drift onto different databases.
    command.upgrade(config, "head")


def main(argv: list[str] | None = None) -> int:
    """Wait for the database, migrate it, seed it, and say so."""
    parser = argparse.ArgumentParser(description="Migrate and seed the Forge database.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to keep retrying the first connection (default: %(default)s).",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Migrate only. The API's readiness probe stays 503 until something is seeded.",
    )
    args = parser.parse_args(argv)

    wait_for_database(args.timeout)

    print("applying migrations (alembic upgrade head) ...")
    migrate()
    print("schema is at head")

    if args.skip_seed:
        print("seed skipped (--skip-seed)")
        return 0

    print("seeding ...")
    return seed.main([])


def _safe(url: str) -> str:
    """Render a database URL without its password, for logs."""
    return make_url(url).render_as_string(hide_password=True)


if __name__ == "__main__":
    sys.exit(main())
