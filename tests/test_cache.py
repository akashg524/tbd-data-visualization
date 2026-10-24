"""Unit tests for ResultCache with Feather serialization and LRU eviction."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pyarrow as pa
import pytest

from app.cache import InMemoryCacheBackend, RedisCacheBackend, ResultCache


@pytest.fixture
def sample_table() -> pa.Table:
    """Fixture providing a sample financial Arrow table."""
    return pa.table(
        {
            "trade_id": [1001, 1002, 1003],
            "symbol": ["AAPL", "MSFT", "GOOGL"],
            "notional": [150000.50, 240000.75, 95000.00],
            "is_active": [True, True, False],
        }
    )


async def test_cache_hit_and_roundtrip(sample_table: pa.Table) -> None:
    """Verify storing and retrieving an Arrow table preserves all schema types and data."""
    cache = ResultCache()
    sql = "SELECT trade_id, symbol, notional, is_active FROM equity.trades"

    # Initially cache miss
    cached_tbl = await cache.get(sql)
    assert cached_tbl is None

    # Store in cache
    await cache.set(sql, sample_table, ttl_seconds=60)

    # Cache hit
    cached_tbl = await cache.get(sql)
    assert cached_tbl is not None
    assert cached_tbl.num_rows == 3
    assert cached_tbl.column_names == ["trade_id", "symbol", "notional", "is_active"]
    assert cached_tbl["trade_id"].to_pylist() == [1001, 1002, 1003]
    assert cached_tbl["symbol"].to_pylist() == ["AAPL", "MSFT", "GOOGL"]
    assert cached_tbl["notional"].to_pylist() == [150000.50, 240000.75, 95000.00]


async def test_sql_fingerprint_normalization(sample_table: pa.Table) -> None:
    """Verify different whitespace or casing in identical SQL queries yield the same cache hit."""
    cache = ResultCache()
    sql1 = "SELECT  trade_id,   symbol FROM   equity.trades  WHERE amount > 100"
    sql2 = "select trade_id, symbol from equity.trades where amount > 100"

    await cache.set(sql1, sample_table)

    # Retrieval via sql2 should hit
    hit = await cache.get(sql2)
    assert hit is not None
    assert hit.num_rows == sample_table.num_rows


async def test_ttl_expiration(sample_table: pa.Table) -> None:
    """Verify cached items expire after ttl_seconds."""
    cache = ResultCache(default_ttl=1)
    sql = "SELECT * FROM fast_expiring"

    await cache.set(sql, sample_table, ttl_seconds=1)
    assert (await cache.get(sql)) is not None

    # Wait for TTL to elapse
    await asyncio.sleep(1.1)
    assert (await cache.get(sql)) is None


async def test_lru_eviction(sample_table: pa.Table) -> None:
    """Verify oldest unaccessed entry is evicted when max_entries is exceeded."""
    backend = InMemoryCacheBackend(max_entries=2)
    cache = ResultCache(backend=backend)

    await cache.set("QUERY 1", sample_table)
    await cache.set("QUERY 2", sample_table)
    assert await cache.size() == 2

    # Access QUERY 1 to make QUERY 2 the least recently used
    assert await cache.get("QUERY 1") is not None

    # Insert QUERY 3 -> should evict QUERY 2
    await cache.set("QUERY 3", sample_table)
    assert await cache.size() == 2

    assert await cache.get("QUERY 1") is not None
    assert await cache.get("QUERY 2") is None
    assert await cache.get("QUERY 3") is not None


async def test_clear_cache(sample_table: pa.Table) -> None:
    """Verify clearing cache removes all entries."""
    cache = ResultCache()
    await cache.set("Q1", sample_table)
    await cache.set("Q2", sample_table)
    assert await cache.size() == 2

    await cache.clear()
    assert await cache.size() == 0
    assert await cache.get("Q1") is None


async def test_redis_backend_mock(sample_table: pa.Table) -> None:
    """Verify RedisCacheBackend protocol integration."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    backend = RedisCacheBackend(mock_redis)
    cache = ResultCache(backend=backend)

    res = await cache.get("SELECT 1")
    assert res is None
    mock_redis.get.assert_awaited_once()

    await cache.set("SELECT 1", sample_table, ttl_seconds=30)
    mock_redis.set.assert_awaited_once()
