"""
Clip CRUD — scoped por tenant (S1-A).

Un clip es un recorte de video YA subido al storage. La API sólo registra
metadata + el ``storage_uri``; no sirve los bytes (eso lo hace nginx/CDN).

El ``tenant_id`` se hereda del Game referenciado — igual que events y
pipeline_runs. Si el clip trae ``event_id``, se sincroniza ``event.clip_id``
para mantener el vínculo bidireccional del modelo.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Clip, Event, Game
from sports_data_api.schemas import ClipCreate, ClipRead

router = APIRouter(prefix="/clips", tags=["clips"])


@router.post("", response_model=ClipRead, status_code=status.HTTP_201_CREATED)
async def create_clip(
    clip_in: ClipCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Registra un clip ya subido al storage. ``tenant_id`` se hereda del game."""
    game = (
        await db.execute(
            select(Game).where(Game.id == clip_in.game_id, Game.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if game is None:
        raise HTTPException(status_code=404, detail=f"Game {clip_in.game_id} not found")

    db_event: Event | None = None
    if clip_in.event_id is not None:
        db_event = (
            await db.execute(
                select(Event).where(
                    Event.id == clip_in.event_id, Event.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if db_event is None:
            raise HTTPException(
                status_code=404, detail=f"Event {clip_in.event_id} not found"
            )

    db_clip = Clip(tenant_id=tenant_id, **clip_in.model_dump())
    db.add(db_clip)
    await db.flush()
    await db.refresh(db_clip)

    # Vínculo bidireccional: el evento apunta de vuelta al clip.
    if db_event is not None:
        db_event.clip_id = db_clip.id
        await db.flush()

    return db_clip


@router.get("", response_model=list[ClipRead])
async def list_clips(
    game_id: UUID | None = None,
    event_id: UUID | None = None,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
    limit: int = 100,
    offset: int = 0,
):
    """Lista clips del tenant, con filtros opcionales por game/event."""
    query = (
        select(Clip)
        .where(Clip.tenant_id == tenant_id)
        .order_by(Clip.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if game_id is not None:
        query = query.where(Clip.game_id == game_id)
    if event_id is not None:
        query = query.where(Clip.event_id == event_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{clip_id}", response_model=ClipRead)
async def get_clip(
    clip_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Metadata de un clip. El ``storage_uri`` es la ubicación en el storage —
    servir un URL pre-firmado queda para cuando haya infra de S3/CDN."""
    db_clip = (
        await db.execute(
            select(Clip).where(Clip.id == clip_id, Clip.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if db_clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return db_clip
