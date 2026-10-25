"""Integration tests for Cross-Protocol Policy Enforcement, Cache Isolation, and SOX/FINRA Audit Trail."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from app.auth.audit import audit_logger
from app.auth.governance import SecurityContext
from app.auth.rbac import get_security_context
from app.cache import ResultCache
from app.catalog import UnifiedCatalogRegistry, catalog
from app.connectors.iceberg_adls import IcebergADLSConnector
from app.connectors.models import (
    ColumnMetadata,
    ConnectionConfig,
    DataType,
    TableMetadata,
    TableSchema,
)
from app.federation.executor import FederatedExecutor
from app.main import create_app


@pytest.fixture
def mock_security_catalog() -> UnifiedCatalogRegistry:
    """Catalog with registered mock ADLS connector and table schemas."""
    cat = UnifiedCatalogRegistry()

    adls = IcebergADLSConnector(ConnectionConfig(name="adls_lake", datasource_type="adls_iceberg"))
    adls.execute_query = AsyncMock(  # type: ignore[method-assign]
        return_value=pa.table(
            {
                "trade_id": [1, 2, 3, 4],
                "desk_code": ["FX", "EQUITIES", "COMMODITIES", "RATES"],
                "region_id": [1, 2, 3, 4],
                "amount": [10000.0, 20000.0, 30000.0, 40000.0],
            }
        )
    )

    cat.register_datasource("adls_lake", adls)

    # Register table schemas in cache
    cat._table_cache["adls_lake.equity.trades"] = TableSchema(
        schema_name="equity",
        table_name="trades",
        columns=[
            ColumnMetadata(name="trade_id", data_type=DataType.INTEGER, is_primary_key=True),
            ColumnMetadata(name="desk_code", data_type=DataType.STRING),
            ColumnMetadata(name="region_id", data_type=DataType.INTEGER),
            ColumnMetadata(name="amount", data_type=DataType.DECIMAL),
        ],
    )
    cat._table_cache["adls_lake.corporate.mna_deals"] = TableSchema(
        schema_name="corporate",
        table_name="mna_deals",
        columns=[
            ColumnMetadata(name="deal_id", data_type=DataType.INTEGER, is_primary_key=True),
            ColumnMetadata(name="target_name", data_type=DataType.STRING),
            ColumnMetadata(name="deal_value", data_type=DataType.DECIMAL),
        ],
    )

    return cat


@pytest.mark.asyncio
async def test_cache_isolation_by_security_fingerprint(mock_security_catalog: UnifiedCatalogRegistry) -> None:
    """Verify identical SQL executed by users with different entitlements generates isolated cache entries."""
    cache = ResultCache()
    executor = FederatedExecutor(catalog=mock_security_catalog, cache=cache)

    user_fx = SecurityContext(
        user_id="user_fx",
        username="fx_trader@bank.com",
        roles=["Trader"],
        trading_desks=["FX"],
        regions=["US"],
    )
    user_eq = SecurityContext(
        user_id="user_eq",
        username="eq_trader@bank.com",
        roles=["Trader"],
        trading_desks=["EQUITIES"],
        regions=["US"],
    )

    sql = "SELECT trade_id, desk_code FROM adls_lake.equity.trades"

    # User FX runs query -> cache miss
    _tbl1, m1 = await executor.execute(sql, security_context=user_fx)
    assert m1.cache_hit is False
    assert "desk_code" in m1.secured_sql

    # User FX runs identical query again -> cache hit!
    _tbl2, m2 = await executor.execute(sql, security_context=user_fx)
    assert m2.cache_hit is True

    # User EQ runs identical query -> MUST be cache miss (separate fingerprint)
    _tbl3, m3 = await executor.execute(sql, security_context=user_eq)
    assert m3.cache_hit is False
    assert "desk_code" in m3.secured_sql

    # User EQ runs again -> cache hit for EQ
    _tbl4, m4 = await executor.execute(sql, security_context=user_eq)
    assert m4.cache_hit is True


@pytest.mark.asyncio
async def test_fail_closed_zero_claims(mock_security_catalog: UnifiedCatalogRegistry) -> None:
    """Verify user with allowed role but zero entitlement claims is secured with 1 = 0."""
    executor = FederatedExecutor(catalog=mock_security_catalog)

    user_empty = SecurityContext(
        user_id="unassigned_user",
        username="unassigned@bank.com",
        roles=["Trader"],
        trading_desks=[],
        regions=[],
        allowed_accounts=[],
    )

    sql = "SELECT trade_id FROM adls_lake.equity.trades"
    _tbl, metrics = await executor.execute(sql, security_context=user_empty)

    assert any("1 = 0" in f for f in metrics.applied_rls_filters)
    assert "1 = 0" in metrics.secured_sql


@pytest.mark.asyncio
async def test_gate1_rbac_permission_rejection(mock_security_catalog: UnifiedCatalogRegistry) -> None:
    """Verify Gate 1 table RBAC rejects unauthorized table access and logs audit failure."""
    executor = FederatedExecutor(catalog=mock_security_catalog)

    unauthorized_user = SecurityContext(
        user_id="trader_joe",
        username="trader_joe@bank.com",
        roles=["Trader"],  # mna_deals requires MNA_Auditor or ComplianceAdmin
    )

    sql = "SELECT * FROM adls_lake.corporate.mna_deals"

    audit_logger._audit_records.clear()
    with pytest.raises(PermissionError) as exc_info:
        await executor.execute(sql, security_context=unauthorized_user)

    assert "adls_lake.corporate.mna_deals" in str(exc_info.value)

    # Check audit log failure event
    assert len(audit_logger._audit_records) >= 1
    fail_event = audit_logger._audit_records[-1]
    assert fail_event["status"] == "FAILED"
    assert "Access denied" in fail_event["error"]
    assert fail_event["user"]["username"] == "trader_joe@bank.com"


@pytest.mark.asyncio
async def test_compliance_admin_exemption(mock_security_catalog: UnifiedCatalogRegistry) -> None:
    """Verify ComplianceAdmin role bypasses RLS filter injection for unrestricted compliance review."""
    executor = FederatedExecutor(catalog=mock_security_catalog)

    admin_user = SecurityContext(
        user_id="auditor_jane",
        username="auditor_jane@bank.com",
        roles=["ComplianceAdmin"],
        trading_desks=[],
        regions=[],
    )

    sql = "SELECT trade_id, desk_code FROM adls_lake.equity.trades"
    _tbl, metrics = await executor.execute(sql, security_context=admin_user)

    assert metrics.applied_rls_filters == []
    assert "WHERE" not in metrics.secured_sql.upper()


def test_rest_query_endpoint_transparent_explain(mock_security_catalog: UnifiedCatalogRegistry) -> None:
    """Verify POST /api/v1/query/execute returns applied_rls_filters and secured_sql in execution metrics."""
    app = create_app()

    executor = FederatedExecutor(catalog=mock_security_catalog)
    from app.api import query

    orig_executor = query.federated_executor
    query.federated_executor = executor

    trader_context = SecurityContext(
        user_id="trader_bob",
        username="trader_bob@bank.com",
        roles=["Trader"],
        trading_desks=["FX"],
        regions=["US"],
    )

    app.dependency_overrides[get_security_context] = lambda: trader_context

    with TestClient(app) as client:
        payload = {"sql": "SELECT trade_id, desk_code, region_id FROM adls_lake.equity.trades"}
        resp = client.post("/api/v1/query/execute", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        metrics = data["metrics"]
        assert "applied_rls_filters" in metrics
        assert len(metrics["applied_rls_filters"]) > 0
        assert any("desk_code" in f and "FX" in f for f in metrics["applied_rls_filters"])
        assert any("region_id" in f and "1" in f for f in metrics["applied_rls_filters"])
        assert "WHERE" in metrics["secured_sql"].upper()

    query.federated_executor = orig_executor


def test_export_endpoint_rls_and_audit(mock_security_catalog: UnifiedCatalogRegistry) -> None:
    """Verify GET /api/v1/export/query applies RLS and logs data export audit record."""
    app = create_app()
    executor = FederatedExecutor(catalog=mock_security_catalog)
    from app.api import query
    from app.serving import export as export_mod

    orig_query_exec = query.federated_executor
    orig_export_exec = export_mod.federated_executor
    query.federated_executor = executor
    export_mod.federated_executor = executor

    trader_context = SecurityContext(
        user_id="export_user",
        username="export_user@bank.com",
        roles=["Trader"],
        trading_desks=["EQUITIES"],
        regions=["EMEA"],
    )

    app.dependency_overrides[get_security_context] = lambda: trader_context
    audit_logger._audit_records.clear()

    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/export/query",
            params={
                "sql": "SELECT trade_id, desk_code FROM adls_lake.equity.trades",
                "format": "csv",
                "filename": "trades_export",
            },
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

        # Check export audit trail
        export_events = [
            r for r in audit_logger._audit_records if r.get("event_type") == "analytical_data_export"
        ]
        assert len(export_events) == 1
        ev = export_events[0]
        assert ev["export"]["format"] == "csv"
        assert ev["export"]["filename"] == "trades_export"
        assert ev["user"]["username"] == "export_user@bank.com"
        assert ev["protocol"] == "Export"

    query.federated_executor = orig_query_exec
    export_mod.federated_executor = orig_export_exec


def test_views_endpoint_with_security_context(mock_security_catalog: UnifiedCatalogRegistry) -> None:
    """Verify GET /api/v1/views/{schema}/{table} enforces security context through federated executor."""
    app = create_app()
    executor = FederatedExecutor(catalog=mock_security_catalog)
    from app.api import query
    from app.api import views as views_mod

    orig_query_exec = query.federated_executor
    orig_views_exec = views_mod.federated_executor
    query.federated_executor = executor
    views_mod.federated_executor = executor

    # Register in global catalog so resolve_view_path finds it
    adls = mock_security_catalog.get_connector("adls_lake")
    assert adls is not None
    catalog.register_datasource("adls_lake", adls)
    catalog._schema_cache["adls_lake"] = {
        "equity": [
            TableMetadata(
                name="trades",
                schema_name="equity",
                row_count_estimate=4,
                format_type="iceberg",
            )
        ]
    }
    catalog._table_cache["adls_lake.equity.trades"] = mock_security_catalog._table_cache[
        "adls_lake.equity.trades"
    ]

    trader_context = SecurityContext(
        user_id="view_trader",
        username="view_trader@bank.com",
        roles=["Trader"],
        trading_desks=["FX"],
        regions=["US"],
    )

    app.dependency_overrides[get_security_context] = lambda: trader_context

    with TestClient(app) as client:
        resp = client.get("/api/v1/views/equity/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_name"] == "equity"
        assert data["table_name"] == "trades"
        assert "columns" in data

    query.federated_executor = orig_query_exec
    views_mod.federated_executor = orig_views_exec
    catalog.unregister_datasource("adls_lake")
