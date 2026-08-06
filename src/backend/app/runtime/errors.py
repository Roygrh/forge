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

    APPROVAL_REQUIRED = "approval_required"
    """The agent called a tool its DNA grants only ``requires_approval``. The call was
    validated and **parked**: the run stops in ``awaiting_approval`` and the tool did
    nothing. An approval the platform cannot obtain never decays into an execution
    (FR-E2, FR-E3); the queue that resumes such a run arrives in Phase 4.4."""


class FailClosedError(Exception):
    """Stop the run short of a decision.

    Raised from anywhere in the loop; caught once, at the top, where it becomes the
    terminal event and status named by ``run_status`` — ``escalated`` for every reason
    but one. A parked approval ends the run ``awaiting_approval`` instead, because
    "a human must act before this continues" is a different state from "a human must
    decide instead of the agent", and a queue cannot be built on a status that conflates
    them.
    """

    def __init__(
        self, reason: EscalationReason, detail: str, *, run_status: str = "escalated"
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.run_status = run_status
        super().__init__(f"{reason}: {detail}")
