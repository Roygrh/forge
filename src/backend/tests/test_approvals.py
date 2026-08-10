"""The human in the loop, end to end through the real HTTP surface (FR-E1..E5).

Phase 4.4's claim is a single sentence: **an action a person did not release does not
run, and running out of time is not releasing it.** Everything below is that sentence
checked from a different angle.

Three outcomes and one non-outcome:

* **approve** — the run resumes, the action executes, and MeridianERP records the
  approver rather than the runtime;
* **reject** — the run is canceled and the ERP receives nothing;
* **expire** — the same, decided by nobody, on a deadline the server owns;
* and the fourth branch that does not exist: there is no operation anywhere in the API
  that extends a deadline or approves an action without a person, which
  :func:`test_no_operation_extends_or_auto_approves_an_approval` asserts against the
  served contract rather than against a promise in a docstring.

The comms agent runs on the shipped deterministic adapter — the same one a freshly
composed stack uses — so what these tests exercise is the demo, not a fixture built to
pass them. Where the point is the *evidence* an approver is shown, a scripted adapter
puts a realistic gather-then-ask sequence in the model's mouth, because a well-behaved
comms agent asks its question before it has gathered anything.
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals import MIN_DECIDED_FOR_PROMOTION
from app.erp import get_erp, reset_erp
from app.llm import FakeAdapter, LlmGateway, ScriptedTurn, tool_turn
from app.models import AgentVersion, Event
from scripts.seed import seed_ap_agents, seed_rules, seed_tenant

RUNS_URL = "/api/v1/runs"
APPROVALS_URL = "/api/v1/approvals"

CONFIGURATOR = {"X-Forge-Role": "configurator"}
APPROVER = {"X-Forge-Role": "approver"}
VIEWER = {"X-Forge-Role": "viewer"}

#: The comms agent's own SLA, from its published DNA (`guardrails.approval_sla_seconds`).
COMMS_SLA_SECONDS = 8 * 60 * 60

COMMS_INPUT = {
    "invoice_id": "inv-0005",
    "question": "Which purchase order covers the price difference on this invoice?",
}


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def agents(committed_session: Session) -> dict[str, AgentVersion]:
    """Exactly what ``python -m scripts.seed`` installs."""
    tenant, _ = seed_tenant(committed_session)
    seed_rules(committed_session, tenant)
    published = seed_ap_agents(committed_session, tenant)
    committed_session.commit()
    return {slug: version for slug, (version, _) in published.items()}


@pytest.fixture(autouse=True)
def fresh_erp() -> Iterator[None]:
    reset_erp()
    yield
    reset_erp()


@pytest.fixture
def scripted(client: TestClient) -> Iterator[Callable[..., FakeAdapter]]:
    """Put an exact sequence of turns in the model's mouth for one test."""
    from app.api.deps import get_llm_gateway
    from app.main import app

    def install(*turns: ScriptedTurn) -> FakeAdapter:
        adapter = FakeAdapter(script=list(turns))
        app.dependency_overrides[get_llm_gateway] = lambda: LlmGateway([adapter])
        return adapter

    yield install
    app.dependency_overrides.clear()


@pytest.fixture
def later(client: TestClient) -> Iterator[Callable[[timedelta], None]]:
    """Move the server's clock forward for the rest of one test.

    Expiry is a governance control measured in hours, and a control that can only be
    verified by waiting eight of them is a control nobody verifies. The queue already
    takes its clock as a dependency — exactly like the runtime's wall-clock guardrail —
    so this overrides the one the server reads. Nothing about the deadline itself is
    faked: ``expires_at`` was written when the action parked, and the platform compares
    it against whatever the server believes the time is.
    """
    from app.api.deps import get_clock
    from app.main import app

    def jump(delta: timedelta) -> None:
        app.dependency_overrides[get_clock] = lambda: lambda: datetime.now(UTC) + delta

    yield jump
    app.dependency_overrides.clear()


# --- Helpers ------------------------------------------------------------------


def start(
    client: TestClient,
    version: AgentVersion,
    run_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.post(
        RUNS_URL,
        json={
            "agent_id": str(version.agent_id),
            "version": version.version,
            "input": run_input if run_input is not None else COMMS_INPUT,
        },
        headers=CONFIGURATOR,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def park(
    client: TestClient, agents: dict[str, AgentVersion], run_input: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the comms agent until it parks, and return (run, its pending approval)."""
    run = start(client, agents["invoice-comms"], run_input)
    assert run["status"] == "awaiting_approval", run

    queue = pending(client)
    approval = next(item for item in queue if item["run_id"] == run["id"])
    return run, approval


def pending(client: TestClient, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    response = client.get(APPROVALS_URL, headers=headers or APPROVER)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def decide(
    client: TestClient,
    approval_id: str,
    verdict: str,
    *,
    headers: dict[str, str] | None = None,
    note: str | None = None,
) -> Response:
    response: Response = client.post(
        f"{APPROVALS_URL}/{approval_id}/{verdict}",
        json={"note": note} if note is not None else {},
        headers=headers or APPROVER,
    )
    return response


def approve(client: TestClient, approval_id: str, note: str | None = None) -> dict[str, Any]:
    response = decide(client, approval_id, "approve", note=note)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def reject(client: TestClient, approval_id: str, note: str | None = None) -> dict[str, Any]:
    response = decide(client, approval_id, "reject", note=note)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def get_approval(client: TestClient, approval_id: str) -> dict[str, Any]:
    response = client.get(f"{APPROVALS_URL}/{approval_id}", headers=APPROVER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def run_of(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.get(f"{RUNS_URL}/{run_id}", headers=VIEWER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def trace_of(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.get(f"{RUNS_URL}/{run_id}/trace", headers=VIEWER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def kinds(trace: dict[str, Any]) -> list[str]:
    return [step["kind"] for step in trace["steps"]]


def approval_steps(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [step["approval"] for step in trace["steps"] if step["kind"] == "approval"]


def governance_steps(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [step["governance"] for step in trace["steps"] if step["kind"] == "governance"]


def tool_steps(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [step["tool_invocation"] for step in trace["steps"] if step["kind"] == "tool"]


# --- 1. Parking: a queue entry with a server-side deadline (FR-E2, FR-E3) ------


def test_a_parked_action_becomes_a_pending_approval_with_a_deadline(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """The gateway parks the call; the queue is where it waits, and it waits on a clock."""
    run, approval = park(client, agents)

    assert approval["status"] == "pending"
    assert approval["run_status"] == "awaiting_approval"
    assert approval["decision"] is None
    assert approval["decided_by"] is None
    assert approval["decided_at"] is None

    # What is being approved: one action instance, with the arguments the gateway
    # validated — not "the comms agent may contact vendors".
    action = approval["proposed_action"]
    assert action["tool_ref"] == "meridian-erp-request-info-from-vendor@1.0.0"
    assert action["autonomy"] == "requires_approval"
    assert action["status"] == "validated"  # checked, and not run
    assert action["args"]["invoice_id"] == "inv-0005"
    assert action["args"]["question"] == COMMS_INPUT["question"]

    # The deadline comes from the agent's own published DNA, and it is already ticking.
    assert 0 < approval["seconds_remaining"] <= COMMS_SLA_SECONDS
    expires_at = datetime.fromisoformat(approval["expires_at"])
    assert expires_at > datetime.fromisoformat(run["started_at"])

    assert "requires a person" in approval["why_approval_required"]
    assert get_erp().posted_actions() == []


def test_the_queue_carries_the_evidence_to_decide_without_opening_another_tab(
    client: TestClient, agents: dict[str, AgentVersion], scripted: Callable[..., FakeAdapter]
) -> None:
    """Kevin's minute (FR-E1): the invoice, the PO, and which rule fired, all in one payload.

    The validator gathers before it asks — the sequence is scripted because a well-behaved
    comms agent asks its question first, and what is under test here is the *envelope*:
    everything the agent saw travels with the approval, verbatim, from the run's own log.
    """
    scripted(
        tool_turn("read_invoice", {"invoice_id": "inv-0001"}),
        tool_turn("match_po", {"invoice_id": "inv-0001"}),
        tool_turn("query_rules", {"invoice_id": "inv-0001"}),
        tool_turn(
            "request_info_from_vendor",
            {
                "invoice_id": "inv-0001",
                "question": "Please confirm the PO covering this delivery.",
                "channel": "email",
            },
        ),
    )

    run = start(client, agents["invoice-validator"], {"invoice_id": "inv-0001"})
    assert run["status"] == "awaiting_approval"

    approval = next(item for item in pending(client) if item["run_id"] == run["id"])
    evidence = approval["evidence"]

    assert evidence["agent"].startswith("invoice-validator@")
    assert evidence["run_input"] == {"invoice_id": "inv-0001"}

    gathered = {observation["tool_name"]: observation for observation in evidence["observations"]}
    assert set(gathered) == {"read_invoice", "match_po", "query_rules"}
    # The invoice as captured, and the PO beside it — the two things Kevin asked for.
    assert gathered["read_invoice"]["result"]["number"] == "INV-4401"
    assert gathered["match_po"]["result"]["po_number"] == "PO-8801"
    assert gathered["match_po"]["result"]["price_variance_pct"] == "0.80"
    # ...and which rules were in play, lifted out of what the agent retrieved.
    assert {"R-001", "R-010"} <= set(evidence["rule_ids"])

    # The parked call itself is the proposal, served beside the evidence rather than
    # inside it: what the agent gathered and what it wants to do are different things.
    assert approval["proposed_action"]["args"]["channel"] == "email"
    assert "request_info_from_vendor" not in gathered


# --- 2. Approve: the run resumes and executes exactly what was released --------


def test_approving_resumes_the_run_and_executes_the_released_action(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """The whole approve branch, on the shipped configuration.

    The action runs *after* the approval is recorded, through the same gateway that
    parked it, with the arguments that were parked — and MeridianERP records the person
    who released it, not the runtime that carried it out.
    """
    run, approval = park(client, agents)

    granted = approve(client, approval["id"], note="PO confirmed by phone; go ahead.")

    assert granted["status"] == "granted"
    assert granted["decision"] == "approve"
    assert granted["decided_by"] == "role:approver"
    assert granted["decided_at"] is not None
    assert granted["note"] == "PO confirmed by phone; go ahead."

    # The run carried on to a terminal state of its own.
    resumed = run_of(client, run["id"])
    assert resumed["status"] == "escalated"
    assert resumed["finished_at"] is not None

    # MeridianERP got the message — once, with the approved question, from the approver.
    posted = get_erp().posted_actions()
    assert [action.kind for action in posted] == ["info_request"]
    assert posted[0].actor == "role:approver"
    assert posted[0].detail["question"] == COMMS_INPUT["question"]
    assert posted[0].invoice_id == "inv-0005"


def test_the_resumed_trace_tells_the_whole_story_in_order(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """Parked, decided, executed, decided — one run, one ordered log (FR-G1)."""
    run, approval = park(client, agents)
    approve(client, approval["id"])

    trace = trace_of(client, run["id"])

    assert kinds(trace) == [
        "reason",  # the agent planned the question
        "tool",  # ...asked for the tool, and the gateway parked the call
        "approval",  # ...which opened this queue entry
        "governance",  # ...and stopped the run in awaiting_approval
        "approval",  # a person released it
        "tool",  # ...so the call ran, this time
        "reason",  # the agent carried on from the result
        "decision",  # ...and decided the invoice waits on the vendor
        "governance",  # R-091: unresolved, so it goes to a human
    ]

    parked, released = approval_steps(trace)
    assert parked["status"] == "pending" and parked["decided_by"] is None
    assert released["status"] == "granted"
    assert released["decided_by"] == "role:approver"
    assert released["decided_at"] is not None
    # The action recorded on the approval is the action that ran: same tool, same args.
    assert parked["args"] == released["args"]

    held, executed = tool_steps(trace)
    assert held["status"] == "validated" and held["result"] is None
    assert executed["status"] == "executed"
    assert executed["args"] == parked["args"]
    assert executed["result"]["status"] == "sent"
    # An execution somebody signed for does not read like an autonomous one.
    assert executed["approval_id"] == approval["id"]
    assert executed["released_by"] == "role:approver"

    # Both stops are in the log, in order, each with its own reason.
    assert [block["reason_code"] for block in governance_steps(trace)] == [
        "approval_required",
        "no_rule_match",
    ]
    assert [event["type"] for event in trace["events"]][-1] == "run.escalated"
    assert {"approval.pending", "approval.granted"} <= {e["type"] for e in trace["events"]}

    # The approval events carry the approver as the actor; the agent's own steps do not.
    granted_event = next(e for e in trace["events"] if e["type"] == "approval.granted")
    assert granted_event["actor"] == "role:approver"
    assert (
        next(e for e in trace["events"] if e["type"] == "run.started")["actor"] != "role:approver"
    )


def test_a_resumed_run_continues_its_ledger_rather_than_starting_a_new_one(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """An approval buys a person's yes, not a second helping of the budget (FR-B3).

    Two model turns happen across the pause — one before, one after — and the run's
    totals are the sum of both. If the resume built a fresh budget, the run would report
    only what it spent after the approval, and the ceiling would be worth nothing.
    """
    run, approval = park(client, agents)
    parked_run = run_of(client, run["id"])
    assert parked_run["total_tokens"] == 300

    approve(client, approval["id"])

    resumed = run_of(client, run["id"])
    assert resumed["total_tokens"] == 600
    assert float(resumed["total_cost_usd"]) == pytest.approx(0.001)


# --- 3. Granularity: one approval, one action instance (FR-E2) ----------------


def test_approving_one_action_does_not_authorise_another(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """Two proposals, one release. The other one is still waiting, untouched."""
    first_input = {**COMMS_INPUT, "question": "Which PO covers the overage?"}
    second_input = {"invoice_id": "inv-0003", "question": "Please confirm your bank details."}

    _, first = park(client, agents, first_input)
    _, second = park(client, agents, second_input)
    assert first["id"] != second["id"]

    approve(client, first["id"])

    still_waiting = [item["id"] for item in pending(client)]
    assert second["id"] in still_waiting
    assert first["id"] not in still_waiting
    assert get_approval(client, second["id"])["status"] == "pending"

    # Exactly one message left the building, and it is the one that was approved.
    posted = get_erp().posted_actions()
    assert len(posted) == 1
    assert posted[0].detail["question"] == first_input["question"]


def test_a_decision_is_made_once(client: TestClient, agents: dict[str, AgentVersion]) -> None:
    """Deciding twice is a conflict, not a second execution."""
    _, approval = park(client, agents)
    approve(client, approval["id"])

    again = decide(client, approval["id"], "approve")
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "approval_not_pending"

    contradicted = decide(client, approval["id"], "reject")
    assert contradicted.status_code == 409

    # And still exactly one message was sent.
    assert len(get_erp().posted_actions()) == 1


# --- 4. Reject: canceled, and nothing ran -------------------------------------


def test_rejecting_cancels_the_run_and_nothing_is_executed(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """A human's veto is the whole point of the queue, and it is recorded as one."""
    run, approval = park(client, agents)

    rejected = reject(client, approval["id"], note="Wrong vendor contact — I'll call them.")

    assert rejected["status"] == "rejected"
    assert rejected["decision"] == "reject"
    assert rejected["decided_by"] == "role:approver"
    assert rejected["note"] == "Wrong vendor contact — I'll call them."

    canceled = run_of(client, run["id"])
    assert canceled["status"] == "canceled"

    trace = trace_of(client, run["id"])
    assert kinds(trace) == ["reason", "tool", "approval", "governance", "approval", "governance"]
    assert approval_steps(trace)[1]["status"] == "rejected"
    assert approval_steps(trace)[1]["reason_code"] == "approval_rejected"

    ended = governance_steps(trace)[-1]
    assert ended["reason_code"] == "approval_rejected"
    assert ended["terminal_status"] == "canceled"
    assert "Wrong vendor contact" in ended["detail"]
    assert trace["events"][-1]["type"] == "run.canceled"

    # The tool call is still in the trace as validated-and-never-run.
    assert [call["status"] for call in tool_steps(trace)] == ["validated"]
    assert get_erp().posted_actions() == []


# --- 5. Expiry: server-side, and it cancels (FR-E3) ---------------------------


def test_an_expired_approval_cancels_the_run_and_never_approves(
    client: TestClient,
    agents: dict[str, AgentVersion],
    later: Callable[[timedelta], None],
) -> None:
    """The fail-closed invariant, stated as plainly as it can be tested.

    Nobody decides. The deadline passes. The run is **canceled** — not approved, not
    extended, not quietly left waiting — and the ERP never hears from us.
    """
    run, approval = park(client, agents)

    later(timedelta(seconds=COMMS_SLA_SECONDS + 60))

    # Reading the queue is one of the moments expiry is enforced, so the lapsed approval
    # is gone from it — and gone because it was canceled, not because it was hidden.
    assert approval["id"] not in [item["id"] for item in pending(client)]

    expired = get_approval(client, approval["id"])
    assert expired["status"] == "expired"
    assert expired["decision"] is None  # expiry is the absence of a decision, not one
    assert expired["decided_by"] == "system"
    assert expired["seconds_remaining"] == 0

    canceled = run_of(client, run["id"])
    assert canceled["status"] == "canceled"

    trace = trace_of(client, run["id"])
    assert approval_steps(trace)[-1]["status"] == "expired"
    ended = governance_steps(trace)[-1]
    assert ended["reason_code"] == "approval_expired"
    assert ended["terminal_status"] == "canceled"
    assert "never a yes" in ended["detail"]
    assert trace["events"][-1]["type"] == "run.canceled"
    assert trace["events"][-1]["payload"]["reason"] == "approval_expired"

    assert get_erp().posted_actions() == []


def test_approving_after_the_deadline_is_refused_and_the_approval_stays_expired(
    client: TestClient,
    agents: dict[str, AgentVersion],
    later: Callable[[timedelta], None],
) -> None:
    """The race a fail-open system loses: a yes that arrives after the clock ran out."""
    run, approval = park(client, agents)

    later(timedelta(seconds=COMMS_SLA_SECONDS + 1))

    too_late = decide(client, approval["id"], "approve")

    assert too_late.status_code == 409, too_late.text
    body = too_late.json()
    assert body["code"] == "approval_not_pending"
    assert "expiry never approves" in body["message"]

    assert get_approval(client, approval["id"])["status"] == "expired"
    assert run_of(client, run["id"])["status"] == "canceled"
    assert get_erp().posted_actions() == []


def test_expiry_is_enforced_server_side_on_every_path(
    client: TestClient,
    agents: dict[str, AgentVersion],
    later: Callable[[timedelta], None],
) -> None:
    """Reading one approval expires it too — no path serves a lapsed approval as live."""
    _, approval = park(client, agents)

    later(timedelta(hours=24))

    # Straight to the detail endpoint, without ever listing the queue.
    assert get_approval(client, approval["id"])["status"] == "expired"


def test_no_operation_extends_or_auto_approves_an_approval() -> None:
    """The absence is the control, so it is asserted against the served contract.

    An extend, a snooze, or a bulk auto-approve would each turn "expiry cancels" into
    "expiry cancels unless somebody clicks the other button". This fails the moment such
    a route appears, whatever it is called.
    """
    from app.main import app

    approval_paths = {
        path: sorted(operations)
        for path, operations in app.openapi()["paths"].items()
        if "/approvals" in path
    }

    assert approval_paths == {
        "/api/v1/approvals": ["get"],
        "/api/v1/approvals/report": ["get"],
        "/api/v1/approvals/{approval_id}": ["get"],
        "/api/v1/approvals/{approval_id}/approve": ["post"],
        "/api/v1/approvals/{approval_id}/reject": ["post"],
    }

    forbidden = ("extend", "renew", "snooze", "postpone", "auto_approve", "auto-approve")
    served = str(app.openapi()["paths"]).lower()
    for word in forbidden:
        assert f"/{word}" not in served, f"the API exposes an operation named {word!r}"


# --- 6. Segregation of duties: only the approver decides (NFR-5) --------------


@pytest.mark.parametrize("headers", [CONFIGURATOR, VIEWER], ids=["configurator", "viewer"])
def test_only_the_approver_role_may_decide(
    client: TestClient, agents: dict[str, AgentVersion], headers: dict[str, str]
) -> None:
    """The person who decides what an agent may do never approves what it proposes."""
    _, approval = park(client, agents)

    refused = decide(client, approval["id"], "approve", headers=headers)

    assert refused.status_code == 403, refused.text
    body = refused.json()
    assert body["code"] == "permission_denied"
    assert body["details"]["required_permission"] == "approval.decide"

    # The action is exactly where it was, and nothing was sent.
    assert get_approval(client, approval["id"])["status"] == "pending"
    assert get_erp().posted_actions() == []


def test_a_refused_decision_is_recorded_not_only_refused(
    client: TestClient, agents: dict[str, AgentVersion], committed_session: Session
) -> None:
    """No silent blocks — including an attempt to release something one may not."""
    _, approval = park(client, agents)

    decide(client, approval["id"], "approve", headers=CONFIGURATOR)

    committed_session.expire_all()
    recorded = committed_session.scalars(
        select(Event).where(
            Event.type == "governance.permission_denied",
            Event.approval_id == uuid.UUID(approval["id"]),
        )
    ).all()

    assert len(recorded) == 1
    assert recorded[0].actor == "role:configurator"
    assert recorded[0].payload["operation"] == "approval.decide"
    assert recorded[0].payload["reason_code"] == "permission_denied"
    assert "stays parked" in recorded[0].payload["detail"]


def test_every_role_can_read_the_queue(client: TestClient, agents: dict[str, AgentVersion]) -> None:
    """An audit trail nobody may read is not one — reading and deciding are different."""
    park(client, agents)

    for headers in (CONFIGURATOR, APPROVER, VIEWER):
        response = client.get(APPROVALS_URL, headers=headers)
        assert response.status_code == 200, headers


def test_an_unknown_approval_is_a_404(client: TestClient) -> None:
    response = client.get(f"{APPROVALS_URL}/{uuid.uuid4()}", headers=APPROVER)

    assert response.status_code == 404
    assert response.json()["code"] == "approval_not_found"


# --- 7. The autonomy-promotion report (FR-E5) --------------------------------
#
# The report aggregates every approval the tenant has ever recorded, and these tests
# share a database with the ones above, so each asserts on the *change* it caused. That
# is also the honest way to read the report: it is a running tally, not a snapshot of
# one afternoon.

#: The action category the comms agent's every approval belongs to — one agent version,
#: one tool, which is exactly the pair a DNA grant names.
COMMS_CATEGORY = ("invoice-comms@1.2.0", "meridian-erp-request-info-from-vendor@1.0.0")

_EMPTY_CATEGORY = {"pending": 0, "granted": 0, "rejected": 0, "expired": 0, "decided": 0}


def category(client: TestClient, key: tuple[str, str] = COMMS_CATEGORY) -> dict[str, Any]:
    """One row of the autonomy-promotion report, or an empty tally if it has none yet."""
    response = client.get(f"{APPROVALS_URL}/report", headers=VIEWER)
    assert response.status_code == 200, response.text
    rows: dict[tuple[str, str], dict[str, Any]] = {
        (row["agent"], row["tool_ref"]): row for row in response.json()
    }
    return rows.get(key, dict(_EMPTY_CATEGORY))


def test_the_report_shows_approval_rates_per_action_category_and_applies_nothing(
    client: TestClient, agents: dict[str, AgentVersion], committed_session: Session
) -> None:
    """Rosa's fatigue risk, measured — and deliberately not acted on.

    Two grants and one rejection on the same action category. The report counts them,
    says the review is doing work, and does not touch the definition: promotion is a new
    DNA version through the eval gate, never a number crossing a line.
    """
    before = category(client)

    for question in ("Which PO covers this?", "Please confirm the delivery date."):
        _, approval = park(client, agents, {**COMMS_INPUT, "question": question})
        approve(client, approval["id"])

    _, refused = park(client, agents, {**COMMS_INPUT, "question": "Confirm your bank details."})
    reject(client, refused["id"], note="Never ask about bank details by email (R-042).")

    stats = category(client)

    assert stats["granted"] - before["granted"] == 2
    assert stats["rejected"] - before["rejected"] == 1
    assert stats["decided"] - before["decided"] == 3
    assert stats["approval_rate"] == pytest.approx(stats["granted"] / stats["decided"], rel=1e-3)

    # A refusal is on the record, so the review is doing work and the category is not a
    # promotion candidate however many grants pile up beside it.
    assert stats["candidate"] is False
    assert "refused" in stats["recommendation"]
    assert str(MIN_DECIDED_FOR_PROMOTION) in stats["recommendation"] or stats["rejected"]

    # The definition is untouched: the tool is still granted with a human in the loop.
    committed_session.expire_all()
    version = committed_session.get(AgentVersion, agents["invoice-comms"].id)
    assert version is not None
    grants = {grant["ref"]: grant["autonomy"] for grant in version.dna["tools"]}
    assert grants["meridian-erp-request-info-from-vendor@1.0.0"] == "requires_approval"


def test_the_report_counts_expiries_as_a_fatigue_signal_not_as_consent(
    client: TestClient,
    agents: dict[str, AgentVersion],
    later: Callable[[timedelta], None],
) -> None:
    """An expired approval is never counted as an approval — that is the whole point."""
    before = category(client)

    park(client, agents)
    later(timedelta(days=1))
    pending(client)  # reading the queue is one of the moments the deadline is enforced

    stats = category(client)

    assert stats["expired"] > before["expired"]
    assert stats["granted"] == before["granted"]  # nothing became an approval
    assert stats["decided"] == before["decided"]  # ...and expiry is not a decision
    assert stats["candidate"] is False
    assert "canceled their runs" in stats["fatigue_note"]
