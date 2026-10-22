"""Unit tests for BaseConnector contract and metadata models."""

import pyarrow as pa
import pytest

from app.connectors import (
    BaseConnector,
    ColumnMetadata,
    ConnectionConfig,
    ConnectionStatus,
    DataType,
    TableMetadata,
    TableSchema,
)


class MockConnector(BaseConnector):
    """Concrete mock connector for testing base contracts."""

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def test_connection(self) -> ConnectionStatus:
        return ConnectionStatus(is_connected=True, latency_ms=1.2, server_version="Mock-1.0")

    async def introspect_schemas(self) -> list[str]:
        return ["default", "finance"]

    async def introspect_tables(self, schema: str) -> list[TableMetadata]:
        return [
            TableMetadata(
                name="trades",
                schema_name=schema,
                row_count_estimate=100000,
                format_type="relational",
            )
        ]

    async def get_table_schema(self, schema: str, table: str) -> TableSchema:
        return TableSchema(
            table_name=table,
            schema_name=schema,
            columns=[
                ColumnMetadata(name="id", data_type=DataType.INTEGER, is_primary_key=True),
                ColumnMetadata(name="ticker", data_type=DataType.STRING),
                ColumnMetadata(name="amount", data_type=DataType.DECIMAL),
            ],
            partition_keys=["ticker"],
        )

    async def execute_query(self, query: str, limit: int | None = None) -> pa.Table:
        return pa.table({"id": [1, 2], "ticker": ["AAPL", "MSFT"]})


@pytest.mark.asyncio
async def test_mock_connector_lifecycle():
    """Verify async context manager and base connector behaviors."""
    config = ConnectionConfig(name="test_mock", datasource_type="mock")
    connector = MockConnector(config=config)

    assert connector.is_read_only is True

    async with connector as conn:
        assert conn._connected is True
        status = await conn.test_connection()
        assert status.is_connected is True
        assert status.server_version == "Mock-1.0"

        schemas = await conn.introspect_schemas()
        assert schemas == ["default", "finance"]

        tables = await conn.introspect_tables("finance")
        assert len(tables) == 1
        assert tables[0].name == "trades"

        table_schema = await conn.get_table_schema("finance", "trades")
        assert len(table_schema.columns) == 3
        assert table_schema.partition_keys == ["ticker"]

        arrow_table = await conn.execute_query("SELECT * FROM trades")
        assert arrow_table.num_rows == 2
        assert arrow_table.column_names == ["id", "ticker"]

    assert connector._connected is False


def test_metadata_model_validation():
    """Verify ColumnMetadata and TableSchema model serialization."""
    col = ColumnMetadata(
        name="trade_date",
        data_type=DataType.DATE,
        is_partition_key=True,
    )
    assert col.data_type == DataType.DATE
    assert col.is_partition_key is True

    schema = TableSchema(
        table_name="executions",
        schema_name="market",
        columns=[col],
    )
    data = schema.model_dump()
    assert data["table_name"] == "executions"
    assert data["columns"][0]["data_type"] == "date"
