"""Structured model output: schema-validated, one bounded retry, then escalate (ADR-006).

The model may end a turn in exactly two ways — ask for a tool, or decide. A tool call is
validated by the tool gateway against that tool's input schema; a decision is validated
here against :data:`DECISION_SCHEMA`. Anything else is malformed, and malformed output
never becomes an action.

On a violation the runtime performs **exactly one** retry, feeding the validation error
back as corrective context (:func:`correction_message`). One, not zero and not N: a
single corrective round fixes most schema violations, while unbounded retries burn
budget hiding a systematic prompt/schema mismatch a human should see.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# The decision vocabulary is platform-level and shared with the rules layer and the
# adapters, so it lives in a dependency-free module (see app/actions.py) and is
# re-exported here, where the runtime's readers expect to find it.
from app.actions import (
    ACTION_RESTRICTIVENESS,
    DECISION_ACTIONS,
    STATUS_FOR_ACTION,
    DecisionAction,
    most_restrictive,
)
from app.dna.model import Guardrails
from app.governance import GovernanceReason
from app.llm.contract import CompletionResult, Message, ToolCall

__all__ = [
    "ACTION_RESTRICTIVENESS",
    "DECISION_ACTIONS",
    "DECISION_SCHEMA",
    "MAX_OUTPUT_RETRIES",
    "NO_RULE_MATCH_RULE",
    "RULE_ID_PATTERN",
    "STATUS_FOR_ACTION",
    "Decision",
    "DecisionAction",
    "OutputValidationError",
    "correction_message",
    "interpret",
    "most_restrictive",
    "review_decision",
]

#: Exactly one corrective round. The count is the contract, so it lives next to the
#: schema it protects rather than inside the loop.
MAX_OUTPUT_RETRIES = 1

#: The governed rule that *is* "no rule matched" (04-tacit-rules.md). A decision citing
#: it is the fail-closed default having fired, and the runtime labels it as such.
NO_RULE_MATCH_RULE = "R-091"

#: R-xxx, the citation format of the governed rule set (R-001 … R-092).
RULE_ID_PATTERN = r"^R-\d{3}$"

#: The schema the model is held to for a final decision. ``citations`` has
#: ``minItems: 1`` because ``guardrails.require_citations`` is const-locked true in the
#: DNA schema (R-092): a decision without citations is rejected, not merely logged.
DECISION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Forge agent decision",
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "citations", "reasoning", "confidence"],
    "properties": {
        "action": {
            "enum": list(DECISION_ACTIONS),
            "description": "Exactly one final action.",
        },
        "citations": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "pattern": RULE_ID_PATTERN},
            "description": "Rule IDs applied, e.g. R-001. Required (R-092).",
        },
        "reasoning": {
            "type": "string",
            "minLength": 1,
            "description": "Why this action follows from those rules.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": (
                "How confident the agent is in this decision, 0–1. Required: R-091 makes "
                "low confidence a fail-closed condition, and a threshold cannot be "
                "enforced against a number the agent was free not to state. Below the "
                "floor its DNA declares, the runtime overrides the action to an "
                "escalation whatever was proposed."
            ),
        },
        "output": {
            "type": "object",
            "description": (
                "Optional structured result for agents whose job is extraction rather "
                "than adjudication — the normalised invoice from intake, say. The "
                "governed part of a decision is always the action and its citations; "
                "this is the agent-specific payload beside them."
            ),
        },
    },
}


class Decision(BaseModel):
    """A validated final decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: DecisionAction
    citations: list[str] = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    output: dict[str, Any] | None = None

    @property
    def run_status(self) -> str:
        """The terminal run status this action implies."""
        return STATUS_FOR_ACTION[self.action]

    def as_payload(self) -> dict[str, Any]:
        """The JSON form persisted on the run step and in the ``decision.made`` event.

        ``exclude_none`` keeps a decision that carries no structured payload exactly the
        shape it has always been — an optional field should not appear as a null in
        every historical record.
        """
        return self.model_dump(exclude_none=True)


def review_decision(
    decision: Decision, guardrails: Guardrails
) -> tuple[GovernanceReason, str] | None:
    """Judge a well-formed decision against the fail-closed doctrine (R-091).

    A decision can satisfy every schema and still not be allowed to stand. Two cases,
    checked in order of severity:

    * **Low confidence.** The agent stated a confidence below the floor its own DNA
      declares. Whatever it proposed — including ``auto_approve`` — the platform
      overrides it to an escalation. This is the half of R-091 that a schema cannot
      express, and it is why ``confidence`` is a required field.
    * **No rule matched.** The decision cites R-091 itself, the fail-closed default. The
      outcome (escalate) is already right; what this adds is the *reason code*, so the
      trace says "no rule covered this" rather than the generic "the agent decided".

    Returns ``None`` when the decision stands on its own. Nothing here re-decides the
    business question — it only refuses to let one through.
    """
    if decision.confidence < guardrails.min_decision_confidence:
        return (
            GovernanceReason.LOW_CONFIDENCE,
            f"decision confidence {decision.confidence} is below the "
            f"guardrails.min_decision_confidence={guardrails.min_decision_confidence} "
            f"this version declares; the proposed action {decision.action!r} was "
            "overridden and the run escalated (R-091)",
        )

    if NO_RULE_MATCH_RULE in decision.citations:
        return (
            GovernanceReason.NO_RULE_MATCH,
            f"the decision cites {NO_RULE_MATCH_RULE}, the fail-closed default: no "
            "governed rule covered this case, so it goes to a human rather than being "
            "guessed at",
        )

    return None


class OutputValidationError(Exception):
    """Model output did not satisfy the response schema."""

    def __init__(self, errors: list[str], raw: str | None) -> None:
        self.errors = errors
        self.raw = raw
        super().__init__("; ".join(errors))


def interpret(result: CompletionResult) -> ToolCall | Decision:
    """Turn one model result into a tool call or a validated decision.

    Raises :class:`OutputValidationError` on anything else — no content, unparseable
    JSON, or a decision that violates :data:`DECISION_SCHEMA`.
    """
    if result.tool_call is not None:
        # Arguments are deliberately *not* checked here: the tool gateway owns that,
        # against the tool's own schema, so there is one place that decides.
        return result.tool_call

    if result.content is None or not result.content.strip():
        raise OutputValidationError(
            ["the model returned neither a tool call nor any content"], result.content
        )

    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError as exc:
        raise OutputValidationError(
            [f"output is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"],
            result.content,
        ) from exc

    if not isinstance(payload, dict):
        raise OutputValidationError(
            [f"output must be a JSON object, got {type(payload).__name__}"], result.content
        )

    try:
        return Decision.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'/'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
            for error in exc.errors()
        ]
        raise OutputValidationError(errors, result.content) from exc


def correction_message(error: OutputValidationError) -> Message:
    """The single corrective turn appended before the one permitted retry.

    Feeds the validation error back verbatim: the model is told exactly what it broke,
    and told that another malformed answer ends in escalation rather than in a third try.
    """
    problems = "\n".join(f"- {item}" for item in error.errors)
    return Message(
        role="user",
        content=(
            "Your previous response did not satisfy the required output schema:\n"
            f"{problems}\n\n"
            "Reply with either a tool call, or a JSON object with exactly these fields: "
            f"action (one of {', '.join(DECISION_ACTIONS)}), citations (a non-empty list "
            "of rule IDs like R-001), reasoning, and confidence (a number from 0 to 1). "
            "Do not add any other text. "
            "This is the only correction attempt; a second invalid response escalates "
            "the run to a human."
        ),
    )
