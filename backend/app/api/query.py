"""Query execution endpoints connected to the FederatedExecutor engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import SecurityContext, get_security_context, require_roles
from app.cache import ResultCache
from app.catalog import catalog as default_catalog
from app.federation.executor import FederatedExecutor

router = APIRouter(
    dependencies=[
        Depends(require_roles("FinancialAnalyst", "DataEngineer", "Trader", "ComplianceAdmin"))
    ]
)

# Global execution instances
query_cache = ResultCache(default_ttl=60)
federated_executor = FederatedExecutor(catalog=default_catalog, cache=query_cache)


class QueryRequest(BaseModel):
    """SQL query payload."""

    sql: str
    limit: int = Field(default=1000, ge=1, le=100000)


class ExecutionMetricsModel(BaseModel):
    """Execution performance metrics returned with query results."""

    planning_ms: float
    subquery_ms: dict[str, float] = Field(default_factory=dict)
    join_ms: float
    total_ms: float
    row_count: int
    cache_hit: bool
    scratch_spill_enabled: bool
    applied_rls_filters: list[str] = Field(default_factory=list)
    secured_sql: str | None = None


class QueryResponse(BaseModel):
    """Structured query result."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    metrics: ExecutionMetricsModel | None = None


@router.post("/execute", response_model=QueryResponse)
async def execute_query(
    payload: QueryRequest,
    context: SecurityContext = Depends(get_security_context),  # noqa: B008
) -> QueryResponse:
    """Execute a federated SQL query with execution metrics, dynamic RLS, and caching."""
    try:
        arrow_table, metrics = await federated_executor.execute(
            payload.sql,
            limit=payload.limit,
            security_context=context,
            protocol="REST",
        )

        columns = arrow_table.column_names
        rows_pydict = arrow_table.to_pydict()
        row_count = arrow_table.num_rows

        rows: list[list[Any]] = []
        for i in range(row_count):
            rows.append([rows_pydict[col][i] for col in columns])

        metrics_model = ExecutionMetricsModel(
            planning_ms=metrics.planning_ms,
            subquery_ms=metrics.subquery_ms,
            join_ms=metrics.join_ms,
            total_ms=metrics.total_ms,
            row_count=metrics.row_count,
            cache_hit=metrics.cache_hit,
            scratch_spill_enabled=metrics.scratch_spill_enabled,
            applied_rls_filters=metrics.applied_rls_filters,
            secured_sql=metrics.secured_sql,
        )

        return QueryResponse(
            columns=columns,
            rows=rows,
            row_count=row_count,
            metrics=metrics_model,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
