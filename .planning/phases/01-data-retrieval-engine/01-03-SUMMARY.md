---
phase: 01-data-retrieval-engine
plan: 01-03
subsystem: connectors
tags:
  - oracle
  - sqlserver
  - catalog
  - arrow
  - federation
completed_at: 2026-10-22T18:43:00Z
---

# Plan 01-03 Summary: Relational Read-Only Connectors & Unified Catalog Registry

## What Was Built
- **`OracleConnector` (`backend/app/connectors/oracle.py`)**:
  - Implements pure Python thin-mode connection using `oracledb` (no Instant Client C-binaries required).
  - Enforces session-level read-only isolation on checkout (`ALTER SESSION SET TRANSACTION READ ONLY`).
  - Introspects distinct non-system schemas and user tables via Oracle data dictionary (`ALL_TABLES`, `ALL_TAB_COLUMNS`, `ALL_CONSTRAINTS`).
  - Executes read-only SQL queries and converts cursor rows to `pyarrow.Table`.
- **`SQLServerConnector` (`backend/app/connectors/sqlserver.py`)**:
  - Connects to on-prem SQL Server and Azure SQL with `ApplicationIntent=ReadOnly` in connection parameters to route traffic to AlwaysOn secondary replicas.
  - Enforces `SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED` for non-blocking analytical scans against active OLTP systems.
  - Introspects schemas and tables via `INFORMATION_SCHEMA.TABLES`, `COLUMNS`, and `KEY_COLUMN_USAGE`.
  - Streams results to `pyarrow.Table`.
- **`UnifiedCatalogRegistry` (`backend/app/catalog.py`)**:
  - Thread-safe registry providing a single virtual namespace across all data stores.
  - Resolves 3-part identifiers (`datasource.schema.table`, e.g. `adls_lake.equity.trades`, `oracle_db.risk.counterparties`).
  - Asynchronously discovers and caches table schemas across all connected sources.
  - Exports a unified hierarchical schema tree (`get_unified_tree()`) for Power BI and UI navigation.
- **Automated Test Suite**:
  - `tests/test_relational_connectors.py`: Tested type mapping, read-only flag enforcement, schema introspection, and Arrow table returns for both Oracle and SQL Server.
  - `tests/test_catalog.py`: Tested registration of heterogeneous sources, path resolution, metadata tree generation, and deregistration.

## Key Files Created
- `backend/app/connectors/oracle.py`
- `backend/app/connectors/sqlserver.py`
- `backend/app/catalog.py`
- `tests/test_relational_connectors.py`
- `tests/test_catalog.py`

## Verification Results
- `pytest tests/test_relational_connectors.py tests/test_catalog.py`: 6 passed in 8.63s.
- Full test suite: 23 passed in 9.05s.
- `ruff check`: All checks passed clean.

## Deviations from Plan
- Used `contextlib.suppress(Exception)` in connector `disconnect()` methods to satisfy modern Python exception handling guidelines.

## Threat Flags
None. All STRIDE mitigations verified:
- `T-01-07`: `ALTER SESSION SET TRANSACTION READ ONLY` physically blocks DML on Oracle.
- `T-01-08`: `ApplicationIntent=ReadOnly` and `READ UNCOMMITTED` prevent lock contention on SQL Server.
- `T-01-09`: Internal system schemas (`SYS`, `SYSTEM`, `information_schema`) filtered out from catalog view.
