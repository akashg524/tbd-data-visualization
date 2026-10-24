"""Integration tests for the RESTful Table Views API."""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from app.catalog import catalog
from app.connectors.base import BaseConnector
from app.connectors.models import (
    ColumnMetadata,
    ConnectionConfig,
    ConnectionStatus,
    DataType,
    TableMetadata,
    TableSchema,
)
from app.main import create_app


class InMemoryTestConnector(BaseConnector):
    """Mock connector backed by an in-memory DuckDB instance."""

    def __init__(self, name: str, schema_name: str, table_name: str, data: pa.Table):
        super().__init__(ConnectionConfig(name=name, datasource_type="adls_iceberg"))
        self.schema_name = schema_name
        self.table_name = table_name
        self.data = data
        self.duck_conn = duckdb.connect()
        self.duck_conn.register("raw_tbl", data)
        self.duck_conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
        self.duck_conn.execute(f"CREATE VIEW {schema_name}.{table_name} AS SELECT * FROM raw_tbl")  # noqa: S608

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.duck_conn.close()

    async def test_connection(self) -> ConnectionStatus:
        return ConnectionStatus(connected=True, latency_ms=1.0)

    async def introspect_schemas(self) -> list[str]:
        return [self.schema_name]

    async def introspect_tables(self, schema: str) -> list[TableMetadata]:
        return [
            TableMetadata(
                name=self.table_name,
                schema_name=schema,
                row_count_estimate=self.data.num_rows,
                format_type="iceberg",
            )
        ]

    async def get_table_schema(self, schema: str, table: str) -> TableSchema:
        return TableSchema(
            table_name=table,
            schema_name=schema,
            columns=[
                ColumnMetadata(name=col, data_type=DataType.STRING)
                for col in self.data.column_names
            ],
        )

    async def execute_query(self, sql: str, limit: int | None = None) -> pa.Table:
        rel = self.duck_conn.sql(sql)
        res = rel.arrow()
        tbl = res.read_all() if hasattr(res, "read_all") else res
        if limit is not None and tbl.num_rows > limit:
            tbl = tbl.slice(0, limit)
        return tbl


@pytest.fixture
def views_client():
    """Setup test client with registered test datasource in global catalog."""
    test_data = pa.table(
        {
            "trade_id": [1, 2, 3, 4],
            "counterparty": ["Alpha", "Beta", "Gamma", "Alpha"],
            "amount": [500.0, 1500.0, 2500.0, 3500.0],
            "status": ["PENDING", "SETTLED", "SETTLED", "SETTLED"],
        }
    )
    connector = InMemoryTestConnector("test_lake", "equity", "trades", test_data)

    catalog.register_datasource("test_lake", connector)
    # Pre-populate schema cache so list_views() and resolve_view_path() discover it
    catalog._schema_cache["test_lake"] = {
        "equity": [
            TableMetadata(
                name="trades",
                schema_name="equity",
                row_count_estimate=4,
                format_type="iceberg",
            )
        ]
    }

    app = create_app()
    with TestClient(app) as tc:
        yield tc

    catalog.unregister_datasource("test_lake")


def test_list_views(views_client: TestClient) -> None:
    """Verify GET /api/v1/views enumerates discoverable catalog views."""
    response = views_client.get("/api/v1/views")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    found = any(
        v["schema_name"] == "equity" and v["table_name"] == "trades"
        for v in data["views"]
    )
    assert found


def test_query_view_default_json(views_client: TestClient) -> None:
    """Verify GET /api/v1/views/{schema}/{table} returns default JSON payload."""
    response = views_client.get("/api/v1/views/equity/trades")
    assert response.status_code == 200
    data = response.json()
    assert data["schema_name"] == "equity"
    assert data["table_name"] == "trades"
    assert "columns" in data
    assert "trade_id" in data["columns"]
    assert data["row_count"] == 4
    assert len(data["rows"]) == 4


def test_query_view_projection(views_client: TestClient) -> None:
    """Verify fields projection parameter."""
    response = views_client.get("/api/v1/views/equity/trades?fields=trade_id,amount")
    assert response.status_code == 200
    data = response.json()
    assert data["columns"] == ["trade_id", "amount"]
    assert len(data["rows"][0]) == 2


def test_query_view_filtering(views_client: TestClient) -> None:
    """Verify dynamic filter query parameters (__gt, __in, equality)."""
    # Filter amount > 1000
    response = views_client.get("/api/v1/views/equity/trades?amount__gt=1000")
    assert response.status_code == 200
    data = response.json()
    assert data["row_count"] == 3

    # Filter status = SETTLED
    response = views_client.get("/api/v1/views/equity/trades?status=SETTLED")
    assert response.status_code == 200
    data = response.json()
    assert data["row_count"] == 3

    # Filter counterparty in Beta, Gamma
    response = views_client.get("/api/v1/views/equity/trades?counterparty__in=Beta,Gamma")
    assert response.status_code == 200
    data = response.json()
    assert data["row_count"] == 2


def test_query_view_sorting_and_pagination(views_client: TestClient) -> None:
    """Verify sorting (-amount) and pagination (limit, offset)."""
    response = views_client.get("/api/v1/views/equity/trades?sort=-amount&limit=2&offset=1")
    assert response.status_code == 200
    data = response.json()
    assert data["row_count"] == 2
    # Amounts descending: 3500, 2500, 1500, 500. Offset 1 -> 2500, 1500
    amount_idx = data["columns"].index("amount")
    assert data["rows"][0][amount_idx] == 2500.0
    assert data["rows"][1][amount_idx] == 1500.0


def test_query_view_csv_streaming(views_client: TestClient) -> None:
    """Verify CSV streaming via Accept: text/csv header."""
    response = views_client.get(
        "/api/v1/views/equity/trades?fields=trade_id,counterparty",
        headers={"Accept": "text/csv"},
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert 'attachment; filename="trades.csv"' in response.headers.get("content-disposition", "")
    lines = response.text.strip().splitlines()
    assert lines[0] == '"trade_id","counterparty"'
    assert len(lines) == 5  # header + 4 rows


def test_query_view_validation_errors(views_client: TestClient) -> None:
    """Verify validation and SQL injection defense for parameters."""
    # Invalid schema name
    bad_schema = views_client.get("/api/v1/views/bad-schema!/trades")
    assert bad_schema.status_code == 400

    # Invalid column in projection
    bad_proj = views_client.get("/api/v1/views/equity/trades?fields=trade_id;DROP TABLE trades")
    assert bad_proj.status_code == 400

    # Unsupported operator
    bad_op = views_client.get("/api/v1/views/equity/trades?amount__custom=100")
    assert bad_op.status_code == 400
