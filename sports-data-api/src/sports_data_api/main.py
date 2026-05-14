"""
FastAPI app factory.

En S0.1 sólo expone health checks. En S0.3-S0.4 se montan los routers
de entidades del modelo.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sports_data_api import __version__
from sports_data_api.api.v1 import api_v1_router
from sports_data_api.config import get_settings
from sports_data_api.db.session import engine, get_db


def _configure_logging(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), serialize=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.log_level)
    logger.info(f"sports-data-api {__version__} starting...")
    logger.info(f"DB URL host: {settings.app_database_url.rsplit('@', 1)[-1]}")
    yield
    logger.info("sports-data-api shutting down...")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="sports-data-api",
        version=__version__,
        description="Multi-tenant API for sports event data — SmartBasket Phase 2.",
        lifespan=lifespan,
    )

    # Routers
    app.include_router(api_v1_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        """Liveness: el proceso responde."""
        return {"status": "ok", "version": __version__}

    @app.get("/health/db", tags=["health"])
    async def health_db(db: AsyncSession = Depends(get_db)) -> dict:
        """Readiness: la DB responde."""
        result = await db.execute(text("SELECT 1"))
        value = result.scalar_one()
        return {"status": "ok", "result": value}

    return app


# Uvicorn entrypoint: `uvicorn sports_data_api.main:app`
app = create_app()
