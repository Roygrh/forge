"""Seed the demonstration tenant.

Idempotent: running it twice leaves exactly one Meridian Supply Co. tenant and one
``tenant.created`` event. Re-running is the normal case (fresh clone, restarted
volume, CI), so it must never be destructive and never duplicate.

Usage (from src/backend, with DATABASE_URL set or the compose default reachable):

    python -m scripts.seed
"""

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import sync_session
from app.models import Event, Tenant

MERIDIAN_SLUG = "meridian-supply-co"
MERIDIAN_NAME = "Meridian Supply Co."


def seed_tenant(session: Session) -> tuple[Tenant, bool]:
    """Ensure the Meridian tenant exists; return it and whether it was created."""
    existing = session.scalar(select(Tenant).where(Tenant.slug == MERIDIAN_SLUG))
    if existing is not None:
        return existing, False

    tenant = Tenant(slug=MERIDIAN_SLUG, name=MERIDIAN_NAME)
    session.add(tenant)
    session.flush()  # assigns tenant_id from the database

    # ADR-008: a state change and its event are written in the same transaction.
    # Even seeding is not exempt — that is the whole point of the rule.
    session.add(
        Event(
            tenant_id=tenant.tenant_id,
            type="tenant.created",
            actor="seed-script",
            payload={"slug": tenant.slug, "name": tenant.name, "source": "scripts/seed.py"},
        )
    )
    return tenant, True


def main() -> int:
    """Seed and report what happened."""
    with sync_session() as session:
        tenant, created = seed_tenant(session)
        session.commit()
        action = "created" if created else "already present"
        print(f"tenant {tenant.slug} {action} (tenant_id={tenant.tenant_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
