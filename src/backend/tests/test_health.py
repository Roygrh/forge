"""Liveness and readiness — two probes answering two different questions (Phase 5.1).

Liveness is about the process; readiness is about whether this instance should be sent
traffic. Conflating them is how a healthy container gets restarted for a database
outage it did not cause, so the split is asserted here rather than described.
"""

from collections.abc import Iterator, Sequence
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.models import AgentVersion, Tenant
from scripts.seed import seed_tenant
from tests.skeleton import publish_skeleton

HEALTH_URL = "/api/v1/health"
READY_URL = "/api/v1/ready"

#: Its own agent, so this module never depends on another test file having run first —
#: readiness asks "is anything published?", and the answer has to be arranged here.
PROBE_SLUG = "readiness-probe"


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    """App client bound to the test database (see conftest for how it is provisioned).

    Module-scoped so every request shares one event loop, which the async connection
    pool requires.
    """
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def published(committed_session: Session) -> AgentVersion:
    """One published agent version, so the seed check has something to find."""
    tenant: Tenant
    tenant, _ = seed_tenant(committed_session)
    committed_session.commit()
    return publish_skeleton(committed_session, tenant, slug=PROBE_SLUG)


def test_liveness_answers_without_reporting_on_any_dependency(client: TestClient) -> None:
    from app import __version__

    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["service"]
    # The point of the split: liveness reports on the *process*, so it carries no
    # dependency verdict at all. A database outage must never read as "restart me".
    assert "db" not in body
    assert "checks" not in body


def test_readiness_is_ready_against_a_migrated_seeded_database(
    client: TestClient, published: AgentVersion
) -> None:
    response = client.get(READY_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # `database: ok` is only reachable through a real SELECT 1 round-trip, so this
    # asserts the app's connection to PostgreSQL, not merely that the route exists.
    assert body["checks"] == {"database": "ok", "migrations": "ok", "seed": "ok"}
    # The schema check is a comparison, not a shrug: both sides are named in the body,
    # so a mismatch can be diagnosed from the response alone.
    assert body["expected_revision"]
    assert body["schema_revision"] == body["expected_revision"]


def test_readiness_holds_traffic_back_when_nothing_is_published(
    client: TestClient, committed_session: Session, published: AgentVersion
) -> None:
    """A migrated but unseeded database is not ready: the catalog would be empty.

    Fail closed (golden rule 3) applied to deployment — "the process started" is not the
    same claim as "this instance can serve", and only the second should attract traffic.
    """
    ids = list(
        committed_session.scalars(select(AgentVersion.id).where(AgentVersion.status == "published"))
    )
    assert ids
    _set_status(committed_session, ids, "draft")
    try:
        response = client.get(READY_URL)

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["seed"] == "missing"
        # The other two still passed and say so — a probe collapsed to one boolean could
        # not tell "still seeding" from "the database is gone".
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["migrations"] == "ok"
        assert "scripts.seed" in body["detail"]
    finally:
        # Exactly the rows that were published, and no others: other modules rely on
        # their own drafts staying drafts.
        _set_status(committed_session, ids, "published")


def test_readiness_reports_a_pending_schema_rather_than_guessing(
    client: TestClient, committed_session: Session
) -> None:
    """An unstamped database reads as `pending` — not ready, and not a 500 either."""
    stamped = committed_session.scalar(text("SELECT version_num FROM alembic_version"))
    assert stamped
    committed_session.execute(text("DELETE FROM alembic_version"))
    committed_session.commit()
    try:
        response = client.get(READY_URL)

        assert response.status_code == 503
        body = response.json()
        assert body["checks"]["migrations"] == "pending"
        assert body["schema_revision"] is None
        # Not reported as `ok` on the strength of the tables happening to be there.
        assert body["checks"]["seed"] == "unknown"
        assert "alembic upgrade head" in body["detail"]
    finally:
        committed_session.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": stamped}
        )
        committed_session.commit()


def test_the_expected_head_is_readable_from_the_shipped_migration_scripts() -> None:
    """`unknown` must be the unreachable branch in a correctly built artifact.

    The migration scripts travel with the image so a running API can state its own schema
    version. If that ever stopped being true, readiness would fail closed forever — and
    this is the test that says why.
    """
    from app.api.health import expected_head

    assert expected_head() is not None


def _set_status(session: Session, ids: Sequence[UUID], status: str) -> None:
    session.execute(update(AgentVersion).where(AgentVersion.id.in_(ids)).values(status=status))
    session.commit()
