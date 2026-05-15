"""
Tenant CRUD — gateado por root token / admin-key (S0.4-D).

Cada tenant representa una organización aislada (club, academia, federación).
Es la raíz de la jerarquía: todo el resto cuelga de aquí vía ``tenant_id``.

Autorización:
  * ``POST`` / ``GET`` (lista) / ``DELETE`` → **root-only**. Crear, listar
    todos, o borrar tenants es inherentemente una operación cross-tenant.
  * ``GET /{id}`` / ``PATCH /{id}`` → root, o un admin-key scopeado a SU
    propio tenant. Un admin-key que apunta a otro tenant recibe 404 (no se
    leakea existencia).

``tenants`` no tiene RLS (es una tabla de administración), así que el scoping
se hace acá a nivel app con el ``AdminCaller``.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._auth import AdminCaller, require_admin_or_root
from sports_data_api.db.models import Tenant
from sports_data_api.db.session import get_db
from sports_data_api.schemas import TenantCreate, TenantRead, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _require_root(caller: AdminCaller) -> None:
    """Operación cross-tenant: sólo el root token."""
    if not caller.is_root:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This operation requires the root admin token",
        )


def _require_root_or_own(caller: AdminCaller, tenant_id: UUID) -> None:
    """Root, o un admin-key del MISMO tenant. Si no, 404 (sin leak)."""
    if not caller.is_root and caller.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_in: TenantCreate,
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
):
    """Crea un nuevo tenant. ``slug`` debe ser único globalmente. Root-only."""
    _require_root(caller)

    db_tenant = Tenant(**tenant_in.model_dump())
    db.add(db_tenant)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant slug '{tenant_in.slug}' already exists",
        ) from exc
    await db.refresh(db_tenant)
    return db_tenant


@router.get("", response_model=list[TenantRead])
async def list_tenants(
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
):
    """Lista todos los tenants. Root-only."""
    _require_root(caller)
    result = await db.execute(select(Tenant).offset(offset).limit(limit))
    return result.scalars().all()


@router.get("/{tenant_id}", response_model=TenantRead)
async def get_tenant(
    tenant_id: UUID,
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
):
    _require_root_or_own(caller, tenant_id)
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    db_tenant = result.scalar_one_or_none()
    if not db_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return db_tenant


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: UUID,
    tenant_in: TenantUpdate,
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
):
    _require_root_or_own(caller, tenant_id)
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    db_tenant = result.scalar_one_or_none()
    if not db_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    for key, value in tenant_in.model_dump(exclude_unset=True).items():
        setattr(db_tenant, key, value)

    await db.commit()
    await db.refresh(db_tenant)
    return db_tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: UUID,
    caller: AdminCaller = Depends(require_admin_or_root),
    db: AsyncSession = Depends(get_db),
):
    """Borra un tenant. Por FK ``ondelete=RESTRICT`` falla si tiene datos. Root-only."""
    _require_root(caller)
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    db_tenant = result.scalar_one_or_none()
    if not db_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        await db.delete(db_tenant)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete tenant: dependent data exists",
        ) from exc
    return None
