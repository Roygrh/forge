"""The embedding seam: semantic retrieval without a required API key.

Semantic search needs vectors; vectors usually need a provider and a key. This module is
the same arrangement ADR-005 makes for the LLM: one small interface, with a
**deterministic, offline implementation as the default**, so the whole platform — seed,
demo, and test suite — runs with no key, no network, and byte-identical results.

The default :class:`HashingEmbedder` is a signed feature-hashing (hashing-trick)
bag-of-words embedder: each token and adjacent-token bigram is hashed (MD5, so the hash
is stable across processes and platforms — Python's ``hash()`` is salted per process)
onto one of ``dimension`` signed buckets, and the vector is L2-normalised. Cosine
similarity over these vectors is term-overlap similarity: crude next to a learned
embedding, but honest, deterministic, and *free* — and the retrieval pipeline above it
(hybrid fusion, authority ranking, conflict detection) is identical either way.

**Switching providers** is configuration, not code: set ``EMBEDDING_PROVIDER`` in the
environment (default ``hashing``). A learned-embedding adapter registers itself in
:data:`_PROVIDERS` with its key handling — the retrieval SQL and the ingest pipeline do
not change, because the vector column is dimensionless (the provider owns the width) and
every chunk records the provider that embedded it is unnecessary: re-ingest re-embeds.
An unknown provider name is an error, never a silent fallback (golden rule 3).
"""

import hashlib
import math
import re
from collections.abc import Callable, Sequence
from typing import Protocol

from app.config import get_settings

_TOKEN = re.compile(r"[a-z0-9$%.,]+")


class EmbeddingProvider(Protocol):
    """What retrieval and ingestion need from an embedder — nothing more."""

    @property
    def name(self) -> str:
        """Provider name, recorded in the retrieval mode string of every result."""
        ...

    @property
    def dimension(self) -> int:
        """Vector width. The provider owns it; the schema deliberately does not."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, one vector per text, in order."""
        ...


class UnknownEmbeddingProviderError(Exception):
    """``EMBEDDING_PROVIDER`` names a provider this build does not register."""


class HashingEmbedder:
    """Deterministic signed feature-hashing embedder — the offline default."""

    def __init__(self, dimension: int = 256) -> None:
        self._dimension = dimension

    @property
    def name(self) -> str:
        return "hashing"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = _TOKEN.findall(text.lower())
        # Unigrams carry the vocabulary; bigrams carry enough phrase identity that
        # "approval threshold" and "threshold ... approval" are not the same point.
        for feature in [*tokens, *(f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False))]:
            digest = hashlib.md5(feature.encode("utf-8")).digest()  # noqa: S324 - not security
            bucket = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:
            return vector
        return [component / norm for component in vector]


#: Registered providers by configuration name. A real provider (e.g. a hosted embedding
#: API) is one entry here plus its adapter class; nothing else in the platform changes.
_PROVIDERS: dict[str, Callable[[], EmbeddingProvider]] = {
    "hashing": HashingEmbedder,
}


def get_embedding_provider() -> EmbeddingProvider:
    """Build the configured embedding provider (``EMBEDDING_PROVIDER``, default hashing)."""
    name = get_settings().embedding_provider
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise UnknownEmbeddingProviderError(
            f"EMBEDDING_PROVIDER={name!r} is not registered in this build "
            f"(available: {', '.join(sorted(_PROVIDERS))}); refusing to guess"
        )
    return factory()
