"""DuckDB-based analytical engine — the core query execution layer."""

from __future__ import annotations

import duckdb
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


class AnalyticsEngine:
    """Manages the DuckDB connection and provides query execution."""

    def __init__(self) -> None:
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("Analytics engine not initialized. Call initialize() first.")
        return self._conn

    def initialize(self) -> None:
        """Create the in-memory DuckDB connection with configured extensions."""
        settings = get_settings()
        self._conn = duckdb.connect(":memory:")

        # Apply resource limits
        self._conn.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
        self._conn.execute(f"SET threads = {settings.duckdb_threads}")

        # Install & load commonly needed extensions
        for ext in ("httpfs", "json", "parquet", "excel"):
            try:
                self._conn.install_extension(ext)
                self._conn.load_extension(ext)
                logger.info("extension_loaded", extension=ext)
            except Exception:
                logger.warning("extension_load_failed", extension=ext)

        logger.info("analytics_engine_ready")

    def execute_query(self, sql: str, params: dict | None = None) -> duckdb.DuckDBPyRelation:
        """Execute a SQL query and return the DuckDB relation."""
        logger.info("execute_query", sql_preview=sql[:200])
        return self.conn.sql(sql)

    def shutdown(self) -> None:
        """Clean up the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("analytics_engine_shutdown")


# Module-level singleton
analytics_engine = AnalyticsEngine()
