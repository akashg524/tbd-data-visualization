"""Credential vault resolving secrets from Azure Key Vault with local fallback.

Enforces zero-crash behavior when offline, in CI, or in environments without
an active Azure Key Vault instance.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class CredentialVault:
    """Thread-safe credential resolver supporting Azure Key Vault and local envs."""

    def __init__(self, vault_url: str | None = None) -> None:
        self.vault_url = vault_url or os.environ.get("AZURE_KEYVAULT_URL", "")
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        self._client: Any = None
        self._azure_attempted = False

    def _get_azure_client(self) -> Any:
        """Lazily initialize SecretClient with DefaultAzureCredential."""
        if self._azure_attempted:
            return self._client

        with self._lock:
            if not self._azure_attempted:
                self._azure_attempted = True
                if self.vault_url:
                    try:
                        from azure.identity import DefaultAzureCredential
                        from azure.keyvault.secrets import SecretClient

                        credential = DefaultAzureCredential()
                        self._client = SecretClient(vault_url=self.vault_url, credential=credential)
                        logger.info("keyvault_client_initialized", vault_url=self.vault_url)
                    except Exception as exc:
                        logger.warning("keyvault_client_init_failed", error=str(exc))
                        self._client = None
        return self._client

    def get_secret(self, secret_name: str, default: str | None = None) -> str:
        """Retrieve a secret by name.

        Order of resolution:
        1. In-memory cache
        2. Azure Key Vault (if configured and reachable)
        3. Local environment variable (e.g., 'DB-PASSWORD' -> 'DB_PASSWORD')
        4. Provided default value (or empty string)
        """
        # 1. Check in-memory cache
        with self._lock:
            if secret_name in self._cache:
                return self._cache[secret_name]

        # 2. Try Azure Key Vault
        client = self._get_azure_client()
        if client is not None:
            try:
                secret_value = client.get_secret(secret_name).value
                if secret_value:
                    with self._lock:
                        self._cache[secret_name] = secret_value
                    logger.debug("secret_resolved_from_keyvault", secret=secret_name)
                    return secret_value
            except Exception as exc:
                logger.debug("keyvault_secret_fetch_failed", secret=secret_name, error=str(exc))

        # 3. Fallback to environment variable
        # Azure Key Vault uses hyphens (db-password); env vars use underscores (DB_PASSWORD)
        env_key = secret_name.upper().replace("-", "_")
        env_val = os.environ.get(env_key) or os.environ.get(secret_name)
        if env_val:
            with self._lock:
                self._cache[secret_name] = env_val
            logger.debug("secret_resolved_from_env", secret=secret_name, env_key=env_key)
            return env_val

        # 4. Default fallback
        fallback = default if default is not None else ""
        return fallback

    def set_local_secret(self, secret_name: str, secret_value: str) -> None:
        """Manually register an in-memory secret for testing / local development."""
        with self._lock:
            self._cache[secret_name] = secret_value

    def clear_cache(self) -> None:
        """Clear the cached secret store."""
        with self._lock:
            self._cache.clear()


# Default singleton instance
vault = CredentialVault()
