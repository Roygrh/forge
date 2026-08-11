"""Metrics endpoints: the operational dashboard, derived from events (FR-G3).

Two reads and no writes. ``GET /metrics`` serves every agent plus the same numbers
overall; ``GET /agents/{agentId}/metrics`` serves one agent's row. Both are computed
from the append-only event log at request time — there is no counters table to be
stale, and no number the audit trail cannot reproduce (ADR-008). ``recent_runs`` on
each row carries real run ids, so every figure on the dashboard resolves back to the
traces that produced it (FR-G1).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status

from app.api.deps import ActorDep
from app.api.errors import ApiError
from app.api.schemas import (
    AgentMetricsResponse,
    MetricsReportResponse,
    MetricsSummaryResponse,
)
from app.db import SessionDep
from app.governance import Permission
from app.observability import collect_metrics

router = APIRouter(tags=["Metrics"])


@router.get(
    "/metrics",
    response_model=MetricsReportResponse,
    summary="Per-agent operational metrics plus the overall picture, derived from events",
)
async def get_metrics(session: SessionDep, actor: ActorDep) -> MetricsReportResponse:
    """The whole dashboard in one request.

    Every agent in the catalog appears, runs or no runs: an operator scanning for
    trouble needs the quiet agents on the screen too.
    """
    actor.require(Permission.READ)
    report = await collect_metrics(session)
    return MetricsReportResponse(
        generated_at=datetime.now(UTC),
        overall=MetricsSummaryResponse.model_validate(report.overall.as_json()),
        agents=[AgentMetricsResponse.of(row) for row in report.agents],
    )


@router.get(
    "/agents/{agent_id}/metrics",
    response_model=AgentMetricsResponse,
    summary="One agent's metrics, state, and recent runs",
)
async def get_agent_metrics(
    agent_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> AgentMetricsResponse:
    """One agent's dashboard row, by the same projection as the full report."""
    actor.require(Permission.READ)
    report = await collect_metrics(session)
    for row in report.agents:
        if row.agent_id == agent_id:
            return AgentMetricsResponse.of(row)
    raise ApiError(status.HTTP_404_NOT_FOUND, "agent_not_found", f"no agent {agent_id}")
