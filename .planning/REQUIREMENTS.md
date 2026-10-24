# Requirements Specification: Milestone 2

## Milestone 2: Enterprise Governance, Row-Level Security (RLS) & Dynamic Masking

### REQ-16: Entra ID Claim-to-Policy Mapping
**Description**: The platform must inspect Microsoft Entra ID JWT bearer tokens (and dev bypass identities) to extract governance claims, including user identifier (`sub`, `preferred_username`), roles (`roles`), group memberships (`groups`), trading desks (`trading_desk`), geographic regions (`region`), legal entities (`entity_id`), and clearance levels (`clearance_level`).
- When governance claims are absent, sensible secure defaults or unconstrained access (for SecurityAdmin) must be applied.
- Support configuration of policy mappings mapping Entra ID security groups to specific desk/region restrictions.

### REQ-17: Dynamic Row-Level Security (RLS) AST Filter Injection
**Description**: The SQL query rewriter must parse incoming queries using SQLGlot, locate all table references against protected schemas/tables, and inject security filter predicates (e.g. `desk = 'FX_DESK'` or `region IN ('EMEA', 'APAC')`) directly into the `WHERE` clause before query planning.
- Injected predicates must propagate into pushdown queries to remote databases (Oracle, SQL Server) and Iceberg manifest pruning.
- Prevent query bypasses or SQL injection via subqueries, CTEs (`WITH` clauses), or union queries.

### REQ-18: Column-Level Dynamic Data Masking (DDM)
**Description**: Define declarative masking rules for sensitive columns (e.g., customer PII, account numbers, IBANs, trader emails, SSNs).
- Masking functions include: `partial(prefix, suffix, mask_char)` (e.g. `****-****-****-1234`), `email_mask()`, `redact()`, and `hash_sha256()`.
- Users with privileged roles (`ComplianceAdmin`, `SecurityAdmin`) or high clearance levels receive unmasked raw data.
- Standard `FinancialAnalyst` callers receive masked columns dynamically without changing underlying data storage.

### REQ-19: Cross-Protocol RLS & Masking Uniformity
**Description**: RLS predicate injection and column masking must be enforced consistently across all access channels:
- REST API `/api/v1/query/execute`
- RESTful Views API `/api/v1/views/**`
- OData v4 Feed Service `/api/v1/odata/**`
- Chunked Export API `/api/v1/export/**`
- PostgreSQL Wire Protocol Gateway (port 5433)
- Apache Arrow Flight Server (port 5005)

### REQ-20: SOX/FINRA/Basel III Regulatory Audit Trail
**Description**: Produce structured audit log events for every query execution and export request, recording:
- Timestamp, request ID, user identity (`sub`, `preferred_username`), and role.
- Client IP, connection protocol (REST, PGWire, Flight, OData).
- Original user SQL and rewritten SQL (with injected RLS filters).
- Data sources and table paths accessed.
- Query execution duration, row count, cache hit/miss status, and whether results were exported.
- Log output emitted to structured JSON logger (`structlog`) ready for Azure Monitor / Log Analytics ingestion.
