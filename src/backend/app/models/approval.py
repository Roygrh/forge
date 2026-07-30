"""Human-in-the-loop approvals."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantFk, UuidPk


class Approval(Base):
    """The approval a ``requires_approval`` tool invocation must obtain (FR-E2).

    ``expires_at`` is a server-side deadline. Expiry cancels — it never approves
    (FR-E3, fail-closed), and there is deliberately no extend operation.
    """

    __tablename__ = "approvals"
    # Exactly one approval per invocation (data-model.md: tool_invocations ||--o| approvals).
    __table_args__ = (UniqueConstraint("tool_invocation_id"),)

    id: Mapped[UuidPk]
    tenant_id: Mapped[TenantFk]
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_invocation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tool_invocations.id"))
    status: Mapped[str] = mapped_column(comment="pending | granted | rejected | expired")
    expires_at: Mapped[datetime] = mapped_column(comment="server-side, fail-closed")
    decision: Mapped[str | None] = mapped_column(comment="approve | reject, null until decided")
    decided_by: Mapped[str | None] = mapped_column(comment="actor")
    decided_at: Mapped[datetime | None]
    note: Mapped[str | None]
    created_at: Mapped[CreatedAt]
