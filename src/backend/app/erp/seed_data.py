"""The seeded contents of MeridianERP.

One frozen, hand-authored dataset. It is deliberately *not* random: every record exists
because a case in ``docs/01-discovery/06-eval-cases.md`` needs it, and the case each one
serves is named in a comment. That traceability is the point — the eval suite (Phase 4.5)
must be expressible against this data without inventing new fixtures for it.

Everything is dated against :data:`ERP_TODAY` rather than the wall clock: "the discount
window closes in two days" has to stay true on the day someone runs the demo, and a run
whose outcome depends on today's date is not reproducible.
"""

from datetime import date
from decimal import Decimal

from app.erp.records import GoodsReceipt, Invoice, PurchaseOrder, Vendor

#: The reference date MeridianERP believes it is. Due dates, discount windows, and the
#: duplicate lookback are all measured from here, so the seeded scenarios are stable
#: forever instead of decaying into "past due" a month after they were written.
ERP_TODAY = date(2026, 8, 6)

#: How far back "trailing 3-month average" looks for the recurring non-PO rule (R-030).
#: A window length, not a rule threshold: R-030 owns the ±15% band, the ERP owns what
#: "trailing 3 months" means for its own ledger.
TRAILING_AVERAGE_DAYS = 92

VENDORS: tuple[Vendor, ...] = (
    Vendor(
        id="V-1001",
        name="Grainger Industrial Supply",
        trust_tier="trusted",
        relationship_years=Decimal("8.5"),
        prior_invoice_count=412,
        open_disputes=0,
        category="mro",
        bank_account_id="BANK-GRA-001",
        phone_on_file="+1-614-555-0101",
    ),
    Vendor(
        id="V-1002",
        name="Fastenal Ohio",
        trust_tier="trusted",
        relationship_years=Decimal("6.0"),
        prior_invoice_count=288,
        open_disputes=0,
        category="mro",
        bank_account_id="BANK-FAS-001",
        phone_on_file="+1-614-555-0102",
    ),
    Vendor(
        id="V-1003",
        name="Buckeye Fasteners",
        trust_tier="standard",
        relationship_years=Decimal("2.4"),
        prior_invoice_count=34,
        open_disputes=0,
        category="mro",
        bank_account_id="BANK-BUC-001",
        phone_on_file="+1-614-555-0103",
    ),
    Vendor(
        id="V-1004",
        name="AEP Ohio",
        trust_tier="standard",
        relationship_years=Decimal("5.0"),
        prior_invoice_count=60,
        open_disputes=0,
        category="utility",
        bank_account_id="BANK-AEP-001",
        phone_on_file="+1-614-555-0104",
    ),
    # Brand new: E-11 turns on this vendor having no history at all.
    Vendor(
        id="V-1005",
        name="Novus Tooling",
        trust_tier="new",
        relationship_years=Decimal("0.2"),
        prior_invoice_count=0,
        open_disputes=0,
        category="mro",
        bank_account_id="BANK-NOV-001",
        phone_on_file="+1-614-555-0105",
    ),
    # Under a year of history — the population R-044's round-number guard is aimed at.
    Vendor(
        id="V-1006",
        name="Keystone Logistics",
        trust_tier="standard",
        relationship_years=Decimal("0.8"),
        prior_invoice_count=6,
        open_disputes=0,
        category="freight",
        bank_account_id="BANK-KEY-001",
        phone_on_file="+1-614-555-0106",
    ),
    # Long relationship, almost no invoices: E-12's "vendor with 2 prior invoices".
    Vendor(
        id="V-1007",
        name="Delta Facilities Services",
        trust_tier="standard",
        relationship_years=Decimal("3.1"),
        prior_invoice_count=2,
        open_disputes=0,
        category="services",
        bank_account_id="BANK-DEL-001",
        phone_on_file="+1-614-555-0107",
    ),
    Vendor(
        id="V-1008",
        name="Riverbend Packaging",
        trust_tier="standard",
        relationship_years=Decimal("1.6"),
        prior_invoice_count=9,
        open_disputes=0,
        category="packaging",
        bank_account_id="BANK-RIV-001",
        phone_on_file="+1-614-555-0108",
    ),
    # Just under a year, four invoices in: not trusted, not new — E-17's skimmer.
    Vendor(
        id="V-1009",
        name="Halcyon Components",
        trust_tier="standard",
        relationship_years=Decimal("0.9"),
        prior_invoice_count=4,
        open_disputes=0,
        category="mro",
        bank_account_id="BANK-HAL-001",
        phone_on_file="+1-614-555-0109",
    ),
)


def _po(
    number: str,
    vendor_id: str,
    description: str,
    quantity: int,
    unit_price: str,
    *,
    issued_on: date = date(2026, 7, 20),
    status: str = "open",
) -> PurchaseOrder:
    """Build a PO, deriving its total so a line and its total can never disagree."""
    unit = Decimal(unit_price)
    return PurchaseOrder(
        number=number,
        vendor_id=vendor_id,
        description=description,
        quantity_ordered=quantity,
        unit_price_usd=unit,
        total_usd=unit * quantity,
        status=status,  # type: ignore[arg-type]  # literal narrowed by the caller
        issued_on=issued_on,
    )


PURCHASE_ORDERS: tuple[PurchaseOrder, ...] = (
    _po("PO-8801", "V-1001", "Safety gloves, nitrile, box", 100, "40.00"),  # E-01
    _po("PO-8802", "V-1001", "Shop rags, industrial, case", 98, "19.00"),  # E-02
    _po("PO-8803", "V-1003", "Hex bolts M12, carton", 40, "80.00"),  # E-03
    _po("PO-8805", "V-1001", "Cutting fluid, 5 gal", 50, "40.00"),  # E-05
    _po("PO-8806", "V-1002", "Anchor bolts, pallet", 100, "50.00"),  # E-06
    _po("PO-8807", "V-1001", "Abrasive discs, box", 120, "10.00"),  # E-07
    _po("PO-8808", "V-1003", "Threaded rod, bundle", 74, "100.00"),  # E-08
    _po("PO-8809", "V-1001", "Warehouse racking, bay", 200, "60.00"),  # E-09
    _po("PO-8810", "V-1002", "Structural fasteners, skid", 310, "100.00"),  # E-10
    _po("PO-8811", "V-1005", "Carbide inserts, pack", 20, "30.00"),  # E-11
    _po("PO-8814", "V-1001", "Lubricant, drum", 60, "40.00"),  # E-14
    _po("PO-8816", "V-1008", "Stretch wrap, roll", 25, "48.00"),  # E-16
    _po("PO-8817", "V-1009", "Bearing assemblies, unit", 90, "110.00"),  # E-17
    _po("PO-8820", "V-1001", "Hand tools, set", 60, "25.00"),  # E-18
)

GOODS_RECEIPTS: tuple[GoodsReceipt, ...] = (
    GoodsReceipt(
        id="GR-9001",
        po_number="PO-8801",
        quantity_received=100,
        received_on=date(2026, 7, 28),
    ),
    GoodsReceipt(
        id="GR-9002",
        po_number="PO-8802",
        quantity_received=98,
        received_on=date(2026, 7, 28),
    ),
    GoodsReceipt(
        id="GR-9003",
        po_number="PO-8803",
        quantity_received=40,
        received_on=date(2026, 7, 29),
    ),
    GoodsReceipt(
        id="GR-9005",
        po_number="PO-8805",
        quantity_received=50,
        received_on=date(2026, 7, 29),
    ),
    GoodsReceipt(
        id="GR-9006",
        po_number="PO-8806",
        quantity_received=100,
        received_on=date(2026, 7, 30),
    ),
    # E-07: 100 of the 120 billed units ever arrived.
    GoodsReceipt(
        id="GR-9007",
        po_number="PO-8807",
        quantity_received=100,
        received_on=date(2026, 7, 30),
    ),
    GoodsReceipt(
        id="GR-9008",
        po_number="PO-8808",
        quantity_received=74,
        received_on=date(2026, 7, 30),
    ),
    GoodsReceipt(
        id="GR-9009",
        po_number="PO-8809",
        quantity_received=200,
        received_on=date(2026, 7, 31),
    ),
    GoodsReceipt(
        id="GR-9010",
        po_number="PO-8810",
        quantity_received=310,
        received_on=date(2026, 7, 31),
    ),
    GoodsReceipt(
        id="GR-9011",
        po_number="PO-8811",
        quantity_received=20,
        received_on=date(2026, 8, 1),
    ),
    GoodsReceipt(
        id="GR-9014",
        po_number="PO-8814",
        quantity_received=60,
        received_on=date(2026, 5, 29),
    ),
    GoodsReceipt(
        id="GR-9016",
        po_number="PO-8816",
        quantity_received=25,
        received_on=date(2026, 8, 1),
    ),
    GoodsReceipt(
        id="GR-9017",
        po_number="PO-8817",
        quantity_received=90,
        received_on=date(2026, 8, 1),
    ),
    GoodsReceipt(
        id="GR-9020",
        po_number="PO-8820",
        quantity_received=60,
        received_on=date(2026, 7, 30),
    ),
)


def _invoice(
    invoice_id: str,
    number: str,
    vendor_id: str,
    amount: str,
    *,
    po_number: str | None = None,
    quantity_billed: int | None = None,
    category: str = "mro",
    payment_terms: str = "net 30",
    issue_date: date = date(2026, 8, 1),
    received_date: date = date(2026, 8, 3),
    remit_to: str | None = None,
    status: str = "received",
) -> Invoice:
    """Build an invoice, defaulting the boring fields.

    ``due_date`` is always 30 days after issue and ``remit_to`` defaults to the vendor's
    account on file, so a record only *differs* where a scenario needs it to — which
    means a reader can see the whole point of a record from the fields it overrides.
    """
    vendor = next(vendor for vendor in VENDORS if vendor.id == vendor_id)
    return Invoice(
        id=invoice_id,
        number=number,
        vendor_id=vendor_id,
        po_number=po_number,
        amount_usd=Decimal(amount),
        currency="USD",
        quantity_billed=quantity_billed,
        category=category,  # type: ignore[arg-type]  # literal narrowed by the caller
        payment_terms=payment_terms,
        issue_date=issue_date,
        due_date=date.fromordinal(issue_date.toordinal() + 30),
        received_date=received_date,
        remit_to_bank_account_id=remit_to or vendor.bank_account_id,
        status=status,  # type: ignore[arg-type]  # literal narrowed by the caller
        source_document=f"email/{number}.pdf",
    )


INVOICES: tuple[Invoice, ...] = (
    # --- Happy paths ----------------------------------------------------------
    # E-01: trusted vendor, PO 4,000.00 vs 4,032.00 -> 0.80% / $32 variance.
    _invoice("inv-0001", "INV-4401", "V-1001", "4032.00", po_number="PO-8801", quantity_billed=100),
    # E-02: $38 on a PO of 1,862.00 -> 2.04%, over the percentage band but under $50.
    _invoice("inv-0002", "INV-4402", "V-1001", "1900.00", po_number="PO-8802", quantity_billed=98),
    # E-03: mid-tier vendor, exact match, under the $5,000 tier cap.
    _invoice("inv-0003", "INV-4403", "V-1003", "3200.00", po_number="PO-8803", quantity_billed=40),
    # E-04: recurring utility, no PO, 6% above the trailing 3-month average of 1,200.00.
    _invoice("inv-0004", "INV-4404", "V-1004", "1272.00", category="utility"),
    # --- Tolerance and matching edges ----------------------------------------
    # E-05: 90.00 on 2,000.00 -> 4.5%, outside tolerance but inside the escalate band.
    _invoice("inv-0005", "INV-4405", "V-1001", "2090.00", po_number="PO-8805", quantity_billed=50),
    # E-06: 700.00 on 5,000.00 -> 14%, presumed wrong PO.
    _invoice("inv-0006", "INV-4406", "V-1002", "5700.00", po_number="PO-8806", quantity_billed=100),
    # E-07: priced exactly to PO, but billing 120 units against a receipt of 100.
    _invoice("inv-0007", "INV-4407", "V-1001", "1200.00", po_number="PO-8807", quantity_billed=120),
    # E-08: mid-tier vendor over its $5,000 cap.
    _invoice("inv-0008", "INV-4408", "V-1003", "7400.00", po_number="PO-8808", quantity_billed=74),
    # --- Thresholds -----------------------------------------------------------
    # E-09: a perfect match a trusted vendor would normally auto-approve, at $12,000.
    _invoice(
        "inv-0009", "INV-4409", "V-1001", "12000.00", po_number="PO-8809", quantity_billed=200
    ),
    # E-10: $31,000 — over the controller threshold as well.
    _invoice(
        "inv-0010", "INV-4410", "V-1002", "31000.00", po_number="PO-8810", quantity_billed=310
    ),
    # --- New vendors and non-PO ----------------------------------------------
    # E-11: first invoice this vendor has ever sent, PO or not.
    _invoice("inv-0011", "INV-4411", "V-1005", "600.00", po_number="PO-8811", quantity_billed=20),
    # E-12: non-PO services from a vendor with 2 prior invoices.
    _invoice("inv-0012", "INV-4412", "V-1007", "900.00", category="services"),
    # E-13: non-PO over $2,000 from a vendor Meridian knows well.
    _invoice("inv-0013", "INV-4413", "V-1002", "2600.00", category="services"),
    # --- Duplicates and fraud patterns ---------------------------------------
    # E-14: the original INV-4471, paid in June...
    _invoice(
        "inv-0014",
        "INV-4471",
        "V-1001",
        "2400.00",
        po_number="PO-8814",
        quantity_billed=60,
        issue_date=date(2026, 5, 28),
        received_date=date(2026, 6, 2),
        status="paid",
    ),
    # ...and the resend that arrives in August under the same number.
    _invoice("inv-0015", "INV-4471", "V-1001", "2400.00", po_number="PO-8814", quantity_billed=60),
    # E-15: 1,250.00 on the 30th...
    _invoice(
        "inv-0016",
        "INV-4480",
        "V-1003",
        "1250.00",
        category="services",
        issue_date=date(2026, 7, 26),
        received_date=date(2026, 7, 30),
        status="paid",
    ),
    # ...and 1,250.00 again four days later, under a different number.
    _invoice("inv-0017", "INV-4492", "V-1003", "1250.00", category="services"),
    # E-16: asks to be paid into an account that is not the one on file.
    _invoice(
        "inv-0018",
        "INV-4501",
        "V-1008",
        "1200.00",
        po_number="PO-8816",
        quantity_billed=25,
        category="packaging",
        remit_to="BANK-RIV-002",
    ),
    # E-17: $9,900 — 1% under the $10,000 approval threshold, from a non-trusted vendor.
    _invoice("inv-0019", "INV-4510", "V-1009", "9900.00", po_number="PO-8817", quantity_billed=90),
    # --- Urgency --------------------------------------------------------------
    # E-18: 2/10 terms issued 2026-07-29, so the discount window closes in two days.
    _invoice(
        "inv-0020",
        "INV-4520",
        "V-1001",
        "1500.00",
        po_number="PO-8820",
        quantity_billed=60,
        payment_terms="2/10 net 30",
        issue_date=date(2026, 7, 29),
        received_date=date(2026, 7, 31),
    ),
    # --- No rule matches ------------------------------------------------------
    # E-20: trusted vendor, no PO, freight (so not the recurring-utility rule), under
    # every amount threshold, no duplicate or fraud signal. Nothing in the rule set
    # speaks to it — which is the case, and the answer is escalate (R-091).
    _invoice("inv-0021", "INV-4530", "V-1002", "900.00", category="freight"),
    # --- Round-number guard ---------------------------------------------------
    # Not one of the 20 cases, but R-044 has to be exercisable: exactly $2,500 from a
    # vendor with under a year of history.
    _invoice("inv-0022", "INV-4540", "V-1006", "2500.00", category="freight"),
    # --- History the trailing-average fact is computed from (E-04) ------------
    _invoice(
        "inv-0023",
        "INV-4390",
        "V-1004",
        "1150.00",
        category="utility",
        issue_date=date(2026, 5, 4),
        received_date=date(2026, 5, 8),
        status="paid",
    ),
    _invoice(
        "inv-0024",
        "INV-4392",
        "V-1004",
        "1200.00",
        category="utility",
        issue_date=date(2026, 6, 4),
        received_date=date(2026, 6, 8),
        status="paid",
    ),
    _invoice(
        "inv-0025",
        "INV-4394",
        "V-1004",
        "1250.00",
        category="utility",
        issue_date=date(2026, 7, 4),
        received_date=date(2026, 7, 8),
        status="paid",
    ),
)

#: The invoice the demo's Run button sends — E-01, the case the whole story opens with.
DEMO_INVOICE_ID = "inv-0001"
