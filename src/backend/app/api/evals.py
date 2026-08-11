"""Eval endpoints: list suites, run one against a version, read the score (FR-F1..F3).

A suite run executes **inline**, like a run does: the response returns once every case
has been scored, so the 202 body already carries the verdict the publish gate will read.
Each case runs against a private, freshly built MeridianERP and the rules currently in
force — see :mod:`app.evals.runner` for why that is what the gate should certify.

Running a suite needs ``agent.configure`` (it is authoring work: the score exists to
earn a publish); reading needs ``read``, so an auditor can inspect every verdict without
being able to produce one.
"""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.api.deps import ActorDep, ClockDep, LlmGatewayDep
from app.api.errors import ApiError
from app.api.schemas import EvalRunResponse, EvalSuiteResponse, RunSuiteRequest
from app.db import SessionDep
from app.evals import EvalRunner
from app.governance import Permission
from app.models import AgentVersion, EvalCase, EvalRun, EvalSuite

router = APIRouter(tags=["Evals"])


@router.get("/eval/suites", response_model=list[EvalSuiteResponse], summary="List eval suites")
async def list_suites(session: SessionDep, actor: ActorDep) -> list[EvalSuiteResponse]:
    """Return every suite with its case count, oldest first."""
    actor.require(Permission.READ)
    rows = await session.execute(
        select(EvalSuite, func.count(EvalCase.id))
        .outerjoin(EvalCase, EvalCase.suite_id == EvalSuite.id)
        .group_by(EvalSuite.id)
        .order_by(EvalSuite.created_at, EvalSuite.slug)
    )
    return [EvalSuiteResponse.of(suite, case_count=count) for suite, count in rows]


@router.post(
    "/eval/suites/{suite_id}/run",
    response_model=EvalRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a suite against an agent version",
)
async def run_suite(
    suite_id: uuid.UUID,
    body: RunSuiteRequest,
    session: SessionDep,
    llm_gateway: LlmGatewayDep,
    clock: ClockDep,
    actor: ActorDep,
) -> EvalRunResponse:
    """Execute every case in the suite and record the ``passed`` verdict (FR-F2).

    Any version may be evaluated — draft, published, or suspended. The gate cares that
    a **draft earns** its publish; scoring a published version again is how a rule
    change is checked against the versions already live.
    """
    actor.require(Permission.AGENT_CONFIGURE)
    suite = await session.get(EvalSuite, suite_id)
    if suite is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "suite_not_found", f"no eval suite {suite_id}")

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

    runner = EvalRunner(session, llm_gateway=llm_gateway, clock=clock, actor=actor.identity)
    eval_run = await runner.run_suite(suite=suite, agent_version=agent_version)
    return EvalRunResponse.of(eval_run)


@router.get(
    "/eval/runs",
    response_model=list[EvalRunResponse],
    summary="List eval runs, optionally for one agent version",
)
async def list_eval_runs(
    session: SessionDep,
    actor: ActorDep,
    agent_version_id: uuid.UUID | None = None,
) -> list[EvalRunResponse]:
    """Return eval runs newest first — how a caller learns whether a version's gate is met.

    ``agent_version_id`` narrows the list to one version, which is the query the catalog
    UI asks before enabling its publish button.
    """
    actor.require(Permission.READ)
    query = select(EvalRun).order_by(EvalRun.created_at.desc())
    if agent_version_id is not None:
        query = query.where(EvalRun.agent_version_id == agent_version_id)
    runs = await session.scalars(query)
    return [EvalRunResponse.of(run) for run in runs]


@router.get(
    "/eval/runs/{eval_run_id}",
    response_model=EvalRunResponse,
    summary="Get eval run results (per-case and aggregate)",
)
async def get_eval_run(
    eval_run_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> EvalRunResponse:
    """Return one eval run with its per-case detail."""
    actor.require(Permission.READ)
    eval_run = await session.get(EvalRun, eval_run_id)
    if eval_run is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "eval_run_not_found", f"no eval run {eval_run_id}"
        )
    return EvalRunResponse.of(eval_run)
