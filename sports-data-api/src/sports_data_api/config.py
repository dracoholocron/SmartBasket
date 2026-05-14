"""
Settings (pydantic-settings).

Single source of truth para configuración. Lee de:
  1. Variables de entorno
  2. Archivo `.env` (si existe en cwd)

Pattern:
    from sports_data_api.config import get_settings
    settings = get_settings()
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la app, validada al boot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── Database ───────────────────────────────────────────────────────────
    # Debe usar driver asyncpg para que SQLAlchemy use el engine async.
    #
    # Hay DOS URLs a propósito (S0.4-C):
    #   * database_url     → rol `sportsdata` (SUPERUSER). Lo usa Alembic
    #     para correr DDL. Los superusers SALTEAN RLS.
    #   * app_database_url → rol `app_user` (no-superuser, NOBYPASSRLS). Lo
    #     usa el runtime de la API. Está sujeto a las policies de RLS, así
    #     que el aislamiento multi-tenant se garantiza a nivel motor.
    database_url: str = Field(
        default="postgresql+asyncpg://sportsdata:sportsdata@localhost:5432/sportsdata",
        description="URL de Postgres (rol superuser) — usada por Alembic para DDL.",
    )
    app_database_url: str = Field(
        default="postgresql+asyncpg://app_user:app_user_dev_pwd@localhost:5432/sportsdata",
        description="URL de Postgres (rol app_user, sujeto a RLS) — usada por el runtime.",
    )

    # ─── Logs ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")

    # ─── Auth ──────────────────────────────────────────────────────────────
    # Token de root para provisionar tenants (out-of-band).
    # NO se debe usar para operaciones normales del API.
    api_root_admin_token: str = Field(default="change-me-in-dev")


@lru_cache
def get_settings() -> Settings:
    """Singleton de settings cacheado."""
    return Settings()
