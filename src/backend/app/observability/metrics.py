"""Per-agent metrics, projected from the append-only event log (FR-G3).

Everything here is derived from ``events`` at read time — there is no counters table,
no rollup job, and no number on the dashboard that is not recomputable from the audit
trail (ADR-008). The relational tables are consulted only as *dimensions*: which agent
a version belongs to, and what an agent's current lifecycle state is. If a figure on
the screen and the event log ever disagreed, one of them would be lying; deriving the
figure from the log makes that structurally impossible.

The vocabulary is the trace's own: this module imports the event names from
:mod:`app.runtime.trace` rather than repeating the strings, so the writer and this
reader cannot drift into different ideas of what a run looked like.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.governance import DENIALS, GovernanceReason
from app.models import Agent, AgentVersion, Event
from app.runtime.trace import (
    EVENT_APPROVAL_PENDING,
    EVENT_GOVERNANCE_BLOCKED,
    EVENT_RUN_AWAITING_APPROVAL,
    EVENT_RUN_CANCELED,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_ESCALATED,
    EVENT_RUN_FAILED,
    EVENT_RUN_STARTED,
)

#: Scale every averaged or summed money figure is quantized to — the same scale as
#: ``runs.total_cost_usd``, so a dashboard number and a run row are the same kind of
#: number.
_MONEY_SCALE = Decimal("0.000001")

#: Lifecycle event -> the run status it records. The inverse of the trace's
#: status->event mapping, kept total the same way: every way a run stops is here.
_STATUS_FOR_LIFECYCLE: dict[str, str] = {
    EVENT_RUN_COMPLETED: "completed",
    EVENT_RUN_ESCALATED: "escalated",
    EVENT_RUN_AWAITING_APPROVAL: "awaiting_approval",
    EVENT_RUN_CANCELED: "canceled",
    EVENT_RUN_FAILED: "error",
}

#: The statuses a run does not come back from. ``awaiting_approval`` is deliberately
#: not one of them — a parked run is a pause, and rates are computed over runs whose
#: story has actually ended.
_FINISHED_STATUSES = frozenset({"completed", "escalated", "canceled", "error"})

#: Reason codes that are a *person* exercising the control the platform gave them —
#: parking an action, refusing it, or letting it lapse. They are refusals in the log,
#: but they are the human-in-the-loop working as designed, so neither the block rate
#: nor the circuit breaker counts them as the platform failing.
_HUMAN_LOOP_REASONS = frozenset(
    {
        str(GovernanceReason.APPROVAL_REQUIRED),
        str(GovernanceReason.APPROVAL_REJECTED),
        str(GovernanceReason.APPROVAL_EXPIRED),
    }
)

#: The reasons that count as the platform stopping something gone wrong: every denial
#: except the human-in-the-loop ones above. This is what the block rate measures and
#: what the circuit breaker trips on (FR-G4).
FAULT_REASONS = frozenset(str(reason) for reason in DENIALS) - _HUMAN_LOOP_REASONS

#: How many of an agent's most recent runs the dashboard links back to.
RECENT_RUNS_LIMIT = 10


# --- One run, as the log tells it ----------------------------------------------


@dataclass
class RunFacts:
    """What the event log says about one run — the unit every metric aggregates."""

    run_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_id: uuid.UUID | None
    agent: str  # slug@semver
    started_at: datetime
    status: str = "running"
    finished_at: datetime | None = None
    total_tokens: int | None = None
    total_cost_usd: Decimal | None = None
    #: The terminal event's reason code, when it carried one (a refusal, a human veto,
    #: or ``agent_decision`` for a decided escalation). None for a plain completion.
    reason: str | None = None
    #: Every ``governance.blocked`` reason this run recorded, in order.
    blocked_reasons: list[str] = field(default_factory=list)
    #: True when the run parked an action for a human at any point.
    parked: bool = False

    @property
    def finished(self) -> bool:
        """Whether this run has ended, as opposed to running or waiting on a person."""
        return self.status in _FINISHED_STATUSES

    @property
    def faulted(self) -> bool:
        """Whether the platform stopped this run for a fault (breaker fuel, FR-G4).

        An ``error`` run counts even without a reason code — a defect that escaped the
        fail-closed vocabulary is still a failure — and a human decision never counts.
        """
        return self.status == "error" or (self.reason is not None and self.reason in FAULT_REASONS)

    @property
    def auto(self) -> bool:
        """Completed entirely within the agent's own authority: no human touched it."""
        return self.status == "completed" and not self.parked

    def latency_seconds(self) -> float | None:
        """Wall-clock seconds from start to the last lifecycle event, once finished."""
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


async def run_facts(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> list[RunFacts]:
    """Project every run into :class:`RunFacts`, from events alone.

    ``since`` bounds the window by the *start* of the run: a run belongs to the window
    it began in, so the breaker's window cannot be gamed by a long-running failure
    finishing late. ``agent_id`` narrows to one agent's runs (all its versions).
    """
    dimension = {
        version_id: (owner_id, f"{slug}@{version}")
        for version_id, owner_id, version, slug in (
            await session.execute(
                select(
                    AgentVersion.id, AgentVersion.agent_id, AgentVersion.version, Agent.slug
                ).join(Agent, AgentVersion.agent_id == Agent.id)
            )
        ).all()
    }

    events = await session.scalars(
        select(Event)
        .where(
            Event.run_id.is_not(None),
            Event.type.in_(
                [
                    EVENT_RUN_STARTED,
                    EVENT_GOVERNANCE_BLOCKED,
                    EVENT_APPROVAL_PENDING,
                    *_STATUS_FOR_LIFECYCLE,
                ]
            ),
        )
        .order_by(Event.event_id)
    )

    facts: dict[uuid.UUID, RunFacts] = {}
    for event in events:
        assert event.run_id is not None  # guaranteed by the query's filter
        if event.type == EVENT_RUN_STARTED:
            if event.agent_version_id is None:  # pragma: no cover - writer always sets it
                continue
            owner_id, label = dimension.get(event.agent_version_id, (None, "unknown@?"))
            if agent_id is not None and owner_id != agent_id:
                continue
            if since is not None and event.occurred_at < since:
                continue
            facts[event.run_id] = RunFacts(
                run_id=event.run_id,
                agent_version_id=event.agent_version_id,
                agent_id=owner_id,
                agent=label,
                started_at=event.occurred_at,
            )
            continue

        run = facts.get(event.run_id)
        if run is None:  # outside the agent/window filter
            continue
        if event.type == EVENT_GOVERNANCE_BLOCKED:
            run.blocked_reasons.append(str(event.payload.get("reason_code")))
        elif event.type == EVENT_APPROVAL_PENDING:
            run.parked = True
        else:
            run.status = _STATUS_FOR_LIFECYCLE[event.type]
            run.finished_at = event.occurred_at
            tokens = event.payload.get("total_tokens")
            run.total_tokens = int(tokens) if tokens is not None else None
            cost = event.payload.get("total_cost_usd")
            run.total_cost_usd = Decimal(cost) if cost not in (None, "None") else None
            run.reason = event.payload.get("reason")

    return list(facts.values())


# --- Aggregation ---------------------------------------------------------------


@dataclass(frozen=True)
class RunRef:
    """One run on the dashboard, resolvable to its full trace (`#/runs/<id>`)."""

    run_id: uuid.UUID
    agent: str
    status: str
    reason: str | None
    total_cost_usd: str | None
    started_at: datetime

    def as_json(self) -> dict[str, Any]:
        """The API shape of this reference."""
        return {
            "run_id": str(self.run_id),
            "agent": self.agent,
            "status": self.status,
            "reason": self.reason,
            "total_cost_usd": self.total_cost_usd,
            "started_at": self.started_at.isoformat(),
        }


@dataclass(frozen=True)
class MetricsSummary:
    """The FR-G3 numbers over one population of runs (one agent's, or everyone's)."""

    runs: int
    runs_by_status: dict[str, int]
    finished_runs: int
    #: Starts the platform refused outright (suspended agent, denied permission) — they
    #: never became runs, so they are beside the run counts rather than inside them.
    runs_refused: int
    auto_approval_rate: float | None
    escalation_rate: float | None
    block_rate: float | None
    blocks_by_reason: dict[str, int]
    avg_tokens_per_run: float | None
    avg_cost_usd_per_run: str | None
    avg_latency_seconds: float | None
    total_cost_usd: str

    def as_json(self) -> dict[str, Any]:
        """The API shape of this summary."""
        return {
            "runs": self.runs,
            "runs_by_status": self.runs_by_status,
            "finished_runs": self.finished_runs,
            "runs_refused": self.runs_refused,
            "auto_approval_rate": self.auto_approval_rate,
            "escalation_rate": self.escalation_rate,
            "block_rate": self.block_rate,
            "blocks_by_reason": self.blocks_by_reason,
            "avg_tokens_per_run": self.avg_tokens_per_run,
            "avg_cost_usd_per_run": self.avg_cost_usd_per_run,
            "avg_latency_seconds": self.avg_latency_seconds,
            "total_cost_usd": self.total_cost_usd,
        }


@dataclass(frozen=True)
class AgentMetrics:
    """One agent's dashboard row: identity, lifecycle state, numbers, recent runs."""

    agent_id: uuid.UUID
    slug: str
    name: str
    #: The agent's operational state, summarised across its versions: ``suspended`` if
    #: any version is suspended, else ``published`` if any is live, else ``draft``.
    state: str
    #: The latest ``version.suspended`` event's payload when suspended — what tripped
    #: the breaker (or who suspended it by hand), verbatim from the log.
    suspension: dict[str, Any] | None
    metrics: MetricsSummary
    recent_runs: list[RunRef]

    def as_json(self) -> dict[str, Any]:
        """The API shape of this row."""
        return {
            "agent_id": str(self.agent_id),
            "slug": self.slug,
            "name": self.name,
            "state": self.state,
            "suspension": self.suspension,
            "metrics": self.metrics.as_json(),
            "recent_runs": [ref.as_json() for ref in self.recent_runs],
        }


@dataclass(frozen=True)
class MetricsReport:
    """The whole dashboard: every agent, and the same numbers overall."""

    overall: MetricsSummary
    agents: list[AgentMetrics]


def summarise(runs: list[RunFacts], *, runs_refused: int = 0) -> MetricsSummary:
    """Aggregate one population of runs into the FR-G3 numbers.

    Rates are over **finished** runs — a run still executing or waiting on a person has
    no outcome to count — and are ``None`` rather than zero when nothing has finished:
    "no data" and "never happens" must not read the same on a governance dashboard.
    """
    finished = [run for run in runs if run.finished]
    denominator = len(finished)

    by_status: dict[str, int] = {}
    blocks: dict[str, int] = {}
    for run in runs:
        by_status[run.status] = by_status.get(run.status, 0) + 1
        for reason in run.blocked_reasons:
            blocks[reason] = blocks.get(reason, 0) + 1

    def rate(count: int) -> float | None:
        return count / denominator if denominator else None

    costs = [run.total_cost_usd for run in finished if run.total_cost_usd is not None]
    tokens = [run.total_tokens for run in finished if run.total_tokens is not None]
    latencies = [latency for run in finished if (latency := run.latency_seconds()) is not None]
    total_cost = sum(costs, Decimal("0"))

    return MetricsSummary(
        runs=len(runs),
        runs_by_status=by_status,
        finished_runs=denominator,
        runs_refused=runs_refused,
        auto_approval_rate=rate(sum(1 for run in finished if run.auto)),
        escalation_rate=rate(sum(1 for run in finished if run.status == "escalated")),
        block_rate=rate(sum(1 for run in finished if run.faulted)),
        blocks_by_reason=blocks,
        avg_tokens_per_run=sum(tokens) / len(tokens) if tokens else None,
        avg_cost_usd_per_run=(
            str((total_cost / len(costs)).quantize(_MONEY_SCALE)) if costs else None
        ),
        avg_latency_seconds=sum(latencies) / len(latencies) if latencies else None,
        total_cost_usd=str(total_cost.quantize(_MONEY_SCALE)),
    )


async def collect_metrics(session: AsyncSession) -> MetricsReport:
    """Build the dashboard: per-agent metrics plus the same numbers overall.

    Every agent in the catalog appears, including ones that have never run — an agent
    with no runs and no state is exactly the kind of thing an operator wants to see.
    """
    from app.observability.containment import EVENT_RUN_REFUSED, latest_suspensions

    facts = await run_facts(session)
    agents = list(await session.scalars(select(Agent).order_by(Agent.created_at, Agent.slug)))
    versions = list(await session.scalars(select(AgentVersion)))

    refused_events = list(
        await session.scalars(select(Event).where(Event.type == EVENT_RUN_REFUSED))
    )
    version_owner = {version.id: version.agent_id for version in versions}
    refused_by_agent: dict[uuid.UUID, int] = {}
    for event in refused_events:
        owner = version_owner.get(event.agent_version_id) if event.agent_version_id else None
        if owner is not None:
            refused_by_agent[owner] = refused_by_agent.get(owner, 0) + 1

    suspended_ids = [version.id for version in versions if version.status == "suspended"]
    suspensions = await latest_suspensions(session, suspended_ids)

    rows: list[AgentMetrics] = []
    for agent in agents:
        own_versions = [version for version in versions if version.agent_id == agent.id]
        own_runs = [run for run in facts if run.agent_id == agent.id]
        statuses = {version.status for version in own_versions}
        state = (
            "suspended"
            if "suspended" in statuses
            else "published"
            if "published" in statuses
            else "draft"
        )
        suspension: dict[str, Any] | None = None
        if state == "suspended":
            suspended = [version for version in own_versions if version.status == "suspended"]
            events = [suspensions[version.id] for version in suspended if version.id in suspensions]
            if events:
                latest = max(events, key=lambda event: event.event_id)
                suspension = {
                    **latest.payload,
                    "actor": latest.actor,
                    "occurred_at": latest.occurred_at.isoformat(),
                }

        recent = sorted(own_runs, key=lambda run: run.started_at, reverse=True)
        rows.append(
            AgentMetrics(
                agent_id=agent.id,
                slug=agent.slug,
                name=agent.name,
                state=state,
                suspension=suspension,
                metrics=summarise(own_runs, runs_refused=refused_by_agent.get(agent.id, 0)),
                recent_runs=[
                    RunRef(
                        run_id=run.run_id,
                        agent=run.agent,
                        status=run.status,
                        reason=run.reason,
                        total_cost_usd=(
                            str(run.total_cost_usd) if run.total_cost_usd is not None else None
                        ),
                        started_at=run.started_at,
                    )
                    for run in recent[:RECENT_RUNS_LIMIT]
                ],
            )
        )

    overall = summarise(facts, runs_refused=sum(refused_by_agent.values()))
    return MetricsReport(overall=overall, agents=rows)
