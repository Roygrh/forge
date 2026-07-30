"""Knowledge layer: collections and their retrievable chunks."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, UniqueConstraint
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
    content: Mapped[str]
    # Dimensionless on purpose: the embedding model is chosen with the knowledge layer
    # (Phase 4.3), and that choice fixes the dimension and the ANN index together.
    # Committing to a width now would be a guess baked into the schema.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), comment="pgvector, semantic")
    lexical_tsv: Mapped[str | None] = mapped_column(TSVECTOR, comment="full-text, lexical")
    created_at: Mapped[CreatedAt]
