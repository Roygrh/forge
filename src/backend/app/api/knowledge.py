"""Knowledge endpoints — read-only: collections, chunks, and remediation items.

Read-only is deliberate. Agents retrieve knowledge through the tool gateway, never
through HTTP; these endpoints exist for *humans* — the collection list shows what the
store governs and under which authority, the chunk endpoint makes a citation openable
(FR-D4: a decision cites a chunk, a reviewer fetches the chunk and reads the source),
and the remediation list is where flagged conflicts wait for their owners (FR-D5).
Ingestion stays in the seed script for now: the contracted ingest endpoint arrives with
a real job model, not as a synchronous shim pretending to be one.
"""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import ActorDep
from app.api.errors import ApiError
from app.api.schemas import (
    KnowledgeChunkResponse,
    KnowledgeCollectionResponse,
    RemediationItemResponse,
)
from app.db import SessionDep
from app.governance import Permission
from app.models import KnowledgeChunk, KnowledgeCollection, RemediationItem

router = APIRouter(tags=["Knowledge"])


@router.get(
    "/knowledge/collections",
    response_model=list[KnowledgeCollectionResponse],
    summary="List knowledge collections with authority levels",
)
async def list_collections(
    session: SessionDep, actor: ActorDep
) -> list[KnowledgeCollectionResponse]:
    """Every governed collection, highest authority first, then by slug."""
    actor.require(Permission.READ)
    rows = await session.scalars(select(KnowledgeCollection).order_by(KnowledgeCollection.slug))
    ordered = sorted(
        rows,
        key=lambda row: (
            {"sme_validated": 0, "policy_2023": 1, "policy_2019": 2}.get(row.authority_level, 3),
            row.slug,
        ),
    )
    return [KnowledgeCollectionResponse.of(row) for row in ordered]


@router.get(
    "/knowledge/chunks/{chunk_id}",
    response_model=KnowledgeChunkResponse,
    summary="Get a knowledge chunk with its authority level and citation",
)
async def get_chunk(
    chunk_id: uuid.UUID, session: SessionDep, actor: ActorDep
) -> KnowledgeChunkResponse:
    """Resolve one chunk — the endpoint that makes a citation verifiable (FR-D4)."""
    actor.require(Permission.READ)
    chunk = await session.get(KnowledgeChunk, chunk_id)
    if chunk is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "knowledge_chunk_not_found", f"no chunk {chunk_id}"
        )
    return KnowledgeChunkResponse.of(chunk)


@router.get(
    "/knowledge/remediation",
    response_model=list[RemediationItemResponse],
    summary="List flagged knowledge conflicts awaiting their owners",
)
async def list_remediation(session: SessionDep, actor: ActorDep) -> list[RemediationItemResponse]:
    """Every remediation item, newest first — the stale-document work queue (FR-D5)."""
    actor.require(Permission.READ)
    rows = await session.scalars(
        select(RemediationItem).order_by(RemediationItem.created_at.desc(), RemediationItem.id)
    )
    return [RemediationItemResponse.of(row) for row in rows]
