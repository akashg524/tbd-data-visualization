"""Pydantic data models for schema metadata and connector configurations."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DataType(StrEnum):
    """Standardized analytical data types."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    TIMESTAMP = "timestamp"
    DATE = "date"
    JSON = "json"
    BINARY = "binary"
    UNKNOWN = "unknown"


class ColumnMetadata(BaseModel):
    """Column definition within a table."""

    name: str
    data_type: DataType
    native_type: str = ""
    nullable: bool = True
    is_primary_key: bool = False
    is_partition_key: bool = False
    comment: str | None = None


class TableMetadata(BaseModel):
    """Table summary within a schema."""

    name: str
    schema_name: str
    row_count_estimate: int | None = None
    format_type: str | None = None  # e.g., 'iceberg', 'delta', 'relational', 'document'
    comment: str | None = None


class TableSchema(BaseModel):
    """Full table definition including all column schemas."""

    table_name: str
    schema_name: str
    columns: list[ColumnMetadata] = Field(default_factory=list)
    partition_keys: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class ConnectionStatus(BaseModel):
    """Status probe outcome for a connector."""

    is_connected: bool
    latency_ms: float = 0.0
    error_message: str | None = None
    server_version: str | None = None


class ConnectionConfig(BaseModel):
    """Generic connection parameters."""

    name: str
    datasource_type: str  # 'adls_iceberg', 'oracle', 'sqlserver', 'cosmos', 'azure_sql'
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password_secret_name: str | None = None
    storage_account: str | None = None
    container: str | None = None
    catalog_uri: str | None = None
    extra_options: dict[str, Any] = Field(default_factory=dict)
