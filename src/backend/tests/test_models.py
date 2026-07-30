"""Model round-trip and the tenant_id guarantee (NFR-4)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Agent, Tenant


def _tenant(session: Session, slug: str = "meridian-supply-co") -> Tenant:
    tenant = Tenant(slug=slug, name="Meridian Supply Co.")
    session.add(tenant)
    session.flush()
    return tenant


def test_tenant_and_agent_round_trip(session: Session) -> None:
    tenant = _tenant(session)
    session.add(
        Agent(
            tenant_id=tenant.tenant_id,
            slug="ap-invoice-triage",
            name="AP Invoice Triage",
            type="workflow",
            description="Triages incoming vendor invoices.",
        )
    )
    session.commit()

    agent = session.scalar(select(Agent).where(Agent.slug == "ap-invoice-triage"))

    assert agent is not None
    assert agent.tenant_id == tenant.tenant_id
    assert agent.type == "workflow"
    # Server-side defaults were applied, not silently skipped.
    assert isinstance(agent.id, uuid.UUID)
    assert agent.created_at is not None


def test_agent_requires_a_tenant(session: Session) -> None:
    """tenant_id is NOT NULL: no business row can exist outside a tenant."""
    session.add(Agent(tenant_id=None, slug="orphan", name="Orphan", type="workflow"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_agent_tenant_must_exist(session: Session) -> None:
    """tenant_id is a real foreign key, not a loose label."""
    session.add(Agent(tenant_id=uuid.uuid4(), slug="ghost-tenant", name="Ghost", type="workflow"))

    with pytest.raises(IntegrityError):
        session.flush()
