"""Structured compliance audit logger for SOX, FINRA, and Microsoft Sentinel integration."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.auth.governance import SecurityContext

logger = structlog.get_logger("audit")


class AuditLogger:
    """Emits structured compliance audit events for all query executions and exports."""

    def __init__(self, event_hub_conn_str: str | None = None) -> None:
        self.event_hub_conn_str = event_hub_conn_str or os.getenv("EVENT_HUB_CONNECTION_STRING")
        self._audit_records: list[dict[str, Any]] = []  # In-memory buffer for testing and verification

    def log_query_execution(
        self,
        context: SecurityContext | None,
        original_sql: str,
        secured_sql: str,
        applied_rls_filters: list[str],
        sources_accessed: list[str],
        duration_ms: float,
        row_count: int,
        cache_hit: bool,
        protocol: str = "REST",
        status: str = "SUCCESS",
        error: str | None = None,
    ) -> dict[str, Any]:
        """Emit structured analytical query execution audit event."""
        event = {
            "event_type": "analytical_query_execution",
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol": protocol,
            "user": {
                "user_id": context.user_id if context else "system",
                "username": context.username if context else "system",
                "roles": context.roles if context else [],
                "trading_desks": context.trading_desks if context else [],
                "regions": context.regions if context else [],
            },
            "query": {
                "original_sql": original_sql,
                "secured_sql": secured_sql,
                "applied_rls_filters": applied_rls_filters,
                "sources_accessed": sources_accessed,
            },
            "telemetry": {
                "duration_ms": round(duration_ms, 2),
                "row_count": row_count,
                "cache_hit": cache_hit,
            },
            "status": status,
            "error": error,
        }

        # Structured logger output (ingested by Azure Monitor / Log Analytics agent)
        logger.info(
            "analytical_query_audit",
            event_type=event["event_type"],
            user=event["user"]["username"],
            protocol=protocol,
            status=status,
            duration_ms=event["telemetry"]["duration_ms"],
            row_count=row_count,
            cache_hit=cache_hit,
            rls_filters=applied_rls_filters,
        )

        self._audit_records.append(event)
        return event

    def log_export_event(
        self,
        context: SecurityContext | None,
        format: str,
        row_count: int,
        filename: str,
        protocol: str = "REST",
    ) -> dict[str, Any]:
        """Emit structured data export audit event."""
        event = {
            "event_type": "analytical_data_export",
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol": protocol,
            "user": {
                "user_id": context.user_id if context else "system",
                "username": context.username if context else "system",
                "roles": context.roles if context else [],
            },
            "export": {
                "format": format,
                "row_count": row_count,
                "filename": filename,
            },
            "status": "SUCCESS",
        }

        logger.info(
            "analytical_export_audit",
            event_type=event["event_type"],
            user=event["user"]["username"],
            format=format,
            row_count=row_count,
            filename=filename,
        )

        self._audit_records.append(event)
        return event


# Global audit logger singleton
audit_logger = AuditLogger()
