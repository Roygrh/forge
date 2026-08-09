"""Seed the demonstration tenant, rules, governed knowledge, and the AP agents.

Idempotent: running it twice leaves exactly one Meridian Supply Co. tenant, one row per
rule, one chunk set per knowledge collection, one published version of each agent, and
one event apiece. Re-running is the normal case (fresh clone, restarted volume, CI), so
it must never be destructive and never duplicate.

**Existing rules are left alone.** A rule row is the AP Manager's, not the seed's: once
it exists, an operator may have edited it — that is the entire point of rules being data
(:mod:`app.rules`) — and a re-seed that quietly reverted her change would make the
mechanism a lie. Pass ``--refresh-rules`` to deliberately restore the shipped catalogue.
Knowledge chunks follow the same convention: collections that already hold chunks are
left alone unless ``--refresh-knowledge`` deliberately rebuilds them (which is also how
a changed embedding provider re-embeds the corpus).

Usage (from src/backend, with DATABASE_URL set or the compose default reachable):

    python -m scripts.seed
    python -m scripts.seed --refresh-rules --refresh-knowledge
"""

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import sync_session
from app.dna import SHIPPED_AGENT_SLUGS, load_agent_dna, validate_dna
from app.knowledge import ingest_knowledge
from app.models import Agent, AgentVersion, Event, Rule, Tenant
from app.rules.catalog import CATALOG, RULESET_VERSION

MERIDIAN_SLUG = "meridian-supply-co"
MERIDIAN_NAME = "Meridian Supply Co."


def seed_tenant(session: Session) -> tuple[Tenant, bool]:
    """Ensure the Meridian tenant exists; return it and whether it was created."""
    existing = session.scalar(select(Tenant).where(Tenant.slug == MERIDIAN_SLUG))
    if existing is not None:
        return existing, False

    tenant = Tenant(slug=MERIDIAN_SLUG, name=MERIDIAN_NAME)
    session.add(tenant)
    session.flush()  # assigns tenant_id from the database

    # ADR-008: a state change and its event are written in the same transaction.
    # Even seeding is not exempt — that is the whole point of the rule.
    session.add(
        Event(
            tenant_id=tenant.tenant_id,
            type="tenant.created",
            actor="seed-script",
            payload={"slug": tenant.slug, "name": tenant.name, "source": "scripts/seed.py"},
        )
    )
    return tenant, True


def seed_rules(session: Session, tenant: Tenant, *, refresh: bool = False) -> tuple[int, int]:
    """Write the captured tacit rules into the ``rules`` table.

    Returns ``(written, left_alone)``. The catalogue in :mod:`app.rules.catalog` is the
    machine-readable form of ``docs/01-discovery/04-tacit-rules.md``; from here on the
    platform reads the table, never the module, which is what makes a rule edit take
    effect without a redeploy.
    """
    existing = {
        row.rule_id: row
        for row in session.scalars(select(Rule).where(Rule.tenant_id == tenant.tenant_id))
    }

    written = 0
    for rule in CATALOG:
        row = existing.get(rule.rule_id)
        if row is not None and not refresh:
            continue

        # by_alias keeps the stored condition readable as `all`/`any`/`not` — the words
        # a person editing the row would expect; exclude_none keeps out the fields a
        # given form does not use.
        clauses: list[dict[str, Any]] = [
            clause.model_dump(by_alias=True, exclude_none=True) for clause in rule.clauses
        ]
        if row is None:
            row = Rule(tenant_id=tenant.tenant_id, rule_id=rule.rule_id)
            session.add(row)
        row.family = rule.family
        row.kind = rule.kind
        row.statement = rule.statement
        row.authority_level = rule.authority_level
        row.version = rule.version
        row.clauses = clauses
        row.cites = list(rule.cites)
        row.source_ref = rule.source_ref
        written += 1

    if written:
        session.add(
            Event(
                tenant_id=tenant.tenant_id,
                type="rules.seeded",
                actor="seed-script",
                payload={
                    "ruleset_version": RULESET_VERSION,
                    "rules_written": written,
                    "rules_left_alone": len(CATALOG) - written,
                    "refresh": refresh,
                    "source": "docs/01-discovery/04-tacit-rules.md",
                },
            )
        )
    return written, len(CATALOG) - written


def seed_knowledge(session: Session, tenant: Tenant, *, refresh: bool = False) -> tuple[int, int]:
    """Ingest the governed knowledge: SME rules + the two policy documents (FR-D1).

    Runs after :func:`seed_rules` because the SME collection is built from the
    ``rules`` table — what is ingested is what is in force, edits included. The policy
    documents are deliberately contradictory (see :mod:`app.knowledge.documents`);
    seeding them intact is the point.
    """
    return ingest_knowledge(session, tenant, refresh=refresh)


def seed_agent(session: Session, tenant: Tenant, slug: str) -> tuple[AgentVersion, bool]:
    """Ensure one shipped agent's published version exists.

    The DNA is validated against ``dna-schema.json`` before it is written — the schema
    is the central contract and the seed script is not exempt from it (golden rule 1).

    **Publishing here is a seed insert, not the publish gate.** The real transition is
    ``POST /agents/{id}/versions/{version}/publish``, which refuses (409) unless the
    version has a passing eval run for its declared suite (FR-F2). That endpoint and the
    eval runner arrive in Phase 4.5; these rows exist so the runtime has something
    published to execute in the meantime, and this is the only place a version becomes
    published without passing its gate — which is why ``published_eval_run_id`` is left
    null and the event says ``gate: bypassed:seed``.
    """
    document = load_agent_dna(slug)
    validate_dna(document)

    identity = document["identity"]
    version_number = str(identity["version"])

    agent = session.scalar(
        select(Agent).where(Agent.tenant_id == tenant.tenant_id, Agent.slug == slug)
    )
    if agent is None:
        agent = Agent(
            tenant_id=tenant.tenant_id,
            slug=slug,
            name=identity["name"],
            type=identity["type"],
            description=identity["description"],
        )
        session.add(agent)
        session.flush()
        session.add(
            Event(
                tenant_id=tenant.tenant_id,
                type="agent.created",
                actor="seed-script",
                payload={"slug": slug, "agent_id": str(agent.id)},
            )
        )

    existing = session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == version_number
        )
    )
    if existing is not None:
        return existing, False

    version = AgentVersion(
        tenant_id=tenant.tenant_id,
        agent_id=agent.id,
        version=version_number,
        dna=document,
        status="published",
        published_at=datetime.now(UTC),
        # No gate evidence: nothing was evaluated. Left null on purpose so a reviewer
        # can tell a seeded version from one that earned its publish.
        published_eval_run_id=None,
    )
    session.add(version)
    session.flush()
    session.add(
        Event(
            tenant_id=tenant.tenant_id,
            type="version.published",
            actor="seed-script",
            agent_version_id=version.id,
            payload={
                "agent_version_id": str(version.id),
                "agent": f"{slug}@{version_number}",
                "gate": "bypassed:seed",
            },
        )
    )
    return version, True


def seed_ap_agents(session: Session, tenant: Tenant) -> dict[str, tuple[AgentVersion, bool]]:
    """Ensure every shipped agent is published.

    The three accounts-payable agents, plus the governance demonstration version whose
    definition forbids it to approve anything — see :data:`~app.dna.GOVERNANCE_DEMO_SLUG`.
    """
    return {slug: seed_agent(session, tenant, slug) for slug in SHIPPED_AGENT_SLUGS}


def main(argv: list[str] | None = None) -> int:
    """Seed and report what happened."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-rules",
        action="store_true",
        help="Overwrite existing rule rows with the shipped catalogue (discards edits).",
    )
    parser.add_argument(
        "--refresh-knowledge",
        action="store_true",
        help="Rebuild every knowledge collection's chunks (re-chunks and re-embeds).",
    )
    args = parser.parse_args(argv)

    with sync_session() as session:
        tenant, tenant_created = seed_tenant(session)
        written, left_alone = seed_rules(session, tenant, refresh=args.refresh_rules)
        # Rules first: the SME knowledge collection is built from the rules table.
        session.flush()
        chunks_written, chunks_left = seed_knowledge(
            session, tenant, refresh=args.refresh_knowledge
        )
        agents = seed_ap_agents(session, tenant)
        session.commit()

        print(
            f"tenant {tenant.slug} {'created' if tenant_created else 'already present'} "
            f"(tenant_id={tenant.tenant_id})"
        )
        print(
            f"rules v{RULESET_VERSION}: {written} written, {left_alone} already present "
            f"and left alone"
        )
        print(
            f"knowledge: {chunks_written} chunks written, {chunks_left} already present "
            f"and left alone"
        )
        for slug, (version, created) in agents.items():
            print(
                f"agent {slug}@{version.version} "
                f"{'published' if created else 'already present'} "
                f"(agent_version_id={version.id})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
