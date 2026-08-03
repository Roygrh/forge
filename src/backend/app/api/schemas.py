"""Request and response bodies for the run endpoints.

Shapes follow ``docs/02-architecture/api/openapi.yaml`` — that contract is the source of
truth, and these models are its executable form (golden rule 5).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Run
from app.runtime.trace import TraceEvent, TraceStep

RunStatus = Literal["running", "awaiting_approval", "completed", "escalated", "canceled", "error"]


class StartRun(BaseModel):
    """Body of ``POST /runs``."""

    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    version: str = Field(description="Semver of a published version, e.g. 1.0.0")
    input: dict[str, Any] = Field(description="Trigger payload for this run")


class RunResponse(BaseModel):
    """A run's status and summary."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_version_id: uuid.UUID
    status: RunStatus
    trigger: str | None = None
    total_tokens: int | None = None
    total_cost_usd: Decimal | None = None
    started_at: datetime
    finished_at: datetime | None = None

    @classmethod
    def of(cls, run: Run) -> "RunResponse":
        """Project a run row onto the API contract."""
        return cls(
            id=run.id,
            tenant_id=run.tenant_id,
            agent_version_id=run.agent_version_id,
            status=run.status,  # type: ignore[arg-type]  # DB text; the enum is the contract
            trigger=run.trigger,
            total_tokens=run.total_tokens,
            total_cost_usd=run.total_cost_usd,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


class RunTraceResponse(BaseModel):
    """The ordered trace of a run — a projection of its append-only events (ADR-008).

    ``steps`` is the reasoning view (model calls, tool calls, the decision); ``events``
    is the raw log those steps were derived from, including the lifecycle events that
    are not steps. Serving both is what lets a reviewer check the projection against
    its source instead of trusting it.
    """

    run_id: uuid.UUID
    steps: list[TraceStep]
    events: list[TraceEvent]


class ErrorResponse(BaseModel):
    """The platform's error shape."""

    code: str = Field(description="Stable machine-readable error code")
    message: str
    details: dict[str, Any] | None = None
