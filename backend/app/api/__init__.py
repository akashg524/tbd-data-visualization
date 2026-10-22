"""API router aggregation."""

from fastapi import APIRouter

from app.api.datasources import router as datasources_router
from app.api.health import router as health_router
from app.api.query import router as query_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(datasources_router, prefix="/datasources", tags=["datasources"])
router.include_router(query_router, prefix="/query", tags=["query"])
