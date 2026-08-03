"""The LLM gateway: one choke point for every model call (ADR-005).

Three jobs, none of which belong in an adapter and none of which the runtime may do
for itself:

1. **Resolve the provider** named by the agent's DNA to a registered adapter.
2. **Enforce the DNA's budgets** — ``max_tokens_per_run`` and ``max_cost_usd_per_run``
   — before and after each call. Exceeding either stops the run (fail closed).
3. **Meter usage** into the run's ledger so the trace shows what was actually spent.

Because every call goes through here, "this agent cannot exceed its budget" is a
property of the architecture rather than a promise about the code.
"""

import logging
from collections.abc import Sequence
from typing import Any

from app.llm.adapters.base import LlmAdapter
from app.llm.contract import (
    Budget,
    BudgetExceededError,
    CompletionResult,
    Message,
    ModelSpec,
    ToolSpec,
    UnknownProviderError,
)

logger = logging.getLogger(__name__)


class LlmGateway:
    """Routes model calls to provider adapters, under budget."""

    def __init__(self, adapters: Sequence[LlmAdapter]) -> None:
        self._adapters = {adapter.provider: adapter for adapter in adapters}

    @property
    def providers(self) -> list[str]:
        """Provider slugs a DNA document may name."""
        return sorted(self._adapters)

    async def complete(
        self,
        *,
        model: ModelSpec,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        response_schema: dict[str, Any],
        budget: Budget,
    ) -> CompletionResult:
        """Answer one turn, or refuse.

        Raises :class:`UnknownProviderError` when the DNA names a provider with no
        adapter, and :class:`BudgetExceededError` when the run has spent — or, with
        this call, has now spent — more than its DNA allows. The post-call overrun
        carries the result so the caller can trace the spend before escalating.
        """
        adapter = self._adapters.get(model.provider)
        if adapter is None:
            raise UnknownProviderError(
                f"no adapter registered for provider {model.provider!r} "
                f"(registered: {', '.join(self.providers) or 'none'})"
            )

        # Pre-flight: never start a call the run has already run out of room for.
        if budget.exhausted:
            raise BudgetExceededError(
                f"run budget already exhausted before this call ({budget.snapshot()})"
            )

        result = await adapter.complete(
            model=model,
            messages=messages,
            tools=tools,
            response_schema=response_schema,
        )

        # Metering happens whether or not the call fit — the trace records real spend.
        budget.record(result.usage)
        overrun = budget.overrun()
        if overrun is not None:
            logger.warning("run stopped by budget: %s", overrun)
            raise BudgetExceededError(overrun, result=result)

        return result
