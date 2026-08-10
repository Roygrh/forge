"""Drive the human-in-the-loop queue end to end and print both traces (Phase 4.4).

Two runs of the shipped ``invoice-comms`` agent, whose only tool is granted
``requires_approval``, so both park instead of contacting the vendor:

1. **approved** — a person releases the action; the run resumes, the message is sent, and
   MeridianERP records the approver rather than the runtime;
2. **expired** — nobody decides before the deadline; the run is **canceled** and nothing
   is sent. Expiry never approves.

Run it against the compose database (or any ``DATABASE_URL``) from ``src/backend``::

    python -m scripts.demo_hitl

It drives the real ASGI application over the real HTTP surface — same routers, same
dependencies, same role header — rather than calling the queue's Python API, so what it
prints is what a browser would get. It seeds the tenant, rules and agents first, so a
fresh clone needs nothing else.

**About the clock.** The comms agent's published SLA is eight hours, and waiting eight
hours to show an expiry is not a demo. For the second run the script advances the
*server's* clock past the deadline by overriding the same injected clock dependency the
runtime's wall-clock guardrail uses. Nothing about the deadline is faked: ``expires_at``
was written when the action parked, from the agent's own definition, and the platform
compares it against whatever the server believes the time is. The script says so on
screen when it does it.
"""

import io
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import sync_session
from app.erp import get_erp, reset_erp
from scripts.seed import seed_ap_agents, seed_knowledge, seed_rules, seed_tenant

CONFIGURATOR = {"X-Forge-Role": "configurator"}
APPROVER = {"X-Forge-Role": "approver"}
VIEWER = {"X-Forge-Role": "viewer"}

RUN_INPUT = {
    "invoice_id": "inv-0005",
    "question": "Which purchase order covers the price difference on this invoice?",
}

RULE = "-" * 78

# The traces quote sentences the platform recorded, em dashes and all. Windows consoles
# default to a codepage that cannot encode them, and a demo should not die on a dash.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Run both scenarios and print their traces."""
    del argv
    from app.api.deps import get_clock
    from app.main import app

    with sync_session() as session:
        tenant, _ = seed_tenant(session)
        seed_rules(session, tenant)
        session.flush()
        seed_knowledge(session, tenant)
        published = seed_ap_agents(session, tenant)
        session.commit()
        comms = published["invoice-comms"][0]
        agent_id, version = str(comms.agent_id), comms.version

    # A clean ERP so the demo shows what these two runs did, and nothing else.
    reset_erp()

    with TestClient(app) as client:
        _scenario_approved(client, agent_id, version)
        _scenario_expired(client, agent_id, version, app, get_clock)
        _report(client)

    return 0


# --- Scenario 1: parked, approved, resumed, executed --------------------------


def _scenario_approved(client: TestClient, agent_id: str, version: str) -> None:
    _banner("1. APPROVED - parked, released by a person, resumed, executed")

    posted_before = len(get_erp().posted_actions())
    run = _start(client, agent_id, version)
    print(f"POST /runs                      -> {run['status']}  (nothing was sent)")

    approval = _await_queue(client, run["id"])
    action = approval["proposed_action"]
    remaining = approval["seconds_remaining"]
    print(f"GET  /approvals                 -> 1 pending, expires in {remaining}s")
    print(f"     proposed action            -> {action['tool_ref']}")
    print(f"     arguments                  -> {action['args']}")
    print(f"     status of the call         -> {action['status']} (checked, and not run)")
    print(
        f"     evidence                   -> agent {approval['evidence']['agent']}, "
        f"{len(approval['evidence']['observations'])} prior observation(s)"
    )

    refused = client.post(
        f"/api/v1/approvals/{approval['id']}/approve", json={}, headers=CONFIGURATOR
    )
    print(
        f"POST /approve as configurator   -> {refused.status_code} "
        f"{refused.json()['code']} (needs {refused.json()['details']['required_permission']})"
    )

    granted = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"note": "PO confirmed by phone - go ahead."},
        headers=APPROVER,
    )
    granted.raise_for_status()
    body = granted.json()
    print(
        f"POST /approve as approver       -> {body['status']} by {body['decided_by']} "
        f"at {body['decided_at']}"
    )

    _print_trace(client, run["id"])
    _print_erp(posted_before)


# --- Scenario 2: parked, nobody decided, canceled -----------------------------


def _scenario_expired(
    client: TestClient,
    agent_id: str,
    version: str,
    app: FastAPI,
    get_clock: Callable[[], Callable[[], datetime]],
) -> None:
    _banner("2. EXPIRED - parked, nobody decided, run canceled (fail closed)")

    # The simulated ERP is stateful across the whole demo, like the system it stands in
    # for, so each scenario reports only what *it* posted.
    posted_before = len(get_erp().posted_actions())
    run = _start(client, agent_id, version)
    approval = _await_queue(client, run["id"])
    expires_at = approval["expires_at"]
    print(f"POST /runs                      -> {run['status']}")
    print(f"GET  /approvals                 -> 1 pending, deadline {expires_at}")

    jump = timedelta(seconds=approval["seconds_remaining"] + 60)
    print(
        f"     (advancing the SERVER clock by {jump} - the deadline above was written "
        "when the action parked, from the agent's own DNA, and is not touched)"
    )
    app.dependency_overrides[get_clock] = lambda: lambda: datetime.now(UTC) + jump
    try:
        queue = client.get("/api/v1/approvals", headers=APPROVER)
        queue.raise_for_status()
        print(f"GET  /approvals                 -> {len(queue.json())} pending (it lapsed)")

        too_late = client.post(
            f"/api/v1/approvals/{approval['id']}/approve", json={}, headers=APPROVER
        )
        print(
            f"POST /approve after the deadline-> {too_late.status_code} {too_late.json()['code']}"
        )
        print(f"     {too_late.json()['message']}")

        expired = client.get(f"/api/v1/approvals/{approval['id']}", headers=VIEWER).json()
        print(
            f"GET  /approvals/{{id}}            -> {expired['status']}, "
            f"decision={expired['decision']}, decided_by={expired['decided_by']}"
        )
        _print_trace(client, run["id"])
    finally:
        app.dependency_overrides.pop(get_clock, None)

    _print_erp(posted_before)


# --- The read-only report (FR-E5) ---------------------------------------------


def _report(client: TestClient) -> None:
    _banner("3. AUTONOMY-PROMOTION REPORT - read-only (FR-E5)")
    response = client.get("/api/v1/approvals/report", headers=VIEWER)
    response.raise_for_status()
    for row in response.json():
        print(f"{row['agent']:<26} {row['tool_ref']}")
        print(
            f"  granted={row['granted']} refused={row['rejected']} expired={row['expired']} "
            f"rate={row['approval_rate']} candidate={row['candidate']}"
        )
        print(f"  {row['recommendation']}")
        if row["fatigue_note"]:
            print(f"  {row['fatigue_note']}")
    print("\nNothing above was applied: autonomy lives in a published DNA document, so a")
    print("promotion is a new version through the eval gate - never a statistic.")


# --- Helpers ------------------------------------------------------------------


def _start(client: TestClient, agent_id: str, version: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/runs",
        json={"agent_id": agent_id, "version": version, "input": RUN_INPUT},
        headers=CONFIGURATOR,
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


def _await_queue(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.get("/api/v1/approvals", headers=APPROVER)
    response.raise_for_status()
    return next(item for item in response.json() if item["run_id"] == run_id)


def _print_trace(client: TestClient, run_id: str) -> None:
    run = client.get(f"/api/v1/runs/{run_id}", headers=VIEWER).json()
    trace = client.get(f"/api/v1/runs/{run_id}/trace", headers=VIEWER).json()

    print(f"\nTRACE  run {run_id}")
    print(
        f"       status={run['status']}  tokens={run['total_tokens']}  "
        f"cost=${run['total_cost_usd']}"
    )
    for step in trace["steps"]:
        print(f"  {step['step_no']:>2}. {_describe(step)}")
    print(
        f"  terminal event: {trace['events'][-1]['type']} "
        f"(reason={trace['events'][-1]['payload'].get('reason')})"
    )


def _describe(step: dict[str, Any]) -> str:
    kind = step["kind"]
    if kind == "reason":
        call = step["model_call"]
        return f"reason      {call['provider']}/{call['model_id']} -> {call['outcome']}"
    if kind == "tool":
        call = step["tool_invocation"]
        released = f" released_by={call['released_by']}" if call["released_by"] else ""
        return (
            f"tool        {call['tool_ref']} -> {call['status']}"
            f"{'  ' + str(call['reason_code']) if call['reason_code'] else ''}{released}"
        )
    if kind == "approval":
        approval = step["approval"]
        who = approval["decided_by"] or "nobody yet"
        return (
            f"approval    {approval['status']:<9} by {who}"
            f"{'  ' + approval['reason_code'] if approval['reason_code'] else ''}"
        )
    if kind == "governance":
        block = step["governance"]
        return f"BLOCKED     {block['reason_code']} -> run {block['terminal_status']}"
    decision = step["decision"]
    return f"decision    {decision['action']} citing {', '.join(decision['citations'])}"


def _print_erp(since: int = 0) -> None:
    """What this scenario posted to MeridianERP, and by whom."""
    posted = get_erp().posted_actions()[since:]
    if not posted:
        print("  MeridianERP: nothing was posted.\n")
        return
    for action in posted:
        print(f"  MeridianERP: {action.kind} {action.ref} on {action.invoice_id} by {action.actor}")
    print()


def _banner(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


if __name__ == "__main__":
    sys.exit(main())
