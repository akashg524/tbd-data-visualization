"""Chunked REST export API streaming CSV, Parquet, and NDJSON for Power BI Web.Contents and Excel."""

from __future__ import annotations

import io
import json
from typing import Any

import pyarrow.csv as pcsv
import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.query import federated_executor

router = APIRouter()


class ExportRequest(BaseModel):
    """Payload for POST export requests."""

    sql: str
    format: str = Field(default="csv", description="Target format: 'csv', 'parquet', or 'ndjson'")
    limit: int | None = Field(default=None, ge=1, le=1000000, description="Row limit")
    filename: str = Field(default="export", description="Download file basename")


async def build_export_response(
    sql: str,
    export_format: str,
    limit: int | None,
    filename: str,
) -> Response:
    """Execute SQL query and generate streaming format response."""
    fmt = export_format.lower().strip()
    if fmt not in ("csv", "parquet", "ndjson"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format '{fmt}'. Choose 'csv', 'parquet', or 'ndjson'.",
        )

    try:
        arrow_table, _metrics = await federated_executor.execute(sql, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Export query failed: {exc}") from exc

    safe_filename = "".join(c for c in filename if c.isalnum() or c in ("-", "_")) or "export"

    if fmt == "csv":
        out_buf = io.BytesIO()
        pcsv.write_csv(arrow_table, out_buf)
        return Response(
            content=out_buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename}.csv"'},
        )

    if fmt == "parquet":
        out_buf = io.BytesIO()
        pq.write_table(arrow_table, out_buf)
        return Response(
            content=out_buf.getvalue(),
            media_type="application/vnd.apache.parquet",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename}.parquet"'},
        )

    # NDJSON (Newline-Delimited JSON)
    def iter_ndjson() -> Any:
        cols = arrow_table.column_names
        pydict = arrow_table.to_pydict()
        for i in range(arrow_table.num_rows):
            row_dict = {col: pydict[col][i] for col in cols}
            yield (json.dumps(row_dict, default=str) + "\n").encode("utf-8")

    return StreamingResponse(
        iter_ndjson(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}.ndjson"'},
    )


@router.get("/query")
async def export_query_get(
    sql: str = Query(..., description="SQL query to execute"),
    format: str = Query("csv", description="Format: 'csv', 'parquet', 'ndjson'"),
    limit: int | None = Query(None, ge=1, le=1000000, description="Row limit"),
    filename: str = Query("export", description="Basename for downloaded file"),
) -> Response:
    """Stream export query results via HTTP GET."""
    return await build_export_response(sql, format, limit, filename)


@router.post("/query")
async def export_query_post(payload: ExportRequest) -> Response:
    """Stream export query results via HTTP POST."""
    return await build_export_response(payload.sql, payload.format, payload.limit, payload.filename)
