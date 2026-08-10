"""The tool registry and gateway — the only path from an agent to a tool (FR-C1)."""

from app.tools.contract import (
    ApprovalRelease,
    InvocationStatus,
    ToolContract,
    ToolExecutionError,
    ToolInput,
    ToolOutcome,
)
from app.tools.gateway import ToolGateway
from app.tools.meridian import (
    APPROVE_INVOICE_REF,
    GET_RECEIPTS_REF,
    GET_VENDOR_REF,
    MATCH_PO_REF,
    QUERY_RULES_REF,
    READ_INVOICE_REF,
    REQUEST_INFO_REF,
    SCHEDULE_PAYMENT_REF,
    meridian_tools,
)
from app.tools.registry import (
    GET_FACT,
    GET_FACT_NAME,
    GET_FACT_REF,
    ToolRegistry,
    build_tools,
)

__all__ = [
    "APPROVE_INVOICE_REF",
    "GET_FACT",
    "GET_FACT_NAME",
    "GET_FACT_REF",
    "GET_RECEIPTS_REF",
    "GET_VENDOR_REF",
    "MATCH_PO_REF",
    "QUERY_RULES_REF",
    "READ_INVOICE_REF",
    "REQUEST_INFO_REF",
    "SCHEDULE_PAYMENT_REF",
    "ApprovalRelease",
    "InvocationStatus",
    "ToolContract",
    "ToolExecutionError",
    "ToolGateway",
    "ToolInput",
    "ToolOutcome",
    "ToolRegistry",
    "build_tools",
    "meridian_tools",
]
