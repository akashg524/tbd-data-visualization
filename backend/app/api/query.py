"""Query execution endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.engine import analytics_engine

router = APIRouter()


class QueryRequest(BaseModel):
    """SQL query payload."""
    sql: str
    limit: int = 1000


class QueryResponse(BaseModel):
    """Structured query result."""
    columns: list[str]
    rows: list[list]
    row_count: int


@router.post("/execute", response_model=QueryResponse)
async def execute_query(payload: QueryRequest) -> QueryResponse:
    """Execute a SQL query against the analytics engine."""
    try:
        relation = analytics_engine.execute_query(payload.sql)
        columns = [desc[0] for desc in relation.description]
        rows = relation.fetchmany(payload.limit)
        return QueryResponse(
            columns=columns,
            rows=[list(row) for row in rows],
            row_count=len(rows),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
