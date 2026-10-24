"""Application entrypoint and FastAPI factory."""

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.engine import analytics_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hook managing background serving gateways."""
    settings = get_settings()
    logger.info("starting_up", environment=settings.environment)
    analytics_engine.initialize()

    pgwire_server: Any = None
    flight_server: Any = None

    if settings.environment != "testing":
        if settings.enable_pgwire:
            try:
                from app.serving.pgwire import PostgresWireServer

                pgwire_server = PostgresWireServer(host=settings.pgwire_host, port=settings.pgwire_port)
                pgwire_server.start()
            except Exception as exc:
                logger.warning("pgwire_start_skipped", error=str(exc))

        if settings.enable_flight:
            try:
                from app.serving.flight import FederatedFlightServer

                flight_server = FederatedFlightServer(host=settings.flight_host, port=settings.flight_port)
                flight_server.start_background()
            except Exception as exc:
                logger.warning("flight_start_skipped", error=str(exc))

    yield

    if flight_server:
        with contextlib.suppress(Exception):
            flight_server.stop()
    if pgwire_server:
        with contextlib.suppress(Exception):
            pgwire_server.stop()

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
