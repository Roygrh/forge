"""The Anthropic provider adapter (ADR-005: "Anthropic first").

Wired and selectable, but never exercised by the test suite — every test runs on the
:class:`~app.llm.adapters.fake.FakeAdapter`, so `pytest` needs no key and no network.
That separation is the ADR's claim made concrete: the runtime cannot tell which adapter
answered it.

Credentials come from settings only. There is no key in this file, in a DNA document,
or in any agent definition — the gateway configuration is the single place one lives.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from anthropic import APIError as AnthropicAPIError
from anthropic import AsyncAnthropic

from app.config import get_settings
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

#: Per-response output ceiling. Distinct from the DNA's ``max_tokens_per_run``, which is
#: a *run* budget the gateway enforces across calls. 16k stays under the SDK's
#: non-streaming HTTP timeout; larger outputs would need the streaming API.
MAX_OUTPUT_TOKENS = 16_000

#: USD per million tokens, (input, output), keyed by model-id prefix so dated snapshots
#: (``claude-haiku-4-5-20251001``) resolve to their family. A model absent from this
#: table has no price the gateway can meter, and metering is not optional — see
#: ``_price``. Update alongside any new model the platform is pointed at.
PRICE_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-fable-5": (Decimal("10"), Decimal("50")),
    "claude-mythos-5": (Decimal("10"), Decimal("50")),
    "claude-opus-5": (Decimal("5"), Decimal("25")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25")),
    "claude-opus-4-7": (Decimal("5"), Decimal("25")),
    "claude-opus-4-6": (Decimal("5"), Decimal("25")),
    "claude-sonnet-5": (Decimal("3"), Decimal("15")),
    "claude-sonnet-4-6": (Decimal("3"), Decimal("15")),
    "claude-haiku-4-5": (Decimal("1"), Decimal("5")),
}

#: Model families that reject ``temperature``/``top_p``/``top_k`` outright (400). The
#: DNA schema requires a temperature, so the adapter drops it for these rather than
#: letting a valid definition fail at the provider.
NO_SAMPLING_PARAMS = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
)


def _price(model_id: str) -> tuple[Decimal, Decimal]:
    """Return (input, output) USD per million tokens for ``model_id``.

    Fails closed on an unknown model: a run whose spend cannot be priced cannot be held
    to its cost ceiling, and a silently-unmetered run is exactly what ADR-005 exists to
    prevent.
    """
    matches = [prefix for prefix in PRICE_PER_MTOK if model_id.startswith(prefix)]
    if not matches:
        raise AdapterError(
            f"no price on file for model {model_id!r}; refusing to run a call whose "
            "cost cannot be metered against the DNA budget"
        )
    return PRICE_PER_MTOK[max(matches, key=len)]


class AnthropicAdapter(LlmAdapter):
    """Real Anthropic Messages API calls, behind the internal contract."""

    provider = "anthropic"

    def __init__(self, client: AsyncAnthropic | None = None) -> None:
        """Build the adapter, reading the API key from settings when no client is given."""
        if client is not None:
            self._client = client
            return
        api_key = get_settings().anthropic_api_key
        if not api_key:
            raise AdapterError(
                "ANTHROPIC_API_KEY is not configured; the anthropic provider is unavailable"
            )
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        *,
        model: ModelSpec,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        response_schema: dict[str, Any],
    ) -> CompletionResult:
        """Translate one internal request into a Messages API call, and back."""
        input_price, output_price = _price(model.model_id)

        # The internal contract carries system turns in the message list; the Messages
        # API takes them as a separate top-level field.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

        request: dict[str, Any] = {
            "model": model.model_id,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": turns,
            # ADR-006: the model is constrained to the decision schema rather than
            # asked nicely for JSON. Tool calls are validated separately, by the tool
            # gateway, against each tool's own input schema.
            "output_config": {"format": {"type": "json_schema", "schema": response_schema}},
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ]
        if not model.model_id.startswith(NO_SAMPLING_PARAMS):
            request["temperature"] = model.temperature

        try:
            response = await self._client.messages.create(**request)
        except AnthropicAPIError as exc:  # transport, auth, rate limit, refusal
            raise AdapterError(f"anthropic call failed: {exc}") from exc

        content: str | None = None
        tool_call: ToolCall | None = None
        for block in response.content:
            if block.type == "text" and content is None:
                content = block.text
            elif block.type == "tool_use" and tool_call is None:
                # `input` is provider-parsed JSON; the tool gateway validates it.
                tool_call = ToolCall(name=block.name, arguments=dict(block.input or {}))

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=(
                response.usage.input_tokens * input_price
                + response.usage.output_tokens * output_price
            )
            / Decimal(1_000_000),
        )
        return CompletionResult(
            provider=self.provider,
            model_id=response.model,
            content=content,
            tool_call=tool_call,
            usage=usage,
        )
