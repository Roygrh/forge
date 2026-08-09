"""Application settings, read from the environment.

The deployment supplies exactly one required value — ``DATABASE_URL`` — which keeps
the compose file (ADR-009) and any cloud environment configured the same way. No
secret ever lives in code or in a migration.

``ANTHROPIC_API_KEY`` is optional and read here only: it is the one place a provider
credential exists (ADR-005), and nothing in the platform runs without it.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Local default: the compose database published on the host (see deploy/docker-compose.yml).
DEFAULT_DATABASE_URL = "postgresql+psycopg://forge:forge@localhost:5432/forge"


class Settings(BaseSettings):
    """Runtime configuration for the Forge backend."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Forge Platform API"
    api_prefix: str = "/api/v1"
    database_url: str = DEFAULT_DATABASE_URL

    # ADR-005: the gateway configuration holds the only copy of a provider key. It is
    # never in a DNA document, a tool, or the frontend. Absent by default — the demo
    # and the whole test suite run on the deterministic fake adapter.
    anthropic_api_key: str | None = None

    # The embedding provider behind semantic retrieval (app/knowledge/embeddings.py).
    # "hashing" is deterministic, offline, and free — the demo needs no key, exactly as
    # it needs none for the LLM. A learned-embedding provider is registered there and
    # named here; an unknown name refuses to start retrieval rather than falling back.
    embedding_provider: str = "hashing"

    # The SPA (ADR-007) is served from its own origin — Vite's dev server locally, a
    # separate container in compose (ADR-009) — so the browser needs these allowed
    # explicitly. Defaults cover the documented dev ports and nothing else: a wildcard
    # would be one fewer line and a worse answer.
    #
    # ``NoDecode`` turns off pydantic-settings' own JSON decoding for this field, which
    # would otherwise demand ``["http://a","http://b"]`` in the environment — a poor
    # thing to write in a compose file, and a parse error before any validator of ours
    # gets a look at it. The comma-separated form below is parsed instead.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept ``CORS_ORIGINS`` as a comma-separated list of origins."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _pin_psycopg_driver(cls, value: str) -> str:
        """Normalise ``postgresql://`` to ``postgresql+psycopg://``.

        SQLAlchemy's default PostgreSQL driver is psycopg2, which Forge does not
        install. Rewriting a bare scheme here means a hand-written or
        platform-provided URL cannot silently fail at connection time.
        """
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, parsed once."""
    return Settings()
