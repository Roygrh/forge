"""What every provider adapter must implement.

An adapter's whole job is translation: internal contract in, provider dialect out,
internal contract back. It does **not** enforce budgets, retry, validate output, or
touch the database — those are the gateway's and the runtime's, and keeping them out of
here is what makes "swap the provider, change nothing else" true (ADR-005).
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from app.llm.contract import CompletionResult, Message, ModelSpec, ToolSpec


class LlmAdapter(ABC):
    """One provider, behind the internal contract."""

    #: Provider slug this adapter answers to; matched against the DNA ``model.provider``.
    provider: str

    @abstractmethod
    async def complete(
        self,
        *,
        model: ModelSpec,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        response_schema: dict[str, Any],
    ) -> CompletionResult:
        """Answer one turn.

        Implementations return either free-standing ``content`` (expected to satisfy
        ``response_schema``) or a ``tool_call``, and must always report ``usage`` —
        an unmetered call is a hole in the cost ceiling.
        """
