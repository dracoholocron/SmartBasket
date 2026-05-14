"""
Session management — async engine + dependency injection.

El engine es módulo-level (singleton) para que asyncpg reuse el pool.
En tests, el conftest sobreescribe `engine` y `SessionLocal` apuntando
a un Postgres en testcontainers.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sports_data_api.config import get_settings

_settings = get_settings()

# El runtime se conecta con `app_database_url` (rol `app_user`, no-superuser).
# Ese rol SÍ está sujeto a las policies de RLS — el aislamiento multi-tenant
# se garantiza a nivel motor, no sólo con el filtro `WHERE tenant_id` de la
# app. Alembic en cambio usa `database_url` (superuser) para correr DDL.
engine: AsyncEngine = create_async_engine(
    _settings.app_database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI dependency. Abre una session por request, hace commit si todo
    salió bien, rollback si hubo excepción.

    Uso:
        @app.get("/games")
        async def list_games(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
