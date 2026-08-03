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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm.contract import CompletionResult, Message, ToolCall

#: Exactly one corrective round. The count is the contract, so it lives next to the
#: schema it protects rather than inside the loop.
MAX_OUTPUT_RETRIES = 1

#: The decision vocabulary is platform-level, not per-agent: the same four actions
#: appear in the API contract (openapi.yaml ``RunStep.decision``), the eval cases, and
#: the tacit rule set. An agent chooses among them; it does not invent its own.
DecisionAction = Literal["auto_approve", "escalate", "block_escalate", "priority_queue"]
DECISION_ACTIONS: tuple[str, ...] = ("auto_approve", "escalate", "block_escalate", "priority_queue")

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
    "required": ["action", "citations", "reasoning"],
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
    },
}

#: Which run status a decided action produces. ``escalate``/``block_escalate`` are
#: legitimate outcomes of a working loop — the agent decided a human should look — so
#: the run ends ``escalated`` without ever having been a failure.
STATUS_FOR_ACTION: dict[str, str] = {
    "auto_approve": "completed",
    "priority_queue": "completed",
    "escalate": "escalated",
    "block_escalate": "escalated",
}


class Decision(BaseModel):
    """A validated final decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: DecisionAction
    citations: list[str] = Field(min_length=1)
    reasoning: str = Field(min_length=1)

    @property
    def run_status(self) -> str:
        """The terminal run status this action implies."""
        return STATUS_FOR_ACTION[self.action]

    def as_payload(self) -> dict[str, Any]:
        """The JSON form persisted on the run step and in the ``decision.made`` event."""
        return self.model_dump()


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
            "of rule IDs like R-001), and reasoning. Do not add any other text. "
            "This is the only correction attempt; a second invalid response escalates "
            "the run to a human."
        ),
    )
