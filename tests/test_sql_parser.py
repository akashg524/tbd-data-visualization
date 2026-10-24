"""Unit tests for SQL AST parser and query decomposer."""

from __future__ import annotations

import pytest

from app.catalog import UnifiedCatalogRegistry
from app.connectors.iceberg_adls import IcebergADLSConnector
from app.connectors.models import ConnectionConfig
from app.connectors.oracle import OracleConnector
from app.connectors.sqlserver import SQLServerConnector
from app.federation.parser import SQLParser


@pytest.fixture
def mock_catalog() -> UnifiedCatalogRegistry:
    """Create a catalog pre-populated with mock connectors."""
    cat = UnifiedCatalogRegistry()
    cat.register_datasource(
        "adls_lake",
        IcebergADLSConnector(ConnectionConfig(name="adls_lake", datasource_type="adls_iceberg")),
    )
    cat.register_datasource(
        "oracle_dw",
        OracleConnector(ConnectionConfig(name="oracle_dw", datasource_type="oracle")),
    )
    cat.register_datasource(
        "mssql_dw",
        SQLServerConnector(ConnectionConfig(name="mssql_dw", datasource_type="sqlserver")),
    )
    return cat


def test_parse_single_source_query(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify single-source query parsing and classification."""
    sql = "SELECT trade_id, amount FROM adls_lake.equity.trades WHERE amount > 100 LIMIT 50"
    parsed = SQLParser.parse(sql, catalog=mock_catalog)

    assert not parsed.is_multi_source
    assert len(parsed.tables) == 1
    assert parsed.tables[0].datasource_name == "adls_lake"
    assert parsed.tables[0].schema_name == "equity"
    assert parsed.tables[0].table_name == "trades"
    assert parsed.tables[0].alias == "trades"
    assert parsed.limit == 50
    assert "trade_id" in parsed.columns_by_alias["trades"]
    assert "amount" in parsed.columns_by_alias["trades"]


def test_parse_multi_source_join(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify multi-source cross-database query parsing and alias resolution."""
    sql = """
        SELECT t.trade_id, c.name, t.amount
        FROM adls_lake.equity.trades AS t
        JOIN oracle_dw.risk.counterparties AS c ON t.counterparty_id = c.id
        WHERE t.amount > 500 AND c.country = 'US'
        ORDER BY t.trade_id DESC
        LIMIT 25
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)

    assert parsed.is_multi_source
    assert len(parsed.tables) == 2
    assert parsed.aliases["t"] == "adls_lake.equity.trades"
    assert parsed.aliases["c"] == "oracle_dw.risk.counterparties"

    assert parsed.table_refs["t"].dialect == "duckdb"
    assert parsed.table_refs["c"].dialect == "oracle"

    assert parsed.columns_by_alias["t"] == {"trade_id", "counterparty_id", "amount"}
    assert parsed.columns_by_alias["c"] == {"id", "name", "country"}
    assert parsed.limit == 25


def test_parse_three_source_join(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify multi-source join across three distinct systems (ADLS + Oracle + MSSQL)."""
    sql = """
        SELECT t.trade_id, c.name, a.account_code
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        JOIN mssql_dw.dbo.accounts a ON t.account_id = a.account_id
        WHERE c.country = 'US' AND a.balance_usd > 1000
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)

    assert parsed.is_multi_source
    assert len(parsed.tables) == 3
    assert set(parsed.aliases.keys()) == {"t", "c", "a"}
    assert parsed.table_refs["a"].dialect == "tsql"
    assert "account_code" in parsed.columns_by_alias["a"]
    assert "account_id" in parsed.columns_by_alias["a"]


def test_parse_star_expansion(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify unqualified and qualified star expansion."""
    sql_unqualified = "SELECT * FROM adls_lake.equity.trades"
    parsed_unq = SQLParser.parse(sql_unqualified, catalog=mock_catalog)
    assert "*" in parsed_unq.columns_by_alias["trades"]

    sql_qualified = """
        SELECT t.*, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
    """
    parsed_qual = SQLParser.parse(sql_qualified, catalog=mock_catalog)
    assert "*" in parsed_qual.columns_by_alias["t"]
    assert "name" in parsed_qual.columns_by_alias["c"]


def test_parse_group_by_and_aggregates(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify columns extracted across aggregates, GROUP BY, and HAVING."""
    sql = """
        SELECT c.country, SUM(t.amount) AS total_amount
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE t.trade_date >= '2026-01-01'
        GROUP BY c.country
        HAVING SUM(t.amount) > 1000000
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)

    assert "country" in parsed.columns_by_alias["c"]
    assert "amount" in parsed.columns_by_alias["t"]
    assert "trade_date" in parsed.columns_by_alias["t"]
    assert "counterparty_id" in parsed.columns_by_alias["t"]


def test_parse_with_cte(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify that CTE identifiers are not mistakenly treated as catalog tables."""
    sql = """
        WITH filtered_trades AS (
            SELECT trade_id, counterparty_id, amount
            FROM adls_lake.equity.trades
            WHERE amount > 500
        )
        SELECT f.trade_id, c.name
        FROM filtered_trades f
        JOIN oracle_dw.risk.counterparties c ON f.counterparty_id = c.id
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)

    # Only adls_lake and oracle_dw should be recognized as catalog tables
    recognized_datasources = {t.datasource_name for t in parsed.tables}
    assert recognized_datasources == {"adls_lake", "oracle_dw"}


def test_security_reject_mutations(mock_catalog: UnifiedCatalogRegistry) -> None:
    """T-02-01: Ensure mutations (INSERT, UPDATE, DELETE, DROP) are strictly rejected."""
    bad_queries = [
        "INSERT INTO adls_lake.equity.trades (trade_id) VALUES (1)",
        "UPDATE oracle_dw.risk.counterparties SET name = 'Hacked' WHERE id = 1",
        "DELETE FROM mssql_dw.dbo.accounts WHERE account_id = 1",
        "DROP TABLE adls_lake.equity.trades",
        "ALTER TABLE oracle_dw.risk.counterparties ADD COLUMN test VARCHAR(10)",
    ]
    for bad_sql in bad_queries:
        with pytest.raises(ValueError, match="Only read-only SELECT queries are allowed"):
            SQLParser.parse(bad_sql, catalog=mock_catalog)


def test_security_reject_dos_lengths() -> None:
    """T-02-02: Ensure excessively large queries trigger DoS protection."""
    huge_sql = "SELECT " + "a" * 60_000
    with pytest.raises(ValueError, match="exceeds maximum allowed limit"):
        SQLParser.parse(huge_sql)

    empty_sql = "   "
    with pytest.raises(ValueError, match="cannot be empty"):
        SQLParser.parse(empty_sql)


def test_unregistered_datasource_error(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify error on nonexistent catalog datasource."""
    sql = "SELECT * FROM non_existent_ds.schema1.table1"
    with pytest.raises(ValueError, match="is not registered in catalog"):
        SQLParser.parse(sql, catalog=mock_catalog)


def test_ambiguous_unqualified_column(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify error when column in multi-table join lacks table qualifier."""
    sql = """
        SELECT ambiguous_col
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
    """
    with pytest.raises(ValueError, match="Unqualified column 'ambiguous_col' in multi-table query"):
        SQLParser.parse(sql, catalog=mock_catalog)
