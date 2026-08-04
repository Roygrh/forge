"""The read-only agent catalog, through the real HTTP surface.

These two endpoints exist so the SPA can answer "which agents are there, and which of
their versions may I run?" without hard-coding a seeded id. What is asserted here is
therefore what the SPA depends on: the agent is listed, its published version comes back
with the DNA the runtime executes, and a missing agent is a 404 rather than an empty
list.

The fixture seeds the real skeleton agent (``scripts/seed.py``, the demo's own artifact)
but under a tenant slug of this module's own, because an API test has to *commit* its
rows for the app's connection to see them. Borrowing the shared ``meridian-supply-co``
slug would leave it behind for whichever module runs next.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AgentVersion, Tenant
from app.tools.registry import GET_FACT_REF
from scripts.seed import SKELETON_VERSION, seed_skeleton_agent

AGENTS_URL = "/api/v1/agents"
HEADERS = {"X-Forge-Role": "viewer"}


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    """App client bound to the test database (module-scoped: one event loop)."""
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def skeleton(committed_session: Session) -> AgentVersion:
    """A published skeleton agent, committed so the app's own connection can see it."""
    tenant = Tenant(slug=f"catalog-test-{uuid.uuid4().hex[:8]}", name="Catalog Test Tenant")
    committed_session.add(tenant)
    committed_session.flush()
    version, _ = seed_skeleton_agent(committed_session, tenant)
    committed_session.commit()
    return version


def _listed(client: TestClient, agent_id: uuid.UUID) -> dict[str, Any]:
    """The catalog entry for one agent, or a failure saying it was not listed."""
    response = client.get(AGENTS_URL, headers=HEADERS)
    assert response.status_code == 200, response.text
    agents: list[dict[str, Any]] = response.json()
    matches = [agent for agent in agents if agent["id"] == str(agent_id)]
    assert matches, f"agent {agent_id} not in the catalog"
    return matches[0]


def test_lists_the_seeded_agent(client: TestClient, skeleton: AgentVersion) -> None:
    agent = _listed(client, skeleton.agent_id)
    assert agent["slug"] == "skeleton-echo"
    assert agent["type"] == "workflow"
    assert agent["description"]


def test_versions_carry_the_dna_the_runtime_executes(
    client: TestClient, skeleton: AgentVersion
) -> None:
    response = client.get(f"{AGENTS_URL}/{skeleton.agent_id}/versions", headers=HEADERS)
    assert response.status_code == 200, response.text

    versions: list[dict[str, Any]] = response.json()
    published = [item for item in versions if item["version"] == SKELETON_VERSION]
    assert len(published) == 1
    version = published[0]
    assert version["status"] == "published"
    # The SPA reads the grant list to show what this version was allowed to reach.
    assert version["dna"]["tools"] == [{"ref": GET_FACT_REF, "autonomy": "autonomous"}]
    # Seeded, so it never passed a gate — and says so (see scripts/seed.py).
    assert version["published_eval_run_id"] is None


def test_versions_of_an_unknown_agent_are_a_404(client: TestClient) -> None:
    response = client.get(f"{AGENTS_URL}/{uuid.uuid4()}/versions", headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["code"] == "agent_not_found"


def test_the_role_header_is_required(client: TestClient) -> None:
    """Every endpoint states an acting identity, read-only ones included (NFR-5)."""
    assert client.get(AGENTS_URL).status_code == 422
