"""Structured output validation (ADR-006): what becomes an action, and what cannot."""

import json
from decimal import Decimal

import pytest

from app.llm.contract import CompletionResult, ToolCall, Usage
from app.runtime.output import (
    Decision,
    OutputValidationError,
    correction_message,
    interpret,
)


def _result(content: str | None = None, tool_call: ToolCall | None = None) -> CompletionResult:
    return CompletionResult(
        provider="fake",
        model_id="fake-scripted-1",
        content=content,
        tool_call=tool_call,
        usage=Usage(input_tokens=1, output_tokens=1, cost_usd=Decimal("0")),
    )


def test_a_tool_call_passes_through_unvalidated() -> None:
    """Argument validation belongs to the tool gateway, against the tool's own schema."""
    call = ToolCall(name="get_fact", arguments={"topic": "forge"})

    assert interpret(_result(tool_call=call)) == call


def test_a_well_formed_decision_is_returned_typed() -> None:
    payload = {
        "action": "auto_approve",
        "citations": ["R-000"],
        "reasoning": "because",
        "confidence": 0.9,
    }

    decision = interpret(_result(json.dumps(payload)))

    assert isinstance(decision, Decision)
    assert decision.action == "auto_approve"
    assert decision.citations == ["R-000"]
    assert decision.confidence == 0.9
    assert decision.run_status == "completed"


def test_an_escalating_decision_ends_the_run_escalated() -> None:
    """A decided escalation is a valid outcome, not a malformed one."""
    payload = {
        "action": "escalate",
        "citations": ["R-091"],
        "reasoning": "no rule matched",
        "confidence": 1.0,
    }

    decision = interpret(_result(json.dumps(payload)))

    assert isinstance(decision, Decision)
    assert decision.run_status == "escalated"


@pytest.mark.parametrize(
    ("content", "because"),
    [
        ("not json at all", "unparseable"),
        ('"a bare string"', "not an object"),
        ('{"action": "auto_approve", "reasoning": "x"}', "citations missing"),
        ('{"action": "auto_approve", "citations": [], "reasoning": "x"}', "citations empty"),
        ('{"action": "ship_it", "citations": ["R-000"], "reasoning": "x"}', "unknown action"),
        ('{"action": "auto_approve", "citations": ["R-000"], "reasoning": ""}', "no reasoning"),
        (
            '{"action": "auto_approve", "citations": ["R-000"], "reasoning": "x"}',
            "confidence missing",
        ),
        (
            '{"action": "auto_approve", "citations": ["R-000"], "reasoning": "x",'
            ' "confidence": 1.4}',
            "confidence out of range",
        ),
    ],
)
def test_malformed_output_never_becomes_a_decision(content: str, because: str) -> None:
    """Every one of these is an escalation candidate, never a best-effort action."""
    with pytest.raises(OutputValidationError):
        interpret(_result(content))


def test_an_empty_response_is_invalid() -> None:
    with pytest.raises(OutputValidationError, match="neither a tool call nor any content"):
        interpret(_result(None))


def test_a_decision_without_citations_is_rejected_not_logged() -> None:
    """R-092 is structural: the citation requirement is in the type, not in a warning."""
    with pytest.raises(OutputValidationError) as excinfo:
        interpret(
            _result(
                '{"action": "auto_approve", "citations": [], "reasoning": "x", "confidence": 1}'
            )
        )

    assert any("citations" in error for error in excinfo.value.errors)


def test_the_correction_turn_feeds_the_violation_back() -> None:
    """The retry is corrective: the model is told exactly what it broke, once."""
    with pytest.raises(OutputValidationError) as excinfo:
        interpret(_result("}{"))

    message = correction_message(excinfo.value)

    assert message.role == "user"
    assert "did not satisfy the required output schema" in message.content
    assert "only correction attempt" in message.content
