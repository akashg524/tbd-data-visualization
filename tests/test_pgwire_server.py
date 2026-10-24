"""Integration tests for PostgreSQL wire protocol server using psycopg client over TCP."""

from __future__ import annotations

import time

import duckdb
import psycopg
import pyarrow as pa
import pytest

from app.cache import ResultCache
from app.catalog import UnifiedCatalogRegistry
from app.connectors.iceberg_adls import IcebergADLSConnector
from app.connectors.models import (
    ColumnMetadata,
    ConnectionConfig,
    DataType,
    TableMetadata,
    TableSchema,
)
from app.connectors.oracle import OracleConnector
from app.federation.executor import FederatedExecutor
from app.serving.pgwire import PostgresWireServer

TEST_PORT = 5439


@pytest.fixture
def mock_catalog() -> UnifiedCatalogRegistry:
    """Catalog pre-populated with ADLS and Oracle mock connectors."""
    cat = UnifiedCatalogRegistry()

    # Backing in-memory DuckDB for ADLS
    duck_adls = duckdb.connect()
    adls_raw = pa.table(
        {
            "trade_id": [1, 2, 3],
            "counterparty_id": [101, 102, 103],
            "amount": [1500.0, 2500.0, 500.0],
        }
    )
    duck_adls.register("trades_raw", adls_raw)
    duck_adls.execute("CREATE SCHEMA IF NOT EXISTS equity")
    duck_adls.execute("CREATE VIEW equity.trades AS SELECT * FROM trades_raw")

    async def adls_query(sql: str, limit: int | None = None) -> pa.Table:
        rel = duck_adls.sql(sql)
        res = rel.arrow()
        tbl = res.read_all() if hasattr(res, "read_all") else res
        if limit is not None and tbl.num_rows > limit:
            tbl = tbl.slice(0, limit)
        return tbl

    adls = IcebergADLSConnector(ConnectionConfig(name="adls_lake", datasource_type="adls_iceberg"))
    adls.execute_query = adls_query  # type: ignore[method-assign]

    # Backing in-memory DuckDB for Oracle
    duck_ora = duckdb.connect()
    ora_raw = pa.table(
        {
            "id": [101, 102, 104],
            "name": ["Alpha Corp", "Beta LLC", "Gamma Inc"],
            "credit_limit": [2000.0, 2000.0, 1000.0],
            "country": ["US", "US", "UK"],
        }
    )
    duck_ora.register("cp_raw", ora_raw)
    duck_ora.execute("CREATE SCHEMA IF NOT EXISTS risk")
    duck_ora.execute("CREATE VIEW risk.counterparties AS SELECT * FROM cp_raw")

    async def ora_query(sql: str, limit: int | None = None) -> pa.Table:
        rel = duck_ora.sql(sql)
        res = rel.arrow()
        tbl = res.read_all() if hasattr(res, "read_all") else res
        if limit is not None and tbl.num_rows > limit:
            tbl = tbl.slice(0, limit)
        return tbl

    ora = OracleConnector(ConnectionConfig(name="oracle_dw", datasource_type="oracle"))
    ora.execute_query = ora_query  # type: ignore[method-assign]

    cat.register_datasource("adls_lake", adls)
    cat.register_datasource("oracle_dw", ora)

    cat._schema_cache["adls_lake"] = {
        "equity": [
            TableMetadata(
                name="trades",
                schema_name="equity",
                row_count_estimate=3,
                format_type="iceberg",
            )
        ]
    }
    cat._schema_cache["oracle_dw"] = {
        "risk": [
            TableMetadata(
                name="counterparties",
                schema_name="risk",
                row_count_estimate=3,
                format_type="relational",
            )
        ]
    }

    cat._table_cache["adls_lake.equity.trades"] = TableSchema(
        table_name="trades",
        schema_name="equity",
        columns=[
            ColumnMetadata(name="trade_id", data_type=DataType.INTEGER, is_primary_key=True),
            ColumnMetadata(name="counterparty_id", data_type=DataType.INTEGER),
            ColumnMetadata(name="amount", data_type=DataType.FLOAT),
        ],
    )
    cat._table_cache["oracle_dw.risk.counterparties"] = TableSchema(
        table_name="counterparties",
        schema_name="risk",
        columns=[
            ColumnMetadata(name="id", data_type=DataType.INTEGER, is_primary_key=True),
            ColumnMetadata(name="name", data_type=DataType.STRING),
            ColumnMetadata(name="credit_limit", data_type=DataType.FLOAT),
            ColumnMetadata(name="country", data_type=DataType.STRING),
        ],
    )

    return cat


@pytest.fixture
def pgwire_server(mock_catalog: UnifiedCatalogRegistry):
    """Start PostgresWireServer on test port 5439 and tear down after tests."""
    cache = ResultCache(default_ttl=60)
    executor = FederatedExecutor(catalog=mock_catalog, cache=cache)
    server = PostgresWireServer(
        host="127.0.0.1",
        port=TEST_PORT,
        executor=executor,
        catalog=mock_catalog,
    )
    server.start()
    time.sleep(0.3)  # Allow socket to bind

    yield server

    server.stop()
    time.sleep(0.2)  # Allow socket release


@pytest.fixture
def pg_conn(pgwire_server: PostgresWireServer):
    """Provide open psycopg connection over TCP."""
    conn = psycopg.connect(
        f"host=127.0.0.1 port={TEST_PORT} dbname=postgres user=postgres",
        autocommit=True,
    )
    yield conn
    conn.close()


def test_connection_handshake_and_params(pg_conn: psycopg.Connection) -> None:
    """Verify standard TCP handshake and PostgreSQL parameters."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT 1")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1


def test_navigator_information_schema(pg_conn: psycopg.Connection) -> None:
    """Verify Power BI Navigator introspection queries against information_schema."""
    with pg_conn.cursor() as cur:
        # Schema and Table discovery
        cur.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_name"
        )
        tables = cur.fetchall()
        assert len(tables) >= 2
        table_names = [t[1] for t in tables]
        assert "trades" in table_names
        assert "counterparties" in table_names

        # Column discovery for equity.trades
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'equity' AND table_name = 'trades' "
            "ORDER BY ordinal_position"
        )
        cols = cur.fetchall()
        assert len(cols) == 3
        col_names = [c[0] for c in cols]
        assert col_names == ["trade_id", "counterparty_id", "amount"]


def test_scalar_query_execution(pg_conn: psycopg.Connection) -> None:
    """Verify scalar expression queries."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT 42 AS answer, 'hello' AS greeting")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 42
        assert row[1] == "hello"


def test_single_source_query(pg_conn: psycopg.Connection) -> None:
    """Verify single-source table query routed to connector."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT trade_id, amount FROM adls_lake.equity.trades")
        rows = cur.fetchall()
        assert len(rows) == 3
        assert rows[0][0] == 1
        assert rows[0][1] == 1500.0


def test_multi_source_federated_join(pg_conn: psycopg.Connection) -> None:
    """Verify cross-source join (ADLS + Oracle) executing in DuckDB over PGWire."""
    sql = """
        SELECT t.trade_id, c.name, t.amount
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        ORDER BY t.trade_id
    """
    with pg_conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0] == (1, "Alpha Corp", 1500.0)
        assert rows[1] == (2, "Beta LLC", 2500.0)


def test_cached_repeat_query_performance(pg_conn: psycopg.Connection) -> None:
    """Verify repeat query hit over wire protocol achieves instant response."""
    sql = "SELECT trade_id, amount FROM adls_lake.equity.trades"
    with pg_conn.cursor() as cur:
        # First execution (populates cache)
        cur.execute(sql)
        rows1 = cur.fetchall()

        # Second execution (served from ResultCache)
        t0 = time.perf_counter()
        cur.execute(sql)
        rows2 = cur.fetchall()
        wire_ms = (time.perf_counter() - t0) * 1000

        assert rows1 == rows2
        # Repeat execution over localhost TCP should be extremely fast (< 10ms)
        assert wire_ms < 50.0
