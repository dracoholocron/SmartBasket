"""
Tenant CRUD.

Cada tenant representa una organización aislada (club, academia, federación).
Es la raíz de la jerarquía: todo el resto cuelga de aquí vía ``tenant_id``.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.db.models import Tenant
from sports_data_api.db.session import get_db
from sports_data_api.schemas import TenantCreate, TenantRead, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_in: TenantCreate,
    db: AsyncSession = Depends(get_db),
):
    """Crea un nuevo tenant. ``slug`` debe ser único globalmente."""
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
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
):
    """Lista tenants (admin-only en producción)."""
    result = await db.execute(select(Tenant).offset(offset).limit(limit))
    return result.scalars().all()


@router.get("/{tenant_id}", response_model=TenantRead)
async def get_tenant(tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    db_tenant = result.scalar_one_or_none()
    if not db_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return db_tenant


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: UUID,
    tenant_in: TenantUpdate,
    db: AsyncSession = Depends(get_db),
):
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
async def delete_tenant(tenant_id: UUID, db: AsyncSession = Depends(get_db)):
    """Borra un tenant. Por FK ``ondelete=RESTRICT`` falla si tiene datos."""
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
