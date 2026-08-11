"""Run endpoints: start a run, read its status, read its trace.

Runs execute **inline**, and the response returns once the run has reached a terminal
state. A queue and a worker are a later concern; inline keeps the walking skeleton
deterministic and means the trace is complete the moment the caller has the run id. The
status code stays ``202`` to match the contract, which is written for the asynchronous
shape this will grow into.

Starting a run needs ``run.start``; reading needs ``read`` (NFR-5). A refused start is
**recorded**, not merely refused: the attempt is an audit fact, and an approver quietly
prevented from starting runs is exactly the kind of thing a compliance review asks about
months later.
"""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import ActorDep, ClockDep, LlmGatewayDep, ToolGatewayDep
from app.api.errors import ApiError
from app.api.schemas import RunResponse, RunTraceResponse, StartRun
from app.db import SessionDep
from app.governance import GovernanceReason, Permission, explain
from app.models import AgentVersion, Event, Run
from app.observability import evaluate_circuit_breaker, latest_suspensions, record_run_refusal
from app.runtime.loop import AgentRuntime
from app.runtime.trace import load_events, project_trace

router = APIRouter(tags=["Runs"])

#: Appended when a caller is refused an operation on a resource that exists. It is not a
#: run event — no run was started — but it carries the tenant and the version that were
#: targeted, so "who tried to do what, and was stopped" is answerable from the log.
EVENT_PERMISSION_DENIED = "governance.permission_denied"


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
    clock: ClockDep,
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

    # Permission is checked *after* the lookup on purpose: only now is the tenant known,
    # and a denial that cannot name what it protected is not much of an audit record.
    if not actor.allows(Permission.RUN_START):
        session.add(
            Event(
                tenant_id=agent_version.tenant_id,
                type=EVENT_PERMISSION_DENIED,
                actor=actor.identity,
                agent_version_id=agent_version.id,
                payload={
                    "reason_code": str(GovernanceReason.PERMISSION_DENIED),
                    "explanation": explain(GovernanceReason.PERMISSION_DENIED),
                    "operation": "run.start",
                    "role": str(actor.role),
                    "detail": (
                        f"role {actor.role} attempted to start a run of "
                        f"{body.agent_id}@{body.version} without the run.start permission"
                    ),
                },
            )
        )
        await session.commit()
        actor.require(Permission.RUN_START)

    if agent_version.status == "suspended":
        # Containment holding the line (FR-G4). The refusal is a governance fact with
        # the machine-readable code, appended before the 409 goes out: a suspended
        # agent's refusals must be visible in the log, not just absent from it.
        suspension = (await latest_suspensions(session, [agent_version.id])).get(agent_version.id)
        await record_run_refusal(
            session,
            agent_version,
            actor=actor.identity,
            detail=(
                f"run of {body.agent_id}@{body.version} refused: the version is suspended"
                + (
                    f" ({suspension.payload.get('detail')})"
                    if suspension is not None and suspension.payload.get("detail")
                    else ""
                )
            ),
        )
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "agent_suspended",
            explain(GovernanceReason.AGENT_SUSPENDED),
            {
                "reason_code": str(GovernanceReason.AGENT_SUSPENDED),
                "status": agent_version.status,
                "suspension": dict(suspension.payload) if suspension is not None else None,
            },
        )

    if agent_version.status != "published":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "agent_version_not_published",
            f"version {body.version} is {agent_version.status}; only published versions run",
            {"status": agent_version.status},
        )

    runtime = AgentRuntime(session, llm_gateway=llm_gateway, tool_gateway=tool_gateway, clock=clock)
    run = await runtime.start_run(
        agent_version=agent_version,
        run_input=body.input,
        trigger="api",
        actor=actor.identity,
    )
    # The run is terminal; judge the trailing window before answering (FR-G4). If this
    # run is the one that tips the rate or the spend over its threshold, the version is
    # suspended here — recorded, and already refusing by the caller's next request.
    await evaluate_circuit_breaker(session, agent_version, now=clock())
    return RunResponse.of(run)


@router.get("/runs/{run_id}", response_model=RunResponse, summary="Get run status and summary")
async def get_run(run_id: uuid.UUID, session: SessionDep, actor: ActorDep) -> RunResponse:
    """Return one run."""
    actor.require(Permission.READ)
    return RunResponse.of(await _load_run(session, run_id))


@router.get(
    "/runs/{run_id}/trace",
    response_model=RunTraceResponse,
    summary="Get the full run trace (steps, tool calls, decisions, governance blocks)",
)
async def get_run_trace(
    run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> RunTraceResponse:
    """Return the ordered trace, projected from the run's append-only events.

    Nothing here reads ``run_steps`` or ``tool_invocations``: the trace is derived from
    the event log alone, so what the viewer shows is what was actually recorded
    (ADR-008, FR-G1) — governance refusals included, with the reason code that caused
    them and the explanation that goes with it.
    """
    actor.require(Permission.READ)
    run = await _load_run(session, run_id)
    steps, events = project_trace(await load_events(session, run.id))
    return RunTraceResponse(run_id=run.id, steps=steps, events=events)


async def _load_run(session: SessionDep, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "run_not_found", f"no run {run_id}")
    return run
