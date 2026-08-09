"""the knowledge layer: conflict metadata and remediation items

Two additions for Phase 4.3 (FR-D1..D5):

* ``knowledge_chunks`` gains ``topic``, ``declared_value``, and ``effective_date``.
  ``topic``/``declared_value`` are the conflict-detection key: two retrieved chunks that
  share a topic but declare different values are the same question answered differently
  — a conflict to resolve by authority or to surface, never to average (FR-D2).
  ``effective_date`` completes the per-section metadata FR-D1 requires.

* ``remediation_items``: one row per detected conflict, flagging the stale document to
  its owner (FR-D5). A record, not a workflow. The unique index is NULLS NOT DISTINCT
  so an *unresolved* conflict (null winner) also dedupes across repeated retrievals.

Grants are explicit, as in 0002: ``GRANT ... ON ALL TABLES`` in 0001 covered only the
tables that existed then.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "forge_app"

# SELECT + INSERT + UPDATE: retrieval reads, conflict detection inserts, and an owner
# eventually marks an item resolved. No DELETE — a flagged conflict is closed, not erased.
GRANT_REMEDIATION = f"GRANT SELECT, INSERT, UPDATE ON TABLE remediation_items TO {APP_ROLE};"
REVOKE_REMEDIATION = f"REVOKE ALL ON TABLE remediation_items FROM {APP_ROLE};"


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "topic",
            sa.Text(),
            nullable=True,
            comment="conflict-detection key: the question this chunk answers",
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "declared_value",
            sa.Text(),
            nullable=True,
            comment="the answer this chunk declares for its topic, normalised for comparison",
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "effective_date",
            sa.Date(),
            nullable=True,
            comment="when this section took effect (FR-D1)",
        ),
    )
    op.create_index(op.f("ix_knowledge_chunks_topic"), "knowledge_chunks", ["topic"], unique=False)

    op.create_table(
        "remediation_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "topic", sa.Text(), nullable=False, comment="the question the sources disagree on"
        ),
        sa.Column(
            "stale_source_ref",
            sa.Text(),
            nullable=False,
            comment="document flagged for remediation",
        ),
        sa.Column("stale_authority_level", sa.Text(), nullable=False),
        sa.Column("stale_declared_value", sa.Text(), nullable=True),
        sa.Column(
            "winning_source_ref",
            sa.Text(),
            nullable=True,
            comment="the source that governed; null when authority could not resolve",
        ),
        sa.Column("winning_authority_level", sa.Text(), nullable=True),
        sa.Column("winning_declared_value", sa.Text(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=True, comment="who owns the stale document (FR-D1)"),
        sa.Column("status", sa.Text(), nullable=False, comment="open | resolved"),
        sa.Column(
            "detail",
            sa.Text(),
            nullable=True,
            comment="human-readable account of the conflict",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_remediation_items_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_remediation_items")),
    )
    op.create_index(
        op.f("ix_remediation_items_tenant_id"), "remediation_items", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_remediation_items_conflict",
        "remediation_items",
        ["tenant_id", "topic", "stale_source_ref", "winning_source_ref"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.execute(GRANT_REMEDIATION)


def downgrade() -> None:
    op.execute(REVOKE_REMEDIATION)
    op.drop_index("uq_remediation_items_conflict", table_name="remediation_items")
    op.drop_index(op.f("ix_remediation_items_tenant_id"), table_name="remediation_items")
    op.drop_table("remediation_items")
    op.drop_index(op.f("ix_knowledge_chunks_topic"), table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "effective_date")
    op.drop_column("knowledge_chunks", "declared_value")
    op.drop_column("knowledge_chunks", "topic")
