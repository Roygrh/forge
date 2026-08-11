"""The evaluation layer: the 20 cases as data, and the runner that scores them.

The suite is the publish gate (FR-F1, FR-F2): ``POST /agents/{id}/versions/{v}/publish``
refuses with 409 unless the version has a completed, passing :class:`~app.models.EvalRun`
for the suite its DNA declares. The cases live in the database
(:mod:`scripts.seed` writes :data:`~app.evals.catalog.CASES` into ``eval_cases``), the
runner executes them through the real runtime, and every score is a programmatic assert
(FR-F3) — no judge, no sampling, no network.
"""

from app.evals.catalog import CASES, SUITE_NAME, SUITE_REF, SUITE_SLUG, SUITE_VERSION, CaseSpec
from app.evals.runner import CaseResult, CheckResult, EvalRunner

__all__ = [
    "CASES",
    "SUITE_NAME",
    "SUITE_REF",
    "SUITE_SLUG",
    "SUITE_VERSION",
    "CaseResult",
    "CaseSpec",
    "CheckResult",
    "EvalRunner",
]
