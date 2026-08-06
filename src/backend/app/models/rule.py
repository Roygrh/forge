"""Governed business rules, stored as queryable data.

The captured tacit rules (``docs/01-discovery/04-tacit-rules.md``) live here as rows,
not as Python branches. An agent retrieves them through the tool gateway and reasons
over what it retrieved, so **changing a rule is a data change**: update the row, and the
next run decides differently with no code change, no rebuild, and no redeploy.

The relationship to ``knowledge_chunks``: this table is the *structured* half of the
knowledge layer — exact lookups and machine-evaluable conditions, which is what a
threshold needs. Phase 4.3 adds the *semantic* half (policy documents, embeddings,
authority-ranked retrieval over prose) alongside it; ``authority_level`` is on both
tables and on the same scale, so a conflict between a rule and a document is rankable
(FR-D2, R-090).
"""

from typing import Any

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantFk, UuidPk


class Rule(Base):
    """One governed rule: its identity, its statement, and what it implies."""

    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_id"),)

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    rule_id: Mapped[str] = mapped_column(index=True, comment="R-xxx, cited in decisions")
    family: Mapped[str] = mapped_column(
        comment="vendor_trust | matching | thresholds | non_po | duplicates_fraud | urgency | meta"
    )
    kind: Mapped[str] = mapped_column(comment="business | definition | meta")
    statement: Mapped[str] = mapped_column(comment="verbatim from the owning document")
    authority_level: Mapped[str] = mapped_column(
        comment="sme_validated | policy_2023 | policy_2019 — same scale as knowledge_chunks"
    )
    version: Mapped[str] = mapped_column(comment="semver of the rule set this row belongs to")
    # The conditions and the actions they imply. jsonb for the same reason DNA is jsonb:
    # the shape is owned by a schema (app/rules/model.py), and shredding a condition tree
    # into columns would fork that definition.
    clauses: Mapped[list[dict[str, Any]]] = mapped_column(
        comment="ordered [{when, action, note}]; first match wins"
    )
    cites: Mapped[list[str]] = mapped_column(
        comment="rule ids cited alongside this one when it fires"
    )
    source_ref: Mapped[str | None] = mapped_column(comment="owning document and anchor")
    created_at: Mapped[CreatedAt]
