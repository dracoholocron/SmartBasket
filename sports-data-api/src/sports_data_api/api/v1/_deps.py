"""
Dependencies compartidas por los routers v1.

`get_current_tenant_id` extrae el header ``X-Tenant-ID`` de la request y lo
valida como UUID. Si falta, FastAPI/Pydantic devuelven 422 automáticamente
porque el ``Header(...)`` lo declara como obligatorio.

`get_tenant_db` abre una session y setea la GUC de Postgres
``app.current_tenant_id`` ANTES de devolverla, de modo que las policies de
Row-Level Security (S0.4-B) filtren automáticamente por tenant. Los routers
de negocio deben depender de ESTA en vez de ``get_db``.

En S0.4-A el header es el ÚNICO mecanismo de scoping a nivel app; en S0.4-B
RLS lo respalda a nivel motor. En S0.4-D (Bearer auth) el tenant_id se
resolverá desde el API key y este header quedará sólo como atajo de dev.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.db.session import SessionLocal


async def get_current_tenant_id(
    x_tenant_id: UUID = Header(
        ...,
        alias="X-Tenant-ID",
        description="UUID del tenant que está haciendo la request.",
    ),
) -> UUID:
    return x_tenant_id


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
