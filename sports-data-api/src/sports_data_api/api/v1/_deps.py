"""
Dependencies compartidas por los routers v1.

`get_current_tenant_id` resuelve el ``tenant_id`` de la request a partir del
``AuthContext`` (S0.4-D): viene del API key del header ``Authorization:
Bearer``, o del fallback de dev ``X-Tenant-ID`` si está habilitado. Los
routers de negocio no necesitan saber de dónde sale — sólo piden el UUID.

`get_tenant_db` abre una session y setea la GUC de Postgres
``app.current_tenant_id`` ANTES de devolverla, de modo que las policies de
Row-Level Security (S0.4-B) filtren automáticamente por tenant. Los routers
de negocio deben depender de ESTA en vez de ``get_db``.

Evolución: S0.4-A scopeaba por el header X-Tenant-ID; S0.4-B agregó RLS a
nivel motor; S0.4-D mueve la fuente de verdad del tenant al API key.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._auth import AuthContext, get_auth_context
from sports_data_api.db.session import SessionLocal


async def get_current_tenant_id(
    auth: AuthContext = Depends(get_auth_context),
) -> UUID:
    """El tenant_id sale del AuthContext (API key o fallback de dev)."""
    return auth.tenant_id


async def get_tenant_db(
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> AsyncIterator[AsyncSession]:
    """
    Session scopeada al tenant del header. Setea ``app.current_tenant_id``
    con ``set_config(..., is_local => true)`` — equivale a ``SET LOCAL``,
    así que el valor vive sólo dentro de la transacción de esta request y
    se limpia solo al cerrarla.

    Se usa ``set_config()`` (función) en vez de ``SET LOCAL`` (comando)
    porque sólo la función acepta bind params; ``SET`` no se puede
    parametrizar de forma segura.
    """
    async with SessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
