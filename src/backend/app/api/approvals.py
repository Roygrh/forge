"""Approval endpoints: read the queue, approve, reject — and nothing else.

Four operations plus a report, and the shape of the set is the governance statement.
There is **no extend, no snooze, no bulk-approve, and no auto-approve**: expiry is
enforced server-side and always cancels (FR-E3), so an operation that moved a deadline
would be the one hole through every control this phase builds. Its absence is not an
omission to fill in later — ``docs/02-architecture/api/openapi.yaml`` says so in the
contract, and ``tests/test_approvals.py`` fails if such a route ever appears.

Reading needs ``read``; deciding needs ``approval.decide``, which only the approver role
holds and which no role holding ``agent.configure`` may ever hold (NFR-5). A refused
decision is **recorded**, not merely refused — "who tried to release what, and was
stopped" is exactly the question a compliance review asks months later.

The autonomy-promotion report (FR-E5) is served here too, and is read-only in the
strongest sense available: there is no endpoint anywhere that applies it. Promotion means
publishing a new DNA version through its eval gate.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ActorDep, ApprovalQueueDep
from app.api.errors import ApiError
from app.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    AutonomyCandidateResponse,
)
from app.approvals import (
    ApprovalError,
    ApprovalNotFoundError,
    ApprovalQueue,
    ApprovalRecord,
    ApprovalStatus,
    autonomy_report,
)
from app.db import SessionDep
from app.governance import GovernanceReason, Permission, explain
from app.models import Event

router = APIRouter(tags=["Approvals"])

#: Appended when a role without ``approval.decide`` tries to release or refuse an action.
EVENT_PERMISSION_DENIED = "governance.permission_denied"


@router.get(
    "/approvals",
    response_model=list[ApprovalResponse],
    summary="List approvals (defaults to pending)",
)
async def list_approvals(
    queue: ApprovalQueueDep,
    actor: ActorDep,
    status_filter: Annotated[
        ApprovalStatus,
        Query(alias="status", description="Which state to list; defaults to the live queue"),
    ] = "pending",
) -> list[ApprovalResponse]:
    """The queue, oldest first, each item carrying the evidence to decide it (FR-E1).

    Expiry runs before the read, so nothing here has already lapsed — and asking for the
    queue is one of the ways a lapsed approval gets canceled.
    """
    actor.require(Permission.READ)
    now = queue.now()
    return [ApprovalResponse.of(record, now=now) for record in await queue.listing(status_filter)]


@router.get(
    "/approvals/report",
    response_model=list[AutonomyCandidateResponse],
    summary="Autonomy-promotion report: approval rates per action category (read-only)",
)
async def approval_report(session: SessionDep, actor: ActorDep) -> list[AutonomyCandidateResponse]:
    """What the approvers actually did, per agent version and tool (FR-E5).

    A report and only a report: it names candidates for an autonomy upgrade and applies
    none of them. Autonomy lives in a published DNA document, so raising it is an
    authoring change that goes through the eval gate — never a statistic crossing a line.
    """
    actor.require(Permission.READ)
    return [AutonomyCandidateResponse.of(stats) for stats in await autonomy_report(session)]


@router.get(
    "/approvals/{approval_id}",
    response_model=ApprovalResponse,
    summary="Get one approval with its evidence",
)
async def get_approval(
    approval_id: uuid.UUID, queue: ApprovalQueueDep, actor: ActorDep
) -> ApprovalResponse:
    """One approval, its proposed action, and everything the agent gathered first."""
    actor.require(Permission.READ)
    return ApprovalResponse.of(await _record(queue, approval_id), now=queue.now())


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=ApprovalResponse,
    summary="Approve a pending action (resumes the run)",
)
async def approve(
    approval_id: uuid.UUID,
    queue: ApprovalQueueDep,
    session: SessionDep,
    actor: ActorDep,
    body: ApprovalDecisionRequest | None = None,
) -> ApprovalResponse:
    """Release exactly this action; the run continues and carries it out.

    The body may carry a note and carries no arguments: what runs is the call the agent
    parked, with the parameters the gateway already validated (FR-E2).
    """
    await _require_decide(session, queue, approval_id, actor)
    note = body.note if body is not None else None
    try:
        record = await queue.approve(approval_id, actor=actor.identity, note=note)
    except ApprovalError as exc:
        raise _as_api_error(exc) from exc
    return ApprovalResponse.of(record, now=queue.now())


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=ApprovalResponse,
    summary="Reject a pending action (cancels the run)",
)
async def reject(
    approval_id: uuid.UUID,
    queue: ApprovalQueueDep,
    session: SessionDep,
    actor: ActorDep,
    body: ApprovalDecisionRequest | None = None,
) -> ApprovalResponse:
    """Refuse the action and cancel its run. Nothing is executed."""
    await _require_decide(session, queue, approval_id, actor)
    note = body.note if body is not None else None
    try:
        record = await queue.reject(approval_id, actor=actor.identity, note=note)
    except ApprovalError as exc:
        raise _as_api_error(exc) from exc
    return ApprovalResponse.of(record, now=queue.now())


async def _record(queue: ApprovalQueue, approval_id: uuid.UUID) -> ApprovalRecord:
    try:
        return await queue.get(approval_id)
    except ApprovalError as exc:
        raise _as_api_error(exc) from exc


async def _require_decide(
    session: SessionDep, queue: ApprovalQueue, approval_id: uuid.UUID, actor: ActorDep
) -> None:
    """Refuse a role that may not decide approvals — and record that it tried (NFR-5).

    The approval is looked up first so the refusal can name what it protected: which
    tenant, which run, which action. A denial that cannot say what it stopped is not much
    of an audit record. A caller that may not decide is told nothing about the approval
    beyond the 403 itself.
    """
    if actor.allows(Permission.APPROVAL_DECIDE):
        return

    record = await _record(queue, approval_id)
    session.add(
        Event(
            tenant_id=record.approval.tenant_id,
            type=EVENT_PERMISSION_DENIED,
            actor=actor.identity,
            run_id=record.run.id,
            agent_version_id=record.agent_version.id,
            approval_id=record.approval.id,
            payload={
                "reason_code": str(GovernanceReason.PERMISSION_DENIED),
                "explanation": explain(GovernanceReason.PERMISSION_DENIED),
                "operation": "approval.decide",
                "role": str(actor.role),
                "detail": (
                    f"role {actor.role} attempted to decide approval {record.approval.id} "
                    f"({record.invocation.tool_ref}) without the approval.decide "
                    "permission; the action stays parked"
                ),
            },
        )
    )
    await session.commit()
    actor.require(Permission.APPROVAL_DECIDE)


def _as_api_error(exc: ApprovalError) -> ApiError:
    """Map a queue refusal onto the platform's error shape."""
    code = (
        status.HTTP_404_NOT_FOUND
        if isinstance(exc, ApprovalNotFoundError)
        else status.HTTP_409_CONFLICT
    )
    return ApiError(code, exc.code, exc.message)
