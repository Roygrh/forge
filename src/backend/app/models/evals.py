"""Evaluation suites, cases, and runs — the publish gate's evidence."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantFk, UuidPk


class EvalSuite(Base):
    """A versioned set of evaluation cases an agent version must pass (FR-F1)."""

    __tablename__ = "eval_suites"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", "version"),)

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    slug: Mapped[str]
    name: Mapped[str]
    version: Mapped[str] = mapped_column(comment="semver")
    created_at: Mapped[CreatedAt]


class EvalCase(Base):
    """One case: a scenario, the action expected, and what must never be called.

    Cases are written before the agent exists (charter §8, Phase 1) and are never
    weakened to make a version pass.
    """

    __tablename__ = "eval_cases"
    __table_args__ = (UniqueConstraint("suite_id", "code"),)

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    suite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_suites.id"), index=True)
    code: Mapped[str] = mapped_column(comment="E-xx")
    scenario: Mapped[str]
    expected_action: Mapped[str]
    expected_citations: Mapped[list[str] | None] = mapped_column(comment="R-xxx list")
    must_not_call: Mapped[list[str] | None] = mapped_column(comment="e.g. approve_invoice")


class EvalRun(Base):
    """One scoring of one suite against one agent version.

    ``passed`` is what the publish gate reads (FR-F2). Per-case detail stays inline as
    ``case_results`` until per-case trend analytics is a real read pattern
    (data-model.md, open question).
    """

    __tablename__ = "eval_runs"

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    suite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_suites.id"), index=True)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), index=True)
    status: Mapped[str] = mapped_column(comment="running | completed")
    passed: Mapped[bool | None] = mapped_column(comment="publish-gate result")
    total: Mapped[int | None]
    passed_count: Mapped[int | None]
    case_results: Mapped[list[dict[str, Any]] | None] = mapped_column(
        comment="per-case pass/fail detail"
    )
    created_at: Mapped[CreatedAt]
