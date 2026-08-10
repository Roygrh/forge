"""The accounts-payable agents end to end, through the real HTTP surface.

These mirror cases from ``docs/01-discovery/06-eval-cases.md``. They are **not** the eval
suite — there is no runner and no publish gate until Phase 4.5 — but they assert the same
things a scored case will: the final action, the rule ids cited, and which tools were (and
were not) called.

Two deterministic model stand-ins are used, deliberately:

* Most tests run on the **shipped** configuration, with no dependency override at all —
  the same deterministic adapter a freshly composed stack uses (``app/llm/adapters/
  demo.py``). What they exercise is therefore the whole chain: ERP facts, the rules in the
  database, the tool gateway, and the decision. A test that stubbed the model's answer
  could pass while the rules said something else entirely.
* Where the point is that the platform refuses something the model asked for, a scripted
  :class:`FakeAdapter` puts the exact bad call in the model's mouth. There is no other
  honest way to test a refusal of a call a well-behaved planner would never make.

Both are offline and byte-for-byte reproducible.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.erp import get_erp, reset_erp
from app.llm import FakeAdapter, LlmGateway, ScriptedTurn, tool_turn
from app.models import AgentVersion, Rule
from scripts.seed import seed_ap_agents, seed_rules, seed_tenant

RUNS_URL = "/api/v1/runs"
HEADERS = {"X-Forge-Role": "configurator"}


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    """App client bound to the test database (module-scoped: one event loop)."""
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def agents(committed_session: Session) -> dict[str, AgentVersion]:
    """The seeded tenant, rule set, and three published AP agents.

    Exactly what ``python -m scripts.seed`` installs — so a failure here is a failure of
    the shipped artefact, not of a fixture written to make the test pass.
    """
    tenant, _ = seed_tenant(committed_session)
    seed_rules(committed_session, tenant)
    published = seed_ap_agents(committed_session, tenant)
    committed_session.commit()
    return {slug: version for slug, (version, _) in published.items()}


@pytest.fixture(autouse=True)
def fresh_erp() -> Iterator[None]:
    """Rebuild MeridianERP before each test.

    The simulated ERP is stateful on purpose (an approved invoice stays approved), so
    without this the order tests happen to run in would decide their outcomes.
    """
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


# --- Helpers ------------------------------------------------------------------


def run_agent(
    client: TestClient, version: AgentVersion, run_input: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(
        RUNS_URL,
        json={
            "agent_id": str(version.agent_id),
            "version": version.version,
            "input": run_input,
        },
        headers=HEADERS,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def trace_of(client: TestClient, run: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"{RUNS_URL}/{run['id']}/trace", headers=HEADERS)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def decision_in(trace: dict[str, Any]) -> dict[str, Any]:
    decisions = [step["decision"] for step in trace["steps"] if step["kind"] == "decision"]
    assert len(decisions) == 1, f"expected exactly one decision, got {len(decisions)}"
    found: dict[str, Any] = decisions[0]
    return found


def tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [step["tool_invocation"] for step in trace["steps"] if step["kind"] == "tool"]


def called_tools(trace: dict[str, Any]) -> list[str]:
    return [call["tool_ref"].split("@")[0] for call in tool_calls(trace)]


def governance_in(trace: dict[str, Any]) -> dict[str, Any]:
    """The one governance step a stopped run carries."""
    blocks = [step["governance"] for step in trace["steps"] if step["kind"] == "governance"]
    assert len(blocks) == 1, f"expected exactly one governance step, got {len(blocks)}"
    found: dict[str, Any] = blocks[0]
    return found


def validate(
    client: TestClient, agents: dict[str, AgentVersion], invoice_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the invoice validator over one invoice; return the run and its trace."""
    run = run_agent(client, agents["invoice-validator"], {"invoice_id": invoice_id})
    return run, trace_of(client, run)


# --- E-01: a routine invoice flows without a human ----------------------------


def test_e01_a_trusted_vendor_in_tolerance_is_auto_approved(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """Grainger, valid PO, 0.8% variance: auto_approve citing R-001 and R-010.

    The whole chain, on the shipped configuration: the ERP's facts, the rules loaded from
    the database, the tool gateway, and a decision that cites what it applied.
    """
    run, trace = validate(client, agents, "inv-0001")

    assert run["status"] == "completed"

    decision = decision_in(trace)
    assert decision["action"] == "auto_approve"
    assert {"R-001", "R-010"} <= set(decision["citations"])
    assert "R-001" in decision["reasoning"]

    # The evidence it gathered first, and the approval it was entitled to post.
    assert called_tools(trace) == [
        "meridian-erp-read-invoice",
        "meridian-erp-get-vendor",
        "meridian-erp-match-po",
        "meridian-erp-get-receipts",
        "meridian-ap-rules-query",
        "meridian-erp-approve-invoice",
    ]
    assert all(call["status"] == "executed" for call in tool_calls(trace))

    # The rule lookup is in the trace with its evidence, so the decision is checkable
    # against the facts it was made from rather than merely asserted.
    rules_result = tool_calls(trace)[4]["result"]
    assert rules_result["ruleset_version"] == "1.0.0"
    assert rules_result["facts"]["match.price_variance_pct"] == "0.80"
    assert [rule["rule_id"] for rule in rules_result["applicable_rules"]] == ["R-001", "R-010"]

    # ...and MeridianERP agrees the approval really happened.
    assert get_erp().invoice("inv-0001").status == "approved"
    assert [action.kind for action in get_erp().posted_actions()] == ["approval"]


# --- E-09: a threshold overrides trust ----------------------------------------


def test_e09_an_invoice_over_ten_thousand_escalates(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """$12,000 from a trusted vendor with a perfect match: R-020 wins over R-001.

    Two rules fire with different actions, so R-090's tie-break decides — and the
    conflict, not just its outcome, is cited.
    """
    run, trace = validate(client, agents, "inv-0009")

    assert run["status"] == "escalated"

    decision = decision_in(trace)
    assert decision["action"] == "escalate"
    assert "R-020" in decision["citations"]
    assert "R-090" in decision["citations"]  # a conflict was resolved, and it says so
    assert "R-001" in decision["citations"]  # ...including the rule that was overridden

    assert "meridian-erp-approve-invoice" not in called_tools(trace)
    assert get_erp().invoice("inv-0009").status == "received"
    assert get_erp().posted_actions() == []


# --- E-14: a duplicate is a hard stop -----------------------------------------


def test_e14_a_duplicate_invoice_number_blocks_and_never_approves(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """INV-4471 already exists for this vendor: block_escalate, and no approval.

    The cross-cutting assert of the eval suite — approve_invoice is never invoked without
    an auto_approve outcome — checked from both sides: no invocation in the trace, and
    nothing posted in the ERP.
    """
    run, trace = validate(client, agents, "inv-0015")

    assert run["status"] == "escalated"

    decision = decision_in(trace)
    assert decision["action"] == "block_escalate"
    assert "R-040" in decision["citations"]

    assert "meridian-erp-approve-invoice" not in called_tools(trace)
    assert get_erp().invoice("inv-0015").status == "received"
    assert get_erp().posted_actions() == []


# --- E-20 / R-091: no rule matches --------------------------------------------


def test_no_rule_match_escalates_and_says_so(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """The fail-closed default: nothing applies, so a human decides — never a guess."""
    run, trace = validate(client, agents, "inv-0021")

    assert run["status"] == "escalated"

    decision = decision_in(trace)
    assert decision["action"] == "escalate"
    assert decision["citations"] == ["R-091"]
    assert "No rule" in decision["reasoning"]

    # The platform labels the stop, rather than leaving it as a generic escalation:
    # citing R-091 *is* the fail-closed default firing, and the trace says so.
    blocked = governance_in(trace)
    assert blocked["reason_code"] == "no_rule_match"
    assert "No governed rule covered this case" in blocked["explanation"]
    assert trace["events"][-1]["payload"]["reason"] == "no_rule_match"

    rules_result = tool_calls(trace)[-1]["result"]
    assert rules_result["applicable_rules"] == []
    assert rules_result["rules_evaluated"] == 22
    assert "meridian-erp-approve-invoice" not in called_tools(trace)


# --- FR-E2: a requires_approval tool parks the run ----------------------------


def test_a_requires_approval_tool_parks_the_run_without_executing(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """The comms agent's only tool needs a human, so the run stops in waiting.

    Not an escalation and not a completion: ``awaiting_approval`` is the state the queue
    is built on, and nothing was sent. What the queue then does with it —  release it,
    refuse it, or let it expire into a cancellation — is ``tests/test_approvals.py``.
    """
    run = run_agent(
        client,
        agents["invoice-comms"],
        {"invoice_id": "inv-0005", "question": "Which PO covers this overage?"},
    )
    trace = trace_of(client, run)

    assert run["status"] == "awaiting_approval"

    calls = tool_calls(trace)
    assert len(calls) == 1
    assert calls[0]["tool_ref"] == "meridian-erp-request-info-from-vendor@1.0.0"
    assert calls[0]["autonomy"] == "requires_approval"
    assert calls[0]["status"] == "validated"  # checked, then held
    assert calls[0]["result"] is None  # ...and it did not run
    assert calls[0]["args"]["question"] == "Which PO covers this overage?"

    # No decision was reached: the agent needed an action it was not allowed to take.
    # The approval step between the parked call and the block is the queue entry itself —
    # written in the same breath, so what a person sees and what the run is waiting on
    # cannot get out of step.
    assert [step["kind"] for step in trace["steps"]] == [
        "reason",
        "tool",
        "approval",
        "governance",
    ]
    parked = trace["steps"][2]["approval"]
    assert parked["status"] == "pending"
    assert parked["args"]["question"] == "Which PO covers this overage?"
    assert parked["decided_by"] is None
    assert parked["expires_at"]  # a server-side deadline exists from the moment it parks

    held = trace["steps"][3]["governance"]
    assert held["reason_code"] == "approval_required"
    assert held["terminal_status"] == "awaiting_approval"
    assert "requires a person" in held["explanation"]
    terminal = trace["events"][-1]
    assert terminal["type"] == "run.awaiting_approval"
    assert terminal["payload"]["reason"] == "approval_required"

    # And MeridianERP received nothing.
    assert get_erp().posted_actions() == []


# --- Rules are data: an edit changes behaviour with no code change ------------


def test_editing_a_rule_changes_the_decision_with_no_code_change(
    client: TestClient, agents: dict[str, AgentVersion], committed_session: Session
) -> None:
    """The claim of :mod:`app.rules`, demonstrated end to end.

    inv-0001 is $4,032 and auto-approves. Drop R-020's threshold from $10,000 to $3,000
    in the database — one ``UPDATE``, no deploy, no restart, no import reloaded — and the
    same invoice escalates instead, citing the rule that changed.
    """
    row = committed_session.scalar(select(Rule).where(Rule.rule_id == "R-020"))
    assert row is not None
    original = row.clauses

    before, _ = validate(client, agents, "inv-0001")
    assert before["status"] == "completed"

    # MeridianERP keeps the approval that run posted, and it will not approve the same
    # invoice twice. Rewind it so the next run meets the same invoice, not the same rule
    # against a different ERP state.
    reset_erp()

    try:
        lowered = [dict(clause) for clause in original]
        lowered[0] = {**lowered[0], "when": {**lowered[0]["when"], "value": 3000}}
        row.clauses = lowered
        committed_session.commit()

        run, trace = validate(client, agents, "inv-0001")

        decision = decision_in(trace)
        assert run["status"] == "escalated"
        assert decision["action"] == "escalate"
        assert "R-020" in decision["citations"]
        assert "meridian-erp-approve-invoice" not in called_tools(trace)
    finally:
        row.clauses = original
        committed_session.commit()
        reset_erp()

    # ...and putting the threshold back restores the original behaviour.
    after, _ = validate(client, agents, "inv-0001")
    assert after["status"] == "completed"


# --- Least privilege, with the bad call put in the model's mouth --------------


def test_the_validator_may_not_schedule_a_payment(
    client: TestClient, agents: dict[str, AgentVersion], scripted: Callable[..., FakeAdapter]
) -> None:
    """`forbidden` is an explicit denial, recorded so a reviewer sees it was refused.

    Segregation of duties: the agent that validates an invoice is not the agent that
    pays it, and the gateway enforces that rather than the prompt.
    """
    scripted(tool_turn("schedule_payment", {"invoice_id": "inv-0001", "pay_date": "2026-08-10"}))

    run, trace = validate(client, agents, "inv-0001")

    assert run["status"] == "escalated"

    invocation = tool_calls(trace)[0]
    assert invocation["status"] == "denied"
    assert "forbidden" in invocation["error"]
    assert invocation["result"] is None
    assert invocation["reason_code"] == "permission_denied"
    blocked = governance_in(trace)
    assert blocked["reason_code"] == "permission_denied"
    assert trace["events"][-1]["payload"]["reason"] == "permission_denied"
    assert get_erp().posted_actions() == []


def test_an_approval_above_the_declared_ceiling_is_refused(
    client: TestClient, agents: dict[str, AgentVersion], scripted: Callable[..., FakeAdapter]
) -> None:
    """The DNA grants approve_invoice with max_amount_usd: 10000. $12,000 is refused.

    The ceiling is a governance statement a reviewer can read in the published
    definition, enforced at the boundary — not a sentence in a prompt the model may
    ignore.
    """
    scripted(
        tool_turn(
            "approve_invoice",
            {"invoice_id": "inv-0009", "amount_usd": "12000.00", "cited_rule_ids": ["R-001"]},
        )
    )

    run, trace = validate(client, agents, "inv-0009")

    assert run["status"] == "escalated"

    invocation = tool_calls(trace)[0]
    assert invocation["status"] == "blocked"
    assert "max_amount_usd" in invocation["error"]
    assert get_erp().invoice("inv-0009").status == "received"
    assert get_erp().posted_actions() == []


def test_an_approval_for_the_wrong_amount_is_refused(
    client: TestClient, agents: dict[str, AgentVersion], scripted: Callable[..., FakeAdapter]
) -> None:
    """An approval is for the invoice as recorded, never for a number the agent chose."""
    scripted(
        tool_turn(
            "approve_invoice",
            {"invoice_id": "inv-0001", "amount_usd": "40.32", "cited_rule_ids": ["R-001"]},
        )
    )

    run, trace = validate(client, agents, "inv-0001")

    assert run["status"] == "escalated"
    assert "does not match invoice" in tool_calls(trace)[0]["error"]
    assert get_erp().invoice("inv-0001").status == "received"


# --- Intake ------------------------------------------------------------------


def test_the_intake_agent_normalises_an_invoice_and_can_do_nothing_else(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """Least privilege at its plainest: intake reads, structures, and hands on."""
    run = run_agent(client, agents["invoice-intake"], {"invoice_id": "inv-0001"})
    trace = trace_of(client, run)

    assert run["status"] == "completed"
    assert called_tools(trace) == ["meridian-erp-read-invoice"]

    decision = decision_in(trace)
    assert decision["action"] == "auto_approve"
    # R-092, not R-091: a clean invoice is not a no-rule-match, and citing the
    # fail-closed default for one would make the platform escalate it.
    assert decision["citations"] == ["R-092"]
    assert decision["confidence"] == 1.0

    normalised = decision["output"]["normalised_invoice"]
    assert normalised["number"] == "INV-4401"
    assert normalised["vendor_id"] == "V-1001"
    assert normalised["amount_usd"] == "4032.00"
    assert normalised["po_number"] == "PO-8801"
    assert decision["output"]["missing_fields"] == []

    # It has no way to act on what it read: nothing was posted to the ERP.
    assert get_erp().posted_actions() == []


# --- The shipped stack answers for itself -------------------------------------


def test_the_seeded_stack_runs_every_agent_with_no_override(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """`docker compose up` + seed + POST /runs, for all three agents.

    Every other test could pass while the shipped configuration was unable to run the
    shipped agents. This one is the demo itself.
    """
    intake = run_agent(client, agents["invoice-intake"], {"invoice_id": "inv-0003"})
    validator = run_agent(client, agents["invoice-validator"], {"invoice_id": "inv-0003"})
    comms = run_agent(client, agents["invoice-comms"], {"invoice_id": "inv-0003"})

    assert intake["status"] == "completed"
    assert validator["status"] == "completed"
    assert comms["status"] == "awaiting_approval"

    decision = decision_in(trace_of(client, validator))
    assert decision["action"] == "auto_approve"
    assert "R-003" in decision["citations"]

    # Every run stayed inside the budgets its own DNA declared (FR-B3).
    for run in (intake, validator, comms):
        assert run["total_tokens"] is not None
        assert float(run["total_cost_usd"]) > 0


# --- Fail-closed on a record that does not exist ------------------------------


def test_an_invoice_that_does_not_exist_escalates_without_deciding(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """No invoice, no facts, no rules — and therefore no decision (golden rule 3)."""
    run, trace = validate(client, agents, "inv-9999")

    assert run["status"] == "escalated"
    assert tool_calls(trace)[0]["status"] == "blocked"
    assert "no invoice 'inv-9999'" in tool_calls(trace)[0]["error"]
    assert [step["kind"] for step in trace["steps"]] == [
        "reason",
        "tool",
        "governance",
    ]
    assert governance_in(trace)["reason_code"] == "tool_failed"


def test_the_erp_refuses_a_second_approval_of_the_same_invoice(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """Two duplicate payments cost Meridian $18,000 last year (01-client-profile.md).

    The rules stop a duplicate *invoice*; this is the other half — the system of record
    refuses a second approval of an invoice it has already approved, so a replayed run
    cannot pay twice even if every rule fired the same way.
    """
    first, _ = validate(client, agents, "inv-0001")
    assert first["status"] == "completed"

    second, trace = validate(client, agents, "inv-0001")

    assert second["status"] == "escalated"
    invocation = tool_calls(trace)[-1]
    assert invocation["tool_ref"].startswith("meridian-erp-approve-invoice")
    assert invocation["status"] == "blocked"
    assert "only a received invoice can be approved" in invocation["error"]
    # Exactly one approval reached MeridianERP, from the first run.
    assert [action.kind for action in get_erp().posted_actions()] == ["approval"]
