"""The tool gateway: least privilege and fail-closed refusals (FR-C1, FR-C3, FR-C5)."""

import json

import pytest

from app.dna import Dna
from app.tools import GET_FACT_NAME, GET_FACT_REF, ToolGateway
from scripts.seed import SKELETON_DNA


def _dna(**overrides: object) -> Dna:
    """Build a DNA read view from the skeleton, with tool grants overridden."""
    document = json.loads(json.dumps(SKELETON_DNA))
    document.update(overrides)
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


def test_requires_approval_does_not_execute_in_this_phase(gateway: ToolGateway) -> None:
    """An approval the platform cannot obtain never becomes an execution (FR-E3)."""
    dna = _dna(tools=[{"ref": GET_FACT_REF, "autonomy": "requires_approval"}])

    outcome = gateway.invoke(name=GET_FACT_NAME, arguments={"topic": "forge"}, dna=dna)

    assert outcome.status == "blocked"
    assert "requires human approval" in (outcome.error or "")


def test_forbidden_tools_are_never_shown_to_the_model(gateway: ToolGateway) -> None:
    """The model is not offered a door it may not open."""
    dna = _dna(tools=[{"ref": GET_FACT_REF, "autonomy": "forbidden"}])

    assert gateway.granted_tools(dna) == []
    assert [tool.ref for tool in gateway.granted_tools(_dna())] == [GET_FACT_REF]
