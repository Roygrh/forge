"""The tool registry and gateway — the only path from an agent to a tool (FR-C1)."""

from app.tools.contract import InvocationStatus, ToolContract, ToolOutcome
from app.tools.gateway import ToolGateway
from app.tools.registry import GET_FACT, GET_FACT_NAME, GET_FACT_REF, ToolRegistry

__all__ = [
    "GET_FACT",
    "GET_FACT_NAME",
    "GET_FACT_REF",
    "InvocationStatus",
    "ToolContract",
    "ToolGateway",
    "ToolOutcome",
    "ToolRegistry",
]
