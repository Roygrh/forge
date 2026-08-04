"""Agent catalog endpoints — read-only in this phase.

The SPA needs two things before it can start a run: which agents exist, and which of
their versions is published. Both are already contracted in
``docs/02-architecture/api/openapi.yaml`` (``GET /agents`` and
``GET /agents/{agentId}/versions``), so this module implements the contract rather than
extending it.

The write half of the catalog — create agent, create draft version, publish, suspend —
is deliberately absent. Publishing is eval-gated (FR-F2) and there is no eval runner
yet; shipping a publish endpoint that could not enforce its gate would be a governance
hole, not a head start. It arrives with the runner in Phase 4.4.
"""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import ActorDep
from app.api.errors import ApiError
from app.api.schemas import AgentResponse, AgentVersionResponse
from app.db import SessionDep
from app.models import Agent, AgentVersion

router = APIRouter(tags=["Agents"])


@router.get("/agents", response_model=list[AgentResponse], summary="List agents in the catalog")
async def list_agents(session: SessionDep, actor: ActorDep) -> list[AgentResponse]:
    """Return every agent, oldest first.

    Unpaginated on purpose: the catalog is a handful of agents per tenant, and a page
    cursor invented before there is anything to page through is a contract to maintain
    for nothing.
    """
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
    if await session.get(Agent, agent_id) is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "agent_not_found", f"no agent {agent_id}")

    versions = await session.scalars(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.created_at.desc())
    )
    return [AgentVersionResponse.of(version) for version in versions]
