"""Health-check endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check() -> dict[str, str]:
    """Readiness probe — verifies the analytics engine is initialized."""
    from app.engine import analytics_engine

    try:
        result = analytics_engine.execute_query("SELECT 1 AS ping")
        _ = result.fetchone()
        return {"status": "ready"}
    except Exception as exc:
        return {"status": "not_ready", "detail": str(exc)}
