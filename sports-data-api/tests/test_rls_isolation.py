"""
Tests de aislamiento Row-Level Security (S0.4-C).

Estos tests NO pasan por los routers ni por el filtro ``WHERE tenant_id`` de
la app. Hacen ``SELECT``/``INSERT``/``UPDATE``/``DELETE`` crudos sobre las
tablas y comprueban que **Postgres por sí solo** — vía las policies de RLS —
no deja cruzar tenants.

La GUC ``app.current_tenant_id`` se setea con ``set_config(..., true)``
(equivale a ``SET LOCAL``), igual que hace ``get_tenant_db`` en el runtime.

El contraste lo da ``test_superuser_bypasses_rls``: el mismo SELECT, con el
rol superuser, ve todo. Eso es exactamente por qué la app corre como
``app_user`` y no como ``sportsdata``.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from tests.conftest import TEAM_B1, TENANT_A, TENANT_B

pytestmark = pytest.mark.asyncio


async def _set_tenant(session, tenant_id: str) -> None:
    """Replica lo que hace get_tenant_db en cada request."""
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


async def _count_teams(session) -> int:
    """count(*) sobre teams SIN filtro de app — sólo RLS decide qué se ve."""
    res = await session.execute(text("SELECT count(*) FROM teams"))
    return res.scalar_one()


async def test_app_user_sees_only_its_own_tenant(app_sessionmaker):
    """Con la GUC en el tenant A se ven 2 equipos; en el B, 1."""
    async with app_sessionmaker() as s:
        await _set_tenant(s, TENANT_A)
        assert await _count_teams(s) == 2

    async with app_sessionmaker() as s:
        await _set_tenant(s, TENANT_B)
        assert await _count_teams(s) == 1


async def test_no_tenant_set_sees_nothing(app_sessionmaker):
    """Sin GUC seteada, current_tenant_id() es NULL => 0 filas (fail closed)."""
    async with app_sessionmaker() as s:
        assert await _count_teams(s) == 0


async def test_with_check_blocks_cross_tenant_insert(app_sessionmaker):
    """Con la GUC en A, insertar una fila con tenant_id = B viola WITH CHECK."""
    async with app_sessionmaker() as s:
        await _set_tenant(s, TENANT_A)
        with pytest.raises(Exception) as exc_info:
            await s.execute(
                text(
                    "INSERT INTO teams (id, tenant_id, name, metadata) "
                    "VALUES (:id, :t, 'rogue', '{}'::jsonb)"
                ),
                {"id": str(uuid.uuid4()), "t": TENANT_B},
            )
        # El mensaje de Postgres para una violación de WITH CHECK de RLS.
        assert "row-level security" in str(exc_info.value).lower()


async def test_insert_within_own_tenant_succeeds(app_sessionmaker):
    """Con la GUC en A, insertar una fila del tenant A pasa el WITH CHECK."""
    async with app_sessionmaker() as s:
        await _set_tenant(s, TENANT_A)
        await s.execute(
            text(
                "INSERT INTO teams (id, tenant_id, name, metadata) "
                "VALUES (:id, :t, 'A-Team Three', '{}'::jsonb)"
            ),
            {"id": str(uuid.uuid4()), "t": TENANT_A},
        )
        # Visible dentro de la misma transacción del tenant A.
        assert await _count_teams(s) == 3
        # No se commitea: el rollback al cerrar la session deja la DB limpia.
        await s.rollback()


async def test_cross_tenant_update_affects_zero_rows(app_sessionmaker):
    """Con la GUC en A, un UPDATE apuntando a una fila de B no toca nada."""
    async with app_sessionmaker() as s:
        await _set_tenant(s, TENANT_A)
        res = await s.execute(
            text("UPDATE teams SET name = 'hacked' WHERE id = :id"),
            {"id": TEAM_B1},
        )
        assert res.rowcount == 0
        await s.rollback()


async def test_cross_tenant_delete_affects_zero_rows(app_sessionmaker):
    """Con la GUC en A, un DELETE apuntando a una fila de B no borra nada."""
    async with app_sessionmaker() as s:
        await _set_tenant(s, TENANT_A)
        res = await s.execute(
            text("DELETE FROM teams WHERE id = :id"),
            {"id": TEAM_B1},
        )
        assert res.rowcount == 0
        await s.rollback()


async def test_superuser_bypasses_rls(su_sessionmaker):
    """
    Contraste: el superuser ve las 3 filas SIN setear la GUC. RLS no aplica
    a superusers — por eso el runtime corre como app_user, no como este rol.
    """
    async with su_sessionmaker() as s:
        assert await _count_teams(s) == 3
