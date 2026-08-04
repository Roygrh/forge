"""Request and response bodies for the agent and run endpoints.

Shapes follow ``docs/02-architecture/api/openapi.yaml`` — that contract is the source of
truth, and these models are its executable form (golden rule 5).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Agent, AgentVersion, Run
from app.runtime.trace import TraceEvent, TraceStep

RunStatus = Literal["running", "awaiting_approval", "completed", "escalated", "canceled", "error"]
AgentType = Literal["chatbot", "workflow", "autonomous"]
VersionStatus = Literal["draft", "published", "suspended"]


class AgentResponse(BaseModel):
    """One agent identity in the catalog. Behaviour lives in its versions, never here."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    slug: str
    name: str
    type: AgentType
    description: str | None = None
    created_at: datetime

    @classmethod
    def of(cls, agent: Agent) -> "AgentResponse":
        """Project an agent row onto the API contract."""
        return cls(
            id=agent.id,
            tenant_id=agent.tenant_id,
            slug=agent.slug,
            name=agent.name,
            type=agent.type,  # type: ignore[arg-type]  # DB text; the enum is the contract
            description=agent.description,
            created_at=agent.created_at,
        )


class AgentVersionResponse(BaseModel):
    """One immutable agent version, DNA included.

    The whole DNA document ships: it is the contract the runtime executed, so a viewer
    that wants to know what a version was *allowed* to do reads it here rather than
    inferring it from a run (golden rule 1).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    version: str = Field(description="Semver, e.g. 1.0.0")
    status: VersionStatus
    dna: dict[str, Any]
    published_eval_run_id: uuid.UUID | None = Field(
        default=None, description="The passing eval run that satisfied the publish gate, if any"
    )
    published_at: datetime | None = None
    created_at: datetime

    @classmethod
    def of(cls, version: AgentVersion) -> "AgentVersionResponse":
        """Project an agent-version row onto the API contract."""
        return cls(
            id=version.id,
            tenant_id=version.tenant_id,
            agent_id=version.agent_id,
            version=version.version,
            status=version.status,  # type: ignore[arg-type]  # DB text; the enum is the contract
            dna=version.dna,
            published_eval_run_id=version.published_eval_run_id,
            published_at=version.published_at,
            created_at=version.created_at,
        )


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
