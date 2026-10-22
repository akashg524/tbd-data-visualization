# Phase 1: High-Performance Read-Only Connectors & Iceberg Catalog - Context

**Gathered:** 2026-10-22
**Status:** Ready for planning
**Source:** Interactive Architecture Consensus (/grill-me)

<domain>
## Phase Boundary

Build and verify enterprise read-only connectors for ADLS Gen2 (Apache Iceberg/Parquet), on-premises Oracle, on-premises SQL Server, Azure SQL, and Cosmos DB, unified under a thread-safe Unified Schema Catalog Registry with Azure Key Vault credential resolution.

</domain>

<decisions>
## Implementation Decisions

### 1. Storage & Table Format
- **Apache Iceberg for ADLS:** Use `pyiceberg` for catalog inspection and DuckDB's official `iceberg` extension for vectorized scanning.
- **Manifest Pruning:** Queries must prune files based on column min/max statistics in Iceberg manifests without scanning ADLS directories.
- **Time Travel:** Expose Iceberg snapshots for financial auditability.

### 2. Read-Only Guardrails (Zero Upstream Mutation)
- **Oracle:** Strictly use `oracledb` in pure Python thin mode (no Instant Client C-binaries). Execute `ALTER SESSION SET TRANSACTION READ ONLY` on session initialization.
- **SQL Server:** Set `ApplicationIntent=ReadOnly` and `TRANSACTION ISOLATION LEVEL READ UNCOMMITTED` to target AlwaysOn secondary replicas.
- **Cosmos DB:** Sample top 50 documents per container with partition-key detection to infer schema without burning Request Units (RUs).

### 3. Credential Security
- **Azure Key Vault:** Use `azure-keyvault-secrets` and `DefaultAzureCredential` for cloud production.
- **Offline / Local Dev Fallback:** Transparently fall back to local `.env` and environment variables without crashing when running offline or in CI/CD without an active Azure tenant.

### 4. Unified Namespace
- Map all stores into a single hierarchical structure: `catalog.schema.table` (e.g., `adls_iceberg.equity.trades`, `oracle_onprem.risk.counterparties`).

### the agent's Discretion
- Choice of async locking for the catalog registry cache.
- Internal mapping of database-specific SQL data types to standard Arrow/DuckDB types.

</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md` — Project scope, constraints, and core value
- `.planning/ROADMAP.md` — Roadmap phases and Phase 1 requirements
- `.planning/phases/01-data-retrieval-engine/01-RESEARCH.md` — Technical research, standard stack, and pitfalls

</canonical_refs>

<deferred>
## Deferred Ideas

- Web UI charts and front-end dashboard panels (deferred to Phase 4; priority is on the Data Retrieval & Federation Engine).
- DirectQuery PostgreSQL wire-protocol listener (Phase 3).
- Two-tier query result caching (Phase 2 & Phase 3).

</deferred>
