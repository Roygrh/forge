"""human approvals as run steps

Phase 4.4 gives the human in the loop a place in the run's own order. Adds
``run_steps.approval``: the parked action's deadline, and the approve / reject / expire
that answered it, with the actor and the timestamp (FR-E4). A person deciding is a step
of the run for the same reason a platform refusal is one — it has a position in the
order and it is what happened next.

The matching ``approval.pending`` / ``approval.granted`` / ``approval.rejected`` /
``approval.expired`` events are written in the same transaction (ADR-008), and the trace
API projects the step from those events rather than from this column.

Nothing is added to ``approvals`` itself: 0001 already created it with the server-side
``expires_at`` this phase enforces. Its grants are unchanged — the application role may
INSERT and UPDATE a row's status, and cannot DELETE one, so a decided approval is a
permanent record.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_steps",
        sa.Column(
            "approval",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="approval lifecycle: status, actor, decided_at, note, expires_at (FR-E4)",
        ),
    )
    # `kind` is text with no CHECK by design (the vocabulary lives in the application,
    # like every other enum here); the comment is the schema's own documentation of it.
    op.alter_column(
        "run_steps",
        "kind",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment="reason | tool | decision | governance | approval",
        existing_comment="reason | tool | decision | governance",
    )


def downgrade() -> None:
    op.alter_column(
        "run_steps",
        "kind",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment="reason | tool | decision | governance",
        existing_comment="reason | tool | decision | governance | approval",
    )
    op.drop_column("run_steps", "approval")
