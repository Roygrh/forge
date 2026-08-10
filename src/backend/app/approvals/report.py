"""The autonomy-promotion report (FR-E5): approval rates per action category.

Rosa Delgado named the risk in discovery: *"approval fatigue"* — a queue full of actions
a person waves through stops being a control and becomes a rubber stamp, and the one
thing worse than no human in the loop is a human who has learned not to read. The answer
is not to approve less carefully; it is to stop asking about the actions nobody has ever
said no to, and spend the attention on the ones that need it.

So this module measures. For each **action category** — one agent version and one tool,
which is the granularity a DNA grant is written at — it counts what the approvers
actually did and computes the rate. A category with a long run of grants and no
rejections is a **candidate** for being granted ``autonomous`` instead.

**It is a report, and only a report.** Nothing here writes anything; there is no endpoint
that promotes an autonomy level, and there could not be one that made sense. Autonomy is
a property of a published DNA document (golden rule 1), so raising it means authoring a
new version and putting it through the eval gate — a change a reviewer approves, with a
diff, that historical runs still resolve against the definition *they* ran under. A
platform that quietly widened an agent's permissions because a statistic crossed a line
would be exactly the thing this whole project argues against.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentVersion, Approval, Run, ToolInvocation

#: How many decided approvals a category needs before its rate means anything. Twenty is
#: a judgement, stated once here rather than implied by a query: below it, "100% approved"
#: is three invoices in a row and no evidence of anything.
MIN_DECIDED_FOR_PROMOTION = 20

#: The grant rate above which a category is worth a reviewer's attention. Not 100%: the
#: question is whether the human is adding judgement, and a rate this high says the
#: rejections are rare enough that the queue is mostly ceremony.
PROMOTION_APPROVAL_RATE = 0.95


@dataclass(frozen=True)
class CategoryStats:
    """What the approvers did with one agent version's use of one tool."""

    agent: str
    agent_version_id: str
    tool_ref: str
    pending: int
    granted: int
    rejected: int
    expired: int

    @property
    def decided(self) -> int:
        """Approvals a person actually answered. Expiry is not an answer."""
        return self.granted + self.rejected

    @property
    def approval_rate(self) -> float | None:
        """Share of answered approvals that were granted, or ``None`` with none answered."""
        return None if self.decided == 0 else round(self.granted / self.decided, 4)

    @property
    def candidate(self) -> bool:
        """Whether this category is worth reviewing for an autonomy upgrade.

        Three conditions, all necessary: enough decisions to mean something, **no
        rejection ever** — one refusal is proof the human is doing work — and a grant
        rate above the threshold. Expiries do not qualify a category and do not
        disqualify one: they are a fatigue signal about the queue, reported separately.
        """
        rate = self.approval_rate
        return (
            self.decided >= MIN_DECIDED_FOR_PROMOTION
            and self.rejected == 0
            and rate is not None
            and rate >= PROMOTION_APPROVAL_RATE
        )

    @property
    def recommendation(self) -> str:
        """The finding, in the words a reviewer would use — never an instruction."""
        if self.candidate:
            return (
                f"{self.granted} approvals, none refused: consider granting {self.tool_ref} "
                f"as autonomous in a new version of {self.agent}. Applying it means "
                "publishing that version through the eval gate — nothing is promoted here."
            )
        if self.rejected:
            return (
                f"{self.rejected} of {self.decided} were refused: the review is doing work. "
                "Keep this action behind a human."
            )
        if self.decided < MIN_DECIDED_FOR_PROMOTION:
            return (
                f"{self.decided} decisions so far, below the {MIN_DECIDED_FOR_PROMOTION} "
                "this report will draw a conclusion from."
            )
        return "Approval rate below the threshold for a promotion candidate."

    @property
    def fatigue_note(self) -> str | None:
        """The expiry signal, when there is one.

        Expired approvals are the measurable form of Rosa's warning: nobody answered, and
        every one of them canceled a run. It is a fact about the queue's load, not about
        the action's safety, so it is surfaced beside the recommendation rather than
        folded into it.
        """
        if not self.expired:
            return None
        return (
            f"{self.expired} expired unanswered and canceled their runs — a queue-load "
            "signal, not evidence that this action is safe to automate."
        )

    def as_json(self) -> dict[str, Any]:
        """The API form."""
        return {
            "agent": self.agent,
            "agent_version_id": self.agent_version_id,
            "tool_ref": self.tool_ref,
            "pending": self.pending,
            "granted": self.granted,
            "rejected": self.rejected,
            "expired": self.expired,
            "decided": self.decided,
            "approval_rate": self.approval_rate,
            "candidate": self.candidate,
            "recommendation": self.recommendation,
            "fatigue_note": self.fatigue_note,
        }


async def autonomy_report(session: AsyncSession) -> list[CategoryStats]:
    """Approval rates per action category, busiest first.

    One aggregate query over the approvals and the invocations they hang off, grouped by
    the agent version and the tool — which is exactly the pair a DNA grant names, so a
    row of this report maps to one line of one document somebody would have to edit.
    """
    rows = await session.execute(
        select(
            Agent.slug,
            AgentVersion.version,
            AgentVersion.id,
            ToolInvocation.tool_ref,
            Approval.status,
            func.count().label("count"),
        )
        .join(ToolInvocation, Approval.tool_invocation_id == ToolInvocation.id)
        .join(Run, Approval.run_id == Run.id)
        .join(AgentVersion, Run.agent_version_id == AgentVersion.id)
        .join(Agent, AgentVersion.agent_id == Agent.id)
        .group_by(
            Agent.slug,
            AgentVersion.version,
            AgentVersion.id,
            ToolInvocation.tool_ref,
            Approval.status,
        )
    )

    tallies: dict[tuple[str, str, str], dict[str, int]] = {}
    for slug, version, version_id, tool_ref, status, count in rows:
        key = (f"{slug}@{version}", str(version_id), str(tool_ref))
        tallies.setdefault(key, {})[str(status)] = int(count)

    report = [
        CategoryStats(
            agent=agent,
            agent_version_id=version_id,
            tool_ref=tool_ref,
            pending=counts.get("pending", 0),
            granted=counts.get("granted", 0),
            rejected=counts.get("rejected", 0),
            expired=counts.get("expired", 0),
        )
        for (agent, version_id, tool_ref), counts in tallies.items()
    ]
    # Busiest first, then alphabetical: the categories that cost the most attention are
    # the ones the report exists to do something about.
    report.sort(key=lambda stats: (-(stats.decided + stats.pending + stats.expired), stats.agent))
    return report
