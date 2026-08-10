"""What an approver is shown beside the action they are being asked to release.

Kevin Osei, discovery interview 2: *"Show me: what it wants to do, the invoice, the PO
next to it, which rule fired, and what's off. If I have to open the ERP in another tab,
that's two more minutes each."* FR-E1 is that sentence turned into a requirement, and
this module is the part of it the API owes the screen — a decision that needs a second
tab is a decision that takes two minutes, and ten of those is a morning.

The evidence is **everything the agent gathered before it asked**, verbatim: the run's
input, and every tool call that actually executed, with its arguments and its result.
Nothing is summarised into prose, because prose can be subtly wrong about the number a
person is about to authorise. Nothing is fetched live either — this is what the agent
saw, read back from the run's own append-only log, so the approver and the agent are
looking at the same facts.

It is deliberately domain-agnostic. There is no invoice-shaped code here: an invoice, a
purchase order, and a fired rule reach the screen because *those are the tool results the
AP agents produce*, and a different domain's agents would put their own evidence in the
same envelope.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.models import AgentVersion, Event
from app.runtime.output import RULE_ID_PATTERN
from app.runtime.trace import EVENT_RUN_STARTED, EVENT_TOOL_CALLED

#: Governed rule ids, as they appear anywhere in what the agent gathered.
_RULE_ID = re.compile(RULE_ID_PATTERN[1:-1])


@dataclass(frozen=True)
class Observation:
    """One tool call the agent made and got an answer to, before it asked for a human."""

    tool_invocation_id: uuid.UUID
    tool_ref: str
    tool_name: str
    args: dict[str, Any] | None
    result: dict[str, Any] | None

    def as_json(self) -> dict[str, Any]:
        """The API form."""
        return {
            "tool_invocation_id": str(self.tool_invocation_id),
            "tool_ref": self.tool_ref,
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
        }


@dataclass(frozen=True)
class Evidence:
    """The case for a decision, assembled from one run's events."""

    agent: str
    agent_description: str | None
    run_input: dict[str, Any]
    observations: list[Observation]
    rule_ids: list[str]

    def as_json(self) -> dict[str, Any]:
        """The API form."""
        return {
            "agent": self.agent,
            "agent_description": self.agent_description,
            "run_input": self.run_input,
            "observations": [observation.as_json() for observation in self.observations],
            "rule_ids": self.rule_ids,
        }


def build_evidence(agent_version: AgentVersion, events: list[Event]) -> Evidence:
    """Assemble the evidence for one parked action from its run's events.

    ``events`` are the run's events in append order. Only executed tool calls contribute:
    a refused call produced no observation, and the parked call itself is the *proposal*,
    served beside this rather than inside it.
    """
    identity = agent_version.dna.get("identity", {})
    run_input: dict[str, Any] = {}
    observations: list[Observation] = []

    for event in events:
        if event.type == EVENT_RUN_STARTED:
            run_input = dict(event.payload.get("input") or {})
        elif event.type == EVENT_TOOL_CALLED and event.payload.get("status") == "executed":
            observations.append(
                Observation(
                    tool_invocation_id=uuid.UUID(str(event.payload["tool_invocation_id"])),
                    tool_ref=str(event.payload["tool_ref"]),
                    tool_name=str(event.payload["tool_name"]),
                    args=event.payload.get("args"),
                    result=event.payload.get("result"),
                )
            )

    return Evidence(
        agent=f"{identity.get('slug')}@{agent_version.version}",
        agent_description=identity.get("description"),
        run_input=run_input,
        observations=observations,
        rule_ids=_rule_ids_in(observations),
    )


def _rule_ids_in(observations: list[Observation]) -> list[str]:
    """Every governed rule id present in what the agent gathered, first seen first.

    "Which rule fired" is the third thing Kevin asks for, and for an AP run the answer is
    already in the ``query_rules`` result the agent retrieved. This surfaces those ids so
    the screen can lead with them instead of burying them in a payload.

    It is a **reading of the evidence, not a decision**: the agent has not made one yet,
    and an id appearing here means only that it was in front of the agent when it asked
    for a human. The authoritative citations are the ones a decision carries (R-092).
    """
    seen: list[str] = []
    for observation in observations:
        gathered = json.dumps(observation.result, sort_keys=True, default=str)
        for rule_id in _RULE_ID.findall(gathered):
            if rule_id not in seen:
                seen.append(rule_id)
    return seen
