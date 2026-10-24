"""Integration tests for chunked REST export endpoints (CSV, Parquet, NDJSON)."""

from __future__ import annotations

import io
import json

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def export_client():
    """FastAPI TestClient for export API."""
    app = create_app()
    with TestClient(app) as tc:
        yield tc


def test_export_csv_get(export_client: TestClient) -> None:
    """Verify GET /api/v1/export/query with format=csv."""
    response = export_client.get(
        "/api/v1/export/query",
        params={
            "sql": "SELECT 1 AS id, 'Alpha' AS name, 100.5 AS score UNION ALL SELECT 2, 'Beta', 200.75",
            "format": "csv",
            "filename": "test_export",
        },
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert 'attachment; filename="test_export.csv"' in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert len(lines) == 3
    assert lines[0] == '"id","name","score"'


def test_export_parquet_post(export_client: TestClient) -> None:
    """Verify POST /api/v1/export/query with format=parquet."""
    payload = {
        "sql": "SELECT 42 AS answer, 'galaxy' AS place",
        "format": "parquet",
        "filename": "answer",
    }
    response = export_client.post("/api/v1/export/query", json=payload)
    assert response.status_code == 200
    assert "parquet" in response.headers["content-type"]
    assert 'attachment; filename="answer.parquet"' in response.headers["content-disposition"]

    # Verify bytes parse as valid Arrow Parquet table
    buf = io.BytesIO(response.content)
    table = pq.read_table(buf)
    assert table.num_rows == 1
    assert table.column_names == ["answer", "place"]
    assert table["answer"][0].as_py() == 42
    assert table["place"][0].as_py() == "galaxy"


def test_export_ndjson_post(export_client: TestClient) -> None:
    """Verify POST /api/v1/export/query with format=ndjson."""
    payload = {
        "sql": "SELECT 1 AS num, 'first' AS label UNION ALL SELECT 2, 'second'",
        "format": "ndjson",
        "filename": "stream",
    }
    response = export_client.post("/api/v1/export/query", json=payload)
    assert response.status_code == 200
    assert "application/x-ndjson" in response.headers["content-type"]
    assert 'attachment; filename="stream.ndjson"' in response.headers["content-disposition"]

    lines = [json.loads(line) for line in response.text.strip().splitlines() if line]
    assert len(lines) == 2
    assert lines[0] == {"num": 1, "label": "first"}
    assert lines[1] == {"num": 2, "label": "second"}


def test_export_invalid_format(export_client: TestClient) -> None:
    """Verify error on unsupported format."""
    response = export_client.get(
        "/api/v1/export/query",
        params={"sql": "SELECT 1", "format": "xml"},
    )
    assert response.status_code == 400
    assert "Unsupported export format" in response.json()["detail"]


def test_export_bad_sql(export_client: TestClient) -> None:
    """Verify error on malformed SQL."""
    response = export_client.post(
        "/api/v1/export/query",
        json={"sql": "SELEC INVALID SYNTAX", "format": "csv"},
    )
    assert response.status_code == 400
