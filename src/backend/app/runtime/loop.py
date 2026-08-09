"""The agent runtime: a custom reason/act/observe loop (ADR-003).

This is the whole engine. It is deliberately not a framework: budget enforcement,
fail-closed escalation, and trace emission are the *subject* of this code rather than
behaviour wrapped around someone else's. Every governance requirement maps to a line
you can point at — ``max_steps`` to a ``range``, the timeout to a deadline check, the
one bounded retry to an ``attempt`` counter, escalation to a ``raise FailClosedError``.

Per run: load the pinned DNA, assemble the prompt from its instructions, then loop —

    call the LLM gateway
      -> decision? record it and finish
      -> tool call? run it through the tool gateway, feed the result back, continue

— until a decision, a guardrail, or a fail-closed condition ends it.

**State lives in the database, not in this object.** Everything durable is written by
the :class:`~app.runtime.trace.TraceRecorder` as it happens; the loop keeps only the
message list it is building. An ``AgentRuntime`` instance holds nothing worth
recovering, which is what makes the run reconstructable from its trace alone.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dna.model import Dna
from app.governance import GovernanceReason
from app.knowledge.retrieval import unresolved_conflicts
from app.llm.contract import (
    AdapterError,
    Budget,
    BudgetExceededError,
    Message,
    ModelSpec,
    ToolCall,
    ToolSpec,
    UnknownProviderError,
)
from app.llm.gateway import LlmGateway
from app.models import AgentVersion, Run
from app.runtime.errors import FailClosedError
from app.runtime.output import (
    DECISION_ACTIONS,
    DECISION_SCHEMA,
    MAX_OUTPUT_RETRIES,
    Decision,
    OutputValidationError,
    correction_message,
    interpret,
    review_decision,
)
from app.runtime.trace import TraceRecorder
from app.tools.gateway import ToolGateway

#: The protocol every agent runs under, prepended to its own task prompt. It states the
#: loop's contract — one tool call or one decision per turn, citations required — and
#: belongs to the runtime, not to any agent: an agent's DNA describes *what* it decides,
#: never *how* the loop works.
RUNTIME_PROTOCOL = (
    "You are executing inside the Forge runtime. On each turn, do exactly one of:\n"
    "  (a) call one of the tools you have been granted, or\n"
    "  (b) return your final decision as a JSON object with the fields "
    f"action (one of {', '.join(DECISION_ACTIONS)}), citations (a non-empty list), "
    "reasoning, and confidence (a number from 0 to 1).\n"
    "Every decision must cite what it applied: rule IDs such as R-001, and — for any "
    "claim drawn from retrieved knowledge — the document citation the retrieval "
    "returned (document#section, e.g. AP-Policy-2023.pdf#approval-thresholds). If no "
    "rule matches, or your confidence is low, decide escalate and say that no rule "
    "matched — never guess. State your confidence honestly: a decision below this "
    "agent's declared floor is escalated to a human whatever action you proposed, and "
    "a confidently wrong answer is the one failure a reviewer cannot catch."
)


class AgentRuntime:
    """Executes one agent version against one input."""

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
        # Injected so the wall-clock guardrail is testable without waiting for it.
        self._now = clock if clock is not None else lambda: datetime.now(UTC)

    async def start_run(
        self,
        *,
        agent_version: AgentVersion,
        run_input: dict[str, Any],
        trigger: str | None = None,
        actor: str = "system",
    ) -> Run:
        """Run the agent to a terminal state and return the run.

        Always returns a finished run for any outcome the platform anticipates —
        decision, guardrail, or fail-closed refusal. Only a genuine defect propagates,
        and even then the run is closed as ``error`` with a ``run.failed`` event first:
        a run left ``running`` forever would be a lie in the audit log.
        """
        recorder = TraceRecorder(self._session, actor=actor)
        await recorder.open_run(agent_version=agent_version, trigger=trigger, run_input=run_input)

        # Replaced as soon as the DNA parses; a DNA that does not parse has no budget,
        # and finishing the run must not depend on having read one.
        budget = Budget(max_tokens=0, max_cost_usd=Decimal("0"))
        try:
            dna = _load_dna(agent_version)
            budget = Budget(
                max_tokens=dna.model.max_tokens_per_run,
                max_cost_usd=dna.model.max_cost_usd_per_run,
            )
            await self._enforce_daily_ceiling(dna, agent_version)
            decision = await self._reason(recorder, dna, run_input, budget)

            # A decision can satisfy every schema and still not be allowed to stand:
            # below the confidence floor, or citing the no-rule-match default (R-091).
            # Raising here keeps every fail-closed stop on the one path below.
            verdict = review_decision(decision, dna.guardrails)
            if verdict is not None:
                raise FailClosedError(*verdict)
        except FailClosedError as exc:
            # **The one place a refusal is recorded.** Every fail-closed condition in the
            # platform — a gateway denial, a blown budget, a low-confidence decision —
            # arrives here as a FailClosedError and leaves as exactly one governance step
            # followed by one terminal event. No path stops a run quietly.
            await recorder.record_governance(
                reason=exc.reason, detail=exc.detail, terminal_status=exc.run_status
            )
            return await recorder.finish(
                status=exc.run_status, budget=budget, reason=exc.reason, detail=exc.detail
            )
        except Exception as exc:
            await recorder.finish(status="error", budget=budget, detail=repr(exc))
            raise

        return await recorder.finish(
            status=decision.run_status,
            budget=budget,
            # A decided escalation is a working loop reaching a human, not a failure.
            reason=GovernanceReason.AGENT_DECISION if decision.run_status == "escalated" else None,
        )

    async def _enforce_daily_ceiling(self, dna: Dna, agent_version: AgentVersion) -> None:
        """Refuse to start when this agent has spent its daily allowance (NFR-3).

        The ceiling is on the **agent**, not on the version or the run, so a runaway
        definition cannot be worked around by publishing a new version or by starting
        more runs. Checked before the first model call: the cheapest place to stop is
        before any spending, and a run that cannot afford to finish should not begin.
        """
        ceiling = dna.model.max_cost_usd_per_day
        spent = await self._spend_today(agent_version)
        if spent >= ceiling:
            raise FailClosedError(
                GovernanceReason.DAILY_BUDGET_EXCEEDED,
                f"agent {dna.identity.slug!r} has spent ${spent} today against a "
                f"model.max_cost_usd_per_day ceiling of ${ceiling}; no further runs "
                "start until the day rolls over",
            )

    async def _spend_today(self, agent_version: AgentVersion) -> Decimal:
        """What every run of this agent has cost since midnight UTC.

        Summed from the ``runs`` table rather than tracked in memory: the ceiling has to
        hold across processes, restarts, and versions, and the ledger that already
        records what was spent is the only honest source for it.
        """
        midnight = datetime.combine(self._now().astimezone(UTC).date(), time.min, tzinfo=UTC)
        total = await self._session.scalar(
            select(func.coalesce(func.sum(Run.total_cost_usd), 0))
            .join(AgentVersion, Run.agent_version_id == AgentVersion.id)
            .where(AgentVersion.agent_id == agent_version.agent_id, Run.started_at >= midnight)
        )
        return Decimal(str(total or 0))

    async def _reason(
        self,
        recorder: TraceRecorder,
        dna: Dna,
        run_input: dict[str, Any],
        budget: Budget,
    ) -> Decision:
        """The loop itself: model, tool, model, ... until a decision or a guardrail."""
        _require_supported(dna)

        model = ModelSpec(
            provider=dna.model.provider,
            model_id=dna.model.model_id,
            temperature=dna.model.temperature,
        )
        tool_specs = [
            ToolSpec(name=tool.name, description=tool.description, input_schema=tool.input_schema)
            for tool in self._tools.granted_tools(dna)
        ]
        messages = [
            Message(role="system", content=f"{RUNTIME_PROTOCOL}\n\n{dna.instructions.task_prompt}"),
            Message(
                role="user",
                content=f"Input for this run:\n{json.dumps(run_input, sort_keys=True, indent=2)}",
            ),
        ]
        deadline = self._now() + timedelta(seconds=dna.guardrails.timeout_seconds)

        # `max_steps` bounds reasoning-loop *iterations*, not persisted run_steps rows:
        # one iteration writes a model step, optionally a tool step, and — on the last
        # one — the decision step.
        for iteration in range(1, dna.guardrails.max_steps + 1):
            if self._now() >= deadline:
                raise FailClosedError(
                    GovernanceReason.TIMEOUT,
                    f"run exceeded guardrails.timeout_seconds="
                    f"{dna.guardrails.timeout_seconds} at step {iteration}",
                )

            output = await self._complete(recorder, model, messages, tool_specs, budget)

            if isinstance(output, Decision):
                await recorder.record_decision(output)
                return output

            outcome = self._tools.invoke(name=output.name, arguments=output.arguments, dna=dna)
            # Recorded whether or not it ran: a reviewer must see what was attempted.
            await recorder.record_tool_call(outcome)
            if outcome.pending_approval:
                # The DNA grants this tool only with a human in the loop. The call is
                # validated and parked; the run stops here rather than deciding without
                # the action it asked for, or executing it anyway (FR-E2).
                raise FailClosedError(
                    GovernanceReason.APPROVAL_REQUIRED,
                    f"tool {outcome.tool_name!r} requires human approval "
                    f"(autonomy={outcome.autonomy}); the call is validated and parked, "
                    "and nothing was executed",
                    run_status="awaiting_approval",
                )
            if not outcome.executed:
                # The gateway already decided *which* refusal this was; the runtime does
                # not re-derive it. One enforcement point, one reason code.
                raise FailClosedError(
                    outcome.reason or GovernanceReason.PERMISSION_DENIED,
                    outcome.error or f"tool {outcome.tool_name!r} did not execute",
                )

            contested = unresolved_conflicts(outcome.result or {})
            if contested:
                # Retrieval surfaced sources of equal authority that contradict each
                # other. R-090 has no winner to give, so nothing may choose — not the
                # model on its next turn, not the platform here. The contested sources
                # are already recorded in the tool step above, side by side with their
                # dates; the run stops for a human (R-091, FR-D2).
                raise FailClosedError(
                    GovernanceReason.KNOWLEDGE_CONFLICT,
                    "knowledge retrieval surfaced contradictory sources of equal "
                    f"authority on topic(s): {', '.join(contested)}; the authority "
                    "hierarchy cannot resolve them, so both are surfaced and the case "
                    "goes to a human (R-090/R-091)",
                )

            messages.append(
                Message(
                    role="assistant",
                    content=json.dumps(
                        {"tool_call": {"name": output.name, "arguments": output.arguments}},
                        sort_keys=True,
                    ),
                )
            )
            messages.append(
                Message(
                    role="user",
                    content=json.dumps(
                        {"tool_result": {"name": outcome.tool_name, "result": outcome.result}},
                        sort_keys=True,
                    ),
                )
            )

        raise FailClosedError(
            GovernanceReason.STEP_LIMIT,
            f"reached guardrails.max_steps={dna.guardrails.max_steps} without a decision",
        )

    async def _complete(
        self,
        recorder: TraceRecorder,
        model: ModelSpec,
        messages: list[Message],
        tool_specs: list[ToolSpec],
        budget: Budget,
    ) -> ToolCall | Decision:
        """One model turn, with the single bounded retry of ADR-006.

        Every call is recorded before it is judged — including the invalid one that
        triggers the retry and the one that overran the budget — so the trace shows
        what the model actually did, not a cleaned-up version of it.
        """
        attempt = 0
        while True:
            try:
                result = await self._llm.complete(
                    model=model,
                    messages=messages,
                    tools=tool_specs,
                    response_schema=DECISION_SCHEMA,
                    budget=budget,
                )
            except BudgetExceededError as exc:
                if exc.result is not None:
                    await recorder.record_model_call(
                        result=exc.result,
                        attempt=attempt,
                        outcome="budget_exceeded",
                        budget=budget,
                    )
                raise FailClosedError(GovernanceReason.BUDGET_EXCEEDED, str(exc)) from exc
            except (UnknownProviderError, AdapterError) as exc:
                raise FailClosedError(GovernanceReason.PROVIDER_UNAVAILABLE, str(exc)) from exc

            try:
                output = interpret(result)
            except OutputValidationError as exc:
                await recorder.record_model_call(
                    result=result, attempt=attempt, outcome="invalid_output", budget=budget
                )
                if attempt >= MAX_OUTPUT_RETRIES:
                    raise FailClosedError(
                        GovernanceReason.INVALID_OUTPUT,
                        f"output failed the response schema after {attempt + 1} attempts: {exc}",
                    ) from exc
                # Feed the violation back once, then hold the model to the schema.
                messages.append(Message(role="assistant", content=result.content or "(no content)"))
                messages.append(correction_message(exc))
                attempt += 1
                continue

            await recorder.record_model_call(
                result=result,
                attempt=attempt,
                outcome="tool_call" if isinstance(output, ToolCall) else "decision",
                budget=budget,
            )
            return output


def _load_dna(agent_version: AgentVersion) -> Dna:
    """Read the pinned DNA into its typed form.

    The document was validated against ``dna-schema.json`` when it was written, so a
    failure here means the stored row and the contract have diverged — which is a
    fail-closed condition, not something to work around.
    """
    try:
        return Dna.model_validate(agent_version.dna)
    except ValidationError as exc:
        raise FailClosedError(
            GovernanceReason.UNSUPPORTED_DEFINITION,
            f"stored DNA does not match the contract: {exc.error_count()} error(s)",
        ) from exc


def _require_supported(dna: Dna) -> None:
    """Refuse a valid definition this build cannot honestly execute.

    Instruction blocks are resolved by a layer that does not exist yet (Phase 4.x).
    Running such an agent anyway would execute a *different* agent from the one that
    was published — one missing its policy context — and would do so silently. Fail
    closed instead (golden rule 3). Knowledge collections stopped being on this list
    in Phase 4.3: they are resolved by the knowledge layer, and a collection the store
    cannot serve is refused at retrieval time with the same doctrine.
    """
    if dna.instructions.system_blocks:
        raise FailClosedError(
            GovernanceReason.UNSUPPORTED_DEFINITION,
            "DNA declares instruction system_blocks "
            f"({', '.join(dna.instructions.system_blocks)}) which this build cannot resolve",
        )
