"""Connector package exposing models and base contracts."""

from app.connectors.base import BaseConnector
from app.connectors.models import (
    ColumnMetadata,
    ConnectionConfig,
    ConnectionStatus,
    DataType,
    TableMetadata,
    TableSchema,
)

__all__ = [
    "BaseConnector",
    "ColumnMetadata",
    "ConnectionConfig",
    "ConnectionStatus",
    "DataType",
    "TableMetadata",
    "TableSchema",
]
