"""A scripted, offline adapter — the default for tests and the local demo.

Determinism is the point. The runtime loop is a pure function of the turns it gets
back, so a fixed script produces a byte-identical run every time: same steps, same
events, same decision. That is what lets a test assert on a whole trace instead of on
"something happened", and what lets the eval suite (Phase 4.5) be a regression gate
rather than a mood ring.

No network, no key, no clock. Build one with the helpers below::

    FakeAdapter([
        tool_turn("get_fact", {"topic": "forge"}),
        decision_turn("auto_approve", ["R-000"], "The fact was retrieved."),
    ])
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.llm.adapters.base import LlmAdapter
from app.llm.contract import (
    AdapterError,
    CompletionResult,
    Message,
    ModelSpec,
    ToolCall,
    ToolSpec,
    Usage,
)

#: Nominal usage per scripted turn. Small enough that a normal run stays well inside a
#: sane budget, large enough that a test can exhaust one in a few turns.
DEFAULT_INPUT_TOKENS = 200
DEFAULT_OUTPUT_TOKENS = 100
DEFAULT_COST_USD = Decimal("0.0005")


@dataclass(frozen=True)
class ScriptedTurn:
    """One canned answer, with the usage it should be metered for."""

    content: str | None = None
    tool_call: ToolCall | None = None
    input_tokens: int = DEFAULT_INPUT_TOKENS
    output_tokens: int = DEFAULT_OUTPUT_TOKENS
    cost_usd: Decimal = DEFAULT_COST_USD


@dataclass
class RecordedCall:
    """What the runtime asked for, kept so tests can assert on the prompt it built."""

    model: ModelSpec
    messages: list[Message]
    tools: list[ToolSpec]
    response_schema: dict[str, Any]


def tool_turn(
    name: str,
    arguments: dict[str, Any],
    *,
    input_tokens: int = DEFAULT_INPUT_TOKENS,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    cost_usd: Decimal = DEFAULT_COST_USD,
) -> ScriptedTurn:
    """A turn in which the model asks to call ``name``."""
    return ScriptedTurn(
        tool_call=ToolCall(name=name, arguments=arguments),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def decision_turn(
    action: str,
    citations: list[str],
    reasoning: str,
    *,
    confidence: float = 1.0,
    input_tokens: int = DEFAULT_INPUT_TOKENS,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    cost_usd: Decimal = DEFAULT_COST_USD,
) -> ScriptedTurn:
    """A turn carrying a well-formed final decision.

    confidence defaults to certainty so a test that is not about the confidence floor
    does not have to mention it; pass a low value to exercise the low_confidence override.
    """
    payload = {
        "action": action,
        "citations": citations,
        "reasoning": reasoning,
        "confidence": confidence,
    }
    return ScriptedTurn(
        content=json.dumps(payload),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def raw_turn(
    content: str,
    *,
    input_tokens: int = DEFAULT_INPUT_TOKENS,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    cost_usd: Decimal = DEFAULT_COST_USD,
) -> ScriptedTurn:
    """A turn carrying arbitrary text — how a test produces malformed output."""
    return ScriptedTurn(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


@dataclass
class FakeAdapter(LlmAdapter):
    """Replays ``script`` in order, one turn per call.

    ``repeat_last`` keeps answering with the final turn once the script runs out, which
    is how a test builds a model that never finishes (for the ``max_steps`` guardrail).
    Without it, an over-long run fails loudly rather than silently looping.
    """

    script: Sequence[ScriptedTurn]
    repeat_last: bool = False
    provider: str = "fake"
    calls: list[RecordedCall] = field(default_factory=list)

    async def complete(
        self,
        *,
        model: ModelSpec,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        response_schema: dict[str, Any],
    ) -> CompletionResult:
        """Return the next scripted turn."""
        index = len(self.calls)
        self.calls.append(
            RecordedCall(
                model=model,
                messages=list(messages),
                tools=list(tools),
                response_schema=response_schema,
            )
        )

        if index < len(self.script):
            turn = self.script[index]
        elif self.repeat_last and self.script:
            turn = self.script[-1]
        else:
            raise AdapterError(
                f"fake adapter script exhausted after {len(self.script)} turn(s); "
                "the runtime asked for one more"
            )

        return CompletionResult(
            provider=self.provider,
            model_id=model.model_id,
            content=turn.content,
            tool_call=turn.tool_call,
            usage=Usage(
                input_tokens=turn.input_tokens,
                output_tokens=turn.output_tokens,
                cost_usd=turn.cost_usd,
            ),
        )
