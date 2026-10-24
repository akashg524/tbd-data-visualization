# Phase 5 Context: Dynamic Row-Level Security, Column Masking & Regulatory Audit Trail

## 1. Business & Regulatory Mandates

In institutional banking, capital markets, and asset management:
1. **Trading Desk Segregation (Chinese Wall / Information Barriers):** An FX trader or quantitative analyst must not view Commodities or Equity proprietary position books unless explicitly cleared.
2. **Data Privacy & PII Protection (GDPR, CCPA):** Personal customer identifiers, counterparty tax IDs, SSNs, and IBAN numbers must be masked at rest and in transit unless queried by authorized compliance personnel.
3. **Regulatory Auditability (SOX Section 404, FINRA Rule 4511, BCBS 239):** Every query execution and export must be deterministically logged with user provenance, original vs. rewritten SQL, and performance telemetry.
4. **Zero Upstream Overhead:** Because upstream databases (Oracle Active Data Guard, SQL Server AlwaysOn, ADLS Gen2 Iceberg) are owned across disparate corporate departments, row-level filtering and column masking **must not require altering upstream database schemas, views, or database roles**. All enforcement takes place within the federated semantic layer.

---

## 2. Scope Boundaries

### In Scope
- **`SecurityContext` model & Entra ID claim mapping:** Extracting `trading_desk`, `region`, `entity_id`, and `clearance_level` from tokens and mock identities.
- **Declarative Governance Policies:** Defining table-level RLS rules and column-level DDM masking specs in a centralized registry.
- **AST Security Transformer:** Parsing user queries into SQLGlot AST, injecting qualified `WHERE` predicates into joins/subqueries/CTEs, expanding wildcards, and wrapping sensitive projections in masking expressions.
- **Cache Fingerprinting:** Augmenting ResultCache keys with user security fingerprints to prevent cross-desk data leakage.
- **Cross-Protocol Propagation:** Propagating `SecurityContext` through REST endpoints, OData v4 feeds, Buenavista PGWire (:5433), and Apache Arrow Flight (:5005).
- **Structured Compliance Audit Trail:** Structured JSON logging for query executions and export actions.

### Out of Scope
- Direct row-level security policy creation on upstream Oracle or SQL Server engines (read-only service account remains unchanged).
- Natural language query copilot (scheduled for Milestone 3).

---

## 3. Key Codebase Integrations

- **`backend/app/auth/`:**
  - `entra.py`: Extends `EntraIDAuthenticator` to extract governance claims from JWT payloads.
  - `rbac.py`: Adds `ComplianceAdmin` role and `SecurityContext` dependency.
  - `governance.py`: New module defining `GovernancePolicyRegistry`, `RowLevelSecurityPolicy`, and `ColumnMaskingPolicy`.
- **`backend/app/federation/`:**
  - `rewriter.py`: New AST rewriter module leveraging `sqlglot` to inject RLS predicates and apply DDM expressions.
  - `executor.py`: Updated `FederatedExecutor.execute` accepting `SecurityContext`, passing secured SQL, and fingerprinting the result cache.
- **`backend/app/cache.py`:**
  - `ResultCache.get(sql, security_fingerprint)` and `set(sql, table, security_fingerprint)`.
- **`backend/app/serving/`:**
  - `pgwire.py`: Injects `SecurityContext` into Buenavista `FederatedSession`.
  - `flight.py`: Resolves `SecurityContext` from Flight call options / ticket.
  - `export.py`: Emits export audit event.
