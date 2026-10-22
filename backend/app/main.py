"""Application entrypoint and FastAPI factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.engine import analytics_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hook."""
    settings = get_settings()
    logger.info("starting_up", environment=settings.environment)
    analytics_engine.initialize()
    yield
    analytics_engine.shutdown()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    application = FastAPI(
        title="TBD Data Visualization API",
        version="0.1.0",
        description="SQL-first financial data visualization platform",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routers
    from app.api import router as api_router

    application.include_router(api_router, prefix="/api/v1")

    return application


app = create_app()
