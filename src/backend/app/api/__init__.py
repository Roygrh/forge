"""The HTTP surface contracted in ``docs/02-architecture/api/openapi.yaml``."""

from app.api.agents import router as agents_router
from app.api.approvals import router as approvals_router
from app.api.errors import ApiError, install_error_handlers
from app.api.evals import router as evals_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.metrics import router as metrics_router
from app.api.runs import router as runs_router

__all__ = [
    "ApiError",
    "agents_router",
    "approvals_router",
    "evals_router",
    "health_router",
    "install_error_handlers",
    "knowledge_router",
    "metrics_router",
    "runs_router",
]
