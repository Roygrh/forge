"""Rules as data: the encoding matches its document, and the engine reads it faithfully.

Three things are under test here, in order of how much they would hurt if they broke:

1. **The catalogue and ``04-tacit-rules.md`` agree.** The markdown is the source of truth
   (golden rule 5); the catalogue is its machine-readable form. A rule in one and not the
   other, or a statement that has drifted, fails here rather than in production.
2. **The engine is an interpreter, not a rulebook.** Unknown facts do not match, money is
   compared exactly, and a malformed condition is an error rather than a silent false.
3. **The seeded scenarios resolve the way the eval cases say they should.** This is not
   the eval runner (Phase 4.5) — no suite, no publish gate — but the rule layer's own
   answers are checked against the cases the suite will score.
"""

import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.actions import most_restrictive
from app.erp import build_fact_sheet, get_erp
from app.models import Tenant
from app.rules import CATALOG, RULESET_VERSION, RuleEvaluationError, catalog_rule_set, evaluate
from app.rules.model import Clause, Condition, Rule, RuleSet
from app.rules.repository import load_rule_set_sync
from scripts.seed import seed_rules

TACIT_RULES_DOC = (
    Path(__file__).resolve().parents[3] / "docs" / "01-discovery" / "04-tacit-rules.md"
)

#: `| R-001 | statement | action |` — the shape of every rule row in the document.
_ROW = re.compile(r"^\|\s*(R-\d{3})\s*\|\s*(.+?)\s*\|")


def _normalise(text: str) -> str:
    """Strip the markdown that is presentation, keep the sentence that is the rule."""
    return re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()


def documented_rules() -> dict[str, str]:
    """Every R-xxx in the source document, mapped to its statement."""
    found = {}
    for line in TACIT_RULES_DOC.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line.strip())
        if match is not None:
            found[match.group(1)] = _normalise(match.group(2))
    return found


# --- 1. The encoding matches the document -------------------------------------


def test_every_documented_rule_is_encoded_and_vice_versa() -> None:
    """No rule may exist in only one of the two places (golden rule 5)."""
    documented = set(documented_rules())
    encoded = {rule.rule_id for rule in CATALOG}

    assert documented, "the tacit-rules document parsed to nothing — check the table format"
    assert documented - encoded == set(), "documented but not encoded"
    assert encoded - documented == set(), "encoded but not documented"


@pytest.mark.parametrize("rule", CATALOG, ids=lambda rule: rule.rule_id)
def test_every_statement_matches_the_one_its_owner_signed_off(rule: Rule) -> None:
    """The statement stored beside a rule is the SME's wording, not a paraphrase."""
    assert _normalise(rule.statement) == documented_rules()[rule.rule_id]


def test_every_rule_carries_its_authority_and_its_source() -> None:
    """A rule with no provenance cannot be ranked against a policy document (FR-D2)."""
    for rule in CATALOG:
        assert rule.authority_level == "sme_validated"
        assert rule.version == RULESET_VERSION
        assert rule.source_ref == f"docs/01-discovery/04-tacit-rules.md#{rule.rule_id}"


def test_business_rules_propose_actions_and_meta_rules_do_not() -> None:
    """The three kinds mean what they say: only a business rule decides anything."""
    for rule in CATALOG:
        if rule.kind == "business":
            assert rule.clauses, f"{rule.rule_id} is a business rule with no clauses"
            assert all(clause.action is not None for clause in rule.clauses)
        elif rule.kind == "definition":
            assert all(clause.action is None for clause in rule.clauses)
        else:
            assert rule.clauses == []


# --- 2. The engine is an interpreter ------------------------------------------


def _one(rule_id: str, when: Condition, action: str = "escalate") -> RuleSet:
    return RuleSet(
        version="9.9.9",
        rules=[
            Rule(
                rule_id=rule_id,
                family="test",
                kind="business",
                statement="test rule",
                authority_level="sme_validated",
                version="9.9.9",
                clauses=[Clause(when=when, action=action)],  # type: ignore[arg-type]
            )
        ],
    )


def test_a_missing_fact_never_matches() -> None:
    """Fail closed: unknown is not "probably fine" (R-091 is what covers the gap)."""
    rule_set = _one("R-999", Condition(fact="match.price_variance_pct", op="lte", value=2))

    assert evaluate(rule_set, {}) == []
    assert evaluate(rule_set, {"match.price_variance_pct": None}) == []


def test_money_is_compared_exactly_not_as_a_float() -> None:
    """0.1 + 0.2 problems must never decide whether an invoice is over a threshold."""
    rule_set = _one("R-999", Condition(fact="invoice.amount_usd", op="gt", value=10000))

    assert evaluate(rule_set, {"invoice.amount_usd": "10000.00"}) == []
    assert len(evaluate(rule_set, {"invoice.amount_usd": "10000.01"})) == 1


def test_a_boolean_fact_does_not_satisfy_a_numeric_comparison() -> None:
    """In Python ``True == 1``; in a rule set that would be a silent false positive."""
    rule_set = _one("R-999", Condition(fact="invoice.has_po", op="eq", value=1))

    assert evaluate(rule_set, {"invoice.has_po": True}) == []


def test_any_expresses_whichever_is_greater() -> None:
    """R-010's tolerance band: under 2% *or* under $50 is within tolerance."""
    rule_set = _one(
        "R-999",
        Condition(
            any=[
                Condition(fact="match.price_variance_pct", op="lte", value=2),
                Condition(fact="match.price_variance_usd", op="lte", value=50),
            ]
        ),
    )

    # 2.04% but only $38 — outside the percentage, inside the dollar band (E-02).
    matches = evaluate(
        rule_set, {"match.price_variance_pct": "2.04", "match.price_variance_usd": "38.00"}
    )

    assert len(matches) == 1
    assert matches[0].because == ["match.price_variance_usd lte 50 (actual: '38.00')"]


def test_the_first_matching_clause_wins() -> None:
    """R-003's tiered cap is one rule id with two branches, and order decides."""
    tiered = RuleSet(
        version="9.9.9",
        rules=[
            Rule(
                rule_id="R-999",
                family="test",
                kind="business",
                statement="tiered",
                authority_level="sme_validated",
                version="9.9.9",
                clauses=[
                    Clause(
                        when=Condition(fact="invoice.amount_usd", op="lte", value=5000),
                        action="auto_approve",
                    ),
                    Clause(
                        when=Condition(fact="invoice.amount_usd", op="gt", value=5000),
                        action="escalate",
                    ),
                ],
            )
        ],
    )

    assert evaluate(tiered, {"invoice.amount_usd": "3200.00"})[0].action == "auto_approve"
    assert evaluate(tiered, {"invoice.amount_usd": "7400.00"})[0].action == "escalate"


def test_a_rule_carries_the_rules_it_is_written_in_terms_of() -> None:
    """R-001 applies R-010's tolerance band, so a decision citing one cites both."""
    matches = evaluate(
        catalog_rule_set(), build_fact_sheet(get_erp(), get_erp().invoice("inv-0001"))
    )
    r001 = next(match for match in matches if match.rule_id == "R-001")

    assert r001.citations == ["R-001", "R-010"]


def test_an_unreadable_rule_is_an_error_not_a_silent_false() -> None:
    """ "Did not fire" and "could not be read" must never look the same to a reviewer."""
    ambiguous = _one(
        "R-999",
        Condition(
            fact="invoice.amount_usd", op="gt", value=1, all=[Condition(fact="x", op="is_true")]
        ),
    )

    with pytest.raises(RuleEvaluationError):
        evaluate(ambiguous, {"invoice.amount_usd": "10.00"})


def test_an_ordering_comparison_against_a_non_number_is_an_authoring_error() -> None:
    """Silently never firing is the worst failure mode a rule can have."""
    rule_set = _one("R-999", Condition(fact="vendor.trust_tier", op="gt", value=3))

    with pytest.raises(RuleEvaluationError, match="needs numbers"):
        evaluate(rule_set, {"vendor.trust_tier": "trusted"})


# --- 3. The seeded scenarios resolve as the eval cases expect ------------------
#
# One row per case in docs/01-discovery/06-eval-cases.md that is expressible without the
# knowledge layer. E-19 is a policy-conflict question about documents, so it waits for
# Phase 4.3. This is the rule layer's own answer — the agent's end-to-end decision on the
# same invoices is asserted in test_ap_agents.py.

EVAL_SCENARIOS = [
    ("E-01", "inv-0001", "auto_approve", {"R-001", "R-010"}),
    ("E-02", "inv-0002", "auto_approve", {"R-001", "R-010"}),
    ("E-03", "inv-0003", "auto_approve", {"R-003"}),
    ("E-04", "inv-0004", "auto_approve", {"R-030"}),
    ("E-05", "inv-0005", "escalate", {"R-011"}),
    ("E-06", "inv-0006", "block_escalate", {"R-012"}),
    ("E-07", "inv-0007", "escalate", {"R-013"}),
    ("E-08", "inv-0008", "escalate", {"R-003"}),
    ("E-09", "inv-0009", "escalate", {"R-020"}),
    ("E-10", "inv-0010", "escalate", {"R-021"}),
    ("E-11", "inv-0011", "escalate", {"R-002"}),
    ("E-12", "inv-0012", "escalate", {"R-031"}),
    ("E-13", "inv-0013", "escalate", {"R-032"}),
    ("E-14", "inv-0015", "block_escalate", {"R-040"}),
    ("E-15", "inv-0017", "escalate", {"R-041"}),
    ("E-16", "inv-0018", "block_escalate", {"R-042"}),
    ("E-17", "inv-0019", "escalate", {"R-043"}),
    # E-18 expects auto_approve *and* priority_queue. The decision contract carries one
    # action, so the most restrictive of the two is what a run returns; both rules are
    # still cited. Splitting the payment-scheduling half out is Phase 4.5's problem.
    ("E-18", "inv-0020", "priority_queue", {"R-001", "R-050"}),
]


@pytest.mark.parametrize(
    ("case", "invoice_id", "expected_action", "must_cite"),
    EVAL_SCENARIOS,
    ids=[case for case, *_ in EVAL_SCENARIOS],
)
def test_a_seeded_scenario_resolves_as_its_eval_case_expects(
    case: str, invoice_id: str, expected_action: str, must_cite: set[str]
) -> None:
    erp = get_erp()
    matches = evaluate(catalog_rule_set(), build_fact_sheet(erp, erp.invoice(invoice_id)))

    action = most_restrictive([match.action for match in matches if match.action])
    cited = {rule_id for match in matches for rule_id in match.citations}

    assert action == expected_action, f"{case}: fired {[(m.rule_id, m.action) for m in matches]}"
    assert must_cite <= cited, f"{case}: cited {sorted(cited)}"


def test_e20_matches_no_rule_at_all() -> None:
    """The fail-closed case: nothing in the governed set speaks to this invoice."""
    erp = get_erp()

    matches = evaluate(catalog_rule_set(), build_fact_sheet(erp, erp.invoice("inv-0021")))

    assert matches == []
    assert most_restrictive([]) is None  # ...and the caller answers that with R-091


# --- The database round trip --------------------------------------------------


def _own_tenant(session: Session) -> Tenant:
    """A tenant of this test's own, so a committed rule set elsewhere cannot leak in."""
    tenant = Tenant(slug=f"rules-test-{uuid.uuid4().hex[:8]}", name="Rules Test Tenant")
    session.add(tenant)
    session.flush()
    return tenant


def test_the_seeded_table_reproduces_the_catalogue(session: Session) -> None:
    """What the seed writes is what the platform reads back — conditions included."""
    tenant = _own_tenant(session)
    written, _ = seed_rules(session, tenant)
    session.flush()

    assert written == len(CATALOG)

    loaded = load_rule_set_sync(session, tenant.tenant_id)

    assert loaded.version == RULESET_VERSION
    assert [rule.rule_id for rule in loaded.rules] == sorted(rule.rule_id for rule in CATALOG)
    # The condition trees survive the jsonb round trip, so a rule evaluates identically
    # whether it came from the catalogue or from the table.
    erp = get_erp()
    facts = build_fact_sheet(erp, erp.invoice("inv-0009"))
    assert [match.rule_id for match in evaluate(loaded, facts)] == [
        match.rule_id for match in evaluate(catalog_rule_set(), facts)
    ]


def test_an_empty_rule_table_matches_nothing_rather_than_everything(session: Session) -> None:
    """A platform that lost its rules approves nothing — fail closed by construction."""
    tenant = _own_tenant(session)

    loaded = load_rule_set_sync(session, tenant.tenant_id)
    erp = get_erp()

    assert evaluate(loaded, build_fact_sheet(erp, erp.invoice("inv-0001"))) == []


def test_money_thresholds_survive_as_decimals_through_the_seed(session: Session) -> None:
    """A threshold stored as JSON is still compared exactly when it is read back."""
    tenant = _own_tenant(session)
    seed_rules(session, tenant)
    session.flush()

    loaded = load_rule_set_sync(session, tenant.tenant_id)
    threshold = loaded.by_id("R-020")

    assert threshold is not None
    assert Decimal(str(threshold.clauses[0].when.value)) == Decimal("10000")
