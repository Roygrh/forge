"""Knowledge layer: collections, their retrievable chunks, and remediation items."""

import uuid
from datetime import date

from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantFk, UuidPk


class KnowledgeCollection(Base):
    """A governed source of knowledge with an owner and an authority level (FR-D1)."""

    __tablename__ = "knowledge_collections"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    slug: Mapped[str]
    name: Mapped[str]
    authority_level: Mapped[str] = mapped_column(
        comment="sme_validated | policy_2023 | policy_2019"
    )
    owner: Mapped[str | None]
    created_at: Mapped[CreatedAt]


class KnowledgeChunk(Base):
    """One retrievable unit of knowledge, carrying both retrieval representations.

    Hybrid retrieval needs both: ``embedding`` for semantic similarity and
    ``lexical_tsv`` for exact terms such as vendor names and invoice numbers (FR-D3).
    ``authority_level`` is denormalised from the collection so conflict ranking is a
    local read (FR-D2), and ``rule_id`` lets a chunk be cited by ID (R-092, FR-D4).
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        # Lexical half of hybrid retrieval.
        Index("ix_knowledge_chunks_lexical_tsv", "lexical_tsv", postgresql_using="gin"),
    )

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_collections.id"), index=True
    )
    source_ref: Mapped[str | None] = mapped_column(comment="document or rule id")
    section: Mapped[str | None]
    rule_id: Mapped[str | None] = mapped_column(index=True, comment="R-xxx, nullable")
    authority_level: Mapped[str] = mapped_column(comment="denormalized for ranking")
    #: What question this chunk answers, when the ingestion pipeline knows. Two chunks
    #: sharing a ``topic`` with different ``declared_value``s are a detectable conflict
    #: (FR-D2): same question, different answers — never averaged, always surfaced.
    topic: Mapped[str | None] = mapped_column(
        index=True, comment="conflict-detection key: the question this chunk answers"
    )
    declared_value: Mapped[str | None] = mapped_column(
        comment="the answer this chunk declares for its topic, normalised for comparison"
    )
    effective_date: Mapped[date | None] = mapped_column(
        Date(), comment="when this section took effect (FR-D1)"
    )
    content: Mapped[str]
    # Dimensionless on purpose: the width is the embedding provider's property
    # (app/knowledge/embeddings.py), not the schema's. At this corpus size a sequential
    # scan beats maintaining an ANN index, so nothing forces a fixed dimension.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), comment="pgvector, semantic")
    lexical_tsv: Mapped[str | None] = mapped_column(TSVECTOR, comment="full-text, lexical")
    created_at: Mapped[CreatedAt]


class RemediationItem(Base):
    """One detected knowledge conflict, flagged to the stale document's owner (FR-D5).

    A record, not a workflow: the living-product principle is that a contradiction found
    at retrieval time becomes visible work for the knowledge owner, not a silent
    resolution. ``winning_source_ref`` is null when authority could not resolve the
    conflict — both documents are flagged and the run failed closed (R-091).
    """

    __tablename__ = "remediation_items"
    __table_args__ = (
        # One open item per (topic, stale doc, winner) — retrieval runs repeat, the
        # flag should not. NULLS NOT DISTINCT so unresolved conflicts dedupe too.
        Index(
            "uq_remediation_items_conflict",
            "tenant_id",
            "topic",
            "stale_source_ref",
            "winning_source_ref",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    topic: Mapped[str] = mapped_column(comment="the question the sources disagree on")
    stale_source_ref: Mapped[str] = mapped_column(comment="document flagged for remediation")
    stale_authority_level: Mapped[str]
    stale_declared_value: Mapped[str | None]
    winning_source_ref: Mapped[str | None] = mapped_column(
        comment="the source that governed; null when authority could not resolve"
    )
    winning_authority_level: Mapped[str | None]
    winning_declared_value: Mapped[str | None]
    owner: Mapped[str | None] = mapped_column(comment="who owns the stale document (FR-D1)")
    status: Mapped[str] = mapped_column(default="open", comment="open | resolved")
    detail: Mapped[str | None] = mapped_column(comment="human-readable account of the conflict")
    created_at: Mapped[CreatedAt]
