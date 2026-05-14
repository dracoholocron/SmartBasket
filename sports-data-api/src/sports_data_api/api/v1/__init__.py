from __future__ import annotations

from fastapi import APIRouter

from sports_data_api.api.v1.events import router as events_router
from sports_data_api.api.v1.games import router as games_router
from sports_data_api.api.v1.pipeline_runs import router as runs_router
from sports_data_api.api.v1.players import router as players_router
from sports_data_api.api.v1.seasons import router as seasons_router
from sports_data_api.api.v1.teams import router as teams_router
from sports_data_api.api.v1.tenants import router as tenants_router

api_v1_router = APIRouter(prefix="/v1")

# Orden: jerárquico, root → leaves.
api_v1_router.include_router(tenants_router)
api_v1_router.include_router(seasons_router)
api_v1_router.include_router(teams_router)
api_v1_router.include_router(players_router)
api_v1_router.include_router(games_router)
api_v1_router.include_router(runs_router)
api_v1_router.include_router(events_router)
