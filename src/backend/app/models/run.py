"""Execution tables: runs, their steps, and the tool calls those steps issue."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantFk, UuidPk


class Run(Base):
    """One execution of one agent version.

    Bound to ``agent_version_id``, not to the agent: the DNA that made a decision is
    always recoverable (FR-A3).
    """

    __tablename__ = "runs"

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), index=True)
    status: Mapped[str] = mapped_column(
        comment="running | awaiting_approval | completed | escalated | canceled | error"
    )
    trigger: Mapped[str | None]
    total_tokens: Mapped[int | None]
    total_cost_usd: Mapped[Decimal | None]
    started_at: Mapped[CreatedAt]
    finished_at: Mapped[datetime | None]


class RunStep(Base):
    """One iteration of the reasoning loop: a reason, tool, or decision step."""

    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "step_no"),)

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    step_no: Mapped[int]
    kind: Mapped[str] = mapped_column(comment="reason | tool | decision")
    model_call: Mapped[dict[str, Any] | None] = mapped_column(comment="model, tokens, cost")
    decision: Mapped[dict[str, Any] | None] = mapped_column(
        comment="action plus rule citations (R-xxx); a decision without citations is a bug"
    )
    created_at: Mapped[CreatedAt]


class ToolInvocation(Base):
    """A single call through the tool gateway, recorded whether or not it executed.

    ``blocked`` and ``denied`` invocations are persisted on purpose: a reviewer must be
    able to see what the agent tried to do, not only what it was allowed to do.
    """

    __tablename__ = "tool_invocations"

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    run_step_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("run_steps.id"), index=True)
    tool_ref: Mapped[str] = mapped_column(comment="slug at semver")
    autonomy: Mapped[str] = mapped_column(comment="autonomous | requires_approval | forbidden")
    args: Mapped[dict[str, Any] | None]
    result: Mapped[dict[str, Any] | None]
    status: Mapped[str] = mapped_column(comment="validated | executed | blocked | denied")
    created_at: Mapped[CreatedAt]
