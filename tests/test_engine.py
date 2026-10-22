"""Tests for the DuckDB analytics engine directly."""

from app.engine import AnalyticsEngine


def test_engine_lifecycle():
    """Engine can initialize, query, and shutdown cleanly."""
    engine = AnalyticsEngine()
    engine.initialize()

    result = engine.execute_query("SELECT 1 + 1 AS sum_result")
    row = result.fetchone()
    assert row is not None
    assert row[0] == 2

    engine.shutdown()


def test_engine_parquet_read(tmp_path):
    """Engine can read a Parquet file produced by PyArrow."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({
        "ticker": ["AAPL", "MSFT", "GOOG"],
        "price": [150.25, 310.50, 140.75],
    })
    path = tmp_path / "stocks.parquet"
    pq.write_table(table, str(path))

    engine = AnalyticsEngine()
    engine.initialize()

    result = engine.execute_query(f"SELECT * FROM read_parquet('{str(path).replace(chr(92), '/')}')")
    rows = result.fetchall()
    assert len(rows) == 3
    assert rows[0][0] == "AAPL"

    engine.shutdown()
