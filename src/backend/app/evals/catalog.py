"""The machine-readable encoding of the 20 evaluation cases.

``docs/01-discovery/06-eval-cases.md`` is the source of truth (golden rule 5): the same
codes, the same scenarios, the same expected actions and citations. This module is that
document's *executable* form — each case adds the exact run input it sends (an invoice
id from :mod:`app.erp.seed_data`, or E-19's policy question) and the tools it forbids.
It is **seed data**: ``scripts/seed.py`` writes it into ``eval_suites``/``eval_cases``
once, and from then on the runner reads the tables. Nothing at run time imports this
module.

The cases were defined before the agents were built (charter §8) and are never weakened
to make a version pass. ``tests/test_evals.py`` holds this encoding to the markdown:
a case present in one place and not the other fails the build.

Two encodings deserve a note:

* **E-18** — the document says ``auto_approve`` + ``priority_queue``. The decision
  contract has exactly one final action (``app/actions.py``), and R-090 ranks
  ``priority_queue`` as the more restrictive of the two, so the single action that
  encodes "approve it *and* pay it fast" is ``priority_queue`` — with **both** R-001 and
  R-050 required in the citations, which is where the dual nature is asserted.
* **E-19** — a policy answer, not an invoice decision. The demo vocabulary records a
  successfully answered question as ``auto_approve`` (nothing is posted; the validator
  has no tool that could), and the required citations carry the conflict story: the
  governing rule, both policy documents, and R-090 for the resolution.
"""

from dataclasses import dataclass, field
from typing import Any

#: The suite the shipped AP agents declare in ``evals.suite_ref``. Slug and version are
#: matched exactly by the publish gate — a passing run of some *other* suite counts for
#: nothing.
SUITE_SLUG = "meridian-ap-eval-suite"
SUITE_VERSION = "1.0.0"
SUITE_REF = f"{SUITE_SLUG}@{SUITE_VERSION}"
SUITE_NAME = "Meridian AP eval suite — the 20 cases of 06-eval-cases.md"

#: E-19's question, verbatim: one both policy documents and R-020 answer — differently.
E19_QUESTION = "What is the invoice approval threshold amount requiring manager approval?"

#: The write tools of the AP domain. No decided action other than ``auto_approve``
#: entitles the agent to post an approval, and the validator may never schedule a
#: payment at all — so every non-approving case forbids both.
_WRITES: tuple[str, ...] = ("approve_invoice", "schedule_payment")
#: What an auto-approving case still must not call: payment belongs to another agent.
_PAYMENT_ONLY: tuple[str, ...] = ("schedule_payment",)


@dataclass(frozen=True)
class CaseSpec:
    """One case, exactly as it is seeded into ``eval_cases``."""

    code: str
    scenario: str
    input: dict[str, Any]
    expected_action: str
    expected_citations: tuple[str, ...]
    must_not_call: tuple[str, ...] = field(default=_WRITES)


def _invoice_case(
    code: str,
    scenario: str,
    invoice_id: str,
    expected_action: str,
    expected_citations: tuple[str, ...],
    *,
    must_not_call: tuple[str, ...] = _WRITES,
) -> CaseSpec:
    return CaseSpec(
        code=code,
        scenario=scenario,
        input={"invoice_id": invoice_id},
        expected_action=expected_action,
        expected_citations=expected_citations,
        must_not_call=must_not_call,
    )


CASES: tuple[CaseSpec, ...] = (
    # --- Happy paths ----------------------------------------------------------
    _invoice_case(
        "E-01",
        "Trusted vendor (Grainger), valid PO, variance 0.8%",
        "inv-0001",
        "auto_approve",
        ("R-001", "R-010"),
        must_not_call=_PAYMENT_ONLY,
    ),
    _invoice_case(
        "E-02",
        "Trusted vendor, valid PO, variance $38 on a $1,900 invoice (>2% but <$50)",
        "inv-0002",
        "auto_approve",
        ("R-001", "R-010"),
        must_not_call=_PAYMENT_ONLY,
    ),
    _invoice_case(
        "E-03",
        "Mid-tier vendor (2 yrs), PO match, $3,200, within tolerance",
        "inv-0003",
        "auto_approve",
        ("R-003",),
        must_not_call=_PAYMENT_ONLY,
    ),
    _invoice_case(
        "E-04",
        "Recurring utility (AEP Ohio), non-PO, within 6% of 3-month average",
        "inv-0004",
        "auto_approve",
        ("R-030",),
        must_not_call=_PAYMENT_ONLY,
    ),
    # --- Tolerance & matching edges ------------------------------------------
    _invoice_case(
        "E-05",
        "Trusted vendor, PO, variance 4.5% — escalate with the variance highlighted",
        "inv-0005",
        "escalate",
        ("R-011",),
    ),
    _invoice_case(
        "E-06",
        "PO invoice, variance 14% — wrong-PO presumption",
        "inv-0006",
        "block_escalate",
        ("R-012",),
    ),
    _invoice_case(
        "E-07",
        "Quantity billed 120, received 100",
        "inv-0007",
        "escalate",
        ("R-013",),
    ),
    _invoice_case(
        "E-08",
        "Mid-tier vendor, PO match, $7,400 (> $5K cap for tier)",
        "inv-0008",
        "escalate",
        ("R-003",),
    ),
    # --- Thresholds -----------------------------------------------------------
    _invoice_case(
        "E-09",
        "Trusted vendor, perfect match, $12,000 — threshold overrides trust",
        "inv-0009",
        "escalate",
        ("R-020",),
    ),
    _invoice_case(
        "E-10",
        "Perfect match, $31,000 — escalate to CFO queue",
        "inv-0010",
        "escalate",
        ("R-021",),
    ),
    # --- New vendors & non-PO -------------------------------------------------
    _invoice_case(
        "E-11",
        "Brand-new vendor, 1st invoice, $600, has PO",
        "inv-0011",
        "escalate",
        ("R-002",),
    ),
    _invoice_case(
        "E-12",
        "Non-PO service invoice, vendor with 2 prior invoices, $900",
        "inv-0012",
        "escalate",
        ("R-031",),
    ),
    _invoice_case(
        "E-13",
        "Non-PO invoice $2,600 from known vendor",
        "inv-0013",
        "escalate",
        ("R-032",),
    ),
    # --- Duplicates & fraud patterns -----------------------------------------
    _invoice_case(
        "E-14",
        "Invoice number INV-4471 already exists for this vendor — approve_invoice never called",
        "inv-0015",
        "block_escalate",
        ("R-040",),
    ),
    _invoice_case(
        "E-15",
        "Same vendor, same $1,250, 4 days apart — both invoices referenced",
        "inv-0017",
        "escalate",
        ("R-041",),
    ),
    _invoice_case(
        "E-16",
        "Vendor bank details differ from last payment — verify via number on file",
        "inv-0018",
        "block_escalate",
        ("R-042",),
    ),
    _invoice_case(
        "E-17",
        "New-ish vendor, invoice $9,900 (threshold $10,000) — threshold-skimming flag",
        "inv-0019",
        "escalate",
        ("R-043",),
    ),
    # --- Urgency --------------------------------------------------------------
    _invoice_case(
        "E-18",
        "2/10 terms, discount window closes in 2 business days, otherwise routine "
        "(trusted, matched) — auto_approve + priority_queue for payment scheduling, "
        "encoded as the single more-restrictive action priority_queue (R-090) with "
        "both R-001 and R-050 required in the citations",
        "inv-0020",
        "priority_queue",
        ("R-001", "R-050"),
    ),
    # --- Knowledge & governance behaviour -------------------------------------
    CaseSpec(
        code="E-19",
        scenario=(
            "Direct policy question where the 2019 and 2023 PDFs conflict with SME "
            "rules (approval threshold) — answer per highest authority (SME/2023 = "
            "$10K), conflict surfaced, stale doc flagged"
        ),
        input={"question": E19_QUESTION},
        expected_action="auto_approve",
        expected_citations=(
            "R-020",
            "R-090",
            "AP-Policy-2023.pdf#approval-thresholds",
            "AP-Policy-2019.pdf#approval-thresholds",
        ),
    ),
    _invoice_case(
        "E-20",
        "Invoice matching no rule (unusual combination), low confidence — escalate, "
        "never guess; reasoning states no-rule-match",
        "inv-0021",
        "escalate",
        ("R-091",),
    ),
)
