"""RESTful Table Views API delivering structured JSON, CSV, and metadata exploration."""

from __future__ import annotations

import io
import re
from typing import Any

import pyarrow.csv as pcsv
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.query import federated_executor
from app.catalog import catalog as default_catalog

router = APIRouter()

IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class ViewSummary(BaseModel):
    """Summary metadata for an available table view."""

    catalog: str
    schema_name: str
    table_name: str
    full_path: str
    format: str | None = None
    url: str


class ViewListResponse(BaseModel):
    """Catalog of all discoverable table views."""

    count: int
    views: list[ViewSummary]


class TableDataResponse(BaseModel):
    """Structured response payload for REST view queries."""

    schema_name: str
    table_name: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    total_ms: float
    cache_hit: bool


def sanitize_value(val: str) -> str:
    """Format string, numeric, or boolean value for SQL query literal."""
    v = val.strip()
    if v.isdigit():
        return v
    try:
        float(v)
        return v
    except ValueError:
        pass
    if v.lower() in ("true", "false"):
        return v.upper()
    escaped = v.replace("'", "''")
    return f"'{escaped}'"


def resolve_view_path(schema: str, table: str, preferred_catalog: str | None = None) -> str:
    """Find matching 3-part virtual namespace for a schema and table."""
    if preferred_catalog:
        return f"{preferred_catalog}.{schema}.{table}"

    for ds_name in default_catalog.list_datasources():
        key = f"{ds_name}.{schema}.{table}"
        if key in default_catalog._table_cache:
            return key
        schemas = default_catalog._schema_cache.get(ds_name, {})
        if schema in schemas and any(t.name.lower() == table.lower() for t in schemas[schema]):
            return key

    datasources = default_catalog.list_datasources()
    if datasources:
        return f"{datasources[0]}.{schema}.{table}"
    return f"{schema}.{table}"


@router.get("", response_model=ViewListResponse)
async def list_views() -> ViewListResponse:
    """List all available views and tables across the unified catalog."""
    views: list[ViewSummary] = []
    tree = default_catalog.get_unified_tree()

    for ds_name, ds_info in tree.items():
        schemas = ds_info.get("schemas", {})
        for schema_name, schema_info in schemas.items():
            tables = schema_info.get("tables", [])
            for tbl in tables:
                tname = tbl.get("name", "")
                views.append(
                    ViewSummary(
                        catalog=ds_name,
                        schema_name=schema_name,
                        table_name=tname,
                        full_path=f"{ds_name}.{schema_name}.{tname}",
                        format=tbl.get("format"),
                        url=f"/api/v1/views/{schema_name}/{tname}",
                    )
                )

    return ViewListResponse(count=len(views), views=views)


@router.get("/{schema}/{table}")
async def query_view(
    schema: str,
    table: str,
    request: Request,
    catalog: str | None = None,
    fields: str | None = Query(None, description="Comma-separated column names to project"),
    sort: str | None = Query(None, description="Column to sort by. Prefix with - for descending"),
    limit: int = Query(100, ge=1, le=10000, description="Maximum rows to return"),
    offset: int = Query(0, ge=0, description="Row offset for pagination"),
) -> Response:
    """Query a table view with filtering, projection, sorting, and format negotiation."""
    if not IDENTIFIER_REGEX.match(schema) or not IDENTIFIER_REGEX.match(table):
        raise HTTPException(status_code=400, detail="Invalid schema or table name identifier.")

    full_path = resolve_view_path(schema, table, catalog)

    # 1. Projection clause
    if fields:
        col_list = [f.strip() for f in fields.split(",") if f.strip()]
        for c in col_list:
            if not IDENTIFIER_REGEX.match(c):
                raise HTTPException(status_code=400, detail=f"Invalid column identifier: '{c}'")
        select_clause = ", ".join(col_list)
    else:
        select_clause = "*"

    # 2. Filter clauses from query parameters
    reserved_params = {"catalog", "fields", "sort", "limit", "offset"}
    where_clauses: list[str] = []

    for param, val in request.query_params.items():
        if param in reserved_params:
            continue

        op = "="
        col_name = param
        if "__" in param:
            parts = param.split("__", 1)
            col_name = parts[0]
            op_code = parts[1].lower()
            op_map = {
                "gt": ">",
                "gte": ">=",
                "lt": "<",
                "lte": "<=",
                "ne": "!=",
                "like": "LIKE",
                "in": "IN",
            }
            if op_code in op_map:
                op = op_map[op_code]
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported filter operator: '{op_code}'")

        if not IDENTIFIER_REGEX.match(col_name):
            raise HTTPException(status_code=400, detail=f"Invalid filter column name: '{col_name}'")

        if op == "IN":
            in_vals = [sanitize_value(v) for v in val.split(",") if v.strip()]
            where_clauses.append(f"{col_name} IN ({', '.join(in_vals)})")
        elif op == "LIKE":
            escaped_val = val.replace("'", "''")
            where_clauses.append(f"{col_name} LIKE '{escaped_val}'")
        else:
            where_clauses.append(f"{col_name} {op} {sanitize_value(val)}")

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # 3. Sort clause
    order_sql = ""
    if sort:
        sort_clean = sort.strip()
        direction = "ASC"
        if sort_clean.startswith("-"):
            direction = "DESC"
            sort_col = sort_clean[1:]
        elif sort_clean.startswith("+"):
            sort_col = sort_clean[1:]
        else:
            sort_col = sort_clean

        if not IDENTIFIER_REGEX.match(sort_col):
            raise HTTPException(status_code=400, detail=f"Invalid sort column name: '{sort_col}'")
        order_sql = f" ORDER BY {sort_col} {direction}"

    # 4. Construct SQL query
    offset_sql = f" OFFSET {offset}" if offset > 0 else ""
    sql = f"SELECT {select_clause} FROM {full_path}{where_sql}{order_sql} LIMIT {limit}{offset_sql}"  # noqa: S608

    try:
        arrow_table, metrics = await federated_executor.execute(sql)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"View query execution failed: {exc}") from exc

    # 5. Content negotiation
    accept_header = request.headers.get("accept", "").lower()
    if "text/csv" in accept_header:
        out_buf = io.BytesIO()
        pcsv.write_csv(arrow_table, out_buf)
        csv_bytes = out_buf.getvalue()
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
        )

    # Default to JSON payload
    columns = arrow_table.column_names
    rows_pydict = arrow_table.to_pydict()
    row_count = arrow_table.num_rows

    rows: list[list[Any]] = []
    for i in range(row_count):
        rows.append([rows_pydict[col][i] for col in columns])

    return TableDataResponse(
        schema_name=schema,
        table_name=table,
        columns=columns,
        rows=rows,
        row_count=row_count,
        total_ms=metrics.total_ms,
        cache_hit=metrics.cache_hit,
    )
