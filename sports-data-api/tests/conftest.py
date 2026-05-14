"""
Fixtures de tests con Postgres real (testcontainers).

Levanta UN contenedor Postgres 16 para toda la sesión de tests, corre
``alembic upgrade head`` contra él (como superuser) y siembra dos tenants
con sus equipos. Después expone dos sessionmakers:

  * ``su_sessionmaker``  → conecta como superuser. SALTEA RLS. Sirve para
    verificar el estado "real" de las tablas y como contraste.
  * ``app_sessionmaker`` → conecta como ``app_user`` (no-superuser). SÍ
    está sujeto a RLS. Es el rol con el que corre la API en producción.

Los tests de aislamiento (``test_rls_isolation.py``) usan ``app_sessionmaker``
y comprueban que, sin el filtro ``WHERE tenant_id`` de la app, Postgres por
sí solo no deja ver/escribir filas de otro tenant.

Notas de implementación
-----------------------
* Se usa ``DockerContainer`` genérico + ``wait_for_logs`` + un poll con
  asyncpg en vez de ``PostgresContainer``, para no depender de qué driver
  síncrono trae instalado el extra ``testcontainers[postgres]``.
* ``get_settings`` está cacheado con ``lru_cache``; importar la app en
  cualquier test ya lo dispara con la URL por defecto, así que hay que
  ``cache_clear()`` después de setear ``DATABASE_URL`` y antes de migrar.
"""
from __future__ import annotations

import asyncio
import pathlib
import os

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

# ─── Constantes de seed ─────────────────────────────────────────────────────
TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"

TEAM_A1 = "aaaaaaa1-0000-0000-0000-000000000001"
TEAM_A2 = "aaaaaaa1-0000-0000-0000-000000000002"
TEAM_B1 = "bbbbbbb2-0000-0000-0000-000000000001"

# Debe coincidir con el password del rol creado en la migración
# b2d4f6a8c0e1_create_app_user_role.py
_APP_PWD = "app_user_dev_pwd"

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

_SU_USER = "postgres"
_SU_PWD = "postgres"
_DB_NAME = "sportsdata"


def _sa_url(host: str, port: str, user: str, pwd: str) -> str:
    """URL para SQLAlchemy (con ``+asyncpg``)."""
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{_DB_NAME}"


def _pg_url(host: str, port: str, user: str, pwd: str) -> str:
    """URL plana para ``asyncpg.connect`` (sin ``+asyncpg``)."""
    return f"postgresql://{user}:{pwd}@{host}:{port}/{_DB_NAME}"


async def _wait_ready(pg_url: str, attempts: int = 30) -> None:
    """Espera a que Postgres acepte conexiones reales (no sólo el log)."""
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            conn = await asyncpg.connect(pg_url)
            await conn.close()
            return
        except Exception as exc:  # noqa: BLE001 — readiness poll
            last_err = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"Postgres no quedó listo a tiempo: {last_err}")


async def _seed(su_url: str) -> None:
    """
    Siembra 2 tenants y 3 equipos (2 del tenant A, 1 del B).

    Corre como superuser, así que saltea RLS y puede insertar filas de
    ambos tenants directamente.
    """
    engine = create_async_engine(su_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, slug, display_name, status, metadata)
                    VALUES
                      (:a, 'tenant-a', 'Tenant A', 'active', '{}'::jsonb),
                      (:b, 'tenant-b', 'Tenant B', 'active', '{}'::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"a": TENANT_A, "b": TENANT_B},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO teams (id, tenant_id, name, metadata)
                    VALUES
                      (:t1, :a, 'A-Team One', '{}'::jsonb),
                      (:t2, :a, 'A-Team Two', '{}'::jsonb),
                      (:t3, :b, 'B-Team One', '{}'::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"t1": TEAM_A1, "t2": TEAM_A2, "t3": TEAM_B1,
                 "a": TENANT_A, "b": TENANT_B},
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def db_urls() -> dict[str, str]:
    """
    Contenedor Postgres efímero + migraciones + seed. Devuelve las dos URLs
    de SQLAlchemy: ``superuser`` y ``app``.
    """
    container = (
        DockerContainer("postgres:16-alpine")
        .with_env("POSTGRES_USER", _SU_USER)
        .with_env("POSTGRES_PASSWORD", _SU_PWD)
        .with_env("POSTGRES_DB", _DB_NAME)
        .with_exposed_ports(5432)
    )
    container.start()
    try:
        # El log aparece dos veces (init + arranque real); el poll con
        # asyncpg confirma que de verdad acepta conexiones.
        wait_for_logs(container, "database system is ready to accept connections", timeout=60)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)

        su_url = _sa_url(host, port, _SU_USER, _SU_PWD)
        app_url = _sa_url(host, port, "app_user", _APP_PWD)

        asyncio.run(_wait_ready(_pg_url(host, port, _SU_USER, _SU_PWD)))

        # Alembic lee DATABASE_URL vía get_settings(); hay que setearlo y
        # limpiar el cache antes de correr las migraciones.
        os.environ["DATABASE_URL"] = su_url
        from sports_data_api.config import get_settings

        get_settings.cache_clear()

        cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(_PROJECT_ROOT / "migrations"))
        command.upgrade(cfg, "head")

        asyncio.run(_seed(su_url))

        yield {"superuser": su_url, "app": app_url}
    finally:
        container.stop()


@pytest.fixture
async def app_sessionmaker(db_urls):
    """sessionmaker conectado como ``app_user`` (sujeto a RLS)."""
    engine = create_async_engine(db_urls["app"], poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def su_sessionmaker(db_urls):
    """sessionmaker conectado como superuser (saltea RLS)."""
    engine = create_async_engine(db_urls["superuser"], poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
