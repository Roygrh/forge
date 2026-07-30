"""The health endpoint — the only route Phase 3.1 exposes."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

HEALTH_URL = "/api/v1/health"


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    """App client bound to the test database (see conftest for how it is provisioned).

    Module-scoped so every request shares one event loop, which the async connection
    pool requires.
    """
    from app.main import app

    with TestClient(app) as client:
        yield client


def test_health_reports_ok_with_a_reachable_database(client: TestClient) -> None:
    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    # `db: ok` is only reachable through a real SELECT 1 round-trip, so this asserts
    # the app's connection to PostgreSQL, not just that the route exists.
    assert response.json() == {"status": "ok", "db": "ok"}
