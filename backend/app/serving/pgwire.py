"""PostgreSQL wire protocol gateway enabling Power BI DirectQuery without client drivers."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any

import duckdb
import structlog
from buenavista.backends.duckdb import DuckDBQueryResult, DuckDBSession
from buenavista.core import Connection, QueryResult, Session
from buenavista.postgres import BuenaVistaServer

from app.catalog import UnifiedCatalogRegistry
from app.catalog import catalog as default_catalog
from app.connectors.models import DataType
from app.federation.executor import FederatedExecutor
from app.federation.parser import SQLParser

logger = structlog.get_logger(__name__)

PG_TYPE_MAP: dict[DataType, str] = {
    DataType.INTEGER: "BIGINT",
    DataType.FLOAT: "DOUBLE",
    DataType.DECIMAL: "DECIMAL(18,4)",
    DataType.BOOLEAN: "BOOLEAN",
    DataType.TIMESTAMP: "TIMESTAMP",
    DataType.DATE: "DATE",
    DataType.JSON: "JSON",
    DataType.BINARY: "BLOB",
    DataType.STRING: "VARCHAR",
    DataType.UNKNOWN: "VARCHAR",
}


def run_async(coro: Any, loop: asyncio.AbstractEventLoop | None = None) -> Any:
    """Execute coroutine synchronously from thread-pool worker."""
    if loop is not None and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None

    if cur_loop and cur_loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    return asyncio.run(coro)


class FederatedSession(Session):
    """BuenaVista session routing metadata queries to DuckDB and analytical queries to FederatedExecutor."""

    def __init__(
        self,
        duck_session: DuckDBSession,
        executor: FederatedExecutor,
        catalog: UnifiedCatalogRegistry,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__()
        self.duck_session = duck_session
        self.executor = executor
        self.catalog = catalog
        self.loop = loop

    def in_transaction(self) -> bool:
        """Report whether session is inside an active transaction."""
        return self.duck_session.in_transaction()

    def cursor(self) -> Any:
        """Return underlying cursor."""
        return self.duck_session.cursor()

    def close(self) -> None:
        """Close underlying session cursor."""
        self.duck_session.close()

    def execute_sql(self, sql: str, params: Any = None) -> QueryResult:
        """Execute or route incoming SQL statements."""
        clean = sql.strip().rstrip(";")
        if not clean:
            return DuckDBQueryResult(status="")

        lsql = clean.lower()

        # 1. Connection configuration and transaction control
        txn_prefixes = ("set ", "show ", "reset ", "discard ", "deallocate ", "begin", "commit", "rollback")
        if lsql.startswith(txn_prefixes):
            return self.duck_session.execute_sql(clean, params)

        # 2. System and metadata queries (information_schema / pg_catalog / system functions)
        if (
            "information_schema." in lsql
            or "pg_catalog." in lsql
            or lsql.startswith(("select current_schema()", "select version()", "select current_setting"))
        ):
            return self.duck_session.execute_sql(clean, params)

        # 3. Check with SQLParser if query targets catalog datasources
        try:
            parsed = SQLParser.parse(clean, catalog=self.catalog)
        except Exception:
            # Fall back to DuckDB for any non-federated statements
            return self.duck_session.execute_sql(clean, params)

        if not parsed.tables:
            # Scalar query (e.g. SELECT 42)
            return self.duck_session.execute_sql(clean, params)

        # 4. Analytical federated query: execute via FederatedExecutor
        logger.info("pgwire_dispatch_analytical_query", sql=clean)
        try:
            table, _metrics = run_async(self.executor.execute(clean), self.loop)
            return DuckDBQueryResult(table.to_reader())
        except Exception as exc:
            logger.error("pgwire_query_failed", sql=clean, error=str(exc))
            raise


class FederatedConnection(Connection):
    """BuenaVista connection factory providing PostgreSQL parameters and FederatedSession."""

    def __init__(
        self,
        catalog_db: duckdb.DuckDBPyConnection,
        executor: FederatedExecutor,
        catalog: UnifiedCatalogRegistry,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        super().__init__()
        self.catalog_db = catalog_db
        self.executor = executor
        self.catalog = catalog
        self.loop = loop

    def parameters(self) -> dict[str, str]:
        """PostgreSQL startup parameters expected by Power BI and standard drivers."""
        return {
            "server_version": "14.0.federated",
            "client_encoding": "UTF8",
            "DateStyle": "ISO",
            "standard_conforming_strings": "on",
        }

    def new_session(self) -> Session:
        """Create a new FederatedSession with a cursor from the shadow catalog database."""
        cursor = self.catalog_db.cursor()
        cursor.execute("SET search_path='main'")
        duck_session = DuckDBSession(cursor)
        return FederatedSession(duck_session, self.executor, self.catalog, self.loop)


class PostgresWireServer:
    """PostgreSQL v3.0 wire protocol gateway for Power BI DirectQuery."""

    def __init__(
        self,
        host: str = "0.0.0.0",  # noqa: S104
        port: int = 5433,
        executor: FederatedExecutor | None = None,
        catalog: UnifiedCatalogRegistry | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.catalog = catalog or default_catalog
        if executor is not None:
            self.executor = executor
        else:
            from app.api.query import federated_executor
            self.executor = federated_executor

        self.loop = loop
        self.catalog_db = duckdb.connect()
        self.sync_catalog_schemas()

        self.conn = FederatedConnection(self.catalog_db, self.executor, self.catalog, self.loop)
        self.server = BuenaVistaServer((self.host, self.port), self.conn)
        self._thread: threading.Thread | None = None

    def sync_catalog_schemas(self) -> None:
        """Populate DuckDB shadow schema tables and views for Navigator introspection."""
        tree = self.catalog.get_unified_tree()

        for ds_name, ds_info in tree.items():
            schemas = ds_info.get("schemas", {})
            for schema_name, schema_info in schemas.items():
                tables = schema_info.get("tables", [])
                self.catalog_db.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

                for tbl in tables:
                    tname = tbl.get("name", "")
                    full_path = f"{ds_name}.{schema_name}.{tname}"
                    cached_schema = self.catalog._table_cache.get(full_path)

                    col_defs_list: list[str] = []
                    if cached_schema and cached_schema.columns:
                        for c in cached_schema.columns:
                            col_type = PG_TYPE_MAP.get(c.data_type, "VARCHAR")
                            col_defs_list.append(f'"{c.name}" {col_type}')
                    else:
                        col_defs_list = ['"id" VARCHAR', '"data" VARCHAR']

                    col_defs = ", ".join(col_defs_list)
                    self.catalog_db.execute(
                        f'CREATE TABLE IF NOT EXISTS {schema_name}.{tname} ({col_defs})'
                    )

    def start(self) -> None:
        """Start BuenaVista TCP socket server on background daemon thread."""
        logger.info("starting_pgwire_gateway", host=self.host, port=self.port)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("pgwire_gateway_running", host=self.host, port=self.port)

    def stop(self) -> None:
        """Gracefully shut down wire server and release TCP socket and catalog DB."""
        logger.info("stopping_pgwire_gateway", port=self.port)
        self.server.shutdown()
        self.server.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.catalog_db.close()
        logger.info("pgwire_gateway_stopped")
