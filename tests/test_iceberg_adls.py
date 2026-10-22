"""Unit and integration tests for IcebergADLSConnector."""

import pytest

from app.connectors.iceberg_adls import (
    IcebergADLSConnector,
    map_iceberg_type_to_datatype,
)
from app.connectors.models import ConnectionConfig, DataType


def test_iceberg_type_mapping():
    """Verify Iceberg schema string mapping to unified DataType enum."""
    assert map_iceberg_type_to_datatype("int") == DataType.INTEGER
    assert map_iceberg_type_to_datatype("long") == DataType.INTEGER
    assert map_iceberg_type_to_datatype("double") == DataType.FLOAT
    assert map_iceberg_type_to_datatype("decimal(18,2)") == DataType.DECIMAL
    assert map_iceberg_type_to_datatype("boolean") == DataType.BOOLEAN
    assert map_iceberg_type_to_datatype("timestamp") == DataType.TIMESTAMP
    assert map_iceberg_type_to_datatype("date") == DataType.DATE
    assert map_iceberg_type_to_datatype("string") == DataType.STRING


@pytest.mark.asyncio
async def test_iceberg_connector_introspection():
    """Verify Iceberg connector metadata discovery and snapshot inspection."""
    config = ConnectionConfig(
        name="adls_equity",
        datasource_type="adls_iceberg",
        storage_account="financeadls",
        container="lakehouse",
        extra_options={
            "schemas": ["equity_markets", "fixed_income"],
            "tables": [{"name": "trades", "comment": "Daily equity trades"}],
            "table_schemas": {
                "equity_markets.trades": {
                    "columns": [
                        {"name": "trade_id", "type": "string", "nullable": False},
                        {"name": "trade_date", "type": "date", "is_partition_key": True},
                        {"name": "notional_usd", "type": "decimal(18,4)"},
                    ],
                    "partition_keys": ["trade_date"],
                }
            },
            "snapshots": [
                {"snapshot_id": 9001, "timestamp_ms": 1729600000000, "summary": {"operation": "append"}}
            ],
        },
    )

    connector = IcebergADLSConnector(config=config)
    async with connector as conn:
        status = await conn.test_connection()
        assert status.is_connected is True

        schemas = await conn.introspect_schemas()
        assert "equity_markets" in schemas

        tables = await conn.introspect_tables("equity_markets")
        assert len(tables) == 1
        assert tables[0].name == "trades"
        assert tables[0].format_type == "iceberg"

        table_schema = await conn.get_table_schema("equity_markets", "trades")
        assert len(table_schema.columns) == 3
        assert table_schema.partition_keys == ["trade_date"]

        snapshots = await conn.get_snapshots("equity_markets", "trades")
        assert len(snapshots) == 1
        assert snapshots[0]["snapshot_id"] == 9001


@pytest.mark.asyncio
async def test_iceberg_query_execution():
    """Verify DuckDB integration converts query results to PyArrow table."""
    config = ConnectionConfig(
        name="adls_iceberg_test",
        datasource_type="adls_iceberg",
    )
    connector = IcebergADLSConnector(config=config)
    async with connector as conn:
        # Standard analytical query executed through DuckDB
        table = await conn.execute_query(
            "SELECT 101 AS trade_id, 'AAPL' AS ticker, 15000.50 AS amount",
            limit=10,
        )
        assert table.num_rows == 1
        assert table.column_names == ["trade_id", "ticker", "amount"]
        assert table.column("ticker")[0].as_py() == "AAPL"
