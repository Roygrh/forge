"""Ingestion: documents and SME rules into one authority-ranked store (FR-D1).

Three collections, one scale:

* ``meridian-ap-tacit-rules`` — the SME-validated rules of
  ``docs/01-discovery/04-tacit-rules.md``, ingested from the ``rules`` table (the table,
  not the module: what is retrieved is what is in force, edits included). **Top
  authority**: a rule and a policy paragraph must be rankable against each other, and
  this collection is why they can be.
* ``ap-policy-2023`` / ``ap-policy-2019`` — the policy documents of
  :mod:`app.knowledge.documents`, chunked along their section structure.

Ingestion is idempotent the same way ``scripts/seed.py`` is for rules: a collection that
already has chunks is left alone (re-running the seed is the normal case), and
``refresh=True`` deliberately rebuilds it. Every chunk gets both retrieval
representations at write time — ``lexical_tsv`` from Postgres itself and ``embedding``
from the configured provider — so retrieval never lazily mutates the store.
"""

from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.knowledge.chunking import Chunk, chunk_document
from app.knowledge.documents import POLICY_DOCUMENTS
from app.knowledge.embeddings import EmbeddingProvider, get_embedding_provider
from app.models import Event, KnowledgeChunk, KnowledgeCollection, Tenant
from app.rules.repository import load_rule_set_sync

SME_COLLECTION_SLUG = "meridian-ap-tacit-rules"
SME_COLLECTION_NAME = "Meridian AP — SME-validated tacit rules"
SME_OWNER = "Rosa Delgado, AP Manager"
SME_SOURCE_DOCUMENT = "docs/01-discovery/04-tacit-rules.md"

#: Rosa's sign-off date (04-tacit-rules.md records it as 2026-07-XX, simulated).
SME_EFFECTIVE_DATE = date(2026, 7, 15)

#: The machine-comparable ``(topic, declared_value)`` a rule chunk carries, for the
#: rules that answer a question the policy documents also answer. This is what makes a
#: rule and a policy paragraph *comparable*, not merely rankable — conflict detection
#: needs both sides to declare a value on the same topic (FR-D2).
RULE_TOPICS: dict[str, tuple[str, str]] = {
    "R-020": ("approval_threshold", "$10,000"),
    "R-001": (
        "trusted_vendor_exception",
        "trusted-tier vendors auto-approve with valid PO within tolerance",
    ),
}


def ensure_collections(session: Session, tenant: Tenant) -> dict[str, KnowledgeCollection]:
    """Create (or refresh the metadata of) the three governed collections."""
    wanted: list[tuple[str, str, str, str]] = [
        (SME_COLLECTION_SLUG, SME_COLLECTION_NAME, "sme_validated", SME_OWNER),
        *(
            (doc.collection_slug, doc.title, doc.authority_level, doc.owner)
            for doc in POLICY_DOCUMENTS
        ),
    ]
    existing = {
        row.slug: row
        for row in session.scalars(
            select(KnowledgeCollection).where(KnowledgeCollection.tenant_id == tenant.tenant_id)
        )
    }
    collections: dict[str, KnowledgeCollection] = {}
    for slug, name, authority_level, owner in wanted:
        row = existing.get(slug)
        if row is None:
            row = KnowledgeCollection(tenant_id=tenant.tenant_id, slug=slug)
            session.add(row)
        # Metadata is the seed's to state: owner, authority, and display name follow
        # the shipped definition even on re-run. Chunk *content* is handled separately.
        row.name = name
        row.authority_level = authority_level
        row.owner = owner
        collections[slug] = row
    session.flush()
    return collections


def ingest_knowledge(
    session: Session,
    tenant: Tenant,
    *,
    refresh: bool = False,
    embedder: EmbeddingProvider | None = None,
) -> tuple[int, int]:
    """Ingest every governed collection; returns ``(chunks_written, left_alone)``.

    Reads the SME rules from the ``rules`` table, so it must run after the rules are
    seeded. Idempotent: collections that already hold chunks are skipped unless
    ``refresh`` deliberately rebuilds them.
    """
    embedder = embedder if embedder is not None else get_embedding_provider()
    collections = ensure_collections(session, tenant)

    written = 0
    left_alone = 0
    for slug, chunks in _chunk_sources(session, tenant).items():
        collection = collections[slug]
        count = session.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.collection_id == collection.id)
        )
        if count and not refresh:
            left_alone += int(count)
            continue
        if count:
            session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.collection_id == collection.id)
            )

        embeddings = embedder.embed([chunk.content for chunk in chunks])
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            session.add(
                KnowledgeChunk(
                    tenant_id=tenant.tenant_id,
                    collection_id=collection.id,
                    source_ref=f"{chunk.source_ref}#{chunk.anchor}",
                    section=chunk.section,
                    rule_id=chunk.rule_id,
                    authority_level=chunk.authority_level,
                    topic=chunk.topic,
                    declared_value=chunk.declared_value,
                    effective_date=chunk.effective_date,
                    content=chunk.content,
                    embedding=embedding,
                    # Computed by Postgres at write time so the lexical index and the
                    # content can never disagree.
                    lexical_tsv=func.to_tsvector("english", chunk.content),
                )
            )
            written += 1

    if written:
        session.add(
            Event(
                tenant_id=tenant.tenant_id,
                type="knowledge.seeded",
                actor="seed-script",
                payload={
                    "collections": sorted(collections),
                    "chunks_written": written,
                    "chunks_left_alone": left_alone,
                    "refresh": refresh,
                    "embedding_provider": embedder.name,
                },
            )
        )
    return written, left_alone


def _chunk_sources(session: Session, tenant: Tenant) -> dict[str, list[Chunk]]:
    """Every collection's chunks: policy documents chunked, rules rendered as chunks."""
    sources: dict[str, list[Chunk]] = {
        doc.collection_slug: chunk_document(doc) for doc in POLICY_DOCUMENTS
    }

    rule_set = load_rule_set_sync(session, tenant.tenant_id)
    rule_chunks: list[Chunk] = []
    for rule in rule_set.rules:
        topic, declared_value = RULE_TOPICS.get(rule.rule_id, (None, None))
        actions = sorted({clause.action for clause in rule.clauses if clause.action})
        action_note = f" Action when it fires: {', '.join(actions)}." if actions else ""
        # The topic is retrievable text, not just a comparison key: a terse rule
        # statement ("Any invoice > $10,000") does not contain the words a person asks
        # with ("approval threshold"), and the topic is exactly that vocabulary.
        topic_note = f" Topic: {topic.replace('_', ' ')}." if topic else ""
        rule_chunks.append(
            Chunk(
                source_ref=SME_SOURCE_DOCUMENT,
                section=f"Rule family: {rule.family}",
                anchor=rule.rule_id,
                content=(
                    f"{rule.rule_id} (SME-validated rule, {rule.family}): "
                    f"{rule.statement}.{action_note}{topic_note}"
                ),
                authority_level="sme_validated",
                owner=SME_OWNER,
                effective_date=SME_EFFECTIVE_DATE,
                topic=topic,
                declared_value=declared_value,
                rule_id=rule.rule_id,
            )
        )
    sources[SME_COLLECTION_SLUG] = rule_chunks
    return sources
