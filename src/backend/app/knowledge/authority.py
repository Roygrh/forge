"""The authority hierarchy: one scale for rules and documents (FR-D2, R-090).

``sme_validated > policy_2023 > policy_2019`` — the SME-captured rules override every
written policy, and the newer policy overrides the older. The scale is shared with the
``rules`` table (:mod:`app.rules.model`) so a rule and a policy paragraph are rankable
against each other, which is what lets one retrieval resolve a conflict between them.
"""

from app.rules.model import AuthorityLevel

#: Highest wins. The numbers are ordering, nothing more.
AUTHORITY_RANK: dict[AuthorityLevel, int] = {
    "sme_validated": 3,
    "policy_2023": 2,
    "policy_2019": 1,
}

#: The scale, highest first — served with every retrieval result so the ranking an
#: agent's context was assembled under is itself part of the record.
AUTHORITY_ORDER: tuple[AuthorityLevel, ...] = ("sme_validated", "policy_2023", "policy_2019")

#: The same map keyed loosely, for ranking levels that arrive as untyped strings.
_RANK_BY_NAME: dict[str, int] = {str(level): rank for level, rank in AUTHORITY_RANK.items()}


def authority_rank(level: str) -> int:
    """Rank a level; an *unknown* level ranks below every known one.

    Fail-closed: a source whose authority the platform cannot place never outranks one
    it can. It still retrieves — it just never wins a conflict.
    """
    return _RANK_BY_NAME.get(level, 0)
