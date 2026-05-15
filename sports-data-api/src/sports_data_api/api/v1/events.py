"""
Event CRUD + revisión humana — scoped por tenant (S0.4-A / S1-A).

* El pipeline inserta eventos con ``POST /bulk`` (tenant heredado del Game).
* Un revisor humano los corrige con ``PATCH /{event_id}`` o en lote con
  ``POST /bulk-review``. Cada revisión deja una fila de auditoría en
  ``event_tags`` con el snapshot antes/después.
* ``GET /{event_id}/tags`` devuelve ese historial de auditoría.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Clip, Event, EventTag, Game, Player, Team
from sports_data_api.schemas import (
    BulkEventReview,
    EventCreate,
    EventRead,
    EventReviewUpdate,
    EventTagRead,
)

router = APIRouter(prefix="/events", tags=["events"])

# Campos que un revisor puede tocar — se snapshotean en la auditoría.
_REVIEWABLE_FIELDS = (
    "event_type",
    "player_id",
    "team_id",
    "assist_player_id",
    "review_status",
    "review_notes",
    "clip_id",
)

# (campo del payload, modelo, label) para validar que los FK opcionales que
# fija un revisor pertenezcan al tenant — los FK del schema no aplican RLS.
_REF_CHECKS = (
    ("player_id", Player, "player"),
    ("team_id", Team, "team"),
    ("assist_player_id", Player, "assist_player"),
    ("clip_id", Clip, "clip"),
)


def _review_snapshot(ev: Event) -> dict:
    """Snapshot JSON-serializable de los campos reseñables de un evento."""

    def _val(v):
        if v is None:
            return None
        if hasattr(v, "value"):  # Enum
            return v.value
        return str(v)  # UUID u otros

    return {field: _val(getattr(ev, field)) for field in _REVIEWABLE_FIELDS}


async def _validate_event_refs(
    db: AsyncSession, changes: dict, tenant_id: UUID
) -> None:
    """Confirma que los FK que fija el revisor pertenezcan al tenant (404 si no)."""
    for field, model, label in _REF_CHECKS:
        ref_id = changes.get(field)
        if ref_id is None:
            continue
        obj = (
            await db.execute(
                select(model.id).where(
                    model.id == ref_id, model.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if obj is None:
            raise HTTPException(status_code=404, detail=f"{label} not found")


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


@router.post("/bulk-review")
async def bulk_review_events(
    review_in: BulkEventReview,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Tagging masivo desde la UI. Aplica la revisión a varios eventos en una
    sola transacción; cada uno deja su fila de auditoría en ``event_tags``.
    """
    event_ids = [item.event_id for item in review_in.items]
    if len(set(event_ids)) != len(event_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate event_id in bulk-review request",
        )

    rows = (
        await db.execute(
            select(Event).where(
                Event.id.in_(event_ids), Event.tenant_id == tenant_id
            )
        )
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    missing = [str(eid) for eid in event_ids if eid not in by_id]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Events not found: {', '.join(missing)}"
        )

    now = datetime.now(timezone.utc)
    for item in review_in.items:
        db_event = by_id[item.event_id]
        changes = item.model_dump(exclude_unset=True, exclude={"event_id"})
        await _validate_event_refs(db, changes, tenant_id)

        before = _review_snapshot(db_event)
        for key, value in changes.items():
            setattr(db_event, key, value)
        db_event.reviewed_by = review_in.reviewed_by
        db_event.reviewed_at = now
        after = _review_snapshot(db_event)

        db.add(
            EventTag(
                tenant_id=tenant_id,
                event_id=db_event.id,
                tagger=review_in.reviewed_by,
                before_json=before,
                after_json=after,
                notes=changes.get("review_notes"),
            )
        )

    await db.flush()
    return {"count": len(review_in.items)}


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


@router.get("/{event_id}/tags", response_model=list[EventTagRead])
async def list_event_tags(
    event_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Historial de auditoría de las revisiones de un evento (orden cronológico)."""
    event_exists = (
        await db.execute(
            select(Event.id).where(
                Event.id == event_id, Event.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if event_exists is None:
        raise HTTPException(status_code=404, detail="Event not found")

    rows = (
        await db.execute(
            select(EventTag)
            .where(EventTag.event_id == event_id, EventTag.tenant_id == tenant_id)
            .order_by(EventTag.tagged_at)
        )
    ).scalars().all()
    return rows


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


@router.patch("/{event_id}", response_model=EventRead)
async def review_event(
    event_id: UUID,
    review_in: EventReviewUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Revisión / tagging humano de un evento. Aplica los cambios, sella
    ``reviewed_by`` / ``reviewed_at``, y registra una fila de auditoría en
    ``event_tags`` con el snapshot antes/después.
    """
    db_event = (
        await db.execute(
            select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")

    changes = review_in.model_dump(exclude_unset=True, exclude={"reviewed_by"})
    await _validate_event_refs(db, changes, tenant_id)

    before = _review_snapshot(db_event)
    for key, value in changes.items():
        setattr(db_event, key, value)
    db_event.reviewed_by = review_in.reviewed_by
    db_event.reviewed_at = datetime.now(timezone.utc)
    after = _review_snapshot(db_event)

    db.add(
        EventTag(
            tenant_id=tenant_id,
            event_id=db_event.id,
            tagger=review_in.reviewed_by,
            before_json=before,
            after_json=after,
            notes=changes.get("review_notes"),
        )
    )

    await db.flush()
    await db.refresh(db_event)
    return db_event
