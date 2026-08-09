"""The knowledge layer: authority-ranked retrieval, conflicts, citations (Phase 4.3).

Two claims are under test, and both are the phase's reason to exist:

* Enterprise knowledge is contradictory, and a governed platform resolves conflicts by
  **declared authority** while *surfacing* that it did — never averaging, never quietly
  picking (FR-D2, R-090), and failing closed when authority cannot decide (R-091).
* Every knowledge-derived claim is traceable to a source a human can open (FR-D4), and
  every detected conflict leaves a remediation record for the stale document's owner
  (FR-D5).

The end-to-end tests run the shipped configuration — seeded documents, seeded rules,
the deterministic demo adapter, no overrides — through the real HTTP surface, exactly
as ``docker compose up`` + seed would. E-19 from ``06-eval-cases.md`` lives here.
"""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge import (
    HashingEmbedder,
    KnowledgeError,
    chunk_document,
    ingest_knowledge,
    retrieve,
)
from app.knowledge.documents import AP_POLICY_2019, AP_POLICY_2023
from app.llm import FakeAdapter, LlmGateway, ScriptedTurn, tool_turn
from app.models import (
    AgentVersion,
    KnowledgeChunk,
    KnowledgeCollection,
    RemediationItem,
    Tenant,
)
from scripts.seed import seed_ap_agents, seed_knowledge, seed_rules, seed_tenant
from tests.skeleton import publish_skeleton

RUNS_URL = "/api/v1/runs"
HEADERS = {"X-Forge-Role": "configurator"}

#: E-19's question: one both policy documents and R-020 answer — differently.
E19_QUESTION = "What is the invoice approval threshold amount requiring manager approval?"


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def client(migrated_database: None) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def seeded(committed_session: Session) -> Tenant:
    """Tenant + rules + knowledge, exactly as ``python -m scripts.seed`` installs them."""
    tenant, _ = seed_tenant(committed_session)
    seed_rules(committed_session, tenant)
    committed_session.flush()
    seed_knowledge(committed_session, tenant)
    committed_session.commit()
    return tenant


@pytest.fixture
def agents(committed_session: Session, seeded: Tenant) -> dict[str, AgentVersion]:
    """The shipped AP agents over the seeded knowledge."""
    published = seed_ap_agents(committed_session, seeded)
    committed_session.commit()
    return {slug: version for slug, (version, _) in published.items()}


@pytest.fixture
def scripted(client: TestClient) -> Iterator[Callable[..., FakeAdapter]]:
    from app.api.deps import get_llm_gateway
    from app.main import app

    def install(*turns: ScriptedTurn) -> FakeAdapter:
        adapter = FakeAdapter(script=list(turns))
        app.dependency_overrides[get_llm_gateway] = lambda: LlmGateway([adapter])
        return adapter

    yield install
    app.dependency_overrides.clear()


def run_agent(
    client: TestClient, version: AgentVersion, run_input: dict[str, Any]
) -> dict[str, Any]:
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


def retrieval_step(trace: dict[str, Any]) -> dict[str, Any]:
    """The one search_knowledge tool step of a trace."""
    steps = [
        step["tool_invocation"]
        for step in trace["steps"]
        if step["kind"] == "tool"
        and step["tool_invocation"]["tool_ref"].startswith("meridian-knowledge-retrieve")
    ]
    assert len(steps) == 1, f"expected one retrieval step, found {len(steps)}"
    found: dict[str, Any] = steps[0]
    return found


# --- Structure-aware chunking ---------------------------------------------------


def test_chunking_follows_document_structure_and_keeps_section_metadata() -> None:
    """One section, one chunk — never a blind cut — and FR-D1's metadata rides along."""
    chunks = chunk_document(AP_POLICY_2019)

    assert len(chunks) == len(AP_POLICY_2019.sections)
    thresholds = next(c for c in chunks if c.anchor == "approval-thresholds")
    assert thresholds.citation == "AP-Policy-2019.pdf#approval-thresholds"
    assert thresholds.section == "3. Approval thresholds"
    assert thresholds.owner == AP_POLICY_2019.owner
    assert thresholds.effective_date == date(2019, 3, 1)
    assert thresholds.authority_level == "policy_2019"
    assert thresholds.topic == "approval_threshold"
    assert thresholds.declared_value == "$5,000"
    # Self-describing: the chunk carries its document and heading, not bare prose.
    assert "Accounts Payable Policy (2019)" in thresholds.content
    assert "$5,000" in thresholds.content


def test_the_documents_disagree_exactly_where_the_discovery_docs_say() -> None:
    """The deliberate conflicts of 04-tacit-rules.md exist in the seeded content."""
    by_topic_2019 = {s.topic: s.declared_value for s in AP_POLICY_2019.sections if s.topic}
    by_topic_2023 = {s.topic: s.declared_value for s in AP_POLICY_2023.sections if s.topic}

    assert by_topic_2019["approval_threshold"] == "$5,000"
    assert by_topic_2023["approval_threshold"] == "$10,000"
    assert by_topic_2019["trusted_vendor_exception"] != by_topic_2023["trusted_vendor_exception"]
    assert by_topic_2019["three_way_match"] != by_topic_2023["three_way_match"]


# --- The embedding seam ---------------------------------------------------------


def test_the_hashing_embedder_is_deterministic_offline_and_normalised() -> None:
    """The default embedder needs no key and returns the same vector every time."""
    embedder = HashingEmbedder()

    [first], [second] = (
        embedder.embed(["approval threshold"]),
        embedder.embed(["approval threshold"]),
    )
    assert first == second
    assert len(first) == embedder.dimension
    assert abs(sum(x * x for x in first) - 1.0) < 1e-9  # unit length
    [other] = embedder.embed(["vendor bank details changed"])
    assert other != first


def test_an_unknown_embedding_provider_is_refused_not_defaulted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed applies to configuration too: no silent fallback embedder."""
    from app.config import get_settings
    from app.knowledge.embeddings import UnknownEmbeddingProviderError, get_embedding_provider

    monkeypatch.setattr(get_settings(), "embedding_provider", "acme-embeddings-9000")
    with pytest.raises(UnknownEmbeddingProviderError, match="acme-embeddings-9000"):
        get_embedding_provider()


# --- Ingestion -------------------------------------------------------------------


def test_ingestion_is_idempotent_and_refresh_rebuilds(
    committed_session: Session, seeded: Tenant
) -> None:
    """Re-seeding leaves chunks alone; refresh rebuilds them — the seed.py convention."""
    count = committed_session.scalar(select(func.count()).select_from(KnowledgeChunk))
    assert count and count > 0

    written, left_alone = ingest_knowledge(committed_session, seeded)
    assert written == 0
    assert left_alone == count

    written, _ = ingest_knowledge(committed_session, seeded, refresh=True)
    committed_session.commit()
    assert written == count
    assert committed_session.scalar(select(func.count()).select_from(KnowledgeChunk)) == count


def test_every_chunk_has_both_retrieval_representations(
    committed_session: Session, seeded: Tenant
) -> None:
    """Hybrid retrieval is only hybrid if the store holds both halves (FR-D3)."""
    missing = committed_session.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where((KnowledgeChunk.lexical_tsv.is_(None)) | (KnowledgeChunk.embedding.is_(None)))
    )
    assert missing == 0


def test_the_sme_rules_are_the_top_authority_collection(
    committed_session: Session, seeded: Tenant
) -> None:
    """A rule and a policy paragraph are rankable on one scale because of this row."""
    sme = committed_session.scalar(
        select(KnowledgeCollection).where(KnowledgeCollection.slug == "meridian-ap-tacit-rules")
    )
    assert sme is not None
    assert sme.authority_level == "sme_validated"
    assert sme.owner == "Rosa Delgado, AP Manager"

    r020 = committed_session.scalar(
        select(KnowledgeChunk).where(
            KnowledgeChunk.rule_id == "R-020", KnowledgeChunk.collection_id == sme.id
        )
    )
    assert r020 is not None
    assert r020.topic == "approval_threshold"
    assert r020.declared_value == "$10,000"


# --- Retrieval: hybrid, scoped, authority-ranked ---------------------------------


def all_collections() -> list[str]:
    return ["meridian-ap-tacit-rules", "ap-policy-2023", "ap-policy-2019"]


def test_lexical_retrieval_hits_exact_terms(committed_session: Session, seeded: Tenant) -> None:
    """FR-D3: exact vocabulary ("three-way match") must hit, not merely rank nearby."""
    result = retrieve(
        committed_session,
        tenant_id=seeded.tenant_id,
        collection_slugs=all_collections(),
        query="three-way match",
        embedder=HashingEmbedder(),
    )

    matching = [c for c in result.chunks if c.topic == "three_way_match"]
    assert matching, "the invoice-matching sections were not retrieved"
    assert any(c.lexical_rank is not None for c in matching), "lexical search did not hit"


def test_retrieval_is_scoped_to_the_declared_collections(
    committed_session: Session, seeded: Tenant
) -> None:
    """A retrieval sees the collections its DNA declares — nothing else."""
    result = retrieve(
        committed_session,
        tenant_id=seeded.tenant_id,
        collection_slugs=["ap-policy-2019"],
        query="approval threshold for invoices",
        embedder=HashingEmbedder(),
    )

    assert result.collections == ["ap-policy-2019"]
    assert all(c.authority_level == "policy_2019" for c in result.chunks)
    # Alone in its scope, the outdated document answers unchallenged — scope is why
    # granting an agent *only* a stale source is a definition decision, not an accident.
    assert result.conflicts == []


def test_an_unknown_collection_is_refused_not_narrowed(
    committed_session: Session, seeded: Tenant
) -> None:
    result = pytest.raises(
        KnowledgeError,
        retrieve,
        committed_session,
        tenant_id=seeded.tenant_id,
        collection_slugs=["ap-policy-2019", "no-such-collection"],
        query="anything",
        embedder=HashingEmbedder(),
    )
    assert "no-such-collection" in str(result.value)


def test_conflicting_sources_are_resolved_by_authority_and_the_loser_is_marked(
    committed_session: Session, seeded: Tenant
) -> None:
    """The heart of FR-D2: same question, different answers, authority decides visibly."""
    result = retrieve(
        committed_session,
        tenant_id=seeded.tenant_id,
        collection_slugs=all_collections(),
        query="What is the invoice approval threshold amount?",
        embedder=HashingEmbedder(),
    )

    conflict = next(c for c in result.conflicts if c.topic == "approval_threshold")
    assert conflict.resolved is True
    assert conflict.resolution_rule == "R-090"
    assert conflict.winner is not None
    assert conflict.winner.citation == "R-020"
    assert conflict.winner.authority_level == "sme_validated"
    assert conflict.winner.declared_value == "$10,000"
    superseded = {party.document for party in conflict.superseded}
    assert superseded == {"AP-Policy-2019.pdf"}
    # The conflict explains itself in words a reviewer can read.
    assert "$5,000" in conflict.explanation
    assert "R-090" in conflict.explanation

    # The losing chunk is *marked*, not dropped: still in the result, visibly outranked.
    stale = next(c for c in result.chunks if c.citation == "AP-Policy-2019.pdf#approval-thresholds")
    assert stale.status == "superseded"
    assert stale.superseded_by == "R-020"
    # The agreeing current policy is corroborating, not superseded.
    current = next(
        c for c in result.chunks if c.citation == "AP-Policy-2023.pdf#approval-thresholds"
    )
    assert current.status == "authoritative"


def test_a_detected_conflict_writes_one_remediation_item_flagged_to_the_owner(
    committed_session: Session, seeded: Tenant
) -> None:
    """FR-D5: the platform does not route around a stale document silently — it flags it."""
    for _ in range(2):  # twice: the flag must not duplicate on repeated retrievals
        retrieve(
            committed_session,
            tenant_id=seeded.tenant_id,
            collection_slugs=all_collections(),
            query="What is the invoice approval threshold amount?",
            embedder=HashingEmbedder(),
        )

    items = list(
        committed_session.scalars(
            select(RemediationItem).where(
                RemediationItem.topic == "approval_threshold",
                RemediationItem.stale_source_ref == "AP-Policy-2019.pdf",
            )
        )
    )
    assert len(items) == 1
    item = items[0]
    assert item.status == "open"
    assert item.owner == AP_POLICY_2019.owner  # flagged to the document's owner
    assert item.stale_declared_value == "$5,000"
    assert item.winning_declared_value == "$10,000"
    assert item.winning_authority_level == "sme_validated"


# --- E-19, end to end on the shipped configuration -------------------------------


def test_e19_a_policy_question_resolves_per_authority_with_the_conflict_visible(
    client: TestClient, agents: dict[str, AgentVersion]
) -> None:
    """E-19: 2019 and 2023 disagree with the SME rules; the answer follows the highest
    authority, the conflict is surfaced in the trace, and the stale document is flagged.

    Shipped configuration, no overrides: seeded documents, seeded rules, the
    deterministic demo adapter — the same run an evaluator gets from compose + seed.
    """
    run = run_agent(client, agents["invoice-validator"], {"question": E19_QUESTION})
    trace = trace_of(client, run)

    assert run["status"] == "completed"

    # Retrieval went through the tool gateway and is recorded in the trace.
    invocation = retrieval_step(trace)
    assert invocation["status"] == "executed"
    assert invocation["autonomy"] == "autonomous"
    result = invocation["result"]

    # The conflict is in the record: who disagreed, who governed, and under which rule.
    conflict = next(c for c in result["conflicts"] if c["topic"] == "approval_threshold")
    assert conflict["resolved"] is True
    assert conflict["resolution_rule"] == "R-090"
    assert conflict["winner"]["citation"] == "R-020"
    assert conflict["winner"]["authority_level"] == "sme_validated"
    assert [p["document"] for p in conflict["superseded"]] == ["AP-Policy-2019.pdf"]

    # The decision answers per the winner and cites the rule, the resolution, and the
    # documents on both sides — verifiable citations, not decoration (FR-D4).
    decisions = [s["decision"] for s in trace["steps"] if s["kind"] == "decision"]
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["action"] == "auto_approve"
    assert {"R-020", "R-090"} <= set(decision["citations"])
    assert "AP-Policy-2019.pdf#approval-thresholds" in decision["citations"]
    assert "AP-Policy-2023.pdf#approval-thresholds" in decision["citations"]
    assert decision["output"]["answer"] == "$10,000"
    assert "superseded" in decision["reasoning"]

    # Verifiability closes the loop: the cited source resolves to an openable chunk.
    cited = next(
        c for c in result["chunks"] if c["citation"] == "AP-Policy-2019.pdf#approval-thresholds"
    )
    fetched = client.get(f"/api/v1/knowledge/chunks/{cited['chunk_id']}", headers=HEADERS)
    assert fetched.status_code == 200, fetched.text
    chunk = fetched.json()
    assert chunk["citation"] == "AP-Policy-2019.pdf#approval-thresholds"
    assert "$5,000" in chunk["content"]
    assert chunk["effective_date"] == "2019-03-01"

    # And the remediation item exists for the knowledge owner (FR-D5).
    flagged = client.get("/api/v1/knowledge/remediation", headers=HEADERS).json()
    assert any(
        item["stale_source_ref"] == "AP-Policy-2019.pdf" and item["topic"] == "approval_threshold"
        for item in flagged
    )


# --- Fail closed: equal authority, contradictory ---------------------------------


@pytest.fixture
def contested_collection(committed_session: Session, seeded: Tenant) -> KnowledgeCollection:
    """A collection holding two equal-authority chunks that contradict each other.

    Deliberately its own collection so the contradiction cannot leak into the shipped
    agents' retrievals — their DNA does not declare it.
    """
    collection = committed_session.scalar(
        select(KnowledgeCollection).where(KnowledgeCollection.slug == "test-contested")
    )
    if collection is None:
        collection = KnowledgeCollection(
            tenant_id=seeded.tenant_id,
            slug="test-contested",
            name="Equal-authority fixture",
            authority_level="policy_2023",
            owner="Fixture Owner",
        )
        committed_session.add(collection)
        committed_session.flush()

        embedder = HashingEmbedder()
        for document, terms in (("Memo-A.pdf", "net 30 days"), ("Memo-B.pdf", "net 45 days")):
            content = f"Standard vendor payment terms are {terms} from invoice receipt."
            committed_session.add(
                KnowledgeChunk(
                    tenant_id=seeded.tenant_id,
                    collection_id=collection.id,
                    source_ref=f"{document}#payment-terms",
                    section=f"Payment terms ({document})",
                    authority_level="policy_2023",
                    topic="payment_terms",
                    declared_value=terms,
                    effective_date=date(2023, 6, 1),
                    content=content,
                    embedding=embedder.embed([content])[0],
                    lexical_tsv=func.to_tsvector("english", content),
                )
            )
        committed_session.commit()
    return collection


def test_equal_authority_contradiction_fails_the_run_closed(
    client: TestClient,
    committed_session: Session,
    seeded: Tenant,
    contested_collection: KnowledgeCollection,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """R-091 for knowledge: when no authority outranks the other, nobody chooses.

    The retrieval executes and its result — both sources, side by side, with dates —
    is in the trace; then the platform stops the run with ``knowledge_conflict``
    rather than letting the model pick a side on its next turn.
    """

    def with_contested(document: dict[str, Any]) -> None:
        document["knowledge"]["collections"] = ["test-contested"]
        document["tools"].append(
            {"ref": "meridian-knowledge-retrieve@1.0.0", "autonomy": "autonomous"}
        )

    version = publish_skeleton(
        committed_session, seeded, slug="skeleton-contested", mutate=with_contested
    )
    adapter = scripted(tool_turn("search_knowledge", {"query": "vendor payment terms"}))

    response = client.post(
        RUNS_URL,
        json={"agent_id": str(version.agent_id), "version": version.version, "input": {}},
        headers=HEADERS,
    )
    assert response.status_code == 202, response.text
    run = response.json()
    trace = trace_of(client, run)

    assert run["status"] == "escalated"
    assert len(adapter.calls) == 1  # the model never got a turn to pick a side

    # The retrieval executed and surfaced both parties.
    invocation = retrieval_step(trace)
    assert invocation["status"] == "executed"
    conflict = next(c for c in invocation["result"]["conflicts"] if c["topic"] == "payment_terms")
    assert conflict["resolved"] is False
    assert conflict["resolution_rule"] == "R-091"
    assert conflict["winner"] is None
    assert {p["declared_value"] for p in conflict["superseded"]} == {"net 30 days", "net 45 days"}
    assert all(
        c["status"] == "contested"
        for c in invocation["result"]["chunks"]
        if c["topic"] == "payment_terms"
    )

    # The platform stopped, with the 4.2 reason-code machinery naming why.
    governance = [s["governance"] for s in trace["steps"] if s["kind"] == "governance"]
    assert len(governance) == 1
    assert governance[0]["reason_code"] == "knowledge_conflict"
    assert "payment_terms" in governance[0]["detail"]
    assert trace["events"][-1]["payload"]["reason"] == "knowledge_conflict"

    # Both documents of an unresolved conflict are flagged for remediation, no winner.
    items = list(
        committed_session.scalars(
            select(RemediationItem).where(RemediationItem.topic == "payment_terms")
        )
    )
    assert len(items) == 2
    assert all(item.winning_source_ref is None for item in items)


# --- The gateway holds for knowledge like for everything else --------------------


def test_an_agent_without_the_grant_cannot_retrieve_knowledge(
    client: TestClient, agents: dict[str, AgentVersion], scripted: Callable[..., FakeAdapter]
) -> None:
    """Least privilege applies to reading, not only to writing: intake has no
    search_knowledge grant, so the gateway refuses the call even when asked nicely."""
    scripted(tool_turn("search_knowledge", {"query": "approval threshold"}))

    run = run_agent(client, agents["invoice-intake"], {"invoice_id": "inv-0001"})
    trace = trace_of(client, run)

    assert run["status"] == "escalated"
    tool_steps = [s["tool_invocation"] for s in trace["steps"] if s["kind"] == "tool"]
    assert len(tool_steps) == 1
    assert tool_steps[0]["status"] == "blocked"
    assert tool_steps[0]["reason_code"] == "permission_denied"
    assert "not granted" in tool_steps[0]["error"]


def test_the_model_cannot_widen_the_retrieval_scope(
    client: TestClient,
    committed_session: Session,
    seeded: Tenant,
    scripted: Callable[..., FakeAdapter],
) -> None:
    """The scope comes from the published DNA via the gateway, never from arguments.

    An agent scoped to the 2019 document alone asks a threshold question: it gets the
    2019 answer, unchallenged — and nothing the model passes as arguments can pull the
    other collections in, because ``collections`` is not part of the tool's input
    schema and an attempt to smuggle it is an argument-validation refusal.
    """

    def scoped_to_2019(document: dict[str, Any]) -> None:
        document["knowledge"]["collections"] = ["ap-policy-2019"]
        document["tools"].append(
            {"ref": "meridian-knowledge-retrieve@1.0.0", "autonomy": "autonomous"}
        )

    version = publish_skeleton(
        committed_session, seeded, slug="skeleton-scoped-2019", mutate=scoped_to_2019
    )
    scripted(
        tool_turn(
            "search_knowledge",
            {"query": "approval threshold", "collections": ["meridian-ap-tacit-rules"]},
        )
    )

    response = client.post(
        RUNS_URL,
        json={"agent_id": str(version.agent_id), "version": version.version, "input": {}},
        headers=HEADERS,
    )
    assert response.status_code == 202, response.text
    run = response.json()
    trace = trace_of(client, run)

    assert run["status"] == "escalated"
    invocation = retrieval_step(trace)
    assert invocation["status"] == "blocked"
    assert invocation["reason_code"] == "args_invalid"
    assert "collections" in invocation["error"]


# --- The read-only knowledge API -------------------------------------------------


def test_the_collections_endpoint_lists_the_authority_hierarchy(
    client: TestClient, seeded: Tenant
) -> None:
    response = client.get("/api/v1/knowledge/collections", headers=HEADERS)
    assert response.status_code == 200, response.text

    listed = {c["slug"]: c for c in response.json()}
    assert {"meridian-ap-tacit-rules", "ap-policy-2023", "ap-policy-2019"} <= set(listed)
    assert listed["meridian-ap-tacit-rules"]["authority_level"] == "sme_validated"
    assert listed["ap-policy-2023"]["authority_level"] == "policy_2023"
    assert listed["ap-policy-2019"]["authority_level"] == "policy_2019"
    # Highest authority first: the order the platform resolves conflicts in.
    slugs = [c["slug"] for c in response.json()]
    assert slugs.index("meridian-ap-tacit-rules") < slugs.index("ap-policy-2023")
    assert slugs.index("ap-policy-2023") < slugs.index("ap-policy-2019")
