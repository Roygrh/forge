"""Request and response bodies for the agent, run, and knowledge endpoints.

Shapes follow ``docs/02-architecture/api/openapi.yaml`` — that contract is the source of
truth, and these models are its executable form (golden rule 5).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.approvals import ApprovalRecord, CategoryStats, why_approval_is_required
from app.models import (
    Agent,
    AgentVersion,
    EvalRun,
    EvalSuite,
    KnowledgeChunk,
    KnowledgeCollection,
    RemediationItem,
    Run,
)
from app.observability import AgentMetrics
from app.runtime.trace import TraceEvent, TraceStep

RunStatus = Literal["running", "awaiting_approval", "completed", "escalated", "canceled", "error"]
AgentType = Literal["chatbot", "workflow", "autonomous"]
VersionStatus = Literal["draft", "published", "suspended"]


class AgentResponse(BaseModel):
    """One agent identity in the catalog. Behaviour lives in its versions, never here."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    slug: str
    name: str
    type: AgentType
    description: str | None = None
    created_at: datetime

    @classmethod
    def of(cls, agent: Agent) -> "AgentResponse":
        """Project an agent row onto the API contract."""
        return cls(
            id=agent.id,
            tenant_id=agent.tenant_id,
            slug=agent.slug,
            name=agent.name,
            type=agent.type,  # type: ignore[arg-type]  # DB text; the enum is the contract
            description=agent.description,
            created_at=agent.created_at,
        )


class AgentVersionResponse(BaseModel):
    """One immutable agent version, DNA included.

    The whole DNA document ships: it is the contract the runtime executed, so a viewer
    that wants to know what a version was *allowed* to do reads it here rather than
    inferring it from a run (golden rule 1).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    version: str = Field(description="Semver, e.g. 1.0.0")
    status: VersionStatus
    dna: dict[str, Any]
    published_eval_run_id: uuid.UUID | None = Field(
        default=None, description="The passing eval run that satisfied the publish gate, if any"
    )
    published_at: datetime | None = None
    created_at: datetime

    @classmethod
    def of(cls, version: AgentVersion) -> "AgentVersionResponse":
        """Project an agent-version row onto the API contract."""
        return cls(
            id=version.id,
            tenant_id=version.tenant_id,
            agent_id=version.agent_id,
            version=version.version,
            status=version.status,  # type: ignore[arg-type]  # DB text; the enum is the contract
            dna=version.dna,
            published_eval_run_id=version.published_eval_run_id,
            published_at=version.published_at,
            created_at=version.created_at,
        )


class CreateAgentVersion(BaseModel):
    """Body of ``POST /agents/{agentId}/versions``: one complete DNA document.

    The version number lives *inside* the document (``identity.version``), not beside
    it: the DNA is the contract, and a version number that could disagree with its own
    definition would be two sources of truth (golden rule 1).
    """

    model_config = ConfigDict(extra="forbid")

    dna: dict[str, Any] = Field(description="Validated against dna-schema.json before acceptance")


class StartRun(BaseModel):
    """Body of ``POST /runs``."""

    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    version: str = Field(description="Semver of a published version, e.g. 1.0.0")
    input: dict[str, Any] = Field(description="Trigger payload for this run")


class RunResponse(BaseModel):
    """A run's status and summary."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_version_id: uuid.UUID
    status: RunStatus
    trigger: str | None = None
    total_tokens: int | None = None
    total_cost_usd: Decimal | None = None
    started_at: datetime
    finished_at: datetime | None = None

    @classmethod
    def of(cls, run: Run) -> "RunResponse":
        """Project a run row onto the API contract."""
        return cls(
            id=run.id,
            tenant_id=run.tenant_id,
            agent_version_id=run.agent_version_id,
            status=run.status,  # type: ignore[arg-type]  # DB text; the enum is the contract
            trigger=run.trigger,
            total_tokens=run.total_tokens,
            total_cost_usd=run.total_cost_usd,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


class RunTraceResponse(BaseModel):
    """The ordered trace of a run — a projection of its append-only events (ADR-008).

    ``steps`` is the reasoning view (model calls, tool calls, the decision); ``events``
    is the raw log those steps were derived from, including the lifecycle events that
    are not steps. Serving both is what lets a reviewer check the projection against
    its source instead of trusting it.
    """

    run_id: uuid.UUID
    steps: list[TraceStep]
    events: list[TraceEvent]


# --- Approvals (FR-E1..E5) ----------------------------------------------------


class ProposedAction(BaseModel):
    """The action a run parked, exactly as the gateway validated it.

    This *is* the scope of the approval: one tool, one set of arguments. Approving it
    authorises this and nothing else — not the same tool again, not the same tool with a
    different amount (FR-E2).
    """

    tool_invocation_id: uuid.UUID
    tool_ref: str = Field(description="slug@semver, as granted in the version's DNA")
    autonomy: str
    args: dict[str, Any] | None = None
    status: str = Field(description="Always `validated` while pending: checked, and not run")


class ApprovalObservation(BaseModel):
    """One tool call the agent executed before it asked for a human."""

    tool_invocation_id: uuid.UUID
    tool_ref: str
    tool_name: str
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class ApprovalEvidence(BaseModel):
    """Everything the agent gathered before it asked (FR-E1).

    Served with the queue rather than behind a second request, because the requirement
    is a decision in under a minute and a round trip per invoice is not that.
    """

    agent: str = Field(description="slug@semver of the version that proposed the action")
    agent_description: str | None = None
    run_input: dict[str, Any]
    observations: list[ApprovalObservation]
    rule_ids: list[str] = Field(
        description="Governed rule ids present in what the agent gathered — the rules in play"
    )


class ApprovalResponse(BaseModel):
    """One approval: the proposed action, its evidence, its deadline, and its outcome."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    run_status: RunStatus
    status: Literal["pending", "granted", "rejected", "expired"]
    proposed_action: ProposedAction
    evidence: ApprovalEvidence
    why_approval_required: str = Field(
        description="The sentence the platform recorded when it parked the action"
    )
    expires_at: datetime = Field(
        description="Server-side deadline. On expiry the run is canceled, never approved"
    )
    seconds_remaining: int = Field(description="0 once the deadline has passed")
    decision: Literal["approve", "reject"] | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    created_at: datetime

    @classmethod
    def of(cls, record: "ApprovalRecord", *, now: datetime) -> "ApprovalResponse":
        """Project an approval and its evidence onto the API contract."""
        approval = record.approval
        return cls(
            id=approval.id,
            tenant_id=approval.tenant_id,
            run_id=approval.run_id,
            run_status=record.run.status,  # type: ignore[arg-type]  # DB text; enum is contract
            status=approval.status,  # type: ignore[arg-type]  # DB text; enum is the contract
            proposed_action=ProposedAction(
                tool_invocation_id=record.invocation.id,
                tool_ref=record.invocation.tool_ref,
                autonomy=record.invocation.autonomy,
                args=record.invocation.args,
                status=record.invocation.status,
            ),
            evidence=ApprovalEvidence.model_validate(record.evidence.as_json()),
            why_approval_required=why_approval_is_required(),
            expires_at=approval.expires_at,
            seconds_remaining=record.seconds_remaining(now),
            decision=approval.decision,  # type: ignore[arg-type]  # DB text; enum is contract
            decided_by=approval.decided_by,
            decided_at=approval.decided_at,
            note=approval.note,
            created_at=approval.created_at,
        )


class ApprovalDecisionRequest(BaseModel):
    """Body of approve and reject.

    A note and nothing else. **There are deliberately no arguments here**: what is being
    released is the action the run already parked, with the parameters the gateway
    already validated, so there is no shape of request that approves one action and runs
    another (FR-E2). There is likewise no ``extend`` field, and no endpoint that would
    accept one (FR-E3).
    """

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, description="Optional reviewer note, recorded verbatim")


class AutonomyCandidateResponse(BaseModel):
    """One action category in the autonomy-promotion report (FR-E5).

    Read-only by construction: no endpoint applies any of this. Raising an autonomy level
    means publishing a new DNA version through its eval gate.
    """

    agent: str
    agent_version_id: uuid.UUID
    tool_ref: str
    pending: int
    granted: int
    rejected: int
    expired: int
    decided: int
    approval_rate: float | None = Field(
        default=None, description="granted / decided; null when nothing has been decided"
    )
    candidate: bool
    recommendation: str
    fatigue_note: str | None = Field(
        default=None, description="Set when approvals in this category expired unanswered"
    )

    @classmethod
    def of(cls, stats: "CategoryStats") -> "AutonomyCandidateResponse":
        """Project one report row onto the API contract."""
        return cls.model_validate(stats.as_json())


class KnowledgeCollectionResponse(BaseModel):
    """One governed knowledge collection with its authority metadata (FR-D1)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    slug: str
    name: str
    authority_level: str
    owner: str | None = None
    created_at: datetime

    @classmethod
    def of(cls, collection: KnowledgeCollection) -> "KnowledgeCollectionResponse":
        """Project a collection row onto the API contract."""
        return cls(
            id=collection.id,
            tenant_id=collection.tenant_id,
            slug=collection.slug,
            name=collection.name,
            authority_level=collection.authority_level,
            owner=collection.owner,
            created_at=collection.created_at,
        )


class KnowledgeChunkResponse(BaseModel):
    """One knowledge chunk, resolvable from a citation.

    This is the verifiability endpoint for FR-D4: a citation in a decision names a
    chunk id (via the trace's retrieval step), and this shape is what a human opens to
    check the claim against its source — content, section, owner, date, authority.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    citation: str = Field(description="The citable reference: rule ID or document#section")
    source_ref: str | None = None
    section: str | None = None
    rule_id: str | None = None
    authority_level: str
    topic: str | None = None
    declared_value: str | None = None
    effective_date: date | None = None
    content: str
    created_at: datetime

    @classmethod
    def of(cls, chunk: KnowledgeChunk) -> "KnowledgeChunkResponse":
        """Project a chunk row onto the API contract."""
        return cls(
            id=chunk.id,
            tenant_id=chunk.tenant_id,
            collection_id=chunk.collection_id,
            citation=chunk.rule_id or chunk.source_ref or "unknown",
            source_ref=chunk.source_ref,
            section=chunk.section,
            rule_id=chunk.rule_id,
            authority_level=chunk.authority_level,
            topic=chunk.topic,
            declared_value=chunk.declared_value,
            effective_date=chunk.effective_date,
            content=chunk.content,
            created_at=chunk.created_at,
        )


class RemediationItemResponse(BaseModel):
    """One flagged knowledge conflict, addressed to the stale document's owner (FR-D5)."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    topic: str
    stale_source_ref: str
    stale_authority_level: str
    stale_declared_value: str | None = None
    winning_source_ref: str | None = Field(
        default=None, description="Null when authority could not resolve the conflict"
    )
    winning_authority_level: str | None = None
    winning_declared_value: str | None = None
    owner: str | None = None
    status: str
    detail: str | None = None
    created_at: datetime

    @classmethod
    def of(cls, item: RemediationItem) -> "RemediationItemResponse":
        """Project a remediation row onto the API contract."""
        return cls(
            id=item.id,
            tenant_id=item.tenant_id,
            topic=item.topic,
            stale_source_ref=item.stale_source_ref,
            stale_authority_level=item.stale_authority_level,
            stale_declared_value=item.stale_declared_value,
            winning_source_ref=item.winning_source_ref,
            winning_authority_level=item.winning_authority_level,
            winning_declared_value=item.winning_declared_value,
            owner=item.owner,
            status=item.status,
            detail=item.detail,
            created_at=item.created_at,
        )


# --- Evals (FR-F1..F3) ---------------------------------------------------------


class EvalSuiteResponse(BaseModel):
    """One eval suite in the catalogue, with how many cases it holds."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    slug: str
    name: str
    version: str = Field(description="Semver of the case set")
    case_count: int
    created_at: datetime

    @classmethod
    def of(cls, suite: EvalSuite, *, case_count: int) -> "EvalSuiteResponse":
        """Project a suite row onto the API contract."""
        return cls(
            id=suite.id,
            tenant_id=suite.tenant_id,
            slug=suite.slug,
            name=suite.name,
            version=suite.version,
            case_count=case_count,
            created_at=suite.created_at,
        )


class RunSuiteRequest(BaseModel):
    """Body of ``POST /eval/suites/{suiteId}/run``: which version to score."""

    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    version: str = Field(description="Semver of the version under test")


class EvalCheckResult(BaseModel):
    """One programmatic assert of one case (FR-F3)."""

    name: str
    passed: bool
    detail: str


class EvalCaseResult(BaseModel):
    """One scored case: expected vs actual, and every check behind the verdict."""

    code: str = Field(description="Case code, e.g. E-14")
    scenario: str
    passed: bool
    expected_action: str
    actual_action: str | None = Field(
        default=None, description="Null when the run reached no decision"
    )
    expected_citations: list[str]
    actual_citations: list[str]
    must_not_call: list[str]
    tools_called: list[str]
    run_id: uuid.UUID = Field(description="The real run this case executed — its trace is live")
    run_status: str
    detail: str = Field(description="Why the case failed, or `ok`")
    checks: list[EvalCheckResult]


class EvalRunResponse(BaseModel):
    """One scoring of one suite against one agent version — the gate's evidence."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    suite_id: uuid.UUID
    agent_version_id: uuid.UUID
    status: str = Field(description="running | completed")
    passed: bool | None = Field(default=None, description="The publish-gate verdict (FR-F2)")
    total: int | None = None
    passed_count: int | None = None
    case_results: list[EvalCaseResult] | None = None
    created_at: datetime

    @classmethod
    def of(cls, eval_run: EvalRun) -> "EvalRunResponse":
        """Project an eval-run row onto the API contract."""
        return cls(
            id=eval_run.id,
            tenant_id=eval_run.tenant_id,
            suite_id=eval_run.suite_id,
            agent_version_id=eval_run.agent_version_id,
            status=eval_run.status,
            passed=eval_run.passed,
            total=eval_run.total,
            passed_count=eval_run.passed_count,
            case_results=(
                [EvalCaseResult.model_validate(case) for case in eval_run.case_results]
                if eval_run.case_results is not None
                else None
            ),
            created_at=eval_run.created_at,
        )


class MetricsSummaryResponse(BaseModel):
    """The FR-G3 numbers over one population of runs — one agent's, or everyone's.

    Every figure is a projection of the append-only event log at read time; nothing here
    is counted anywhere else (ADR-008). Rates are over finished runs and are null, not
    zero, when nothing has finished — "no data" and "never happens" must not read alike.
    """

    runs: int
    runs_by_status: dict[str, int]
    finished_runs: int
    runs_refused: int = Field(
        description="Starts refused outright (suspended agent) — never became runs"
    )
    auto_approval_rate: float | None = Field(
        default=None, description="Completed with no human in the loop / finished runs"
    )
    escalation_rate: float | None = None
    block_rate: float | None = Field(
        default=None,
        description="Finished runs the platform stopped for a fault; human vetoes excluded",
    )
    blocks_by_reason: dict[str, int] = Field(
        description="governance.blocked events per reason code, human-loop codes included"
    )
    avg_tokens_per_run: float | None = None
    avg_cost_usd_per_run: str | None = Field(
        default=None, description="Exact decimal as a string, like every money field"
    )
    avg_latency_seconds: float | None = None
    total_cost_usd: str


class MetricsRunRef(BaseModel):
    """One recent run on the dashboard, resolvable to its full trace."""

    run_id: uuid.UUID
    agent: str = Field(description="slug@semver of the version that ran")
    status: str
    reason: str | None = None
    total_cost_usd: str | None = None
    started_at: datetime


class AgentMetricsResponse(BaseModel):
    """One agent's dashboard row: identity, lifecycle state, numbers, recent runs."""

    agent_id: uuid.UUID
    slug: str
    name: str
    state: Literal["draft", "published", "suspended"] = Field(
        description="suspended if any version is; else published if any is; else draft"
    )
    suspension: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The latest version.suspended event when suspended — trigger, detail, and "
            "the breaker's numbers, verbatim from the log"
        ),
    )
    metrics: MetricsSummaryResponse
    recent_runs: list[MetricsRunRef]

    @classmethod
    def of(cls, row: AgentMetrics) -> "AgentMetricsResponse":
        """Project one aggregated row onto the API contract."""
        return cls.model_validate(row.as_json())


class MetricsReportResponse(BaseModel):
    """The whole dashboard: every agent in the catalog, and the same numbers overall."""

    generated_at: datetime
    overall: MetricsSummaryResponse
    agents: list[AgentMetricsResponse]


class SuspendVersionRequest(BaseModel):
    """Body of the manual suspend: why, for the record."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, description="Recorded verbatim in the event")


class ResumeVersionRequest(BaseModel):
    """Body of resume: a note, recorded with the actor who overrode the suspension."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, description="Recorded verbatim in the event")


class ErrorResponse(BaseModel):
    """The platform's error shape."""

    code: str = Field(description="Stable machine-readable error code")
    message: str
    details: dict[str, Any] | None = None
