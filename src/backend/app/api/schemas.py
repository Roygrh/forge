"""Request and response bodies for the agent, run, and knowledge endpoints.

Shapes follow ``docs/02-architecture/api/openapi.yaml`` — that contract is the source of
truth, and these models are its executable form (golden rule 5).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    Agent,
    AgentVersion,
    KnowledgeChunk,
    KnowledgeCollection,
    RemediationItem,
    Run,
)
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


class KnowledgeCollectionResponse(BaseModel):
    """One governed knowledge collection with its authority metadata (FR-D1)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    slug: str
    name: str
    authority_level: str
    owner: str | None = None
    created_at: datetime

    @classmethod
    def of(cls, collection: KnowledgeCollection) -> "KnowledgeCollectionResponse":
        """Project a collection row onto the API contract."""
        return cls(
            id=collection.id,
            tenant_id=collection.tenant_id,
            slug=collection.slug,
            name=collection.name,
            authority_level=collection.authority_level,
            owner=collection.owner,
            created_at=collection.created_at,
        )


class KnowledgeChunkResponse(BaseModel):
    """One knowledge chunk, resolvable from a citation.

    This is the verifiability endpoint for FR-D4: a citation in a decision names a
    chunk id (via the trace's retrieval step), and this shape is what a human opens to
    check the claim against its source — content, section, owner, date, authority.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    citation: str = Field(description="The citable reference: rule ID or document#section")
    source_ref: str | None = None
    section: str | None = None
    rule_id: str | None = None
    authority_level: str
    topic: str | None = None
    declared_value: str | None = None
    effective_date: date | None = None
    content: str
    created_at: datetime

    @classmethod
    def of(cls, chunk: KnowledgeChunk) -> "KnowledgeChunkResponse":
        """Project a chunk row onto the API contract."""
        return cls(
            id=chunk.id,
            tenant_id=chunk.tenant_id,
            collection_id=chunk.collection_id,
            citation=chunk.rule_id or chunk.source_ref or "unknown",
            source_ref=chunk.source_ref,
            section=chunk.section,
            rule_id=chunk.rule_id,
            authority_level=chunk.authority_level,
            topic=chunk.topic,
            declared_value=chunk.declared_value,
            effective_date=chunk.effective_date,
            content=chunk.content,
            created_at=chunk.created_at,
        )


class RemediationItemResponse(BaseModel):
    """One flagged knowledge conflict, addressed to the stale document's owner (FR-D5)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    topic: str
    stale_source_ref: str
    stale_authority_level: str
    stale_declared_value: str | None = None
    winning_source_ref: str | None = Field(
        default=None, description="Null when authority could not resolve the conflict"
    )
    winning_authority_level: str | None = None
    winning_declared_value: str | None = None
    owner: str | None = None
    status: str
    detail: str | None = None
    created_at: datetime

    @classmethod
    def of(cls, item: RemediationItem) -> "RemediationItemResponse":
        """Project a remediation row onto the API contract."""
        return cls(
            id=item.id,
            tenant_id=item.tenant_id,
            topic=item.topic,
            stale_source_ref=item.stale_source_ref,
            stale_authority_level=item.stale_authority_level,
            stale_declared_value=item.stale_declared_value,
            winning_source_ref=item.winning_source_ref,
            winning_authority_level=item.winning_authority_level,
            winning_declared_value=item.winning_declared_value,
            owner=item.owner,
            status=item.status,
            detail=item.detail,
            created_at=item.created_at,
        )


class ErrorResponse(BaseModel):
    """The platform's error shape."""

    code: str = Field(description="Stable machine-readable error code")
    message: str
    details: dict[str, Any] | None = None
