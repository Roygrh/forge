"""Run the eval suite against an agent version and report per-case pass/fail (FR-F1).

The one command of the requirement. Offline and deterministic: the shipped agents run on
the demo adapter, so no API key and no network are involved, and the same version against
the same rules produces the same score on every machine.

The score is **recorded**, not just printed: this writes the same ``eval_runs`` row the
API's ``POST /eval/suites/{id}/run`` writes, so a suite passed from this command
satisfies the publish gate exactly as one run from the UI does — same evidence, same
table, same gate.

Usage (from src/backend, with DATABASE_URL set or the compose default reachable):

    python -m scripts.run_evals
    python -m scripts.run_evals --agent invoice-validator --version 1.2.0

Exit code 0 when the suite passed, 1 when any case failed — so CI can gate on it too.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.db import get_async_session_factory
from app.evals import EvalRunner
from app.evals.catalog import SUITE_SLUG, SUITE_VERSION
from app.llm.adapters.demo import MeridianDemoAdapter
from app.llm.gateway import LlmGateway
from app.models import Agent, AgentVersion, EvalSuite

# psycopg's async driver refuses Windows' default ProactorEventLoop — same arrangement,
# and same reason, as app/main.py: the deployment target is Linux, this line exists so
# the command also runs natively on a Windows development machine.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run(agent_slug: str, version_number: str | None) -> int:
    """Execute the suite and print the report; return the process exit code."""
    async with get_async_session_factory()() as session:
        suite = await session.scalar(
            select(EvalSuite).where(
                EvalSuite.slug == SUITE_SLUG, EvalSuite.version == SUITE_VERSION
            )
        )
        if suite is None:
            print(
                f"eval suite {SUITE_SLUG}@{SUITE_VERSION} is not seeded — "
                "run `python -m scripts.seed` first"
            )
            return 1

        agent = await session.scalar(select(Agent).where(Agent.slug == agent_slug))
        if agent is None:
            print(f"no agent {agent_slug!r} — run `python -m scripts.seed` first")
            return 1

        query = select(AgentVersion).where(AgentVersion.agent_id == agent.id)
        if version_number is not None:
            query = query.where(AgentVersion.version == version_number)
        agent_version = (
            await session.scalars(query.order_by(AgentVersion.created_at.desc()))
        ).first()
        if agent_version is None:
            wanted = version_number or "any version"
            print(f"no version ({wanted}) of agent {agent_slug!r}")
            return 1

        runner = EvalRunner(
            session,
            # The demo adapter alone, on purpose: the suite must be offline (FR-F1), so
            # a DNA naming a network provider scores `provider_unavailable` rather than
            # quietly reaching out.
            llm_gateway=LlmGateway([MeridianDemoAdapter()]),
            actor="scripts/run_evals",
        )
        eval_run = await runner.run_suite(suite=suite, agent_version=agent_version)

        print(f"suite {suite.slug}@{suite.version} vs {agent_slug}@{agent_version.version}")
        print(f"eval_run {eval_run.id}")
        print()
        for case in eval_run.case_results or []:
            mark = "PASS" if case["passed"] else "FAIL"
            line = (
                f"  {case['code']}  {mark}  expected={case['expected_action']} "
                f"actual={case['actual_action']}"
            )
            if not case["passed"]:
                line += f"  — {case['detail']}"
            print(line)
        print()
        verdict = "PASSED" if eval_run.passed else "FAILED"
        print(f"{verdict}: {eval_run.passed_count}/{eval_run.total} cases passed")
        return 0 if eval_run.passed else 1


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent",
        default="invoice-validator",
        help="Slug of the agent under test (default: invoice-validator).",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Semver of the version under test (default: the newest version).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(args.agent, args.version))


if __name__ == "__main__":
    sys.exit(main())
