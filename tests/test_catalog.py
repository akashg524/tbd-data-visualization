"""Unit tests for UnifiedCatalogRegistry multi-source registration and resolution."""

import pytest

from app.catalog import UnifiedCatalogRegistry
from app.connectors.iceberg_adls import IcebergADLSConnector
from app.connectors.models import ConnectionConfig
from app.connectors.oracle import OracleConnector


@pytest.mark.asyncio
async def test_unified_catalog_registration_and_resolution():
    """Verify multiple heterogeneous datasources can register and resolve paths."""
    catalog = UnifiedCatalogRegistry()

    # 1. Register ADLS Iceberg connector
    adls_cfg = ConnectionConfig(
        name="adls_lake",
        datasource_type="adls_iceberg",
        extra_options={
            "schemas": ["equity"],
            "tables": ["trades"],
        },
    )
    adls_conn = IcebergADLSConnector(config=adls_cfg)
    catalog.register_datasource("adls_lake", adls_conn)

    # 2. Register Oracle connector
    oracle_cfg = ConnectionConfig(
        name="oracle_db",
        datasource_type="oracle",
        extra_options={
            "schemas": ["risk"],
            "tables": ["counterparties"],
        },
    )
    oracle_conn = OracleConnector(config=oracle_cfg)
    catalog.register_datasource("oracle_db", oracle_conn)

    # Verify listing
    assert set(catalog.list_datasources()) == {"adls_lake", "oracle_db"}

    # Refresh catalog
    await catalog.refresh_catalog()

    # Resolve table path
    conn, schema, table = catalog.resolve_table("adls_lake.equity.trades")
    assert conn == adls_conn
    assert schema == "equity"
    assert table == "trades"

    conn_ora, schema_ora, table_ora = catalog.resolve_table("oracle_db.risk.counterparties")
    assert conn_ora == oracle_conn
    assert schema_ora == "risk"
    assert table_ora == "counterparties"

    # Get hierarchical tree
    tree = catalog.get_unified_tree()
    assert "adls_lake" in tree
    assert "oracle_db" in tree
    assert "equity" in tree["adls_lake"]["schemas"]
    assert "risk" in tree["oracle_db"]["schemas"]

    tables = tree["adls_lake"]["schemas"]["equity"]["tables"]
    assert len(tables) == 1
    assert tables[0]["full_path"] == "adls_lake.equity.trades"

    # Unregister
    catalog.unregister_datasource("oracle_db")
    assert "oracle_db" not in catalog.list_datasources()


def test_invalid_table_path_resolution():
    """Verify error on malformed table path."""
    catalog = UnifiedCatalogRegistry()
    with pytest.raises(ValueError, match="Invalid table identifier"):
        catalog.resolve_table("invalid_path_without_enough_parts")
