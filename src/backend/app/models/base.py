"""Declarative base, constraint naming, and the shared column vocabulary.

Every table in ``docs/02-architecture/data-model.md`` maps here as a plain table
definition — no business methods, no relationship traversal. The data model is the
source of truth; these classes are its executable form.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import DateTime, ForeignKey, MetaData, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column

# Deterministic constraint names so migrations are readable and reversible.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all Forge tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Python annotation -> PostgreSQL type, so the models read as the data model does.
    type_annotation_map = {
        str: Text,  # data-model.md uses `text` throughout, never varchar(n)
        datetime: DateTime(timezone=True),  # timestamptz
        uuid.UUID: UUID(as_uuid=True),
        Decimal: Numeric(14, 6),  # money: exact, never float
        dict[str, Any]: JSONB,  # dna / model_call / decision / args / result / payload
        list[str]: JSONB,
        list[dict[str, Any]]: JSONB,
    }


# --- Shared column vocabulary -------------------------------------------------

UuidPk = Annotated[
    uuid.UUID,
    mapped_column(primary_key=True, server_default=text("gen_random_uuid()")),
]

# NFR-4: every business table carries tenant_id, so the schema is multi-tenant-ready
# while a single tenant is active. Indexed because it filters every query.
TenantFk = Annotated[
    uuid.UUID,
    mapped_column(ForeignKey("tenants.tenant_id"), nullable=False, index=True),
]

CreatedAt = Annotated[
    datetime,
    mapped_column(server_default=func.now(), nullable=False),
]
