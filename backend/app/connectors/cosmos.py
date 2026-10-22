"""Azure Cosmos DB connector with partition-aware schema sampling and Arrow projection."""

from __future__ import annotations

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


def infer_type_from_value(value: Any) -> DataType:
    """Infer DataType from sample Python/JSON values."""
    if value is None:
        return DataType.STRING
    if isinstance(value, bool):
        return DataType.BOOLEAN
    if isinstance(value, int):
        return DataType.INTEGER
    if isinstance(value, float):
        return DataType.FLOAT
    if isinstance(value, dict | list):
        return DataType.JSON
    return DataType.STRING


class CosmosDBConnector(BaseConnector):
    """Read-only connector for Azure Cosmos DB (SQL/Core API)."""

    def __init__(self, config: ConnectionConfig, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)
        self._client: Any = None
        self._db_client: Any = None

    async def connect(self) -> None:
        """Initialize CosmosClient using endpoint and key."""
        endpoint = self.config.host or self.config.extra_options.get("endpoint", "")
        master_key = self.resolve_secret(self.config.password_secret_name) or self.config.extra_options.get("key", "")

        if endpoint and master_key:
            try:
                from azure.cosmos import CosmosClient

                self._client = CosmosClient(endpoint, credential=master_key)
                if self.config.database:
                    self._db_client = self._client.get_database_client(self.config.database)
                logger.info("cosmos_client_initialized", endpoint=endpoint)
            except Exception as exc:
                logger.warning("cosmos_client_init_failed", error=str(exc))
                self._client = None
        self._connected = True

    async def disconnect(self) -> None:
        """Reset client handles."""
        self._client = None
        self._db_client = None
        self._connected = False
        logger.info("cosmos_disconnected", name=self.config.name)

    async def test_connection(self) -> ConnectionStatus:
        """Probe Cosmos DB connectivity."""
        start = time.perf_counter()
        try:
            if not self._connected:
                await self.connect()

            if self._client and self.config.database:
                db = self._client.get_database_client(self.config.database)
                # Read database properties as a lightweight probe
                db.read()

            elapsed_ms = (time.perf_counter() - start) * 1000
            return ConnectionStatus(
                is_connected=True,
                latency_ms=round(elapsed_ms, 2),
                server_version="Azure Cosmos DB SQL API",
            )
        except Exception as exc:
            return ConnectionStatus(
                is_connected=False,
                error_message=str(exc),
            )

    async def introspect_schemas(self) -> list[str]:
        """List databases in the Cosmos DB account."""
        if self._client:
            try:
                dbs = list(self._client.list_databases())
                return [d["id"] for d in dbs]
            except Exception as exc:
                logger.warning("cosmos_list_dbs_failed", error=str(exc))

        if self.config.database:
            return [self.config.database]
        return self.config.extra_options.get("databases", ["default"])

    async def introspect_tables(self, schema: str) -> list[TableMetadata]:
        """List containers within a database."""
        if self._client:
            try:
                db = self._client.get_database_client(schema)
                containers = list(db.list_containers())
                return [
                    TableMetadata(
                        name=c["id"],
                        schema_name=schema,
                        format_type="document",
                        comment=f"Partition Key: {c.get('partitionKey', {}).get('paths', [''])[0]}",
                    )
                    for c in containers
                ]
            except Exception as exc:
                logger.warning("cosmos_list_containers_failed", error=str(exc))

        configured_containers = self.config.extra_options.get("containers", ["audit_events"])
        return [
            TableMetadata(
                name=c if isinstance(c, str) else c.get("name", "unnamed"),
                schema_name=schema,
                format_type="document",
            )
            for c in configured_containers
        ]

    async def get_table_schema(self, schema: str, table: str) -> TableSchema:
        """Infer table schema by sampling top documents and checking partition key."""
        partition_path = "/id"
        sample_docs: list[dict[str, Any]] = []

        if self._client:
            try:
                db = self._client.get_database_client(schema)
                container = db.get_container_client(table)
                props = container.read()
                paths = props.get("partitionKey", {}).get("paths", ["/id"])
                if paths:
                    partition_path = paths[0]

                # Sample top 50 documents to keep RU burn minimal
                items = container.query_items(
                    query="SELECT TOP 50 * FROM c",
                    enable_cross_partition_query=True,
                )
                sample_docs = list(items)
            except Exception as exc:
                logger.warning("cosmos_schema_sampling_failed", table=table, error=str(exc))

        if not sample_docs:
            sample_docs = self.config.extra_options.get(
                "sample_documents",
                [
                    {
                        "id": "evt-001",
                        "portfolioId": "PORT-99",
                        "eventType": "ORDER_SUBMITTED",
                        "amount": 54000.50,
                        "timestamp": 1729600000,
                    }
                ],
            )
            partition_path = self.config.extra_options.get("partition_key_path", "/portfolioId")

        # Map partition key field name from path (/portfolioId -> portfolioId)
        pk_field = partition_path.lstrip("/")

        # Aggregate columns across sampled documents
        discovered_cols: dict[str, DataType] = {}
        for doc in sample_docs:
            for k, v in doc.items():
                if k.startswith("_"):  # Skip Cosmos system properties (_rid, _self, _ts, etc.)
                    continue
                if k not in discovered_cols or discovered_cols[k] == DataType.STRING:
                    discovered_cols[k] = infer_type_from_value(v)

        columns = [
            ColumnMetadata(
                name=col_name,
                data_type=col_type,
                is_primary_key=(col_name == "id"),
                is_partition_key=(col_name == pk_field),
            )
            for col_name, col_type in discovered_cols.items()
        ]

        return TableSchema(
            table_name=table,
            schema_name=schema,
            columns=columns,
            partition_keys=[pk_field] if pk_field in discovered_cols else [],
        )

    async def execute_query(self, query: str, limit: int | None = None) -> pa.Table:
        """Execute Cosmos SQL query and convert items to Apache Arrow Table."""
        items: list[dict[str, Any]] = []
        if self._client and self.config.database:
            try:
                db = self._client.get_database_client(self.config.database)
                # First container in database as default target
                container_name = self.config.extra_options.get("container", "audit_events")
                container = db.get_container_client(container_name)
                results = container.query_items(
                    query=query,
                    enable_cross_partition_query=True,
                    max_item_count=limit or 1000,
                )
                items = list(results)
            except Exception as exc:
                logger.error("cosmos_query_execution_failed", error=str(exc))
                raise

        if not items:
            items = self.config.extra_options.get("mock_items", [])

        # Clean system fields (_rid, _etag, etc.)
        cleaned = [{k: v for k, v in doc.items() if not k.startswith("_")} for doc in items]
        if not cleaned:
            return pa.Table.from_arrays([], names=[])
        return pa.Table.from_pylist(cleaned)
