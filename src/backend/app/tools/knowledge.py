"""The knowledge-retrieval tool: the one door from an agent to governed knowledge.

``search_knowledge`` is a registered tool like any other — which is the point. Retrieval
obeys exactly the same governance as an ERP write: the DNA must grant it, the gateway
validates the call, the invocation is recorded in the trace whether or not it ran
(golden rule 2), and what it may *read* is scoped by the gateway from the published
``knowledge`` block, not by anything the model says (``ToolContract.knowledge_scoped``).

What comes back is not "context" — it is evidence: every chunk carries its citation,
source, section, owner, effective date, and authority level; conflicting sources arrive
resolved-and-marked or contested-and-surfaced, never averaged (FR-D2); and every claim
the agent then makes can cite a reference a human can open (FR-D4).
"""

from typing import Any

from sqlalchemy import select

from app.db import get_sync_session_factory
from app.knowledge.embeddings import get_embedding_provider
from app.knowledge.retrieval import KnowledgeError, retrieve
from app.models import Tenant
from app.tools.contract import ToolContract, ToolExecutionError, ToolInput

SEARCH_KNOWLEDGE_REF = "meridian-knowledge-retrieve@1.0.0"
SEARCH_KNOWLEDGE_NAME = "search_knowledge"

DEFAULT_TOP_K = 8

_NULLABLE_STR: dict[str, Any] = {"type": ["string", "null"]}

_CONFLICT_PARTY: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["citation", "source_ref", "document", "authority_level", "declared_value"],
    "properties": {
        "citation": {"type": "string"},
        "source_ref": {"type": "string"},
        "document": {"type": "string"},
        "section": _NULLABLE_STR,
        "rule_id": _NULLABLE_STR,
        "authority_level": {"type": "string"},
        "declared_value": _NULLABLE_STR,
        "effective_date": _NULLABLE_STR,
        "owner": _NULLABLE_STR,
    },
}

SEARCH_KNOWLEDGE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "query",
        "collections",
        "retrieval_mode",
        "authority_order",
        "chunks",
        "conflicts",
    ],
    "properties": {
        "query": {"type": "string"},
        "collections": {"type": "array", "items": {"type": "string"}},
        "retrieval_mode": {"type": "string"},
        "authority_order": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Highest first — the scale the chunks below were ranked on.",
        },
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "chunk_id",
                    "citation",
                    "source_ref",
                    "authority_level",
                    "content",
                    "status",
                ],
                "properties": {
                    "chunk_id": {"type": "string"},
                    "citation": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "section": _NULLABLE_STR,
                    "rule_id": _NULLABLE_STR,
                    "authority_level": {"type": "string"},
                    "owner": _NULLABLE_STR,
                    "effective_date": _NULLABLE_STR,
                    "topic": _NULLABLE_STR,
                    "declared_value": _NULLABLE_STR,
                    "content": {"type": "string"},
                    "status": {"enum": ["authoritative", "superseded", "contested"]},
                    "superseded_by": _NULLABLE_STR,
                    "lexical_rank": {"type": ["integer", "null"]},
                    "semantic_rank": {"type": ["integer", "null"]},
                    "score": {"type": "number"},
                },
            },
        },
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "topic",
                    "resolved",
                    "resolution_rule",
                    "winner",
                    "superseded",
                    "explanation",
                ],
                "properties": {
                    "topic": {"type": "string"},
                    "resolved": {"type": "boolean"},
                    "resolution_rule": {"type": "string"},
                    "winner": {"oneOf": [_CONFLICT_PARTY, {"type": "null"}]},
                    "superseded": {"type": "array", "items": _CONFLICT_PARTY},
                    "explanation": {"type": "string"},
                },
            },
        },
    },
}


def _search_knowledge(call: ToolInput) -> dict[str, Any]:
    """Run one governed retrieval under the scope the gateway injected."""
    scope = call.config.get("knowledge_scope")
    if not isinstance(scope, dict):  # pragma: no cover - gateway always injects it
        raise ToolExecutionError(
            "no knowledge scope was injected; search_knowledge must be invoked through "
            "the tool gateway"
        )
    collections = [str(slug) for slug in scope.get("collections", [])]
    if not collections:
        # A grant of the tool without declared collections is a definition that cannot
        # retrieve anything; refusing beats returning an empty context that looks real.
        raise ToolExecutionError(
            "this agent's DNA grants search_knowledge but declares no knowledge "
            "collections; there is nothing it is permitted to retrieve from"
        )

    with get_sync_session_factory()() as session:
        tenant_slug = str(scope.get("tenant_slug", ""))
        tenant = session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            raise ToolExecutionError(f"unknown tenant {tenant_slug!r} in knowledge scope")
        try:
            result = retrieve(
                session,
                tenant_id=tenant.tenant_id,
                collection_slugs=collections,
                query=str(call.arguments["query"]),
                embedder=get_embedding_provider(),
                top_k=int(call.arguments.get("top_k", DEFAULT_TOP_K)),
            )
        except KnowledgeError as exc:
            raise ToolExecutionError(str(exc)) from exc

    return result.model_dump()


SEARCH_KNOWLEDGE = ToolContract(
    ref=SEARCH_KNOWLEDGE_REF,
    name=SEARCH_KNOWLEDGE_NAME,
    description=(
        "Search Meridian's governed knowledge — the SME-validated AP rules and the "
        "policy documents — with hybrid lexical+semantic retrieval. Results are ranked "
        "and conflict-checked under the authority hierarchy (sme_validated > "
        "policy_2023 > policy_2019): a superseded source is marked, never hidden, and "
        "an unresolvable conflict stops the run for a human. Cite what you use: every "
        "chunk carries the citation to put in your decision (rule ID or "
        "document#section)."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "description": "The question to retrieve for, in plain language.",
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "How many chunks to return (default 8).",
            },
        },
    },
    output_schema=SEARCH_KNOWLEDGE_OUTPUT_SCHEMA,
    handler=_search_knowledge,
    knowledge_scoped=True,
)
