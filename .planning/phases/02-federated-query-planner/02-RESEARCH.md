# Phase 2: Hybrid Federated Query Planner & In-Memory Join Engine — Research

## Standard Stack

| Layer | Library / Tool | Version | Role & Justification |
| :--- | :--- | :--- | :--- |
| **SQL AST Parser & Transpiler** | `sqlglot` | `^30.24` | State-of-the-art pure-Python SQL parser and semantic optimizer. Builds full Abstract Syntax Trees (AST), resolves table aliases, isolates predicate expressions, and transpiles to source dialects (Oracle, T-SQL, Postgres, DuckDB) without C-dependencies. |
| **Vectorized Join Engine** | `duckdb` | `^1.5` | In-memory analytical OLAP engine. Uses compiled C++ SIMD vectorization to execute hash joins across Arrow tables at tens of millions of rows per second per CPU core with automatic out-of-core disk spilling. |
| **Columnar Memory Bus** | `pyarrow` | `^19.0` | Zero-copy in-memory format. Connectors stream Arrow tables directly into DuckDB via `conn.register()`, avoiding serialization and garbage collection overhead. |
| **Async Orchestration** | `asyncio` | Built-in | Dispatches pushed-down subqueries in parallel across remote network connections (Oracle over VPN, ADLS over TLS, Cosmos over HTTP). |

---

## Architecture Patterns

### 1. The Federated Query Execution Pipeline

```
Incoming SQL (Power BI / Studio)
              │
              ▼
   [1. SQLGlot AST Parser]
              │
              ▼
   [2. Catalog Table Resolution] ──> Resolves catalog.schema.table via UnifiedCatalogRegistry
              │
              ├── Single Source? ──> [Direct Pushdown] (Execute 100% on native DB)
              │
              └── Multi-Source? (Cross-Source Join)
                     │
                     ▼
        [3. Pushdown Predicate Splitter]
                     ├── Filters for Source A ──> Subquery A (e.g. Oracle SQL)
                     └── Filters for Source B ──> Subquery B (e.g. ADLS Iceberg)
                     │
                     ▼
        [4. Parallel Async Execution] (asyncio.gather)
                     ├── Connector A ──> Arrow Table A (e.g. 500 KB)
                     └── Connector B ──> Arrow Table B (e.g. 25 MB)
                     │
                     ▼
        [5. DuckDB Vectorized Hash Join]
                     ├── Register Table A as __subq_0 (Zero-Copy)
                     ├── Register Table B as __subq_1 (Zero-Copy)
                     └── Execute Rewritten Root Join Query in C++ RAM
                             │
                             ▼
                    Final pyarrow.Table (<1.5s total)
```

### 2. Isolated vs. Mixed Predicate Extraction
* **Isolated Predicates:** Predicates referencing columns from **only one table** (e.g., `t.trade_date >= '2026-10-01'` or `c.country = 'US'`) are stripped from the root query and pushed down to the source.
* **Mixed / Cross-Table Predicates:** Predicates referencing columns from **multiple tables** (e.g., `WHERE t.notional_usd > c.credit_limit`) cannot be evaluated by either source independently. They **must remain in the root query** and are evaluated by DuckDB during the join phase.

### 3. Dialect Transpilation
Each database engine speaks a different SQL dialect:
* **Oracle:** Requires `FETCH FIRST N ROWS ONLY` instead of `LIMIT`, uppercase identifiers, and Oracle-specific date functions.
* **SQL Server:** Requires `SELECT TOP N` instead of `LIMIT`, bracket escaping (`[table]`), and T-SQL string functions.
* **DuckDB:** Uses standard PostgreSQL-style syntax with native vectorized functions.
`sqlglot.to_sql(ast, dialect='oracle')` handles dialect conversion automatically.

---

## Don't Hand-Roll

* **DO NOT use regex or string manipulation to split SQL queries:** Complex financial SQL includes aliases, nested CTEs, subqueries, and table functions. String manipulation will fail. Always use `sqlglot` AST traversal.
* **DO NOT copy Arrow tables into Python dictionaries before joining:** Use DuckDB's zero-copy pointer registration:
  ```python
  conn.register("__subq_0", arrow_table_0)
  ```
  This points DuckDB's C++ engine directly to the PyArrow memory buffer with zero allocation overhead.
* **DO NOT perform nested-loop joins in Python:** Python loops on 100,000 rows take seconds; DuckDB vectorized hash joins take under 50 milliseconds.
* **DO NOT pull unprojected columns:** Always project only the columns explicitly requested in `SELECT`, `JOIN ON`, `WHERE`, `GROUP BY`, and `ORDER BY`.

---

## Common Pitfalls & How to Avoid Them

### 1. Column Name Collisions in Subqueries
* *Pitfall:* If both tables have a column named `id` or `status`, pushing down `SELECT id FROM table1` and `SELECT id FROM table2` can cause ambiguous column errors when DuckDB executes the root join.
* *Solution:* In subqueries, columns required for the join are aliased or prefixed if necessary, or the root query explicitly references `__subq_0.id` and `__subq_1.id`.

### 2. Data Type Mismatches on Join Keys
* *Pitfall:* ADLS Iceberg represents a counterparty ID as `BIGINT` (64-bit integer), while an on-prem database represents it as `VARCHAR(20)` or `DECIMAL(10,0)`. Direct hash joins in DuckDB will fail or return 0 matching rows due to type strictness.
* *Solution:* The query planner checks the data types of join keys from the `TableSchema` metadata and injects explicit `CAST(c.counterparty_id AS BIGINT)` into the join predicate if types diverge.

### 3. Out-Of-Memory (OOM) on Massive Result Sets
* *Pitfall:* If a join produces 10 million rows, loading the entire result into memory at once can exhaust pod RAM on AKS.
* *Solution:* DuckDB provides automatic disk spilling to local SSD when RAM limits are reached, and results can be streamed in chunks using `RecordBatchReader`.

---

## Code Examples

### A. SQLGlot Table & Predicate Separation
```python
import sqlglot
from sqlglot import exp

def decompose_query(sql: str) -> tuple[dict[str, str], dict[str, set[str]], list[exp.Expression]]:
    ast = sqlglot.parse_one(sql)
    
    # 1. Alias to full table mapping
    alias_map = {}
    for table in ast.find_all(exp.Table):
        alias = table.alias_or_name
        parts = [p for p in [table.catalog, table.db, table.name] if p]
        alias_map[alias] = ".".join(parts)
        
    # 2. Extract columns per alias
    cols_by_alias = {alias: set() for alias in alias_map}
    for col in ast.find_all(exp.Column):
        if col.table in cols_by_alias:
            cols_by_alias[col.table].add(col.name)
            
    # 3. Separate isolated predicates from mixed predicates
    isolated_predicates = {alias: [] for alias in alias_map}
    mixed_predicates = []
    
    where = ast.find(exp.Where)
    if where:
        for conj in where.this.flatten():
            target_tables = {c.table for c in conj.find_all(exp.Column) if c.table}
            if len(target_tables) == 1:
                target_alias = next(iter(target_tables))
                isolated_predicates[target_alias].append(conj)
            else:
                mixed_predicates.append(conj)
                
    return alias_map, cols_by_alias, isolated_predicates, mixed_predicates
```

### B. DuckDB Zero-Copy In-Memory Hash Join
```python
import duckdb
import pyarrow as pa

def execute_in_memory_join(
    duck_conn: duckdb.DuckDBPyConnection,
    subqueries: dict[str, pa.Table],
    root_sql: str
) -> pa.Table:
    # Zero-copy pointer registration
    for view_name, arrow_table in subqueries.items():
        duck_conn.register(view_name, arrow_table)
        
    relation = duck_conn.sql(root_sql)
    res = relation.arrow()
    return res.read_all() if hasattr(res, "read_all") else res
```

---

## Validation Architecture

### Test Infrastructure
- **Framework**: `pytest` 8.4+ with `pytest-asyncio`
- **Unit Test Command**: `pytest tests/test_sql_parser.py tests/test_pushdown_compiler.py -v`
- **Federation Test Command**: `pytest tests/test_federated_executor.py -v`
- **Full Suite Command**: `pytest tests/ -v`

### Automated Verification Targets
1. `tests/test_sql_parser.py`: Verify AST parsing, alias resolution, and single vs. multi-source detection across various SQL constructs (joins, subqueries, aggregations).
2. `tests/test_pushdown_compiler.py`: Verify extraction of isolated predicates, dialect transpilation (Oracle, T-SQL, DuckDB), and column projection minimization.
3. `tests/test_federated_executor.py`: End-to-end simulation of cross-source joins (e.g. ADLS Iceberg Arrow table joined with Oracle Arrow table in DuckDB) validating execution speed, memory footprint, and result accuracy.
