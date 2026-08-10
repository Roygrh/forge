"""The typed read view of an agent DNA document.

``dna-schema.json`` admits a document at write time; these models are how the runtime
*reads* one, so no part of the loop indexes into raw ``jsonb``. The two are deliberately
not generated from each other — the schema stays the single authority on what is valid,
and this module mirrors it with ``extra="forbid"`` so a field the schema would reject
cannot reach the runtime either. ``tests/test_dna_schema.py`` parses the shipped
examples through both, which is what keeps the mirror honest.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.governance import DEFAULT_APPROVAL_SLA_SECONDS

Autonomy = Literal["autonomous", "requires_approval", "forbidden"]


class _Block(BaseModel):
    """Base for every DNA block: unknown fields are a rejection, never a shrug."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Identity(_Block):
    """Who the agent is."""

    name: str
    slug: str
    version: str
    tenant_id: str
    type: Literal["chatbot", "workflow", "autonomous"]
    description: str


class Instructions(_Block):
    """What the agent is told."""

    system_blocks: list[str]
    task_prompt: str


class ToolGrant(_Block):
    """One explicit tool grant — least privilege (FR-C3)."""

    ref: str
    autonomy: Autonomy
    config: dict[str, object] | None = None


class Knowledge(_Block):
    """What the agent may retrieve from."""

    collections: list[str]
    authority_policy: Literal["highest_wins"]


class Model(_Block):
    """Which model answers, and what it may spend doing so."""

    provider: str
    model_id: str
    temperature: float
    max_tokens_per_run: int
    # Decimal, not float: these are money ceilings and are compared exactly.
    max_cost_usd_per_run: Decimal
    max_cost_usd_per_day: Decimal


class Guardrails(_Block):
    """The limits the loop enforces. The fail-closed pair is const-locked."""

    max_steps: int
    timeout_seconds: int
    #: The confidence floor for this agent's decisions (R-091). A decision below it is
    #: overridden to an escalation, whatever action it proposed.
    min_decision_confidence: float
    escalate_on_no_rule_match: Literal[True]
    require_citations: Literal[True]
    #: How long an action this agent parks waits for a human (FR-E3). ``None`` means the
    #: platform default (:data:`~app.governance.DEFAULT_APPROVAL_SLA_SECONDS`) applies —
    #: absent from a definition is "unstated", not "unlimited". Whichever number applies,
    #: the deadline is server-side and running out of it cancels the run.
    approval_sla_seconds: int | None = None

    def approval_sla(self) -> timedelta:
        """The SLA a parked action of this agent waits under."""
        return timedelta(seconds=self.approval_sla_seconds or DEFAULT_APPROVAL_SLA_SECONDS)


class Evals(_Block):
    """The suite this version must pass before it can be published (FR-F2)."""

    suite_ref: str
    publish_gate: Literal[True]


class Dna(_Block):
    """A complete agent definition, as the runtime reads it."""

    identity: Identity
    instructions: Instructions
    tools: list[ToolGrant] = Field(default_factory=list)
    knowledge: Knowledge
    model: Model
    guardrails: Guardrails
    evals: Evals

    def grant_for(self, tool_ref: str) -> ToolGrant | None:
        """Return the grant for ``tool_ref``, or ``None`` if the DNA does not grant it.

        A tool absent from the list does not exist for this agent — the tool gateway
        turns that ``None`` into a refusal, never into a default.
        """
        return next((grant for grant in self.tools if grant.ref == tool_ref), None)
