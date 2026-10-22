"""Unit tests for Oracle and SQL Server read-only relational connectors."""

import pytest

from app.connectors.models import ConnectionConfig, DataType
from app.connectors.oracle import OracleConnector, map_oracle_type_to_datatype
from app.connectors.sqlserver import SQLServerConnector, map_sqlserver_type_to_datatype


def test_oracle_type_mapping():
    """Verify Oracle type string to DataType mapping."""
    assert map_oracle_type_to_datatype("NUMBER(10)") == DataType.INTEGER
    assert map_oracle_type_to_datatype("NUMBER(18,4)") == DataType.DECIMAL
    assert map_oracle_type_to_datatype("FLOAT") == DataType.FLOAT
    assert map_oracle_type_to_datatype("DATE") == DataType.DATE
    assert map_oracle_type_to_datatype("TIMESTAMP(6)") == DataType.TIMESTAMP
    assert map_oracle_type_to_datatype("VARCHAR2(100)") == DataType.STRING


def test_sqlserver_type_mapping():
    """Verify SQL Server type string to DataType mapping."""
    assert map_sqlserver_type_to_datatype("int") == DataType.INTEGER
    assert map_sqlserver_type_to_datatype("bigint") == DataType.INTEGER
    assert map_sqlserver_type_to_datatype("decimal(18,2)") == DataType.DECIMAL
    assert map_sqlserver_type_to_datatype("datetime2") == DataType.TIMESTAMP
    assert map_sqlserver_type_to_datatype("varchar(50)") == DataType.STRING
    assert map_sqlserver_type_to_datatype("bit") == DataType.BOOLEAN


@pytest.mark.asyncio
async def test_oracle_connector_readonly_and_introspection():
    """Verify Oracle connector enforces read-only property and extracts metadata."""
    config = ConnectionConfig(
        name="oracle_risk",
        datasource_type="oracle",
        host="localhost",
        username="readonly_user",
        extra_options={
            "schemas": ["RISK", "MARKETS"],
            "tables": ["COUNTERPARTIES", "CREDIT_LINES"],
            "table_schemas": {
                "RISK.COUNTERPARTIES": {
                    "columns": [
                        {"name": "COUNTERPARTY_ID", "type": "NUMBER(10)", "is_primary_key": True},
                        {"name": "NAME", "type": "VARCHAR2(100)"},
                        {"name": "RATING", "type": "VARCHAR2(10)"},
                    ]
                }
            },
            "mock_data": {
                "COUNTERPARTY_ID": [101, 102],
                "NAME": ["JPMorgan", "Morgan Stanley"],
                "RATING": ["AAA", "AA+"],
            },
        },
    )

    connector = OracleConnector(config=config)
    assert connector.is_read_only is True

    async with connector as conn:
        status = await conn.test_connection()
        assert status.is_connected is True

        schemas = await conn.introspect_schemas()
        assert "RISK" in schemas

        tables = await conn.introspect_tables("RISK")
        assert len(tables) == 2
        assert tables[0].name == "COUNTERPARTIES"

        table_schema = await conn.get_table_schema("RISK", "COUNTERPARTIES")
        assert len(table_schema.columns) == 3
        assert table_schema.columns[0].is_primary_key is True

        # Query execution to Arrow
        arrow_table = await conn.execute_query("SELECT * FROM RISK.COUNTERPARTIES", limit=5)
        assert arrow_table.num_rows == 2
        assert arrow_table.column("NAME")[0].as_py() == "JPMorgan"


@pytest.mark.asyncio
async def test_sqlserver_connector_readonly_and_introspection():
    """Verify SQL Server connector targets secondary replicas and streams Arrow."""
    config = ConnectionConfig(
        name="mssql_accounting",
        datasource_type="sqlserver",
        host="localhost",
        database="GeneralLedger",
        username="ro_analyst",
        extra_options={
            "schemas": ["dbo", "accounting"],
            "tables": ["gl_accounts"],
            "mock_data": {
                "account_id": [1, 2],
                "account_code": ["GL-1000", "GL-2000"],
                "account_name": ["Cash", "Investments"],
                "balance_usd": [100000.0, 500000.0],
            },
        },
    )

    connector = SQLServerConnector(config=config)
    assert connector.is_read_only is True

    async with connector as conn:
        status = await conn.test_connection()
        assert status.is_connected is True

        schemas = await conn.introspect_schemas()
        assert "accounting" in schemas

        tables = await conn.introspect_tables("accounting")
        assert len(tables) == 1
        assert tables[0].name == "gl_accounts"

        table_schema = await conn.get_table_schema("accounting", "gl_accounts")
        assert len(table_schema.columns) == 4
        assert table_schema.columns[0].name == "account_id"

        arrow_table = await conn.execute_query("SELECT * FROM accounting.gl_accounts", limit=10)
        assert arrow_table.num_rows == 2
        assert arrow_table.column("account_code")[0].as_py() == "GL-1000"
