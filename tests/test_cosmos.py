"""Unit tests for CosmosDBConnector schema sampling and partition key detection."""

import pytest

from app.connectors.cosmos import CosmosDBConnector, infer_type_from_value
from app.connectors.models import ConnectionConfig, DataType


def test_infer_type_from_value():
    """Verify JSON value type inference."""
    assert infer_type_from_value("text") == DataType.STRING
    assert infer_type_from_value(123) == DataType.INTEGER
    assert infer_type_from_value(99.99) == DataType.FLOAT
    assert infer_type_from_value(True) == DataType.BOOLEAN
    assert infer_type_from_value({"key": "val"}) == DataType.JSON
    assert infer_type_from_value(["item"]) == DataType.JSON


@pytest.mark.asyncio
async def test_cosmos_connector_sampling_and_partition_key():
    """Verify Cosmos DB connector samples documents and detects partition key."""
    config = ConnectionConfig(
        name="cosmos_compliance",
        datasource_type="cosmos",
        database="risk_audit",
        extra_options={
            "databases": ["risk_audit", "logs"],
            "containers": ["audit_events"],
            "partition_key_path": "/portfolioId",
            "sample_documents": [
                {
                    "id": "evt-100",
                    "portfolioId": "PORT-ALPHA",
                    "action": "TRADE_BUY",
                    "shares": 500,
                    "price": 182.25,
                    "metadata": {"source": "FIX_ENGINE"},
                    "_rid": "system_ignored",
                }
            ],
            "mock_items": [
                {"id": "evt-100", "portfolioId": "PORT-ALPHA", "action": "TRADE_BUY", "_rid": "ignored"}
            ],
        },
    )

    connector = CosmosDBConnector(config=config)
    async with connector as conn:
        status = await conn.test_connection()
        assert status.is_connected is True

        schemas = await conn.introspect_schemas()
        assert "risk_audit" in schemas

        tables = await conn.introspect_tables("risk_audit")
        assert len(tables) == 1
        assert tables[0].name == "audit_events"

        table_schema = await conn.get_table_schema("risk_audit", "audit_events")
        # System property `_rid` should be filtered out
        col_names = [c.name for c in table_schema.columns]
        assert "_rid" not in col_names
        assert "id" in col_names
        assert "portfolioId" in col_names
        assert "shares" in col_names

        # Check partition key detection
        pk_cols = [c.name for c in table_schema.columns if c.is_partition_key]
        assert pk_cols == ["portfolioId"]

        # Check query execution to Arrow
        arrow_table = await conn.execute_query("SELECT * FROM c", limit=10)
        assert arrow_table.num_rows == 1
        assert "_rid" not in arrow_table.column_names
        assert "portfolioId" in arrow_table.column_names
