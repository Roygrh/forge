"""The skeleton agent: the runtime's own fixture, with no business domain attached.

Phase 3 seeded this agent so the walking skeleton had something to execute. Phase 4.1
replaced the demonstration with the three real accounts-payable agents
(``scripts/seed.py``), and the skeleton moved here — where it is still worth having.

Guardrail tests want an agent whose *only* interesting property is the guardrail under
test: a budget that runs out, a step limit that bites, a model that never finishes. Doing
that with the invoice validator would mean an eight-tool agent and a five-step plan
standing in for a two-step one, and a failure would no longer say which layer broke. So
the skeleton stays: one trivial tool, one decision, no rules, no ERP.

It cites **R-000**, which is deliberately *not* a rule in
``docs/01-discovery/04-tacit-rules.md`` — a placeholder that satisfies the const-locked
``require_citations`` guardrail without pretending to govern anything. The AP agents cite
governed rules for real.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dna import validate_dna
from app.models import Agent, AgentVersion, Event, Tenant
from app.tools.registry import GET_FACT_REF

SKELETON_SLUG = "skeleton-echo"
SKELETON_VERSION = "1.0.0"

SKELETON_DNA: dict[str, Any] = {
    "identity": {
        "name": "Skeleton Echo Agent",
        "slug": SKELETON_SLUG,
        "version": SKELETON_VERSION,
        "tenant_id": "meridian-supply-co",
        "type": "workflow",
        "description": (
            "Test fixture for the Forge runtime. Looks up one governed fact with the "
            "skeleton tool and returns a cited decision. Carries no business rules and "
            "makes no external calls; it exists to exercise the loop, the gateways, and "
            "the trace end to end."
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


def publish_skeleton(
    session: Session,
    tenant: Tenant,
    *,
    slug: str = SKELETON_SLUG,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    status: str = "published",
) -> AgentVersion:
    """Publish the skeleton, or a variant of it, for one test.

    ``mutate`` receives the document before it is validated, so a test can move one
    guardrail (a budget, a step limit) without inventing a whole agent — and
    ``validate_dna`` keeps the result an honest definition rather than a convenient
    fixture.
    """
    document: dict[str, Any] = json.loads(json.dumps(SKELETON_DNA))
    document["identity"]["slug"] = slug
    if mutate is not None:
        mutate(document)
    validate_dna(document)

    agent = session.scalar(
        select(Agent).where(Agent.tenant_id == tenant.tenant_id, Agent.slug == slug)
    )
    if agent is None:
        agent = Agent(
            tenant_id=tenant.tenant_id,
            slug=slug,
            name=document["identity"]["name"],
            type=document["identity"]["type"],
            description=document["identity"]["description"],
        )
        session.add(agent)
        session.flush()

    existing = session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == SKELETON_VERSION
        )
    )
    if existing is not None:
        return existing

    version = AgentVersion(
        tenant_id=tenant.tenant_id,
        agent_id=agent.id,
        version=SKELETON_VERSION,
        dna=document,
        status=status,
        published_at=datetime.now(UTC) if status == "published" else None,
    )
    session.add(version)
    session.flush()
    session.add(
        Event(
            tenant_id=tenant.tenant_id,
            type="version.published",
            actor="test",
            agent_version_id=version.id,
            payload={"agent": f"{slug}@{SKELETON_VERSION}", "gate": "bypassed:test"},
        )
    )
    session.commit()
    return version
