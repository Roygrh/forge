"""What a tool is, and what one invocation of it produced.

A tool is a *contract* — a versioned ref, a typed input schema, a typed output schema,
and optionally a schema for the per-agent configuration a DNA grant may carry — plus a
handler. Splitting it that way is what lets the gateway validate a call before any
handler runs, and what lets the trace record an attempt that never executed.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.dna.model import Autonomy
from app.governance import GovernanceReason

#: Terminal states of one trip through the tool gateway, matching
#: ``tool_invocations.status`` in the data model.
#:
#: ``executed``  — validated, permitted, and run.
#: ``validated`` — validated and permitted *in form*, but the DNA grants it only with a
#:                 human approval, so it is parked rather than run (FR-E2).
#: ``blocked``   — refused by policy or validation; the handler never ran.
#: ``denied``    — the DNA grants the tool as ``forbidden``.
InvocationStatus = Literal["validated", "executed", "blocked", "denied"]


@dataclass(frozen=True)
class ApprovalRelease:
    """A human's recorded decision to let **one** parked call run (FR-E2, FR-E4).

    The gateway parks every ``requires_approval`` call. This is the only thing that
    unparks one, and it is evidence rather than a flag: it names the approval row, the
    person who granted it, and when. A release is minted in exactly one place — the
    approval queue, from a ``granted`` row it just wrote — so "executed without a
    recorded approval" is not a state the code can reach.

    It authorises the call it was minted for and nothing else. Granularity is structural:
    one approval row exists per ``tool_invocations`` row (a unique constraint), the queue
    replays *that row's stored arguments*, and an approver's request body carries no
    arguments at all. Approving a $4,000 payment cannot approve a $40,000 one.
    """

    approval_id: uuid.UUID
    decided_by: str
    decided_at: datetime

    def as_json(self) -> dict[str, Any]:
        """The form a handler and the trace see."""
        return {
            "approval_id": str(self.approval_id),
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat(),
        }


@dataclass(frozen=True)
class ToolInput:
    """Everything a handler is given: the model's arguments and the DNA's configuration.

    The two are kept apart on purpose. ``arguments`` come from the model and are never
    trusted until the gateway has checked them; ``config`` comes from the published DNA
    and is a governance statement about this agent's use of this tool (a spend cap, a
    channel restriction). A handler that consults ``config`` is enforcing something a
    reviewer can read in the definition.
    """

    arguments: dict[str, Any]
    config: dict[str, Any]


ToolHandler = Callable[[ToolInput], dict[str, Any]]


class ToolExecutionError(Exception):
    """A tool refused the call for a reason of its own — an unknown record, a bad state.

    Distinct from an unexpected exception: this is an anticipated refusal the gateway
    turns into a recorded ``blocked`` outcome with the reason intact, rather than an
    incident with a stack trace.
    """


@dataclass(frozen=True)
class ToolContract:
    """One registered tool.

    ``ref`` (``slug@semver``) is what a DNA document grants; ``name`` is what the model
    is shown and calls. Keeping them distinct means a tool can be re-versioned without
    changing the vocabulary the model was prompted with.
    """

    ref: str
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: ToolHandler = field(repr=False)
    #: Validates the ``config`` object a DNA grant may attach. ``None`` means this tool
    #: takes no configuration, and a grant that supplies some is a definition error.
    config_schema: dict[str, Any] | None = None
    #: A tool that declares this consumes the DNA's ``knowledge`` block: the gateway
    #: injects the published collection scope and tenant into its config under
    #: ``knowledge_scope`` (see :meth:`ToolGateway.invoke`). The scope therefore comes
    #: from the *published definition*, never from arguments the model chose — the model
    #: cannot widen what its agent may read (FR-C3 applied to knowledge).
    knowledge_scoped: bool = False


@dataclass(frozen=True)
class ToolOutcome:
    """The result of asking the gateway to run a tool — including a refusal.

    Refusals are first-class values, not exceptions, because they must be *recorded*:
    a reviewer has to see what the agent tried to do, not only what it was allowed to
    do. The runtime decides what a refusal means for the run (it escalates).

    ``reason`` carries the governance code the gateway assigned. The gateway is the only
    place that decides *which* refusal this was; the runtime and the trace propagate that
    code without re-deriving it, so the words in the audit log are the words the
    enforcement point used.
    """

    tool_name: str
    tool_ref: str
    autonomy: Autonomy | None
    arguments: dict[str, Any]
    status: InvocationStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    reason: GovernanceReason | None = None
    #: The approval that released this call, when it ran only because a human said so.
    #: ``None`` for everything else. Carried into the trace so a released execution is
    #: never indistinguishable from an autonomous one (FR-E4).
    release: ApprovalRelease | None = None

    @property
    def executed(self) -> bool:
        """True only when the handler actually ran."""
        return self.status == "executed"

    @property
    def pending_approval(self) -> bool:
        """True when the call was validated and parked for a human (FR-E2, FR-E3).

        Not a refusal and not an execution: the run stops in ``awaiting_approval`` and
        the tool has done nothing. An approval that cannot be obtained never decays into
        an execution (golden rule 3).
        """
        return self.status == "validated"
