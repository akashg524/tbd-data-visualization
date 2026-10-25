"""Expandable Result Cache for sub-5ms repeated analytical query serving."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import pyarrow as pa
import pyarrow.feather as feather
import structlog

if TYPE_CHECKING:
    from app.catalog import UnifiedCatalogRegistry

logger = structlog.get_logger(__name__)


@dataclass
class CacheEntry:
    """In-memory cached Arrow buffer with expiration timestamp."""

    buffer: bytes
    expires_at: float
    row_count: int
    size_bytes: int


class CacheBackend(Protocol):
    """Protocol for pluggable cache storage backends (In-Memory, Redis)."""

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...
    async def clear(self) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def size(self) -> int: ...


class InMemoryCacheBackend:
    """Thread-safe in-memory LRU cache storing compressed Arrow Feather buffers."""

    def __init__(self, max_entries: int = 1000) -> None:
        self.max_entries = max_entries
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        async with self._lock:
            if key not in self._cache:
                return None

            entry = self._cache[key]
            if time.time() > entry.expires_at:
                del self._cache[key]
                logger.debug("cache_entry_expired", key=key)
                return None

            # Move to end for LRU
            self._cache.move_to_end(key)
            return entry.buffer

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        async with self._lock:
            now = time.time()
            # If key already exists, update and move to end
            if key in self._cache:
                self._cache[key] = CacheEntry(
                    buffer=value,
                    expires_at=now + ttl_seconds,
                    row_count=0,
                    size_bytes=len(value),
                )
                self._cache.move_to_end(key)
                return

            # Check capacity and evict oldest if full
            while len(self._cache) >= self.max_entries:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug("cache_lru_evicted", key=evicted_key)

            self._cache[key] = CacheEntry(
                buffer=value,
                expires_at=now + ttl_seconds,
                row_count=0,
                size_bytes=len(value),
            )

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._cache.pop(key, None)

    async def size(self) -> int:
        async with self._lock:
            now = time.time()
            # Purge expired
            expired = [k for k, v in self._cache.items() if now > v.expires_at]
            for k in expired:
                del self._cache[k]
            return len(self._cache)


class RedisCacheBackend:
    """Pluggable Redis cache adapter for distributed caching across pods."""

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    async def get(self, key: str) -> bytes | None:
        if not self.redis:
            return None
        res = await self.redis.get(key)
        if isinstance(res, str):
            return res.encode("utf-8")
        return res

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        if self.redis:
            await self.redis.set(key, value, ex=ttl_seconds)

    async def clear(self) -> None:
        if self.redis:
            await self.redis.flushdb()

    async def delete(self, key: str) -> None:
        if self.redis:
            await self.redis.delete(key)

    async def size(self) -> int:
        if self.redis:
            return await self.redis.dbsize()
        return 0


class ResultCache:
    """High-performance query result cache with SHA-256 fingerprinting and Arrow Feather serialization."""

    def __init__(
        self,
        backend: CacheBackend | None = None,
        default_ttl: int = 60,
        max_entries: int = 1000,
    ) -> None:
        self.backend = backend or InMemoryCacheBackend(max_entries=max_entries)
        self.default_ttl = default_ttl

    @staticmethod
    def compute_fingerprint(
        sql: str,
        params: dict[str, Any] | None = None,
        security_fingerprint: str = "",
    ) -> str:
        """Generate SHA-256 fingerprint hash from normalized SQL query, parameters, and security fingerprint."""
        normalized = " ".join(sql.strip().lower().split())
        param_str = json.dumps(params or {}, sort_keys=True)
        payload = f"{normalized}::{param_str}::sec={security_fingerprint}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def get(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        security_fingerprint: str = "",
    ) -> pa.Table | None:
        """Fetch cached Arrow table if available and unexpired."""
        key = self.compute_fingerprint(sql, params, security_fingerprint=security_fingerprint)
        raw_buffer = await self.backend.get(key)
        if raw_buffer is None:
            return None

        try:
            reader = pa.BufferReader(raw_buffer)
            table = feather.read_table(reader)
            logger.debug("result_cache_hit", key=key, rows=table.num_rows)
            return table
        except Exception as exc:
            logger.warning("result_cache_deserialization_failed", key=key, error=str(exc))
            await self.backend.delete(key)
            return None

    async def set(
        self,
        sql: str,
        table: pa.Table,
        ttl_seconds: int | None = None,
        params: dict[str, Any] | None = None,
        security_fingerprint: str = "",
    ) -> None:
        """Serialize Arrow table using Feather with zstd compression and store in cache."""
        key = self.compute_fingerprint(sql, params, security_fingerprint=security_fingerprint)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl

        try:
            sink = pa.BufferOutputStream()
            feather.write_feather(table, sink, compression="zstd")
            compressed_bytes = sink.getvalue().to_pybytes()

            await self.backend.set(key, compressed_bytes, ttl_seconds=ttl)
            logger.debug(
                "result_cache_stored",
                key=key,
                rows=table.num_rows,
                bytes=len(compressed_bytes),
                ttl=ttl,
            )
        except Exception as exc:
            logger.warning("result_cache_serialization_failed", key=key, error=str(exc))

    async def clear(self) -> None:
        """Purge all entries from cache."""
        await self.backend.clear()

    async def size(self) -> int:
        """Return count of active unexpired entries in cache."""
        return await self.backend.size()


class DimensionCache:
    """Pre-materializes reference/dimension tables in memory for high-speed cross-source joins."""

    def __init__(
        self,
        catalog: UnifiedCatalogRegistry,
        refresh_interval: int = 3600,
        max_rows: int = 100_000,
    ) -> None:
        self.catalog = catalog
        self.refresh_interval = refresh_interval
        self.max_rows = max_rows
        self._dimensions: dict[str, pa.Table | None] = {}
        self._last_refreshed: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def register_dimension(self, full_table_path: str) -> None:
        """Register a 3-part identifier (e.g. 'oracle_dw.risk.counterparties') as a pre-cached dimension."""
        key = full_table_path.strip().lower()
        self._dimensions.setdefault(key, None)

    def is_dimension_cached(self, full_table_path: str) -> bool:
        """Check if a table path is registered and currently held in dimension cache."""
        key = full_table_path.strip().lower()
        return key in self._dimensions and self._dimensions[key] is not None

    def list_dimensions(self) -> list[str]:
        """Return list of all registered dimension table identifiers."""
        return list(self._dimensions.keys())

    async def get_dimension(self, full_table_path: str) -> pa.Table | None:
        """Retrieve pre-cached Arrow Table for dimension, refreshing automatically if expired."""
        key = full_table_path.strip().lower()
        if key not in self._dimensions:
            return None

        now = time.time()
        last_refreshed = self._last_refreshed.get(key, 0.0)

        # Refresh if not yet loaded or if expired past refresh_interval
        if self._dimensions[key] is None or (now - last_refreshed) > self.refresh_interval:
            return await self.refresh_dimension(full_table_path)

        return self._dimensions[key]

    async def refresh_dimension(self, full_table_path: str) -> pa.Table:
        """Load fresh Arrow Table from catalog connector and cache in memory."""
        key = full_table_path.strip().lower()
        connector, schema, table = self.catalog.resolve_table(full_table_path)

        query = f"SELECT * FROM {schema}.{table}"  # noqa: S608
        arrow_tbl = await connector.execute_query(query)

        # Security check: T-03-01 Cap maximum dimension rows to prevent memory exhaustion
        if arrow_tbl.num_rows > self.max_rows:
            raise ValueError(
                f"Table '{full_table_path}' has {arrow_tbl.num_rows} rows, "
                f"exceeding maximum allowed dimension size of {self.max_rows} rows."
            )

        async with self._lock:
            self._dimensions[key] = arrow_tbl
            self._last_refreshed[key] = time.time()

        logger.info(
            "dimension_table_cached",
            table=full_table_path,
            rows=arrow_tbl.num_rows,
            columns=arrow_tbl.num_columns,
        )
        return arrow_tbl

    async def refresh_all(self) -> None:
        """Refresh all registered dimension tables concurrently."""
        keys = list(self._dimensions.keys())
        await asyncio.gather(*(self.refresh_dimension(k) for k in keys))

    def clear(self) -> None:
        """Clear all cached dimension tables."""
        for k in self._dimensions:
            self._dimensions[k] = None
        self._last_refreshed.clear()
