"""The append-only guarantee (ADR-008).

"An audit log that application code can UPDATE is not an audit log." These tests assert
that the guarantee is enforced by the database — both layers the initial migration
installs — rather than by convention in application code.
"""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.models import Event, Tenant

APP_ROLE = "forge_app"


def _one_committed_event(session: Session) -> int:
    """Insert a tenant and one event, commit, and return the event id."""
    tenant = Tenant(slug="meridian-supply-co", name="Meridian Supply Co.")
    session.add(tenant)
    session.flush()

    event = Event(
        tenant_id=tenant.tenant_id,
        type="run.started",
        actor="system",
        payload={"note": "immutability probe"},
    )
    session.add(event)
    session.commit()
    return event.event_id


def test_update_on_events_is_rejected(session: Session) -> None:
    event_id = _one_committed_event(session)

    with pytest.raises(DatabaseError) as raised:
        session.execute(
            text("UPDATE events SET actor = 'tampered' WHERE event_id = :id"), {"id": event_id}
        )
    assert "append-only" in str(raised.value)

    session.rollback()
    stored = session.scalar(select(Event).where(Event.event_id == event_id))
    assert stored is not None
    assert stored.actor == "system"


def test_delete_on_events_is_rejected(session: Session) -> None:
    event_id = _one_committed_event(session)

    with pytest.raises(DatabaseError) as raised:
        session.execute(text("DELETE FROM events WHERE event_id = :id"), {"id": event_id})
    assert "append-only" in str(raised.value)

    session.rollback()
    assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_truncate_on_events_is_rejected(session: Session) -> None:
    _one_committed_event(session)

    with pytest.raises(DatabaseError) as raised:
        session.execute(text("TRUNCATE TABLE events"))
    assert "append-only" in str(raised.value)

    session.rollback()
    assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_application_role_holds_insert_and_select_only(session: Session) -> None:
    """The grant layer of ADR-008: the app role cannot even be asked to mutate history."""
    privileges = {
        privilege: session.scalar(select(func.has_table_privilege(APP_ROLE, "events", privilege)))
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
    }

    assert privileges == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
    }
