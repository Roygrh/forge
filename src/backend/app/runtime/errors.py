"""Fail-closed stops, with a reason a human can act on.

Golden rule 3: on doubt, ambiguity, or missing permission the run stops. *Why* it
stopped is :class:`~app.governance.GovernanceReason` — one enum, shared by the tool
gateway that raises the condition, the runtime that catches it, the audit log that
records it, and the API that serves it. Keeping the vocabulary in one dependency-free
module is what stops those four from drifting into different names for the same refusal.

This module holds only the exception that carries it.
"""

from app.governance import GovernanceReason

__all__ = ["FailClosedError", "GovernanceReason"]


class FailClosedError(Exception):
    """Stop the run short of a decision.

    Raised from anywhere in the loop — the tool gateway's verdict, a blown budget, a
    decision below its confidence floor — and caught in exactly one place, at the top of
    :meth:`~app.runtime.loop.AgentRuntime.start_run`, where it becomes one governance
    step plus the terminal event and status named by ``run_status``.

    ``run_status`` is ``escalated`` for every reason but one. A parked approval ends the
    run ``awaiting_approval`` instead, because "a human must act before this continues"
    is a different state from "a human must decide instead of the agent", and an approval
    queue cannot be built on a status that conflates them.
    """

    def __init__(
        self, reason: GovernanceReason, detail: str, *, run_status: str = "escalated"
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.run_status = run_status
        super().__init__(f"{reason}: {detail}")
