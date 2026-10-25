"""Apache Arrow Flight server providing multi-GB/s columnar batch transport over gRPC."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pyarrow as pa
import pyarrow.flight as fl
import structlog

from app.auth.governance import SecurityContext
from app.catalog import UnifiedCatalogRegistry
from app.catalog import catalog as default_catalog
from app.connectors.models import DataType
from app.federation.executor import FederatedExecutor
from app.serving.pgwire import run_async

logger = structlog.get_logger(__name__)

ARROW_TYPE_MAP: dict[DataType, pa.DataType] = {
    DataType.INTEGER: pa.int64(),
    DataType.FLOAT: pa.float64(),
    DataType.DECIMAL: pa.decimal128(18, 4),
    DataType.BOOLEAN: pa.bool_(),
    DataType.TIMESTAMP: pa.timestamp("ms"),
    DataType.DATE: pa.date32(),
    DataType.JSON: pa.string(),
    DataType.BINARY: pa.binary(),
    DataType.STRING: pa.string(),
    DataType.UNKNOWN: pa.string(),
}


class FederatedFlightServer(fl.FlightServerBase):
    """High-throughput Arrow Flight gRPC server serving federated datasets."""

    def __init__(
        self,
        host: str = "0.0.0.0",  # noqa: S104
        port: int = 5005,
        executor: FederatedExecutor | None = None,
        catalog: UnifiedCatalogRegistry | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        location = f"grpc+tcp://{host}:{port}"
        super().__init__(location)
        self.host = host
        self.catalog = catalog or default_catalog
        if executor is not None:
            self.executor = executor
        else:
            from app.api.query import federated_executor
            self.executor = federated_executor

        self.loop = loop
        self._thread: threading.Thread | None = None

    def list_flights(self, context: Any, criteria: Any) -> Any:
        """Enumerate available catalog tables as queryable flight streams."""
        tree = self.catalog.get_unified_tree()

        for ds_name, ds_info in tree.items():
            schemas = ds_info.get("schemas", {})
            for schema_name, schema_info in schemas.items():
                tables = schema_info.get("tables", [])
                for tbl in tables:
                    tname = tbl.get("name", "")
                    full_path = f"{ds_name}.{schema_name}.{tname}"
                    cached_schema = self.catalog._table_cache.get(full_path)

                    fields: list[pa.Field] = []
                    if cached_schema and cached_schema.columns:
                        for c in cached_schema.columns:
                            pa_type = ARROW_TYPE_MAP.get(c.data_type, pa.string())
                            fields.append(pa.field(c.name, pa_type, nullable=c.nullable))
                    else:
                        fields = [pa.field("id", pa.string()), pa.field("data", pa.string())]

                    schema = pa.schema(fields)
                    descriptor = fl.FlightDescriptor.for_path(schema_name, tname)
                    ticket = fl.Ticket(f"SELECT * FROM {full_path}".encode())  # noqa: S608  # noqa: S608
                    endpoint = fl.FlightEndpoint(ticket, [fl.Location.for_grpc_tcp(self.host, self.port)])
                    yield fl.FlightInfo(schema, descriptor, [endpoint], -1, -1)

    def get_flight_info(self, context: Any, descriptor: fl.FlightDescriptor) -> fl.FlightInfo:
        """Return schema and connection endpoints for a requested flight dataset."""
        if not descriptor.path:
            raise fl.FlightServerError("Invalid flight descriptor: empty path.")

        path_parts = [p.decode("utf-8") if isinstance(p, bytes) else str(p) for p in descriptor.path]
        if len(path_parts) == 1:
            schema_name, table_name = "default", path_parts[0]
        else:
            schema_name, table_name = path_parts[-2], path_parts[-1]

        # Locate full path in catalog
        full_path = f"{schema_name}.{table_name}"
        tree = self.catalog.get_unified_tree()
        for ds_name, ds_info in tree.items():
            schemas = ds_info.get("schemas", {})
            if schema_name in schemas:
                for tbl in schemas[schema_name].get("tables", []):
                    if tbl.get("name", "").lower() == table_name.lower():
                        full_path = f"{ds_name}.{schema_name}.{table_name}"
                        break

        cached_schema = self.catalog._table_cache.get(full_path)
        fields: list[pa.Field] = []
        if cached_schema and cached_schema.columns:
            for c in cached_schema.columns:
                pa_type = ARROW_TYPE_MAP.get(c.data_type, pa.string())
                fields.append(pa.field(c.name, pa_type, nullable=c.nullable))
        else:
            fields = [pa.field("id", pa.string()), pa.field("data", pa.string())]

        schema = pa.schema(fields)
        ticket = fl.Ticket(f"SELECT * FROM {full_path}".encode())  # noqa: S608
        endpoint = fl.FlightEndpoint(ticket, [fl.Location.for_grpc_tcp(self.host, self.port)])
        return fl.FlightInfo(schema, descriptor, [endpoint], -1, -1)

    def do_get(self, context: Any, ticket: fl.Ticket) -> fl.FlightDataStream:
        """Execute analytical query embedded in ticket and stream Arrow record batches."""
        sql = ticket.ticket.decode("utf-8").strip()
        if not sql:
            raise fl.FlightServerError("Empty query string received in ticket.")

        sec_context = getattr(context, "security_context", None)
        if sec_context is None:
            sec_context = SecurityContext(
                user_id="flight_analyst",
                username="flight_analyst@contoso.com",
                roles=["FinancialAnalyst"],
                trading_desks=["FX", "EQUITIES"],
                regions=["US", "EMEA"],
                allowed_accounts=["ACC-001", "ACC-002"],
            )

        logger.info("flight_executing_query", sql=sql)
        try:
            arrow_table, _metrics = run_async(
                self.executor.execute(sql, security_context=sec_context, protocol="Flight"),
                self.loop,
            )
            return fl.RecordBatchStream(arrow_table)
        except Exception as exc:
            logger.error("flight_query_execution_failed", sql=sql, error=str(exc))
            raise fl.FlightServerError(f"Flight query execution failed: {exc}") from exc

    def start_background(self) -> None:
        """Start Flight gRPC server on a background daemon thread."""
        logger.info("starting_arrow_flight_server", host=self.host, port=self.port)
        self._thread = threading.Thread(target=self.serve, daemon=True)
        self._thread.start()
        logger.info("arrow_flight_server_running", host=self.host, port=self.port)

    def stop(self) -> None:
        """Gracefully terminate gRPC listener and join thread."""
        logger.info("stopping_arrow_flight_server", port=self.port)
        self.shutdown()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("arrow_flight_server_stopped")
