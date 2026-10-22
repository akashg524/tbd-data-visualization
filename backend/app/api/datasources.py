"""Datasource management endpoints — CRUD for connections."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_datasources() -> dict[str, list]:
    """List all configured datasources."""
    # Placeholder — will be backed by a persistent store
    return {"datasources": []}


@router.post("/test")
async def test_connection() -> dict[str, str]:
    """Test a datasource connection."""
    return {"status": "not_implemented"}
