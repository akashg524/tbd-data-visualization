# Roadmap: Enterprise Financial Data Hub & Semantic Query Layer

## Overview

A phased journey from foundational read-only connectors and Apache Iceberg cataloging, to a high-speed federated query planner and in-memory join engine, up to Power BI serving and enterprise AKS deployment.

## Phases

- [x] **Phase 1: High-Performance Read-Only Connectors & Iceberg Catalog** - Connect ADLS Gen2 Iceberg, Oracle, SQL Server, Azure SQL, and Cosmos DB with unified metadata introspection.
- [ ] **Phase 2: Hybrid Federated Query Planner & In-Memory Join Engine** - Build predicate pushdown query compiler and vectorized DuckDB hash joiner with Arrow streaming.
- [ ] **Phase 3: Speed Layer & Semantic Power BI Serving** - Implement two-tier result/dimension caching and PostgreSQL wire protocol / Arrow Flight gateway for Power BI DirectQuery.
- [ ] **Phase 4: Web SQL Studio, Enterprise Security & AKS Production Deployment** - Monaco SQL Studio, Entra ID SSO, Key Vault, and Helm/Kubernetes deployment manifests.

---

## Phase Details

### Phase 1: High-Performance Read-Only Connectors & Iceberg Catalog
**Goal**: Establish enterprise-grade, read-only connectors for ADLS Gen2 (Apache Iceberg/Parquet), On-Premises Oracle, On-Premises SQL Server, Azure SQL, and Cosmos DB, unified under a single virtual schema registry.
**Depends on**: Nothing (first phase)
**Requirements**: [REQ-01: Key Vault & Credential Resolution, REQ-02: Apache Iceberg ADLS Connector, REQ-03: Relational Read-Only Connectors (Oracle, SQL Server, Azure SQL), REQ-04: Cosmos DB Connector, REQ-05: Unified Schema Catalog Registry]
**Success Criteria** (what must be TRUE):
  1. Credentials resolve dynamically from Azure Key Vault with fallback to mock/env for local development.
  2. Apache Iceberg catalog reader can inspect ADLS Gen2 tables and retrieve file manifests and column statistics without listing storage directories.
  3. Oracle and SQL Server connectors strictly enforce read-only execution (`ApplicationIntent=ReadOnly`, read-only transactions) and introspect schemas, tables, and column types.
  4. Cosmos DB connector samples container schemas and builds tabular column definitions with partition-key metadata.
  5. Unified Schema Registry exposes a single hierarchical namespace (`catalog.schema.table`) resolving tables across all connected stores.
**Plans**: 3 plans

Plans:
- [x] 01-01: Credential Vault & Pluggable Base Connector Architecture
- [x] 01-02: Apache Iceberg ADLS Gen2 & Cosmos DB Connectors
- [x] 01-03: Relational Read-Only Connectors (Oracle, MSSQL, Azure SQL) & Unified Catalog Registry

### Phase 2: Hybrid Federated Query Planner & In-Memory Join Engine
**Goal**: Compile federated SQL across multiple stores, push down predicates to source engines, and execute vectorized cross-source hash joins in DuckDB/PyArrow.
**Depends on**: Phase 1
**Requirements**: [REQ-06: SQL AST Parser & Cross-Source Decomposer, REQ-07: Pushdown Predicate Compiler, REQ-08: DuckDB Vectorized Hash Joiner, REQ-09: Arrow Streaming Pipeline]
**Success Criteria** (what must be TRUE):
  1. SQL queries joining ADLS Iceberg with Oracle/SQL Server parse and decompose into source-specific subqueries.
  2. Predicate filters and column projections are pushed down natively to Oracle and SQL Server.
  3. DuckDB joins incoming Arrow record batches in memory at sub-second speeds.
**Plans**: TBD

### Phase 3: Speed Layer & Semantic Power BI Serving
**Goal**: Enable Power BI DirectQuery and scheduled import via PostgreSQL wire-protocol listener and REST/Arrow Flight endpoints with two-tier caching.
**Depends on**: Phase 2
**Requirements**: [REQ-10: Result-Set & Dimension Cache, REQ-11: PostgreSQL Wire Protocol Gateway, REQ-12: Arrow Flight / OData Feed]
**Success Criteria** (what must be TRUE):
  1. Power BI Desktop connects via standard PostgreSQL connector and issues DirectQuery requests.
  2. Repeated dashboard queries return in <5ms from in-memory cache.
**Plans**: TBD

### Phase 4: Web SQL Studio, Enterprise Security & AKS Production Deployment
**Goal**: Provide internal Monaco SQL Studio, Microsoft Entra ID authentication, and production Kubernetes packaging.
**Depends on**: Phase 3
**Requirements**: [REQ-13: Monaco SQL Studio, REQ-14: Microsoft Entra ID SSO, REQ-15: AKS Helm Chart & Docker Containerization]
**Success Criteria** (what must be TRUE):
  1. Analysts can query, test, and explain federated queries in a web-based Monaco SQL Studio.
  2. System deploys to AKS with VNet peering to on-premises networks.
**Plans**: TBD
