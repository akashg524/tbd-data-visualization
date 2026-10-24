"""Integration tests for OData v4 endpoints and one-click connection file launchers."""

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


class ODataTestConnector(BaseConnector):
    """Mock connector backed by DuckDB for OData testing."""

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
                ColumnMetadata(name="trade_id", data_type=DataType.INTEGER, is_primary_key=True),
                ColumnMetadata(name="counterparty", data_type=DataType.STRING),
                ColumnMetadata(name="amount", data_type=DataType.FLOAT),
                ColumnMetadata(name="status", data_type=DataType.STRING),
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
def odata_client():
    """Setup test client with test datasource registered in catalog."""
    test_data = pa.table(
        {
            "trade_id": [1, 2, 3, 4],
            "counterparty": ["Alpha", "Beta", "Gamma", "Alpha"],
            "amount": [500.0, 1500.0, 2500.0, 3500.0],
            "status": ["PENDING", "SETTLED", "SETTLED", "SETTLED"],
        }
    )
    connector = ODataTestConnector("lake", "equity", "trades", test_data)

    catalog.register_datasource("lake", connector)
    catalog._schema_cache["lake"] = {
        "equity": [
            TableMetadata(
                name="trades",
                schema_name="equity",
                row_count_estimate=4,
                format_type="iceberg",
            )
        ]
    }
    catalog._table_cache["lake.equity.trades"] = TableSchema(
        table_name="trades",
        schema_name="equity",
        columns=[
            ColumnMetadata(name="trade_id", data_type=DataType.INTEGER, is_primary_key=True),
            ColumnMetadata(name="counterparty", data_type=DataType.STRING),
            ColumnMetadata(name="amount", data_type=DataType.FLOAT),
            ColumnMetadata(name="status", data_type=DataType.STRING),
        ],
    )

    app = create_app()
    with TestClient(app) as tc:
        yield tc

    catalog.unregister_datasource("lake")


def test_odata_metadata(odata_client: TestClient) -> None:
    """Verify GET /api/v1/odata/$metadata returns EDM XML."""
    response = odata_client.get("/api/v1/odata/$metadata")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    text = response.text
    assert "<edmx:Edmx" in text
    assert '<EntityType Name="equity_trades">' in text
    assert '<Property Name="trade_id" Type="Edm.Int64"' in text
    assert '<PropertyRef Name="trade_id"' in text
    assert '<EntitySet Name="equity_trades"' in text


def test_odata_service_document(odata_client: TestClient) -> None:
    """Verify GET /api/v1/odata returns service document JSON."""
    response = odata_client.get("/api/v1/odata")
    assert response.status_code == 200
    data = response.json()
    assert "@odata.context" in data
    assert any(es["name"] == "equity_trades" for es in data["value"])


def test_odata_query_entity_set(odata_client: TestClient) -> None:
    """Verify GET /api/v1/odata/{schema}/{table} returns OData JSON envelope."""
    response = odata_client.get("/api/v1/odata/equity/trades")
    assert response.status_code == 200
    data = response.json()
    assert "@odata.context" in data
    assert len(data["value"]) == 4
    first = data["value"][0]
    assert "trade_id" in first
    assert "counterparty" in first
    assert "amount" in first


def test_odata_query_select(odata_client: TestClient) -> None:
    """Verify $select projection in OData feed."""
    response = odata_client.get("/api/v1/odata/equity/trades?$select=trade_id,amount")
    assert response.status_code == 200
    data = response.json()
    first = data["value"][0]
    assert set(first.keys()) == {"trade_id", "amount"}


def test_odata_query_filter_and_count(odata_client: TestClient) -> None:
    """Verify $filter clause and $count annotation in OData feed."""
    response = odata_client.get(
        "/api/v1/odata/equity/trades?$filter=amount gt 1000 and status eq 'SETTLED'&$count=true"
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("@odata.count") == 3
    assert len(data["value"]) == 3
    for row in data["value"]:
        assert row["amount"] > 1000
        assert row["status"] == "SETTLED"


def test_odata_query_sorting_and_paging(odata_client: TestClient) -> None:
    """Verify $orderby, $top, and $skip parameters."""
    response = odata_client.get("/api/v1/odata/equity/trades?$orderby=amount desc&$top=2&$skip=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["value"]) == 2
    # Sorted desc: 3500, 2500, 1500, 500. Skip 1 -> 2500, 1500
    assert data["value"][0]["amount"] == 2500.0
    assert data["value"][1]["amount"] == 1500.0


def test_launcher_pbids(odata_client: TestClient) -> None:
    """Verify GET /api/v1/launchers/pbids returns downloadable .pbids file."""
    response = odata_client.get("/api/v1/launchers/pbids?port=5433&database=federated")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    assert 'attachment; filename="federated_data_hub.pbids"' in response.headers["content-disposition"]
    pbids = response.json()
    assert pbids["version"] == "0.1"
    assert pbids["connections"][0]["details"]["protocol"] == "postgresql"
    assert pbids["connections"][0]["mode"] == "DirectQuery"


def test_launcher_odc(odata_client: TestClient) -> None:
    """Verify GET /api/v1/launchers/odc returns downloadable .odc file."""
    response = odata_client.get("/api/v1/launchers/odc?schema=equity&table=trades")
    assert response.status_code == 200
    assert "text/x-ms-odc" in response.headers["content-type"]
    assert 'attachment; filename="federated_data_hub.odc"' in response.headers["content-disposition"]
    assert "ODC.DataFeed" in response.text
    assert "Microsoft.Data.Mashup.Provider" in response.text
    assert "/api/v1/odata/equity/trades" in response.text
