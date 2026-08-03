"""The one internal contract every model call passes through (ADR-005).

``complete(messages, tools, response_schema, budget) -> CompletionResult``. Nothing in
this module names a provider: these types are the vocabulary adapters translate *into*,
which is what makes an adapter swap invisible to the runtime.
"""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    """One turn of the conversation the gateway is asked to continue."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class ToolSpec(BaseModel):
    """A tool as the *model* sees it: a name, a purpose, and an argument schema.

    Deliberately not the tool gateway's contract — the model is told what it may ask
    for; the gateway decides what actually runs.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]


class ModelSpec(BaseModel):
    """Which provider and model to use, taken from the agent's DNA ``model`` block."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model_id: str
    temperature: float


class ToolCall(BaseModel):
    """A model's request to invoke a tool. Arguments are unvalidated at this point."""

    model_config = ConfigDict(frozen=True)

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """What one model call consumed. Cost is priced by the adapter that made the call."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int
    cost_usd: Decimal

    @property
    def total_tokens(self) -> int:
        """Tokens counted against the run's token budget."""
        return self.input_tokens + self.output_tokens


class CompletionResult(BaseModel):
    """The typed result of one model call.

    Exactly one of ``content`` and ``tool_call`` is expected to be meaningful; deciding
    which — and rejecting the ambiguous case — is the structured-output layer's job
    (:mod:`app.runtime.output`), not the gateway's.
    """

    model_config = ConfigDict(frozen=True)

    provider: str
    model_id: str
    content: str | None = None
    tool_call: ToolCall | None = None
    usage: Usage


class Budget:
    """A run's token and cost ceilings, and what it has spent so far (FR-B3).

    Mutable and per-run on purpose: it is the ledger the gateway debits at one choke
    point, so no caller can spend without being metered. Exceeding either ceiling stops
    the run — budgets fail closed, they do not degrade.
    """

    def __init__(self, *, max_tokens: int, max_cost_usd: Decimal) -> None:
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.tokens_used = 0
        self.cost_usd = Decimal("0")

    @property
    def exhausted(self) -> bool:
        """True once either ceiling has been reached or passed."""
        return self.tokens_used >= self.max_tokens or self.cost_usd >= self.max_cost_usd

    def record(self, usage: Usage) -> None:
        """Debit one call's usage. Recording always happens, even when it overruns —
        the trace must show what was actually spent."""
        self.tokens_used += usage.total_tokens
        self.cost_usd += usage.cost_usd

    def overrun(self) -> str | None:
        """Return which ceiling was breached, or ``None`` while within budget."""
        if self.tokens_used > self.max_tokens:
            return f"token budget exceeded: {self.tokens_used} > {self.max_tokens}"
        if self.cost_usd > self.max_cost_usd:
            return f"cost budget exceeded: ${self.cost_usd} > ${self.max_cost_usd}"
        return None

    def snapshot(self) -> dict[str, Any]:
        """A JSON-friendly view for traces and run summaries."""
        return {
            "tokens_used": self.tokens_used,
            "max_tokens": self.max_tokens,
            "cost_usd": str(self.cost_usd),
            "max_cost_usd": str(self.max_cost_usd),
        }


class LlmGatewayError(Exception):
    """Base class for every failure raised by the gateway layer."""


class UnknownProviderError(LlmGatewayError):
    """The DNA names a provider with no registered adapter.

    Fail closed: a definition the platform cannot honestly execute does not get a
    best-effort substitute.
    """


class BudgetExceededError(LlmGatewayError):
    """A run hit its token or cost ceiling.

    Carries ``result`` when the overrun was discovered *after* a call returned, so the
    runtime can still record that call before escalating — spend that happened must
    appear in the trace.
    """

    def __init__(self, message: str, *, result: CompletionResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class AdapterError(LlmGatewayError):
    """A provider adapter could not produce a result (transport, auth, pricing)."""
