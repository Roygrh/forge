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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.contract import Budget, CompletionResult
from app.models import AgentVersion, Event, Run, RunStep, ToolInvocation
from app.runtime.errors import EscalationReason
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
EVENT_MODEL_CALLED = "model.called"
EVENT_TOOL_CALLED = "tool.called"
EVENT_DECISION_MADE = "decision.made"
EVENT_RUN_COMPLETED = "run.completed"
EVENT_RUN_ESCALATED = "run.escalated"
EVENT_RUN_FAILED = "run.failed"

#: Terminal run status -> the event that records it. The mapping is total: there is no
#: way to end a run without appending exactly one of these.
_TERMINAL_EVENT_FOR_STATUS = {
    "completed": EVENT_RUN_COMPLETED,
    "escalated": EVENT_RUN_ESCALATED,
    "error": EVENT_RUN_FAILED,
}

#: Which event types project into ordered trace steps. Everything else is lifecycle:
#: real, appended, and visible in the trace's ``events``, but not a reasoning step.
_STEP_KIND_FOR_EVENT: dict[str, Literal["reason", "tool", "decision"]] = {
    EVENT_MODEL_CALLED: "reason",
    EVENT_TOOL_CALLED: "tool",
    EVENT_DECISION_MADE: "decision",
}


# --- Read model ---------------------------------------------------------------


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


class TraceStep(BaseModel):
    """One ordered step of a run: a model call, a tool call, or the decision."""

    model_config = ConfigDict(frozen=True)

    step_no: int
    kind: Literal["reason", "tool", "decision"]
    model_call: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    tool_invocation: TraceToolInvocation | None = None
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

        if kind == "tool":
            tool_invocation = TraceToolInvocation(
                id=uuid.UUID(payload["tool_invocation_id"]),
                tool_ref=payload["tool_ref"],
                autonomy=payload.get("autonomy"),
                args=payload.get("args"),
                result=payload.get("result"),
                status=payload["status"],
                error=payload.get("error"),
            )
        elif kind == "reason":
            model_call = payload
        else:
            decision = payload

        steps.append(
            TraceStep(
                step_no=step_no,
                kind=kind,
                model_call=model_call,
                decision=decision,
                tool_invocation=tool_invocation,
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
    """

    def __init__(self, session: AsyncSession, *, actor: str = "system") -> None:
        self._session = session
        self._actor = actor
        self._step_no = 0
        self.run: Run | None = None

    @property
    def steps_recorded(self) -> int:
        """How many steps this run has written."""
        return self._step_no

    def _require_run(self) -> Run:
        if self.run is None:  # pragma: no cover - programming error, not a run outcome
            raise RuntimeError("open_run() must be called before anything is recorded")
        return self.run

    def _event(self, type_: str, payload: dict[str, Any]) -> Event:
        run = self._require_run()
        return Event(
            tenant_id=run.tenant_id,
            type=type_,
            actor=self._actor,
            run_id=run.id,
            agent_version_id=run.agent_version_id,
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

    async def record_tool_call(self, outcome: ToolOutcome) -> None:
        """Record one trip through the tool gateway, executed or refused."""
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
                },
            )
        )
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
        budget: Budget,
        reason: EscalationReason | None = None,
        detail: str | None = None,
    ) -> Run:
        """Close the run: terminal status, totals, and the matching terminal event."""
        run = self._require_run()
        run.status = status
        run.total_tokens = budget.tokens_used
        # Quantized to the column's scale so the object in memory and the row on disk
        # are the same number: without this, the run returned by POST /runs and the one
        # returned by GET /runs/{id} serialise differently ("0.0010" vs "0.001000").
        run.total_cost_usd = Decimal(budget.cost_usd).quantize(_MONEY_SCALE)
        run.finished_at = datetime.now(UTC)

        payload: dict[str, Any] = {
            "status": status,
            "steps": self._step_no,
            "total_tokens": budget.tokens_used,
            "total_cost_usd": str(budget.cost_usd),
        }
        if reason is not None:
            payload["reason"] = str(reason)
        if detail is not None:
            payload["detail"] = detail

        self._session.add(self._event(_TERMINAL_EVENT_FOR_STATUS[status], payload))
        await self._session.commit()
        return run
