"""Unit tests for DimensionCache and fast-path substitution in FederatedExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pyarrow as pa
import pytest

from app.cache import DimensionCache
from app.catalog import UnifiedCatalogRegistry
from app.connectors.iceberg_adls import IcebergADLSConnector
from app.connectors.models import ConnectionConfig
from app.connectors.oracle import OracleConnector
from app.federation.executor import FederatedExecutor


@pytest.fixture
def mock_catalog() -> UnifiedCatalogRegistry:
    """Fixture providing a catalog populated with mock ADLS and Oracle connectors."""
    cat = UnifiedCatalogRegistry()

    adls = IcebergADLSConnector(ConnectionConfig(name="adls_lake", datasource_type="adls_iceberg"))
    adls.execute_query = AsyncMock(  # type: ignore[method-assign]
        return_value=pa.table(
            {
                "trade_id": [1, 2, 3],
                "counterparty_id": [101, 102, 103],
                "amount": [1500.0, 2500.0, 500.0],
            }
        )
    )

    ora = OracleConnector(ConnectionConfig(name="oracle_dw", datasource_type="oracle"))
    ora.execute_query = AsyncMock(  # type: ignore[method-assign]
        return_value=pa.table(
            {
                "id": [101, 102, 104],
                "name": ["Alpha Corp", "Beta LLC", "Gamma Inc"],
                "credit_limit": [2000.0, 2000.0, 1000.0],
                "country": ["US", "US", "UK"],
            }
        )
    )

    cat.register_datasource("adls_lake", adls)
    cat.register_datasource("oracle_dw", ora)
    return cat


async def test_dimension_cache_registration_and_fetch(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify dimension table registration, lazy loading, and status checking."""
    dim_cache = DimensionCache(catalog=mock_catalog)
    table_path = "oracle_dw.risk.counterparties"

    dim_cache.register_dimension(table_path)
    assert not dim_cache.is_dimension_cached(table_path)

    # First fetch loads from connector
    tbl = await dim_cache.get_dimension(table_path)
    assert tbl is not None
    assert tbl.num_rows == 3
    assert dim_cache.is_dimension_cached(table_path)

    # Second fetch returns from memory cache without connector call
    ora_conn = mock_catalog.get_connector("oracle_dw")
    ora_conn.execute_query.reset_mock()  # type: ignore[attr-defined]

    tbl2 = await dim_cache.get_dimension(table_path)
    assert tbl2 is not None
    assert tbl2.num_rows == 3
    ora_conn.execute_query.assert_not_called()  # type: ignore[attr-defined]


async def test_dimension_cache_max_rows_limit(mock_catalog: UnifiedCatalogRegistry) -> None:
    """T-03-01: Verify error when a table exceeds max_rows limit."""
    dim_cache = DimensionCache(catalog=mock_catalog, max_rows=2)
    table_path = "oracle_dw.risk.counterparties"

    dim_cache.register_dimension(table_path)

    # Table has 3 rows > max_rows 2 -> raises ValueError
    with pytest.raises(ValueError, match="exceeding maximum allowed dimension size"):
        await dim_cache.refresh_dimension(table_path)


async def test_federated_executor_with_dimension_substitution(
    mock_catalog: UnifiedCatalogRegistry, tmp_path
) -> None:
    """Verify FederatedExecutor substitutes cached dimension tables and skips connector queries."""
    dim_cache = DimensionCache(catalog=mock_catalog)
    dim_table_path = "oracle_dw.risk.counterparties"
    dim_cache.register_dimension(dim_table_path)
    await dim_cache.refresh_dimension(dim_table_path)

    scratch_dir = str(tmp_path / "scratch")
    executor = FederatedExecutor(
        catalog=mock_catalog,
        dimension_cache=dim_cache,
        scratch_dir=scratch_dir,
    )

    sql = """
        SELECT t.trade_id, c.name, t.amount
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE c.country = 'US'
        ORDER BY t.trade_id
    """

    ora_conn = mock_catalog.get_connector("oracle_dw")
    ora_conn.execute_query.reset_mock()  # type: ignore[attr-defined]

    table, metrics = await executor.execute(sql)

    # Oracle connector should NEVER be called over network because it's in DimensionCache
    ora_conn.execute_query.assert_not_called()  # type: ignore[attr-defined]

    # Join results should be 100% correct
    assert table.num_rows == 2
    assert table.column_names == ["trade_id", "name", "amount"]
    assert table["name"].to_pylist() == ["Alpha Corp", "Beta LLC"]
    assert metrics.join_ms > 0
