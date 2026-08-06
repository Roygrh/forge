"""governed rules as queryable data

Adds the ``rules`` table: Meridian's captured tacit rules (R-001 … R-092) stored as
rows an agent retrieves and reasons over, rather than as branches in Python. See
``app/models/rule.py`` for why the condition tree is ``jsonb`` and how this table
relates to ``knowledge_chunks``.

The application role's grants are extended explicitly. ``GRANT ... ON ALL TABLES`` in
0001 applied to the tables that existed then; a table added later is not covered by it,
and a silently unreadable rule set would fail closed but for the wrong reason.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "forge_app"

GRANT_RULES = f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE rules TO {APP_ROLE};"
REVOKE_RULES = f"REVOKE ALL ON TABLE rules FROM {APP_ROLE};"


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False, comment="R-xxx, cited in decisions"),
        sa.Column(
            "family",
            sa.Text(),
            nullable=False,
            comment=(
                "vendor_trust | matching | thresholds | non_po | duplicates_fraud | urgency | meta"
            ),
        ),
        sa.Column("kind", sa.Text(), nullable=False, comment="business | definition | meta"),
        sa.Column(
            "statement", sa.Text(), nullable=False, comment="verbatim from the owning document"
        ),
        sa.Column(
            "authority_level",
            sa.Text(),
            nullable=False,
            comment=("sme_validated | policy_2023 | policy_2019 — same scale as knowledge_chunks"),
        ),
        sa.Column(
            "version",
            sa.Text(),
            nullable=False,
            comment="semver of the rule set this row belongs to",
        ),
        sa.Column(
            "clauses",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="ordered [{when, action, note}]; first match wins",
        ),
        sa.Column(
            "cites",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="rule ids cited alongside this one when it fires",
        ),
        sa.Column("source_ref", sa.Text(), nullable=True, comment="owning document and anchor"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.tenant_id"], name=op.f("fk_rules_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules")),
        sa.UniqueConstraint("tenant_id", "rule_id", name=op.f("uq_rules_tenant_id_rule_id")),
    )
    op.create_index(op.f("ix_rules_rule_id"), "rules", ["rule_id"], unique=False)
    op.create_index(op.f("ix_rules_tenant_id"), "rules", ["tenant_id"], unique=False)

    op.execute(GRANT_RULES)


def downgrade() -> None:
    op.execute(REVOKE_RULES)
    op.drop_index(op.f("ix_rules_tenant_id"), table_name="rules")
    op.drop_index(op.f("ix_rules_rule_id"), table_name="rules")
    op.drop_table("rules")
