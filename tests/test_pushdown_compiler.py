"""Unit tests for pushdown predicate compiler and root query rewriting."""

from __future__ import annotations

import pytest

from app.catalog import UnifiedCatalogRegistry
from app.connectors.iceberg_adls import IcebergADLSConnector
from app.connectors.models import ConnectionConfig
from app.connectors.oracle import OracleConnector
from app.connectors.sqlserver import SQLServerConnector
from app.federation.compiler import PushdownCompiler
from app.federation.parser import SQLParser


@pytest.fixture
def mock_catalog() -> UnifiedCatalogRegistry:
    """Fixture providing catalog with ADLS, Oracle, and SQL Server."""
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


def test_pushdown_isolated_predicates(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify single-table isolated predicates are pushed down to respective subqueries."""
    sql = """
        SELECT t.trade_id, c.name, t.amount
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE t.amount > 1000
          AND t.trade_date >= '2026-01-01'
          AND c.country = 'US'
          AND c.credit_rating IN ('AAA', 'AA+')
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)
    subqueries, root_ast = PushdownCompiler.compile(parsed)

    # Subquery for trades (ADLS / DuckDB dialect)
    subq_t = subqueries["t"]
    assert subq_t.datasource_name == "adls_lake"
    assert "t.amount > 1000" in subq_t.sql
    assert "t.trade_date >= '2026-01-01'" in subq_t.sql
    assert "equity.trades" in subq_t.sql

    # Subquery for counterparties (Oracle dialect)
    subq_c = subqueries["c"]
    assert subq_c.datasource_name == "oracle_dw"
    assert "c.country = 'US'" in subq_c.sql
    assert "c.credit_rating IN ('AAA', 'AA+')" in subq_c.sql
    # Oracle dialect uses 'risk.counterparties c' without AS keyword
    assert "AS c" not in subq_c.sql
    assert "risk.counterparties c" in subq_c.sql

    # Root AST should have all isolated WHERE predicates removed
    root_sql = root_ast.sql(dialect="duckdb")
    assert "FROM __subq_t AS t JOIN __subq_c AS c ON t.counterparty_id = c.id" in root_sql
    assert "WHERE" not in root_sql


def test_mixed_predicates_retained_in_root_ast(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify cross-source predicates referencing multiple tables remain in DuckDB join AST."""
    sql = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE t.amount > 100
          AND c.country = 'US'
          AND t.amount > c.credit_limit
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)
    subqueries, root_ast = PushdownCompiler.compile(parsed)

    # Isolated predicates pushed down
    assert "t.amount > 100" in subqueries["t"].sql
    assert "c.country = 'US'" in subqueries["c"].sql

    # Mixed predicate retained in root DuckDB query
    root_sql = root_ast.sql(dialect="duckdb")
    assert "WHERE" in root_sql
    assert 't.amount > c.credit_limit' in root_sql
    assert "t.amount > 100" not in root_sql
    assert "c.country = 'US'" not in root_sql


def test_disjunction_handling(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify single-table OR conditions are pushed down, while cross-table ORs stay in root."""
    # Single-table OR
    sql_isolated_or = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE (t.status = 'SETTLED' OR t.status = 'PENDING')
          AND c.country = 'US'
    """
    parsed = SQLParser.parse(sql_isolated_or, catalog=mock_catalog)
    subqueries, root_ast = PushdownCompiler.compile(parsed)

    assert "t.status = 'SETTLED' OR t.status = 'PENDING'" in subqueries["t"].sql
    assert "WHERE" not in root_ast.sql(dialect="duckdb")

    # Cross-table OR
    sql_mixed_or = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE (t.status = 'PENDING' OR c.country = 'UK')
    """
    parsed_mixed = SQLParser.parse(sql_mixed_or, catalog=mock_catalog)
    _subqueries_mixed, root_ast_mixed = PushdownCompiler.compile(parsed_mixed)

    root_sql = root_ast_mixed.sql(dialect="duckdb")
    assert "WHERE" in root_sql
    assert "t.status = 'PENDING' OR c.country = 'UK'" in root_sql


def test_query_without_where_clause(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify query with no WHERE clause compiles cleanly without errors."""
    sql = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)
    subqueries, root_ast = PushdownCompiler.compile(parsed)

    assert "WHERE" not in subqueries["t"].sql
    assert "WHERE" not in subqueries["c"].sql
    assert "WHERE" not in root_ast.sql(dialect="duckdb")
    assert "FROM __subq_t AS t JOIN __subq_c AS c" in root_ast.sql(dialect="duckdb")


def test_compile_single_source_sql_oracle(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify single-source query bypass transpilation for Oracle."""
    sql = "SELECT id, name FROM oracle_dw.risk.counterparties WHERE status = 'ACTIVE' LIMIT 20"
    parsed = SQLParser.parse(sql, catalog=mock_catalog)
    native_sql = PushdownCompiler.compile_single_source_sql(parsed)

    # Oracle replaces LIMIT with FETCH FIRST
    assert "FETCH FIRST 20 ROWS ONLY" in native_sql
    assert "oracle_dw." not in native_sql
    assert "risk.counterparties" in native_sql


def test_compile_single_source_sql_mssql(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify single-source query bypass transpilation for SQL Server."""
    sql = "SELECT account_id, balance_usd FROM mssql_dw.dbo.accounts WHERE balance_usd > 5000 LIMIT 15"
    parsed = SQLParser.parse(sql, catalog=mock_catalog)
    native_sql = PushdownCompiler.compile_single_source_sql(parsed)

    # SQL Server replaces LIMIT with SELECT TOP
    assert "SELECT TOP 15" in native_sql
    assert "mssql_dw." not in native_sql
    assert "dbo.accounts" in native_sql


def test_compile_to_sql_helper(mock_catalog: UnifiedCatalogRegistry) -> None:
    """Verify compile_to_sql returns both subquery dictionary and DuckDB SQL string."""
    sql = """
        SELECT t.trade_id, c.name
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        WHERE t.amount > 100
        ORDER BY t.trade_id
    """
    parsed = SQLParser.parse(sql, catalog=mock_catalog)
    subqueries, root_sql = PushdownCompiler.compile_to_sql(parsed)

    assert isinstance(subqueries, dict)
    assert "t" in subqueries
    assert "c" in subqueries
    assert isinstance(root_sql, str)
    assert "ORDER BY t.trade_id" in root_sql
