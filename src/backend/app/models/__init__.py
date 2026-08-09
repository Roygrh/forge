"""SQLAlchemy models — the executable form of ``docs/02-architecture/data-model.md``.

All fifteen tables of the data model are declared here and re-exported so that
Alembic sees the complete metadata from one import.
"""

from app.models.agent import Agent, AgentVersion
from app.models.approval import Approval
from app.models.base import Base
from app.models.evals import EvalCase, EvalRun, EvalSuite
from app.models.event import Event
from app.models.knowledge import KnowledgeChunk, KnowledgeCollection, RemediationItem
from app.models.rule import Rule
from app.models.run import Run, RunStep, ToolInvocation
from app.models.tenant import Tenant

__all__ = [
    "Agent",
    "AgentVersion",
    "Approval",
    "Base",
    "EvalCase",
    "EvalRun",
    "EvalSuite",
    "Event",
    "KnowledgeChunk",
    "KnowledgeCollection",
    "RemediationItem",
    "Rule",
    "Run",
    "RunStep",
    "Tenant",
    "ToolInvocation",
]
