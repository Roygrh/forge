"""The append-only event log (ADR-008)."""

import uuid
from typing import Any

from sqlalchemy import BigInteger, Identity, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, TenantFk


class Event(Base):
    """One immutable record of something that happened.

    Events are the audit ground truth: every state transition and every agent decision
    is written here in the same transaction as the state row it describes, so run state,
    the approval queue, and lifecycle history are reconstructable from events alone
    (FR-G1, FR-G2).

    Immutability is enforced by the database, not by this class — the application role
    holds ``INSERT``/``SELECT`` only, and a trigger rejects ``UPDATE``/``DELETE`` even
    for the table owner. See the initial migration.
    """

    __tablename__ = "events"
    __table_args__ = (
        # The trace viewer reads a run's events in order (FR-G1).
        Index("ix_events_run_id_event_id", "run_id", "event_id"),
    )

    # Monotonic identity, not a UUID: ordering is part of the contract, and
    # GENERATED ALWAYS means application code cannot supply or reuse an id.
    event_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[TenantFk]
    occurred_at: Mapped[CreatedAt]
    type: Mapped[str] = mapped_column(
        comment="run.started, decision.made, approval.granted, version.published, ..."
    )
    actor: Mapped[str] = mapped_column(comment="system or user id")

    # Soft references: nullable and deliberately *not* foreign keys. Each event type
    # populates only the refs it concerns, and the audit log must never be
    # constrained — or made deletable — by the lifecycle of the rows it describes.
    run_id: Mapped[uuid.UUID | None] = mapped_column(comment="soft ref, nullable")
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(comment="soft ref, nullable")
    approval_id: Mapped[uuid.UUID | None] = mapped_column(comment="soft ref, nullable")

    payload: Mapped[dict[str, Any]] = mapped_column(comment="typed by event type")
