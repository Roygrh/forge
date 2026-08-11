"""eval cases carry their run input

Phase 4.5 makes the eval suite executable. A case that is to be *run*, not merely
described, must state the trigger payload it sends — the invoice id from the seeded
MeridianERP, or the policy question for E-19. Without it the runner would have to map
case codes to inputs in code, which would put half of each case outside the table the
publish gate reads.

Added as a column rather than folded into ``scenario`` because the two answer different
questions: ``scenario`` is prose for a human, ``input`` is the exact JSON the runner
POSTs into the runtime, byte for byte.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The table has never been seeded before this phase, so it is empty everywhere this
    # migration can run; NOT NULL needs no backfill. A case without an input cannot be
    # executed, and an inexecutable case would satisfy no publish gate.
    op.add_column(
        "eval_cases",
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="the run input this case sends, e.g. {invoice_id: inv-0001}",
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_cases", "input")
