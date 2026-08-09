"""Structure-aware chunking: split on document structure, never blind fixed-size cuts.

A policy document already has a shape — sections, each with one subject, one owner, one
effective date. Chunking that ignores the shape (every N characters, sliding windows)
manufactures chunks that straddle subjects, which poisons both retrieval *and* conflict
detection: a chunk half about thresholds and half about matching has no one
``declared_value`` to compare.

So the unit of chunking is the **section**. A section that is too long to serve as one
retrieval unit is split on its paragraph boundaries — still structure, still never
mid-sentence — and every fragment keeps the whole section's metadata and anchor, so a
citation always resolves to a place a human can open.
"""

from dataclasses import dataclass
from datetime import date

from app.knowledge.documents import PolicyDocument, PolicySection
from app.rules.model import AuthorityLevel

#: A section longer than this is split on paragraph boundaries. Generous on purpose:
#: policy sections are a few hundred words, and one section is one subject — splitting
#: should be the exception a very long section forces, not the norm.
MAX_CHUNK_CHARS = 1800


@dataclass(frozen=True)
class Chunk:
    """One retrieval unit, carrying everything FR-D1 requires the store to keep."""

    source_ref: str
    section: str
    anchor: str
    content: str
    authority_level: AuthorityLevel
    owner: str
    effective_date: date
    topic: str | None = None
    declared_value: str | None = None
    rule_id: str | None = None

    @property
    def citation(self) -> str:
        """The citation string a decision carries: ``source_ref#anchor``."""
        return f"{self.source_ref}#{self.anchor}"


def chunk_document(document: PolicyDocument) -> list[Chunk]:
    """Chunk one policy document along its section structure."""
    chunks: list[Chunk] = []
    for section in document.sections:
        for body in _split_section(section):
            chunks.append(
                Chunk(
                    source_ref=document.source_ref,
                    section=section.heading,
                    anchor=section.anchor,
                    # The title and heading travel with the body so a chunk is
                    # self-describing to both retrieval and a human reading the trace.
                    content=f"{document.title}\n{section.heading}\n\n{body}",
                    authority_level=document.authority_level,
                    owner=document.owner,
                    effective_date=document.effective_date,
                    topic=section.topic,
                    declared_value=section.declared_value,
                )
            )
    return chunks


def _split_section(section: PolicySection) -> list[str]:
    """One body per chunk; paragraphs are regrouped only when the section is too long."""
    if len(section.body) <= MAX_CHUNK_CHARS:
        return [section.body]

    parts: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in section.body.split("\n\n") if p.strip()):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(candidate) > MAX_CHUNK_CHARS:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts
