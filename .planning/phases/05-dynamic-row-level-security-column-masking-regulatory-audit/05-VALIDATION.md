# Phase 5 Validation Plan & Test Matrix

## 1. Test Architecture

The validation framework for Phase 5 tests all three pillars of enterprise governance:
1. **Unit Tests (`tests/test_governance.py`)**: Tests claim extraction, policy definitions, and security fingerprinting.
2. **AST Rewriter Tests (`tests/test_ast_rewriter.py`)**: Tests SQLGlot AST transformation across complex SQL patterns (joins, CTEs, subqueries, unions, column masking, wildcard expansion).
3. **Cross-Protocol & Audit Tests (`tests/test_security_audit.py`)**: Tests cache isolation across different security contexts, REST/OData/PGWire/Flight integration, and structured audit log emission.

---

## 2. Test Scenarios Matrix

| Test ID | Test Category | Target Component | Input / Scenario | Expected Behavior |
|:---|:---|:---|:---|:---|
| **V-05-01** | Claims & Policy | `SecurityContext` | Entra ID token with `roles=["FinancialAnalyst"]`, `trading_desks=["FX"]`, `regions=["EMEA"]` | Correctly parses claims into `SecurityContext` dataclass. |
| **V-05-02** | Claims & Policy | `SecurityContext` | Two contexts with different desks (`FX` vs `Equity`) | Generate distinct `fingerprint` strings for cache isolation. |
| **V-05-03** | RLS AST Rewriting | `ASTRewriter` | Single table query: `SELECT * FROM trades` | Injects `WHERE (desk = 'FX')` into AST. |
| **V-05-04** | RLS AST Rewriting | `ASTRewriter` | Aliased join: `SELECT * FROM trades t JOIN counterparties c ON t.cid = c.id` | Qualifies aliases: `WHERE (t.desk = 'FX') AND (c.region = 'EMEA')`. |
| **V-05-05** | RLS AST Rewriting | `ASTRewriter` | Query with existing WHERE: `SELECT * FROM trades WHERE notional > 1000` | Combines with `AND`: `WHERE (notional > 1000) AND (desk = 'FX')`. |
| **V-05-06** | RLS AST Rewriting | `ASTRewriter` | Subquery / CTE: `WITH t AS (SELECT * FROM trades) SELECT * FROM t` | Injects RLS into inner CTE table reference. |
| **V-05-07** | RLS AST Rewriting | `ASTRewriter` | Set operation: `SELECT * FROM trades_ny UNION ALL SELECT * FROM trades_lon` | Injects RLS into both branches of the UNION. |
| **V-05-08** | DDM Masking | `ASTRewriter` | Unprivileged analyst projects masked column: `SELECT ssn FROM counterparties` | Replaces `ssn` with masking expression `CONCAT('***-**-', SUBSTRING(CAST(ssn AS VARCHAR), -4, 4)) AS ssn`. |
| **V-05-09** | DDM Masking | `ASTRewriter` | Wildcard projection: `SELECT * FROM counterparties` | Expands `*` into schema columns and applies masking expression to `ssn`. |
| **V-05-10** | Governance Bypass | `ASTRewriter` | Privileged caller (`ComplianceAdmin` or `SecurityAdmin`) | Leaves SQL unchanged (no RLS filter, no column masking). |
| **V-05-11** | Cache Isolation | `ResultCache` | User A (Desk FX) caches `SELECT count(*) FROM trades`; User B (Desk Equity) executes same query | User B gets a cache miss and executes fresh query scoped to Desk Equity (zero cross-tenant leakage). |
| **V-05-12** | Audit Logging | `AuditLogger` | Query execution and CSV export | Structured JSON log emitted with `request_id`, `user_id`, `original_sql`, `secured_sql`, `row_count`, `duration_ms`. |
| **V-05-13** | Cross-Protocol | `FederatedExecutor` | Execution through REST, Views, OData, and Export | All endpoints enforce RLS and DDM uniformly. |

---

## 3. Exit Criteria
- 100% green execution across all new tests (`pytest tests/test_governance.py tests/test_ast_rewriter.py tests/test_security_audit.py`).
- Zero regressions across existing 103 unit and integration tests (totaling 120+ tests).
- Clean `ruff check` with zero linting or type violations.
