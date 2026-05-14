"""
Event CRUD — scoped por X-Tenant-ID (S0.4-A).

POST /v1/events/bulk: el game referenciado debe pertenecer al tenant del
header (404 si no). El ``tenant_id`` se hereda del Game.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Event, Game
from sports_data_api.schemas import EventCreate, EventRead

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
async def create_events_bulk(
    events_in: list[EventCreate],
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Inserción masiva de eventos producidos por el pipeline."""
    if not events_in:
        return {"count": 0}

    game_ids = {ev.game_id for ev in events_in}
    if len(game_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All events in a bulk request must share the same game_id",
        )
    game_id = next(iter(game_ids))

    game = (
        await db.execute(
            select(Game).where(Game.id == game_id, Game.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

    db_events = [
        Event(tenant_id=game.tenant_id, **ev.model_dump())
        for ev in events_in
    ]
    db.add_all(db_events)
    await db.flush()
    return {"count": len(db_events), "game_id": str(game_id)}


@router.get("", response_model=list[EventRead])
async def list_events(
    game_id: UUID | None = None,
    player_id: UUID | None = None,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
    limit: int = 100,
    offset: int = 0,
):
    """Lista eventos con filtros (todos scoped al tenant del header)."""
    query = (
        select(Event)
        .where(Event.tenant_id == tenant_id)
        .order_by(Event.game_id, Event.start_time_seconds)
        .offset(offset)
        .limit(limit)
    )
    if game_id:
        query = query.where(Event.game_id == game_id)
    if player_id:
        query = query.where(Event.player_id == player_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{event_id}", response_model=EventRead)
async def get_event(
    event_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_event = (
        await db.execute(
            select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")
    return db_event
