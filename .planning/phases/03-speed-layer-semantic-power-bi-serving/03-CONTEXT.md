# Phase 3: Speed Layer & Semantic Power BI Serving - Context

**Gathered:** 2026-10-24
**Status:** Ready for planning
**Source:** Phase 3 Research & Denodo-style Data Delivery Architecture

<domain>
## Phase Boundary

Expose the federated query engine and catalog to Power BI, Excel, and analytical consumers across multiple enterprise delivery channels:
1. Native PostgreSQL Wire Protocol Gateway for zero-driver Power BI DirectQuery.
2. Denodo-style OData v4 feeds and RESTful views for Excel and Power BI OData Feed.
3. Apache Arrow Flight Server for high-throughput batch imports (multi-GB/s).
4. One-click `.pbids` and `.odc` connection file generators.
5. Two-tier acceleration (Result-Set Cache + Pre-materialized Dimension Cache).

</domain>

<decisions>
## Implementation Decisions

### 1. PostgreSQL Wire Protocol Server
- **Library:** Use `buenavista` (`^0.5.0`), a pure-Python PostgreSQL v3.0 wire protocol server.
- **Port:** Bind to configurable port (default `5433` or `5432`) to avoid local database port conflicts.
- **Schema Shadowing:** Maintain shadow schemas in DuckDB so Power BI Navigator can inspect `information_schema.tables`, `information_schema.columns`, and `pg_catalog`.
- **Query Interception:** Forward analytical queries to `FederatedExecutor`, returning Arrow Tables as PostgreSQL `DataRow` packets over TCP.

### 2. Denodo-Style OData v4 & REST Views
- **OData Feed Endpoint:** `/api/v1/odata/` implementing `$metadata`, `$filter`, `$select`, `$top`, and `$skip`.
- **Direct Consumers:** Microsoft Excel (Data -> From Other Sources -> From OData Feed) and Power BI (Get Data -> OData Feed).
- **RESTful Views API:** `/api/v1/views/{catalog}/{schema}/{table}` returning JSON, CSV, or Parquet with pagination headers.

### 3. One-Click Launch Files (.pbids / .odc)
- **Power BI (.pbids):** Dynamically generate `.pbids` JSON files pre-configured with server host, port, database, and DirectQuery mode.
- **Excel (.odc):** Generate `.odc` XML files pre-wired to the OData feed.

### 4. Apache Arrow Flight Server
- **Library:** `pyarrow.flight.FlightServerBase` (built into PyArrow 19.0.1).
- **Port:** `grpc+tcp://0.0.0.0:5005`.
- **Protocol:** Submit ticket with SQL query -> Stream zero-copy `RecordBatch` streams at multi-GB/s.

### 5. Two-Tier Acceleration
- **Tier 1:** Result-Set Cache (`ResultCache`) with SHA-256 fingerprinting for <5ms repeated query latency.
- **Tier 2:** Dimension Table Cache (`DimensionCache`) pre-materializing slow reference tables (Oracle counterparties, SQL Server accounts) to eliminate VPN latency during cross-source joins.

</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md` — Power BI connectivity and dual-channel serving goals
- `.planning/ROADMAP.md` — Phase 3 requirements (REQ-10 through REQ-12)
- `.planning/phases/03-speed-layer-semantic-power-bi-serving/03-RESEARCH.md` — Technical research and code examples

</canonical_refs>

<deferred>
## Deferred Ideas

- Monaco Web SQL Studio UI (Phase 4)
- Microsoft Entra ID (Azure AD) SSO token validation (Phase 4)
- Kubernetes Helm manifests for AKS deployment (Phase 4)
</deferred>
