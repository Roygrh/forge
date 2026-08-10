"""The human in the loop: the approval queue, its evidence, and what it reports.

Three modules, one rule between them — an action a person did not release does not run,
and running out of time is not releasing it (FR-E1..E5).
"""

from app.approvals.evidence import Evidence, Observation, build_evidence
from app.approvals.queue import (
    SYSTEM_ACTOR,
    ApprovalError,
    ApprovalNotFoundError,
    ApprovalNotPendingError,
    ApprovalQueue,
    ApprovalRecord,
    ApprovalStatus,
    why_approval_is_required,
)
from app.approvals.report import (
    MIN_DECIDED_FOR_PROMOTION,
    PROMOTION_APPROVAL_RATE,
    CategoryStats,
    autonomy_report,
)

__all__ = [
    "MIN_DECIDED_FOR_PROMOTION",
    "PROMOTION_APPROVAL_RATE",
    "SYSTEM_ACTOR",
    "ApprovalError",
    "ApprovalNotFoundError",
    "ApprovalNotPendingError",
    "ApprovalQueue",
    "ApprovalRecord",
    "ApprovalStatus",
    "CategoryStats",
    "Evidence",
    "Observation",
    "autonomy_report",
    "build_evidence",
    "why_approval_is_required",
]
