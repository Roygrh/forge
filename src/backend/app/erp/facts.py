"""Turning ERP records into the flat fact sheet the governed rules are evaluated against.

This is the seam that keeps rules out of Python. A **fact** is something MeridianERP can
observe and state without judgement — "the price variance is 4.50%", "an invoice with
this number already exists for this vendor", "the remit-to account differs from the one
on file". A **rule** is what that means and what to do about it — "over 2% and over $50
is outside tolerance, escalate" — and every threshold in that sentence lives in the
rules data (:mod:`app.rules`), never here.

The test for whether something belongs in this module: could Meridian's AP manager
change her mind about it without the ERP changing? If yes, it is a rule, not a fact.
``2%``, ``$50``, ``$10,000``, ``7 days``, ``±15%`` are all rules. The arithmetic that
produces a variance percentage, and the query that finds a same-numbered invoice, are
facts.

Values are JSON-safe scalars. Money and percentages are carried as **strings** holding
exact decimal text: the rule engine compares them as :class:`~decimal.Decimal`, so no
threshold comparison is ever decided by a float.
"""

import re
from datetime import date
from decimal import Decimal

from app.erp.records import Invoice
from app.erp.store import ErpError, ErpStore

#: What a single fact may be. Deliberately scalar: a fact sheet is a flat namespace a
#: rule can point at with a dotted key, not a document a rule has to navigate.
FactValue = str | int | bool | None

#: Two decimal places for money and percentages — enough to express Meridian's
#: tolerances exactly, and stable to serialise.
_CENTS = Decimal("0.01")

#: Early-payment terms as vendors write them: "2/10 net 30" is 2% off within 10 days.
_DISCOUNT_TERMS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+)\b")


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENTS))


def _percent(numerator: Decimal, denominator: Decimal) -> str | None:
    """A percentage of ``denominator``, or ``None`` when there is nothing to divide by."""
    if denominator == 0:
        return None
    return str((numerator / denominator * 100).quantize(_CENTS))


def discount_window_days(invoice: Invoice, today: date) -> int | None:
    """Days left on an early-payment discount, or ``None`` when there is no live window.

    ``None`` covers both "these terms carry no discount" and "the window has already
    closed" — in either case there is no discount left to hurry for, and a rule keyed on
    a live window simply does not match.
    """
    match = _DISCOUNT_TERMS.match(invoice.payment_terms)
    if match is None:
        return None
    remaining = (invoice.issue_date.toordinal() + int(match.group(2))) - today.toordinal()
    return remaining if remaining >= 0 else None


def build_fact_sheet(store: ErpStore, invoice: Invoice) -> dict[str, FactValue]:
    """Everything MeridianERP can say about one invoice, as a flat, dotted namespace."""
    vendor = store.vendor(invoice.vendor_id)

    facts: dict[str, FactValue] = {
        "invoice.number": invoice.number,
        "invoice.amount_usd": _money(invoice.amount_usd),
        "invoice.currency": invoice.currency,
        "invoice.category": invoice.category,
        "invoice.has_po": invoice.po_number is not None,
        "invoice.days_past_due": (store.today - invoice.due_date).days,
        "invoice.discount_window_days": discount_window_days(invoice, store.today),
        "vendor.id": vendor.id,
        "vendor.name": vendor.name,
        "vendor.trust_tier": vendor.trust_tier,
        "vendor.relationship_years": str(vendor.relationship_years),
        "vendor.prior_invoice_count": vendor.prior_invoice_count,
        "vendor.open_disputes": vendor.open_disputes,
        # R-042's fact: the invoice asks to be paid somewhere other than the account on
        # file. The ERP reports the difference; the rule decides it is a hard stop.
        "vendor.bank_details_changed": (invoice.remit_to_bank_account_id != vendor.bank_account_id),
    }

    facts.update(_matching_facts(store, invoice))
    facts.update(_duplicate_facts(store, invoice))
    facts.update(_non_po_facts(store, invoice))
    return facts


def _matching_facts(store: ErpStore, invoice: Invoice) -> dict[str, FactValue]:
    """Three-way-match arithmetic: PO price against the invoice, receipts against it."""
    absent: dict[str, FactValue] = {
        "match.po_found": False,
        "match.price_variance_usd": None,
        "match.price_variance_pct": None,
        "match.quantity_billed": invoice.quantity_billed,
        "match.quantity_received": None,
        # A quantity that cannot be compared is not a quantity that checks out: the
        # fact stays False and any rule needing evidence of over-billing does not fire.
        "match.quantity_billed_over_received": False,
    }
    if invoice.po_number is None:
        return absent

    try:
        purchase_order = store.purchase_order(invoice.po_number)
    except ErpError:
        # A referenced PO that does not exist is a matching failure, not a crash: the
        # invoice claims a PO, so `has_po` is true while `po_found` is false, and the
        # rules can tell those two situations apart.
        return absent

    variance = invoice.amount_usd - purchase_order.total_usd
    received = sum(receipt.quantity_received for receipt in store.receipts(purchase_order.number))
    billed = invoice.quantity_billed

    return {
        "match.po_found": True,
        "match.po_number": purchase_order.number,
        "match.po_total_usd": _money(purchase_order.total_usd),
        # Absolute values: every tolerance rule is written about the *size* of the gap,
        # so signing them here would make each rule carry the sign handling instead.
        "match.price_variance_usd": _money(abs(variance)),
        "match.price_variance_pct": _percent(abs(variance), purchase_order.total_usd),
        "match.quantity_ordered": purchase_order.quantity_ordered,
        "match.quantity_billed": billed,
        "match.quantity_received": received,
        "match.quantity_billed_over_received": billed is not None and billed > received,
    }


def _duplicate_facts(store: ErpStore, invoice: Invoice) -> dict[str, FactValue]:
    """Whether this invoice has been seen before, by number or by amount and date."""
    same_number = store.invoices_sharing_number(invoice)
    same_amount = store.invoices_with_same_amount(invoice)

    return {
        "duplicate.invoice_number_exists": bool(same_number),
        "duplicate.matching_invoice_ids": ",".join(other.id for other in same_number) or None,
        # Days since the closest prior invoice for the identical amount, or None when
        # there is none. The *window* that makes it suspicious belongs to R-041.
        "duplicate.days_since_same_amount": same_amount[0][1] if same_amount else None,
        "duplicate.same_amount_invoice_id": same_amount[0][0].id if same_amount else None,
    }


def _non_po_facts(store: ErpStore, invoice: Invoice) -> dict[str, FactValue]:
    """The recurring-spend baseline a non-PO invoice is judged against."""
    average = store.trailing_average(invoice)
    if average is None:
        return {
            "nonpo.trailing_3m_avg_usd": None,
            "nonpo.variance_vs_trailing_avg_pct": None,
        }
    return {
        "nonpo.trailing_3m_avg_usd": _money(average),
        "nonpo.variance_vs_trailing_avg_pct": _percent(abs(invoice.amount_usd - average), average),
    }
