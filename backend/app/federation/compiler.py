"""Pushdown predicate compiler and subquery transpile engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlglot
import structlog
from pydantic import BaseModel, Field
from sqlglot import exp

if TYPE_CHECKING:
    from app.federation.parser import ParsedQuery

logger = structlog.get_logger(__name__)


class SubqueryPlan(BaseModel):
    """Specification of a pushdown subquery targeted at a specific datasource."""

    alias: str
    datasource_name: str
    schema_name: str
    table_name: str
    projected_columns: list[str] = Field(default_factory=list)
    sql: str
    dialect: str


def extract_conjuncts(node: exp.Expression | None) -> list[exp.Expression]:
    """Recursively extract top-level AND conjuncts, unpacking parentheses where appropriate."""
    if node is None:
        return []
    if isinstance(node, exp.Paren):
        if isinstance(node.this, exp.And):
            return extract_conjuncts(node.this)
        return [node]
    if isinstance(node, exp.And):
        return extract_conjuncts(node.left) + extract_conjuncts(node.right)
    return [node]


class PushdownCompiler:
    """Compiles a ParsedQuery into isolated pushdown subqueries and a rewritten root join AST."""

    @classmethod
    def compile(cls, parsed: ParsedQuery) -> tuple[dict[str, SubqueryPlan], exp.Expression]:
        """Separate isolated predicates, build dialect-transpiled subqueries, and rewrite root AST."""
        isolated_predicates: dict[str, list[exp.Expression]] = {ref.alias: [] for ref in parsed.tables}
        mixed_predicates: list[exp.Expression] = []

        # Alias lookup mapping (including case-insensitive table name lookups)
        alias_lookup: dict[str, str] = {}
        for ref in parsed.tables:
            alias_lookup[ref.alias.lower()] = ref.alias
            alias_lookup[ref.table_name.lower()] = ref.alias

        # 1. Decompose WHERE conjuncts into isolated vs. mixed
        where_node = parsed.ast.find(exp.Where)
        if where_node:
            conjuncts = extract_conjuncts(where_node.this)
            for conj in conjuncts:
                ref_aliases: set[str] = set()
                cols = list(conj.find_all(exp.Column))
                for col in cols:
                    if col.table:
                        tbl_key = col.table.lower()
                        if tbl_key in alias_lookup:
                            ref_aliases.add(alias_lookup[tbl_key])
                    elif len(parsed.tables) == 1:
                        ref_aliases.add(parsed.tables[0].alias)

                if len(ref_aliases) == 1:
                    target_alias = next(iter(ref_aliases))
                    isolated_predicates[target_alias].append(conj.copy())
                else:
                    mixed_predicates.append(conj.copy())

        # 2. Build subquery plans per table
        subqueries: dict[str, SubqueryPlan] = {}
        for ref in parsed.tables:
            alias = ref.alias
            cols = parsed.columns_by_alias.get(alias, set())

            # Format projection clause
            if "*" in cols or not cols:
                select_clause = "*"
                projected_cols = ["*"]
            else:
                projected_cols = sorted(cols)
                select_clause = ", ".join(f"{alias}.{c}" for c in projected_cols)

            # Format remote table target
            if ref.schema_name and ref.schema_name.lower() != "default":
                remote_table = f"{ref.schema_name}.{ref.table_name}"
            else:
                remote_table = ref.table_name

            # Structured subquery generation validated through AST parsing
            subq_sql = f"SELECT {select_clause} FROM {remote_table} AS {alias}"  # noqa: S608
            subq_ast = sqlglot.parse_one(subq_sql)

            # Attach isolated WHERE predicates if any exist
            isolated = isolated_predicates.get(alias, [])
            if isolated:
                combined_where = exp.and_(*isolated)
                subq_ast.set("where", exp.Where(this=combined_where))

            # Transpile to target dialect
            transpiled_sql = subq_ast.sql(dialect=ref.dialect)

            subqueries[alias] = SubqueryPlan(
                alias=alias,
                datasource_name=ref.datasource_name,
                schema_name=ref.schema_name,
                table_name=ref.table_name,
                projected_columns=projected_cols,
                sql=transpiled_sql,
                dialect=ref.dialect,
            )

        # 3. Rewrite root AST for DuckDB hash join
        root_ast = parsed.ast.copy()
        cte_names = {cte.alias_or_name.lower() for cte in root_ast.find_all(exp.CTE)}

        for tbl in list(root_ast.find_all(exp.Table)):
            tbl_name = tbl.name
            if tbl_name.lower() in cte_names:
                continue

            tbl_alias = tbl.alias if tbl.alias else tbl.alias_or_name
            if not tbl_alias:
                tbl_alias = tbl_name

            # Lookup matching table alias
            matched_alias = alias_lookup.get(tbl_alias.lower(), tbl_alias)
            view_name = f"__subq_{matched_alias}"
            tbl.replace(exp.to_table(view_name).as_(tbl_alias))

        # Update WHERE in root AST
        root_where = root_ast.find(exp.Where)
        if mixed_predicates:
            combined_mixed = exp.and_(*mixed_predicates)
            if root_where:
                root_where.set("this", combined_mixed)
            else:
                root_ast.set("where", exp.Where(this=combined_mixed))
        elif root_where:
            root_where.pop()

        return subqueries, root_ast

    @classmethod
    def compile_to_sql(cls, parsed: ParsedQuery) -> tuple[dict[str, SubqueryPlan], str]:
        """Compile query returning subqueries and the rewritten DuckDB root SQL string."""
        subqueries, root_ast = cls.compile(parsed)
        return subqueries, root_ast.sql(dialect="duckdb")

    @classmethod
    def compile_single_source_sql(cls, parsed: ParsedQuery) -> str:
        """Compile a single-source query directly to the native datasource dialect."""
        if not parsed.tables:
            raise ValueError("Parsed query has no tables.")

        ref = parsed.tables[0]
        ast_copy = parsed.ast.copy()
        cte_names = {cte.alias_or_name.lower() for cte in ast_copy.find_all(exp.CTE)}

        # Strip catalog name from tables so dialect executes cleanly against local schema
        for tbl in ast_copy.find_all(exp.Table):
            if tbl.name.lower() in cte_names:
                continue
            tbl.set("catalog", None)
            if tbl.db and tbl.db.lower() == "default":
                tbl.set("db", None)

        return ast_copy.sql(dialect=ref.dialect)
