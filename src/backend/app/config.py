"""Application settings, read from the environment.

The deployment supplies exactly one required value — ``DATABASE_URL`` — which keeps
the compose file (ADR-009) and any cloud environment configured the same way. No
secret ever lives in code or in a migration.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local default: the compose database published on the host (see deploy/docker-compose.yml).
DEFAULT_DATABASE_URL = "postgresql+psycopg://forge:forge@localhost:5432/forge"


class Settings(BaseSettings):
    """Runtime configuration for the Forge backend."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Forge Platform API"
    api_prefix: str = "/api/v1"
    database_url: str = DEFAULT_DATABASE_URL

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
