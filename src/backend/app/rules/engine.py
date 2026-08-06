"""Evaluating stored rules against an ERP fact sheet.

This module is a small, general **interpreter** — the same relationship a SQL engine has
to a ``WHERE`` clause. It contains no thresholds, no vendor tiers, no dollar amounts:
those are in the rule rows, and editing a row changes what the agent decides without a
line of Python changing (see :mod:`app.rules`).

Two properties are load-bearing:

* **Unknown means no match.** A leaf whose fact is missing or ``None`` is false, never
  "probably fine". A non-PO invoice has no price variance, so every tolerance rule
  simply declines to fire, and an invoice nothing matches escalates under R-091.
* **Numbers are compared as decimals.** Money and percentages arrive as exact decimal
  strings and are compared as :class:`~decimal.Decimal`, so no threshold is ever decided
  by binary floating point.

The engine returns *matches*, not a decision. Choosing between conflicting matches
(R-090) and deciding what to do when there are none (R-091) is the agent's reasoning,
performed by the model over what it retrieved — which is what makes those decisions
traceable and citable rather than buried in a function.
"""

from decimal import Decimal, InvalidOperation

from app.erp.facts import FactValue
from app.rules.model import Clause, Condition, LiteralValue, Rule, RuleMatch, RuleSet

#: Operators that take no ``value`` — they ask about the fact alone.
_UNARY = {"is_true", "is_false", "is_null", "not_null"}


class RuleEvaluationError(ValueError):
    """A stored rule could not be evaluated — a malformed condition, or an unknown op.

    Fail closed: a rule the engine cannot read is not silently skipped, because "the
    rule did not fire" and "the rule was unreadable" must never look the same to a
    reviewer.
    """


def evaluate(rule_set: RuleSet, facts: dict[str, FactValue]) -> list[RuleMatch]:
    """Return every rule that fires against ``facts``, in rule-id order.

    Meta rules (R-090..R-092) are excluded: they are always in force and are handed to
    the agent separately, not "matched" against an invoice.
    """
    matches = []
    for rule in rule_set.rules:
        if rule.kind == "meta":
            continue
        match = _match_rule(rule, facts)
        if match is not None:
            matches.append(match)
    return sorted(matches, key=lambda match: match.rule_id)


def _match_rule(rule: Rule, facts: dict[str, FactValue]) -> RuleMatch | None:
    """Fire the first clause of ``rule`` whose condition holds, or return ``None``."""
    for clause in rule.clauses:
        because: list[str] = []
        if _holds(clause.when, facts, because):
            return RuleMatch(
                rule_id=rule.rule_id,
                statement=rule.statement,
                action=clause.action,
                authority_level=rule.authority_level,
                # A rule that is written in terms of another one carries it into the
                # citation list, so the decision cites everything it actually applied.
                citations=[rule.rule_id, *rule.cites],
                because=because,
                note=clause.note,
            )
    return None


def explain(clause: Clause, facts: dict[str, FactValue]) -> list[str]:
    """Render why ``clause`` holds (or does not) — used by tests and diagnostics."""
    because: list[str] = []
    _holds(clause.when, facts, because)
    return because


def _holds(condition: Condition, facts: dict[str, FactValue], because: list[str]) -> bool:
    """Evaluate one condition node, appending the leaves that held to ``because``."""
    populated = [
        form
        for form in (condition.all_of, condition.any_of, condition.not_of, condition.fact)
        if form is not None
    ]
    if len(populated) != 1:
        raise RuleEvaluationError(
            "a condition must be exactly one of: a leaf (fact + op), all, any, or not; "
            f"got {len(populated)} forms"
        )

    if condition.all_of is not None:
        # Every branch is evaluated even after one fails, so `because` still shows the
        # evidence that *was* found. Cheap here (facts are in memory) and much more
        # useful in a trace than a short-circuited half-answer.
        results = [_holds(branch, facts, because) for branch in condition.all_of]
        return all(results)

    if condition.any_of is not None:
        results = [_holds(branch, facts, because) for branch in condition.any_of]
        return any(results)

    if condition.not_of is not None:
        # Evidence from inside a negation would read backwards ("variance ≤ 2%" as the
        # reason a rule fired *because* it was not), so it is collected and discarded.
        return not _holds(condition.not_of, facts, [])

    return _leaf_holds(condition, facts, because)


def _leaf_holds(condition: Condition, facts: dict[str, FactValue], because: list[str]) -> bool:
    """Evaluate one ``fact op value`` comparison."""
    if condition.op is None:
        raise RuleEvaluationError(f"leaf condition on {condition.fact!r} has no operator")
    if condition.op not in _UNARY and condition.value is None:
        raise RuleEvaluationError(f"operator {condition.op!r} on {condition.fact!r} needs a value")

    fact_name = str(condition.fact)
    actual = facts.get(fact_name)
    held = _compare(condition.op, actual, condition.value)
    if held:
        because.append(_render(fact_name, condition.op, condition.value, actual))
    return held


def _compare(op: str, actual: FactValue, expected: LiteralValue) -> bool:
    """Apply one operator. An unknown fact is false for every comparison but the null ones."""
    if op == "is_null":
        return actual is None
    if op == "not_null":
        return actual is not None
    if actual is None:
        return False
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False

    if op == "eq":
        return _equal(actual, expected)
    if op == "ne":
        return not _equal(actual, expected)
    if op == "in":
        return any(_equal(actual, item) for item in _as_list(expected))
    if op == "not_in":
        return not any(_equal(actual, item) for item in _as_list(expected))

    left, right = _numbers(actual, expected)
    if left is None or right is None:
        # An ordering comparison against something that is not a number is a rule
        # authoring error, not a false: it would silently never fire.
        raise RuleEvaluationError(f"operator {op!r} needs numbers, got {actual!r} and {expected!r}")

    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "multiple_of":
        return right != 0 and left % right == 0

    raise RuleEvaluationError(f"unknown operator {op!r}")


def _equal(actual: FactValue, expected: LiteralValue) -> bool:
    """Equality that treats ``"4032.00"`` and ``4032`` as the same number.

    Booleans are compared as booleans first: in Python ``True == 1``, and a fact sheet
    that says ``has_po: true`` must not satisfy a rule looking for the number 1.
    """
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    left, right = _numbers(actual, expected)
    if left is not None and right is not None:
        return left == right
    return bool(actual == expected)


def _numbers(actual: FactValue, expected: LiteralValue) -> tuple[Decimal | None, Decimal | None]:
    return _decimal(actual), _decimal(expected)


def _decimal(value: LiteralValue) -> Decimal | None:
    """Read a scalar as an exact decimal, or ``None`` when it is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def _as_list(value: LiteralValue) -> list[LiteralValue]:
    return list(value) if isinstance(value, list) else [value]


def _render(fact: str, op: str, expected: LiteralValue, actual: FactValue) -> str:
    """One line of evidence: the comparison that held, and the value it held against."""
    if op in _UNARY:
        return f"{fact} {op} (actual: {actual!r})"
    return f"{fact} {op} {expected!r} (actual: {actual!r})"
