"""The DNA contract: the vendored artefacts, and the two views of it agreeing."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.dna import (
    SCHEMA_PATH,
    SHIPPED_AGENT_SLUGS,
    Dna,
    DnaValidationError,
    agent_path,
    validate_dna,
)
from tests.skeleton import SKELETON_DNA

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHITECTURE = REPO_ROOT / "docs" / "02-architecture"
DOCS_SCHEMA = ARCHITECTURE / "dna-schema.json"
DOCS_AGENTS = ARCHITECTURE / "dna-examples"


def test_vendored_schema_matches_the_docs_original() -> None:
    """docs/ is the source of truth; the packaged copy may never drift from it.

    The image cannot reach docs/ at build time, so the schema is vendored into the
    package. This test is the mechanism that keeps vendoring honest (golden rule 5).
    """
    assert SCHEMA_PATH.read_bytes() == DOCS_SCHEMA.read_bytes()


@pytest.mark.parametrize("slug", SHIPPED_AGENT_SLUGS)
def test_vendored_agent_definitions_match_the_docs_originals(slug: str) -> None:
    """Same arrangement, same guarantee, for the three shipped agent definitions."""
    assert agent_path(slug).read_bytes() == (DOCS_AGENTS / f"{slug}.agent.json").read_bytes()


def test_skeleton_dna_is_valid_and_parses() -> None:
    """The runtime's own test fixture satisfies the schema and the typed read view."""
    validate_dna(SKELETON_DNA)

    dna = Dna.model_validate(SKELETON_DNA)

    assert dna.identity.slug == "skeleton-echo"
    assert dna.model.provider == "fake"
    assert [grant.autonomy for grant in dna.tools] == ["autonomous"]
    # Const-locked in the schema; the typed view pins them as literals, so a document
    # that disabled either could not even be read.
    assert dna.guardrails.require_citations is True
    assert dna.guardrails.escalate_on_no_rule_match is True


@pytest.mark.parametrize("slug", SHIPPED_AGENT_SLUGS)
def test_every_shipped_agent_validates_and_parses(slug: str) -> None:
    """A definition the platform ships is one both views admit — no exceptions."""
    document = json.loads((DOCS_AGENTS / f"{slug}.agent.json").read_text(encoding="utf-8"))

    validate_dna(document)
    dna = Dna.model_validate(document)

    assert dna.identity.slug == slug
    assert dna.identity.tenant_id == "meridian-supply-co"
    assert dna.guardrails.require_citations is True


def test_the_validator_declares_all_three_autonomy_levels() -> None:
    """The richest definition in the repo: least privilege stated at every level.

    Reads are autonomous, the vendor contact needs a human, and payment scheduling is
    explicitly forbidden — recorded as a refusal so a reviewer can see it was
    considered rather than merely omitted (FR-C3).
    """
    dna = Dna.model_validate(
        json.loads((DOCS_AGENTS / "invoice-validator.agent.json").read_text(encoding="utf-8"))
    )

    autonomy = {grant.ref: grant.autonomy for grant in dna.tools}

    assert autonomy["meridian-erp-read-invoice@1.0.0"] == "autonomous"
    assert autonomy["meridian-ap-rules-query@1.0.0"] == "autonomous"
    assert autonomy["meridian-erp-request-info-from-vendor@1.0.0"] == "requires_approval"
    assert autonomy["meridian-erp-schedule-payment@1.0.0"] == "forbidden"
    # The spend ceiling is declared in the definition, not hidden in a prompt.
    approve = dna.grant_for("meridian-erp-approve-invoice@1.0.0")
    assert approve is not None
    assert approve.config == {"max_amount_usd": 10000}


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
