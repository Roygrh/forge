"""The demo story, walked end to end — so the script cannot quietly stop being true.

``docs/demo-script.md`` tells a presenter what will happen when they press Run. That is
a promise made to an audience in a room, and the only way to keep it is to execute every
beat here, through the real HTTP surface, and assert the outcome the script claims:
terminal status, final action, and the citations the decision carried.

Nothing is stubbed. These runs use the shipped configuration — the deterministic demo
adapter the composed stack uses, the governed rules read from the database, the real tool
gateway — so a beat that stops behaving fails the build rather than failing on stage.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.demo_story import DEMO_RUNS, DEMO_STORY, DemoRun
from app.dna import SHIPPED_AGENT_SLUGS
from app.erp import reset_erp
from app.erp.seed_data import INVOICES
from app.evals.catalog import E19_QUESTION
from app.models import AgentVersion, Tenant
from scripts.seed import seed_ap_agents, seed_knowledge, seed_rules, seed_tenant

RUNS_URL = "/api/v1/runs"
HEADERS = {"X-Forge-Role": "configurator"}


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def seeded(committed_session: Session) -> Tenant:
    """Tenant, rules and knowledge — beat 5 answers from the governed corpus."""
    tenant, _ = seed_tenant(committed_session)
    seed_rules(committed_session, tenant)
    committed_session.flush()
    seed_knowledge(committed_session, tenant)
    committed_session.commit()
    return tenant


@pytest.fixture
def agents(committed_session: Session, seeded: Tenant) -> dict[str, AgentVersion]:
    tenant = seeded
    published = seed_ap_agents(committed_session, tenant)
    committed_session.commit()
    return {slug: version for slug, (version, _) in published.items()}


@pytest.fixture(autouse=True)
def fresh_erp() -> Iterator[None]:
    """Rebuild MeridianERP around each beat — the same reset a presenter gets by
    restarting the API container between rehearsal and performance."""
    reset_erp()
    yield
    reset_erp()


def start(client: TestClient, version: AgentVersion, run_input: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        RUNS_URL,
        json={"agent_id": str(version.agent_id), "version": version.version, "input": run_input},
        headers=HEADERS,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def trace_of(client: TestClient, run: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"{RUNS_URL}/{run['id']}/trace", headers=HEADERS)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- The story as data --------------------------------------------------------


def test_the_story_is_five_beats_in_order() -> None:
    assert [run.beat for run in DEMO_STORY] == [1, 2, 3, 4, 5]


def test_every_run_targets_a_shipped_agent() -> None:
    assert {run.agent_slug for run in DEMO_RUNS} <= set(SHIPPED_AGENT_SLUGS)


def test_every_run_names_an_invoice_that_exists_or_asks_a_question() -> None:
    """No beat invents data: the story is a curation of the frozen ERP dataset."""
    known = {invoice.id for invoice in INVOICES}
    for run in DEMO_RUNS:
        if run.invoice_id is None:
            assert "question" in run.input, run.key
        else:
            assert run.invoice_id in known, run.key
            assert run.input["invoice_id"] == run.invoice_id, run.key


def test_keys_and_labels_are_unique() -> None:
    """A presenter picks by label mid-sentence; two identical ones is a stumble."""
    assert len({run.key for run in DEMO_RUNS}) == len(DEMO_RUNS)
    assert len({run.label for run in DEMO_RUNS}) == len(DEMO_RUNS)


def test_beat_5_asks_e19s_question_verbatim() -> None:
    """The conflict beat is eval case E-19 on stage, not a paraphrase of it."""
    conflict = next(run for run in DEMO_STORY if run.beat == 5)
    assert conflict.input["question"] == E19_QUESTION


def test_beats_1_and_2_are_the_same_trusted_vendor() -> None:
    """The threshold beat only lands if nothing about the vendor changed."""
    by_id = {invoice.id: invoice for invoice in INVOICES}
    clean = by_id[next(run for run in DEMO_STORY if run.beat == 1).invoice_id or ""]
    threshold = by_id[next(run for run in DEMO_STORY if run.beat == 2).invoice_id or ""]
    assert clean.vendor_id == threshold.vendor_id
    assert threshold.amount_usd > 10000


def test_beat_3_is_a_real_duplicate_in_the_ledger() -> None:
    """R-040 fires on a fact, not on a label: another invoice carries the same number."""
    by_id = {invoice.id: invoice for invoice in INVOICES}
    duplicate = by_id[next(run for run in DEMO_STORY if run.beat == 3).invoice_id or ""]
    twins = [
        other
        for other in INVOICES
        if other.id != duplicate.id
        and other.vendor_id == duplicate.vendor_id
        and other.number == duplicate.number
    ]
    assert twins, "the duplicate beat needs a prior invoice sharing its number"


# --- The story as it actually runs --------------------------------------------


@pytest.mark.parametrize("demo", DEMO_RUNS, ids=lambda demo: demo.key)
def test_each_run_lands_what_the_script_claims(
    client: TestClient, agents: dict[str, AgentVersion], demo: DemoRun
) -> None:
    run = start(client, agents[demo.agent_slug], dict(demo.input))
    assert run["status"] == demo.expect_status, f"{demo.key}: {run['status']}"

    trace = trace_of(client, run)
    decisions = [step["decision"] for step in trace["steps"] if step["kind"] == "decision"]

    if demo.expect_action is None:
        assert decisions == [], f"{demo.key} is not supposed to reach a decision"
        return

    assert len(decisions) == 1, f"{demo.key} recorded {len(decisions)} decisions"
    assert decisions[0]["action"] == demo.expect_action
    assert decisions[0]["citations"] == list(demo.cites)


def test_the_blocked_beat_never_calls_approve_invoice(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """The beat that sells governance: the write tool is not merely refused — the agent
    never asks for it, because the rule that fired forbids the action outright."""
    demo = next(run for run in DEMO_STORY if run.beat == 3)
    trace = trace_of(client, start(client, agents[demo.agent_slug], dict(demo.input)))
    called = [
        step["tool_invocation"]["tool_ref"]
        for step in trace["steps"]
        if step["kind"] == "tool" and step["tool_invocation"] is not None
    ]
    assert not any("approve-invoice" in ref for ref in called), called


def test_the_human_beat_parks_exactly_one_action_and_sends_nothing(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    demo = next(run for run in DEMO_STORY if run.beat == 4)
    trace = trace_of(client, start(client, agents[demo.agent_slug], dict(demo.input)))
    parked = [
        step["tool_invocation"]
        for step in trace["steps"]
        if step["kind"] == "tool" and step["tool_invocation"] is not None
    ]
    assert len(parked) == 1
    assert parked[0]["status"] == "validated"
    assert parked[0]["result"] is None
