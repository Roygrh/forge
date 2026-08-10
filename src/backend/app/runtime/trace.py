"""Writing the trace, and reading it back.

One module owns the event vocabulary in both directions: :class:`TraceRecorder` appends
it, :func:`project_trace` projects it. Keeping the writer and the reader together is
what stops the two from drifting into different ideas of what a run looked like.

Two invariants come from ADR-008 and are load-bearing here:

* **State row and its event are written in the same transaction.** Every method below
  adds both, then commits once. A run row without its event, or an event without its
  row, is a bug the tests are there to catch.
* **The trace the API serves is a projection of events, not of the state tables.**
  ``GET /runs/{id}/trace`` reads ``events`` alone. That is what makes "the screen shows
  exactly what happened" true by construction rather than by convention.

Commits happen per step rather than once at the end, deliberately: a run that dies
mid-flight leaves a partial but truthful trace instead of nothing at all.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.governance import GovernanceReason, explain
from app.llm.contract import Budget, CompletionResult
from app.models import AgentVersion, Approval, Event, Run, RunStep, ToolInvocation
from app.runtime.output import Decision
from app.tools.contract import ToolOutcome

# --- Event vocabulary ---------------------------------------------------------
#
# Terminal events always match the run's terminal status: a run that ends `completed`
# emits run.completed, one that ends `escalated` emits run.escalated. There is no
# reading of the log in which the status and the last event disagree.

#: Scale of ``runs.total_cost_usd`` (Numeric(14, 6)) — see app/models/base.py.
_MONEY_SCALE = Decimal("0.000001")

EVENT_RUN_STARTED = "run.started"
#: Every platform refusal, with its machine-readable reason code. Emitted from one
#: place in the runtime, so "no silent blocks" is structural rather than a habit.
EVENT_GOVERNANCE_BLOCKED = "governance.blocked"
EVENT_MODEL_CALLED = "model.called"
EVENT_TOOL_CALLED = "tool.called"
EVENT_DECISION_MADE = "decision.made"

#: The human in the loop (FR-E4). Four events, one per state an approval can be in, each
#: carrying the actor and the timestamp. ``pending`` is the platform parking an action;
#: the other three are how it ended — and only ``granted`` ever leads to an execution.
EVENT_APPROVAL_PENDING = "approval.pending"
EVENT_APPROVAL_GRANTED = "approval.granted"
EVENT_APPROVAL_REJECTED = "approval.rejected"
EVENT_APPROVAL_EXPIRED = "approval.expired"

EVENT_RUN_COMPLETED = "run.completed"
EVENT_RUN_ESCALATED = "run.escalated"
EVENT_RUN_AWAITING_APPROVAL = "run.awaiting_approval"
EVENT_RUN_CANCELED = "run.canceled"
EVENT_RUN_FAILED = "run.failed"

#: Terminal run status -> the event that records it. The mapping is total: there is no
#: way to end a run without appending exactly one of these.
_TERMINAL_EVENT_FOR_STATUS = {
    "completed": EVENT_RUN_COMPLETED,
    "escalated": EVENT_RUN_ESCALATED,
    # A pause, not an ending: the run stops with nothing executed and waits for the
    # approval queue. It resumes on a grant, and is canceled on a rejection or on the
    # deadline passing — a run cannot leave this state by itself.
    "awaiting_approval": EVENT_RUN_AWAITING_APPROVAL,
    # A parked action a human refused, or one whose deadline passed. Nothing ran.
    "canceled": EVENT_RUN_CANCELED,
    "error": EVENT_RUN_FAILED,
}

#: Approval status -> the event that records it. Total, like the terminal mapping above:
#: an approval cannot change state without appending exactly one of these.
_APPROVAL_EVENT_FOR_STATUS = {
    "pending": EVENT_APPROVAL_PENDING,
    "granted": EVENT_APPROVAL_GRANTED,
    "rejected": EVENT_APPROVAL_REJECTED,
    "expired": EVENT_APPROVAL_EXPIRED,
}

#: The five kinds of ordered step a trace can contain. ``governance`` is the platform
#: speaking rather than the agent — a refusal, with the reason code that caused it — and
#: ``approval`` is a person speaking: the action they were shown, and what they did
#: about it.
StepKind = Literal["reason", "tool", "decision", "governance", "approval"]


#: Which event types project into ordered trace steps. Everything else is lifecycle:
#: real, appended, and visible in the trace's ``events``, but not a reasoning step.
_STEP_KIND_FOR_EVENT: dict[str, StepKind] = {
    EVENT_MODEL_CALLED: "reason",
    EVENT_TOOL_CALLED: "tool",
    EVENT_DECISION_MADE: "decision",
    EVENT_GOVERNANCE_BLOCKED: "governance",
    EVENT_APPROVAL_PENDING: "approval",
    EVENT_APPROVAL_GRANTED: "approval",
    EVENT_APPROVAL_REJECTED: "approval",
    EVENT_APPROVAL_EXPIRED: "approval",
}


# --- Read model ---------------------------------------------------------------


class TraceGovernance(BaseModel):
    """One platform refusal, as the trace viewer shows it.

    ``reason_code`` is the machine-readable code from
    :class:`~app.governance.GovernanceReason`; ``explanation`` is the sentence that goes
    with it, written for a reader who has never seen the code. ``detail`` is the specific
    circumstance — which tool, which ceiling, which number.
    """

    model_config = ConfigDict(frozen=True)

    reason_code: str
    explanation: str
    detail: str | None = None
    terminal_status: str


class TraceToolInvocation(BaseModel):
    """One tool call as the trace viewer shows it — including one that never ran."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    tool_ref: str
    autonomy: str | None
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    status: str
    error: str | None = None
    #: The governance code the gateway assigned, when this call was refused or parked.
    #: Null for one that executed. The same code appears on the governance step that
    #: follows, so a reader can tie the refusal to the stop it caused.
    reason_code: str | None = None
    #: Set when this call ran only because a person released it: the approval that
    #: authorised it and who granted it. Null for an autonomous execution — an action a
    #: human signed for must never read the same as one the agent took on its own.
    approval_id: uuid.UUID | None = None
    released_by: str | None = None


class TraceApproval(BaseModel):
    """One state of one approval, as the trace shows it (FR-E4).

    Carries the action being decided — tool ref and the exact arguments — because that
    *is* the scope of the approval: one action instance, its parameters, and nothing
    else. A reader can see what was authorised without joining anything.
    """

    model_config = ConfigDict(frozen=True)

    approval_id: uuid.UUID
    status: str
    tool_ref: str
    args: dict[str, Any] | None = None
    expires_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    #: ``approval_rejected`` or ``approval_expired`` when the approval ended the run.
    #: Null while pending and on a grant, which ends nothing.
    reason_code: str | None = None


class TraceStep(BaseModel):
    """One ordered step of a run: a model call, a tool call, a decision, a refusal, or
    a human's decision on an action the run parked."""

    model_config = ConfigDict(frozen=True)

    step_no: int
    kind: StepKind
    model_call: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    tool_invocation: TraceToolInvocation | None = None
    governance: TraceGovernance | None = None
    approval: TraceApproval | None = None
    created_at: datetime


class TraceEvent(BaseModel):
    """One raw append-only event, exposed so the trace can be audited, not just read."""

    model_config = ConfigDict(frozen=True)

    event_id: int
    type: str
    actor: str
    occurred_at: datetime
    payload: dict[str, Any]


def project_trace(events: list[Event]) -> tuple[list[TraceStep], list[TraceEvent]]:
    """Project a run's events into ordered steps plus the raw event log.

    The caller supplies events already ordered by ``event_id`` — the monotonic identity
    the events table exists to provide. This function adds no ordering of its own, so
    the trace's order *is* the log's order.
    """
    steps: list[TraceStep] = []
    raw: list[TraceEvent] = []

    for event in events:
        raw.append(
            TraceEvent(
                event_id=event.event_id,
                type=event.type,
                actor=event.actor,
                occurred_at=event.occurred_at,
                payload=event.payload,
            )
        )

        kind = _STEP_KIND_FOR_EVENT.get(event.type)
        if kind is None:
            continue

        payload = dict(event.payload)
        step_no = int(payload.pop("step_no"))
        tool_invocation = None
        model_call = None
        decision = None
        governance = None
        approval = None

        if kind == "tool":
            approval_id = payload.get("approval_id")
            tool_invocation = TraceToolInvocation(
                id=uuid.UUID(payload["tool_invocation_id"]),
                tool_ref=payload["tool_ref"],
                autonomy=payload.get("autonomy"),
                args=payload.get("args"),
                result=payload.get("result"),
                status=payload["status"],
                error=payload.get("error"),
                reason_code=payload.get("reason_code"),
                approval_id=uuid.UUID(approval_id) if approval_id else None,
                released_by=payload.get("released_by"),
            )
        elif kind == "reason":
            model_call = payload
        elif kind == "governance":
            governance = TraceGovernance(
                reason_code=payload["reason_code"],
                explanation=payload["explanation"],
                detail=payload.get("detail"),
                terminal_status=payload["terminal_status"],
            )
        elif kind == "approval":
            approval = TraceApproval(
                approval_id=uuid.UUID(payload["approval_id"]),
                status=payload["status"],
                tool_ref=payload["tool_ref"],
                args=payload.get("args"),
                expires_at=payload["expires_at"],
                decided_by=payload.get("decided_by"),
                decided_at=payload.get("decided_at"),
                note=payload.get("note"),
                reason_code=payload.get("reason_code"),
            )
        else:
            decision = payload

        steps.append(
            TraceStep(
                step_no=step_no,
                kind=kind,
                model_call=model_call,
                decision=decision,
                tool_invocation=tool_invocation,
                governance=governance,
                approval=approval,
                created_at=event.occurred_at,
            )
        )

    return steps, raw


async def load_events(session: AsyncSession, run_id: uuid.UUID) -> list[Event]:
    """Read every event for a run, in append order."""
    result = await session.scalars(
        select(Event).where(Event.run_id == run_id).order_by(Event.event_id)
    )
    return list(result)


# --- Write model --------------------------------------------------------------


class TraceRecorder:
    """Appends one run's history: state rows and their events, in step order.

    One recorder per run. It owns the step counter, so ``run_steps.step_no`` is dense
    and monotonic without the loop having to track it.

    A run that parked for an approval is written by *two* recorders in sequence — the one
    that started it, and the one :meth:`resume` builds when a person releases it. The
    second picks the counter up from the log rather than from memory, which is the only
    way it could work: nothing about the first recorder survives the request that made it.
    """

    def __init__(self, session: AsyncSession, *, actor: str = "system") -> None:
        self._session = session
        self._actor = actor
        self._step_no = 0
        self.run: Run | None = None

    @classmethod
    async def resume(cls, session: AsyncSession, run: Run, *, actor: str = "system") -> Self:
        """Continue recording an existing run, after its last recorded step.

        ``step_no`` is read back from ``run_steps`` because it is a property of the run,
        not of this process: the run was paused across a request boundary — possibly
        across a restart — and its order has to continue rather than start again.
        """
        recorder = cls(session, actor=actor)
        recorder.run = run
        last = await session.scalar(
            select(func.coalesce(func.max(RunStep.step_no), 0)).where(RunStep.run_id == run.id)
        )
        recorder._step_no = int(last or 0)
        return recorder

    @property
    def steps_recorded(self) -> int:
        """How many steps this run has written."""
        return self._step_no

    def _require_run(self) -> Run:
        if self.run is None:  # pragma: no cover - programming error, not a run outcome
            raise RuntimeError("open_run() must be called before anything is recorded")
        return self.run

    def _event(
        self,
        type_: str,
        payload: dict[str, Any],
        *,
        actor: str | None = None,
        approval_id: uuid.UUID | None = None,
    ) -> Event:
        run = self._require_run()
        return Event(
            tenant_id=run.tenant_id,
            type=type_,
            # Overridden for the events a *person* caused: an approval carries the
            # approver's identity, not the identity the run happens to be executing as.
            actor=actor if actor is not None else self._actor,
            run_id=run.id,
            agent_version_id=run.agent_version_id,
            approval_id=approval_id,
            payload=payload,
        )

    async def open_run(
        self,
        *,
        agent_version: AgentVersion,
        trigger: str | None,
        run_input: dict[str, Any],
    ) -> Run:
        """Create the run and append ``run.started``.

        The run binds to ``agent_version_id``, never to the agent: the exact DNA that
        produced a decision stays recoverable forever (FR-A3).
        """
        run = Run(
            tenant_id=agent_version.tenant_id,
            agent_version_id=agent_version.id,
            status="running",
            trigger=trigger,
        )
        self._session.add(run)
        await self._session.flush()  # assigns run.id, needed by the event's soft ref
        self.run = run

        identity = agent_version.dna.get("identity", {})
        self._session.add(
            self._event(
                EVENT_RUN_STARTED,
                {
                    "agent": f"{identity.get('slug')}@{agent_version.version}",
                    "agent_version_id": str(agent_version.id),
                    "trigger": trigger,
                    "input": run_input,
                },
            )
        )
        await self._session.commit()
        return run

    async def record_model_call(
        self,
        *,
        result: CompletionResult,
        attempt: int,
        outcome: str,
        budget: Budget,
    ) -> None:
        """Record one call through the LLM gateway.

        ``attempt`` is 0 for the first try and 1 for the single ADR-006 correction, so
        a retry is visible in the trace as a retry rather than as two unrelated calls.
        """
        run = self._require_run()
        self._step_no += 1
        payload = {
            "step_no": self._step_no,
            "provider": result.provider,
            "model_id": result.model_id,
            "attempt": attempt,
            "outcome": outcome,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            # Money is carried as a string in JSON: JSONB has no exact decimal, and
            # rounding an audit record through a float is not acceptable.
            "cost_usd": str(result.usage.cost_usd),
            "budget": budget.snapshot(),
        }
        self._session.add(
            RunStep(
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_no=self._step_no,
                kind="reason",
                model_call=payload,
            )
        )
        self._session.add(self._event(EVENT_MODEL_CALLED, payload))
        await self._session.commit()

    async def record_tool_call(self, outcome: ToolOutcome) -> ToolInvocation:
        """Record one trip through the tool gateway, executed or refused.

        Returns the persisted invocation because a parked call needs it: the approval
        that follows hangs off this exact row, which is what makes an approval cover one
        action instance with its arguments and nothing else (FR-E2).
        """
        run = self._require_run()
        self._step_no += 1
        step = RunStep(
            tenant_id=run.tenant_id,
            run_id=run.id,
            step_no=self._step_no,
            kind="tool",
        )
        self._session.add(step)
        await self._session.flush()  # tool_invocations.run_step_id is a real FK

        invocation = ToolInvocation(
            tenant_id=run.tenant_id,
            run_id=run.id,
            run_step_id=step.id,
            tool_ref=outcome.tool_ref,
            # A refused call may have no autonomy at all (unknown or ungranted tool);
            # the column is NOT NULL, so record the absence explicitly.
            autonomy=outcome.autonomy or "none",
            args=outcome.arguments,
            result=outcome.result,
            status=outcome.status,
        )
        self._session.add(invocation)
        await self._session.flush()

        self._session.add(
            self._event(
                EVENT_TOOL_CALLED,
                {
                    "step_no": self._step_no,
                    "tool_invocation_id": str(invocation.id),
                    "tool_ref": outcome.tool_ref,
                    "tool_name": outcome.tool_name,
                    "autonomy": outcome.autonomy,
                    "args": outcome.arguments,
                    "status": outcome.status,
                    "result": outcome.result,
                    "error": outcome.error,
                    # Assigned by the gateway, carried verbatim: the audit log names the
                    # refusal with the same code the enforcement point used.
                    "reason_code": str(outcome.reason) if outcome.reason else None,
                    # Present only when a human released this call. An execution somebody
                    # signed for is not the same fact as one the agent took alone.
                    "approval_id": (
                        str(outcome.release.approval_id) if outcome.release is not None else None
                    ),
                    "released_by": (
                        outcome.release.decided_by if outcome.release is not None else None
                    ),
                },
            )
        )
        await self._session.commit()
        return invocation

    async def park_approval(self, invocation: ToolInvocation, *, expires_at: datetime) -> Approval:
        """Open the pending approval a parked call is waiting on (FR-E2, FR-E3).

        One approval, one invocation — a database unique constraint, not a convention —
        so what a person is asked to release is exactly one action instance with the
        arguments the gateway already validated. ``expires_at`` is written once, here,
        and no operation in the platform moves it.
        """
        run = self._require_run()
        approval = Approval(
            tenant_id=run.tenant_id,
            run_id=run.id,
            tool_invocation_id=invocation.id,
            status="pending",
            expires_at=expires_at,
        )
        self._session.add(approval)
        await self._session.flush()  # assigns approval.id, needed by the event's soft ref
        await self.record_approval(approval, invocation, actor=self._actor)
        return approval

    async def record_approval(
        self,
        approval: Approval,
        invocation: ToolInvocation,
        *,
        actor: str,
        reason: GovernanceReason | None = None,
    ) -> None:
        """Record one state of one approval — parked, granted, rejected, or expired.

        The caller has already put the ``approvals`` row into this session in whatever
        state it is reporting; this writes the step and the event that go with it and
        commits all three together, which is the dual-write discipline ADR-008 asks for
        applied to the human in the loop.

        The action being decided travels in the payload — the tool ref and the exact
        arguments — so the audit log answers "what was authorised" without a join, and so
        a later change to the invocation row could not rewrite what somebody approved.
        """
        run = self._require_run()
        self._step_no += 1
        payload: dict[str, Any] = {
            "step_no": self._step_no,
            "approval_id": str(approval.id),
            "status": approval.status,
            "tool_ref": invocation.tool_ref,
            "args": invocation.args,
            "expires_at": approval.expires_at.isoformat(),
            "decided_by": approval.decided_by,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            "note": approval.note,
            "reason_code": str(reason) if reason is not None else None,
        }
        self._session.add(
            RunStep(
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_no=self._step_no,
                kind="approval",
                approval=payload,
            )
        )
        self._session.add(
            self._event(
                _APPROVAL_EVENT_FOR_STATUS[approval.status],
                payload,
                actor=actor,
                approval_id=approval.id,
            )
        )
        await self._session.commit()

    async def record_governance(
        self,
        *,
        reason: GovernanceReason,
        detail: str | None,
        terminal_status: str,
    ) -> None:
        """Record that the platform refused to continue, and why.

        Called from exactly one place — the runtime's fail-closed handler — so every
        stop produces exactly one of these, and none can be produced without a stop.
        That is what makes "every denial is recorded" true by construction rather than
        by review (ADR-008, FR-C5).
        """
        run = self._require_run()
        self._step_no += 1
        payload = {
            "step_no": self._step_no,
            "reason_code": str(reason),
            # The sentence travels with the code so the API, the SPA, and an export all
            # say the same thing; a code with no explanation is an incident report with
            # the incident removed.
            "explanation": explain(reason),
            "detail": detail,
            "terminal_status": terminal_status,
        }
        self._session.add(
            RunStep(
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_no=self._step_no,
                kind="governance",
                governance=payload,
            )
        )
        self._session.add(self._event(EVENT_GOVERNANCE_BLOCKED, payload))
        await self._session.commit()

    async def record_decision(self, decision: Decision) -> None:
        """Record the agent's final decision, citations and all."""
        run = self._require_run()
        self._step_no += 1
        payload = {"step_no": self._step_no, **decision.as_payload()}
        self._session.add(
            RunStep(
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_no=self._step_no,
                kind="decision",
                decision=decision.as_payload(),
            )
        )
        self._session.add(self._event(EVENT_DECISION_MADE, payload))
        await self._session.commit()

    async def finish(
        self,
        *,
        status: str,
        budget: Budget | None = None,
        reason: GovernanceReason | None = None,
        detail: str | None = None,
    ) -> Run:
        """Close the run: terminal status, totals, and the matching terminal event.

        ``budget`` is ``None`` when the run is being closed without the loop having run —
        a rejected or expired approval cancels a run that spent nothing further, and
        rewriting its totals from an empty ledger would erase what it did spend.
        """
        run = self._require_run()
        run.status = status
        if budget is not None:
            run.total_tokens = budget.tokens_used
            # Quantized to the column's scale so the object in memory and the row on disk
            # are the same number: without this, the run returned by POST /runs and the
            # one returned by GET /runs/{id} serialise differently ("0.0010" vs
            # "0.001000").
            run.total_cost_usd = Decimal(budget.cost_usd).quantize(_MONEY_SCALE)
        run.finished_at = datetime.now(UTC)

        payload: dict[str, Any] = {
            "status": status,
            "steps": self._step_no,
            "total_tokens": budget.tokens_used if budget is not None else run.total_tokens,
            "total_cost_usd": str(budget.cost_usd if budget is not None else run.total_cost_usd),
        }
        if reason is not None:
            payload["reason"] = str(reason)
        if detail is not None:
            payload["detail"] = detail

        self._session.add(self._event(_TERMINAL_EVENT_FOR_STATUS[status], payload))
        await self._session.commit()
        return run
