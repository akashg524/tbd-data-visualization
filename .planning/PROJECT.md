# Enterprise Financial Data Hub & Semantic Query Layer for Power BI

## What This Is

An enterprise-grade federated semantic query layer and financial data hub connecting 10 TB – 100 TB of read-only financial data across Azure (ADLS Gen2, Azure SQL, Cosmos DB) and on-premises databases (Oracle, SQL Server) directly to Power BI, Excel, and analytical consumers. It executes sub-second federated queries and cross-source joins using Apache Iceberg, DuckDB, PyArrow, and Buenavista PGWire serving.

## Core Value

Enable instantaneous (<1s) and cost-effective federated analytical queries and cross-source joins across 10–100 TB of heterogeneous read-only financial data stores directly into Power BI without commercial virtualization licensing fees, with enterprise-grade row-level security, dynamic data masking, and SOX/FINRA compliance.

## Current Milestone

**Milestone 2: Enterprise Governance, Row-Level Security (RLS) & Dynamic Masking (v1.1.0)**
Focusing on Phase 5: Dynamic Row-Level Security (RLS), Column Masking & Regulatory Compliance Audit Trail.

## Requirements

### Validated (Milestone 1 — Complete)
- [x] Initial project scaffolding and developer toolchain (FastAPI, DuckDB, Vite React TypeScript, Tailwind v4, Pytest, Ruff)
- [x] Connect and query Apache Iceberg catalog over 10–100 TB ADLS Gen2 Parquet files with manifest-level pruning
- [x] Read-only connectors for on-premises Oracle, on-premises SQL Server, Azure SQL, and Azure Cosmos DB
- [x] Unified virtual namespace (`catalog.schema.table`) resolving multi-store tables
- [x] Federated query planner with predicate pushdown to source relational engines
- [x] Vectorized in-memory hash join execution using DuckDB + Apache Arrow
- [x] Two-tier result and dimension caching for sub-second dashboard performance
- [x] Power BI connectivity via native PostgreSQL wire protocol (DirectQuery) and REST/Arrow Flight (Import)
- [x] Web SQL Studio UI with Monaco editor, catalog autocomplete, execution flame graph, and results grid
- [x] Enterprise Azure Native security (Microsoft Entra ID SSO & Azure Key Vault credential resolution)
- [x] Multi-stage non-root Dockerfiles and AKS Helm chart with NVMe scratch spilling

### Active (Milestone 2 — Phase 5)
- [ ] **REQ-16: Entra ID Claim-to-Policy Mapping**: Extract user governance claims (`trading_desk`, `region`, `entity_id`, `clearance_level`) from Entra ID JWT tokens and map them to fine-grained access policies.
- [ ] **REQ-17: Dynamic Row-Level Security (RLS) AST Filter Injection**: Implement an AST-level query rewriter that transparently injects security filtering predicates into user queries before pushdown planning, guaranteeing zero cross-desk or cross-tenant data leakage.
- [ ] **REQ-18: Column-Level Dynamic Data Masking (DDM)**: Enforce declarative column masking policies (e.g. partial masking `***-**-1234`, IBAN redaction, PII hashing) based on user roles and clearance levels across all queries and views.
- [ ] **REQ-19: Cross-Protocol RLS & Masking Uniformity**: Enforce RLS and DDM uniformly across all query surfaces: REST `/query/execute`, REST Views `/views/**`, OData v4 `/odata/**`, PostgreSQL Wire Protocol `:5433`, and Apache Arrow Flight `:5005`.
- [ ] **REQ-20: SOX/FINRA/Basel III Regulatory Audit Trail**: Structured event logging and metrics capturing full query lifecycle (user identity, original SQL, rewritten SQL, sources accessed, execution time, row count, RLS filters applied, and data export events).

### Out of Scope (Milestone 2)
- Direct write/mutation to upstream data stores (100% read-only access constraint).
- Complex natural language copilot (scheduled for Milestone 3).
- Real-time streaming market data feeds (scheduled for Milestone 4).

## Context

- Target volume: 10 TB – 100 TB of financial transactional and market data
- Cloud ecosystem: Azure (ADLS Gen2, Azure SQL, Cosmos DB) hosted on Azure Kubernetes Service (AKS)
- On-premises connectivity: Corporate network via ExpressRoute / VPN to Oracle and SQL Server
- Read-only constraint: Upstream sources owned by other business units; zero write access; no rewriting or indexing upstream files directly
- Primary consumer: Power BI Desktop and Power BI Service for executive & desk dashboards
