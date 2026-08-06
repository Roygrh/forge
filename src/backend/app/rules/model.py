"""The shape of a governed rule, and of one firing of it.

A rule is **data**: an id, the statement its owner signed off, an authority level, and a
list of *clauses* — each a machine-readable condition over the ERP fact sheet plus the
action it implies. Nothing in this module knows what R-001 says; it knows what a rule
*is*.

The condition grammar is deliberately tiny — leaves, ``all``, ``any``, ``not``. Small
enough that a non-programmer can read a rule row and see what it will do, and expressive
enough for every rule in ``docs/01-discovery/04-tacit-rules.md``, including the
"whichever is greater" tolerances (an ``any`` of two leaves) and the tiered vendor cap
(two clauses on one rule).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.actions import DecisionAction

#: What a rule is *for*.
#:
#: ``business``   — matched against the facts; when it fires it proposes an action.
#: ``definition`` — matched, but proposes no action of its own; it exists to be named by
#:                  other rules and cited alongside them (R-010, the tolerance band).
#: ``meta``       — platform behaviour with no fact conditions (R-090..R-092). Always in
#:                  force, always shown to the agent, never "matched".
RuleKind = Literal["business", "definition", "meta"]

#: Highest wins on conflict (FR-D2, R-090). The knowledge layer in Phase 4.3 ranks
#: documents on this same scale; the SME-validated rule set sits at the top of it.
AuthorityLevel = Literal["sme_validated", "policy_2023", "policy_2019"]

#: What a rule may compare a fact *against*: a JSON scalar, or a list of them for the
#: membership operators. Narrow on purpose — a threshold is a literal, and a condition
#: that could hold an arbitrary object would be a small programming language in a column.
LiteralValue = str | int | float | bool | list[str | int | float | bool] | None

#: The comparisons a rule may make. Every one is a pure predicate over one fact and one
#: literal from the rule row — which is what keeps the thresholds in the data.
Operator = Literal[
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "in",
    "not_in",
    "multiple_of",
    "is_true",
    "is_false",
    "is_null",
    "not_null",
]


class Condition(BaseModel):
    """One node of a rule's condition tree.

    Exactly one form is populated: a leaf (``fact`` + ``op``), or one of the three
    combinators. Mixing them is rejected — an ambiguous condition is not a condition.
    """

    # `all`, `any` and `not` are Python builtins, so the fields are named ``*_of`` and
    # aliased to the words a rule row actually uses. ``populate_by_name`` keeps both
    # spellings working, which is what lets a test construct one in Python.
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fact: str | None = None
    op: Operator | None = None
    value: LiteralValue = None

    all_of: list["Condition"] | None = Field(default=None, alias="all")
    any_of: list["Condition"] | None = Field(default=None, alias="any")
    not_of: "Condition | None" = Field(default=None, alias="not")


class Clause(BaseModel):
    """One "when this holds, do that" branch of a rule.

    Clauses are evaluated in order and the first match wins, which is how a single rule
    id covers a tiered outcome (R-003: auto-approve up to $5,000, escalate above it)
    without splitting into two ids nobody could cite.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    when: Condition
    action: DecisionAction | None = None
    note: str = ""


class Rule(BaseModel):
    """One governed rule, exactly as it is stored and retrieved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    family: str
    kind: RuleKind
    statement: str
    authority_level: AuthorityLevel
    version: str
    clauses: list[Clause] = Field(default_factory=list)
    #: Rules to cite *with* this one when it fires. R-001 is written in terms of the
    #: tolerance band R-010 defines, so a decision that applies R-001 has applied R-010
    #: too and must say so (R-092).
    cites: list[str] = Field(default_factory=list)
    source_ref: str | None = None


class RuleMatch(BaseModel):
    """One rule firing, with the evidence for it.

    ``because`` renders the leaves that held, with the fact values they held against, so
    a reviewer never has to take "R-011 applied" on faith.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    statement: str
    action: DecisionAction | None
    authority_level: AuthorityLevel
    citations: list[str]
    because: list[str]
    note: str = ""


class RuleSet(BaseModel):
    """The rules in force, as one retrieved unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    rules: list[Rule]

    def by_id(self, rule_id: str) -> Rule | None:
        """One rule, or ``None`` — a citation for a rule that no longer exists is a bug."""
        return next((rule for rule in self.rules if rule.rule_id == rule_id), None)

    @property
    def meta_rules(self) -> list[Rule]:
        """The platform-behaviour rules (R-090..R-092), always in force."""
        return [rule for rule in self.rules if rule.kind == "meta"]
