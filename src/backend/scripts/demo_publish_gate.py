"""Drive the publish gate end to end and print both attempts (Phase 4.5).

One draft version of the shipped invoice validator, three requests:

1. **publish, REFUSED** — no eval run exists for the draft, so the server answers
   ``409 publish_gate_unmet`` and the version stays a draft;
2. **the suite runs** — all 20 cases of ``06-eval-cases.md``, deterministic and offline,
   scored programmatically against the draft;
3. **publish, SUCCEEDS** — the same request as before, now answered 200, with the
   passing eval run recorded on the version as the gate's evidence.

Run it against the compose database (or any ``DATABASE_URL``) from ``src/backend``::

    python -m scripts.demo_publish_gate

It drives the real ASGI application over the real HTTP surface — same routers, same
dependencies, same role header — so what it prints is what a browser would get,
including the 409 body verbatim. It seeds everything first, so a fresh clone needs
nothing else. Each invocation authors a fresh draft (next free patch version), because
versions are immutable and a published one cannot be re-published.
"""

import io
import json
import sys
from typing import Any

from fastapi.testclient import TestClient

from app.db import sync_session
from scripts.seed import seed_ap_agents, seed_evals, seed_knowledge, seed_rules, seed_tenant

CONFIGURATOR = {"X-Forge-Role": "configurator"}

RULE = "-" * 78

# The bodies quote sentences the platform recorded, em dashes and all. Windows consoles
# default to a codepage that cannot encode them, and a demo should not die on a dash.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Author a draft, get refused, pass the suite, publish."""
    del argv
    from app.dna import load_agent_dna
    from app.main import app

    with sync_session() as session:
        tenant, _ = seed_tenant(session)
        seed_rules(session, tenant)
        session.flush()
        seed_knowledge(session, tenant)
        seed_evals(session, tenant)
        published = seed_ap_agents(session, tenant)
        session.commit()
        validator = published["invoice-validator"][0]
        agent_id = str(validator.agent_id)

    with TestClient(app) as client:
        taken = {
            v["version"]
            for v in client.get(f"/api/v1/agents/{agent_id}/versions", headers=CONFIGURATOR).json()
        }
        draft_version = _next_free_version(taken)

        print(RULE)
        print(f"1. Author a draft: invoice-validator@{draft_version}")
        print(RULE)
        dna = load_agent_dna("invoice-validator")
        dna["identity"]["version"] = draft_version
        created = client.post(
            f"/api/v1/agents/{agent_id}/versions", json={"dna": dna}, headers=CONFIGURATOR
        )
        created.raise_for_status()
        print(f"   created: status={created.json()['status']!r} (a draft, not published)")

        print()
        print(RULE)
        print("2. Publish attempt with no eval run — REFUSED")
        print(RULE)
        refused = client.post(
            f"/api/v1/agents/{agent_id}/versions/{draft_version}/publish", headers=CONFIGURATOR
        )
        print(f"   POST .../versions/{draft_version}/publish -> HTTP {refused.status_code}")
        _print_json(refused.json())

        print()
        print(RULE)
        print("3. Run the suite against the draft (20 cases, offline, deterministic)")
        print(RULE)
        suites = client.get("/api/v1/eval/suites", headers=CONFIGURATOR).json()
        suite = next(s for s in suites if s["slug"] == "meridian-ap-eval-suite")
        scored = client.post(
            f"/api/v1/eval/suites/{suite['id']}/run",
            json={"agent_id": agent_id, "version": draft_version},
            headers=CONFIGURATOR,
        )
        scored.raise_for_status()
        result = scored.json()
        for case in result["case_results"]:
            mark = "PASS" if case["passed"] else "FAIL"
            print(
                f"   {case['code']}  {mark}  expected={case['expected_action']} "
                f"actual={case['actual_action']}"
            )
        print(
            f"   => passed={result['passed']} "
            f"({result['passed_count']}/{result['total']} cases), eval_run {result['id']}"
        )

        print()
        print(RULE)
        print("4. The same publish attempt — SUCCEEDS")
        print(RULE)
        granted = client.post(
            f"/api/v1/agents/{agent_id}/versions/{draft_version}/publish", headers=CONFIGURATOR
        )
        print(f"   POST .../versions/{draft_version}/publish -> HTTP {granted.status_code}")
        body = granted.json()
        print(f"   status={body['status']!r}")
        print(f"   published_eval_run_id={body['published_eval_run_id']}  (the gate's evidence)")
        print(f"   published_at={body['published_at']}")
        return 0 if granted.status_code == 200 and refused.status_code == 409 else 1


def _next_free_version(taken: set[str]) -> str:
    """The first 1.2.x patch version this agent does not already have."""
    patch = 1
    while f"1.2.{patch}" in taken:
        patch += 1
    return f"1.2.{patch}"


def _print_json(body: dict[str, Any]) -> None:
    for line in json.dumps(body, indent=2).splitlines():
        print(f"   {line}")


if __name__ == "__main__":
    sys.exit(main())
