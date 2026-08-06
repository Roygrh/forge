"""The agent definitions that ship with the platform.

The authoritative documents are in ``docs/02-architecture/dna-examples/``; the copies
under ``app/dna/agents/`` are byte-identical and exist only so the container image is
self-contained (the build context is ``src/backend``, which cannot reach ``docs/``) —
the same arrangement, and the same justification, as the vendored ``dna-schema.json``.
``tests/test_dna_schema.py`` fails if any pair diverges, so the vendoring can never
drift from the source of truth (golden rule 5).

These are *documents*, not code: the seed script writes them into ``agent_versions`` as
validated ``jsonb``, and the runtime executes what it reads back from that column.
"""

import json
from pathlib import Path
from typing import Any

AGENTS_DIR = Path(__file__).with_name("agents")

#: The three Meridian accounts-payable agents, in the order they act on an invoice:
#: intake normalises it, the validator decides on it, comms asks the vendor when the
#: validator could not.
AP_AGENT_SLUGS: tuple[str, ...] = ("invoice-intake", "invoice-validator", "invoice-comms")

#: A fourth definition that exists to be *refused*: the validator with approve_invoice
#: granted as ``forbidden``. It carries no new capability — it is the same agent minus
#: one permission — and it is shipped so that "the platform stops things, and shows you
#: why" is one click away in the catalog rather than a paragraph in a README.
GOVERNANCE_DEMO_SLUG = "invoice-validator-restricted"

#: Every definition the seed publishes.
SHIPPED_AGENT_SLUGS: tuple[str, ...] = (*AP_AGENT_SLUGS, GOVERNANCE_DEMO_SLUG)


def agent_path(slug: str) -> Path:
    """Where a shipped definition lives inside the package."""
    return AGENTS_DIR / f"{slug}.agent.json"


def load_agent_dna(slug: str) -> dict[str, Any]:
    """Read one shipped agent definition. Unvalidated — the caller validates it."""
    document: dict[str, Any] = json.loads(agent_path(slug).read_text(encoding="utf-8"))
    return document
