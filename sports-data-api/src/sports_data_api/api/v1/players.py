"""
Player CRUD — scoped por X-Tenant-ID (S0.4-A).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Player
from sports_data_api.schemas import PlayerCreate, PlayerRead, PlayerUpdate

router = APIRouter(prefix="/players", tags=["players"])


@router.post("", response_model=PlayerRead, status_code=status.HTTP_201_CREATED)
async def create_player(
    player_in: PlayerCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_player = Player(tenant_id=tenant_id, **player_in.model_dump())
    db.add(db_player)
    await db.flush()
    await db.refresh(db_player)
    return db_player


@router.get("", response_model=list[PlayerRead])
async def list_players(
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
    limit: int = 100,
    offset: int = 0,
):
    query = (
        select(Player)
        .where(Player.tenant_id == tenant_id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{player_id}", response_model=PlayerRead)
async def get_player(
    player_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_player = (
        await db.execute(
            select(Player).where(Player.id == player_id, Player.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_player:
        raise HTTPException(status_code=404, detail="Player not found")
    return db_player


@router.patch("/{player_id}", response_model=PlayerRead)
async def update_player(
    player_id: UUID,
    player_in: PlayerUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_player = (
        await db.execute(
            select(Player).where(Player.id == player_id, Player.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_player:
        raise HTTPException(status_code=404, detail="Player not found")

    for key, value in player_in.model_dump(exclude_unset=True).items():
        setattr(db_player, key, value)

    await db.flush()
    await db.refresh(db_player)
    return db_player


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_player(
    player_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_player = (
        await db.execute(
            select(Player).where(Player.id == player_id, Player.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_player:
        raise HTTPException(status_code=404, detail="Player not found")

    await db.delete(db_player)
    await db.flush()
    return None
