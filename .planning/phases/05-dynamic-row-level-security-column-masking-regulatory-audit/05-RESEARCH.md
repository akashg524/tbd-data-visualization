# Phase 5 Research: Dynamic Row-Level Security, Column Masking & Regulatory Audit Trail

## 1. Executive Summary

Milestone 2 elevates the Federated Semantic Financial Data Hub into a multi-tenant, enterprise-governed platform. By introducing **Dynamic Row-Level Security (RLS)**, **Column-Level Dynamic Data Masking (DDM)**, and **SOX / FINRA Compliance Audit Trails**, the platform guarantees that financial analysts, desk heads, and compliance officers only access authorized slices of the 10 TB – 100 TB multi-store lakehouse without requiring separate data copies or write mutations on upstream source stores.

---

## 2. Threat Modeling & STRIDE Matrix

```
                      Client Request (SQL / View / OData)
                                      │
                                      ▼
                      ┌──────────────────────────────┐
                      │  FastAPI / PGWire / Flight   │
                      └──────────────┬───────────────┘
                                     │
           ┌─────────────────────────┴─────────────────────────┐
           ▼                                                   ▼
┌──────────────────────┐                           ┌──────────────────────┐
│  Threat Boundary 1:  │                           │  Threat Boundary 2:  │
│  Context Tampering   │                           │  Cache Cross-Tenant  │
│  & Role Elevation    │                           │  Data Leakage        │
└──────────────────────┘                           └──────────────────────┘
           │                                                   │
           ▼                                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      SQLGlot AST Security Rewriter                      │
│      - Table Alias Qualification (t.desk = 'FX')                        │
│      - AST Traversal across CTEs, Subqueries, Unions                    │
│      - Column-Level Wildcard (*) Expansion & Expression Masking         │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
                      ┌──────────────────────────────┐
                      │   Pushdown Query Planner     │
                      └──────────────────────────────┘
```

### STRIDE Assessment

| Threat ID | Category | Component | Vulnerability / Attack Vector | Mitigation Strategy |
|:---|:---|:---|:---|:---|
| **T-05-01** | **Information Disclosure** | Result Cache | **Cross-Tenant Cache Poisoning**: User A (Trading Desk: FX) queries `SELECT * FROM trades`. If cached under raw SQL text, User B (Trading Desk: Equity) executes the same text and receives Desk A's data. | **Security Context Fingerprinting**: Incorporate SHA-256 hash of user's active RLS policies (`security_context.fingerprint`) into the cache key: `hash(sql + ":" + security_fingerprint)`. |
| **T-05-02** | **Elevation of Privilege** | AST Rewriter | **Subquery & CTE Bypass**: Attacker constructs `WITH sub AS (SELECT * FROM trades) SELECT * FROM sub` or `UNION SELECT ...` to evade simple top-level WHERE injection. | **Comprehensive AST Traversal**: Traverse all `exp.Select` and `exp.Table` nodes across main query, CTE bodies, subqueries, and set operations (`UNION`, `INTERSECT`). |
| **T-05-03** | **Elevation of Privilege** | AST Rewriter | **Alias Shadowing / Ambiguity**: In multi-table join `trades t JOIN counterparties c`, injecting `WHERE desk = 'FX'` causes ambiguous column errors or incorrect table binding. | **Alias Qualification**: Resolve table alias for each table node and prefix predicate columns with the exact alias (`t.desk = 'FX'`). |
| **T-05-04** | **Information Disclosure** | Dynamic Masking | **Wildcard (`SELECT *`) Data Leak**: Projecting `*` bypasses named column masking. | **Wildcard Expansion**: In the AST rewriter, expand `*` into catalog schema columns and wrap masked columns in SQL masking expressions. |
| **T-05-05** | **Repudiation** | Audit Logger | **Audit Trail Evasion**: Failed queries or aborted exports omit logging, preventing compliance reconstruction. | **Transactional Structured Logging**: Wrap all query executions in try/finally context managers that guarantee structured log emission with unique `request_id`. |

---

## 3. SQLGlot AST Rewriting Deep-Dive

### 3.1. Row-Level Security (RLS) Filter Injection
When an incoming query references a governed table (e.g., `equity.trades`), the AST rewriter must inject appropriate filter conditions:

```python
# Conceptual AST injection
def inject_rls_predicate(select_node: exp.Select, table_alias: str, predicate_sql: str) -> None:
    predicate_ast = sqlglot.parse_one(predicate_sql)
    # Qualify column references in predicate with table alias
    for col in predicate_ast.find_all(exp.Column):
        if not col.table:
            col.set("table", exp.to_identifier(table_alias))
    # Combine with existing WHERE clause via AND
    if select_node.args.get("where"):
        select_node.where(predicate_ast, copy=False)
    else:
        select_node.where(predicate_ast, copy=False)
```

### 3.2. Column-Level Dynamic Data Masking (DDM)
Column masking replaces sensitive column expressions in the `SELECT` projection list with deterministic masking expressions:

| Masking Type | Raw Example | SQL Expression (DuckDB / Remote Compatible) | Masked Output |
|:---|:---|:---|:---|
| **Partial Account / SSN** | `123456789` | `CONCAT('***-**-', SUBSTRING(CAST(col AS VARCHAR), -4, 4))` | `***-**-6789` |
| **Email Redaction** | `trader@firm.com` | `CONCAT(SUBSTRING(col, 1, 1), '***@', SPLIT_PART(col, '@', 2))` | `t***@firm.com` |
| **Full Redaction** | `confidential notes` | `'[REDACTED]'` | `[REDACTED]` |
| **Cryptographic Hash** | `CUST-9872` | `SHA256(CAST(col AS VARCHAR))` | `e3b0c44298fc1...` |

When a privileged role (`ComplianceAdmin`, `SecurityAdmin`) executes the query, the rewriter preserves the original raw column reference.

---

## 4. Cross-Protocol Architecture

The security context must be consistently available across all serving channels:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        SecurityContext Model                           │
│  - user_id: str (sub / username)                                       │
│  - roles: list[str] (FinancialAnalyst, ComplianceAdmin, SecurityAdmin) │
│  - groups: list[str] (Active Directory Security Groups)                │
│  - trading_desks: list[str] (e.g. ['FX', 'COMMODITIES'])               │
│  - regions: list[str] (e.g. ['EMEA', 'US'])                            │
│  - clearance_level: str ('STANDARD', 'CONFIDENTIAL', 'SECRET')         │
│  - fingerprint: str (SHA-256 of active policy constraints)             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    ▼                               ▼                               ▼
FastAPI REST & OData      PostgreSQL Wire Gateway       Apache Arrow Flight
- Extracted from          - Extracted from connection   - Extracted from Flight
  Entra ID Bearer token     handshake username/token      ticket / bearer token
- Dev bypass fallback     - Default session context     - Session call options
```

---

## 5. Regulatory Audit Specification (SOX / FINRA / Basel III)

Financial institutions require comprehensive audit logs of all analytical data access. Every query execution and export will emit a structured JSON event:

```json
{
  "event_type": "analytical_query_execution",
  "timestamp": "2026-10-24T14:30:00.123456Z",
  "request_id": "req-98f2b31a",
  "protocol": "PGWire",
  "user": {
    "sub": "jdoe@enterprise.com",
    "roles": ["FinancialAnalyst"],
    "trading_desks": ["FX"],
    "regions": ["EMEA"]
  },
  "query": {
    "original_sql": "SELECT trade_id, counterparty_ssn, notional FROM equity.trades",
    "secured_sql": "SELECT trade_id, CONCAT('***-**-', SUBSTRING(CAST(counterparty_ssn AS VARCHAR), -4, 4)) AS counterparty_ssn, notional FROM equity.trades WHERE desk = 'FX'",
    "rls_filters_applied": ["desk = 'FX'"],
    "columns_masked": ["counterparty_ssn"],
    "sources_accessed": ["adls_lake.equity.trades"]
  },
  "performance": {
    "duration_ms": 14.2,
    "row_count": 500,
    "cache_hit": false
  },
  "status": "SUCCESS"
}
```
