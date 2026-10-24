# Phase 4: Web SQL Studio, Enterprise Security & AKS Production Deployment - Context

**Gathered:** 2026-10-24
**Status:** Research complete, ready for planning
**Source:** Phase 4 Research, Enterprise Architecture Requirements & Azure Cloud Standards

<domain>
## Phase Boundary

Deliver production-ready user interfaces, enterprise security, and cloud deployment manifests:
1. **Monaco Web SQL Studio**: Internal web cockpit featuring catalog schema tree navigation, Monaco code editor with dynamic autocompletion, visual explain execution timeline, results grid, export integration, and 1-click launcher downloads.
2. **Enterprise Azure Security & RBAC**: Microsoft Entra ID (Azure AD) SSO with JWT validation, Azure Workload Identity, Role-Based Access Control (`FinancialAnalyst`, `DataEngineer`, `SecurityAdmin`), and dev bypass.
3. **AKS Production Packaging & Networking**: Production multi-stage Dockerfiles, Helm chart packaging, local NVMe/SSD `/scratch` volume for DuckDB out-of-core spill, multi-protocol Service (HTTP 8000, PGWire 5433, Arrow Flight 5005), and VNet Peering blueprint for on-premises database connectivity via ExpressRoute.

</domain>

<decisions>
## Implementation Decisions

### 1. Monaco SQL Studio Frontend
- **Editor**: `@monaco-editor/react` with dark theme (`vs-dark`).
- **Autocompletion**: Dynamic completion provider injecting catalog schemas, table paths (`datasource.schema.table`), and column names into Monaco.
- **Execution Cockpit**: Visual timeline displaying planning ms, per-source subquery pushdown ms, DuckDB join ms, cache hit badge, and spill alerts.
- **Export & Launchers**: Direct UI buttons for CSV/Parquet/NDJSON streaming exports and `.pbids` / `.odc` connection launcher downloads.

### 2. Microsoft Entra ID SSO & Role-Based Access Control
- **JWT Verification**: `pyjwt[crypto]` using `PyJWKClient` pointing to `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys`.
- **Role Enforcement**: FastAPI dependency checking `roles` or `groups` claims for `FinancialAnalyst` (query/export), `DataEngineer` (cache/catalog refresh), `SecurityAdmin` (system/vault config).
- **Zero-Trust Dev Toggle**: `AUTH_ENABLED: bool = False` (defaults to False in development/testing, True in production).

### 3. AKS Helm Packaging & Out-of-Core Scratch Architecture
- **Scratch Volume**: Mount an `emptyDir` backed by local ephemeral SSD at `/scratch` and set `DUCKDB_TEMP_DIRECTORY=/scratch` to allow multi-gigabyte/s NVMe bus spill during massive joins.
- **Multi-Port Service**: Expose HTTP (8000), PGWire (5433), and Arrow Flight (5005) via Kubernetes Service.
- **Networking Blueprint**: Azure VNet peering from AKS cluster VNet to ExpressRoute Hub VNet for on-premises Oracle and SQL Server access.

</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md` — Enterprise security and AKS constraints
- `.planning/ROADMAP.md` — Phase 4 requirements (REQ-13 through REQ-15)
- `.planning/phases/04-web-sql-studio-enterprise-security-aks/04-RESEARCH.md` — Detailed research and architecture blueprints

</canonical_refs>

<deferred>
## Deferred Ideas

- Advanced automated query cost estimation (future release)
- Real-time collaborative SQL editing (future release)
</deferred>
