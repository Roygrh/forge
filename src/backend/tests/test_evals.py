"""The eval suite as the publish gate (Phase 4.5, FR-F1..F3).

Three claims are under test, end to end through the real HTTP surface:

* **The suite is executable and the shipped validator passes it** — all 20 cases of
  ``06-eval-cases.md``, scored programmatically from each run's append-only events, with
  no key, no network, and no judge.
* **The gate is hard.** ``POST .../publish`` answers 409 for a draft with no eval run,
  with a failed run, or with a passing run of a *different* version — and 200 only once
  this exact version has passed its declared suite. There is no parameter, role, or
  sequence of calls that bypasses it.
* **The score is honest.** A version whose definition cannot do the job — the shipped
  restricted validator, which forbids ``approve_invoice`` — fails the cases that need
  the tool, and therefore cannot ship.

The suite runs on the seeded artefacts (tenant, rules, knowledge, cases, agents), so a
failure here is a failure of what ``python -m scripts.seed`` installs, not of a fixture
written to make the test pass.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dna import load_agent_dna
from app.evals.catalog import CASES, SUITE_SLUG, SUITE_VERSION
from app.models import AgentVersion, EvalCase, EvalSuite
from scripts.seed import seed_ap_agents, seed_evals, seed_knowledge, seed_rules, seed_tenant

EVAL_CASES_DOC = Path(__file__).resolve().parents[3] / "docs" / "01-discovery" / "06-eval-cases.md"

CONFIGURATOR = {"X-Forge-Role": "configurator"}
APPROVER = {"X-Forge-Role": "approver"}
VIEWER = {"X-Forge-Role": "viewer"}


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    """App client bound to the test database (module-scoped: one event loop)."""
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def seeded(committed_session: Session) -> dict[str, AgentVersion]:
    """Everything ``python -m scripts.seed`` installs, plus the suite id under ``_suite``."""
    tenant, _ = seed_tenant(committed_session)
    seed_rules(committed_session, tenant)
    committed_session.flush()
    seed_knowledge(committed_session, tenant)
    seed_evals(committed_session, tenant)
    published = seed_ap_agents(committed_session, tenant)
    committed_session.commit()
    return {slug: version for slug, (version, _) in published.items()}


def suite_id_of(session: Session) -> str:
    suite = session.scalar(
        select(EvalSuite).where(EvalSuite.slug == SUITE_SLUG, EvalSuite.version == SUITE_VERSION)
    )
    assert suite is not None
    return str(suite.id)


# --- Helpers ------------------------------------------------------------------


def run_suite_for(
    client: TestClient, session: Session, version: AgentVersion | dict[str, Any]
) -> dict[str, Any]:
    """Run the seeded suite against a version through the API and return the result."""
    agent_id = version["agent_id"] if isinstance(version, dict) else str(version.agent_id)
    semver = version["version"] if isinstance(version, dict) else version.version
    response = client.post(
        f"/api/v1/eval/suites/{suite_id_of(session)}/run",
        json={"agent_id": str(agent_id), "version": semver},
        headers=CONFIGURATOR,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def draft_of(client: TestClient, base_slug: str, agent_id: str, new_version: str) -> dict[str, Any]:
    """Create a draft version of a shipped agent's DNA with a bumped version number."""
    dna = load_agent_dna(base_slug)
    dna["identity"]["version"] = new_version
    response = client.post(
        f"/api/v1/agents/{agent_id}/versions", json={"dna": dna}, headers=CONFIGURATOR
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "draft"
    assert body["published_eval_run_id"] is None
    return body


def publish(
    client: TestClient, agent_id: str, version: str, headers: dict[str, str]
) -> httpx.Response:
    response: httpx.Response = client.post(
        f"/api/v1/agents/{agent_id}/versions/{version}/publish", headers=headers
    )
    return response


# --- The seeded suite ----------------------------------------------------------


def test_seeding_the_cases_is_idempotent(committed_session: Session) -> None:
    """Two seeds leave exactly one suite and one row per case, like every other seed."""
    tenant, _ = seed_tenant(committed_session)
    first_written, _ = seed_evals(committed_session, tenant)
    committed_session.commit()
    second_written, left_alone = seed_evals(committed_session, tenant)
    committed_session.commit()

    assert second_written == 0
    assert left_alone == len(CASES)

    suites = list(committed_session.scalars(select(EvalSuite).where(EvalSuite.slug == SUITE_SLUG)))
    assert len(suites) == 1
    cases = list(
        committed_session.scalars(select(EvalCase).where(EvalCase.suite_id == suites[0].id))
    )
    assert len(cases) == len(CASES) == 20
    assert {case.code for case in cases} == {case.code for case in CASES}
    # Every seeded case is executable: it has an input, an expected action, citations.
    for case in cases:
        assert case.input, f"{case.code} has no run input"
        assert case.expected_action
        assert case.expected_citations


def test_the_catalogue_matches_the_markdown() -> None:
    """Golden rule 5: a case in the document and not the encoding (or vice versa) fails."""
    text = EVAL_CASES_DOC.read_text(encoding="utf-8")
    documented = set(re.findall(r"\bE-\d{2}\b", text))
    encoded = {case.code for case in CASES}
    assert encoded == documented


def test_the_suite_is_listed_with_its_case_count(
    client: TestClient, seeded: dict[str, AgentVersion]
) -> None:
    response = client.get("/api/v1/eval/suites", headers=VIEWER)
    assert response.status_code == 200
    suites = [s for s in response.json() if s["slug"] == SUITE_SLUG]
    assert len(suites) == 1
    assert suites[0]["case_count"] == 20


# --- The runner: the shipped validator passes all 20 cases ---------------------


def test_the_shipped_validator_passes_every_case(
    client: TestClient, seeded: dict[str, AgentVersion], committed_session: Session
) -> None:
    """The 20 cases, through the real runtime, all green — the artefact the gate reads.

    Beyond the aggregate, the cases that define the suite's teeth are spot-checked:
    the duplicate (E-14) never called ``approve_invoice``, the no-rule case (E-20)
    cited the fail-closed default, and the policy question (E-19) cited both policy
    documents and the governing rule.
    """
    result = run_suite_for(client, committed_session, seeded["invoice-validator"])

    assert result["status"] == "completed"
    assert result["total"] == 20
    by_code = {case["code"]: case for case in result["case_results"]}
    failed = [case["code"] for case in result["case_results"] if not case["passed"]]
    assert failed == [], {code: by_code[code]["detail"] for code in failed}
    assert result["passed_count"] == 20
    assert result["passed"] is True

    e01 = by_code["E-01"]
    assert e01["actual_action"] == "auto_approve"
    assert {"R-001", "R-010"} <= set(e01["actual_citations"])
    assert "approve_invoice" in e01["tools_called"]

    e14 = by_code["E-14"]
    assert e14["actual_action"] == "block_escalate"
    assert "approve_invoice" not in e14["tools_called"]

    e18 = by_code["E-18"]
    assert e18["actual_action"] == "priority_queue"
    assert {"R-001", "R-050"} <= set(e18["actual_citations"])

    e19 = by_code["E-19"]
    assert {"R-020", "R-090", "AP-Policy-2019.pdf#approval-thresholds"} <= set(
        e19["actual_citations"]
    )

    e20 = by_code["E-20"]
    assert e20["actual_citations"] == ["R-091"]

    # Every case executed a real, inspectable run — cross-cutting assert 4.
    for case in result["case_results"]:
        trace = client.get(f"/api/v1/runs/{case['run_id']}/trace", headers=VIEWER)
        assert trace.status_code == 200
        assert trace.json()["events"], f"{case['code']} left no trace"

    # The verdict is retrievable, and listable by version (what the UI's gate reads).
    fetched = client.get(f"/api/v1/eval/runs/{result['id']}", headers=VIEWER)
    assert fetched.status_code == 200
    assert fetched.json()["passed"] is True

    listed = client.get(
        f"/api/v1/eval/runs?agent_version_id={result['agent_version_id']}", headers=VIEWER
    )
    assert result["id"] in {run["id"] for run in listed.json()}


# --- The publish gate ----------------------------------------------------------


def test_publish_is_refused_until_the_suite_passes_and_succeeds_after(
    client: TestClient, seeded: dict[str, AgentVersion], committed_session: Session
) -> None:
    """The whole gate, in order: 409 with no evidence, 200 after a pass, 409 thereafter."""
    validator = seeded["invoice-validator"]
    agent_id = str(validator.agent_id)
    draft = draft_of(client, "invoice-validator", agent_id, "1.3.0")

    # REFUSED: no eval run exists for this version. Hard 409, still a draft.
    refused = publish(client, agent_id, "1.3.0", CONFIGURATOR)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "publish_gate_unmet"
    assert refused.json()["details"]["suite_ref"] == f"{SUITE_SLUG}@{SUITE_VERSION}"
    assert refused.json()["details"]["latest_eval_run_passed"] is None
    still = client.get(f"/api/v1/agents/{agent_id}/versions/1.3.0", headers=VIEWER).json()
    assert still["status"] == "draft"

    # A passing run of a DIFFERENT version satisfies nothing for this one.
    other = run_suite_for(client, committed_session, seeded["invoice-validator"])
    assert other["passed"] is True
    assert publish(client, agent_id, "1.3.0", CONFIGURATOR).status_code == 409

    # Now this version earns it.
    result = run_suite_for(client, committed_session, draft)
    assert result["passed"] is True

    published = publish(client, agent_id, "1.3.0", CONFIGURATOR)
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "published"
    # The gate's evidence travels with the version — unlike a seeded row's null.
    assert body["published_eval_run_id"] == result["id"]
    assert body["published_at"] is not None

    # The published version actually runs.
    run = client.post(
        "/api/v1/runs",
        json={"agent_id": agent_id, "version": "1.3.0", "input": {"invoice_id": "inv-0003"}},
        headers=CONFIGURATOR,
    )
    assert run.status_code == 202, run.text
    assert run.json()["status"] == "completed"

    # Publishing is not repeatable: the version is no longer a draft.
    assert publish(client, agent_id, "1.3.0", CONFIGURATOR).status_code == 409
    assert publish(client, agent_id, "1.3.0", CONFIGURATOR).json()["code"] == "version_not_draft"


def test_a_version_that_fails_the_suite_cannot_ship(
    client: TestClient, seeded: dict[str, AgentVersion], committed_session: Session
) -> None:
    """The restricted validator forbids approve_invoice, fails the happy paths, stays a draft.

    This is the honesty check on the runner itself: a definition that cannot do the job
    scores as one, and its failed run is exactly as useless to the gate as no run.
    """
    restricted = seeded["invoice-validator-restricted"]
    agent_id = str(restricted.agent_id)
    draft = draft_of(client, "invoice-validator-restricted", agent_id, "9.9.9")

    result = run_suite_for(client, committed_session, draft)
    assert result["status"] == "completed"
    assert result["passed"] is False

    by_code = {case["code"]: case for case in result["case_results"]}
    # E-01 needs an approval the definition forbids: no decision is reached, the
    # gateway's refusal ends the run, and the case fails on the missing action.
    assert by_code["E-01"]["passed"] is False
    assert by_code["E-01"]["actual_action"] is None
    # The duplicate case never needed the tool, so it still passes — the suite fails
    # the version for what it cannot do, not for everything at once.
    assert by_code["E-14"]["passed"] is True

    refused = publish(client, agent_id, "9.9.9", CONFIGURATOR)
    assert refused.status_code == 409
    assert refused.json()["code"] == "publish_gate_unmet"
    assert refused.json()["details"]["latest_eval_run_passed"] is False
    assert refused.json()["details"]["latest_eval_run_id"] == result["id"]


def test_the_gate_respects_segregation_of_duties(
    client: TestClient, seeded: dict[str, AgentVersion], committed_session: Session
) -> None:
    """Authoring and publishing need the configurator; the approver and viewer get 403."""
    validator = seeded["invoice-validator"]
    agent_id = str(validator.agent_id)

    dna = load_agent_dna("invoice-validator")
    dna["identity"]["version"] = "8.8.8"
    for headers in (APPROVER, VIEWER):
        created = client.post(
            f"/api/v1/agents/{agent_id}/versions", json={"dna": dna}, headers=headers
        )
        assert created.status_code == 403
        assert created.json()["code"] == "permission_denied"

        ran = client.post(
            f"/api/v1/eval/suites/{suite_id_of(committed_session)}/run",
            json={"agent_id": agent_id, "version": validator.version},
            headers=headers,
        )
        assert ran.status_code == 403

        refused = publish(client, agent_id, validator.version, headers)
        assert refused.status_code == 403


def test_invalid_dna_is_rejected_with_every_violation(
    client: TestClient, seeded: dict[str, AgentVersion]
) -> None:
    """The DNA schema is the write-time contract for API authoring too (golden rule 1)."""
    validator = seeded["invoice-validator"]
    dna = load_agent_dna("invoice-validator")
    dna["identity"]["version"] = "7.7.7"
    dna["guardrails"]["escalate_on_no_rule_match"] = False  # const-locked fail-closed field

    response = client.post(
        f"/api/v1/agents/{validator.agent_id}/versions", json={"dna": dna}, headers=CONFIGURATOR
    )
    assert response.status_code == 400
    assert response.json()["code"] == "dna_invalid"
    assert any(
        "escalate_on_no_rule_match" in error for error in response.json()["details"]["errors"]
    )
