"""
Team CRUD — scoped por X-Tenant-ID (S0.4-A).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Team
from sports_data_api.schemas import TeamCreate, TeamRead, TeamUpdate

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(
    team_in: TeamCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_team = Team(tenant_id=tenant_id, **team_in.model_dump())
    db.add(db_team)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Team external_id already exists for this tenant",
        ) from exc
    await db.refresh(db_team)
    return db_team


@router.get("", response_model=list[TeamRead])
async def list_teams(
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
    limit: int = 100,
    offset: int = 0,
):
    query = (
        select(Team)
        .where(Team.tenant_id == tenant_id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(
    team_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_team = (
        await db.execute(
            select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_team:
        raise HTTPException(status_code=404, detail="Team not found")
    return db_team


@router.patch("/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: UUID,
    team_in: TeamUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_team = (
        await db.execute(
            select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_team:
        raise HTTPException(status_code=404, detail="Team not found")

    for key, value in team_in.model_dump(exclude_unset=True).items():
        setattr(db_team, key, value)

    await db.flush()
    await db.refresh(db_team)
    return db_team


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_team = (
        await db.execute(
            select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_team:
        raise HTTPException(status_code=404, detail="Team not found")

    await db.delete(db_team)
    await db.flush()
    return None
