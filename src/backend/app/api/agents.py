"""Agent catalog endpoints: the read surface, draft authoring, and the eval-gated publish.

The SPA needs two things before it can start a run: which agents exist, and which of
their versions is published. Both are contracted in
``docs/02-architecture/api/openapi.yaml``, and Phase 4.5 adds the write half that was
deliberately deferred until the eval runner existed: ``POST /agents/{agentId}/versions``
creates a **draft**, and ``POST .../publish`` is **the publish gate** (FR-F2) — it
refuses with 409 unless the version has a completed, passing eval run for the suite its
own DNA declares. There is no force flag, no admin bypass, and no other route to
``status = published``; the only versions that ever skipped the gate are the seeded
ones, which carry ``published_eval_run_id = null`` as the visible mark of that
documented exception (``scripts/seed.py``).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import Actor, ActorDep
from app.api.errors import ApiError
from app.api.schemas import (
    AgentResponse,
    AgentVersionResponse,
    CreateAgentVersion,
    ResumeVersionRequest,
    SuspendVersionRequest,
)
from app.db import SessionDep
from app.dna import DnaValidationError, validate_dna
from app.governance import GovernanceReason, Permission, explain
from app.models import Agent, AgentVersion, EvalRun, EvalSuite, Event
from app.observability import resume_version, suspend_version

router = APIRouter(tags=["Agents"])

#: Appended when a caller is refused an operation on a resource that exists — the same
#: audit fact ``app.api.runs`` records for a refused start (NFR-5).
EVENT_PERMISSION_DENIED = "governance.permission_denied"


@router.get("/agents", response_model=list[AgentResponse], summary="List agents in the catalog")
async def list_agents(session: SessionDep, actor: ActorDep) -> list[AgentResponse]:
    """Return every agent, oldest first.

    Unpaginated on purpose: the catalog is a handful of agents per tenant, and a page
    cursor invented before there is anything to page through is a contract to maintain
    for nothing.
    """
    actor.require(Permission.READ)
    agents = await session.scalars(select(Agent).order_by(Agent.created_at, Agent.slug))
    return [AgentResponse.of(agent) for agent in agents]


@router.get(
    "/agents/{agent_id}/versions",
    response_model=list[AgentVersionResponse],
    summary="List versions of an agent",
)
async def list_agent_versions(
    agent_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> list[AgentVersionResponse]:
    """Return one agent's versions, newest first.

    A missing agent is a 404 rather than an empty list: "this agent has no versions"
    and "there is no such agent" are different answers, and the caller has to be able
    to tell them apart.
    """
    actor.require(Permission.READ)
    if await session.get(Agent, agent_id) is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "agent_not_found", f"no agent {agent_id}")

    versions = await session.scalars(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.created_at.desc())
    )
    return [AgentVersionResponse.of(version) for version in versions]


@router.get(
    "/agents/{agent_id}/versions/{version}",
    response_model=AgentVersionResponse,
    summary="Get one agent version, including its DNA",
)
async def get_agent_version(
    agent_id: uuid.UUID, version: str, session: SessionDep, actor: ActorDep
) -> AgentVersionResponse:
    """Return one version with the exact DNA document the runtime would execute."""
    actor.require(Permission.READ)
    return AgentVersionResponse.of(await _load_version(session, agent_id, version))


@router.post(
    "/agents/{agent_id}/versions",
    response_model=AgentVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent version (draft) from a DNA document",
)
async def create_agent_version(
    agent_id: uuid.UUID, body: CreateAgentVersion, session: SessionDep, actor: ActorDep
) -> AgentVersionResponse:
    """Admit one DNA document as a **draft** — published only through the eval gate.

    The document is validated against ``dna-schema.json`` before the row exists (golden
    rule 1); invalid DNA is a 400 carrying every violation. The version number comes
    from ``identity.version`` inside the document, and an existing version is a 409:
    versions are immutable, so changing behaviour means authoring the next one.
    """
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "agent_not_found", f"no agent {agent_id}")

    await _require_recorded(
        session,
        actor,
        Permission.AGENT_CONFIGURE,
        operation="version.create",
        tenant_id=agent.tenant_id,
        detail=f"role {actor.role} attempted to create a version of agent {agent.slug!r}",
    )

    try:
        validate_dna(body.dna)
    except DnaValidationError as exc:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "dna_invalid",
            "the document does not satisfy the agent DNA schema",
            {"errors": exc.errors},
        ) from exc

    identity = body.dna["identity"]
    if identity["slug"] != agent.slug:
        # A version stored under one agent describing another would break the promise
        # that a run's history resolves to the definition that produced it (FR-A3).
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "dna_identity_mismatch",
            f"dna identity.slug {identity['slug']!r} does not match agent {agent.slug!r}",
        )

    version_number = str(identity["version"])
    existing = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == version_number
        )
    )
    if existing is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "version_exists",
            f"version {version_number} of {agent.slug!r} already exists; versions are "
            "immutable — author the next version instead",
        )

    row = AgentVersion(
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        version=version_number,
        dna=body.dna,
        status="draft",
    )
    session.add(row)
    await session.flush()
    session.add(
        Event(
            tenant_id=agent.tenant_id,
            type="version.created",
            actor=actor.identity,
            agent_version_id=row.id,
            payload={
                "agent_version_id": str(row.id),
                "agent": f"{agent.slug}@{version_number}",
                "status": "draft",
                "suite_ref": body.dna.get("evals", {}).get("suite_ref"),
            },
        )
    )
    await session.commit()
    return AgentVersionResponse.of(row)


@router.post(
    "/agents/{agent_id}/versions/{version}/publish",
    response_model=AgentVersionResponse,
    summary="Publish a version (hard eval gate)",
)
async def publish_agent_version(
    agent_id: uuid.UUID, version: str, session: SessionDep, actor: ActorDep
) -> AgentVersionResponse:
    """Transition draft → published **only** on a completed, passing eval run (FR-F2).

    The gate reads the suite the version's own DNA declares (``evals.suite_ref``) and
    demands a completed :class:`~app.models.EvalRun` with ``passed = true`` for exactly
    this version and exactly that suite. Anything less — no run, an unfinished run, a
    failed run, a passing run of a *different* version or a *different* suite — is a
    409, and the version stays a draft. There is deliberately no parameter that relaxes
    any of this: the gate cannot be bypassed through this API.
    """
    row = await _load_version(session, agent_id, version)

    await _require_recorded(
        session,
        actor,
        Permission.AGENT_PUBLISH,
        operation="version.publish",
        tenant_id=row.tenant_id,
        agent_version_id=row.id,
        detail=f"role {actor.role} attempted to publish {agent_id}@{version}",
    )

    if row.status != "draft":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "version_not_draft",
            f"version {version} is {row.status}; only a draft can be published",
            {"status": row.status},
        )

    suite_ref = str(row.dna.get("evals", {}).get("suite_ref", ""))
    slug, _, suite_version = suite_ref.partition("@")
    suite = await session.scalar(
        select(EvalSuite).where(
            EvalSuite.tenant_id == row.tenant_id,
            EvalSuite.slug == slug,
            EvalSuite.version == suite_version,
        )
    )
    if suite is None:
        # A declared suite the platform cannot find is an unmet gate, not a waiver:
        # fail closed (golden rule 3).
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "publish_gate_unmet",
            f"eval suite {suite_ref!r} is not installed, so the gate cannot be satisfied",
            {"suite_ref": suite_ref, "latest_eval_run_passed": None},
        )

    latest = (
        await session.scalars(
            select(EvalRun)
            .where(
                EvalRun.suite_id == suite.id,
                EvalRun.agent_version_id == row.id,
                EvalRun.status == "completed",
            )
            .order_by(EvalRun.created_at.desc())
        )
    ).first()
    if latest is None or latest.passed is not True:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "publish_gate_unmet",
            f"eval suite {suite_ref} has not passed for this version; it stays a draft",
            {
                "suite_ref": suite_ref,
                "latest_eval_run_id": str(latest.id) if latest is not None else None,
                "latest_eval_run_passed": latest.passed if latest is not None else None,
                "passed_count": latest.passed_count if latest is not None else None,
                "total": latest.total if latest is not None else None,
            },
        )

    row.status = "published"
    row.published_at = datetime.now(UTC)
    # The gate's evidence, kept on the row: which passing run earned this publish.
    # A seeded version's null here is what marks the one documented exception.
    row.published_eval_run_id = latest.id
    session.add(
        Event(
            tenant_id=row.tenant_id,
            type="version.published",
            actor=actor.identity,
            agent_version_id=row.id,
            payload={
                "agent_version_id": str(row.id),
                "agent": f"{row.dna.get('identity', {}).get('slug')}@{row.version}",
                "gate": f"eval_run:{latest.id}",
                "suite_ref": suite_ref,
                "passed_count": latest.passed_count,
                "total": latest.total,
            },
        )
    )
    await session.commit()
    return AgentVersionResponse.of(row)


@router.post(
    "/agents/{agent_id}/versions/{version}/suspend",
    response_model=AgentVersionResponse,
    summary="Suspend a published version (manual)",
)
async def suspend_agent_version(
    agent_id: uuid.UUID,
    version: str,
    session: SessionDep,
    actor: ActorDep,
    body: SuspendVersionRequest | None = None,
) -> AgentVersionResponse:
    """Transition published → suspended by hand, on the record (FR-A4, FR-G4).

    The fail-safe direction: it stops things, so both the configurator and the admin
    hold it. New runs of the version are refused with ``agent_suspended`` from the next
    request on, and the suspension — who, when, why — is an appended event.
    """
    row = await _load_version(session, agent_id, version)
    await _require_recorded(
        session,
        actor,
        Permission.AGENT_SUSPEND,
        operation="version.suspend",
        tenant_id=row.tenant_id,
        agent_version_id=row.id,
        detail=f"role {actor.role} attempted to suspend {agent_id}@{version}",
    )

    if row.status != "published":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "version_not_published",
            f"version {version} is {row.status}; only a published version can be suspended",
            {"status": row.status},
        )

    reason = body.reason if body is not None else None
    await suspend_version(
        session,
        row,
        actor=actor.identity,
        trigger="manual",
        detail=reason or f"suspended manually by {actor.identity}",
    )
    return AgentVersionResponse.of(row)


@router.post(
    "/agents/{agent_id}/versions/{version}/resume",
    response_model=AgentVersionResponse,
    summary="Resume a suspended version (admin only)",
)
async def resume_agent_version(
    agent_id: uuid.UUID,
    version: str,
    session: SessionDep,
    actor: ActorDep,
    body: ResumeVersionRequest | None = None,
) -> AgentVersionResponse:
    """Transition suspended → published — the only way out of a suspension.

    Needs ``agent.resume``, which only the admin role holds and which no role holding
    ``agent.configure`` or ``agent.publish`` may ever hold: whoever built or shipped an
    agent cannot override the breaker that contained it. There is no automatic path —
    no cool-down, no retry window — and the resume is recorded with its actor and note.
    """
    row = await _load_version(session, agent_id, version)
    await _require_recorded(
        session,
        actor,
        Permission.AGENT_RESUME,
        operation="version.resume",
        tenant_id=row.tenant_id,
        agent_version_id=row.id,
        detail=f"role {actor.role} attempted to resume {agent_id}@{version}",
    )

    if row.status != "suspended":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "version_not_suspended",
            f"version {version} is {row.status}; only a suspended version can be resumed",
            {"status": row.status},
        )

    await resume_version(session, row, actor=actor.identity, note=body.note if body else None)
    return AgentVersionResponse.of(row)


async def _load_version(session: SessionDep, agent_id: uuid.UUID, version: str) -> AgentVersion:
    row = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id, AgentVersion.version == version
        )
    )
    if row is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "agent_version_not_found",
            f"no version {version} for agent {agent_id}",
        )
    return row


async def _require_recorded(
    session: SessionDep,
    actor: Actor,
    permission: Permission,
    *,
    operation: str,
    tenant_id: uuid.UUID,
    agent_version_id: uuid.UUID | None = None,
    detail: str,
) -> None:
    """Require a permission, recording the refusal as an audit fact before raising.

    The same discipline as a refused run start: an attempt to change the catalog by a
    role that may not is exactly what a compliance review asks about later, so the
    refusal is an event, not just a 403 (NFR-5).
    """
    if actor.allows(permission):
        return
    session.add(
        Event(
            tenant_id=tenant_id,
            type=EVENT_PERMISSION_DENIED,
            actor=actor.identity,
            agent_version_id=agent_version_id,
            payload={
                "reason_code": str(GovernanceReason.PERMISSION_DENIED),
                "explanation": explain(GovernanceReason.PERMISSION_DENIED),
                "operation": operation,
                "role": str(actor.role),
                "detail": detail,
            },
        )
    )
    await session.commit()
    actor.require(permission)
