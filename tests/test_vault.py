"""Unit tests for CredentialVault secret resolution and fallback behavior."""

import os
from unittest.mock import MagicMock

from app.vault import CredentialVault


def test_vault_env_fallback():
    """Vault should resolve secret from environment variable with underscore formatting."""
    v = CredentialVault(vault_url="")
    os.environ["TEST_DB_PASSWORD"] = "super-secret-123"  # noqa: S105

    try:
        val = v.get_secret("test-db-password")
        assert val == "super-secret-123"
    finally:
        del os.environ["TEST_DB_PASSWORD"]


def test_vault_in_memory_override():
    """Vault should prioritize in-memory local secrets."""
    v = CredentialVault(vault_url="")
    v.set_local_secret("my-api-key", "token-xyz")

    val = v.get_secret("my-api-key")
    assert val == "token-xyz"

    v.clear_cache()
    assert v.get_secret("my-api-key", default="fallback") == "fallback"


def test_vault_default_fallback():
    """Vault should return default when secret cannot be found."""
    v = CredentialVault(vault_url="")
    val = v.get_secret("non-existent-secret", default="my-default")
    assert val == "my-default"


def test_vault_azure_mocked():
    """Vault should query SecretClient when vault_url is configured."""
    mock_secret = MagicMock()
    mock_secret.value = "vault-resolved-secret"

    mock_client = MagicMock()
    mock_client.get_secret.return_value = mock_secret

    v = CredentialVault(vault_url="https://mock-vault.vault.azure.net/")
    v._client = mock_client
    v._azure_attempted = True

    resolved = v.get_secret("prod-db-pass")
    assert resolved == "vault-resolved-secret"
    mock_client.get_secret.assert_called_once_with("prod-db-pass")

    # Second call should hit in-memory cache
    resolved_cached = v.get_secret("prod-db-pass")
    assert resolved_cached == "vault-resolved-secret"
    assert mock_client.get_secret.call_count == 1
