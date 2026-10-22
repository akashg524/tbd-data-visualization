# Enterprise Financial Data Hub & Semantic Query Layer for Power BI

## What This Is

An enterprise-grade federated semantic query layer and financial data hub connecting 10 TB – 100 TB of read-only financial data across Azure (ADLS Gen2, Azure SQL, Cosmos DB) and on-premises databases (Oracle, SQL Server) directly to Power BI and financial analysts. It executes sub-second federated queries and cross-source joins using Apache Iceberg, DuckDB, PyArrow, and Azure Synapse Serverless SQL.

## Core Value

Enable instantaneous (<1s) and cost-effective federated analytical queries and cross-source joins across 10–100 TB of heterogeneous read-only financial data stores directly into Power BI without commercial virtualization licensing fees.

## Requirements

### Validated
- [x] Initial project scaffolding and developer toolchain (FastAPI, DuckDB, Vite React TypeScript, Tailwind v4, Pytest, Ruff)

### Active
- [ ] Connect and query Apache Iceberg catalog over 10–100 TB ADLS Gen2 Parquet files with manifest-level pruning
- [ ] Read-only connectors for on-premises Oracle, on-premises SQL Server, Azure SQL, and Azure Cosmos DB
- [ ] Unified virtual namespace (`catalog.schema.table`) resolving multi-store tables
- [ ] Federated query planner with predicate pushdown to source relational engines
- [ ] Vectorized in-memory hash join execution using DuckDB + Apache Arrow
- [ ] Two-tier result and dimension caching for sub-second dashboard performance
- [ ] Power BI connectivity via native PostgreSQL wire protocol (DirectQuery) and REST/Arrow Flight (Import)
- [ ] Enterprise Azure Native security (Microsoft Entra ID SSO & Azure Key Vault credential resolution)

### Out of Scope
- Direct write/mutation to upstream data stores (100% read-only access constraint)
- Custom Web UI visualizations in initial milestone (focus prioritized on Data Retrieval & Federation Engine for Power BI)
- Proprietary vendor data virtualization software (e.g. Denodo licenses)

## Context

- Target volume: 10 TB – 100 TB of financial transactional and market data
- Cloud ecosystem: Azure (ADLS Gen2, Azure Synapse, Azure SQL, Cosmos DB) hosted on Azure Kubernetes Service (AKS)
- On-premises connectivity: Corporate network via ExpressRoute / VPN to Oracle and SQL Server
- Read-only constraint: Upstream sources owned by other business units; zero write access; no rewriting or indexing upstream files directly
- Primary consumer: Power BI Desktop and Power BI Service for executive & desk dashboards

## Constraints

- **Security**: Must support Microsoft Entra ID (Azure AD) and Azure Key Vault for credentials
- **Performance**: Sub-second (<1s) dashboard queries via caching and manifest pruning
- **Network**: Minimize cross-network egress by pushing down filtering predicates to Oracle/SQL Server
- **Cost**: Zero 24/7 dedicated compute clusters (use in-process DuckDB for standard joins, Synapse Serverless for large lakehouse scans)

## Key Decisions

- **Apache Iceberg for ADLS**: Used for metadata-level file pruning and audit time-travel snapshots without directory listing overhead.
- **Smart Hybrid Compute**: DuckDB + PyArrow for in-memory joins; Azure Synapse Serverless SQL for multi-TB lakehouse scan fallback.
- **Power BI Delivery**: PostgreSQL wire protocol emulation for seamless DirectQuery without client drivers, plus REST/Arrow Flight for scheduled batch imports.
- **Engine First**: Build and benchmark high-throughput data retrieval and federation engine before web visualization studio.
