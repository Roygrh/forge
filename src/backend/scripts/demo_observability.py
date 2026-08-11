"""Demonstrate Phase 4.6 end to end: metrics from events, and the circuit breaker.

Runs against a **throwaway database** it creates and drops, so it never touches the demo
stack, and drives the real HTTP surface with a scripted model adapter — the same path
the SPA takes. Nothing here reaches into the runtime or writes a metric directly: every
number printed is what ``GET /agents/{id}/metrics`` served, and every number that
endpoint served was projected from the append-only event log (ADR-008).

Three acts:

1. **Mixed outcomes.** One agent, one completed run, one escalated run, one the platform
   blocked — then its metrics, and the runs they were derived from.
2. **The breaker trips.** A second agent faults past its window threshold, is suspended
   automatically, and its next start is refused with ``agent_suspended``.
3. **A person puts it back.** The configurator is refused; the admin resumes it, on the
   record; the agent runs again.

Usage (from src/backend, with a reachable PostgreSQL):

    python -m scripts.demo_observability
"""

import os
import sys
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# The output below is prose, and prose has arrows and em-dashes in it. A Windows console
# defaults to cp1252 and would abort on the first one, so say what encoding this writes.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEMO_DB_NAME = "forge_observability_demo"
DEFAULT_URL = "postgresql+psycopg://forge:forge@localhost:5432/forge"

_base_url = make_url(os.environ.get("DATABASE_URL") or DEFAULT_URL)
DEMO_DATABASE_URL = _base_url.set(database=DEMO_DB_NAME)
ADMIN_DATABASE_URL = _base_url.set(database="postgres")

# Set before any app module reads its settings, exactly as the test suite does.
os.environ["DATABASE_URL"] = DEMO_DATABASE_URL.render_as_string(hide_password=False)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.llm import FakeAdapter, LlmGateway, ScriptedTurn, decision_turn, tool_turn  # noqa: E402
from app.models import AgentVersion, Event, Tenant  # noqa: E402
from scripts.seed import seed_tenant  # noqa: E402
from tests.skeleton import publish_skeleton  # noqa: E402

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIGURATOR = {"X-Forge-Role": "configurator"}
ADMIN = {"X-Forge-Role": "admin"}
VIEWER = {"X-Forge-Role": "viewer"}

LOOK_UP = tool_turn("get_fact", {"topic": "forge"})
APPROVE = decision_turn("auto_approve", ["R-000"], "The governed fact was retrieved.")
ESCALATE = decision_turn("escalate", ["R-000"], "This one belongs with a person.")
FAULT = tool_turn("no_such_tool", {})


def _admin_statements(*statements: str) -> None:
    engine = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            for statement in statements:
                connection.execute(text(statement))
    finally:
        engine.dispose()


def _migrate() -> None:
    config = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_ROOT, "alembic"))
    command.upgrade(config, "head")


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def start(
    client: TestClient, version: AgentVersion, *turns: ScriptedTurn, expect: int = 202
) -> dict[str, Any]:
    """Script the model and start one run through the API."""
    from app.api.deps import get_llm_gateway
    from app.main import app

    adapter = FakeAdapter(script=list(turns))
    app.dependency_overrides[get_llm_gateway] = lambda: LlmGateway([adapter])
    response = client.post(
        "/api/v1/runs",
        json={
            "agent_id": str(version.agent_id),
            "version": version.version,
            "input": {"topic": "forge"},
        },
        headers=CONFIGURATOR,
    )
    assert response.status_code == expect, response.text
    body: dict[str, Any] = response.json()
    return body


def metrics(client: TestClient, version: AgentVersion) -> dict[str, Any]:
    response = client.get(f"/api/v1/agents/{version.agent_id}/metrics", headers=VIEWER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def show_metrics(row: dict[str, Any]) -> None:
    """Print one agent's dashboard row the way the SPA lays it out."""
    numbers = row["metrics"]
    print(f"\n  agent    {row['name']}  ({row['slug']})")
    print(f"  state    {row['state'].upper()}")
    print(f"\n  {'runs':<22}{numbers['runs']}")
    print(f"  {'by status':<22}{numbers['runs_by_status']}")
    print(f"  {'auto-approval rate':<22}{_pct(numbers['auto_approval_rate'])}")
    print(f"  {'escalation rate':<22}{_pct(numbers['escalation_rate'])}")
    print(f"  {'block rate':<22}{_pct(numbers['block_rate'])}")
    print(f"  {'blocks by reason':<22}{numbers['blocks_by_reason'] or '—'}")
    print(f"  {'avg tokens / run':<22}{numbers['avg_tokens_per_run']}")
    print(f"  {'avg cost / run':<22}${numbers['avg_cost_usd_per_run']}")
    print(f"  {'avg latency':<22}{numbers['avg_latency_seconds']:.3f}s")
    print(f"  {'total cost':<22}${numbers['total_cost_usd']}")
    print(f"  {'refused starts':<22}{numbers['runs_refused']}")
    print("\n  the runs these came from (each opens a full trace):")
    for ref in row["recent_runs"]:
        print(
            f"    {ref['run_id'][:8]}…  {ref['status']:<12}"
            f"{(ref['reason'] or '—'):<18}${ref['total_cost_usd']}"
        )


def _pct(rate: float | None) -> str:
    return "— (no finished runs)" if rate is None else f"{rate * 100:.1f}%"


def main() -> int:
    _admin_statements(
        f'DROP DATABASE IF EXISTS "{DEMO_DB_NAME}" WITH (FORCE)',
        f'CREATE DATABASE "{DEMO_DB_NAME}"',
    )
    try:
        _migrate()
        from app.config import get_settings
        from app.db import sync_session
        from app.main import app

        settings = get_settings()

        with sync_session() as session:
            tenant: Tenant = seed_tenant(session)[0]
            session.commit()
            mixed = publish_skeleton(session, tenant, slug="ap-triage")
            fragile = publish_skeleton(session, tenant, slug="ap-fragile")

        with TestClient(app) as client:
            # --- Act 1: an agent with mixed outcomes --------------------------
            rule("1. METRICS FOR AN AGENT WITH MIXED OUTCOMES (FR-G3)")
            # Headroom, so this act demonstrates metrics and not the breaker.
            settings.breaker_min_runs = 10**6
            settings.breaker_max_cost_usd = Decimal("1000000")

            start(client, mixed, LOOK_UP, APPROVE)
            print("  ran: a clean run — tool call, then a cited decision → completed")
            start(client, mixed, ESCALATE)
            print("  ran: the agent handed the case to a person → escalated")
            start(client, mixed, FAULT)
            print("  ran: the agent asked for a tool that does not exist → blocked")
            show_metrics(metrics(client, mixed))
            print(
                "\n  note  the block rate counts the platform's refusal, not the agent's\n"
                "        own escalation — a person being asked is the system working."
            )

            # --- Act 2: the breaker trips ------------------------------------
            rule("2. THE CIRCUIT BREAKER TRIPS (FR-G4)")
            settings.breaker_min_runs = 3
            settings.breaker_max_failure_rate = 0.5
            print(
                f"  thresholds  min {settings.breaker_min_runs} finished runs · "
                f"failure rate > {settings.breaker_max_failure_rate:.0%} · "
                f"window {settings.breaker_window_seconds}s"
            )
            start(client, fragile, LOOK_UP, APPROVE)
            print("\n  run 1  completed")
            start(client, fragile, FAULT)
            print("  run 2  blocked (tool_unknown)")
            start(client, fragile, FAULT)
            print("  run 3  blocked (tool_unknown)  → 2 of 3 faulted = 66.7% > 50%")

            row = metrics(client, fragile)
            suspension = row["suspension"]
            breaker = suspension["breaker"]
            print(f"\n  STATE     {row['state'].upper()}")
            print(f"  trigger   {suspension['trigger']}   by {suspension['actor']}")
            print(f"  detail    {suspension['detail']}")
            print(
                f"  judged    metric={breaker['metric']} observed={breaker['observed']} "
                f"threshold={breaker['threshold']} "
                f"({breaker['faulted_in_window']}/{breaker['runs_in_window']} runs)"
            )

            refused = start(client, fragile, LOOK_UP, APPROVE, expect=409)
            print(f"\n  next start → HTTP 409  code={refused['code']}")
            print(f"    {refused['message']}")
            print(
                f"  recorded as a governance.run_refused event; refused starts now "
                f"{metrics(client, fragile)['metrics']['runs_refused']}"
            )

            # --- Act 3: a person puts it back --------------------------------
            rule("3. MANUAL RESUME — ADMIN ONLY, ON THE RECORD (FR-G4, NFR-5)")
            url = f"/api/v1/agents/{fragile.agent_id}/versions/{fragile.version}/resume"

            denied = client.post(url, headers=CONFIGURATOR)
            print(f"  as configurator → HTTP {denied.status_code}  {denied.json()['message']}")
            print(f"  still {metrics(client, fragile)['state'].upper()}")

            resumed = client.post(url, headers=ADMIN, json={"note": "root cause fixed"})
            print(f"\n  as admin → HTTP {resumed.status_code}  status={resumed.json()['status']}")

            settings.breaker_min_runs = 10**6
            after = start(client, fragile, LOOK_UP, APPROVE)
            print(f"  and it runs again: {after['id'][:8]}… → {after['status']}")

            row = metrics(client, fragile)
            print(f"\n  STATE     {row['state'].upper()}   suspension={row['suspension']}")
            print(f"  runs      {row['metrics']['runs']}  ({row['metrics']['runs_by_status']})")

            rule("THE LOG BEHIND ALL OF IT")
            for event_type in (
                "version.suspended",
                "governance.run_refused",
                "governance.permission_denied",
                "version.resumed",
            ):
                with sync_session() as session:
                    rows = list(
                        session.scalars(
                            select(Event).where(Event.type == event_type).order_by(Event.event_id)
                        )
                    )
                for event in rows:
                    print(f"  #{event.event_id:<4} {event.type:<32} actor={event.actor}")
        return 0
    finally:
        _admin_statements(f'DROP DATABASE IF EXISTS "{DEMO_DB_NAME}" WITH (FORCE)')


if __name__ == "__main__":
    sys.exit(main())
