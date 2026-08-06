"""The LLM adapter layer (ADR-005): one contract, swappable providers, one budget."""

from app.llm.adapters.anthropic import AnthropicAdapter
from app.llm.adapters.base import LlmAdapter
from app.llm.adapters.demo import MeridianDemoAdapter
from app.llm.adapters.fake import FakeAdapter, ScriptedTurn, decision_turn, raw_turn, tool_turn
from app.llm.contract import (
    AdapterError,
    Budget,
    BudgetExceededError,
    CompletionResult,
    LlmGatewayError,
    Message,
    ModelSpec,
    ToolCall,
    ToolSpec,
    UnknownProviderError,
    Usage,
)
from app.llm.gateway import LlmGateway

__all__ = [
    "AdapterError",
    "AnthropicAdapter",
    "Budget",
    "BudgetExceededError",
    "CompletionResult",
    "FakeAdapter",
    "LlmAdapter",
    "LlmGateway",
    "LlmGatewayError",
    "MeridianDemoAdapter",
    "Message",
    "ModelSpec",
    "ScriptedTurn",
    "ToolCall",
    "ToolSpec",
    "UnknownProviderError",
    "Usage",
    "decision_turn",
    "raw_turn",
    "tool_turn",
]
