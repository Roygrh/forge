"""Tenant table."""

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class Tenant(Base):
    """An owning organisation.

    One tenant is active (Meridian Supply Co.); the structure is multi-tenant-ready
    (NFR-4).
    """

    __tablename__ = "tenants"

    # Note the column name: tenants are keyed by `tenant_id`, and every other
    # business table's `tenant_id` points here.
    tenant_id: Mapped[UuidPk]
    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    created_at: Mapped[CreatedAt]
