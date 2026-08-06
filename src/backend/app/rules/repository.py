"""Reading the governed rule set out of the database.

Loaded fresh per request, not cached at import: that is the mechanism behind "editing a
rule needs no redeploy". The rule set is a few dozen rows, so a read per run costs
nothing measurable and buys the property that matters — the next run always sees the
rules as they are *now*.
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Rule as RuleRow
from app.rules.model import Rule, RuleSet

#: What an empty ``rules`` table means. A rule set with no rules is not an error here —
#: the agent retrieves nothing, no rule matches, and the run escalates under R-091.
#: Fail-closed by construction: a platform that lost its rules approves nothing.
EMPTY_VERSION = "0.0.0"


def _query(tenant_id: uuid.UUID | None) -> Select[tuple[RuleRow]]:
    """Rules in force, optionally scoped to one tenant.

    ``tenant_id`` is optional because one tenant is active (NFR-4) and the request that
    builds the tool gateway has no tenant context yet — the run resolves its tenant from
    its agent version, further in. Passing it is the correct call wherever it *is* known,
    and when a second tenant becomes active it stops being optional.
    """
    statement = select(RuleRow).order_by(RuleRow.rule_id)
    if tenant_id is not None:
        statement = statement.where(RuleRow.tenant_id == tenant_id)
    return statement


def _to_rule(row: RuleRow) -> Rule:
    """Parse one row into its typed form, validating the stored condition tree."""
    return Rule.model_validate(
        {
            "rule_id": row.rule_id,
            "family": row.family,
            "kind": row.kind,
            "statement": row.statement,
            "authority_level": row.authority_level,
            "version": row.version,
            "clauses": row.clauses,
            "cites": row.cites,
            "source_ref": row.source_ref,
        }
    )


def _to_rule_set(rows: list[RuleRow]) -> RuleSet:
    rules = [_to_rule(row) for row in rows]
    # Every row of one set carries the same version; take it from the data rather than
    # storing it twice, so there is nothing to keep in sync.
    version = rules[0].version if rules else EMPTY_VERSION
    return RuleSet(version=version, rules=rules)


async def load_rule_set(session: AsyncSession, tenant_id: uuid.UUID | None = None) -> RuleSet:
    """Load the rules in force, in rule-id order."""
    rows = await session.scalars(_query(tenant_id))
    return _to_rule_set(list(rows))


def load_rule_set_sync(session: Session, tenant_id: uuid.UUID | None = None) -> RuleSet:
    """Synchronous twin of :func:`load_rule_set`, for scripts and tests."""
    rows = session.scalars(_query(tenant_id))
    return _to_rule_set(list(rows))
