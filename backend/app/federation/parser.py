"""SQL AST parser and query decomposer using sqlglot."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlglot
import structlog
from sqlglot import exp
from sqlglot.errors import ParseError

if TYPE_CHECKING:
    from app.catalog import UnifiedCatalogRegistry
    from app.connectors.base import BaseConnector

logger = structlog.get_logger(__name__)

# Maximum SQL string length to prevent DoS attacks (T-02-02)
MAX_SQL_LENGTH = 50_000
# Maximum AST nodes to prevent deeply nested recursive expressions (T-02-02)
MAX_AST_NODES = 2_000


def map_datasource_type_to_dialect(datasource_type: str) -> str:
    """Map datasource type string to sqlglot dialect name."""
    ds = datasource_type.lower()
    if "oracle" in ds:
        return "oracle"
    if "sqlserver" in ds or "mssql" in ds or "azure_sql" in ds:
        return "tsql"
    if "postgres" in ds:
        return "postgres"
    if "cosmos" in ds:
        return "duckdb"
    return "duckdb"


@dataclass
class TableReference:
    """Metadata representing a referenced table in a query."""

    raw_name: str
    datasource_name: str
    schema_name: str
    table_name: str
    alias: str
    connector: BaseConnector | None = None
    dialect: str = "duckdb"


@dataclass
class ParsedQuery:
    """Decomposed query metadata extracted from SQLglot AST."""

    raw_sql: str
    ast: exp.Expression
    tables: list[TableReference] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)  # alias -> raw_name
    table_refs: dict[str, TableReference] = field(default_factory=dict)  # alias -> TableReference
    is_multi_source: bool = False
    columns_by_alias: dict[str, set[str]] = field(default_factory=dict)
    limit: int | None = None


class SQLParser:
    """SQL parser for federated queries with security, catalog resolution, and alias decomposition."""

    @staticmethod
    def parse(sql: str, catalog: UnifiedCatalogRegistry | None = None) -> ParsedQuery:
        """Parse SQL, resolve table references, extract column projections, and classify execution mode."""
        if not sql or not sql.strip():
            raise ValueError("Query string cannot be empty.")

        if len(sql) > MAX_SQL_LENGTH:
            raise ValueError(f"Query length ({len(sql)}) exceeds maximum allowed limit of {MAX_SQL_LENGTH} characters.")

        try:
            ast = sqlglot.parse_one(sql)
        except ParseError as exc:
            raise ValueError(f"SQL parsing error: {exc}") from exc

        # Security check: T-02-01 Enforce 100% Read-Only queries
        disallowed_types = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Drop,
            exp.Alter,
            exp.Create,
            exp.Merge,
        )
        if isinstance(ast, disallowed_types) or any(ast.find_all(disallowed_types)):
            raise ValueError("Only read-only SELECT queries are allowed.")

        # Security check: T-02-02 AST complexity limit
        node_count = sum(1 for _ in ast.walk())
        if node_count > MAX_AST_NODES:
            raise ValueError(f"Query complexity exceeds maximum limit ({node_count} nodes > {MAX_AST_NODES}).")

        # Discover CTEs and their aliases
        cte_names = {cte.alias_or_name.lower() for cte in ast.find_all(exp.CTE)}
        cte_aliases = set(cte_names)
        for tbl in ast.find_all(exp.Table):
            if tbl.name.lower() in cte_names:
                alias = tbl.alias if tbl.alias else tbl.alias_or_name
                if alias:
                    cte_aliases.add(alias.lower())

        # Extract limit
        limit: int | None = None
        limit_node = ast.find(exp.Limit)
        if limit_node and limit_node.expression:
            with contextlib.suppress(ValueError, TypeError, AttributeError):
                limit = int(limit_node.expression.this)
        else:
            fetch_node = ast.find(exp.Fetch)
            if fetch_node:
                target = fetch_node.expression or fetch_node.this
                if target:
                    with contextlib.suppress(ValueError, TypeError):
                        limit = int(str(target))

        # Extract table references
        table_nodes = list(ast.find_all(exp.Table))
        tables: list[TableReference] = []
        aliases: dict[str, str] = {}
        table_refs: dict[str, TableReference] = {}
        datasources_seen: set[str] = set()

        for tbl in table_nodes:
            tbl_name = tbl.name
            if tbl_name.lower() in cte_names:
                continue

            # Determine alias (defaults to table name if not explicitly aliased)
            alias = tbl.alias if tbl.alias else tbl.alias_or_name
            if not alias:
                alias = tbl_name

            # Resolve catalog, schema, table
            cat_name = tbl.catalog
            db_name = tbl.db

            if cat_name and db_name and tbl_name:
                raw_name = f"{cat_name}.{db_name}.{tbl_name}"
                ds_name = cat_name
                schema_name = db_name
                table_name = tbl_name
            elif db_name and tbl_name:
                # 2-part name (schema.table)
                if catalog and len(catalog.list_datasources()) == 1:
                    ds_name = catalog.list_datasources()[0]
                    schema_name = db_name
                    table_name = tbl_name
                    raw_name = f"{ds_name}.{schema_name}.{table_name}"
                else:
                    raise ValueError(
                        f"Ambiguous 2-part table identifier '{db_name}.{tbl_name}'. "
                        "Expected 3-part identifier 'datasource.schema.table'."
                    )
            elif tbl_name:
                # 1-part name
                if catalog and len(catalog.list_datasources()) == 1:
                    ds_name = catalog.list_datasources()[0]
                    schema_name = "default"
                    table_name = tbl_name
                    raw_name = f"{ds_name}.{schema_name}.{table_name}"
                else:
                    raise ValueError(
                        f"Unqualified table identifier '{tbl_name}'. "
                        "Expected 3-part identifier 'datasource.schema.table'."
                    )
            else:
                continue

            # Resolve connector and dialect if catalog provided
            connector: BaseConnector | None = None
            dialect = "duckdb"
            if catalog:
                try:
                    connector = catalog.get_connector(ds_name)
                    dialect = getattr(connector, "dialect", None) or map_datasource_type_to_dialect(
                        connector.config.datasource_type
                    )
                except KeyError as err:
                    raise ValueError(
                        f"Datasource '{ds_name}' referenced in table '{raw_name}' is not registered in catalog."
                    ) from err

            ref = TableReference(
                raw_name=raw_name,
                datasource_name=ds_name,
                schema_name=schema_name,
                table_name=table_name,
                alias=alias,
                connector=connector,
                dialect=dialect,
            )
            tables.append(ref)
            aliases[alias] = raw_name
            table_refs[alias] = ref
            datasources_seen.add(ds_name)

        # If no tables are referenced (e.g. SELECT 1 or SELECT 'hello'), treat as scalar query
        if not tables:
            return ParsedQuery(
                raw_sql=sql,
                ast=ast,
                tables=[],
                aliases={},
                table_refs={},
                is_multi_source=False,
                columns_by_alias={},
                limit=limit,
            )

        is_multi_source = len(datasources_seen) > 1

        # Extract columns referenced per alias
        columns_by_alias: dict[str, set[str]] = {ref.alias: set() for ref in tables}

        # Check for stars (SELECT * or SELECT t.*)
        for star in ast.find_all(exp.Star):
            parent = star.parent
            if isinstance(parent, exp.Column) and parent.table:
                # Qualified star (e.g. t.*)
                if parent.table in columns_by_alias:
                    columns_by_alias[parent.table].add("*")
            else:
                # Unqualified star (*) -> all tables project *
                for a in columns_by_alias:
                    columns_by_alias[a].add("*")

        # Check for column references
        for col in ast.find_all(exp.Column):
            col_name = col.name
            if not col_name or col_name == "*":
                continue

            if col.table:
                tbl_key = col.table.lower()
                if tbl_key in cte_aliases:
                    # Column references a CTE view; will be resolved within DuckDB
                    continue
                # Explicitly qualified with table or alias (e.g. t.trade_id)
                if col.table in columns_by_alias:
                    columns_by_alias[col.table].add(col_name)
                else:
                    # Check if col.table matches a raw table name
                    matched = False
                    for ref in tables:
                        if col.table.lower() == ref.table_name.lower():
                            columns_by_alias[ref.alias].add(col_name)
                            matched = True
                            break
                    if not matched:
                        logger.warning("unknown_column_table_qualifier", table=col.table, column=col_name)
            else:
                # Unqualified column: determine scope from enclosing Select statement
                sel = col.find_ancestor(exp.Select)
                scope_tables = (
                    [
                        t
                        for t in sel.find_all(exp.Table)
                        if t.find_ancestor(exp.Select) == sel and t.name.lower() not in cte_aliases
                    ]
                    if sel
                    else []
                )

                if len(scope_tables) == 1:
                    scope_tbl = scope_tables[0]
                    tbl_alias = scope_tbl.alias if scope_tbl.alias else scope_tbl.alias_or_name
                    if not tbl_alias:
                        tbl_alias = scope_tbl.name
                    if tbl_alias in columns_by_alias:
                        columns_by_alias[tbl_alias].add(col_name)
                    else:
                        for ref in tables:
                            if scope_tbl.name.lower() == ref.table_name.lower():
                                columns_by_alias[ref.alias].add(col_name)
                                break
                elif len(tables) == 1:
                    # Single table in query -> attribute to it
                    columns_by_alias[tables[0].alias].add(col_name)
                else:
                    # Multiple tables: try to resolve via catalog cached schema if possible
                    attributed = False
                    if catalog:
                        candidate_aliases = []
                        for ref in tables:
                            schema = catalog._table_cache.get(ref.raw_name)
                            if schema and any(c.name.lower() == col_name.lower() for c in schema.columns):
                                candidate_aliases.append(ref.alias)
                        if len(candidate_aliases) == 1:
                            columns_by_alias[candidate_aliases[0]].add(col_name)
                            attributed = True
                        elif len(candidate_aliases) > 1:
                            raise ValueError(
                                f"Ambiguous column '{col_name}' exists in multiple tables: "
                                f"{candidate_aliases}. Please qualify with table alias."
                            )

                    if not attributed:
                        raise ValueError(
                            f"Unqualified column '{col_name}' in multi-table query. "
                            "Please qualify with table alias (e.g. alias.column_name)."
                        )

        return ParsedQuery(
            raw_sql=sql,
            ast=ast,
            tables=tables,
            aliases=aliases,
            table_refs=table_refs,
            is_multi_source=is_multi_source,
            columns_by_alias=columns_by_alias,
            limit=limit,
        )
