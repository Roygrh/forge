"""The machine-readable encoding of Meridian's captured tacit rules.

``docs/01-discovery/04-tacit-rules.md`` is the source of truth (golden rule 5). This
module is that document's *executable* form: the same rule ids, the same statements
verbatim, plus the conditions and actions needed to evaluate them. It is **seed data**
— ``scripts/seed.py`` writes it into the ``rules`` table once, and from then on the
platform reads the table. Nothing at run time imports this module.

``tests/test_rules.py`` parses the markdown and fails if a rule exists in one place and
not the other, or if a statement here has drifted from the statement Rosa signed off. So
the encoding cannot quietly diverge from the document it claims to encode.

Adding a rule is: a row in the markdown table, an entry here, re-run the seed. Changing
what an existing rule *does* needs neither — see :mod:`app.rules`.
"""

from app.rules.model import AuthorityLevel, Clause, Condition, LiteralValue, Rule, RuleSet

#: Semver of the captured rule set, matching the header of 04-tacit-rules.md. Bumped by
#: its owner (the AP Manager) whenever a rule changes and is re-validated.
RULESET_VERSION = "1.0.0"

#: The SME-captured set is the top authority: it overrides every written policy document
#: on conflict (FR-D2, R-090).
SME: AuthorityLevel = "sme_validated"

SOURCE_DOCUMENT = "docs/01-discovery/04-tacit-rules.md"


# --- Condition builders -------------------------------------------------------
# Thin sugar over app.rules.model so a rule below reads close to the sentence it
# encodes. They construct data; they do not evaluate anything.


def fact(name: str, op: str, value: LiteralValue = None) -> Condition:
    """One comparison: ``fact op value``."""
    return Condition(fact=name, op=op, value=value)  # type: ignore[arg-type]  # op is a Literal


def all_of(*conditions: Condition) -> Condition:
    """Every branch must hold."""
    return Condition(all=list(conditions))


def any_of(*conditions: Condition) -> Condition:
    """At least one branch must hold — how "whichever is greater" is expressed."""
    return Condition(any=list(conditions))


def _rule(
    rule_id: str,
    family: str,
    statement: str,
    *clauses: Clause,
    kind: str = "business",
    cites: tuple[str, ...] = (),
) -> Rule:
    return Rule(
        rule_id=rule_id,
        family=family,
        kind=kind,  # type: ignore[arg-type]  # literal narrowed by the callers below
        statement=statement,
        authority_level=SME,
        version=RULESET_VERSION,
        clauses=list(clauses),
        cites=list(cites),
        source_ref=f"{SOURCE_DOCUMENT}#{rule_id}",
    )


#: The tolerance band R-010 defines, reused by the rules that are written in terms of it.
#: Both halves are data: "2" and "50" are values on a condition, not constants in code.
WITHIN_TOLERANCE = any_of(
    fact("match.price_variance_pct", "lte", 2),
    fact("match.price_variance_usd", "lte", 50),
)

#: The negation R-011 needs. "> 2% (or > $50)" in the document means *outside* the band,
#: which is both halves failing at once — not either one.
OUTSIDE_TOLERANCE = all_of(
    fact("match.price_variance_pct", "gt", 2),
    fact("match.price_variance_usd", "gt", 50),
)


CATALOG: tuple[Rule, ...] = (
    # --- Vendor trust ---------------------------------------------------------
    _rule(
        "R-001",
        "vendor_trust",
        "Vendor is trusted tier (top-20 list, ≥3 years history, zero disputes) AND valid "
        "PO exists AND price variance within tolerance (R-010)",
        Clause(
            when=all_of(
                fact("vendor.trust_tier", "eq", "trusted"),
                fact("vendor.relationship_years", "gte", 3),
                fact("vendor.open_disputes", "eq", 0),
                fact("match.po_found", "is_true"),
                WITHIN_TOLERANCE,
            ),
            action="auto_approve",
        ),
        cites=("R-010",),
    ),
    _rule(
        "R-002",
        "vendor_trust",
        "New vendor (first 3 invoices ever) — regardless of amount or PO",
        Clause(when=fact("vendor.prior_invoice_count", "lt", 3), action="escalate"),
    ),
    _rule(
        "R-003",
        "vendor_trust",
        "Vendor not on trusted tier but >1 year history: PO-matched invoices within tolerance",
        # Two clauses, one rule id: the tier's cap is a boundary inside R-003, not a
        # second rule. First match wins, so the order here is the rule's own order.
        Clause(
            when=all_of(
                fact("vendor.trust_tier", "ne", "trusted"),
                fact("vendor.relationship_years", "gt", 1),
                fact("match.po_found", "is_true"),
                WITHIN_TOLERANCE,
                fact("invoice.amount_usd", "lte", 5000),
            ),
            action="auto_approve",
            note="Within the $5,000 cap this tier may be auto-approved up to.",
        ),
        Clause(
            when=all_of(
                fact("vendor.trust_tier", "ne", "trusted"),
                fact("vendor.relationship_years", "gt", 1),
                fact("match.po_found", "is_true"),
                WITHIN_TOLERANCE,
                fact("invoice.amount_usd", "gt", 5000),
            ),
            action="escalate",
            note="Above the $5,000 cap for a non-trusted tier.",
        ),
        cites=("R-010",),
    ),
    # --- Matching tolerances --------------------------------------------------
    _rule(
        "R-010",
        "matching",
        "Price variance vs PO ≤ 2% or ≤ $50 (whichever is greater) → within tolerance",
        Clause(
            when=all_of(fact("match.po_found", "is_true"), WITHIN_TOLERANCE),
            note=("Feeds R-001 and R-003; states the tolerance band, proposes no action itself."),
        ),
        kind="definition",
    ),
    _rule(
        "R-011",
        "matching",
        "Price variance > 2% (or > $50) and ≤ 10% (and ≤ $2,500)",
        Clause(
            when=all_of(
                fact("match.po_found", "is_true"),
                OUTSIDE_TOLERANCE,
                fact("match.price_variance_pct", "lte", 10),
                fact("match.price_variance_usd", "lte", 2500),
            ),
            action="escalate",
            note="Escalate with the variance highlighted.",
        ),
    ),
    _rule(
        "R-012",
        "matching",
        "Price variance > 10% or > $2,500 → presumed wrong PO, not a tolerance issue",
        Clause(
            when=all_of(
                fact("match.po_found", "is_true"),
                any_of(
                    fact("match.price_variance_pct", "gt", 10),
                    fact("match.price_variance_usd", "gt", 2500),
                ),
            ),
            action="block_escalate",
            note="Treat as the wrong purchase order, not as a tolerance question.",
        ),
    ),
    _rule(
        "R-013",
        "matching",
        "Quantity billed > quantity received (per goods receipt)",
        Clause(when=fact("match.quantity_billed_over_received", "is_true"), action="escalate"),
    ),
    # --- Amount thresholds ----------------------------------------------------
    _rule(
        "R-020",
        "thresholds",
        "Any invoice > $10,000, regardless of matching outcome",
        Clause(
            when=fact("invoice.amount_usd", "gt", 10000),
            action="escalate",
            note="To the AP approver queue.",
        ),
    ),
    _rule(
        "R-021",
        "thresholds",
        "Any invoice > $25,000",
        Clause(
            when=fact("invoice.amount_usd", "gt", 25000),
            action="escalate",
            note="To the CFO / controller queue.",
        ),
    ),
    # --- Non-PO invoices ------------------------------------------------------
    _rule(
        "R-030",
        "non_po",
        "Recurring utility/rent from known vendor, amount within ±15% of trailing 3-month average",
        Clause(
            when=all_of(
                fact("invoice.has_po", "is_false"),
                fact("invoice.category", "in", ["utility", "rent"]),
                fact("vendor.prior_invoice_count", "gte", 5),
                fact("nonpo.trailing_3m_avg_usd", "not_null"),
                fact("nonpo.variance_vs_trailing_avg_pct", "lte", 15),
            ),
            action="auto_approve",
        ),
    ),
    _rule(
        "R-031",
        "non_po",
        "Non-PO invoice from vendor with <5 prior invoices",
        Clause(
            when=all_of(
                fact("invoice.has_po", "is_false"),
                fact("vendor.prior_invoice_count", "lt", 5),
            ),
            action="escalate",
        ),
    ),
    _rule(
        "R-032",
        "non_po",
        "Non-PO invoice > $2,000 (any vendor)",
        Clause(
            when=all_of(
                fact("invoice.has_po", "is_false"),
                fact("invoice.amount_usd", "gt", 2000),
            ),
            action="escalate",
        ),
    ),
    # --- Duplicates and fraud guards -----------------------------------------
    _rule(
        "R-040",
        "duplicates_fraud",
        "Invoice number already exists for this vendor",
        Clause(
            when=fact("duplicate.invoice_number_exists", "is_true"),
            action="block_escalate",
            note="Possible duplicate or resend; hard stop before any approval.",
        ),
    ),
    _rule(
        "R-041",
        "duplicates_fraud",
        "Same vendor + same amount within 7 days of a prior invoice",
        Clause(
            when=all_of(
                fact("duplicate.days_since_same_amount", "not_null"),
                fact("duplicate.days_since_same_amount", "lte", 7),
            ),
            action="escalate",
            note="Show both invoices side by side.",
        ),
    ),
    _rule(
        "R-042",
        "duplicates_fraud",
        "Vendor bank details changed since last payment — any channel",
        Clause(
            when=fact("vendor.bank_details_changed", "is_true"),
            action="block_escalate",
            note=(
                "A human verifies by calling the number on file — never a number from the invoice."
            ),
        ),
    ),
    _rule(
        "R-043",
        "duplicates_fraud",
        "Amount within 2% under an approval threshold (e.g., $9,800–$9,999 vs $10K) from "
        "non-trusted vendor",
        Clause(
            when=all_of(
                fact("invoice.amount_usd", "gte", 9800),
                fact("invoice.amount_usd", "lt", 10000),
                fact("vendor.trust_tier", "ne", "trusted"),
            ),
            action="escalate",
            note="Flag as a threshold-skimming pattern.",
        ),
    ),
    _rule(
        "R-044",
        "duplicates_fraud",
        "Round-number invoice (multiples of $500) from vendor with <1 year history",
        Clause(
            when=all_of(
                fact("invoice.amount_usd", "multiple_of", 500),
                fact("vendor.relationship_years", "lt", 1),
            ),
            action="escalate",
        ),
    ),
    # --- Urgency and cash discipline -----------------------------------------
    _rule(
        "R-050",
        "urgency",
        "Early-payment discount terms (e.g., 2/10) and discount window closes within 3 "
        "business days",
        Clause(
            when=all_of(
                fact("invoice.discount_window_days", "not_null"),
                fact("invoice.discount_window_days", "lte", 3),
            ),
            action="priority_queue",
        ),
    ),
    _rule(
        "R-051",
        "urgency",
        "Invoice past due date (vendor chasing)",
        Clause(when=fact("invoice.days_past_due", "gt", 0), action="priority_queue"),
    ),
    # --- Meta rules -----------------------------------------------------------
    # No conditions: these govern how the agent reasons, not what an invoice is. They
    # are handed to the agent on every retrieval and are cited when they are applied.
    _rule(
        "R-090",
        "meta",
        "On any rule conflict: higher authority source wins; same authority → most "
        "restrictive action wins",
        kind="meta",
    ),
    _rule(
        "R-091",
        "meta",
        "If no rule matches or confidence below threshold → escalate (never guess) — the "
        "fail-closed default",
        kind="meta",
    ),
    _rule(
        "R-092",
        "meta",
        "Every decision cites the rule ID(s) applied",
        kind="meta",
    ),
)


def catalog_rule_set() -> RuleSet:
    """The shipped rule set as one retrievable unit."""
    return RuleSet(version=RULESET_VERSION, rules=list(CATALOG))
