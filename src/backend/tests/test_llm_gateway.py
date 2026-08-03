"""The LLM gateway: provider resolution and budget enforcement (ADR-005).

No database and no network — the gateway is a pure choke point, and these tests treat
it as one.
"""

import asyncio
from decimal import Decimal

import pytest

from app.llm import (
    AdapterError,
    Budget,
    BudgetExceededError,
    CompletionResult,
    FakeAdapter,
    LlmGateway,
    ModelSpec,
    ScriptedTurn,
    UnknownProviderError,
    decision_turn,
)
from app.llm.adapters.anthropic import _price
from app.runtime.output import DECISION_SCHEMA

FAKE_MODEL = ModelSpec(provider="fake", model_id="fake-scripted-1", temperature=0)


def _complete(
    gateway: LlmGateway, budget: Budget, model: ModelSpec = FAKE_MODEL
) -> CompletionResult:
    """Drive one gateway call from a synchronous test."""
    return asyncio.run(
        gateway.complete(
            model=model,
            messages=[],
            tools=[],
            response_schema=DECISION_SCHEMA,
            budget=budget,
        )
    )


def _budget(*, tokens: int = 10_000, cost: str = "1.00") -> Budget:
    return Budget(max_tokens=tokens, max_cost_usd=Decimal(cost))


def _gateway(*turns: ScriptedTurn) -> LlmGateway:
    return LlmGateway([FakeAdapter(script=list(turns))])


def test_meters_usage_into_the_run_budget() -> None:
    """Every call is debited at the choke point, so nothing spends unmetered."""
    gateway = _gateway(decision_turn("auto_approve", ["R-000"], "done"))
    budget = _budget()

    result = _complete(gateway, budget)

    assert budget.tokens_used == result.usage.total_tokens
    assert budget.cost_usd == result.usage.cost_usd


def test_unknown_provider_fails_closed() -> None:
    """A DNA naming a provider with no adapter gets a refusal, not a substitute."""
    gateway = _gateway(decision_turn("auto_approve", ["R-000"], "done"))

    with pytest.raises(UnknownProviderError):
        _complete(gateway, _budget(), ModelSpec(provider="openai", model_id="x", temperature=0))


def test_token_ceiling_stops_the_run_and_keeps_the_result() -> None:
    """Overrunning tokens raises — carrying the result so the spend is still traceable."""
    turn = decision_turn("auto_approve", ["R-000"], "done", input_tokens=200, output_tokens=100)
    gateway = _gateway(turn)
    budget = _budget(tokens=100)

    with pytest.raises(BudgetExceededError) as excinfo:
        _complete(gateway, budget)

    assert "token budget exceeded" in str(excinfo.value)
    assert excinfo.value.result is not None
    assert excinfo.value.result.usage.total_tokens == 300
    # Recorded even though it overran: the trace must show what was actually spent.
    assert budget.tokens_used == 300


def test_cost_ceiling_stops_the_run() -> None:
    """The money ceiling is enforced with the same fail-closed shape as tokens."""
    turn = decision_turn("auto_approve", ["R-000"], "done", cost_usd=Decimal("0.10"))
    gateway = _gateway(turn)

    with pytest.raises(BudgetExceededError) as excinfo:
        _complete(gateway, _budget(cost="0.01"))

    assert "cost budget exceeded" in str(excinfo.value)


def test_an_exhausted_budget_blocks_the_next_call_before_it_is_made() -> None:
    """Pre-flight refusal: no call is started that the run has no room for."""
    gateway = _gateway(decision_turn("auto_approve", ["R-000"], "done"))
    budget = _budget(tokens=100)
    budget.tokens_used = 100

    with pytest.raises(BudgetExceededError) as excinfo:
        _complete(gateway, budget)

    assert excinfo.value.result is None  # nothing was called, so nothing was spent


def test_anthropic_pricing_resolves_dated_snapshots() -> None:
    """A dated model id prices as its family, so metering survives a snapshot pin."""
    assert _price("claude-haiku-4-5-20251001") == _price("claude-haiku-4-5")


def test_anthropic_refuses_a_model_it_cannot_price() -> None:
    """No price on file means no enforceable cost ceiling — so the call does not happen."""
    with pytest.raises(AdapterError, match="cannot be metered"):
        _price("some-unlisted-model")
