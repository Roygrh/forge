"""MeridianERP — the simulated client system of record.

The C4 model puts MeridianERP *outside* Forge: it is the client's ERP, not part of the
platform. This module honours that boundary. It is an in-process simulation with its own
storage, its own ids, and its own ledger of what Forge did to it — deliberately **not**
tables in Forge's PostgreSQL, because Forge's schema
(``docs/02-architecture/data-model.md``) describes platform state, and a vendor master
is not platform state. Swapping this module for an HTTP client against a real ERP is
the only change that integration would need; nothing above the tool layer knows the
difference.

Deterministic and reconstructable: the read model is rebuilt from
:mod:`app.erp.seed_data` on demand, so the same invoice produces the same answer on
every machine, on every day (see :data:`~app.erp.seed_data.ERP_TODAY`).

Writes mutate the store, exactly as a real ERP would: approving an invoice twice is a
different situation from approving it once, and the demo must be able to show that.
:func:`reset_erp` puts the world back for a test.
"""

import itertools
from datetime import date
from decimal import Decimal
from typing import Any

from app.erp.records import GoodsReceipt, Invoice, PostedAction, PurchaseOrder, Vendor
from app.erp.seed_data import (
    ERP_TODAY,
    GOODS_RECEIPTS,
    INVOICES,
    PURCHASE_ORDERS,
    TRAILING_AVERAGE_DAYS,
    VENDORS,
)


class ErpError(Exception):
    """MeridianERP refused the call — unknown record, or a state it will not accept.

    Raised by the store and translated by the tool layer into a recorded gateway
    refusal, so an agent asking for an invoice that does not exist fails closed with a
    reason rather than receiving an empty result it might reason over.
    """


class ErpStore:
    """The simulated ERP's data and the writes Forge has posted to it."""

    def __init__(self) -> None:
        self._vendors = {vendor.id: vendor for vendor in VENDORS}
        self._purchase_orders = {po.number: po for po in PURCHASE_ORDERS}
        self._receipts = tuple(GOODS_RECEIPTS)
        self._invoices = {invoice.id: invoice for invoice in INVOICES}
        self._posted: list[PostedAction] = []
        self._refs = itertools.count(1)

    # --- Reads ---------------------------------------------------------------

    @property
    def today(self) -> date:
        """The date this ERP believes it is (fixed, so scenarios never decay)."""
        return ERP_TODAY

    def invoice(self, invoice_id: str) -> Invoice:
        """One invoice by ERP id."""
        found = self._invoices.get(invoice_id)
        if found is None:
            raise ErpError(f"no invoice {invoice_id!r} in MeridianERP")
        return found

    def vendor(self, vendor_id: str) -> Vendor:
        """One vendor master record."""
        found = self._vendors.get(vendor_id)
        if found is None:
            raise ErpError(f"no vendor {vendor_id!r} in MeridianERP")
        return found

    def purchase_order(self, po_number: str) -> PurchaseOrder:
        """One purchase order."""
        found = self._purchase_orders.get(po_number)
        if found is None:
            raise ErpError(f"no purchase order {po_number!r} in MeridianERP")
        return found

    def receipts(self, po_number: str) -> list[GoodsReceipt]:
        """Every goods receipt posted against a PO, oldest first."""
        return sorted(
            (receipt for receipt in self._receipts if receipt.po_number == po_number),
            key=lambda receipt: receipt.received_on,
        )

    def posted_actions(self) -> list[PostedAction]:
        """Everything Forge has written to this ERP, in order."""
        return list(self._posted)

    # --- Derived lookups the AP rules are evaluated against -------------------
    #
    # These answer questions *about the ledger* — "is there already an invoice with
    # this number?" — and stop there. What such an answer means (a duplicate, a resend,
    # a fraud attempt) is a rule's judgement, and rules live in app.rules as data.

    def invoices_sharing_number(self, invoice: Invoice) -> list[Invoice]:
        """Other invoices from the same vendor carrying the same invoice number."""
        return [
            other
            for other in self._invoices.values()
            if other.id != invoice.id
            and other.vendor_id == invoice.vendor_id
            and other.number == invoice.number
        ]

    def invoices_with_same_amount(self, invoice: Invoice) -> list[tuple[Invoice, int]]:
        """Earlier invoices from the same vendor for the same amount, with the gap in days.

        Ordered by proximity, so the caller reads the closest match first.
        """
        matches = [
            (other, (invoice.received_date - other.received_date).days)
            for other in self._invoices.values()
            if other.id != invoice.id
            and other.vendor_id == invoice.vendor_id
            and other.amount_usd == invoice.amount_usd
            and other.received_date <= invoice.received_date
        ]
        return sorted(matches, key=lambda item: item[1])

    def trailing_average(self, invoice: Invoice) -> Decimal | None:
        """Mean amount of this vendor's prior invoices of the same category.

        Scoped to the :data:`~app.erp.seed_data.TRAILING_AVERAGE_DAYS` window ending at
        the invoice's receipt date. ``None`` when there is no history to average — which
        is the honest answer, and one the rules can be written against (a rule that
        needs a baseline simply does not match without one).
        """
        window_start = date.fromordinal(invoice.received_date.toordinal() - TRAILING_AVERAGE_DAYS)
        prior = [
            other.amount_usd
            for other in self._invoices.values()
            if other.id != invoice.id
            and other.vendor_id == invoice.vendor_id
            and other.category == invoice.category
            and window_start <= other.received_date < invoice.received_date
        ]
        if not prior:
            return None
        return sum(prior, Decimal("0")) / len(prior)

    # --- Writes ---------------------------------------------------------------

    def approve_invoice(
        self, invoice_id: str, *, actor: str, detail: dict[str, Any]
    ) -> PostedAction:
        """Post an approval against an invoice.

        Refuses an invoice that is not in ``received`` state: approving something already
        approved, paid, or blocked is exactly the duplicate-payment incident Meridian is
        trying to stop, and the ERP declines it rather than trusting the caller.
        """
        invoice = self.invoice(invoice_id)
        if invoice.status != "received":
            raise ErpError(
                f"invoice {invoice.number} is {invoice.status}; only a received invoice "
                "can be approved"
            )
        self._invoices[invoice_id] = invoice.model_copy(update={"status": "approved"})
        return self._post("approval", invoice_id, actor, detail)

    def schedule_payment(
        self, invoice_id: str, *, actor: str, detail: dict[str, Any]
    ) -> PostedAction:
        """Schedule a payment for an approved invoice."""
        invoice = self.invoice(invoice_id)
        if invoice.status != "approved":
            raise ErpError(
                f"invoice {invoice.number} is {invoice.status}; only an approved invoice "
                "can be scheduled for payment"
            )
        self._invoices[invoice_id] = invoice.model_copy(update={"status": "paid"})
        return self._post("payment", invoice_id, actor, detail)

    def request_info(self, invoice_id: str, *, actor: str, detail: dict[str, Any]) -> PostedAction:
        """Record an outbound information request to the vendor."""
        self.invoice(invoice_id)  # existence check; the request is not tied to a state
        return self._post("info_request", invoice_id, actor, detail)

    def _post(self, kind: str, invoice_id: str, actor: str, detail: dict[str, Any]) -> PostedAction:
        action = PostedAction(
            ref=f"{kind.upper()[:3]}-{next(self._refs):04d}",
            kind=kind,  # type: ignore[arg-type]  # literal narrowed by the callers above
            invoice_id=invoice_id,
            actor=actor,
            detail=detail,
        )
        self._posted.append(action)
        return action


_store: ErpStore | None = None


def get_erp() -> ErpStore:
    """Return the process-wide MeridianERP.

    A singleton because the simulated ERP is *stateful*, like the system it stands in
    for: an invoice approved by one run is approved for the next one too. Rebuilding it
    per request would quietly erase that, and with it the ability to demonstrate a
    duplicate approval being refused.
    """
    global _store
    if _store is None:
        _store = ErpStore()
    return _store


def reset_erp() -> ErpStore:
    """Rebuild the ERP from its seed. For tests, and for restarting the demo cleanly."""
    global _store
    _store = ErpStore()
    return _store
