"""The agent DNA JSON Schema — the central contract, enforced.

Golden rule 1: nothing runs that this schema has not admitted. The authoritative
document is ``docs/02-architecture/dna-schema.json``; the copy that ships inside the
package is byte-identical to it and exists only so the container image is
self-contained (the build context is ``src/backend``, which cannot reach ``docs/``).
``tests/test_dna_schema.py`` fails if the two ever diverge, so the vendored copy can
never silently drift from the source of truth (golden rule 5).

Validation happens at **write** time — a definition is admitted once, then stored. The
Pydantic model in :mod:`app.dna.model` is the typed *read* view the runtime uses.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("dna-schema.json")


class DnaValidationError(ValueError):
    """A document that is not a valid agent DNA definition.

    Carries every violation, not just the first: a rejected definition should tell its
    author everything that is wrong with it in one pass.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@lru_cache
def _validator() -> Draft202012Validator:
    """Return the process-wide compiled validator."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_dna(document: dict[str, Any]) -> None:
    """Raise :class:`DnaValidationError` unless ``document`` satisfies the schema."""
    errors = [
        # `#/identity/version: 'v1' does not match ...` — path first, so a reviewer
        # can find the offending field without reading the whole message.
        f"#/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in sorted(_validator().iter_errors(document), key=str)
    ]
    if errors:
        raise DnaValidationError(errors)
