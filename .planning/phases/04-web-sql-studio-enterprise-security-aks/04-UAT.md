---
status: complete
phase: 04-web-sql-studio-enterprise-security-aks
source:
  - 04-01-SUMMARY.md
  - 04-02-SUMMARY.md
  - 04-03-SUMMARY.md
started: 2026-10-24T06:00:00Z
updated: 2026-10-24T06:30:00Z
---

## Current Test

number: 3
name: Production Multi-Stage Dockerfiles & AKS Helm Chart Deployment
expected: |
  All Phase 4 user acceptance criteria completed and verified 100% passing across 103 unit and integration tests.
awaiting: none

## Tests

### 1. Monaco Web SQL Studio UI & Visual Query Cockpit
expected: Interactive web query studio with Monaco editor, catalog autocompletion across 3-part virtual namespaces, interactive SchemaTree with datasource badges, visual execution timeline (planning, pushdown, vectorized hash join, cache hit badge), virtualized results grid with CSV/Parquet/NDJSON exports, and 1-click Power BI (.pbids) / Excel (.odc) launchers.
result: pass

### 2. Microsoft Entra ID SSO & Role-Based Access Control (RBAC)
expected: Cryptographic RS256 token verification against Microsoft Entra ID discovery keys (`/discovery/v2.0/keys`), role enforcement (`FinancialAnalyst`, `DataEngineer`, `SecurityAdmin`) across `/api/v1/query/execute`, `/api/v1/views/**`, `/api/v1/odata/**`, and `/api/v1/export/**`, with automated dev bypass mode (`AUTH_ENABLED=false`) for local development and test suites.
result: pass

### 3. Production Multi-Stage Dockerfiles & AKS Helm Chart Deployment
expected: Hardened multi-stage non-root Docker images (`appuser` UID 10001, `nginx:alpine`), Nginx SPA routing with reverse proxy to backend, complete AKS Helm chart parameterizing local NVMe SSD `emptyDir` scratch storage mounted at `/scratch` for DuckDB out-of-core spill joins, multi-port Kubernetes services (8000 REST, 5433 PGWire, 5005 Arrow Flight), and hybrid VNet Peering blueprint for on-premises Oracle and SQL Server access via ExpressRoute.
result: pass
