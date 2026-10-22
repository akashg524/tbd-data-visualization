"""Abstract base connector defining lifecycle and read-only query contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import structlog

from app.connectors.models import (
    ConnectionConfig,
    ConnectionStatus,
    TableMetadata,
    TableSchema,
)

if TYPE_CHECKING:
    from app.vault import CredentialVault

logger = structlog.get_logger(__name__)


class BaseConnector(ABC):
    """Abstract base connector with strictly enforced read-only semantics."""

    def __init__(self, config: ConnectionConfig, vault: CredentialVault | None = None) -> None:
        self.config = config
        self._vault = vault
        self._connected = False

    @property
    def is_read_only(self) -> bool:
        """Enforce read-only constraint across all child connectors."""
        return True

    def resolve_secret(self, secret_name: str | None, default: str | None = None) -> str:
        """Resolve a password or token via the configured CredentialVault."""
        if not secret_name:
            return default or ""
        if self._vault is not None:
            return self._vault.get_secret(secret_name, default=default)
        from app.vault import vault

        return vault.get_secret(secret_name, default=default)

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection or initialize client session."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Release all connections, pools, and open resources."""

    @abstractmethod
    async def test_connection(self) -> ConnectionStatus:
        """Probe the datasource and return latency and status."""

    @abstractmethod
    async def introspect_schemas(self) -> list[str]:
        """List distinct schemas / databases in the target source."""

    @abstractmethod
    async def introspect_tables(self, schema: str) -> list[TableMetadata]:
        """List tables within a specified schema."""

    @abstractmethod
    async def get_table_schema(self, schema: str, table: str) -> TableSchema:
        """Extract full column metadata and partition specs for a table."""

    @abstractmethod
    async def execute_query(self, query: str, limit: int | None = None) -> pa.Table:
        """Execute a read-only query and stream results into an Apache Arrow Table."""

    async def __aenter__(self) -> BaseConnector:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()
