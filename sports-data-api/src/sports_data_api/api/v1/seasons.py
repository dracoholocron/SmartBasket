"""
Season CRUD — scoped por X-Tenant-ID (S0.4-A).

Todos los reads filtran por current_tenant_id; los writes ignoran cualquier
``tenant_id`` que venga del cliente y usan el del header.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Season
from sports_data_api.schemas import SeasonCreate, SeasonRead, SeasonUpdate

router = APIRouter(prefix="/seasons", tags=["seasons"])


@router.post("", response_model=SeasonRead, status_code=status.HTTP_201_CREATED)
async def create_season(
    season_in: SeasonCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if season_in.end_date < season_in.start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be >= start_date",
        )
    db_season = Season(tenant_id=tenant_id, **season_in.model_dump())
    db.add(db_season)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Season name already exists for this tenant",
        ) from exc
    await db.refresh(db_season)
    return db_season


@router.get("", response_model=list[SeasonRead])
async def list_seasons(
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
    limit: int = 100,
    offset: int = 0,
):
    query = (
        select(Season)
        .where(Season.tenant_id == tenant_id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{season_id}", response_model=SeasonRead)
async def get_season(
    season_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_season = (
        await db.execute(
            select(Season).where(Season.id == season_id, Season.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_season:
        raise HTTPException(status_code=404, detail="Season not found")
    return db_season


@router.patch("/{season_id}", response_model=SeasonRead)
async def update_season(
    season_id: UUID,
    season_in: SeasonUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_season = (
        await db.execute(
            select(Season).where(Season.id == season_id, Season.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_season:
        raise HTTPException(status_code=404, detail="Season not found")

    for key, value in season_in.model_dump(exclude_unset=True).items():
        setattr(db_season, key, value)

    if db_season.end_date < db_season.start_date:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be >= start_date",
        )

    await db.flush()
    await db.refresh(db_season)
    return db_season


@router.delete("/{season_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_season(
    season_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_season = (
        await db.execute(
            select(Season).where(Season.id == season_id, Season.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_season:
        raise HTTPException(status_code=404, detail="Season not found")

    await db.delete(db_season)
    await db.flush()
    return None
