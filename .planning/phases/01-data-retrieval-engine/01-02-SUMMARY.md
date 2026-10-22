---
phase: 01-data-retrieval-engine
plan: 01-02
subsystem: connectors
tags:
  - iceberg
  - adls
  - cosmos
  - duckdb
  - arrow
completed_at: 2026-10-22T18:38:00Z
---

# Plan 01-02 Summary: Apache Iceberg ADLS Gen2 & Cosmos DB Connectors

## What Was Built
- **`IcebergADLSConnector` (`backend/app/connectors/iceberg_adls.py`)**:
  - Implements ADLS Gen2 Apache Iceberg table integration.
  - Inspects metadata schemas, namespaces, and partition specifications without full storage scans.
  - Implements snapshot retrieval (`get_snapshots`) for financial time-travel auditing.
  - Executes vectorized queries using DuckDB's native `iceberg` extension (`iceberg_scan`), streaming Arrow tables directly.
- **`CosmosDBConnector` (`backend/app/connectors/cosmos.py`)**:
  - Integrates with Azure Cosmos DB SQL API.
  - Safely samples top 50 documents per container to dynamically infer schema while keeping RU consumption negligible.
  - Detects container partition key paths (e.g., `/portfolioId`) and marks partition columns with `is_partition_key = True`.
  - Filters out internal Cosmos metadata attributes (`_rid`, `_etag`, `_ts`) and projects JSON documents to Arrow record batches.
- **Automated Test Suite**:
  - `tests/test_iceberg_adls.py`: Tested type mapping, schema introspection, snapshot listing, and DuckDB vectorized execution.
  - `tests/test_cosmos.py`: Tested JSON type inference, document sampling, partition key detection, and clean Arrow conversion.

## Key Files Created
- `backend/app/connectors/iceberg_adls.py`
- `backend/app/connectors/cosmos.py`
- `tests/test_iceberg_adls.py`
- `tests/test_cosmos.py`

## Verification Results
- `pytest tests/test_iceberg_adls.py tests/test_cosmos.py`: 5 passed in 0.29s.
- Full test suite: 17 passed in 0.82s.
- `ruff check`: All checks passed clean.

## Deviations from Plan
- Adjusted DuckDB Arrow execution in `IcebergADLSConnector` to invoke `read_all()` on the `RecordBatchReader` returned by DuckDB relation to ensure an in-memory `pyarrow.Table` is returned.

## Threat Flags
None. All STRIDE mitigations verified:
- `T-01-04`: Read-only access enforced on ADLS Iceberg files.
- `T-01-05`: Schema sampling restricted to top 50 documents to eliminate RU exhaustion risk on Cosmos DB.
- `T-01-06`: Snapshot history exported without exposing underlying storage SAS tokens or credentials.
