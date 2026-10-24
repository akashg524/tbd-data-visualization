"""Tests for Microsoft Entra ID authentication and Role-Based Access Control (RBAC)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import Role, authenticator
from app.config import Settings
from app.main import app

# Generate RSA key pair for testing RS256 token verification
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")

_public_key = _private_key.public_key()
_public_pem = _public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode("utf-8")

TEST_TENANT_ID = "00000000-1111-2222-3333-444444444444"
TEST_CLIENT_ID = "api://financial-data-hub"
TEST_ISSUER = f"https://login.microsoftonline.com/{TEST_TENANT_ID}/v2.0"


def make_test_settings(auth_enabled: bool = True) -> Settings:
    """Create settings instance with configured Entra ID parameters."""
    return Settings(
        auth_enabled=auth_enabled,
        entra_tenant_id=TEST_TENANT_ID,
        entra_client_id=TEST_CLIENT_ID,
        environment="testing",
    )


def create_jwt_token(
    roles: list[str] | None = None,
    groups: list[str] | None = None,
    audience: str = TEST_CLIENT_ID,
    issuer: str = TEST_ISSUER,
    expires_in: int = 3600,
    subject: str = "analyst@enterprise.com",
) -> str:
    """Issue a mock Entra ID JWT signed with RS256."""
    now = int(time.time())
    payload = {
        "sub": subject,
        "name": "Enterprise Analyst",
        "preferred_username": subject,
        "iss": issuer,
        "aud": audience,
        "nbf": now - 10,
        "iat": now - 10,
        "exp": now + expires_in,
    }
    if roles is not None:
        payload["roles"] = roles
    if groups is not None:
        payload["groups"] = groups

    return jwt.encode(payload, _private_pem, algorithm="RS256", headers={"kid": "mock-test-key"})


@pytest.fixture
def mock_jwks():
    """Mock PyJWKClient in EntraIDAuthenticator to return test RSA public key."""
    mock_key = MagicMock()
    mock_key.key = _public_pem

    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    with patch.object(authenticator, "get_jwks_client", return_value=mock_client):
        yield mock_client


def test_role_enum_constants():
    """Verify standard enterprise role names."""
    assert Role.FINANCIAL_ANALYST == "FinancialAnalyst"
    assert Role.DATA_ENGINEER == "DataEngineer"
    assert Role.SECURITY_ADMIN == "SecurityAdmin"


def test_dev_bypass_mode():
    """When auth_enabled=False, requests succeed with mock identity without tokens."""
    settings = make_test_settings(auth_enabled=False)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post("/api/v1/query/execute", json={"sql": "SELECT 1 AS num", "limit": 10})
        assert resp.status_code == 200
        assert resp.json()["columns"] == ["num"]


def test_missing_auth_header_when_enabled(mock_jwks):
    """When auth_enabled=True, missing Authorization header returns 401."""
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post("/api/v1/query/execute", json={"sql": "SELECT 1 AS num"})
        assert resp.status_code == 401
        assert "credentials were not provided" in resp.json()["detail"]


def test_invalid_token_format(mock_jwks):
    """Malformed bearer token returns 401."""
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post(
            "/api/v1/query/execute",
            json={"sql": "SELECT 1 AS num"},
            headers={"Authorization": "Bearer not-a-valid-jwt-token"},
        )
        assert resp.status_code == 401
        assert "Invalid authentication token" in resp.json()["detail"] or "validation failed" in resp.json()["detail"]


def test_expired_token(mock_jwks):
    """Expired token returns 401."""
    token = create_jwt_token(roles=["FinancialAnalyst"], expires_in=-300)  # expired 5 min ago
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post(
            "/api/v1/query/execute",
            json={"sql": "SELECT 1 AS num"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"]


def test_audience_mismatch(mock_jwks):
    """Token with wrong audience returns 401."""
    token = create_jwt_token(roles=["FinancialAnalyst"], audience="api://wrong-app-id")
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post(
            "/api/v1/query/execute",
            json={"sql": "SELECT 1 AS num"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert "Invalid authentication token" in resp.json()["detail"] or "Audience" in resp.json()["detail"]


def test_issuer_mismatch(mock_jwks):
    """Token with wrong issuer returns 401."""
    token = create_jwt_token(roles=["FinancialAnalyst"], issuer="https://login.microsoftonline.com/wrong-tenant/v2.0")
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post(
            "/api/v1/query/execute",
            json={"sql": "SELECT 1 AS num"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert "Invalid authentication token" in resp.json()["detail"] or "Issuer" in resp.json()["detail"]


def test_insufficient_role_forbidden(mock_jwks):
    """Valid token with unauthorized role returns 403 Forbidden."""
    token = create_jwt_token(roles=["GuestAuditor"])  # not FinancialAnalyst or DataEngineer
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post(
            "/api/v1/query/execute",
            json={"sql": "SELECT 1 AS num"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert "Insufficient role permissions" in resp.json()["detail"]


def test_valid_token_financial_analyst_permitted(mock_jwks):
    """Valid token with FinancialAnalyst role executes query successfully."""
    token = create_jwt_token(roles=["FinancialAnalyst"])
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post(
            "/api/v1/query/execute",
            json={"sql": "SELECT 42 AS answer", "limit": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["columns"] == ["answer"]
        assert data["rows"] == [[42]]


def test_valid_token_groups_claim_permitted(mock_jwks):
    """Valid token with DataEngineer in groups claim executes query successfully."""
    token = create_jwt_token(groups=["DataEngineer"])
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        resp = client.post(
            "/api/v1/query/execute",
            json={"sql": "SELECT 'ok' AS status", "limit": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["rows"] == [["ok"]]


def test_guarded_serving_routes(mock_jwks):
    """Verify views, odata, and export routes enforce authentication when enabled."""
    settings = make_test_settings(auth_enabled=True)
    with patch("app.auth.entra.get_settings", return_value=settings), TestClient(app) as client:
        # Views listing
        resp = client.get("/api/v1/views")
        assert resp.status_code == 401

        # Export query
        resp = client.get("/api/v1/export/query?sql=SELECT+1")
        assert resp.status_code == 401

        # OData service document
        resp = client.get("/api/v1/odata")
        assert resp.status_code == 401

        # Now test with valid token
        token = create_jwt_token(roles=["DataEngineer"])
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get("/api/v1/views", headers=headers)
        assert resp.status_code == 200

        resp = client.get("/api/v1/export/query?sql=SELECT+1+AS+num&format=csv", headers=headers)
        assert resp.status_code == 200

        resp = client.get("/api/v1/odata", headers=headers)
        assert resp.status_code == 200
