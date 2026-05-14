"""
PipelineRun CRUD — scoped por X-Tenant-ID (S0.4-A).

El cliente manda ``game_id``. La API verifica que el Game pertenezca al
tenant del header (404 si no, sin leakear existencia cross-tenant) y
hereda el ``tenant_id`` desde ahí.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api.api.v1._deps import get_current_tenant_id, get_tenant_db
from sports_data_api.db.models import Game, PipelineRun
from sports_data_api.schemas import PipelineRunCreate, PipelineRunRead, PipelineRunUpdate

router = APIRouter(prefix="/pipeline-runs", tags=["pipeline-runs"])


@router.post("", response_model=PipelineRunRead, status_code=status.HTTP_201_CREATED)
async def create_pipeline_run(
    run_in: PipelineRunCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Registra el inicio de una corrida del pipeline."""
    game = (
        await db.execute(
            select(Game).where(Game.id == run_in.game_id, Game.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail=f"Game {run_in.game_id} not found")

    db_run = PipelineRun(tenant_id=game.tenant_id, **run_in.model_dump())
    db.add(db_run)
    await db.flush()
    await db.refresh(db_run)
    return db_run


@router.get("", response_model=list[PipelineRunRead])
async def list_pipeline_runs(
    game_id: UUID | None = None,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
    limit: int = 100,
    offset: int = 0,
):
    query = (
        select(PipelineRun)
        .where(PipelineRun.tenant_id == tenant_id)
        .order_by(PipelineRun.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if game_id:
        query = query.where(PipelineRun.game_id == game_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{run_id}", response_model=PipelineRunRead)
async def get_pipeline_run(
    run_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    db_run = (
        await db.execute(
            select(PipelineRun).where(
                PipelineRun.id == run_id,
                PipelineRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not db_run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return db_run


@router.patch("/{run_id}", response_model=PipelineRunRead)
async def update_pipeline_run(
    run_id: UUID,
    run_in: PipelineRunUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Actualiza estado / métricas / finished_at al cerrar la corrida."""
    db_run = (
        await db.execute(
            select(PipelineRun).where(
                PipelineRun.id == run_id,
                PipelineRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not db_run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    for key, value in run_in.model_dump(exclude_unset=True).items():
        setattr(db_run, key, value)

    await db.flush()
    await db.refresh(db_run)
    return db_run
