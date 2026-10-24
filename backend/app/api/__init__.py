"""API router aggregation."""

from fastapi import APIRouter

from app.api.datasources import router as datasources_router
from app.api.health import router as health_router
from app.api.launchers import router as launchers_router
from app.api.odata import router as odata_router
from app.api.query import router as query_router
from app.api.views import router as views_router
from app.serving.export import router as export_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(datasources_router, prefix="/datasources", tags=["datasources"])
router.include_router(query_router, prefix="/query", tags=["query"])
router.include_router(views_router, prefix="/views", tags=["views"])
router.include_router(odata_router, prefix="/odata", tags=["odata"])
router.include_router(launchers_router, prefix="/launchers", tags=["launchers"])
router.include_router(export_router, prefix="/export", tags=["export"])
