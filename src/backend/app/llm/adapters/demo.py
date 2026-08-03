"""The deterministic stand-in the seeded skeleton agent runs on.

:class:`~app.llm.adapters.fake.FakeAdapter` replays a script a *test* wrote. This one
has no script: it derives its two turns from the request, so a freshly seeded, freshly
started stack answers ``POST /api/v1/runs`` correctly with no key, no network, and no
test harness. That is what makes the walking skeleton demonstrable rather than merely
tested.

Still a pure function of its input — same request, same answer, every time:

    no tool result in the transcript yet  -> ask for the fact
    a tool result is present              -> decide, citing the placeholder rule
"""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.llm.adapters.base import LlmAdapter
from app.llm.contract import CompletionResult, Message, ModelSpec, ToolCall, ToolSpec, Usage

#: The rule the skeleton cites. Deliberately not a governed rule — see scripts/seed.py.
PLACEHOLDER_RULE = "R-000"

#: What the agent looks up when the run input names no topic.
DEFAULT_TOPIC = "forge"

#: Nominal usage, so budgets and cost totals are exercised rather than reported as zero.
_USAGE = Usage(input_tokens=200, output_tokens=100, cost_usd=Decimal("0.0005"))


class SkeletonDemoAdapter(LlmAdapter):
    """Answers the skeleton agent's two turns, derived from the conversation."""

    provider = "fake"

    async def complete(
        self,
        *,
        model: ModelSpec,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        response_schema: dict[str, Any],
    ) -> CompletionResult:
        """Ask for the fact, then decide once it has been observed."""
        observed = _last_tool_result(messages)

        if observed is None and tools:
            content, tool_call = (
                None,
                ToolCall(name=tools[0].name, arguments={"topic": _topic(messages)}),
            )
        else:
            fact = (observed or {}).get("fact", "no fact was retrieved")
            content, tool_call = (
                json.dumps(
                    {
                        "action": "auto_approve",
                        "citations": [PLACEHOLDER_RULE],
                        "reasoning": f"Retrieved the governed fact: {fact}",
                    }
                ),
                None,
            )

        return CompletionResult(
            provider=self.provider,
            model_id=model.model_id,
            content=content,
            tool_call=tool_call,
            usage=_USAGE,
        )


def _messages_as_json(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Every user turn that carries a JSON object, oldest first."""
    payloads = []
    for message in messages:
        if message.role != "user":
            continue
        # The runtime writes tool results as JSON and the run input after a text label;
        # take whatever parses and ignore the rest.
        _, _, tail = message.content.partition("\n")
        for candidate in (message.content, tail):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                payloads.append(parsed)
                break
    return payloads


def _last_tool_result(messages: Sequence[Message]) -> dict[str, Any] | None:
    """The most recent tool result in the transcript, if the loop has fed one back."""
    results = [
        payload["tool_result"].get("result")
        for payload in _messages_as_json(messages)
        if isinstance(payload.get("tool_result"), dict)
    ]
    return results[-1] if results else None


def _topic(messages: Sequence[Message]) -> str:
    """The topic from the run input, or the demo's default subject."""
    for payload in _messages_as_json(messages):
        topic = payload.get("topic")
        if isinstance(topic, str) and topic:
            return topic
    return DEFAULT_TOPIC
