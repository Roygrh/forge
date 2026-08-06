"""The record types MeridianERP stores.

These mirror the entities an AP clerk actually touches: a **vendor** (with the trust
tier and history the rules key on), a **purchase order**, the **goods receipts** posted
against it, and the **invoices** themselves. Nothing here knows what a rule is — these
are facts of the client's system of record, and the governed rules that interpret them
live in :mod:`app.rules`.

Money is :class:`~decimal.Decimal` throughout and is serialised to JSON as a string:
an audit figure rounded through a float is not an audit figure (the same convention the
API contract uses for ``total_cost_usd``).
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

#: How much of a relationship a vendor has earned. ``trusted`` is Meridian's top-20
#: list (>= 3 years, zero disputes); ``new`` is the first three invoices ever (R-002).
TrustTier = Literal["trusted", "standard", "new"]

#: What Meridian buys. ``utility`` and ``rent`` are the recurring non-PO spend R-030
#: is written for; the rest are ordinary PO-backed or service spend.
SpendCategory = Literal["mro", "utility", "rent", "freight", "services", "packaging"]

InvoiceStatus = Literal["received", "approved", "paid", "blocked"]


class _Record(BaseModel):
    """Base for every ERP record: immutable, and closed to unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def as_json(self) -> dict[str, Any]:
        """JSON-safe form for a tool result (dates as ISO, money as strings)."""
        return self.model_dump(mode="json")


class Vendor(_Record):
    """A vendor master record."""

    id: str
    name: str
    trust_tier: TrustTier
    # Decimal, not float: R-001 and R-044 compare it against exact thresholds (>= 3
    # years, < 1 year), and a boundary decided by binary floating point is a boundary
    # that can move.
    relationship_years: Decimal
    prior_invoice_count: int
    open_disputes: int
    category: SpendCategory
    #: The bank account Meridian has on file. An invoice asking to be paid somewhere
    #: else is the fact R-042 is written about — the ERP reports the difference, the
    #: rule decides what it means.
    bank_account_id: str
    #: The number a human calls to verify a bank change — "the number **on file**",
    #: never one taken from the invoice or the email that asked for the change (R-042).
    phone_on_file: str


class PurchaseOrder(_Record):
    """A purchase order: what was agreed, at what price."""

    number: str
    vendor_id: str
    description: str
    quantity_ordered: int
    unit_price_usd: Decimal
    total_usd: Decimal
    status: Literal["open", "closed"]
    issued_on: date


class GoodsReceipt(_Record):
    """Proof that goods actually arrived — the third leg of a three-way match."""

    id: str
    po_number: str
    quantity_received: int
    received_on: date


class Invoice(_Record):
    """One vendor invoice as MeridianERP holds it.

    ``id`` is the ERP's own key and is what a run is started with; ``number`` is the
    vendor's invoice number, which is *not* unique — two records sharing one is exactly
    the duplicate R-040 exists to catch.
    """

    id: str
    number: str
    vendor_id: str
    po_number: str | None
    amount_usd: Decimal
    currency: str
    quantity_billed: int | None
    category: SpendCategory
    #: Free text as the vendor wrote it, e.g. ``2/10 net 30``. The discount window is
    #: derived from it in app.erp.facts; the *threshold* for acting on it is R-050.
    payment_terms: str
    issue_date: date
    due_date: date
    received_date: date
    #: Where this invoice asks to be paid. Compared against the vendor's account on
    #: file to produce the bank-change fact.
    remit_to_bank_account_id: str
    status: InvoiceStatus
    #: Provenance for read_invoice: which document this record was captured from.
    source_document: str


class PostedAction(_Record):
    """One write MeridianERP accepted — an approval, a payment, an information request.

    The ERP keeps its own ledger of what Forge did to it. It is not the audit trail
    (that is the ``events`` table); it is the external system's state, which is what
    makes "``approve_invoice`` was never called" checkable from the other side too.
    """

    ref: str
    kind: Literal["approval", "payment", "info_request"]
    invoice_id: str
    actor: str
    detail: dict[str, Any]
