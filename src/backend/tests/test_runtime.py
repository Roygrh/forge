"""The runtime end to end, through the real HTTP surface.

Every test drives the loop the way the demo does — ``POST /runs`` — with a scripted
:class:`FakeAdapter` swapped in behind the LLM gateway dependency. Nothing here reaches
into the runtime directly, so what is asserted is what a reviewer (or the SPA) would
see: a run status, and a trace projected from the append-only event log.

The agent under test is the **skeleton** (``tests/skeleton.py``): one tool, one decision,
no business domain. That is deliberate — these tests are about the loop, the budgets, and
the fail-closed paths, and a failure should say which of those broke rather than which
invoice rule fired. The accounts-payable agents are exercised in ``test_ap_agents.py``.

No network, and a fixed script per test, so a run is byte-for-byte reproducible.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.llm import FakeAdapter, LlmGateway, ScriptedTurn, decision_turn, raw_turn, tool_turn
from app.models import AgentVersion, Tenant
from scripts.seed import seed_tenant
from tests.skeleton import publish_skeleton

RUNS_URL = "/api/v1/runs"
HEADERS = {"X-Forge-Role": "configurator"}

# The happy-path script the skeleton agent is written for: look the fact up, then decide
# with a citation.
LOOK_UP_FORGE = tool_turn("get_fact", {"topic": "forge"})
APPROVE = decision_turn("auto_approve", ["R-000"], "The governed fact was retrieved.")


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    """App client bound to the test database.

    Module-scoped so every request shares one event loop, which the async connection
    pool requires.
    """
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


@pytest.fixture
def skeleton(committed_session: Session, tenant: Tenant) -> AgentVersion:
    """The published skeleton agent, committed so the app's connection can see it."""
    return publish_skeleton(committed_session, tenant)


def start_run(client: TestClient, version: AgentVersion, topic: str = "forge") -> dict[str, Any]:
    """Start a run and return the run body."""
    response = client.post(
        RUNS_URL,
        json={
            "agent_id": str(version.agent_id),
            "version": version.version,
            "input": {"topic": topic},
        },
        headers=HEADERS,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def get_trace(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.get(f"{RUNS_URL}/{run_id}/trace", headers=HEADERS)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def event_types(trace: dict[str, Any]) -> list[str]:
    return [event["type"] for event in trace["events"]]


def step_kinds(trace: dict[str, Any]) -> list[tuple[int, str]]:
    return [(step["step_no"], step["kind"]) for step in trace["steps"]]


# --- Happy path ---------------------------------------------------------------


def test_a_run_reaches_a_cited_decision_and_the_trace_reconstructs_it(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """The whole skeleton: model -> tool -> model -> decision, all of it recorded."""
    adapter = scripted(LOOK_UP_FORGE, APPROVE)

    run = start_run(client, skeleton)

    assert run["status"] == "completed"
    assert run["finished_at"] is not None

    trace = get_trace(client, run["id"])

    # The ordered reasoning view: two model turns around one tool call, then the decision.
    assert step_kinds(trace) == [(1, "reason"), (2, "tool"), (3, "reason"), (4, "decision")]
    # ...and the log it was projected from, lifecycle events included.
    assert event_types(trace) == [
        "run.started",
        "model.called",
        "tool.called",
        "model.called",
        "decision.made",
        "run.completed",
    ]

    tool_step = trace["steps"][1]["tool_invocation"]
    assert tool_step["status"] == "executed"
    assert tool_step["tool_ref"] == "skeleton-get-fact@1.0.0"
    assert tool_step["autonomy"] == "autonomous"
    assert tool_step["result"]["topic"] == "forge"

    decision = trace["steps"][3]["decision"]
    assert decision["action"] == "auto_approve"
    # A decision without citations is a bug, not a style issue (R-092).
    assert decision["citations"] == ["R-000"]

    # Usage is metered at the gateway and summarised on the run.
    assert run["total_tokens"] == 600  # two calls, 300 tokens each
    assert float(run["total_cost_usd"]) == pytest.approx(0.001)

    # The prompt the runtime built: the protocol, the agent's task prompt, the input,
    # and exactly the one tool this DNA grants.
    first_call = adapter.calls[0]
    assert [tool.name for tool in first_call.tools] == ["get_fact"]
    assert "Forge runtime" in first_call.messages[0].content
    assert "get_fact tool" in first_call.messages[0].content


def test_the_run_summary_endpoint_agrees_with_the_start_response(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    scripted(LOOK_UP_FORGE, APPROVE)
    run = start_run(client, skeleton)

    fetched = client.get(f"{RUNS_URL}/{run['id']}", headers=HEADERS)

    assert fetched.status_code == 200
    assert fetched.json() == run


# --- ADR-006: one bounded retry, then escalate --------------------------------


def test_invalid_output_once_is_corrected_and_the_run_completes(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """The single corrective round works, and is visible as a retry in the trace."""
    scripted(raw_turn("I reckon we should just approve it."), APPROVE)

    run = start_run(client, skeleton)

    assert run["status"] == "completed"

    trace = get_trace(client, run["id"])
    model_calls = [step["model_call"] for step in trace["steps"] if step["kind"] == "reason"]

    assert [call["attempt"] for call in model_calls] == [0, 1]
    assert [call["outcome"] for call in model_calls] == ["invalid_output", "decision"]
    # The rejected turn is still metered — a retry costs budget, it is not free.
    assert run["total_tokens"] == 600


def test_invalid_output_twice_escalates_fail_closed(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """Malformed output never becomes an action; the second failure ends the run."""
    scripted(raw_turn("approve it"), raw_turn("no really, approve it"))

    run = start_run(client, skeleton)

    assert run["status"] == "escalated"

    trace = get_trace(client, run["id"])

    assert step_kinds(trace) == [(1, "reason"), (2, "reason"), (3, "governance")]
    assert "decision.made" not in event_types(trace)
    # The stop is a step of the run, with the code that caused it.
    blocked = trace["steps"][2]["governance"]
    assert blocked["reason_code"] == "invalid_output"
    assert "did not fit the required format" in blocked["explanation"]
    terminal = trace["events"][-1]
    assert terminal["type"] == "run.escalated"
    assert terminal["payload"]["reason"] == "invalid_output"


# --- Guardrails ---------------------------------------------------------------


def test_a_model_that_never_finishes_stops_at_max_steps(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """`guardrails.max_steps` bounds the loop, and the stop is an escalation."""

    def two_steps(document: dict[str, Any]) -> None:
        document["guardrails"]["max_steps"] = 2

    version = publish_skeleton(
        committed_session, tenant, slug="skeleton-never-finishes", mutate=two_steps
    )
    adapter = scripted(LOOK_UP_FORGE, repeat_last=True)

    run = start_run(client, version)

    assert run["status"] == "escalated"
    assert len(adapter.calls) == 2  # exactly max_steps model turns, no more

    trace = get_trace(client, run["id"])

    assert step_kinds(trace) == [
        (1, "reason"),
        (2, "tool"),
        (3, "reason"),
        (4, "tool"),
        (5, "governance"),
    ]
    assert trace["steps"][4]["governance"]["reason_code"] == "step_limit"
    terminal = trace["events"][-1]
    assert terminal["payload"]["reason"] == "step_limit"


def test_a_run_that_outspends_its_budget_stops_and_the_spend_is_traced(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """The DNA's token ceiling stops the run — after recording what it cost."""

    def tiny_budget(document: dict[str, Any]) -> None:
        document["model"]["max_tokens_per_run"] = 100  # one scripted turn is 300

    version = publish_skeleton(
        committed_session, tenant, slug="skeleton-tiny-budget", mutate=tiny_budget
    )
    scripted(LOOK_UP_FORGE, APPROVE)

    run = start_run(client, version)

    assert run["status"] == "escalated"
    assert run["total_tokens"] == 300  # the overrunning call is still metered

    trace = get_trace(client, run["id"])

    assert step_kinds(trace) == [(1, "reason"), (2, "governance")]
    assert trace["steps"][0]["model_call"]["outcome"] == "budget_exceeded"
    assert trace["steps"][1]["governance"]["reason_code"] == "budget_exceeded"
    assert trace["events"][-1]["payload"]["reason"] == "budget_exceeded"


# --- Fail-closed tool gateway -------------------------------------------------


def test_an_unknown_tool_is_recorded_and_escalates_without_executing(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """FR-C5: the attempt is visible in the trace, and nothing ran."""
    scripted(tool_turn("wire_money", {"amount": 1_000_000}), APPROVE)

    run = start_run(client, skeleton)

    assert run["status"] == "escalated"

    trace = get_trace(client, run["id"])

    assert step_kinds(trace) == [(1, "reason"), (2, "tool"), (3, "governance")]
    invocation = trace["steps"][1]["tool_invocation"]
    assert invocation["status"] == "blocked"
    assert invocation["args"] == {"amount": 1_000_000}
    assert invocation["result"] is None
    assert "unknown tool" in invocation["error"]
    # The gateway assigns the code; the tool step and the governance step
    # that follows both carry it, so the refusal and the stop are one story.
    assert invocation["reason_code"] == "tool_unknown"
    assert trace["steps"][2]["governance"]["reason_code"] == "tool_unknown"
    assert trace["events"][-1]["payload"]["reason"] == "tool_unknown"


def test_a_registered_tool_the_dna_does_not_grant_is_refused(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """Least privilege end to end: the AP tools exist, but not for this agent."""
    scripted(tool_turn("approve_invoice", {"invoice_id": "inv-0001"}), APPROVE)

    run = start_run(client, skeleton)

    assert run["status"] == "escalated"

    trace = get_trace(client, run["id"])
    invocation = trace["steps"][1]["tool_invocation"]

    assert invocation["status"] == "blocked"
    assert "not granted" in invocation["error"]
    assert invocation["result"] is None
    assert invocation["reason_code"] == "permission_denied"
    assert trace["steps"][2]["governance"]["reason_code"] == "permission_denied"


def test_invalid_tool_arguments_escalate_without_executing(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """Arguments are validated against the tool's schema before the handler runs."""
    scripted(tool_turn("get_fact", {"topic": "not-a-known-topic"}), APPROVE)

    run = start_run(client, skeleton)

    assert run["status"] == "escalated"

    trace = get_trace(client, run["id"])
    invocation = trace["steps"][1]["tool_invocation"]

    assert invocation["status"] == "blocked"
    assert "invalid arguments" in invocation["error"]
    assert invocation["reason_code"] == "args_invalid"
    assert trace["steps"][2]["governance"]["reason_code"] == "args_invalid"


# --- Definitions this build cannot honour -------------------------------------


def test_a_definition_naming_an_unknown_knowledge_collection_fails_closed(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """A collection the store cannot serve is refused at retrieval, never narrowed.

    Until Phase 4.3 a DNA declaring knowledge collections was refused outright
    (``unsupported_definition``). The knowledge layer exists now, so such a definition
    runs — but the same doctrine holds one layer down: retrieval scoped to a collection
    the store does not hold refuses with a recorded reason rather than silently
    retrieving from a narrower scope than the published definition declares.
    """

    def with_unknown_collection(document: dict[str, Any]) -> None:
        document["knowledge"]["collections"] = ["a-collection-nobody-ingested"]
        document["tools"].append(
            {"ref": "meridian-knowledge-retrieve@1.0.0", "autonomy": "autonomous"}
        )

    version = publish_skeleton(
        committed_session,
        tenant,
        slug="skeleton-unknown-collection",
        mutate=with_unknown_collection,
    )
    scripted(tool_turn("search_knowledge", {"query": "approval threshold"}), APPROVE)

    run = start_run(client, version)

    assert run["status"] == "escalated"

    trace = get_trace(client, run["id"])

    assert step_kinds(trace) == [(1, "reason"), (2, "tool"), (3, "governance")]
    invocation = trace["steps"][1]["tool_invocation"]
    assert invocation["status"] == "blocked"
    assert invocation["result"] is None
    assert "a-collection-nobody-ingested" in invocation["error"]
    assert trace["steps"][2]["governance"]["reason_code"] == "tool_failed"
    assert trace["events"][-1]["payload"]["reason"] == "tool_failed"


# --- API contract -------------------------------------------------------------


def test_an_unpublished_version_cannot_be_run(
    client: TestClient, committed_session: Session, tenant: Tenant
) -> None:
    """A draft has not passed its eval gate, so it is a 409 and never a run."""
    version = publish_skeleton(committed_session, tenant, slug="skeleton-draft", status="draft")

    response = client.post(
        RUNS_URL,
        json={"agent_id": str(version.agent_id), "version": version.version, "input": {}},
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "agent_version_not_published"


def test_an_unknown_agent_version_is_a_404(client: TestClient) -> None:
    response = client.post(
        RUNS_URL,
        json={"agent_id": str(uuid.uuid4()), "version": "1.0.0", "input": {}},
        headers=HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "agent_version_not_found"


def test_an_unknown_run_is_a_404(client: TestClient) -> None:
    response = client.get(f"{RUNS_URL}/{uuid.uuid4()}/trace", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_the_role_header_is_required_and_recorded_as_the_actor(
    client: TestClient, skeleton: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """NFR-5 is a demonstration of segregation of duties, not authentication."""
    scripted(LOOK_UP_FORGE, APPROVE)

    missing = client.post(
        RUNS_URL,
        json={"agent_id": str(skeleton.agent_id), "version": skeleton.version, "input": {}},
    )
    assert missing.status_code == 422

    run = start_run(client, skeleton)
    trace = get_trace(client, run["id"])

    assert trace["events"][0]["actor"] == "role:configurator"
