"""Agent identity and its immutable versions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantFk, UuidPk


class Agent(Base):
    """An agent identity. Behaviour lives in its versions, never here."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    slug: Mapped[str]
    name: Mapped[str]
    type: Mapped[str] = mapped_column(comment="chatbot | workflow | autonomous")
    description: Mapped[str | None]
    created_at: Mapped[CreatedAt]


class AgentVersion(Base):
    """One immutable version of an agent's DNA.

    The DNA document is stored whole as ``jsonb``: ``dna-schema.json`` is the single
    authority on its structure and validates it at write time, so shredding it into
    columns would fork the contract (data-model.md). A run binds to the exact version
    that produced it (FR-A3), which is what makes a historical decision reproducible.
    """

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version"),
        # The relational guarantee about DNA is deliberately thin — it asserts only
        # that the stored value is a JSON object. Structure is the JSON Schema's job.
        CheckConstraint("jsonb_typeof(dna) = 'object'", name="dna_is_object"),
    )

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[str] = mapped_column(comment="semver")
    dna: Mapped[dict[str, Any]] = mapped_column(comment="validated vs dna-schema.json at write")
    status: Mapped[str] = mapped_column(comment="draft | published | suspended")
    # Publish-gate evidence (FR-F2): the passing eval run that permitted publishing.
    # Nullable because a draft has none. This FK closes a cycle with eval_runs
    # (which references agent_versions), so it is added by ALTER TABLE.
    published_eval_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("eval_runs.id", use_alter=True),
        comment="gate evidence, nullable",
    )
    published_at: Mapped[datetime | None]
    created_at: Mapped[CreatedAt]
