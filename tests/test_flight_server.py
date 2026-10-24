"""Integration tests for Apache Arrow Flight columnar server over gRPC."""

from __future__ import annotations

import time

import duckdb
import pyarrow as pa
import pyarrow.flight as fl
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
from app.serving.flight import FederatedFlightServer

FLIGHT_TEST_PORT = 5007


@pytest.fixture
def flight_catalog() -> UnifiedCatalogRegistry:
    """Catalog pre-populated with ADLS and Oracle mock connectors."""
    cat = UnifiedCatalogRegistry()

    # ADLS DuckDB backend
    duck_adls = duckdb.connect()
    adls_data = pa.table(
        {
            "trade_id": [1, 2, 3],
            "counterparty_id": [101, 102, 103],
            "amount": [1500.0, 2500.0, 500.0],
        }
    )
    duck_adls.register("trades_raw", adls_data)
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

    # Oracle DuckDB backend
    duck_ora = duckdb.connect()
    ora_data = pa.table(
        {
            "id": [101, 102, 104],
            "name": ["Alpha Corp", "Beta LLC", "Gamma Inc"],
            "country": ["US", "US", "UK"],
        }
    )
    duck_ora.register("cp_raw", ora_data)
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

    return cat


@pytest.fixture
def flight_server(flight_catalog: UnifiedCatalogRegistry):
    """Start FederatedFlightServer on test port 5006 and stop after tests."""
    cache = ResultCache(default_ttl=60)
    executor = FederatedExecutor(catalog=flight_catalog, cache=cache)
    server = FederatedFlightServer(
        host="127.0.0.1",
        port=FLIGHT_TEST_PORT,
        executor=executor,
        catalog=flight_catalog,
    )
    server.start_background()
    time.sleep(0.3)

    yield server

    server.stop()
    time.sleep(0.2)


@pytest.fixture
def flight_client(flight_server: FederatedFlightServer):
    """Provide connected Arrow FlightClient."""
    client = fl.connect(f"grpc+tcp://127.0.0.1:{FLIGHT_TEST_PORT}")
    yield client
    client.close()


def test_flight_list_flights(flight_client: fl.FlightClient) -> None:
    """Verify list_flights yields flight descriptors for catalog tables."""
    flights = list(flight_client.list_flights())
    assert len(flights) >= 2
    paths = [f.descriptor.path for f in flights]
    assert [b"equity", b"trades"] in paths
    assert [b"risk", b"counterparties"] in paths


def test_flight_get_flight_info(flight_client: fl.FlightClient) -> None:
    """Verify get_flight_info returns table schema and endpoints."""
    desc = fl.FlightDescriptor.for_path("equity", "trades")
    info = flight_client.get_flight_info(desc)
    assert info is not None
    assert "trade_id" in info.schema.names
    assert "amount" in info.schema.names
    assert len(info.endpoints) >= 1


def test_flight_do_get_single_source(flight_client: fl.FlightClient) -> None:
    """Verify do_get streams Arrow record batches for single-source queries."""
    ticket = fl.Ticket(b"SELECT trade_id, amount FROM adls_lake.equity.trades WHERE amount > 1000")
    reader = flight_client.do_get(ticket)
    arrow_table = reader.read_all()
    assert arrow_table.num_rows == 2
    assert arrow_table.column_names == ["trade_id", "amount"]
    pydict = arrow_table.to_pydict()
    assert pydict["trade_id"] == [1, 2]
    assert pydict["amount"] == [1500.0, 2500.0]


def test_flight_do_get_federated_join(flight_client: fl.FlightClient) -> None:
    """Verify do_get streams zero-copy Arrow record batches for cross-source joins."""
    sql = """
        SELECT t.trade_id, c.name, t.amount
        FROM adls_lake.equity.trades t
        JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
        ORDER BY t.trade_id
    """
    ticket = fl.Ticket(sql.encode("utf-8"))
    reader = flight_client.do_get(ticket)
    arrow_table = reader.read_all()
    assert arrow_table.num_rows == 2
    assert arrow_table.column_names == ["trade_id", "name", "amount"]
    pydict = arrow_table.to_pydict()
    assert pydict["name"] == ["Alpha Corp", "Beta LLC"]
