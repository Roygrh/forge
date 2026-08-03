"""Run endpoints: start a run, read its status, read its trace.

Runs execute **inline**, and the response returns once the run has reached a terminal
state. A queue and a worker are a later concern; inline keeps the walking skeleton
deterministic and means the trace is complete the moment the caller has the run id. The
status code stays ``202`` to match the contract, which is written for the asynchronous
shape this will grow into.
"""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import ActorDep, LlmGatewayDep, ToolGatewayDep
from app.api.errors import ApiError
from app.api.schemas import RunResponse, RunTraceResponse, StartRun
from app.db import SessionDep
from app.models import AgentVersion, Run
from app.runtime.loop import AgentRuntime
from app.runtime.trace import load_events, project_trace

router = APIRouter(tags=["Runs"])


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a run of a published agent version",
)
async def start_run(
    body: StartRun,
    session: SessionDep,
    llm_gateway: LlmGatewayDep,
    tool_gateway: ToolGatewayDep,
    actor: ActorDep,
) -> RunResponse:
    """Execute one run of a **published** agent version and return it.

    Only published versions run: a draft has not passed its eval gate, and a suspended
    one was stopped on purpose. Either is a 409, never a run.
    """
    agent_version = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == body.agent_id, AgentVersion.version == body.version
        )
    )
    if agent_version is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "agent_version_not_found",
            f"no version {body.version} for agent {body.agent_id}",
        )
    if agent_version.status != "published":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "agent_version_not_published",
            f"version {body.version} is {agent_version.status}; only published versions run",
            {"status": agent_version.status},
        )

    runtime = AgentRuntime(session, llm_gateway=llm_gateway, tool_gateway=tool_gateway)
    run = await runtime.start_run(
        agent_version=agent_version,
        run_input=body.input,
        trigger="api",
        actor=actor,
    )
    return RunResponse.of(run)


@router.get("/runs/{run_id}", response_model=RunResponse, summary="Get run status and summary")
async def get_run(run_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> RunResponse:
    """Return one run."""
    return RunResponse.of(await _load_run(session, run_id))


@router.get(
    "/runs/{run_id}/trace",
    response_model=RunTraceResponse,
    summary="Get the full run trace (steps, tool calls, decisions)",
)
async def get_run_trace(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> RunTraceResponse:
    """Return the ordered trace, projected from the run's append-only events.

    Nothing here reads ``run_steps`` or ``tool_invocations``: the trace is derived from
    the event log alone, so what the viewer shows is what was actually recorded
    (ADR-008, FR-G1).
    """
    run = await _load_run(session, run_id)
    steps, events = project_trace(await load_events(session, run.id))
    return RunTraceResponse(run_id=run.id, steps=steps, events=events)


async def _load_run(session: SessionDep, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "run_not_found", f"no run {run_id}")
    return run
