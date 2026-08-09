"""Meridian's AP policy documents, as seeded content — deliberately contradictory.

These are the "PDFs" of the simulation (``01-client-profile.md``,
``04-tacit-rules.md`` closing section): an outdated **AP-Policy-2019** and a current
**AP-Policy-2023**, written so they conflict with each other and with the SME-validated
rules on exactly the points the discovery documents name:

===========================  ======================  ======================  =================
topic                        AP-Policy-2019          AP-Policy-2023          SME rules
===========================  ======================  ======================  =================
``approval_threshold``       $5,000                  $10,000                 $10,000 (R-020)
``trusted_vendor_exception`` none — same path for    trusted tier exists,    exists (R-001)
                             every vendor            auto-approves in band
``three_way_match``          mandatory, every        required above $2,500   —
                             invoice                 only
===========================  ======================  ======================  =================

The contradictions are the *point*: they are what authority-ranked retrieval resolves
(R-090), what the trace surfaces, and what the remediation loop flags to the stale
document's owner (FR-D5). Do not "fix" them.

Each section carries its own metadata — owner, effective date, authority level — because
FR-D1 requires ingestion to preserve exactly that, and because conflict detection needs
a machine-comparable ``(topic, declared_value)`` pair per section. Where two sections
*agree* they declare the same value string; where they conflict they cannot, and the
difference is the detection signal. Prose is free; the declared value is data.
"""

from dataclasses import dataclass, field
from datetime import date

from app.rules.model import AuthorityLevel


@dataclass(frozen=True)
class PolicySection:
    """One section of a policy document — the unit structure-aware chunking preserves."""

    anchor: str
    """Stable slug for citations: ``AP-Policy-2023.pdf#approval-thresholds``."""

    heading: str
    body: str

    topic: str | None = None
    """The question this section answers, when it answers one machine-comparably."""

    declared_value: str | None = None
    """The answer it declares — the comparable half of conflict detection (FR-D2)."""


@dataclass(frozen=True)
class PolicyDocument:
    """One policy document with the metadata FR-D1 requires ingestion to keep."""

    source_ref: str
    collection_slug: str
    title: str
    owner: str
    authority_level: AuthorityLevel
    effective_date: date
    sections: list[PolicySection] = field(default_factory=list)


AP_POLICY_2019 = PolicyDocument(
    source_ref="AP-Policy-2019.pdf",
    collection_slug="ap-policy-2019",
    title="Meridian Supply Co. — Accounts Payable Policy (2019)",
    owner="Finance Policy Office — Dana Whitfield, CFO",
    authority_level="policy_2019",
    effective_date=date(2019, 3, 1),
    sections=[
        PolicySection(
            anchor="purpose-and-scope",
            heading="1. Purpose and scope",
            body=(
                "This policy governs the processing, verification, and approval of all "
                "vendor invoices received by Meridian Supply Co. It applies to every "
                "member of the Accounts Payable department and to any employee who "
                "initiates, approves, or records a payment obligation on the company's "
                "behalf. The objective of this policy is uniformity: every invoice, "
                "from every vendor, follows the same documented path from receipt to "
                "payment, with no informal shortcuts."
            ),
        ),
        PolicySection(
            anchor="invoice-matching",
            heading="2. Invoice matching",
            body=(
                "A full three-way match is mandatory for every invoice without "
                "exception. Before an invoice may be approved, Accounts Payable staff "
                "shall verify (a) the invoice against the corresponding purchase "
                "order, (b) the purchase order against the goods receipt, and (c) the "
                "quantities and unit prices across all three documents. No invoice "
                "shall be approved on a two-way match, regardless of vendor, amount, "
                "or urgency. Invoices lacking a purchase order shall be returned to "
                "the originating department for retroactive purchase order creation."
            ),
            topic="three_way_match",
            declared_value="mandatory for every invoice, no exceptions",
        ),
        PolicySection(
            anchor="approval-thresholds",
            heading="3. Approval thresholds",
            body=(
                "Any invoice exceeding five thousand dollars ($5,000) requires the "
                "written approval of the Accounts Payable Manager before posting. "
                "Invoices at or below this threshold may be posted by Accounts "
                "Payable staff once the three-way match of Section 2 is complete. "
                "The five-thousand-dollar threshold applies uniformly to all vendors "
                "and all expense categories; no vendor relationship, however "
                "long-standing, modifies it."
            ),
            topic="approval_threshold",
            declared_value="$5,000",
        ),
        PolicySection(
            anchor="vendor-treatment",
            heading="4. Vendor treatment",
            body=(
                "All vendors are subject to identical review procedures. Meridian "
                "Supply Co. does not maintain preferred, trusted, or expedited vendor "
                "categories for the purposes of invoice approval. Length of "
                "relationship, order volume, and dispute history shall not be used to "
                "reduce or waive any verification step. This uniform treatment is a "
                "deliberate control against familiarity-based fraud."
            ),
            topic="trusted_vendor_exception",
            declared_value="none — every vendor follows the same review path",
        ),
        PolicySection(
            anchor="payment-processing",
            heading="5. Payment processing",
            body=(
                "Approved invoices are paid on net terms as stated on the invoice. "
                "Payment runs are executed weekly on Thursdays. Changes to a vendor's "
                "remittance details must be submitted on the bank amendment form and "
                "countersigned by the Controller before the next payment run."
            ),
        ),
    ],
)


AP_POLICY_2023 = PolicyDocument(
    source_ref="AP-Policy-2023.pdf",
    collection_slug="ap-policy-2023",
    title="Meridian Supply Co. — Accounts Payable Policy (2023 revision)",
    owner="Finance Policy Office — Dana Whitfield, CFO",
    authority_level="policy_2023",
    effective_date=date(2023, 4, 1),
    sections=[
        PolicySection(
            anchor="purpose-and-scope",
            heading="1. Purpose and scope",
            body=(
                "This revision supersedes the Accounts Payable Policy dated March "
                "2019. It governs the processing, verification, and approval of "
                "vendor invoices at Meridian Supply Co. The 2023 revision introduces "
                "risk-based processing: verification effort is proportionate to "
                "invoice risk, so that control attention concentrates where exposure "
                "actually is rather than being spread uniformly across routine, "
                "low-value invoices."
            ),
        ),
        PolicySection(
            anchor="invoice-matching",
            heading="2. Invoice matching",
            body=(
                "A three-way match (invoice, purchase order, goods receipt) is "
                "required for invoices above two thousand five hundred dollars "
                "($2,500). Invoices at or below this amount may be processed on a "
                "two-way match of invoice against purchase order, provided the "
                "vendor is in good standing. Recurring service invoices without a "
                "purchase order (utilities, rent) may be processed against the "
                "historical run rate for that vendor."
            ),
            topic="three_way_match",
            declared_value="required above $2,500; two-way match acceptable below",
        ),
        PolicySection(
            anchor="approval-thresholds",
            heading="3. Approval thresholds",
            body=(
                "Any invoice exceeding ten thousand dollars ($10,000) requires the "
                "approval of the Accounts Payable Manager before posting, regardless "
                "of matching outcome. Any invoice exceeding twenty-five thousand "
                "dollars ($25,000) additionally requires approval from the "
                "Controller or the Chief Financial Officer. Invoices at or below "
                "ten thousand dollars that satisfy the matching requirements of "
                "Section 2 may be posted without further approval."
            ),
            topic="approval_threshold",
            declared_value="$10,000",
        ),
        PolicySection(
            anchor="trusted-vendor-program",
            heading="4. Trusted vendor program",
            body=(
                "Meridian Supply Co. maintains a trusted vendor tier comprising its "
                "top suppliers by volume with at least three years of relationship "
                "history and no open disputes. Invoices from trusted-tier vendors "
                "that reference a valid purchase order and fall within the price "
                "variance tolerance may be approved without manual review, subject "
                "to the thresholds of Section 3. The trusted tier is reviewed "
                "semi-annually by the Accounts Payable Manager, and a vendor is "
                "removed from it immediately upon any dispute or any change to its "
                "banking details pending re-verification."
            ),
            topic="trusted_vendor_exception",
            declared_value="trusted-tier vendors auto-approve with valid PO within tolerance",
        ),
        PolicySection(
            anchor="exceptions-and-escalation",
            heading="5. Exceptions and escalation",
            body=(
                "Any invoice that does not fit the paths above — a missing purchase "
                "order from a new vendor, a price variance outside tolerance, a "
                "duplicate invoice number, or changed remittance details — is "
                "escalated to a human reviewer. Staff are reminded that escalation "
                "is the expected behaviour for ambiguous cases, not a failure of "
                "processing. Changed vendor banking details are always verified by "
                "telephone using the number already on file, never a number printed "
                "on the invoice itself."
            ),
        ),
    ],
)


#: Every policy document the seed ingests, oldest first.
POLICY_DOCUMENTS: tuple[PolicyDocument, ...] = (AP_POLICY_2019, AP_POLICY_2023)
