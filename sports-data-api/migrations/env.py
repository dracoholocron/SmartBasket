"""
Alembic environment — async-aware.

Conecta a Postgres usando el mismo DATABASE_URL que el resto del servicio
(via pydantic-settings) y corre migrations sobre engine asyncpg.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importar settings y Base para que las migrations conozcan los modelos.
# Cuando agreguemos modelos en S0.3, importarlos acá para que `target_metadata`
# los recoja.
from sports_data_api.config import get_settings
from sports_data_api.db.base import Base  # noqa: F401
from sports_data_api.db import models  # noqa: F401

# Configuración de Alembic
config = context.config

# Inyectar la URL del settings (no se lee de alembic.ini)
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata para autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Modo offline: solo emite SQL, no abre conexión real.
    Útil para CI/CD que genere SQL para revisión.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # `transaction_per_migration=True` hace que cada migration corra y commitee
    # en su propia transacción. Es indispensable, por ejemplo, para encadenar
    # `ALTER TYPE ... ADD VALUE` (que requiere commit) con una migration
    # posterior que use los valores nuevos en un cast.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Crea engine asyncpg y corre migrations sobre él."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
