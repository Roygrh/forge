"""Seed the demonstration tenant and the Phase 3.2 skeleton agent.

Idempotent: running it twice leaves exactly one Meridian Supply Co. tenant, one
skeleton agent, one published version of it, and one event apiece. Re-running is the
normal case (fresh clone, restarted volume, CI), so it must never be destructive and
never duplicate.

Usage (from src/backend, with DATABASE_URL set or the compose default reachable):

    python -m scripts.seed
"""

import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import sync_session
from app.dna import validate_dna
from app.models import Agent, AgentVersion, Event, Tenant
from app.tools.registry import GET_FACT_REF

MERIDIAN_SLUG = "meridian-supply-co"
MERIDIAN_NAME = "Meridian Supply Co."

SKELETON_SLUG = "skeleton-echo"
SKELETON_VERSION = "1.0.0"

#: The Phase 3.2 walking-skeleton agent: one trivial tool, one decision, no business
#: rules. It exists to prove the loop end to end, not to be useful.
#:
#: It cites **R-000**, which is deliberately *not* a rule in
#: ``docs/01-discovery/04-tacit-rules.md`` — it is a placeholder that satisfies the
#: const-locked ``require_citations`` guardrail while the knowledge layer that serves
#: real R-xxx rules is still ahead (Phase 4.3). The accounts-payable agent in Phase 4.2
#: cites governed rules for real.
SKELETON_DNA: dict[str, Any] = {
    "identity": {
        "name": "Skeleton Echo Agent",
        "slug": SKELETON_SLUG,
        "version": SKELETON_VERSION,
        "tenant_id": MERIDIAN_SLUG,
        "type": "workflow",
        "description": (
            "Walking-skeleton agent for the Forge runtime. Looks up one governed fact "
            "with the skeleton tool and returns a cited decision. Carries no business "
            "rules and makes no external calls; it exists to exercise the loop, the "
            "gateways, and the trace end to end."
        ),
    },
    "instructions": {
        # Empty on purpose: instruction blocks are resolved by a registry that does not
        # exist yet, and the runtime refuses to run a definition whose blocks it cannot
        # resolve rather than quietly running a less-instructed agent.
        "system_blocks": [],
        "task_prompt": (
            "Look up the requested topic with the get_fact tool, then decide. "
            "Return the action auto_approve with the fact in your reasoning, citing "
            "R-000 (the placeholder rule for the skeleton agent). If the tool refuses "
            "or the topic is missing, decide escalate and say why."
        ),
    },
    "tools": [{"ref": GET_FACT_REF, "autonomy": "autonomous"}],
    "knowledge": {"collections": [], "authority_policy": "highest_wins"},
    "model": {
        # The deterministic in-process adapter (ADR-005). Swapping this block to
        # {"provider": "anthropic", "model_id": "claude-haiku-4-5"} is the only change
        # needed to run this same agent against a real model — that is the ADR's claim.
        "provider": "fake",
        "model_id": "fake-scripted-1",
        "temperature": 0,
        "max_tokens_per_run": 10000,
        "max_cost_usd_per_run": 0.05,
        "max_cost_usd_per_day": 1,
    },
    "guardrails": {
        "max_steps": 4,
        "timeout_seconds": 30,
        "escalate_on_no_rule_match": True,
        "require_citations": True,
    },
    "evals": {"suite_ref": "skeleton-eval-suite@1.0.0", "publish_gate": True},
}


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


def seed_skeleton_agent(session: Session, tenant: Tenant) -> tuple[AgentVersion, bool]:
    """Ensure the published skeleton agent version exists.

    The DNA is validated against ``dna-schema.json`` before it is written — the schema
    is the central contract and the seed script is not exempt from it (golden rule 1).

    **Publishing here is a seed insert, not the publish gate.** The real transition is
    ``POST /agents/{id}/versions/{version}/publish``, which refuses (409) unless the
    version has a passing eval run for its declared suite (FR-F2). That endpoint and
    the eval runner arrive in Phase 4.4; this row exists so the runtime has something
    published to execute in the meantime, and it is the only place a version becomes
    published without passing its gate.
    """
    validate_dna(SKELETON_DNA)

    agent = session.scalar(
        select(Agent).where(Agent.tenant_id == tenant.tenant_id, Agent.slug == SKELETON_SLUG)
    )
    if agent is None:
        identity = SKELETON_DNA["identity"]
        agent = Agent(
            tenant_id=tenant.tenant_id,
            slug=SKELETON_SLUG,
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
                payload={"slug": SKELETON_SLUG, "agent_id": str(agent.id)},
            )
        )

    existing = session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == SKELETON_VERSION
        )
    )
    if existing is not None:
        return existing, False

    version = AgentVersion(
        tenant_id=tenant.tenant_id,
        agent_id=agent.id,
        version=SKELETON_VERSION,
        dna=SKELETON_DNA,
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
            payload={
                "agent_version_id": str(version.id),
                "agent": f"{SKELETON_SLUG}@{SKELETON_VERSION}",
                "gate": "bypassed:seed",
            },
        )
    )
    return version, True


def main() -> int:
    """Seed and report what happened."""
    with sync_session() as session:
        tenant, tenant_created = seed_tenant(session)
        version, version_created = seed_skeleton_agent(session, tenant)
        session.commit()
        print(
            f"tenant {tenant.slug} {'created' if tenant_created else 'already present'} "
            f"(tenant_id={tenant.tenant_id})"
        )
        print(
            f"agent {SKELETON_SLUG}@{SKELETON_VERSION} "
            f"{'published' if version_created else 'already present'} "
            f"(agent_version_id={version.id})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
