---
phase: 02-federated-query-planner
plan: 02-01
subsystem: federation
tags:
  - sqlglot
  - parser
  - compiler
  - pushdown
  - ast
completed_at: 2026-10-24T04:49:00Z
---

# Plan 02-01 Summary: SQL AST Parser & Pushdown Predicate Compiler

## What Was Built
- **`SQLParser` (`backend/app/federation/parser.py`)**:
  - AST-driven SQL parser built on `sqlglot` resolving 3-part virtual namespaces (`datasource.schema.table`) against `UnifiedCatalogRegistry`.
  - Maps table aliases and extracts exact column projections across `SELECT`, `WHERE`, `JOIN ON`, `GROUP BY`, `ORDER BY`, and `HAVING`.
  - Unpacks CTEs and prevents local CTE view aliases from being treated as remote datasources.
  - Classifies queries into single-source vs. multi-source cross-database joins.
  - Implements security validations: strictly rejects SQL mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `MERGE`), enforces max query length (50,000 chars), and limits AST complexity.
- **`PushdownCompiler` (`backend/app/federation/compiler.py`)**:
  - Recursively extracts top-level conjuncts from `WHERE` clauses and isolates unmixed single-table predicates from mixed multi-table join conditions.
  - Synthesizes dialect-transpiled subqueries per remote table (`oracle` with `FETCH FIRST`, `tsql` with `SELECT TOP`, `duckdb` with `LIMIT`).
  - Generates single-source bypass SQL (`compile_single_source_sql`) directly executable on remote engines without DuckDB join overhead.
  - Rewrites root AST for DuckDB hash join, replacing catalog table references with isolated views (`__subq_{alias}`) and retaining only mixed cross-table predicates.
- **Automated Test Suite**:
  - `tests/test_sql_parser.py`: 10 tests verifying single/multi-source classification, 3-system joins (ADLS + Oracle + MSSQL), star expansions, CTE parsing, security rejections, and catalog error handling.
  - `tests/test_pushdown_compiler.py`: 7 tests verifying predicate isolation, mixed predicate retention, single-table disjunction pushdown, single-source bypass transpilation, and DuckDB root AST generation.

## Key Files Created
- `backend/app/federation/__init__.py`
- `backend/app/federation/parser.py`
- `backend/app/federation/compiler.py`
- `tests/test_sql_parser.py`
- `tests/test_pushdown_compiler.py`
- `.planning/phases/02-federated-query-planner/02-01-SUMMARY.md`

## Verification Results
- `pytest tests/test_sql_parser.py tests/test_pushdown_compiler.py -v`: 17 passed in 0.34s.
- Full test suite: 40 passed in 9.43s.
- `ruff check backend/ tests/`: All checks passed clean.

## Deviations from Plan
- **CTE Support Added**: Extended AST traversal to discover `exp.CTE` definitions and track CTE aliases so that local DuckDB CTE expressions can freely query federated tables without triggering unqualified column validation errors.

## Threat Flags
None. All STRIDE mitigations from plan threat model verified:
- `T-02-01` (Tampering / SQL Injection): Queries parsed exclusively via AST nodes; all non-SELECT queries rejected.
- `T-02-02` (Denial of Service): Maximum SQL length and AST node depth verified.
- `T-02-03` (Information Disclosure): Table identifiers validated against catalog.
