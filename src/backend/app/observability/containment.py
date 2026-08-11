"""The circuit breaker, and the suspend/resume lifecycle transitions (FR-G4, FR-A4).

Containment doctrine, in one place:

* **Tripping is automatic and fail-safe.** After each of an agent's runs reaches a
  terminal state, the breaker re-reads the trailing window *from the event log* — the
  same projection the metrics endpoint serves, so the dashboard and the breaker can
  never disagree about what happened. Too many faulted runs, or too much money, and the
  published version is suspended right there, with the tripping numbers recorded in the
  ``version.suspended`` event.
* **Suspension is a recorded state transition, not a flag.** The status change on
  ``agent_versions`` and its event are written in the same transaction (ADR-008), and a
  suspended version's refusals are themselves events — a stopped agent is visible in
  the log, not just absent from it.
* **Nothing un-suspends itself.** There is no cool-down, no retry-after, no automatic
  half-open state. The only way back is a person holding ``agent.resume`` — a role that
  structurally cannot be the one who configured or published the agent (NFR-5 applied
  to containment) — saying so, on the record.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.governance import GovernanceReason, explain
from app.models import AgentVersion, Event
from app.observability.metrics import run_facts

#: Lifecycle transitions on an agent version, and the refusal a suspended one answers
#: runs with. Beside the trace's run events in spirit, but owned here: these are about
#: the *agent*, not about any one run.
EVENT_VERSION_SUSPENDED = "version.suspended"
EVENT_VERSION_RESUMED = "version.resumed"
#: A start the platform refused because the version is suspended. No run exists — the
#: event carries the agent version, the actor who asked, and the reason code, so "who
#: tried to run a contained agent" is answerable from the log.
EVENT_RUN_REFUSED = "governance.run_refused"


@dataclass(frozen=True)
class BreakerTrip:
    """Why the breaker tripped — the numbers, exactly as they were judged."""

    metric: Literal["failure_rate", "cost"]
    observed: str
    threshold: str
    window_seconds: int
    runs_in_window: int
    faulted_in_window: int

    def as_payload(self) -> dict[str, Any]:
        """The shape recorded in the ``version.suspended`` event."""
        return {
            "metric": self.metric,
            "observed": self.observed,
            "threshold": self.threshold,
            "window_seconds": self.window_seconds,
            "runs_in_window": self.runs_in_window,
            "faulted_in_window": self.faulted_in_window,
        }

    def describe(self) -> str:
        """One sentence for the event detail and the API error."""
        if self.metric == "cost":
            return (
                f"spent ${self.observed} across {self.runs_in_window} run(s) in the last "
                f"{self.window_seconds}s against a ceiling of ${self.threshold}"
            )
        return (
            f"{self.faulted_in_window} of {self.runs_in_window} finished run(s) in the last "
            f"{self.window_seconds}s faulted (rate {self.observed}, threshold {self.threshold})"
        )


async def evaluate_circuit_breaker(
    session: AsyncSession, agent_version: AgentVersion, *, now: datetime
) -> BreakerTrip | None:
    """Judge the trailing window for this agent; suspend the version if it trips.

    Called after a run reaches a terminal state. The window is computed over the whole
    **agent** — every version, like the daily budget ceiling — because a runaway agent
    must not reset its own breaker by being republished; what gets suspended is the
    version that is live, which is the one that just ran.

    The cost ceiling is judged on any evidence at all; the failure rate only once the
    window holds ``breaker_min_runs`` finished runs, so a single bad run out of one is
    not a pattern. Both thresholds are strict: *exceeds*, not meets.
    """
    if agent_version.status != "published":
        return None  # already contained (or never live); nothing to trip

    settings = get_settings()
    window = settings.breaker_window_seconds
    facts = await run_facts(
        session, agent_id=agent_version.agent_id, since=now - timedelta(seconds=window)
    )
    finished = [run for run in facts if run.finished]
    faulted = sum(1 for run in finished if run.faulted)
    cost = sum(
        (run.total_cost_usd for run in facts if run.total_cost_usd is not None), Decimal("0")
    )

    trip: BreakerTrip | None = None
    if cost > settings.breaker_max_cost_usd:
        trip = BreakerTrip(
            metric="cost",
            observed=str(cost),
            threshold=str(settings.breaker_max_cost_usd),
            window_seconds=window,
            runs_in_window=len(facts),
            faulted_in_window=faulted,
        )
    elif len(finished) >= settings.breaker_min_runs:
        rate = faulted / len(finished)
        if rate > settings.breaker_max_failure_rate:
            trip = BreakerTrip(
                metric="failure_rate",
                observed=f"{rate:.3f}",
                threshold=f"{settings.breaker_max_failure_rate:.3f}",
                window_seconds=window,
                runs_in_window=len(finished),
                faulted_in_window=faulted,
            )

    if trip is None:
        return None

    await suspend_version(
        session,
        agent_version,
        actor="system:circuit-breaker",
        trigger="circuit_breaker",
        detail=f"circuit breaker tripped: {trip.describe()}",
        trip=trip,
    )
    return trip


async def suspend_version(
    session: AsyncSession,
    version: AgentVersion,
    *,
    actor: str,
    trigger: Literal["circuit_breaker", "manual"],
    detail: str,
    trip: BreakerTrip | None = None,
) -> None:
    """Transition published → suspended, and record it — one transaction, both writes.

    The event payload carries everything the dashboard later shows about *why* — the
    trigger, the sentence, and the breaker's numbers when it was the breaker — so the
    explanation of a suspension is the recorded fact of it, not a reconstruction.
    """
    version.status = "suspended"
    session.add(
        Event(
            tenant_id=version.tenant_id,
            type=EVENT_VERSION_SUSPENDED,
            actor=actor,
            agent_version_id=version.id,
            payload={
                "agent_version_id": str(version.id),
                "agent": _label(version),
                "trigger": trigger,
                "reason_code": str(GovernanceReason.AGENT_SUSPENDED),
                "explanation": explain(GovernanceReason.AGENT_SUSPENDED),
                "detail": detail,
                "breaker": trip.as_payload() if trip is not None else None,
            },
        )
    )
    await session.commit()


async def resume_version(
    session: AsyncSession, version: AgentVersion, *, actor: str, note: str | None
) -> None:
    """Transition suspended → published, on a person's recorded say-so (FR-G4).

    The one operation that reverses a containment, and it is deliberately manual: the
    caller has already verified ``agent.resume``, which no configuring or publishing
    role may hold. The event names who resumed it and what suspension they overrode.
    """
    suspensions = await latest_suspensions(session, [version.id])
    overridden = suspensions.get(version.id)

    version.status = "published"
    session.add(
        Event(
            tenant_id=version.tenant_id,
            type=EVENT_VERSION_RESUMED,
            actor=actor,
            agent_version_id=version.id,
            payload={
                "agent_version_id": str(version.id),
                "agent": _label(version),
                "note": note,
                "cleared_suspension_event_id": (
                    overridden.event_id if overridden is not None else None
                ),
                "cleared_trigger": (
                    overridden.payload.get("trigger") if overridden is not None else None
                ),
            },
        )
    )
    await session.commit()


async def record_run_refusal(
    session: AsyncSession, version: AgentVersion, *, actor: str, detail: str
) -> None:
    """Record that a start was refused because the version is suspended.

    A refusal with no run is still an audit fact — the same discipline as a denied
    permission — and it is what the dashboard's ``runs_refused`` counts.
    """
    session.add(
        Event(
            tenant_id=version.tenant_id,
            type=EVENT_RUN_REFUSED,
            actor=actor,
            agent_version_id=version.id,
            payload={
                "agent_version_id": str(version.id),
                "agent": _label(version),
                "reason_code": str(GovernanceReason.AGENT_SUSPENDED),
                "explanation": explain(GovernanceReason.AGENT_SUSPENDED),
                "detail": detail,
            },
        )
    )
    await session.commit()


async def latest_suspensions(
    session: AsyncSession, agent_version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Event]:
    """The most recent ``version.suspended`` event per version, from the log.

    Why a version is suspended is not a column anywhere — it is the recorded event,
    which is exactly what ADR-008 wants: the explanation cannot be edited after the
    fact, because nothing in the events table can.
    """
    if not agent_version_ids:
        return {}
    events = await session.scalars(
        select(Event)
        .where(
            Event.type == EVENT_VERSION_SUSPENDED,
            Event.agent_version_id.in_(agent_version_ids),
        )
        .order_by(Event.event_id)
    )
    latest: dict[uuid.UUID, Event] = {}
    for event in events:
        assert event.agent_version_id is not None  # guaranteed by the query's filter
        latest[event.agent_version_id] = event
    return latest


def _label(version: AgentVersion) -> str:
    """``slug@semver`` from the version's own DNA — the name every event uses."""
    return f"{version.dna.get('identity', {}).get('slug')}@{version.version}"
