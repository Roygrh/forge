"""The knowledge layer: governed documents, authority-ranked retrieval, conflicts.

Enterprise knowledge is contradictory — Meridian's own policy PDFs disagree with each
other and with how AP actually works (Rosa: "if your system follows the PDF blindly, it
will be wrong by lunchtime"). This package is Forge's answer to that fact:

* :mod:`app.knowledge.documents` — the policy documents as seeded, *deliberately
  conflicting* content, every section carrying owner, effective date, and authority.
* :mod:`app.knowledge.chunking` — structure-aware chunking: sections, never blind cuts.
* :mod:`app.knowledge.embeddings` — the embedding seam; deterministic and offline by
  default, exactly as the FakeAdapter is for the LLM.
* :mod:`app.knowledge.ingest` — idempotent seeding of collections and chunks, including
  the SME-validated rules as the top-authority collection.
* :mod:`app.knowledge.retrieval` — hybrid lexical+semantic search, authority-ranked
  conflict resolution (R-090), fail-closed surfacing when authority cannot resolve
  (R-091), and the remediation record every conflict leaves behind (FR-D5).

Agents reach all of this through exactly one door: the ``search_knowledge`` tool in
:mod:`app.tools.knowledge`, scoped by their DNA's ``knowledge`` block at the gateway.
"""

from app.knowledge.authority import AUTHORITY_ORDER, AUTHORITY_RANK, authority_rank
from app.knowledge.chunking import Chunk, chunk_document
from app.knowledge.documents import POLICY_DOCUMENTS, PolicyDocument, PolicySection
from app.knowledge.embeddings import (
    EmbeddingProvider,
    HashingEmbedder,
    UnknownEmbeddingProviderError,
    get_embedding_provider,
)
from app.knowledge.ingest import SME_COLLECTION_SLUG, ensure_collections, ingest_knowledge
from app.knowledge.retrieval import (
    Conflict,
    ConflictParty,
    KnowledgeError,
    RetrievalResult,
    RetrievedChunk,
    retrieve,
    unresolved_conflicts,
)

__all__ = [
    "AUTHORITY_ORDER",
    "AUTHORITY_RANK",
    "POLICY_DOCUMENTS",
    "SME_COLLECTION_SLUG",
    "Chunk",
    "Conflict",
    "ConflictParty",
    "EmbeddingProvider",
    "HashingEmbedder",
    "KnowledgeError",
    "PolicyDocument",
    "PolicySection",
    "RetrievalResult",
    "RetrievedChunk",
    "UnknownEmbeddingProviderError",
    "authority_rank",
    "chunk_document",
    "ensure_collections",
    "get_embedding_provider",
    "ingest_knowledge",
    "retrieve",
    "unresolved_conflicts",
]
