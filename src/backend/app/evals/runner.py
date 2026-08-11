"""The eval runner: every case, through the real runtime, scored by asserts (FR-F1, FR-F3).

Nothing here is a harness stand-in. Each case starts a genuine run of the version under
test — the same :class:`~app.runtime.loop.AgentRuntime`, the same tool gateway contract,
the same trace — and is then scored **from the run's append-only events**, not from
anything the runner kept in memory. What the suite certifies is what an auditor could
re-derive from the log (ADR-008).

Deterministic and offline by construction:

* The model is whatever the DNA's provider resolves to through the LLM gateway — for the
  shipped agents that is the deterministic demo adapter, so the suite needs no key and
  no network.
* Each case runs against a **private, freshly built** :class:`~app.erp.store.ErpStore`,
  never the process-wide one: E-01 approving an invoice must not change what E-14 sees,
  and running the suite must not disturb a demo in progress.
* The governed rules are read from the database once per suite run — the suite scores
  the version against the rules in force, which is the pair the publish gate certifies.

Every score is a programmatic assert. Per case: the final action, the required
citations, the tools that must never be called, and the cross-cutting asserts of
``06-eval-cases.md`` — at least one citation (R-092), no unapproved write, budgets
respected, and a reconstructable trace. LLM-as-judge is deliberately absent: nothing in
these cases needs one, and a gate should not be as probabilistic as the thing it gates.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dna.model import Dna
from app.erp.store import ErpStore
from app.llm.gateway import LlmGateway
from app.models import AgentVersion, EvalCase, EvalRun, EvalSuite, Event, Run
from app.rules.model import RuleSet
from app.rules.repository import load_rule_set
from app.runtime.loop import AgentRuntime
from app.runtime.trace import (
    EVENT_DECISION_MADE,
    EVENT_MODEL_CALLED,
    EVENT_RUN_STARTED,
    EVENT_TOOL_CALLED,
    load_events,
)
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry, build_tools

EVENT_EVAL_RUN_STARTED = "eval_run.started"
EVENT_EVAL_RUN_COMPLETED = "eval_run.completed"

#: The AP write tools of the cross-cutting assert: never executed without either an
#: ``auto_approve`` outcome or a recorded human approval (06-eval-cases.md §cross-cutting).
_GOVERNED_WRITES = frozenset({"approve_invoice", "schedule_payment"})


@dataclass(frozen=True)
class CheckResult:
    """One programmatic assert of one case."""

    name: str
    passed: bool
    detail: str

    def as_json(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class CaseResult:
    """One scored case, exactly as persisted in ``eval_runs.case_results``."""

    code: str
    scenario: str
    passed: bool
    expected_action: str
    actual_action: str | None
    expected_citations: list[str]
    actual_citations: list[str]
    must_not_call: list[str]
    tools_called: list[str]
    run_id: str
    run_status: str
    checks: list[CheckResult]

    @property
    def detail(self) -> str:
        """Why the case failed, or ``ok`` — the one-line summary the UI leads with."""
        failures = [f"{check.name}: {check.detail}" for check in self.checks if not check.passed]
        return "; ".join(failures) if failures else "ok"

    def as_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "scenario": self.scenario,
            "passed": self.passed,
            "expected_action": self.expected_action,
            "actual_action": self.actual_action,
            "expected_citations": self.expected_citations,
            "actual_citations": self.actual_citations,
            "must_not_call": self.must_not_call,
            "tools_called": self.tools_called,
            "run_id": self.run_id,
            "run_status": self.run_status,
            "detail": self.detail,
            "checks": [check.as_json() for check in self.checks],
        }


class EvalRunner:
    """Scores one suite against one agent version and records the result."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm_gateway: LlmGateway,
        clock: Callable[[], datetime] | None = None,
        actor: str = "system",
    ) -> None:
        self._session = session
        self._llm = llm_gateway
        self._clock = clock
        self._actor = actor

    async def run_suite(self, *, suite: EvalSuite, agent_version: AgentVersion) -> EvalRun:
        """Execute every case of ``suite`` against ``agent_version`` and persist the score.

        Returns the completed :class:`~app.models.EvalRun` whose ``passed`` boolean is
        what the publish gate reads (FR-F2). The row is written ``running`` first and
        completed at the end, in the same append-then-close discipline as a run: a
        crashed suite leaves a visibly unfinished record, never a quietly missing one.
        """
        eval_run = EvalRun(
            tenant_id=suite.tenant_id,
            suite_id=suite.id,
            agent_version_id=agent_version.id,
            status="running",
        )
        self._session.add(eval_run)
        await self._session.flush()
        self._session.add(
            Event(
                tenant_id=suite.tenant_id,
                type=EVENT_EVAL_RUN_STARTED,
                actor=self._actor,
                agent_version_id=agent_version.id,
                payload={
                    "eval_run_id": str(eval_run.id),
                    "suite": f"{suite.slug}@{suite.version}",
                    "agent_version_id": str(agent_version.id),
                },
            )
        )
        await self._session.commit()

        cases = list(
            await self._session.scalars(
                select(EvalCase).where(EvalCase.suite_id == suite.id).order_by(EvalCase.code)
            )
        )
        # The rules in force *now*: the suite certifies the version against them, which
        # is the same pair the runtime executes after publish.
        rule_set = await load_rule_set(self._session)

        results = [await self._run_case(case, agent_version, rule_set) for case in cases]

        eval_run.status = "completed"
        eval_run.total = len(results)
        eval_run.passed_count = sum(1 for result in results if result.passed)
        # An empty suite does not pass: a gate satisfied by zero evidence is no gate.
        eval_run.passed = bool(results) and eval_run.passed_count == eval_run.total
        eval_run.case_results = [result.as_json() for result in results]
        self._session.add(
            Event(
                tenant_id=suite.tenant_id,
                type=EVENT_EVAL_RUN_COMPLETED,
                actor=self._actor,
                agent_version_id=agent_version.id,
                payload={
                    "eval_run_id": str(eval_run.id),
                    "suite": f"{suite.slug}@{suite.version}",
                    "passed": eval_run.passed,
                    "passed_count": eval_run.passed_count,
                    "total": eval_run.total,
                    "failed_cases": [r.code for r in results if not r.passed],
                },
            )
        )
        await self._session.commit()
        return eval_run

    async def _run_case(
        self, case: EvalCase, agent_version: AgentVersion, rule_set: RuleSet
    ) -> CaseResult:
        """Run one case in isolation and score its trace.

        A private ERP per case: the store is rebuilt from seed so every case meets
        MeridianERP exactly as ``06-eval-cases.md`` describes it, whatever the cases
        before it did — and the process-wide demo store is never touched.
        """
        tool_gateway = ToolGateway(ToolRegistry(build_tools(erp=ErpStore(), rule_set=rule_set)))
        runtime = AgentRuntime(
            self._session,
            llm_gateway=self._llm,
            tool_gateway=tool_gateway,
            clock=self._clock,
        )
        run = await runtime.start_run(
            agent_version=agent_version,
            run_input=dict(case.input),
            trigger="eval",
            actor=self._actor,
        )
        return await self._score(case, agent_version, run)

    async def _score(self, case: EvalCase, agent_version: AgentVersion, run: Run) -> CaseResult:
        """Score one finished run against its case — every check from the log."""
        events = await load_events(self._session, run.id)
        decision = next(
            (event.payload for event in events if event.type == EVENT_DECISION_MADE), None
        )
        tool_calls = [event.payload for event in events if event.type == EVENT_TOOL_CALLED]
        model_turns = sum(1 for event in events if event.type == EVENT_MODEL_CALLED)

        actual_action = str(decision["action"]) if decision is not None else None
        actual_citations = [str(c) for c in decision.get("citations", [])] if decision else []
        expected_citations = list(case.expected_citations or [])
        must_not_call = list(case.must_not_call or [])
        tools_called = [str(call.get("tool_name")) for call in tool_calls]

        checks = [
            self._check_action(case, actual_action),
            self._check_citations(expected_citations, actual_citations, decision),
            self._check_must_not_call(must_not_call, tools_called),
            self._check_no_unapproved_write(actual_action, tool_calls),
            self._check_budgets(agent_version, run, model_turns),
            self._check_trace(events, decision),
        ]

        return CaseResult(
            code=case.code,
            scenario=case.scenario,
            passed=all(check.passed for check in checks),
            expected_action=case.expected_action,
            actual_action=actual_action,
            expected_citations=expected_citations,
            actual_citations=actual_citations,
            must_not_call=must_not_call,
            tools_called=tools_called,
            run_id=str(run.id),
            run_status=run.status,
            checks=checks,
        )

    # --- The individual asserts ------------------------------------------------

    def _check_action(self, case: EvalCase, actual_action: str | None) -> CheckResult:
        """The final action is exactly the one the case expects."""
        if actual_action is None:
            return CheckResult(
                "final_action",
                False,
                f"expected {case.expected_action!r} but the run reached no decision",
            )
        passed = actual_action == case.expected_action
        return CheckResult(
            "final_action",
            passed,
            "ok" if passed else f"expected {case.expected_action!r}, got {actual_action!r}",
        )

    def _check_citations(
        self,
        expected: list[str],
        actual: list[str],
        decision: dict[str, Any] | None,
    ) -> CheckResult:
        """Every required citation is present, and the decision cites at least one (R-092)."""
        if decision is None:
            return CheckResult("citations", False, "no decision, so nothing was cited")
        if not actual:
            return CheckResult("citations", False, "decision carries no citations (R-092)")
        missing = [citation for citation in expected if citation not in actual]
        if missing:
            return CheckResult(
                "citations",
                False,
                f"missing required citation(s): {', '.join(missing)} (cited: {', '.join(actual)})",
            )
        return CheckResult("citations", True, "ok")

    def _check_must_not_call(
        self, must_not_call: list[str], tools_called: list[str]
    ) -> CheckResult:
        """None of the forbidden tools appears in the trace — called at all, in any status."""
        violations = [name for name in must_not_call if name in tools_called]
        if violations:
            return CheckResult(
                "must_not_call",
                False,
                f"forbidden tool(s) were called: {', '.join(violations)}",
            )
        return CheckResult("must_not_call", True, "ok")

    def _check_no_unapproved_write(
        self, actual_action: str | None, tool_calls: list[dict[str, Any]]
    ) -> CheckResult:
        """Cross-cutting assert 2: a write executes only under auto_approve or a human release."""
        unapproved = [
            str(call.get("tool_name"))
            for call in tool_calls
            if str(call.get("tool_name")) in _GOVERNED_WRITES
            and call.get("status") == "executed"
            and not call.get("released_by")
            and actual_action != "auto_approve"
        ]
        if unapproved:
            return CheckResult(
                "no_unapproved_write",
                False,
                f"{', '.join(unapproved)} executed without an auto_approve outcome "
                "or a recorded human approval",
            )
        return CheckResult("no_unapproved_write", True, "ok")

    def _check_budgets(
        self, agent_version: AgentVersion, run: Run, model_turns: int
    ) -> CheckResult:
        """Cross-cutting assert 3: the run finished inside every budget its DNA declares."""
        dna = Dna.model_validate(agent_version.dna)
        problems: list[str] = []
        if run.finished_at is None:
            problems.append("run never reached a terminal state")
        if (run.total_tokens or 0) > dna.model.max_tokens_per_run:
            problems.append(
                f"tokens {run.total_tokens} exceed max_tokens_per_run="
                f"{dna.model.max_tokens_per_run}"
            )
        if Decimal(str(run.total_cost_usd or 0)) > dna.model.max_cost_usd_per_run:
            problems.append(
                f"cost {run.total_cost_usd} exceeds max_cost_usd_per_run="
                f"{dna.model.max_cost_usd_per_run}"
            )
        if model_turns > dna.guardrails.max_steps:
            problems.append(
                f"{model_turns} model turns exceed max_steps={dna.guardrails.max_steps}"
            )
        if problems:
            return CheckResult("budgets", False, "; ".join(problems))
        return CheckResult("budgets", True, "ok")

    def _check_trace(self, events: list[Event], decision: dict[str, Any] | None) -> CheckResult:
        """Cross-cutting assert 4: the full trace exists and is reconstructable."""
        if not events:
            return CheckResult("trace", False, "no events were recorded for this run")
        problems: list[str] = []
        if events[0].type != EVENT_RUN_STARTED:
            problems.append(f"log does not open with run.started (got {events[0].type})")
        if not events[-1].type.startswith("run."):
            problems.append(f"log does not close with a terminal run event (got {events[-1].type})")
        if decision is None and not any(event.type == "governance.blocked" for event in events):
            problems.append("run ended with neither a decision nor a recorded refusal")
        if problems:
            return CheckResult("trace", False, "; ".join(problems))
        return CheckResult("trace", True, "ok")
