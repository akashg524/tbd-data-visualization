# Plan 05-02 Summary: SQLGlot AST RLS Rewriter & Pluggable ACL Filter Injection Engine

## Completed Tasks
1. **SQLGlot AST Security Rewriter (`ASTRewriter`)**:
   - Implemented `backend/app/federation/rewriter.py`:
     - Walks all `exp.Table` nodes in AST query representations, ignoring in-query CTE references.
     - **Gate 1 Coarse-Grained RBAC Check**: Validates user's roles against `TableSecurityPolicy.required_roles`, immediately raising `PermissionError` if the caller lacks permission on any referenced table.
     - **Gate 2 Fine-Grained ACL/RLS Synthesis**: Dynamically qualifies table aliases (`t.desk_code = 'FX'`), prevents ambiguous columns in multi-table joins, and appends predicates to enclosing `WHERE` clauses.
     - **Pluggable Strategies**: Executes direct column matching and value translation (e.g. region names `["US", "EMEA"]` -> integer IDs `[1, 2]`).
     - **Strict Fail-Closed**: Injects `1 = 0` when an unprivileged user has no entitlement claims for governed tables.
     - Supports CTEs, nested subqueries, and set operations (`UNION`, `UNION ALL`).
     - Preserves full unconstrained queries for `ComplianceAdmin` and `SecurityAdmin` roles.

2. **Federation Module Integration**:
   - Exported `ASTRewriter` in `backend/app/federation/__init__.py`.

3. **Comprehensive AST Rewriter Test Suite**:
   - Implemented `tests/test_ast_rewriter.py` covering 12 test scenarios:
     - Scalar query passthrough.
     - Gate 1 RBAC denial (PermissionError on unauthorized tables).
     - Gate 1 RBAC permission for authorized roles.
     - Single-table direct RLS predicate injection.
     - Translation strategy RLS injection (name-to-ID).
     - Composite ACL injection (multiple claims combining with `AND`).
     - Multi-table join table alias qualification.
     - Existing WHERE clause combination.
     - CTE inner subquery table injection.
     - UNION query branches.
     - Fail-closed empty claim handling (`1 = 0`).
     - ComplianceAdmin bypass.

## Verification
- `pytest tests/test_ast_rewriter.py -v`: All 12 tests passed in 0.15s.
- Total governance test suite: 31 passed in 6.69s.
- `ruff check backend/ tests/`: 0 errors, 0 warnings.
