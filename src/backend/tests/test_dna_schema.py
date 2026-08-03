"""The DNA contract: the vendored schema, and the two views of it agreeing."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.dna import SCHEMA_PATH, Dna, DnaValidationError, validate_dna
from scripts.seed import SKELETON_DNA

DOCS_SCHEMA = Path(__file__).resolve().parents[3] / "docs" / "02-architecture" / "dna-schema.json"
INVOICE_VALIDATOR = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "02-architecture"
    / "dna-examples"
    / "invoice-validator.agent.json"
)


def test_vendored_schema_matches_the_docs_original() -> None:
    """docs/ is the source of truth; the packaged copy may never drift from it.

    The image cannot reach docs/ at build time, so the schema is vendored into the
    package. This test is the mechanism that keeps vendoring honest (golden rule 5).
    """
    assert SCHEMA_PATH.read_bytes() == DOCS_SCHEMA.read_bytes()


def test_skeleton_dna_is_valid_and_parses() -> None:
    """The seeded agent satisfies the schema and the runtime's typed read view."""
    validate_dna(SKELETON_DNA)

    dna = Dna.model_validate(SKELETON_DNA)

    assert dna.identity.slug == "skeleton-echo"
    assert dna.model.provider == "fake"
    assert [grant.autonomy for grant in dna.tools] == ["autonomous"]
    # Const-locked in the schema; the typed view pins them as literals, so a document
    # that disabled either could not even be read.
    assert dna.guardrails.require_citations is True
    assert dna.guardrails.escalate_on_no_rule_match is True


def test_the_shipped_example_validates_and_parses() -> None:
    """The Phase 2 invoice-validator example is admitted by both views.

    It is the richest DNA the repo contains — every autonomy level, real knowledge
    collections, a full rule-citing prompt — so it is what proves the Pydantic mirror
    covers the schema and not just the skeleton's corner of it.
    """
    document = json.loads(INVOICE_VALIDATOR.read_text(encoding="utf-8"))

    validate_dna(document)
    dna = Dna.model_validate(document)

    assert dna.identity.slug == "invoice-validator"
    assert {grant.autonomy for grant in dna.tools} == {
        "autonomous",
        "requires_approval",
        "forbidden",
    }


def test_fail_closed_guardrails_cannot_be_disabled() -> None:
    """A definition that turns off a const-locked guardrail is not a definition."""
    document: dict[str, Any] = json.loads(json.dumps(SKELETON_DNA))
    document["guardrails"]["require_citations"] = False

    with pytest.raises(DnaValidationError) as excinfo:
        validate_dna(document)

    assert any("require_citations" in error for error in excinfo.value.errors)


def test_validation_reports_every_violation_at_once() -> None:
    """A rejected definition tells its author everything that is wrong with it."""
    document: dict[str, Any] = json.loads(json.dumps(SKELETON_DNA))
    document["identity"]["version"] = "v1"  # not semver
    document["guardrails"]["max_steps"] = 0  # below minimum

    with pytest.raises(DnaValidationError) as excinfo:
        validate_dna(document)

    assert len(excinfo.value.errors) >= 2
