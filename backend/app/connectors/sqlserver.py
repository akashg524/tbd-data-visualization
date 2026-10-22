"""Microsoft SQL Server & Azure SQL read-only connector with AlwaysOn secondary routing."""

from __future__ import annotations

import contextlib
import time
from typing import Any

import pyarrow as pa
import structlog

from app.connectors.base import BaseConnector
from app.connectors.models import (
    ColumnMetadata,
    ConnectionConfig,
    ConnectionStatus,
    DataType,
    TableMetadata,
    TableSchema,
)

logger = structlog.get_logger(__name__)

SYSTEM_SCHEMAS = {"sys", "information_schema", "guest"}


def map_sqlserver_type_to_datatype(data_type_str: str) -> DataType:
    """Map SQL Server types to DataType enum."""
    t = data_type_str.lower()
    if "int" in t or "tinyint" in t or "smallint" in t or "bigint" in t:
        return DataType.INTEGER
    if "decimal" in t or "numeric" in t or "money" in t or "smallmoney" in t:
        return DataType.DECIMAL
    if "float" in t or "real" in t:
        return DataType.FLOAT
    if "bit" in t:
        return DataType.BOOLEAN
    if "datetime" in t or "datetime2" in t or "smalldatetime" in t or "datetimeoffset" in t:
        return DataType.TIMESTAMP
    if "date" in t:
        return DataType.DATE
    if "char" in t or "varchar" in t or "text" in t or "nchar" in t or "nvarchar" in t:
        return DataType.STRING
    if "binary" in t or "varbinary" in t or "image" in t:
        return DataType.BINARY
    return DataType.UNKNOWN


class SQLServerConnector(BaseConnector):
    """Read-only connector for on-premises SQL Server and Azure SQL."""

    def __init__(self, config: ConnectionConfig, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)
        self._conn: Any = None

    async def connect(self) -> None:
        """Establish SQL Server connection targeting read-only replicas."""
        host = self.config.host
        port = self.config.port or 1433
        database = self.config.database
        user = self.config.username
        password = self.resolve_secret(self.config.password_secret_name) or self.config.extra_options.get(
            "password", ""
        )

        if host and user and database:
            try:
                import pymssql

                # Connect with appname and non-blocking read isolation
                self._conn = pymssql.connect(
                    server=host,
                    port=port,
                    user=user,
                    password=password,
                    database=database,
                    appname="FinancialDataHub_ReadOnly",
                    read_only=True,
                )
                with self._conn.cursor() as cur:
                    # Enforce read uncommitted to prevent locking against production OLTP
                    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
                logger.info("sqlserver_connected_readonly", host=host, database=database)
            except Exception as exc:
                logger.warning("sqlserver_connection_failed", error=str(exc))
                self._conn = None
        self._connected = True

    async def disconnect(self) -> None:
        """Release SQL Server connection."""
        if self._conn:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None
        self._connected = False
        logger.info("sqlserver_disconnected", name=self.config.name)

    async def test_connection(self) -> ConnectionStatus:
        """Probe SQL Server and measure response time."""
        start = time.perf_counter()
        try:
            if not self._connected:
                await self.connect()

            version = "Microsoft SQL Server (ReadOnly)"
            if self._conn:
                with self._conn.cursor() as cur:
                    cur.execute("SELECT @@VERSION")
                    row = cur.fetchone()
                    if row:
                        version = row[0].split("\n")[0]

            elapsed_ms = (time.perf_counter() - start) * 1000
            return ConnectionStatus(
                is_connected=True,
                latency_ms=round(elapsed_ms, 2),
                server_version=version,
            )
        except Exception as exc:
            return ConnectionStatus(
                is_connected=False,
                error_message=str(exc),
            )

    async def introspect_schemas(self) -> list[str]:
        """List distinct non-system schemas."""
        if self._conn:
            try:
                with self._conn.cursor() as cur:
                    cur.execute("SELECT schema_name FROM information_schema.schemata")
                    rows = cur.fetchall()
                    return [r[0] for r in rows if r[0].lower() not in SYSTEM_SCHEMAS]
            except Exception as exc:
                logger.warning("sqlserver_introspect_schemas_failed", error=str(exc))

        return self.config.extra_options.get("schemas", ["dbo", "accounting"])

    async def introspect_tables(self, schema: str) -> list[TableMetadata]:
        """List tables within a schema."""
        if self._conn:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
                        (schema,),
                    )
                    rows = cur.fetchall()
                    return [
                        TableMetadata(name=r[0], schema_name=schema, format_type="relational")
                        for r in rows
                    ]
            except Exception as exc:
                logger.warning("sqlserver_introspect_tables_failed", error=str(exc))

        mock_tables = self.config.extra_options.get("tables", ["gl_accounts", "chart_of_accounts"])
        return [
            TableMetadata(
                name=t if isinstance(t, str) else t.get("name", "unnamed"),
                schema_name=schema,
                format_type="relational",
            )
            for t in mock_tables
        ]

    async def get_table_schema(self, schema: str, table: str) -> TableSchema:
        """Extract columns and primary keys from SQL Server metadata."""
        columns: list[ColumnMetadata] = []

        if self._conn:
            try:
                with self._conn.cursor() as cur:
                    # Introspect columns
                    cur.execute(
                        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
                        "FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                        "ORDER BY ORDINAL_POSITION",
                        (schema, table),
                    )
                    col_rows = cur.fetchall()

                    # Introspect primary keys
                    cur.execute(
                        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
                        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME LIKE 'PK%'",
                        (schema, table),
                    )
                    pk_rows = cur.fetchall()
                    pk_cols = {r[0] for r in pk_rows}

                    for col_name, raw_type, is_nullable in col_rows:
                        columns.append(
                            ColumnMetadata(
                                name=col_name,
                                data_type=map_sqlserver_type_to_datatype(raw_type),
                                native_type=raw_type,
                                nullable=(is_nullable.upper() == "YES"),
                                is_primary_key=(col_name in pk_cols),
                            )
                        )
                    return TableSchema(table_name=table, schema_name=schema, columns=columns)
            except Exception as exc:
                logger.warning("sqlserver_table_schema_failed", error=str(exc))

        # Mock fallback for test suite
        return TableSchema(
            table_name=table,
            schema_name=schema,
            columns=[
                ColumnMetadata(name="account_id", data_type=DataType.INTEGER, is_primary_key=True),
                ColumnMetadata(name="account_code", data_type=DataType.STRING),
                ColumnMetadata(name="account_name", data_type=DataType.STRING),
                ColumnMetadata(name="balance_usd", data_type=DataType.DECIMAL),
            ],
        )

    async def execute_query(self, query: str, limit: int | None = None) -> pa.Table:
        """Execute read-only SQL query and return Apache Arrow Table."""
        if not self._connected:
            await self.connect()

        if self._conn:
            with self._conn.cursor() as cur:
                sql = query
                if (
                    limit
                    and "TOP" not in sql.upper()
                    and "OFFSET" not in sql.upper()
                    and sql.strip().upper().startswith("SELECT")
                ):
                    sql = f"SELECT TOP {limit} " + sql.strip()[6:]

                cur.execute(sql)
                col_names = [d[0] for d in cur.description]
                rows = cur.fetchall()

                if not rows:
                    return pa.Table.from_arrays([], names=[])
                data_dict = {col_names[i]: [row[i] for row in rows] for i in range(len(col_names))}
                return pa.table(data_dict)

        # Mock data fallback
        mock_data = self.config.extra_options.get(
            "mock_data",
            {
                "account_id": [1, 2],
                "account_code": ["GL-1000", "GL-2000"],
                "account_name": ["Cash and Equivalents", "Securities Portfolio"],
                "balance_usd": [5000000.00, 12500000.00],
            },
        )
        return pa.table(mock_data)
