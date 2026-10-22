"""Smoke tests for the API layer."""


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness(client):
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_execute_query(client):
    response = client.post(
        "/api/v1/query/execute",
        json={"sql": "SELECT 42 AS answer, 'hello' AS greeting", "limit": 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["columns"] == ["answer", "greeting"]
    assert data["row_count"] == 1
    assert data["rows"][0] == [42, "hello"]


def test_execute_bad_sql(client):
    response = client.post(
        "/api/v1/query/execute",
        json={"sql": "SELEC INVALID SYNTAX"},
    )
    assert response.status_code == 400
