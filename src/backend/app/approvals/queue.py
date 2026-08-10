"""The human-in-the-loop approval queue (FR-E1..E4).

One module owns everything that can happen to a parked action, because the invariant is
about *all* of it at once: an approval leaves ``pending`` in exactly three ways, and only
one of them ever reaches a tool.

======================  ==================================  ========================
 outcome                 what the platform does              the run ends
======================  ==================================  ========================
 approve                 releases the call to the gateway    as the agent's loop decides
 reject                  nothing runs                        ``canceled``
 expire (SLA elapsed)    nothing runs                        ``canceled``
======================  ==================================  ========================

**Expiry cancels. It never approves.** That is golden rule 3 applied to the one place
where doing nothing is the most tempting default: an approval nobody answered is the
platform's own doubt, and doubt escalates. The deadline is written once when the action
is parked and read server-side here — the browser is never asked what time it is — and
there is deliberately **no extend, no snooze, and no auto-approve operation anywhere in
this module or the API above it.** Adding one would not be a feature; it would be the
removal of the control this phase exists to demonstrate.

Expiry is applied on every read of the queue as well as on every decision, so a lapsed
approval cannot be seen, decided on, or acted upon. Not a background job on purpose: a
control that only holds while a worker happens to be running is not a control, and the
question "is this still live?" has to be answered by whoever is about to rely on the
answer.

Granularity (FR-E2) is structural rather than promised. One approval row exists per
``tool_invocations`` row — a unique constraint — the release replays *that row's stored
arguments*, and the approve request carries no arguments of its own. There is no shape of
request that can approve one action and run a different one.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.evidence import Evidence, build_evidence
from app.governance import GovernanceReason, explain
from app.llm.gateway import LlmGateway
from app.models import AgentVersion, Approval, Run, ToolInvocation
from app.runtime.loop import AgentRuntime
from app.runtime.trace import TraceRecorder, load_events
from app.tools.contract import ApprovalRelease
from app.tools.gateway import ToolGateway

#: Who the log names when the *platform* ends an approval. Expiry is not a decision — it
#: is the absence of one — so it is recorded as the platform acting on a deadline rather
#: than as a person deciding anything.
SYSTEM_ACTOR = "system"

ApprovalStatus = Literal["pending", "granted", "rejected", "expired"]


class ApprovalError(Exception):
    """The queue refused an operation, with a stable code the API surfaces verbatim."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ApprovalNotFoundError(ApprovalError):
    """No such approval."""


class ApprovalNotPendingError(ApprovalError):
    """Already decided, or already expired. A decision is made once and stands."""


@dataclass(frozen=True)
class ApprovalRecord:
    """One approval with everything a person needs to decide it, and nothing they must
    open another tab for (FR-E1)."""

    approval: Approval
    invocation: ToolInvocation
    run: Run
    agent_version: AgentVersion
    evidence: Evidence

    def seconds_remaining(self, now: datetime) -> int:
        """Whole seconds left before the deadline; ``0`` once it has passed."""
        return max(0, int((self.approval.expires_at - now).total_seconds()))


class ApprovalQueue:
    """Reads the queue, and is the only thing that can end an approval.

    Built per request like the runtime it resumes, with the same gateways: an approved
    action is executed by the *same* tool gateway, against the *same* published DNA, as
    the call that was parked. There is no privileged path through the enforcement point
    for something a human said yes to — only an extra piece of evidence.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm_gateway: LlmGateway,
        tool_gateway: ToolGateway,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._llm = llm_gateway
        self._tools = tool_gateway
        self._now = clock if clock is not None else lambda: datetime.now(UTC)

    def now(self) -> datetime:
        """The clock every deadline in this queue is measured against — the server's."""
        return self._now()

    # --- Reading ---------------------------------------------------------------

    async def listing(self, status: ApprovalStatus = "pending") -> list[ApprovalRecord]:
        """Every approval in one state, oldest first — the queue as a person works it.

        Expiry runs first, always. A queue that shows an approval whose deadline has
        already passed is inviting somebody to release an action the platform has
        already refused to let through.
        """
        await self.expire_due()
        rows = await self._session.scalars(
            select(Approval).where(Approval.status == status).order_by(Approval.created_at)
        )
        return [await self._record(approval) for approval in rows]

    async def get(self, approval_id: uuid.UUID) -> ApprovalRecord:
        """One approval with its evidence. Expires first, for the same reason."""
        await self.expire_due()
        return await self._record(await self._load(approval_id))

    # --- Deciding --------------------------------------------------------------

    async def approve(
        self, approval_id: uuid.UUID, *, actor: str, note: str | None = None
    ) -> ApprovalRecord:
        """Release exactly this action, then let its run carry on and execute it.

        The order matters and is not an accident: the approval is written ``granted``
        **before** anything runs, so a crash between the two leaves a recorded approval
        and an unexecuted action — a state a person can look at — rather than an action
        that happened with no record of anyone permitting it.
        """
        approval = await self._decidable(approval_id)
        invocation = await self._invocation(approval)
        run = await self._run(approval)
        agent_version = await self._agent_version(run)
        recorder = await TraceRecorder.resume(self._session, run, actor=actor)

        decided_at = self._now()
        approval.status = "granted"
        approval.decision = "approve"
        approval.decided_by = actor
        approval.decided_at = decided_at
        approval.note = note
        # The run leaves `awaiting_approval` in the same transaction as the grant that
        # released it: there is no reading of the log in which an approval is granted and
        # the run is still described as waiting for it.
        run.status = "running"
        await recorder.record_approval(approval, invocation, actor=actor)

        await AgentRuntime(
            self._session,
            llm_gateway=self._llm,
            tool_gateway=self._tools,
            clock=self._now,
        ).resume_run(
            run=run,
            agent_version=agent_version,
            invocation=invocation,
            release=ApprovalRelease(
                approval_id=approval.id, decided_by=actor, decided_at=decided_at
            ),
        )
        return await self._record(approval)

    async def reject(
        self, approval_id: uuid.UUID, *, actor: str, note: str | None = None
    ) -> ApprovalRecord:
        """Refuse the action and cancel its run. Nothing is executed, ever."""
        approval = await self._decidable(approval_id)
        invocation = await self._invocation(approval)

        approval.status = "rejected"
        approval.decision = "reject"
        approval.decided_by = actor
        approval.decided_at = self._now()
        approval.note = note
        await self._cancel(
            approval,
            actor=actor,
            reason=GovernanceReason.APPROVAL_REJECTED,
            detail=(
                f"{actor} rejected the proposed {invocation.tool_ref} call"
                + (f": {note}" if note else "")
            ),
        )
        return await self._record(approval)

    # --- Expiry: server-side, and it cancels ------------------------------------

    async def expire_due(self) -> list[Approval]:
        """Cancel every approval whose deadline has passed (FR-E3).

        The fail-closed half of the queue, and the reason there is no extend operation:
        an approval that ran out of time is a cancellation. It is not renewed, not
        escalated into a longer wait, and above all not treated as consent. The run it
        was holding open is canceled with ``approval_expired`` recorded against it, so
        "nobody answered" is as legible in the audit log as "somebody said no".
        """
        now = self._now()
        due = list(
            await self._session.scalars(
                select(Approval)
                .where(Approval.status == "pending", Approval.expires_at <= now)
                .order_by(Approval.created_at)
                # Serialises with a concurrent approve of the same row: whichever
                # transaction gets the lock decides, and the other sees the outcome.
                .with_for_update()
            )
        )
        for approval in due:
            approval.status = "expired"
            # No `decision`: expiry is precisely the absence of one. `decided_at` is the
            # deadline itself rather than the moment the platform noticed — the authority
            # lapsed when the clock said so, not when someone next looked at the queue.
            approval.decided_by = SYSTEM_ACTOR
            approval.decided_at = approval.expires_at
            await self._cancel(
                approval,
                actor=SYSTEM_ACTOR,
                reason=GovernanceReason.APPROVAL_EXPIRED,
                detail=(
                    f"the approval expired at {approval.expires_at.isoformat()} with no "
                    f"decision (noticed at {now.isoformat()}); the run is canceled and "
                    "the action was never carried out — an approval that runs out of "
                    "time is never a yes"
                ),
            )
        return due

    # --- Internals --------------------------------------------------------------

    async def _cancel(
        self, approval: Approval, *, actor: str, reason: GovernanceReason, detail: str
    ) -> None:
        """End an approval that permits nothing, and cancel the run waiting on it."""
        invocation = await self._invocation(approval)
        run = await self._run(approval)
        recorder = await TraceRecorder.resume(self._session, run, actor=actor)

        await recorder.record_approval(approval, invocation, actor=actor, reason=reason)
        await recorder.record_governance(reason=reason, detail=detail, terminal_status="canceled")
        # No budget: nothing further was spent, and rewriting the totals from an empty
        # ledger would erase what the run did spend before it stopped.
        await recorder.finish(status="canceled", reason=reason, detail=detail)

    async def _decidable(self, approval_id: uuid.UUID) -> Approval:
        """Load an approval a person may still decide, or refuse to let them.

        Expiry is applied before the state is read, so "expired half a second ago" and
        "expired yesterday" are the same answer. A decision on anything but a live
        pending approval is a conflict, never a silent no-op.
        """
        await self.expire_due()
        approval = await self._load(approval_id, lock=True)
        if approval.status != "pending":
            raise ApprovalNotPendingError(
                "approval_not_pending",
                f"approval {approval_id} is {approval.status}; only a pending approval "
                "can be decided"
                + (
                    ". Its deadline passed and the run was canceled — expiry never "
                    "approves, and no operation extends it"
                    if approval.status == "expired"
                    else ""
                ),
            )
        return approval

    async def _load(self, approval_id: uuid.UUID, *, lock: bool = False) -> Approval:
        statement = select(Approval).where(Approval.id == approval_id)
        if lock:
            statement = statement.with_for_update()
        approval = await self._session.scalar(statement)
        if approval is None:
            raise ApprovalNotFoundError("approval_not_found", f"no approval {approval_id}")
        return approval

    async def _invocation(self, approval: Approval) -> ToolInvocation:
        invocation = await self._session.get(ToolInvocation, approval.tool_invocation_id)
        if invocation is None:  # pragma: no cover - a FK guarantees this row exists
            raise ApprovalNotFoundError(
                "tool_invocation_not_found",
                f"approval {approval.id} references a missing tool invocation",
            )
        return invocation

    async def _run(self, approval: Approval) -> Run:
        run = await self._session.get(Run, approval.run_id)
        if run is None:  # pragma: no cover - a FK guarantees this row exists
            raise ApprovalNotFoundError(
                "run_not_found", f"approval {approval.id} references a missing run"
            )
        return run

    async def _agent_version(self, run: Run) -> AgentVersion:
        version = await self._session.get(AgentVersion, run.agent_version_id)
        if version is None:  # pragma: no cover - a FK guarantees this row exists
            raise ApprovalNotFoundError(
                "agent_version_not_found", f"run {run.id} references a missing agent version"
            )
        return version

    async def _record(self, approval: Approval) -> ApprovalRecord:
        run = await self._run(approval)
        agent_version = await self._agent_version(run)
        return ApprovalRecord(
            approval=approval,
            invocation=await self._invocation(approval),
            run=run,
            agent_version=agent_version,
            evidence=build_evidence(agent_version, await load_events(self._session, run.id)),
        )


def why_approval_is_required() -> str:
    """The sentence the platform recorded when it parked the action.

    Served rather than written into the screen, so the reason an approver reads is the
    reason the platform acted on (the same discipline as every other governance code).
    """
    return explain(GovernanceReason.APPROVAL_REQUIRED)
