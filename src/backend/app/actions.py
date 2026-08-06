"""The platform's decision vocabulary.

Four actions, and the order of restrictiveness between them. An agent chooses one; it
does not invent its own. The same four appear in the API contract
(``openapi.yaml`` ``RunStep.decision``), in the eval cases, and in the captured rule set
— so they are defined once, here.

This module deliberately imports nothing from the rest of the application. Three layers
need the vocabulary — the runtime (which validates a decision), the rules layer (which
stores the action a rule implies), and the LLM adapters (which produce one) — and each
of those depends on the others in some direction. A dependency-free module is what lets
all three share the definition without an import cycle.
"""

from collections.abc import Iterable
from typing import Literal

#: The four final actions of an AP decision.
DecisionAction = Literal["auto_approve", "escalate", "block_escalate", "priority_queue"]

DECISION_ACTIONS: tuple[str, ...] = ("auto_approve", "escalate", "block_escalate", "priority_queue")

#: Which run status a decided action produces. ``escalate``/``block_escalate`` are
#: legitimate outcomes of a working loop — the agent decided a human should look — so
#: the run ends ``escalated`` without ever having been a failure.
STATUS_FOR_ACTION: dict[str, str] = {
    "auto_approve": "completed",
    "priority_queue": "completed",
    "escalate": "escalated",
    "block_escalate": "escalated",
}

#: R-090's tie-break, as an ordering: when several rules fire under the same authority,
#: the **most restrictive** action wins. Rank, not preference — nothing may reorder it.
ACTION_RESTRICTIVENESS: dict[str, int] = {
    "auto_approve": 0,
    "priority_queue": 1,
    "escalate": 2,
    "block_escalate": 3,
}


def most_restrictive(actions: Iterable[str]) -> str | None:
    """The most restrictive of ``actions`` (R-090), or ``None`` when there are none.

    ``None`` is the fail-closed prompt, not a default: no action to choose from means no
    rule proposed one, and the caller answers that with an escalation under R-091.
    """
    candidates = [action for action in actions if action in ACTION_RESTRICTIVENESS]
    if not candidates:
        return None
    return max(candidates, key=lambda action: ACTION_RESTRICTIVENESS[action])
