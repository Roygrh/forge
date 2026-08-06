"""governance refusals as run steps

Adds ``run_steps.governance``: the reason code, the plain-language explanation, and the
circumstance behind every platform refusal. A block is a *step* of the run — it has a
position in the order and it is what happened next — so it belongs in the same table as
the reasoning and the tool calls rather than being inferred from a terminal status.

The matching ``governance.blocked`` event is written in the same transaction (ADR-008),
and the trace API projects the step from that event, not from this column.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_steps",
        sa.Column(
            "governance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="reason_code, explanation, detail — why the platform stopped (FR-C5)",
        ),
    )
    # `kind` is text with no CHECK by design (the vocabulary lives in the application,
    # like every other enum here); the comment is the schema's own documentation of it.
    op.alter_column(
        "run_steps",
        "kind",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment="reason | tool | decision | governance",
        existing_comment="reason | tool | decision",
    )


def downgrade() -> None:
    op.alter_column(
        "run_steps",
        "kind",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment="reason | tool | decision",
        existing_comment="reason | tool | decision | governance",
    )
    op.drop_column("run_steps", "governance")
