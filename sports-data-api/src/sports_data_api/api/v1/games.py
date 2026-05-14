"""
Game CRUD — scoped por X-Tenant-ID (S0.4-A).

Para validar referencias cruzadas (home_team, away_team, season) confirmamos
que pertenezcan al mismo tenant del header — 404 si no, para no leakear
existencia cross-tenant.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Game, Season, Team
from sports_data_api.schemas import GameCreate, GameRead, GameUpdate

router = APIRouter(prefix="/games", tags=["games"])


async def _check_ref_belongs_to_tenant(
    db: AsyncSession, model, ref_id: UUID | None, tenant_id: UUID, label: str
) -> None:
    """Confirma que un FK opcional/obligatorio pertenezca al tenant actual."""
    if ref_id is None:
        return
    obj = (
        await db.execute(
            select(model).where(model.id == ref_id, model.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail=f"{label} not found")


@router.post("", response_model=GameRead, status_code=status.HTTP_201_CREATED)
async def create_game(
    game_in: GameCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    if game_in.home_team_id == game_in.away_team_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="home_team_id and away_team_id must be different",
        )
    await _check_ref_belongs_to_tenant(db, Team, game_in.home_team_id, tenant_id, "home_team")
    await _check_ref_belongs_to_tenant(db, Team, game_in.away_team_id, tenant_id, "away_team")
    await _check_ref_belongs_to_tenant(db, Season, game_in.season_id, tenant_id, "season")

    db_game = Game(tenant_id=tenant_id, **game_in.model_dump())
    db.add(db_game)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Game external_id already exists for this tenant",
        ) from exc
    await db.refresh(db_game)
    return db_game


@router.get("", response_model=list[GameRead])
async def list_games(
    season_id: UUID | None = None,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
    limit: int = 100,
    offset: int = 0,
):
    query = (
        select(Game)
        .where(Game.tenant_id == tenant_id)
        .offset(offset)
        .limit(limit)
    )
    if season_id:
        query = query.where(Game.season_id == season_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{game_id}", response_model=GameRead)
async def get_game(
    game_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_game = (
        await db.execute(
            select(Game).where(Game.id == game_id, Game.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_game:
        raise HTTPException(status_code=404, detail="Game not found")
    return db_game


@router.patch("/{game_id}", response_model=GameRead)
async def update_game(
    game_id: UUID,
    game_in: GameUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_game = (
        await db.execute(
            select(Game).where(Game.id == game_id, Game.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_game:
        raise HTTPException(status_code=404, detail="Game not found")

    # Si tocan season_id, verificar que el nuevo season siga siendo del tenant.
    if game_in.season_id is not None:
        await _check_ref_belongs_to_tenant(db, Season, game_in.season_id, tenant_id, "season")

    for key, value in game_in.model_dump(exclude_unset=True).items():
        setattr(db_game, key, value)

    await db.flush()
    await db.refresh(db_game)
    return db_game


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game(
    game_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_game = (
        await db.execute(
            select(Game).where(Game.id == game_id, Game.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_game:
        raise HTTPException(status_code=404, detail="Game not found")

    await db.delete(db_game)
    await db.flush()
    return None
