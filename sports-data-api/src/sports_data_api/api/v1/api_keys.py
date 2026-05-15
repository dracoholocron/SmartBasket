"""
Gestión de API keys — ``/v1/admin/api-keys`` (S0.4-D).

Quién puede usar estos endpoints (``require_admin_or_root``):

  * **Root token** — el header ``X-Root-Admin-Token`` con el valor de
    ``settings.api_root_admin_token``. Es el bootstrap: sirve para mintear el
    PRIMER key de un tenant, cuando todavía no hay ningún admin-key. Opera
    cross-tenant, así que el ``tenant_id`` destino va explícito en el body /
    query param.

  * **Admin-key** — un API key con rol ``admin`` (vía ``Authorization:
    Bearer``). Sólo puede gestionar keys de SU propio tenant; el ``tenant_id``
    sale de su contexto y cualquier ``tenant_id`` del request se ignora.

``api_keys`` no tiene RLS (migración ``c3e5a7b9d1f2``), así que el scoping por
tenant de estos endpoints es a nivel app: filtro ``WHERE tenant_id`` explícito.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._auth import AdminCaller, require_admin_or_root
from sports_data_api.db.models import APIKey, Tenant
from sports_data_api.db.session import get_db
from sports_data_api.schemas import APIKeyCreate, APIKeyCreateResponse, APIKeyRead
from sports_data_api.security import generate_api_key

router = APIRouter(prefix="/admin/api-keys", tags=["admin:api-keys"])


@router.post("", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_in: APIKeyCreate,
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
):
    """
    Mintea un API key nuevo. El token completo se devuelve UNA sola vez en
    ``api_key`` — después sólo queda la metadata.
    """
    if caller.is_root:
        if key_in.tenant_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "tenant_id is required when minting with the root admin token",
            )
        target_tenant = key_in.tenant_id
        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == target_tenant))
        ).scalar_one_or_none()
        if tenant is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Tenant {target_tenant} not found"
            )
    else:
        # Admin-key: el tenant sale de su contexto; key_in.tenant_id se ignora.
        target_tenant = caller.tenant_id

    full_key, key_prefix, key_hash = generate_api_key()
    db_key = APIKey(
        tenant_id=target_tenant,
        name=key_in.name,
        role=key_in.role,
        key_hash=key_hash,
        key_prefix=key_prefix,
        expires_at=key_in.expires_at,
    )
    db.add(db_key)
    await db.flush()
    await db.refresh(db_key)

    return APIKeyCreateResponse(
        **APIKeyRead.model_validate(db_key).model_dump(),
        api_key=full_key,
    )


@router.get("", response_model=list[APIKeyRead])
async def list_api_keys(
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Lista keys del tenant (metadata, nunca el hash ni el token)."""
    if caller.is_root:
        if tenant_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "tenant_id query param is required when using the root admin token",
            )
        target_tenant = tenant_id
    else:
        target_tenant = caller.tenant_id

    rows = (
        await db.execute(
            select(APIKey)
            .where(APIKey.tenant_id == target_tenant)
            .order_by(APIKey.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return rows


@router.delete("/{key_id}", response_model=APIKeyRead)
async def revoke_api_key(
    key_id: UUID,
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoca un key (setea ``revoked_at``). Idempotente: revocar uno ya revocado
    devuelve la fila sin cambiarla. Un admin-key sólo puede revocar keys de su
    propio tenant — si apunta a otro, 404 (no se leakea existencia).
    """
    db_key = (
        await db.execute(select(APIKey).where(APIKey.id == key_id))
    ).scalar_one_or_none()
    if db_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    if not caller.is_root and db_key.tenant_id != caller.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")

    if db_key.revoked_at is None:
        db_key.revoked_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(db_key)
    return db_key
