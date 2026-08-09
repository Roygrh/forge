"""Hybrid, authority-ranked retrieval — and what happens when the sources disagree.

The pipeline, in order:

1. **Lexical** search over Postgres full-text (``lexical_tsv`` + ``websearch_to_tsquery``)
   — exact terms like vendor names, invoice numbers, and dollar figures must hit (FR-D3).
2. **Semantic** search over pgvector cosine distance, behind the embedding seam of
   :mod:`app.knowledge.embeddings` — deterministic and offline by default.
3. **Fusion** by reciprocal rank (RRF): robust to the two scorers' incomparable scales,
   deterministic given the two orderings, no weights to tune or to justify.
4. **Authority + conflicts** over the fused set: chunks that answer the same question
   (same ``topic``) with different answers (different ``declared_value``) are a conflict.
   Higher authority wins (R-090) and the loser is **marked superseded, never dropped** —
   the disagreement is part of the answer. Equal authority with different answers is
   *unresolvable*: nothing wins, both are surfaced as contested, and the runtime fails
   the run closed (R-091) rather than letting anyone pick silently.
5. **Remediation** (FR-D5): every detected conflict writes one
   :class:`~app.models.RemediationItem` flagging the stale document to its owner. The
   platform does not just route around a wrong document — it starts the process of
   fixing it.

Everything here is scoped by tenant and by the collection list the caller passes, which
the tool gateway takes from the agent's published DNA — never from the model's arguments.
"""

import uuid
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge.authority import AUTHORITY_ORDER, authority_rank
from app.knowledge.embeddings import EmbeddingProvider
from app.models import KnowledgeChunk, KnowledgeCollection, RemediationItem

#: The standard RRF constant. The exact value matters little (it damps the top ranks);
#: what matters is that fusion depends only on ranks, so it is deterministic.
_RRF_K = 60

#: How many candidates each retriever contributes before fusion.
_POOL_SIZE = 12

#: The meta-rules a conflict cites: R-090 resolves, R-091 refuses to guess.
RESOLUTION_RULE = "R-090"
FAIL_CLOSED_RULE = "R-091"

#: How a retrieved chunk stands after conflict resolution.
ChunkStatus = Literal["authoritative", "superseded", "contested"]


class KnowledgeError(Exception):
    """Retrieval was asked for something the store cannot honestly serve.

    An unknown collection, an unembeddable corpus — refused with a reason, never
    approximated. The tool layer turns this into a recorded ``tool_failed`` refusal.
    """


class ConflictParty(BaseModel):
    """One side of a conflict, with everything a human needs to open the source."""

    model_config = ConfigDict(frozen=True)

    citation: str
    #: Anchored reference (``AP-Policy-2019.pdf#approval-thresholds`` or a rule's
    #: markdown anchor) — the exact place a human opens.
    source_ref: str
    #: The owning document alone — the unit remediation flags to an owner (FR-D5).
    document: str
    section: str | None
    rule_id: str | None
    authority_level: str
    declared_value: str | None
    effective_date: str | None
    owner: str | None


class Conflict(BaseModel):
    """Two or more retrieved sources answering the same question differently (FR-D2)."""

    model_config = ConfigDict(frozen=True)

    topic: str
    resolved: bool
    #: R-090 when authority resolved it; R-091 when it could not and the platform must
    #: fail closed instead of choosing.
    resolution_rule: str
    winner: ConflictParty | None
    #: Resolved: the outranked sources. Unresolved: every party — nobody outranks anybody.
    superseded: list[ConflictParty]
    explanation: str


class RetrievedChunk(BaseModel):
    """One retrieved unit as the agent (and the trace) sees it."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    citation: str
    source_ref: str
    section: str | None
    rule_id: str | None
    authority_level: str
    owner: str | None
    effective_date: str | None
    topic: str | None
    declared_value: str | None
    content: str
    #: ``authoritative`` — no conflict, or it won. ``superseded`` — it lost to a higher
    #: authority and is kept to show that it lost. ``contested`` — an unresolved conflict
    #: no authority can settle; the run fails closed.
    status: ChunkStatus
    #: Citation of the source that outranked this one, when superseded.
    superseded_by: str | None
    lexical_rank: int | None
    semantic_rank: int | None
    score: float


class RetrievalResult(BaseModel):
    """What one retrieval produced: the chunks, the conflicts, and the ranking rules."""

    model_config = ConfigDict(frozen=True)

    query: str
    collections: list[str]
    retrieval_mode: str
    authority_order: list[str]
    chunks: list[RetrievedChunk]
    conflicts: list[Conflict]


def retrieve(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    collection_slugs: list[str],
    query: str,
    embedder: EmbeddingProvider,
    top_k: int = 8,
) -> RetrievalResult:
    """Run one governed retrieval and record any conflicts it detected.

    Commits the remediation items it writes; everything else is a read.
    """
    collections = _load_collections(session, tenant_id, collection_slugs)
    collection_ids = [collection.id for collection in collections.values()]
    owners = {collection.id: collection.owner for collection in collections.values()}

    lexical = _lexical_ranks(session, tenant_id, collection_ids, query)
    semantic = _semantic_ranks(session, tenant_id, collection_ids, query, embedder)

    fused = _fuse(lexical, semantic)[:top_k]
    rows = _load_chunks(session, [chunk_id for chunk_id, _ in fused])

    conflicts, chunk_status = _detect_conflicts([rows[chunk_id] for chunk_id, _ in fused], owners)
    _flag_remediation(session, tenant_id, conflicts)

    chunks = []
    for chunk_id, score in fused:
        row = rows[chunk_id]
        status, superseded_by = chunk_status.get(row.id, ("authoritative", None))
        chunks.append(
            RetrievedChunk(
                chunk_id=str(row.id),
                citation=_citation(row),
                source_ref=row.source_ref or "unknown",
                section=row.section,
                rule_id=row.rule_id,
                authority_level=row.authority_level,
                owner=owners.get(row.collection_id),
                effective_date=row.effective_date.isoformat() if row.effective_date else None,
                topic=row.topic,
                declared_value=row.declared_value,
                content=row.content,
                status=status,
                superseded_by=superseded_by,
                lexical_rank=lexical.get(chunk_id),
                semantic_rank=semantic.get(chunk_id),
                score=round(score, 6),
            )
        )

    return RetrievalResult(
        query=query,
        collections=sorted(collections),
        retrieval_mode=(
            f"hybrid: lexical (postgres tsvector) + semantic "
            f"({embedder.name}, {embedder.dimension}d), rrf-fused"
        ),
        authority_order=list(AUTHORITY_ORDER),
        chunks=chunks,
        conflicts=conflicts,
    )


def unresolved_conflicts(result: dict[str, object]) -> list[str]:
    """The topics of any *unresolved* conflicts in a retrieval tool result.

    The runtime calls this on every executed knowledge retrieval: a non-empty answer is
    a fail-closed condition (R-091) — the platform stops rather than letting an agent
    quietly pick a side no authority settles.
    """
    conflicts = result.get("conflicts")
    if not isinstance(conflicts, list):
        return []
    return [
        str(conflict.get("topic"))
        for conflict in conflicts
        if isinstance(conflict, dict) and conflict.get("resolved") is False
    ]


# --- The two retrievers and their fusion ---------------------------------------


def _load_collections(
    session: Session, tenant_id: uuid.UUID, slugs: list[str]
) -> dict[str, KnowledgeCollection]:
    """Resolve the granted collection slugs, refusing any the store does not hold.

    A DNA that names a collection this store cannot serve must not run against a
    silently narrower scope — that would execute a less-informed agent than the one
    that was published (the same doctrine as ``unsupported_definition``).
    """
    if not slugs:
        raise KnowledgeError("no knowledge collections declared; nothing to retrieve from")

    rows = session.scalars(
        select(KnowledgeCollection).where(
            KnowledgeCollection.tenant_id == tenant_id,
            KnowledgeCollection.slug.in_(slugs),
        )
    )
    collections = {row.slug: row for row in rows}
    missing = sorted(set(slugs) - set(collections))
    if missing:
        raise KnowledgeError(
            f"unknown knowledge collection(s) {', '.join(missing)}: declared by the DNA "
            "but not present in this store"
        )
    return collections


def _lexical_ranks(
    session: Session,
    tenant_id: uuid.UUID,
    collection_ids: list[uuid.UUID],
    query: str,
) -> dict[uuid.UUID, int]:
    """Full-text candidates as ``chunk_id -> rank`` (1 = best)."""
    tsquery = func.websearch_to_tsquery("english", query)
    statement = (
        select(KnowledgeChunk.id)
        .where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.collection_id.in_(collection_ids),
            KnowledgeChunk.lexical_tsv.isnot(None),
            KnowledgeChunk.lexical_tsv.op("@@")(tsquery),
        )
        # id as tie-break so equal-scoring rows have one deterministic order.
        .order_by(func.ts_rank(KnowledgeChunk.lexical_tsv, tsquery).desc(), KnowledgeChunk.id)
        .limit(_POOL_SIZE)
    )
    return {chunk_id: rank for rank, chunk_id in enumerate(session.scalars(statement), start=1)}


def _semantic_ranks(
    session: Session,
    tenant_id: uuid.UUID,
    collection_ids: list[uuid.UUID],
    query: str,
    embedder: EmbeddingProvider,
) -> dict[uuid.UUID, int]:
    """Vector-similarity candidates as ``chunk_id -> rank`` (1 = best)."""
    [query_vector] = embedder.embed([query])
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
    statement = (
        select(KnowledgeChunk.id)
        .where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.collection_id.in_(collection_ids),
            KnowledgeChunk.embedding.isnot(None),
        )
        .order_by(distance, KnowledgeChunk.id)
        .limit(_POOL_SIZE)
    )
    return {chunk_id: rank for rank, chunk_id in enumerate(session.scalars(statement), start=1)}


def _fuse(
    lexical: dict[uuid.UUID, int], semantic: dict[uuid.UUID, int]
) -> list[tuple[uuid.UUID, float]]:
    """Reciprocal-rank fusion of the two candidate lists, best first."""
    scores: dict[uuid.UUID, float] = defaultdict(float)
    for ranks in (lexical, semantic):
        for chunk_id, rank in ranks.items():
            scores[chunk_id] += 1.0 / (_RRF_K + rank)
    # Deterministic: score, then id. Two chunks can genuinely tie (same ranks in both
    # lists is impossible, but same *sum* is not), and a tie must not reorder run to run.
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))


def _load_chunks(session: Session, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, KnowledgeChunk]:
    if not chunk_ids:
        return {}
    rows = session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids)))
    return {row.id: row for row in rows}


def _citation(row: KnowledgeChunk) -> str:
    """The citable reference for a chunk: its rule id, or its anchored source_ref."""
    return row.rule_id or (row.source_ref or "unknown")


def _document(row: KnowledgeChunk) -> str:
    """The owning document, without the section anchor."""
    return (row.source_ref or "unknown").split("#", 1)[0]


# --- Conflict detection and resolution (the heart of FR-D2) --------------------


def _detect_conflicts(
    rows: list[KnowledgeChunk], owners: dict[uuid.UUID, str | None]
) -> tuple[list[Conflict], dict[uuid.UUID, tuple[ChunkStatus, str | None]]]:
    """Find same-topic/different-answer groups and resolve them by authority.

    Returns the conflicts plus each affected chunk's ``(status, superseded_by)``.
    """
    by_topic: dict[str, list[KnowledgeChunk]] = defaultdict(list)
    for row in rows:
        if row.topic is not None and row.declared_value is not None:
            by_topic[row.topic].append(row)

    conflicts: list[Conflict] = []
    status: dict[uuid.UUID, tuple[ChunkStatus, str | None]] = {}

    for topic in sorted(by_topic):
        group = by_topic[topic]
        values = {row.declared_value for row in group}
        if len(values) < 2:
            continue  # every retrieved source agrees; nothing to resolve

        ranked = sorted(
            group, key=lambda row: (-authority_rank(row.authority_level), _citation(row))
        )
        top_rank = authority_rank(ranked[0].authority_level)
        top_values = {
            row.declared_value for row in ranked if authority_rank(row.authority_level) == top_rank
        }

        if len(top_values) == 1:
            winner = ranked[0]
            losers = [row for row in ranked if row.declared_value != winner.declared_value]
            for row in losers:
                status[row.id] = ("superseded", _citation(winner))
            conflicts.append(
                Conflict(
                    topic=topic,
                    resolved=True,
                    resolution_rule=RESOLUTION_RULE,
                    winner=_party(winner, owners),
                    superseded=[_party(row, owners) for row in losers],
                    explanation=_resolved_explanation(topic, winner, losers),
                )
            )
        else:
            # Equal authority, contradictory answers. Nothing here may choose — the
            # sources are surfaced side by side and the runtime fails the run closed.
            for row in group:
                status[row.id] = ("contested", None)
            conflicts.append(
                Conflict(
                    topic=topic,
                    resolved=False,
                    resolution_rule=FAIL_CLOSED_RULE,
                    winner=None,
                    superseded=[_party(row, owners) for row in ranked],
                    explanation=_unresolved_explanation(topic, ranked),
                )
            )

    return conflicts, status


def _party(row: KnowledgeChunk, owners: dict[uuid.UUID, str | None]) -> ConflictParty:
    return ConflictParty(
        citation=_citation(row),
        source_ref=row.source_ref or "unknown",
        document=_document(row),
        section=row.section,
        rule_id=row.rule_id,
        authority_level=row.authority_level,
        declared_value=row.declared_value,
        effective_date=row.effective_date.isoformat() if row.effective_date else None,
        owner=owners.get(row.collection_id),
    )


def _describe(row: KnowledgeChunk) -> str:
    dated = f", effective {row.effective_date.isoformat()}" if row.effective_date else ""
    return f"{_citation(row)} ({row.authority_level}{dated}) declares {row.declared_value!r}"


def _resolved_explanation(topic: str, winner: KnowledgeChunk, losers: list[KnowledgeChunk]) -> str:
    losing = "; ".join(_describe(row) for row in losers)
    return (
        f"Sources disagree on {topic!r}: {losing}, but {_describe(winner)}. "
        f"Per {RESOLUTION_RULE} the higher-authority source governs "
        f"({' > '.join(AUTHORITY_ORDER)}); the outranked source is superseded, not "
        "hidden, and has been flagged to its owner for remediation."
    )


def _unresolved_explanation(topic: str, parties: list[KnowledgeChunk]) -> str:
    listed = "; ".join(_describe(row) for row in parties)
    return (
        f"Sources of EQUAL authority disagree on {topic!r}: {listed}. No authority "
        f"outranks the other, so nothing may choose between them ({FAIL_CLOSED_RULE}): "
        "both are surfaced with their dates and the case goes to a human."
    )


# --- Remediation (FR-D5) --------------------------------------------------------


def _flag_remediation(session: Session, tenant_id: uuid.UUID, conflicts: list[Conflict]) -> None:
    """One remediation item per (topic, stale document, winner) — writes are deduped.

    The stale party of a resolved conflict is each superseded source; an unresolved
    conflict flags every party, because until a human decides, *each* document is
    potentially the wrong one.
    """
    wrote = False
    for conflict in conflicts:
        winner = conflict.winner
        for party in conflict.superseded:
            existing = session.scalar(
                select(RemediationItem.id).where(
                    RemediationItem.tenant_id == tenant_id,
                    RemediationItem.topic == conflict.topic,
                    RemediationItem.stale_source_ref == party.document,
                    (
                        RemediationItem.winning_source_ref == winner.document
                        if winner is not None
                        else RemediationItem.winning_source_ref.is_(None)
                    ),
                )
            )
            if existing is not None:
                continue
            session.add(
                RemediationItem(
                    tenant_id=tenant_id,
                    topic=conflict.topic,
                    stale_source_ref=party.document,
                    stale_authority_level=party.authority_level,
                    stale_declared_value=party.declared_value,
                    winning_source_ref=winner.document if winner else None,
                    winning_authority_level=winner.authority_level if winner else None,
                    winning_declared_value=winner.declared_value if winner else None,
                    owner=party.owner,
                    status="open",
                    detail=conflict.explanation,
                )
            )
            wrote = True
    if wrote:
        session.commit()
