"""Observability and containment, through the real HTTP surface (FR-G3, FR-G4).

Three claims under test, each structural rather than behavioural:

* **Metrics are the event log, aggregated.** The dashboard numbers are asserted against
  runs this file itself produced through ``POST /runs``, and every figure has to agree
  with what the append-only events say — there is no counters table that could agree
  or disagree on its own (ADR-008).
* **The breaker trips on the record, and refusals are recorded too.** A suspension is a
  ``version.suspended`` event carrying the numbers it was judged on; a refused start is
  a ``governance.run_refused`` event with the ``agent_suspended`` reason code.
* **Nothing resumes itself, and no builder can.** Resume needs ``agent.resume`` —
  admin only, structurally incompatible with configuring or publishing (NFR-5 applied
  to containment).

The breaker thresholds are process-cached settings; ``conftest.breaker_headroom`` parks
them out of everyone else's way, and the tests here lower them explicitly.
"""

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.governance import INCOMPATIBLE_DUTIES, ROLE_PERMISSIONS, Permission, Role
from app.llm import FakeAdapter, LlmGateway, ScriptedTurn, decision_turn, tool_turn
from app.models import AgentVersion, Event, Tenant
from scripts.seed import seed_tenant
from tests.skeleton import publish_skeleton

RUNS_URL = "/api/v1/runs"
METRICS_URL = "/api/v1/metrics"
CONFIGURATOR = {"X-Forge-Role": "configurator"}
ADMIN = {"X-Forge-Role": "admin"}
VIEWER = {"X-Forge-Role": "viewer"}

# The three outcomes the metrics tests mix. A fault asks for a tool that does not
# exist, which the gateway refuses (tool_unknown) — a platform fault, breaker fuel.
LOOK_UP_FORGE = tool_turn("get_fact", {"topic": "forge"})
APPROVE = decision_turn("auto_approve", ["R-000"], "The governed fact was retrieved.")
ESCALATE = decision_turn("escalate", ["R-000"], "This one belongs with a person.")
FAULT = tool_turn("no_such_tool", {})


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    """App client bound to the test database (one event loop per module)."""
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def scripted(client: TestClient) -> Iterator[Callable[..., FakeAdapter]]:
    """Install a scripted adapter behind the LLM gateway for one test."""
    from app.api.deps import get_llm_gateway
    from app.main import app

    def install(*turns: ScriptedTurn, repeat_last: bool = False) -> FakeAdapter:
        adapter = FakeAdapter(script=list(turns), repeat_last=repeat_last)
        app.dependency_overrides[get_llm_gateway] = lambda: LlmGateway([adapter])
        return adapter

    yield install
    app.dependency_overrides.clear()


@pytest.fixture
def tenant(committed_session: Session) -> Tenant:
    tenant, _ = seed_tenant(committed_session)
    committed_session.commit()
    return tenant


def start_run(
    client: TestClient,
    version: AgentVersion,
    scripted: Callable[..., FakeAdapter],
    *turns: ScriptedTurn,
    expect: int = 202,
) -> dict[str, Any]:
    """Script the model, start one run, and return the response body."""
    scripted(*turns)
    response = client.post(
        RUNS_URL,
        json={
            "agent_id": str(version.agent_id),
            "version": version.version,
            "input": {"topic": "forge"},
        },
        headers=CONFIGURATOR,
    )
    assert response.status_code == expect, response.text
    body: dict[str, Any] = response.json()
    return body


def agent_metrics(client: TestClient, agent_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/agents/{agent_id}/metrics", headers=VIEWER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def events_of_type(session: Session, type_: str) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.type == type_).order_by(Event.event_id)))


# --- FR-G3: metrics are the event log, aggregated ------------------------------


def test_metrics_reflect_mixed_outcomes_and_link_back_to_their_runs(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """One completed, one escalated, one blocked — and the numbers must say exactly that."""
    version = publish_skeleton(committed_session, tenant, slug="metrics-mixed")

    completed = start_run(client, version, scripted, LOOK_UP_FORGE, APPROVE)
    escalated = start_run(client, version, scripted, ESCALATE)
    blocked = start_run(client, version, scripted, FAULT)

    row = agent_metrics(client, str(version.agent_id))
    assert row["slug"] == "metrics-mixed"
    assert row["state"] == "published"
    assert row["suspension"] is None

    metrics = row["metrics"]
    assert metrics["runs"] == 3
    assert metrics["finished_runs"] == 3
    assert metrics["runs_by_status"] == {"completed": 1, "escalated": 2}
    # One of three ran start-to-decision with no human and no refusal.
    assert metrics["auto_approval_rate"] == pytest.approx(1 / 3)
    # Both the agent's own escalation and the refused tool end in `escalated`.
    assert metrics["escalation_rate"] == pytest.approx(2 / 3)
    # Only the refusal is a platform fault; the agent deciding "a person" is not.
    assert metrics["block_rate"] == pytest.approx(1 / 3)
    assert metrics["blocks_by_reason"] == {"tool_unknown": 1}
    # 2 turns + 1 turn + 1 turn at 300 tokens and $0.0005 each, over 3 finished runs.
    assert metrics["avg_tokens_per_run"] == pytest.approx(400)
    assert metrics["avg_cost_usd_per_run"] == "0.000667"
    assert metrics["total_cost_usd"] == "0.002000"
    assert metrics["avg_latency_seconds"] is not None and metrics["avg_latency_seconds"] > 0

    # The receipts: every run behind the numbers is listed and its trace is servable.
    listed = {ref["run_id"] for ref in row["recent_runs"]}
    assert listed == {completed["id"], escalated["id"], blocked["id"]}
    trace = client.get(f"{RUNS_URL}/{blocked['id']}/trace", headers=VIEWER)
    assert trace.status_code == 200
    assert any(
        step["kind"] == "governance" and step["governance"]["reason_code"] == "tool_unknown"
        for step in trace.json()["steps"]
    )

    # The same row appears in the overall report, and the overall numbers include it.
    report = client.get(METRICS_URL, headers=VIEWER)
    assert report.status_code == 200, report.text
    body = report.json()
    assert any(agent["slug"] == "metrics-mixed" for agent in body["agents"])
    assert body["overall"]["runs"] >= 3


def test_an_agent_with_no_runs_reports_no_data_rather_than_zero_rates(
    client: TestClient, committed_session: Session, tenant: Tenant
) -> None:
    """Null, not 0: "never ran" must not read as "never escalates" on a dashboard."""
    version = publish_skeleton(committed_session, tenant, slug="metrics-idle")

    metrics = agent_metrics(client, str(version.agent_id))["metrics"]

    assert metrics["runs"] == 0
    assert metrics["auto_approval_rate"] is None
    assert metrics["escalation_rate"] is None
    assert metrics["block_rate"] is None
    assert metrics["avg_cost_usd_per_run"] is None
    assert metrics["total_cost_usd"] == "0.000000"


# --- FR-G4: the circuit breaker ------------------------------------------------


def test_breaker_trips_on_failure_rate_refuses_new_runs_and_only_admin_resumes(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole containment story: trip, recorded refusals, failed override, resume."""
    settings = get_settings()
    monkeypatch.setattr(settings, "breaker_min_runs", 3)
    monkeypatch.setattr(settings, "breaker_max_failure_rate", 0.5)
    version = publish_skeleton(committed_session, tenant, slug="breaker-rate")
    agent_id = str(version.agent_id)

    # One good run, then two faults: 2 of 3 finished runs faulted (0.667 > 0.5).
    start_run(client, version, scripted, LOOK_UP_FORGE, APPROVE)
    start_run(client, version, scripted, FAULT)
    start_run(client, version, scripted, FAULT)

    # The transition happened and was recorded with the numbers it was judged on.
    committed_session.expire_all()
    row = committed_session.get(AgentVersion, version.id)
    assert row is not None and row.status == "suspended"
    suspended = [
        event
        for event in events_of_type(committed_session, "version.suspended")
        if event.agent_version_id == version.id
    ]
    assert len(suspended) == 1
    payload = suspended[0].payload
    assert suspended[0].actor == "system:circuit-breaker"
    assert payload["trigger"] == "circuit_breaker"
    assert payload["breaker"]["metric"] == "failure_rate"
    assert payload["breaker"]["faulted_in_window"] == 2

    dashboard = agent_metrics(client, agent_id)
    assert dashboard["state"] == "suspended"
    assert dashboard["suspension"]["trigger"] == "circuit_breaker"

    # A new run is refused with the governance code, and the refusal is itself an event.
    refusal = start_run(client, version, scripted, LOOK_UP_FORGE, APPROVE, expect=409)
    assert refusal["code"] == "agent_suspended"
    assert refusal["details"]["reason_code"] == "agent_suspended"
    refused_events = [
        event
        for event in events_of_type(committed_session, "governance.run_refused")
        if event.agent_version_id == version.id
    ]
    assert len(refused_events) == 1
    assert agent_metrics(client, agent_id)["metrics"]["runs_refused"] == 1

    # The role that published the agent cannot un-contain it (NFR-5).
    denied = client.post(
        f"/api/v1/agents/{agent_id}/versions/{version.version}/resume",
        headers=CONFIGURATOR,
    )
    assert denied.status_code == 403, denied.text
    committed_session.expire_all()
    row = committed_session.get(AgentVersion, version.id)
    assert row is not None and row.status == "suspended"

    # The admin can, and the resume is recorded with actor and note.
    resumed = client.post(
        f"/api/v1/agents/{agent_id}/versions/{version.version}/resume",
        headers=ADMIN,
        json={"note": "root cause fixed"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "published"
    resume_events = [
        event
        for event in events_of_type(committed_session, "version.resumed")
        if event.agent_version_id == version.id
    ]
    assert len(resume_events) == 1
    assert resume_events[0].actor == "role:admin"
    assert resume_events[0].payload["note"] == "root cause fixed"
    assert resume_events[0].payload["cleared_trigger"] == "circuit_breaker"

    # And the agent runs again — with thresholds it will trip once more if abused,
    # so keep this last run clean and the window judged on fresh evidence.
    monkeypatch.setattr(settings, "breaker_min_runs", 10**6)
    start_run(client, version, scripted, LOOK_UP_FORGE, APPROVE)
    assert agent_metrics(client, agent_id)["state"] == "published"


def test_breaker_trips_on_cost_regardless_of_run_count(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One absurdly expensive run is already the incident; no minimum applies."""
    settings = get_settings()
    monkeypatch.setattr(settings, "breaker_max_cost_usd", Decimal("0.0001"))
    version = publish_skeleton(committed_session, tenant, slug="breaker-cost")

    # A single completed run costs 2 x $0.0005 — over the $0.0001 ceiling.
    start_run(client, version, scripted, LOOK_UP_FORGE, APPROVE)

    committed_session.expire_all()
    row = committed_session.get(AgentVersion, version.id)
    assert row is not None and row.status == "suspended"
    dashboard = agent_metrics(client, str(version.agent_id))
    assert dashboard["state"] == "suspended"
    assert dashboard["suspension"]["breaker"]["metric"] == "cost"


# --- Manual suspend, and who may hold which lever -------------------------------


def test_manual_suspend_is_recorded_and_the_viewer_may_not_pull_the_lever(
    client: TestClient, committed_session: Session, tenant: Tenant
) -> None:
    version = publish_skeleton(committed_session, tenant, slug="manual-suspend")
    url = f"/api/v1/agents/{version.agent_id}/versions/{version.version}"

    refused = client.post(f"{url}/suspend", headers=VIEWER, json={"reason": "no"})
    assert refused.status_code == 403

    suspended = client.post(
        f"{url}/suspend", headers=CONFIGURATOR, json={"reason": "maintenance window"}
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    dashboard = agent_metrics(client, str(version.agent_id))
    assert dashboard["state"] == "suspended"
    assert dashboard["suspension"]["trigger"] == "manual"
    assert dashboard["suspension"]["detail"] == "maintenance window"

    # Only a suspended version can be resumed, and only published ones suspended.
    again = client.post(f"{url}/suspend", headers=CONFIGURATOR)
    assert again.status_code == 409
    assert again.json()["code"] == "version_not_published"

    back = client.post(f"{url}/resume", headers=ADMIN)
    assert back.status_code == 200
    not_suspended = client.post(f"{url}/resume", headers=ADMIN)
    assert not_suspended.status_code == 409
    assert not_suspended.json()["code"] == "version_not_suspended"


def test_no_role_that_builds_or_ships_agents_may_hold_the_resume_lever() -> None:
    """NFR-5 applied to containment, asserted against the matrix itself."""
    assert (Permission.AGENT_CONFIGURE, Permission.AGENT_RESUME) in INCOMPATIBLE_DUTIES
    assert (Permission.AGENT_PUBLISH, Permission.AGENT_RESUME) in INCOMPATIBLE_DUTIES
    resumers = [role for role, held in ROLE_PERMISSIONS.items() if Permission.AGENT_RESUME in held]
    assert resumers == [Role.ADMIN]
    for role in resumers:
        held = ROLE_PERMISSIONS[role]
        assert Permission.AGENT_CONFIGURE not in held
        assert Permission.AGENT_PUBLISH not in held
