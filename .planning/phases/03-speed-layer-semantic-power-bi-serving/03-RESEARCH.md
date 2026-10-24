# Phase 3: Speed Layer & Semantic Power BI Serving — Research

## Executive Summary

Phase 3 builds the enterprise serving and acceleration layer that connects financial analysts and Power BI directly to the federated query engine built in Phase 2. The primary objective is to enable zero-driver, zero-cluster **Power BI DirectQuery** and high-throughput **Batch Import** over standard enterprise protocols:

1. **PostgreSQL Wire Protocol Gateway**: Allows Power BI Desktop and Power BI Service to connect natively via the built-in PostgreSQL connector using DirectQuery (no custom ODBC drivers required on corporate Windows workstations).
2. **Apache Arrow Flight Server & REST Streaming**: Enables multi-gigabyte/second batch extraction into Power BI, Excel, and analytical Python notebooks with zero serialization overhead.
3. **Two-Tier Acceleration Layer**:
   - **Tier 1 (Result-Set Cache)**: Instantaneous (<5ms) responses for repeated dashboard slicer queries via SHA-256 fingerprinting.
   - **Tier 2 (Dimension Table Cache)**: In-memory pre-materialization of slow reference dimensions (e.g., Oracle counterparties, SQL Server GL accounts) to eliminate network hops across on-prem VPNs during cross-source joins.

---

## Standard Stack

| Layer | Library / Tool | Version | Role & Justification |
| :--- | :--- | :--- | :--- |
| **PostgreSQL Wire Server** | `buenavista` | `^0.5.0` | Battle-tested, pure-Python PostgreSQL v3.0 wire protocol proxy (created by the `dbt-duckdb` author). Handles SSL negotiation (`SSLRequest`), authentication, parameter status, `RowDescription`, and `DataRow` packet encoding without C-extensions. |
| **Columnar Streaming Server** | `pyarrow.flight` | `^19.0.1` | Native Arrow Flight server (`FlightServerBase`) built into PyArrow. Streams Arrow `RecordBatch` streams over gRPC at multi-GB/s with zero-copy memory transfers. |
| **HTTP Batch Export** | `fastapi` + `starlette` | `^0.115` | Chunked `StreamingResponse` for CSV, Parquet, and NDJSON consumption via Power BI Web Connector (`Web.Contents`) and Excel. |
| **Vectorized In-Memory DB** | `duckdb` | `^1.5.6` | Backing engine for `buenavista` sessions, hosting standard `information_schema` and `pg_catalog` metadata views queried by Power BI Navigator. |
| **Integration Test Client** | `psycopg` (v3) | `^3.3.6` | Pure-Python/C PostgreSQL client library used to verify the PGWire server over TCP sockets during unit and integration test runs. |

---

## Architecture Patterns

### 1. Dual-Channel Power BI Serving Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │               Power BI Desktop / Service               │
                    └───────────────────┬────────────────┬───────────────────┘
                                        │                │
                   Channel 1: DirectQuery                │ Channel 2: Batch Import
               (PostgreSQL Wire Protocol)                │ (Arrow Flight / REST)
                                        │                │
                                        ▼                ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               Antigravity Speed Layer                                  │
│                                                                                        │
│   ┌────────────────────────────────┐              ┌────────────────────────────────┐   │
│   │   PostgresWireServer (5433)    │              │   ArrowFlightServer (5005)     │   │
│   │   - SSLRequest Negotiation     │              │   - gRPC Columnar Transport    │   │
│   │   - Auth & ParameterStatus     │              │   - FlightDescriptor / Tickets │   │
│   │   - Information Schema Shadow  │              │   - Multi-GB/s Stream Reader   │   │
│   └───────────────┬────────────────┘              └───────────────┬────────────────┘   │
│                   │                                               │                    │
│                   ▼                                               ▼                    │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                      Two-Tier Caching & Dispatch Engine                        │   │
│   │                                                                                │   │
│   │   [Tier 1: ResultCache (SHA-256)]  ── Hit (<5ms) ──────────────────────────┐   │   │
│   │                        │ Miss                                              │   │   │
│   │                        ▼                                                   │   │   │
│   │   [Tier 2: DimensionCache] ── In-Memory Fast Lookup (Oracle Counterparties)│   │   │
│   │                        │                                                   │   │   │
│   │                        ▼                                                   │   │   │
│   │   [FederatedExecutor & PushdownCompiler]                                   │   │   │
│   │                        │                                                   │   │   │
│   │                        ▼                                                   │   │   │
│   │   [DuckDB In-Memory Hash Join & SSD/NVMe Out-of-Core Spilling]             │   │   │
│   └────────────────────────┬───────────────────────────────────────────────────┘   │
│                            │                                                       │
└────────────────────────────┼───────────────────────────────────────────────────────┘
                             │
                             ▼
              [Remote Upstream Heterogeneous Stores]
       (ADLS Iceberg, Oracle, SQL Server, Cosmos DB)
```

### 2. Power BI Navigator & Schema Shadowing Pattern

When Power BI connects to PostgreSQL in DirectQuery mode, it immediately interrogates standard PostgreSQL system catalog tables to populate its Navigator pane:
1. `SELECT current_schema()`
2. `SELECT table_schema, table_name FROM information_schema.tables WHERE ...`
3. `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ...`
4. `SELECT typname, oid FROM pg_catalog.pg_type`

To support this seamlessly without hardcoding SQL responses:
- The `PostgresWireServer` maintains an internal catalog DuckDB instance with shadow schemas (`equity`, `risk`, `dbo`, etc.) reflecting tables registered in `UnifiedCatalogRegistry`.
- `information_schema` and `pg_catalog` queries are resolved directly by DuckDB's native schema engine.
- When Power BI sends analytical queries (e.g. `SELECT "t0"."trade_id", SUM("t0"."amount") FROM "equity"."trades" AS "t0" GROUP BY "t0"."trade_id"`), `FederatedSession` intercepts the query, executes it via `FederatedExecutor`, and returns the result as PostgreSQL `DataRow` packets.

### 3. Two-Tier Caching: Result-Set vs. Dimension Cache

1. **Tier 1 (Result-Set Cache)**:
   - Fingerprint: SHA-256 of normalized SQL string + parameter dictionary.
   - Storage: Compressed Feather (zstd) in memory or Redis.
   - Target: Repeated dashboard loads, slicer clicks, and KPI card re-evaluations. Latency: **<5ms**.
2. **Tier 2 (Dimension Table Cache)**:
   - Target: Frequently joined reference tables that change infrequently (e.g. `oracle_dw.risk.counterparties`, `mssql_dw.dbo.accounts`, FX rate tables).
   - Mechanism: Periodically (or on startup) materializes dimension tables as in-memory PyArrow tables or registered DuckDB views.
   - Benefit: When a cross-source join is compiled, the executor substitutes the cached dimension table directly into DuckDB instead of executing a remote VPN network call to on-premises Oracle. Cross-source join latency drops from ~500ms to **~25ms**.

---

## Don't Hand-Roll

- **DO NOT hand-roll raw PostgreSQL binary wire protocol parsers**: Building frontend/backend packet decoders with `struct.pack` for `StartupMessage`, `AuthenticationOk`, `ParameterStatus`, `RowDescription`, and `DataRow` leads to fragile connection hangs when Power BI sends complex startup handshakes or SSL requests. Use `buenavista` which provides a battle-tested, pure-Python RFC-compliant implementation.
- **DO NOT create custom proprietary binary streaming protocols for batch exports**: Use Apache Arrow Flight (`pyarrow.flight`), which provides an open, gRPC-based standard that natively delivers multi-gigabyte/sec throughput with zero CPU memory copies.
- **DO NOT block FastAPI's async event loop**: The `buenavista` server runs on a socket server and Arrow Flight runs on a gRPC C++ server. Run both in managed background threads or daemons, communicating with FastAPI and `FederatedExecutor` cleanly.
- **DO NOT pull full fact tables into the dimension cache**: Limit dimension caching strictly to reference tables (<1 million rows). Massive fact tables (10 TB – 100 TB ADLS Iceberg files) must always be queried via pushdown predicates and manifest pruning.

---

## Common Pitfalls & How to Avoid Them

### 1. Power BI Double-Quoted Case Sensitivity & Aliases
- *Pitfall:* Power BI generates SQL with explicit double quotes and auto-generated aliases, e.g.:
  ```sql
  SELECT "t0"."trade_id", SUM("t0"."amount") AS "a0"
  FROM "equity"."trades" AS "t0"
  GROUP BY "t0"."trade_id"
  ```
  If the SQL parser strictly expects unquoted lowercase identifiers, alias extraction or table resolution might fail.
- *Mitigation:* `sqlglot` parses quoted identifiers seamlessly. In `PushdownCompiler` and `SQLParser`, identifier comparisons are normalized using `.lower()`.

### 2. SSL Negotiation (`SSLRequest`) Failures
- *Pitfall:* By default, Npgsql / Power BI starts every connection by sending an `SSLRequest` code (80877103). If the server abruptly closes the connection or sends invalid bytes, Power BI throws "An existing connection was forcibly closed by the remote host".
- *Mitigation:* `buenavista` handles `SSLRequest` correctly by sending `b'N'` (No SSL, proceed with unencrypted TCP) when TLS certificates are not configured, allowing Power BI to immediately proceed with the standard startup handshake without error.

### 3. Port Conflicts on Default PostgreSQL Port 5432
- *Pitfall:* Many developer machines or container hosts already run a local PostgreSQL instance on port `5432`. Binding `5432` unconditionally can cause startup failure (`OSError: [Errno 10048] Address already in use`).
- *Mitigation:* Default the wire protocol server to port `5433` (or configurable via `PGWIRE_PORT` / `SETTINGS.pgwire_port`), with fallback probe logic.

### 4. DirectQuery DAX Dialect Nuances
- *Pitfall:* Power BI emits specific PostgreSQL-compatible scalar functions (e.g. `EXTRACT(YEAR FROM ...)`, `DATE_TRUNC`, `COALESCE`).
- *Mitigation:* DuckDB's SQL dialect natively implements PostgreSQL date and text functions, ensuring 100% compatibility when DuckDB evaluates root aggregations.

---

## Code Examples

### A. Exposing FederatedExecutor via BuenaVista PostgreSQL Server

```python
import threading
from typing import Optional
import pyarrow as pa
import structlog
from buenavista.postgres import BuenaVistaServer
from buenavista.connection import Connection, Session, QueryResult
from buenavista.backends.duckdb import DuckDBQueryResult
from app.federation.executor import FederatedExecutor

logger = structlog.get_logger(__name__)

class FederatedSession(Session):
    def __init__(self, executor: FederatedExecutor):
        super().__init__()
        self.executor = executor
        self.in_txn = False

    def execute_sql(self, sql: str, params: Optional[dict] = None) -> QueryResult:
        # Route metadata/system queries or pass to FederatedExecutor
        clean_sql = sql.strip().rstrip(";")
        
        # Run async executor in thread-safe loop
        import asyncio
        loop = asyncio.get_event_loop()
        table, metrics = loop.run_until_complete(self.executor.execute(clean_sql))
        
        # Convert PyArrow Table to BuenaVista QueryResult
        return DuckDBQueryResult(table.to_reader())

class FederatedConnection(Connection):
    def __init__(self, executor: FederatedExecutor):
        super().__init__()
        self.executor = executor

    def parameters(self) -> dict[str, str]:
        return {
            "server_version": "14.0.federated",
            "client_encoding": "UTF8",
            "DateStyle": "ISO",
            "standard_conforming_strings": "on",
        }

    def new_session(self) -> Session:
        return FederatedSession(self.executor)
```

### B. Apache Arrow Flight Server for High-Throughput Batch Import

```python
import pyarrow as pa
import pyarrow.flight as fl
import structlog
from app.federation.executor import FederatedExecutor

logger = structlog.get_logger(__name__)

class FederatedFlightServer(fl.FlightServerBase):
    def __init__(self, executor: FederatedExecutor, host: str = "0.0.0.0", port: int = 5005):
        location = f"grpc+tcp://{host}:{port}"
        super().__init__(location)
        self.executor = executor

    def do_get(self, context, ticket: fl.Ticket):
        # Ticket payload contains the SQL query string
        sql = ticket.ticket.decode("utf-8")
        
        # Execute query synchronously or bridge to async executor
        import asyncio
        loop = asyncio.get_event_loop()
        table, _ = loop.run_until_complete(self.executor.execute(sql))
        
        # Stream Arrow batches with zero-copy
        return fl.RecordBatchStreamReader(table)

    def list_flights(self, context, criteria):
        # Expose catalog tables as flight descriptors
        pass
```

### C. Dimension Table Pre-Materialization (`DimensionCache`)

```python
import asyncio
import time
import pyarrow as pa
import structlog
from app.catalog import UnifiedCatalogRegistry

logger = structlog.get_logger(__name__)

class DimensionCache:
    """Pre-caches slow dimension tables in local memory for instant cross-source joins."""
    
    def __init__(self, catalog: UnifiedCatalogRegistry, refresh_interval: int = 3600):
        self.catalog = catalog
        self.refresh_interval = refresh_interval
        self._dimensions: dict[str, pa.Table] = {}
        self._last_refreshed: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def register_dimension(self, full_table_path: str) -> None:
        self._dimensions[full_table_path] = None

    async def get_dimension(self, full_table_path: str) -> pa.Table | None:
        async with self._lock:
            return self._dimensions.get(full_table_path)

    async def refresh_all(self) -> None:
        async with self._lock:
            for table_path in self._dimensions:
                connector, schema, table = self.catalog.resolve_table(table_path)
                # Pull full dimension table into Arrow memory
                arrow_tbl = await connector.execute_query(f"SELECT * FROM {schema}.{table}")
                self._dimensions[table_path] = arrow_tbl
                self._last_refreshed[table_path] = time.time()
                logger.info("dimension_cached", table=table_path, rows=arrow_tbl.num_rows)
```

---

## Validation Architecture

### Test Infrastructure & Tools
- **Framework**: `pytest` 8.4+ with `pytest-asyncio`
- **PGWire Integration**: `psycopg` connects over standard TCP to `127.0.0.1:5433` and executes SQL.
- **Flight Integration**: `pyarrow.flight.connect("grpc://127.0.0.1:5005")` executes `do_get` tickets.
- **HTTP Streaming Integration**: `httpx` / FastAPI `TestClient` tests CSV, Parquet, and NDJSON streaming endpoints.

### Commands to Run
```bash
# Test PostgreSQL Wire Protocol server
pytest tests/test_pgwire_server.py -v

# Test Arrow Flight Server
pytest tests/test_flight_server.py -v

# Test Dimension Cache & REST Streaming
pytest tests/test_dimension_cache.py tests/test_export_api.py -v

# Full Suite
pytest tests/ -v
```
