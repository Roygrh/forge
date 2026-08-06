"""Governance, proved rather than asserted.

Phase 4.2's claim is that Forge's controls are *structural*: enforced in one place,
impossible to bypass, and recorded whenever they fire. This module is where that claim
is checked, in four parts:

1. **The autonomy matrix.** Each of the three levels, on the sensitive tools they were
   written for, with the outcome each must produce.
2. **One enforcement point.** The source tree is read: a tool handler is invoked in
   exactly one place, and if a second call site ever appears this fails.
3. **Fail-closed, exhaustively.** Every way the platform can refuse, driven end to end
   through the HTTP surface, each asserting the same three things — nothing executed, a
   governance step with the right reason code, and a terminal state that is not success.
4. **Segregation of duties.** The permission matrix, the 403s that follow from it, and
   the audit record a refused operation leaves behind (NFR-5).
"""

import ast
import itertools
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dna import load_agent_dna, validate_dna
from app.erp import get_erp, reset_erp
from app.governance import (
    DENIALS,
    INCOMPATIBLE_DUTIES,
    ROLE_PERMISSIONS,
    GovernanceReason,
    Permission,
    Role,
    explain,
    segregation_violations,
)
from app.llm import FakeAdapter, LlmGateway, ScriptedTurn, decision_turn, raw_turn, tool_turn
from app.models import Agent, AgentVersion, Event, Run, Tenant
from app.tools import ToolGateway
from scripts.seed import seed_ap_agents, seed_rules, seed_tenant

RUNS_URL = "/api/v1/runs"
CONFIGURATOR = {"X-Forge-Role": "configurator"}
BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: The demo invoice every scenario below runs against.
INVOICE = {"invoice_id": "inv-0001"}


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def fresh_erp() -> Iterator[None]:
    reset_erp()
    yield
    reset_erp()


@pytest.fixture
def tenant(committed_session: Session) -> Tenant:
    tenant, _ = seed_tenant(committed_session)
    seed_rules(committed_session, tenant)
    committed_session.commit()
    return tenant


@pytest.fixture
def validator(committed_session: Session, tenant: Tenant) -> AgentVersion:
    """The shipped invoice validator, exactly as ``scripts.seed`` publishes it."""
    published = seed_ap_agents(committed_session, tenant)
    committed_session.commit()
    return published["invoice-validator"][0]


@pytest.fixture
def scripted(client: TestClient) -> Iterator[Callable[..., FakeAdapter]]:
    """Put an exact sequence of turns in the model's mouth for one test."""
    from app.api.deps import get_llm_gateway
    from app.main import app

    def install(*turns: ScriptedTurn, repeat_last: bool = False) -> FakeAdapter:
        adapter = FakeAdapter(script=list(turns), repeat_last=repeat_last)
        app.dependency_overrides[get_llm_gateway] = lambda: LlmGateway([adapter])
        return adapter

    yield install
    app.dependency_overrides.clear()


@pytest.fixture
def racing_clock(client: TestClient) -> Iterator[None]:
    """Install a clock that jumps an hour every time the runtime reads it.

    A guardrail that can only be verified by waiting a real two minutes is a guardrail
    nobody verifies. The runtime already takes its clock as a parameter; this overrides
    the dependency that supplies it.

    It has to *advance*, not merely be offset: the loop computes its deadline from the
    same clock it later checks, so a constant offset moves both and nothing ever expires.
    An hour a tick is far past any timeout a definition may declare, which keeps the test
    independent of how many times the loop happens to look at the clock.
    """
    from app.api.deps import get_clock
    from app.main import app

    def build() -> Callable[[], datetime]:
        start = datetime.now(UTC)
        ticks = itertools.count()

        def tick() -> datetime:
            return start + timedelta(hours=next(ticks))

        return tick

    app.dependency_overrides[get_clock] = build
    yield
    app.dependency_overrides.clear()


def publish_variant(
    session: Session,
    tenant: Tenant,
    slug: str,
    mutate: Callable[[dict[str, Any]], None],
) -> AgentVersion:
    """Publish a variant of the shipped validator, still valid against the schema.

    Variants move exactly one guardrail so a limit can be reached in a test without
    waiting for a real one — and ``validate_dna`` keeps each an honest definition rather
    than a convenient fixture.
    """
    document = load_agent_dna("invoice-validator")
    document["identity"]["slug"] = slug
    mutate(document)
    validate_dna(document)

    agent = session.scalar(
        select(Agent).where(Agent.tenant_id == tenant.tenant_id, Agent.slug == slug)
    )
    if agent is None:
        agent = Agent(
            tenant_id=tenant.tenant_id,
            slug=slug,
            name=document["identity"]["name"],
            type=document["identity"]["type"],
        )
        session.add(agent)
        session.flush()

    existing = session.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id))
    if existing is not None:
        return existing

    version = AgentVersion(
        tenant_id=tenant.tenant_id,
        agent_id=agent.id,
        version=document["identity"]["version"],
        dna=document,
        status="published",
        published_at=datetime.now(UTC),
    )
    session.add(version)
    session.flush()
    session.add(
        Event(
            tenant_id=tenant.tenant_id,
            type="version.published",
            actor="test",
            agent_version_id=version.id,
            payload={"agent": slug, "gate": "bypassed:test"},
        )
    )
    session.commit()
    return version


def run(
    client: TestClient,
    version: AgentVersion,
    run_input: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    response: Response = client.post(
        RUNS_URL,
        json={
            "agent_id": str(version.agent_id),
            "version": version.version,
            "input": run_input if run_input is not None else INVOICE,
        },
        headers=headers or CONFIGURATOR,
    )
    return response


def trace_of(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.get(f"{RUNS_URL}/{run_id}/trace", headers=CONFIGURATOR)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def governance_step(trace: dict[str, Any]) -> dict[str, Any]:
    """The single governance step a stopped run carries."""
    blocks = [step["governance"] for step in trace["steps"] if step["kind"] == "governance"]
    assert len(blocks) == 1, f"expected exactly one governance step, got {len(blocks)}"
    found: dict[str, Any] = blocks[0]
    return found


# --- 1. The autonomy matrix ---------------------------------------------------
#
# One table, three levels, three sensitive tools — the shape a reviewer asks to see.
# Driven straight at the gateway: this is about what the enforcement point decides, not
# about what any particular model happened to ask for.

AUTONOMY_MATRIX = [
    # tool                        autonomy in the shipped DNA   status      reason
    ("read_invoice", "autonomous", "executed", None),
    ("approve_invoice", "autonomous", "executed", None),
    ("request_info_from_vendor", "requires_approval", "validated", "approval_required"),
    ("schedule_payment", "forbidden", "denied", "permission_denied"),
]

VALID_ARGS: dict[str, dict[str, Any]] = {
    "read_invoice": {"invoice_id": "inv-0001"},
    "approve_invoice": {
        "invoice_id": "inv-0001",
        "amount_usd": "4032.00",
        "cited_rule_ids": ["R-001"],
    },
    "request_info_from_vendor": {
        "invoice_id": "inv-0001",
        "question": "Which PO covers this?",
        "channel": "phone_on_file",
    },
    "schedule_payment": {"invoice_id": "inv-0001", "pay_date": "2026-08-10"},
}


@pytest.mark.parametrize(
    ("tool_name", "autonomy", "expected_status", "expected_reason"),
    AUTONOMY_MATRIX,
    ids=[f"{name}-{autonomy}" for name, autonomy, *_ in AUTONOMY_MATRIX],
)
def test_the_gateway_enforces_the_autonomy_its_dna_declares(
    tool_name: str, autonomy: str, expected_status: str, expected_reason: str | None
) -> None:
    """Each level, on the tool the shipped validator grants it for (FR-C3)."""
    from app.dna import Dna

    dna = Dna.model_validate(load_agent_dna("invoice-validator"))
    gateway = ToolGateway()

    outcome = gateway.invoke(name=tool_name, arguments=VALID_ARGS[tool_name], dna=dna)

    assert outcome.autonomy == autonomy
    assert outcome.status == expected_status
    assert (str(outcome.reason) if outcome.reason else None) == expected_reason
    # Only `executed` may carry a result. Parked and denied calls did nothing at all.
    assert (outcome.result is not None) is (expected_status == "executed")


def test_revoking_a_tool_in_the_dna_blocks_the_same_invoice_on_the_shipped_adapter(
    client: TestClient, committed_session: Session, tenant: Tenant
) -> None:
    """One line of the definition changed, and the money-moving step is refused.

    No scripted misbehaviour here: this is the deterministic adapter the demo runs on,
    against the invoice it auto-approves, with `approve_invoice` granted as ``forbidden``
    instead of ``autonomous``. Same runtime, same rules, same facts — the gateway refuses
    the approval, records ``permission_denied``, and the run stops. Least privilege has
    to hold against a model that asks for a tool it was not given, not only against one
    polite enough never to try.
    """

    def revoke(document: dict[str, Any]) -> None:
        for grant in document["tools"]:
            if grant["ref"] == "meridian-erp-approve-invoice@1.0.0":
                grant["autonomy"] = "forbidden"
                grant.pop("config", None)

    version = publish_variant(committed_session, tenant, "governance-no-approval", revoke)

    body = run(client, version).json()
    trace = trace_of(client, body["id"])

    assert body["status"] == "escalated"
    refused = [
        step["tool_invocation"]
        for step in trace["steps"]
        if step["kind"] == "tool" and step["tool_invocation"]["status"] == "denied"
    ]
    assert len(refused) == 1
    assert refused[0]["tool_ref"] == "meridian-erp-approve-invoice@1.0.0"
    assert refused[0]["autonomy"] == "forbidden"
    assert refused[0]["reason_code"] == "permission_denied"
    assert governance_step(trace)["reason_code"] == "permission_denied"
    # And the invoice was never approved in the ERP.
    assert get_erp().invoice("inv-0001").status == "received"


def test_a_forbidden_tool_is_never_offered_to_the_model() -> None:
    """Denial is not only enforced, it is invisible: no door the agent may not open."""
    from app.dna import Dna

    dna = Dna.model_validate(load_agent_dna("invoice-validator"))

    offered = {tool.name for tool in ToolGateway().granted_tools(dna)}

    assert "schedule_payment" not in offered
    assert {"read_invoice", "approve_invoice", "request_info_from_vendor"} <= offered


def test_every_autonomy_level_in_the_contract_has_an_enforcement_rule() -> None:
    """A level the DNA schema admits but the gateway has no rule for would default to...

    ...whatever the last ``if`` did. The mapping is exhaustive by construction instead.
    """
    import json

    from app.tools.gateway import AUTONOMY_EFFECT

    schema = json.loads((BACKEND_ROOT / "app" / "dna" / "dna-schema.json").read_text("utf-8"))
    declared = schema["properties"]["tools"]["items"]["properties"]["autonomy"]["enum"]

    assert set(declared) == set(AUTONOMY_EFFECT)


# --- 2. One enforcement point -------------------------------------------------


def test_a_tool_handler_is_invoked_in_exactly_one_place() -> None:
    """ "Nothing bypasses the gateway" as a property of the call graph, not a convention.

    Reads every module in the package and finds each ``<something>.handler(...)`` call.
    There must be exactly one, in the gateway. A second one — a helper that "just runs
    the tool", a test seam, a shortcut in an endpoint — fails this immediately.
    """
    call_sites: list[str] = []
    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "handler"
            ):
                call_sites.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

    assert len(call_sites) == 1, (
        f"tool handlers are invoked in {len(call_sites)} places: {call_sites}"
    )
    assert call_sites[0].replace("\\", "/").startswith("app/tools/gateway.py")


def test_the_runtime_never_reaches_a_tool_except_through_the_gateway() -> None:
    """The loop knows about ``invoke``, and about nothing further down."""
    source = (BACKEND_ROOT / "app" / "runtime" / "loop.py").read_text(encoding="utf-8")

    assert "self._tools.invoke(" in source
    assert ".handler" not in source
    assert "ToolRegistry" not in source  # it cannot even look a tool up itself


# --- 3. Fail-closed, exhaustively ---------------------------------------------
#
# Each row drives one refusal end to end and asserts the same contract: a terminal state
# that is not success, exactly one governance step carrying the right reason code and a
# human-readable explanation, and no tool executed.


def test_every_reason_code_carries_an_explanation() -> None:
    """A code with no sentence beside it is an incident report with the incident removed."""
    for reason in GovernanceReason:
        assert explain(reason).strip(), f"{reason} has no explanation"
        assert len(explain(reason)) > 40, f"{reason}'s explanation is too thin to be useful"


def test_every_reason_but_a_decided_escalation_counts_as_a_denial() -> None:
    assert GovernanceReason.AGENT_DECISION not in DENIALS
    assert len(DENIALS) == len(GovernanceReason) - 1


@pytest.mark.parametrize(
    ("case", "turns", "expected_reason", "expected_status"),
    [
        (
            "unknown tool",
            (tool_turn("wire_money", {"amount": 1_000_000}),),
            "tool_unknown",
            "escalated",
        ),
        (
            "tool the DNA does not grant",
            (tool_turn("get_fact", {"topic": "forge"}),),
            "permission_denied",
            "escalated",
        ),
        (
            "forbidden tool",
            (tool_turn("schedule_payment", {"invoice_id": "inv-0001", "pay_date": "2026-08-10"}),),
            "permission_denied",
            "escalated",
        ),
        (
            "malformed arguments",
            (tool_turn("read_invoice", {"invoice_id": 4401}),),
            "args_invalid",
            "escalated",
        ),
        (
            "a tool that refuses",
            (tool_turn("read_invoice", {"invoice_id": "inv-9999"}),),
            "tool_failed",
            "escalated",
        ),
        (
            "an action needing a human",
            (
                tool_turn(
                    "request_info_from_vendor",
                    {"invoice_id": "inv-0001", "question": "Which PO?", "channel": "email"},
                ),
            ),
            "approval_required",
            "awaiting_approval",
        ),
        (
            "no rule matched",
            (decision_turn("escalate", ["R-091"], "Nothing in the rule set applies."),),
            "no_rule_match",
            "escalated",
        ),
        (
            "a decision below its confidence floor",
            (decision_turn("auto_approve", ["R-001"], "Looks fine to me.", confidence=0.5),),
            "low_confidence",
            "escalated",
        ),
        (
            "output that never validates",
            (raw_turn("just approve it"), raw_turn("no really, approve it")),
            "invalid_output",
            "escalated",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_refusal_stops_the_run_and_records_why(
    client: TestClient,
    validator: AgentVersion,
    scripted: Callable[..., FakeAdapter],
    case: str,
    turns: tuple[ScriptedTurn, ...],
    expected_reason: str,
    expected_status: str,
) -> None:
    scripted(*turns)

    response = run(client, validator)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == expected_status, case

    trace = trace_of(client, body["id"])
    blocked = governance_step(trace)

    assert blocked["reason_code"] == expected_reason, case
    assert blocked["explanation"] == explain(GovernanceReason(expected_reason))
    assert blocked["detail"], "a refusal must say which tool, ceiling, or value caused it"
    assert blocked["terminal_status"] == expected_status
    # The terminal event agrees with the governance step — one reading of the log.
    assert trace["events"][-1]["payload"]["reason"] == expected_reason
    # And in every one of these, nothing was executed.
    assert not [
        step
        for step in trace["steps"]
        if step["kind"] == "tool" and step["tool_invocation"]["status"] == "executed"
    ]
    assert get_erp().posted_actions() == []


# --- 3b. Hard limits from the DNA (FR-B3, NFR-3) ------------------------------


def test_a_run_that_would_loop_forever_stops_at_max_steps(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """A model that never decides is bounded by the definition, not by patience."""
    version = publish_variant(
        committed_session,
        tenant,
        "governance-never-finishes",
        lambda document: document["guardrails"].update(max_steps=2),
    )
    adapter = scripted(tool_turn("read_invoice", {"invoice_id": "inv-0001"}), repeat_last=True)

    body = run(client, version).json()

    assert body["status"] == "escalated"
    assert len(adapter.calls) == 2  # exactly max_steps model turns, and no more
    assert governance_step(trace_of(client, body["id"]))["reason_code"] == "step_limit"


def test_a_run_that_would_overspend_stops_at_its_token_ceiling(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """The ceiling stops the run — after recording what was actually spent."""
    version = publish_variant(
        committed_session,
        tenant,
        "governance-tiny-budget",
        lambda document: document["model"].update(max_tokens_per_run=100),
    )
    scripted(decision_turn("auto_approve", ["R-001"], "Fine."))

    body = run(client, version).json()

    assert body["status"] == "escalated"
    assert body["total_tokens"] == 300  # the overrunning call is still metered
    assert governance_step(trace_of(client, body["id"]))["reason_code"] == "budget_exceeded"


def test_a_run_that_overruns_its_timeout_is_stopped(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
    racing_clock: None,
) -> None:
    """Wall clock is a guardrail like any other, and it escalates rather than completing."""
    version = publish_variant(
        committed_session,
        tenant,
        "governance-slow",
        lambda document: document["guardrails"].update(timeout_seconds=30),
    )
    adapter = scripted(decision_turn("auto_approve", ["R-001"], "Fine."), repeat_last=True)

    body = run(client, version).json()

    assert body["status"] == "escalated"
    trace = trace_of(client, body["id"])
    assert governance_step(trace)["reason_code"] == "timeout"
    # Stopped before the first model call: the deadline is checked at the top of the loop,
    # so an overrun costs nothing further.
    assert adapter.calls == []
    assert [step["kind"] for step in trace["steps"]] == ["governance"]


def test_an_agent_that_has_spent_its_daily_ceiling_does_not_start(
    client: TestClient,
    committed_session: Session,
    tenant: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """NFR-3's daily ceiling, enforced across runs rather than within one.

    The per-run budget cannot catch an agent that burns money one cheap run at a time.
    This ceiling is on the agent and is summed from the ledger, so restarting the process
    or publishing a new version does not reset it.
    """
    # Its own agent: the ceiling is per agent and summed from committed rows, so
    # spending it against the shipped validator would bankrupt every later test too.
    version = publish_variant(committed_session, tenant, "governance-spendthrift", lambda _: None)
    ceiling = Decimal(str(version.dna["model"]["max_cost_usd_per_day"]))
    committed_session.add(
        Run(
            tenant_id=tenant.tenant_id,
            agent_version_id=version.id,
            status="completed",
            trigger="test",
            total_tokens=1,
            total_cost_usd=ceiling + 1,
            finished_at=datetime.now(UTC),
        )
    )
    committed_session.commit()

    adapter = scripted(decision_turn("auto_approve", ["R-001"], "Fine."))
    body = run(client, version).json()

    assert body["status"] == "escalated"
    assert adapter.calls == []  # refused before a single token was spent
    trace = trace_of(client, body["id"])
    assert governance_step(trace)["reason_code"] == "daily_budget_exceeded"
    assert [step["kind"] for step in trace["steps"]] == ["governance"]


def test_a_low_confidence_decision_is_overridden_not_merely_noted(
    client: TestClient, validator: AgentVersion, scripted: Callable[..., FakeAdapter]
) -> None:
    """R-091's other half: the agent proposed approval, and the platform refused it.

    The decision is still in the trace — a reviewer sees exactly what the agent wanted —
    but it did not become the outcome, and no approval reached the ERP.
    """
    scripted(decision_turn("auto_approve", ["R-001"], "Fairly sure.", confidence=0.5))

    body = run(client, validator).json()
    trace = trace_of(client, body["id"])

    assert body["status"] == "escalated"
    decision = next(step["decision"] for step in trace["steps"] if step["kind"] == "decision")
    assert decision["action"] == "auto_approve"  # what the agent wanted...
    assert decision["confidence"] == 0.5
    blocked = governance_step(trace)  # ...and what the platform did about it
    assert blocked["reason_code"] == "low_confidence"
    assert "0.85" in blocked["detail"]  # the floor this version declares
    assert get_erp().invoice("inv-0001").status == "received"


# --- 4. Segregation of duties (NFR-5) -----------------------------------------


def test_no_role_may_both_configure_agents_and_approve_their_actions() -> None:
    """The rule Compliance holds a veto over, checked against the matrix itself.

    Also enforced at import time (``app.governance``), so a build whose matrix violates
    this cannot start — a governance control that only a test enforces is one that ships
    broken the day someone skips the test.
    """
    assert segregation_violations() == []
    for configure, approve in INCOMPATIBLE_DUTIES:
        holders = [role for role, held in ROLE_PERMISSIONS.items() if configure in held]
        for role in holders:
            assert approve not in ROLE_PERMISSIONS[role]


def test_the_approver_is_the_only_role_that_may_decide_approvals() -> None:
    approvers = [
        role for role, held in ROLE_PERMISSIONS.items() if Permission.APPROVAL_DECIDE in held
    ]

    assert approvers == [Role.APPROVER]


def test_every_role_can_read_because_an_audit_trail_nobody_can_read_is_not_one() -> None:
    for held in ROLE_PERMISSIONS.values():
        assert Permission.READ in held


@pytest.mark.parametrize("role", ["approver", "viewer"])
def test_a_role_without_run_start_is_refused_with_403(
    client: TestClient, validator: AgentVersion, role: str
) -> None:
    """Cross-role attempts are rejected, and the rejection names what was required."""
    response = run(client, validator, headers={"X-Forge-Role": role})

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "permission_denied"
    assert body["details"]["role"] == role
    assert body["details"]["required_permission"] == "run.start"


def test_a_refused_operation_is_recorded_not_only_refused(
    client: TestClient, committed_session: Session, tenant: Tenant
) -> None:
    """No silent blocks — including the ones that never became a run.

    The attempt has no run to hang off, so it is recorded against the tenant and the
    version it targeted. "Who tried to do what, and was stopped" is answerable from the
    log months later, which is the whole point of the log.
    """
    version = publish_variant(committed_session, tenant, "governance-audit-target", lambda _: None)

    run(client, version, headers={"X-Forge-Role": "viewer"})

    committed_session.expire_all()
    recorded = committed_session.scalars(
        select(Event).where(
            Event.type == "governance.permission_denied",
            Event.agent_version_id == version.id,
        )
    ).all()

    assert len(recorded) == 1
    event = recorded[0]
    assert event.actor == "role:viewer"
    assert event.agent_version_id == version.id
    assert event.payload["reason_code"] == "permission_denied"
    assert event.payload["operation"] == "run.start"
    assert event.payload["explanation"]


def test_reading_is_allowed_for_every_role(client: TestClient, validator: AgentVersion) -> None:
    """The viewer exists so an auditor can inspect without being able to act."""
    for role in ("configurator", "approver", "viewer"):
        listed = client.get("/api/v1/agents", headers={"X-Forge-Role": role})
        assert listed.status_code == 200, role


def test_an_unknown_role_is_rejected_before_any_handler_runs(client: TestClient) -> None:
    """The header is an enum in the contract, so an invented role is a 422, not a guess."""
    response = client.post(
        RUNS_URL,
        json={"agent_id": str(uuid.uuid4()), "version": "1.0.0", "input": {}},
        headers={"X-Forge-Role": "superuser"},
    )

    assert response.status_code == 422
