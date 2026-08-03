"""What a tool is, and what one invocation of it produced.

A tool is a *contract* — a versioned ref, a typed input schema, a typed output schema —
plus a handler. Splitting it that way is what lets the gateway validate a call before
any handler runs, and what lets the trace record an attempt that never executed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.dna.model import Autonomy

#: Terminal states of one trip through the tool gateway, matching
#: ``tool_invocations.status`` in the data model.
#:
#: ``executed`` — validated, permitted, and run.
#: ``blocked``  — refused by policy or validation; the handler never ran.
#: ``denied``   — the DNA grants the tool as ``forbidden``.
#: (``validated`` is reserved for Phase 3.x HITL, where a call is validated and then
#: parked in the approval queue before it may execute.)
InvocationStatus = Literal["validated", "executed", "blocked", "denied"]

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


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


@dataclass(frozen=True)
class ToolOutcome:
    """The result of asking the gateway to run a tool — including a refusal.

    Refusals are first-class values, not exceptions, because they must be *recorded*:
    a reviewer has to see what the agent tried to do, not only what it was allowed to
    do. The runtime decides what a refusal means for the run (it escalates).
    """

    tool_name: str
    tool_ref: str
    autonomy: Autonomy | None
    arguments: dict[str, Any]
    status: InvocationStatus
    result: dict[str, Any] | None = None
    error: str | None = None

    @property
    def executed(self) -> bool:
        """True only when the handler actually ran."""
        return self.status == "executed"
