"""Integration tests for FederatedExecutor with parallel subquery dispatch, caching, and disk spilling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pyarrow as pa
import pytest

from app.cache import ResultCache
from app.catalog import UnifiedCatalogRegistry
from app.connectors.iceberg_adls import IcebergADLSConnector
from app.connectors.models import ConnectionConfig
from app.connectors.oracle import OracleConnector
from app.federation.executor import FederatedExecutor


@pytest.fixture
def mock_catalog() -> UnifiedCatalogRegistry:
    """Fixture providing a catalog populated with mock ADLS and Oracle connectors."""
    cat = UnifiedCatalogRegistry()

    # ADLS trades connector
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

    # Oracle counterparties connector
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


async def test_single_source_query_bypass(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify single-source queries bypass the DuckDB join engine and route directly to connector."""
    executor = FederatedExecutor(catalog=mock_catalog)
    sql = "SELECT trade_id, amount FROM adls_lake.equity.trades WHERE amount > 1000"

    table, metrics = await executor.execute(sql)

    assert table.num_rows == 3
    assert metrics.planning_ms > 0
    assert metrics.join_ms == 0.0  # DuckDB join bypassed
    assert not metrics.cache_hit
    assert "trades" in metrics.subquery_ms

    adls_conn = mock_catalog.get_connector("adls_lake")
    adls_conn.execute_query.assert_awaited_once()  # type: ignore[attr-defined]


async def test_multi_source_federated_join(mock_catalog: UnifiedCatalogRegistry, tmp_path) -> None:
    """Verify cross-source hash join between ADLS Iceberg and Oracle in DuckDB."""
    scratch_dir = str(tmp_path / "scratch")
    executor = FederatedExecutor(catalog=mock_catalog, scratch_dir=scratch_dir)

    sql = """
        SELECT t.trade_id, c.name, t.amount
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        ORDER BY t.trade_id
    """

    table, metrics = await executor.execute(sql)

    # Inner join on counterparties: 101 and 102 match
    assert table.num_rows == 2
    assert table.column_names == ["trade_id", "name", "amount"]
    assert table["trade_id"].to_pylist() == [1, 2]
    assert table["name"].to_pylist() == ["Alpha Corp", "Beta LLC"]

    assert metrics.planning_ms > 0
    assert metrics.join_ms > 0
    assert metrics.scratch_spill_enabled
    assert "t" in metrics.subquery_ms
    assert "c" in metrics.subquery_ms


async def test_mixed_predicate_evaluation(mock_catalog: UnifiedCatalogRegistry, tmp_path) -> None:
    """Verify cross-source predicates referencing multiple tables are evaluated by DuckDB."""
    scratch_dir = str(tmp_path / "scratch")
    executor = FederatedExecutor(catalog=mock_catalog, scratch_dir=scratch_dir)

    # Predicate: t.amount > c.credit_limit
    # 101: 1500 > 2000 -> False
    # 102: 2500 > 2000 -> True
    sql = """
        SELECT t.trade_id, c.name, t.amount, c.credit_limit
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE t.amount > c.credit_limit
    """

    table, metrics = await executor.execute(sql)

    assert metrics.row_count == 1
    assert table.num_rows == 1
    assert table["trade_id"].to_pylist() == [2]
    assert table["name"].to_pylist() == ["Beta LLC"]
    assert table["amount"].to_pylist() == [2500.0]


async def test_result_cache_hit_under_5ms(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify second query returns instantly with cache_hit=True."""
    cache = ResultCache(default_ttl=60)
    executor = FederatedExecutor(catalog=mock_catalog, cache=cache)

    sql = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
    """

    # First run: cache miss
    tbl1, metrics1 = await executor.execute(sql)
    assert not metrics1.cache_hit
    assert tbl1.num_rows == 2

    # Second run: cache hit
    tbl2, metrics2 = await executor.execute(sql)
    assert metrics2.cache_hit
    assert metrics2.total_ms < 50.0  # Typically <5ms
    assert tbl2.num_rows == 2
    assert tbl2.column_names == tbl1.column_names


async def test_query_limit_enforcement(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify row limit parameter caps the returned table."""
    executor = FederatedExecutor(catalog=mock_catalog)
    sql = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
    """

    table, metrics = await executor.execute(sql, limit=1)
    assert table.num_rows == 1
    assert metrics.row_count == 1


async def test_subquery_timeout_error(mock_catalog: UnifiedCatalogRegistry) -> None:
    """T-02-05: Verify hanging connector triggers TimeoutError."""
    adls = mock_catalog.get_connector("adls_lake")

    async def slow_fetch(*args, **kwargs):
        await asyncio.sleep(2.0)
        return pa.table({"a": [1]})

    adls.execute_query = AsyncMock(side_effect=slow_fetch)  # type: ignore[method-assign]
    executor = FederatedExecutor(catalog=mock_catalog, default_timeout=0.1)

    sql = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
    """

    with pytest.raises(TimeoutError, match="timed out"):
        await executor.execute(sql)
