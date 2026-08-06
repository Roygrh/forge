"""The tool gateway: least privilege and fail-closed refusals (FR-C1, FR-C3, FR-C5)."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from app.dna import Dna, load_agent_dna
from app.tools import APPROVE_INVOICE_REF, GET_FACT_NAME, GET_FACT_REF, ToolGateway
from tests.skeleton import SKELETON_DNA


def _dna(**overrides: object) -> Dna:
    """Build a DNA read view from the skeleton, with tool grants overridden."""
    document = json.loads(json.dumps(SKELETON_DNA))
    document.update(overrides)
    return Dna.model_validate(document)


def _validator_dna(mutate: Callable[[dict[str, Any]], None] | None = None) -> Dna:
    """The shipped invoice-validator definition, optionally tweaked."""
    document = load_agent_dna("invoice-validator")
    if mutate is not None:
        mutate(document)
    return Dna.model_validate(document)


@pytest.fixture
def gateway() -> ToolGateway:
    return ToolGateway()


def test_a_granted_tool_with_valid_arguments_executes(gateway: ToolGateway) -> None:
    outcome = gateway.invoke(name=GET_FACT_NAME, arguments={"topic": "forge"}, dna=_dna())

    assert outcome.executed
    assert outcome.status == "executed"
    assert outcome.autonomy == "autonomous"
    assert outcome.result is not None
    assert outcome.result["topic"] == "forge"


def test_an_unknown_tool_is_blocked_and_recorded(gateway: ToolGateway) -> None:
    """The model asking for something that does not exist is data, not a crash."""
    outcome = gateway.invoke(name="wire_money", arguments={"amount": 1}, dna=_dna())

    assert not outcome.executed
    assert outcome.status == "blocked"
    assert outcome.autonomy is None
    assert "unknown tool" in (outcome.error or "")
    # The attempt is fully described, so the recorder can persist what was tried.
    assert outcome.arguments == {"amount": 1}


def test_invalid_arguments_are_blocked_before_the_handler_runs(gateway: ToolGateway) -> None:
    outcome = gateway.invoke(name=GET_FACT_NAME, arguments={"topic": "nonsense"}, dna=_dna())

    assert outcome.status == "blocked"
    assert "invalid arguments" in (outcome.error or "")
    assert outcome.result is None


def test_a_missing_argument_is_blocked(gateway: ToolGateway) -> None:
    outcome = gateway.invoke(name=GET_FACT_NAME, arguments={}, dna=_dna())

    assert outcome.status == "blocked"


def test_a_registered_tool_the_dna_does_not_grant_does_not_exist(gateway: ToolGateway) -> None:
    """Least privilege: absence from the DNA is a refusal, not a default-allow."""
    outcome = gateway.invoke(name=GET_FACT_NAME, arguments={"topic": "forge"}, dna=_dna(tools=[]))

    assert outcome.status == "blocked"
    assert "not granted" in (outcome.error or "")


def test_a_forbidden_grant_is_denied_not_merely_blocked(gateway: ToolGateway) -> None:
    """`forbidden` is recorded distinctly so a reviewer sees an explicit denial."""
    dna = _dna(tools=[{"ref": GET_FACT_REF, "autonomy": "forbidden"}])

    outcome = gateway.invoke(name=GET_FACT_NAME, arguments={"topic": "forge"}, dna=dna)

    assert outcome.status == "denied"
    assert not outcome.executed


def test_forbidden_tools_are_never_shown_to_the_model(gateway: ToolGateway) -> None:
    """The model is not offered a door it may not open."""
    dna = _dna(tools=[{"ref": GET_FACT_REF, "autonomy": "forbidden"}])

    assert gateway.granted_tools(dna) == []
    assert [tool.ref for tool in gateway.granted_tools(_dna())] == [GET_FACT_REF]


# --- requires_approval: validated, parked, never executed ----------------------


def test_requires_approval_is_validated_and_parked_not_executed(gateway: ToolGateway) -> None:
    """FR-E2: the call is checked, then held for a human. Nothing runs."""
    outcome = gateway.invoke(
        name="request_info_from_vendor",
        arguments={"invoice_id": "inv-0001", "question": "Which PO?", "channel": "email"},
        dna=_validator_dna(),
    )

    assert outcome.status == "validated"
    assert outcome.pending_approval
    assert not outcome.executed
    assert outcome.result is None
    assert outcome.autonomy == "requires_approval"


def test_a_parked_call_is_still_argument_checked_first(gateway: ToolGateway) -> None:
    """A human is never asked to approve a call that was malformed anyway."""
    outcome = gateway.invoke(
        name="request_info_from_vendor",
        arguments={"invoice_id": "inv-0001", "channel": "carrier-pigeon"},
        dna=_validator_dna(),
    )

    assert outcome.status == "blocked"
    assert "invalid arguments" in (outcome.error or "")


# --- Per-agent tool configuration ---------------------------------------------


def test_a_grants_config_cap_is_enforced_at_the_gateway(gateway: ToolGateway) -> None:
    """The DNA declares what this agent may approve; the boundary enforces it.

    inv-0009 is $12,000 and the shipped validator is granted approve_invoice with
    ``max_amount_usd: 10000``, so the tool refuses — the ceiling is a governance
    statement a reviewer can read in the definition, not a promise in a prompt.
    """
    outcome = gateway.invoke(
        name="approve_invoice",
        arguments={
            "invoice_id": "inv-0009",
            "amount_usd": "12000.00",
            "cited_rule_ids": ["R-001"],
        },
        dna=_validator_dna(),
    )

    assert outcome.status == "blocked"
    assert "max_amount_usd" in (outcome.error or "")
    assert outcome.result is None


def test_config_the_tool_cannot_honour_refuses_the_call(gateway: ToolGateway) -> None:
    """A definition with unhonourable config is refused, never run with it ignored."""

    def bad_config(document: dict[str, Any]) -> None:
        for grant in document["tools"]:
            if grant["ref"] == APPROVE_INVOICE_REF:
                grant["config"] = {"max_amount_usd": 10000, "skip_checks": True}

    outcome = gateway.invoke(
        name="approve_invoice",
        arguments={"invoice_id": "inv-0001", "amount_usd": "4032.00", "cited_rule_ids": ["R-001"]},
        dna=_validator_dna(bad_config),
    )

    assert outcome.status == "blocked"
    assert "invalid config" in (outcome.error or "")


def test_a_tools_own_refusal_is_recorded_not_raised(gateway: ToolGateway) -> None:
    """An unknown ERP record is an anticipated refusal with its reason intact."""
    outcome = gateway.invoke(
        name="read_invoice", arguments={"invoice_id": "inv-9999"}, dna=_validator_dna()
    )

    assert outcome.status == "blocked"
    assert "no invoice 'inv-9999'" in (outcome.error or "")
