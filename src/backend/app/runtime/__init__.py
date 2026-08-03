"""The agent runtime (ADR-003): the loop, its output contract, and its trace."""

from app.runtime.errors import EscalationReason, FailClosedError
from app.runtime.loop import AgentRuntime
from app.runtime.output import (
    DECISION_SCHEMA,
    MAX_OUTPUT_RETRIES,
    Decision,
    OutputValidationError,
    interpret,
)
from app.runtime.trace import TraceEvent, TraceRecorder, TraceStep, load_events, project_trace

__all__ = [
    "DECISION_SCHEMA",
    "MAX_OUTPUT_RETRIES",
    "AgentRuntime",
    "Decision",
    "EscalationReason",
    "FailClosedError",
    "OutputValidationError",
    "TraceEvent",
    "TraceRecorder",
    "TraceStep",
    "interpret",
    "load_events",
    "project_trace",
]
