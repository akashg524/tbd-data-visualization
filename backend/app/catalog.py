"""Unified Schema Catalog Registry organizing heterogeneous stores into a single virtual namespace."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.connectors.base import BaseConnector
from app.connectors.models import TableMetadata, TableSchema

logger = structlog.get_logger(__name__)


class UnifiedCatalogRegistry:
    """Thread-safe catalog registry providing a single virtual namespace across all data stores."""

    def __init__(self) -> None:
        self._datasources: dict[str, BaseConnector] = {}
        self._schema_cache: dict[str, dict[str, list[TableMetadata]]] = {}
        self._table_cache: dict[str, TableSchema] = {}
        self._lock = asyncio.Lock()

    def register_datasource(self, name: str, connector: BaseConnector) -> None:
        """Register a new datasource connector under the given namespace identifier."""
        self._datasources[name] = connector
        logger.info("datasource_registered", name=name, type=connector.config.datasource_type)

    def unregister_datasource(self, name: str) -> None:
        """Remove a datasource from the catalog and purge its cache entries."""
        if name in self._datasources:
            del self._datasources[name]
            self._schema_cache.pop(name, None)
            # Evict matching table caches
            prefix = f"{name}."
            self._table_cache = {k: v for k, v in self._table_cache.items() if not k.startswith(prefix)}
            logger.info("datasource_unregistered", name=name)

    def list_datasources(self) -> list[str]:
        """Return all registered datasource namespace identifiers."""
        return list(self._datasources.keys())

    def get_connector(self, name: str) -> BaseConnector:
        """Retrieve connector by namespace identifier."""
        if name not in self._datasources:
            raise KeyError(f"Datasource '{name}' is not registered in the catalog.")
        return self._datasources[name]

    def resolve_table(self, full_path: str) -> tuple[BaseConnector, str, str]:
        """Parse a 3-part identifier ('datasource.schema.table') to connector, schema, and table name."""
        parts = full_path.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid table identifier '{full_path}'. Expected format: 'datasource.schema.table'"
            )
        ds_name, schema_name, table_name = parts[0], parts[1], parts[2]
        connector = self.get_connector(ds_name)
        return connector, schema_name, table_name

    async def refresh_catalog(self, datasource_name: str | None = None) -> None:
        """Asynchronously introspect and cache schemas and tables across datasources."""
        async with self._lock:
            targets = [datasource_name] if datasource_name else list(self._datasources.keys())

            for name in targets:
                if name not in self._datasources:
                    continue
                connector = self._datasources[name]
                try:
                    schemas = await connector.introspect_schemas()
                    ds_schema_map: dict[str, list[TableMetadata]] = {}

                    for schema in schemas:
                        tables = await connector.introspect_tables(schema)
                        ds_schema_map[schema] = tables

                        # Pre-cache table schemas
                        for tbl in tables:
                            try:
                                tbl_schema = await connector.get_table_schema(schema, tbl.name)
                                cache_key = f"{name}.{schema}.{tbl.name}"
                                self._table_cache[cache_key] = tbl_schema
                            except Exception as exc:
                                logger.warning(
                                    "table_schema_fetch_failed",
                                    table=f"{name}.{schema}.{tbl.name}",
                                    error=str(exc),
                                )

                    self._schema_cache[name] = ds_schema_map
                    logger.info("datasource_catalog_refreshed", name=name, schemas=len(schemas))
                except Exception as exc:
                    logger.error("datasource_refresh_failed", name=name, error=str(exc))

    async def get_table_schema(self, full_path: str) -> TableSchema:
        """Retrieve schema metadata for a table, using cache or fetching directly."""
        if full_path in self._table_cache:
            return self._table_cache[full_path]

        connector, schema, table = self.resolve_table(full_path)
        schema_meta = await connector.get_table_schema(schema, table)
        self._table_cache[full_path] = schema_meta
        return schema_meta

    def get_unified_tree(self) -> dict[str, Any]:
        """Export the full hierarchical schema tree for UI or Power BI navigation."""
        tree: dict[str, Any] = {}

        for ds_name, connector in self._datasources.items():
            ds_entry: dict[str, Any] = {
                "type": connector.config.datasource_type,
                "schemas": {},
            }
            cached_schemas = self._schema_cache.get(ds_name, {})

            for schema_name, tables in cached_schemas.items():
                ds_entry["schemas"][schema_name] = {
                    "tables": [
                        {
                            "name": t.name,
                            "format": t.format_type,
                            "comment": t.comment,
                            "full_path": f"{ds_name}.{schema_name}.{t.name}",
                        }
                        for t in tables
                    ]
                }
            tree[ds_name] = ds_entry

        return tree


# Default global catalog singleton
catalog = UnifiedCatalogRegistry()
