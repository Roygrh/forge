"""The conversation a run is having, built live and rebuilt from the log.

A run that parks for a human approval stops mid-conversation. When somebody releases it,
the loop has to pick that conversation back up — and the object that was holding it is
long gone: the parking and the approval are different HTTP requests, possibly different
processes, possibly separated by a restart. **State lives in the database, not in the
runtime object** (see :mod:`app.runtime.loop`), so the transcript is rebuilt from the
append-only event log rather than stashed anywhere.

That is why every message the loop builds is built *here*, by a function the replay calls
too. The live transcript and the replayed one are the same code path, so they cannot
drift into two ideas of what the agent was told — a resumed agent seeing a subtly
different conversation from the one it paused in is the kind of bug that produces a
plausible, wrong, and completely unreproducible decision.

What a replay reconstructs, in order:

* the system message — the runtime protocol plus this version's ``task_prompt``, read
  from the pinned DNA, so the resumed agent runs under the definition it started under;
* the user message carrying the run input, read from the ``run.started`` event;
* one assistant/user pair per **executed** tool call, read from its ``tool.called``
  event: what the agent asked for, and what came back.

What it deliberately does not reconstruct: the correction turn of a schema violation
(ADR-006). Those are the platform telling the model about its *formatting*, not facts
about the case, and replaying "your last answer was malformed" into a conversation whose
malformed answer is not there would be less faithful, not more. Everything that bears on
the decision is a tool result, and every tool result is in the log.
"""

import json
from typing import Any

from app.dna.model import Dna
from app.llm.contract import Message
from app.models import Event
from app.runtime.output import DECISION_ACTIONS

#: The protocol every agent runs under, prepended to its own task prompt. It states the
#: loop's contract — one tool call or one decision per turn, citations required — and
#: belongs to the runtime, not to any agent: an agent's DNA describes *what* it decides,
#: never *how* the loop works.
RUNTIME_PROTOCOL = (
    "You are executing inside the Forge runtime. On each turn, do exactly one of:\n"
    "  (a) call one of the tools you have been granted, or\n"
    "  (b) return your final decision as a JSON object with the fields "
    f"action (one of {', '.join(DECISION_ACTIONS)}), citations (a non-empty list), "
    "reasoning, and confidence (a number from 0 to 1).\n"
    "Every decision must cite what it applied: rule IDs such as R-001, and — for any "
    "claim drawn from retrieved knowledge — the document citation the retrieval "
    "returned (document#section, e.g. AP-Policy-2023.pdf#approval-thresholds). If no "
    "rule matches, or your confidence is low, decide escalate and say that no rule "
    "matched — never guess. State your confidence honestly: a decision below this "
    "agent's declared floor is escalated to a human whatever action you proposed, and "
    "a confidently wrong answer is the one failure a reviewer cannot catch."
)


def opening_messages(dna: Dna, run_input: dict[str, Any]) -> list[Message]:
    """The two messages every run starts from: the protocol and the trigger payload."""
    return [
        Message(role="system", content=f"{RUNTIME_PROTOCOL}\n\n{dna.instructions.task_prompt}"),
        Message(
            role="user",
            content=f"Input for this run:\n{json.dumps(run_input, sort_keys=True, indent=2)}",
        ),
    ]


def tool_call_message(name: str, arguments: dict[str, Any]) -> Message:
    """The assistant turn recording what the agent asked the gateway for."""
    return Message(
        role="assistant",
        content=json.dumps({"tool_call": {"name": name, "arguments": arguments}}, sort_keys=True),
    )


def tool_result_message(name: str, result: dict[str, Any] | None) -> Message:
    """The user turn carrying what the gateway handed back."""
    return Message(
        role="user",
        content=json.dumps({"tool_result": {"name": name, "result": result}}, sort_keys=True),
    )


def replay_messages(dna: Dna, events: list[Event]) -> list[Message]:
    """Rebuild a paused run's conversation from its own append-only log.

    ``events`` are the run's events in append order — the order the events table exists
    to provide. Only executed tool calls contribute: a refused call produced no
    observation, and the parked one has not run yet (it is the caller's next move).
    """
    started = next((event for event in events if event.type == "run.started"), None)
    if started is None:  # pragma: no cover - a run always opens with its own event
        raise ValueError("cannot replay a run with no run.started event")

    messages = opening_messages(dna, dict(started.payload.get("input") or {}))
    for event in events:
        if event.type != "tool.called" or event.payload.get("status") != "executed":
            continue
        name = str(event.payload["tool_name"])
        messages.append(tool_call_message(name, dict(event.payload.get("args") or {})))
        messages.append(tool_result_message(name, event.payload.get("result")))
    return messages
