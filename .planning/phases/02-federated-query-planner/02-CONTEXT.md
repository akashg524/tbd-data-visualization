# Phase 2: Hybrid Federated Query Planner & In-Memory Join Engine - Context

**Gathered:** 2026-10-24
**Status:** Ready for planning
**Source:** Phase 2 Research & Architecture Blueprint

<domain>
## Phase Boundary

Build the SQL AST decomposition planner, the predicate pushdown compiler, and the DuckDB vectorized in-memory hash joiner capable of executing arbitrary cross-source federated queries across ADLS Gen2 Iceberg, Oracle, and SQL Server with zero-copy Apache Arrow streaming.

</domain>

<decisions>
## Implementation Decisions

### 1. SQL Parser & Query Decomposer
- **Library:** Use `sqlglot` for AST parsing, table alias resolution, and dialect transpilation.
- **Routing:**
  - If all referenced tables reside in the same data source: execute 100% via direct pushdown on the native source connector.
  - If tables span multiple distinct data sources: decompose into source-specific subqueries.

### 2. Pushdown Predicate Optimization
- **Isolated Predicates:** Predicates referencing columns from a single table (e.g., `trade_date >= '2026-10-01'` or `country = 'US'`) must be compiled into the source subquery.
- **Dialect Transpilation:** Subqueries targeting Oracle use Oracle SQL dialect (`FETCH FIRST N ROWS ONLY`); subqueries targeting SQL Server use T-SQL (`SELECT TOP N`); ADLS Iceberg uses standard SQL.
- **Mixed Predicates:** Predicates spanning multiple sources (e.g. `WHERE t.amount > c.limit`) remain in the root query evaluated by DuckDB.

### 3. In-Memory Vectorized Join Execution
- **Zero-Copy Registration:** Subquery result sets are returned as `pyarrow.Table` and registered directly into an in-memory DuckDB connection via `conn.register("__subq_alias", arrow_table)`.
- **Join Execution:** DuckDB executes the rewritten join query using vectorized SIMD C++ execution.
- **Output:** Returns a zero-copy `pyarrow.Table`.

### 4. Concurrency & Performance
- Subqueries must execute in parallel using `asyncio.gather()` across network connections.
- Record execution metrics: planning time, subquery execution times, join execution time, and total rows produced.

</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md` — Project scope and performance goals
- `.planning/ROADMAP.md` — Phase 2 requirements (REQ-06 through REQ-09)
- `.planning/phases/02-federated-query-planner/02-RESEARCH.md` — Technical research, AST decomposition patterns, and pitfalls

</canonical_refs>

<deferred>
## Deferred Ideas

- PostgreSQL wire protocol listener (:5432) for Power BI (Phase 3)
- In-memory result cache and local SSD dimension cache (Phase 3)
- Web UI Monaco query studio (Phase 4)

</deferred>
