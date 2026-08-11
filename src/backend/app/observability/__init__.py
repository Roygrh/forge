"""Observability and containment (FR-G3, FR-G4).

Two halves, one source. :mod:`app.observability.metrics` projects per-agent operational
metrics — runs, rates, cost, latency — from the append-only event log, and from nothing
else: there is no counters table to drift from the audit trail (ADR-008).
:mod:`app.observability.containment` is the circuit breaker and the suspend/resume
lifecycle transitions, which consume the same projection and write their own events.
"""

from app.observability.containment import (
    EVENT_RUN_REFUSED,
    EVENT_VERSION_RESUMED,
    EVENT_VERSION_SUSPENDED,
    BreakerTrip,
    evaluate_circuit_breaker,
    latest_suspensions,
    record_run_refusal,
    resume_version,
    suspend_version,
)
from app.observability.metrics import (
    AgentMetrics,
    MetricsReport,
    MetricsSummary,
    RunFacts,
    RunRef,
    collect_metrics,
    run_facts,
)

__all__ = [
    "EVENT_RUN_REFUSED",
    "EVENT_VERSION_RESUMED",
    "EVENT_VERSION_SUSPENDED",
    "AgentMetrics",
    "BreakerTrip",
    "MetricsReport",
    "MetricsSummary",
    "RunFacts",
    "RunRef",
    "collect_metrics",
    "evaluate_circuit_breaker",
    "latest_suspensions",
    "record_run_refusal",
    "resume_version",
    "run_facts",
    "suspend_version",
]
