"""Fail-closed stops, with a reason a human can act on.

Golden rule 3: on doubt, ambiguity, or missing permission the run escalates. Every way
that can happen is enumerated here, so an escalation in the trace always says *why* —
"escalated" with no reason is an incident report with the incident removed.
"""

from enum import StrEnum


class EscalationReason(StrEnum):
    """Why a run stopped short of a decision."""

    INVALID_OUTPUT = "invalid_output"
    """Model output failed the response schema twice — once, then once after correction
    (ADR-006). Malformed output never becomes an action."""

    TOOL_REFUSED = "tool_refused"
    """The tool gateway would not execute the call: unknown tool, missing grant,
    forbidden tool, or arguments that failed the tool's schema (FR-C5)."""

    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    """The loop reached ``guardrails.max_steps`` without reaching a decision."""

    TIMEOUT = "timeout"
    """The run passed ``guardrails.timeout_seconds`` of wall clock."""

    BUDGET_EXCEEDED = "budget_exceeded"
    """The run reached a token or cost ceiling from the DNA ``model`` block."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    """The DNA names a provider or model the gateway cannot serve or meter."""

    UNSUPPORTED_DEFINITION = "unsupported_definition"
    """The DNA is valid but declares a capability this build cannot honour — e.g.
    knowledge collections before the knowledge layer exists. Running it anyway would
    silently execute a *different*, less-informed agent than the one published."""

    AGENT_DECISION = "agent_decision"
    """Not a failure: the agent reached a decision whose action is a human queue
    (``escalate`` / ``block_escalate``). The loop worked; the answer is 'a person'."""


class FailClosedError(Exception):
    """Stop the run and escalate.

    Raised from anywhere in the loop; caught once, at the top, where it becomes a
    ``run.escalated`` event and an ``escalated`` run status.
    """

    def __init__(self, reason: EscalationReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")
