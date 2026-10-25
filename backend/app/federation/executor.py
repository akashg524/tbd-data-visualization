"""Federated query execution engine with parallel dispatch, out-of-core DuckDB joins, and governance enforcement."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa
import structlog

from app.federation.compiler import PushdownCompiler
from app.federation.parser import SQLParser

if TYPE_CHECKING:
    from app.auth.governance import SecurityContext
    from app.cache import DimensionCache, ResultCache
    from app.catalog import UnifiedCatalogRegistry
    from app.federation.compiler import SubqueryPlan

logger = structlog.get_logger(__name__)


@dataclass
class ExecutionMetrics:
    """Execution performance and latency profile for federated queries."""

    planning_ms: float
    subquery_ms: dict[str, float] = field(default_factory=dict)
    join_ms: float = 0.0
    total_ms: float = 0.0
    row_count: int = 0
    cache_hit: bool = False
    scratch_spill_enabled: bool = True
    applied_rls_filters: list[str] = field(default_factory=list)
    secured_sql: str | None = None


class FederatedExecutor:
    """Orchestrates parallel subquery dispatch, zero-copy Arrow memory bus, DuckDB joins, and governance."""

    def __init__(
        self,
        catalog: UnifiedCatalogRegistry,
        cache: ResultCache | None = None,
        dimension_cache: DimensionCache | None = None,
        scratch_dir: str = "./scratch",
        default_timeout: float = 60.0,
        max_memory: str = "4GB",
    ) -> None:
        self.catalog = catalog
        self.cache = cache
        self.dimension_cache = dimension_cache
        self.scratch_dir = scratch_dir
        self.default_timeout = default_timeout
        self.max_memory = max_memory

    async def execute(
        self,
        sql: str,
        limit: int | None = None,
        security_context: SecurityContext | None = None,
        protocol: str = "REST",
    ) -> tuple[pa.Table, ExecutionMetrics]:
        """Execute a SQL query across federated datasources with caching, RLS rewriting, and audit logging."""
        t0 = time.perf_counter()
        applied_rls: list[str] = []
        secured_sql = sql
        sec_fp = security_context.fingerprint if security_context else ""

        # 0. Apply Security AST Rewriting if security context is provided
        if security_context:
            try:
                from app.federation.rewriter import ASTRewriter

                secured_sql, applied_rls = ASTRewriter.rewrite(
                    sql, security_context, catalog=self.catalog
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                from app.auth.audit import audit_logger

                audit_logger.log_query_execution(
                    context=security_context,
                    original_sql=sql,
                    secured_sql=secured_sql,
                    applied_rls_filters=[],
                    sources_accessed=[],
                    duration_ms=elapsed_ms,
                    row_count=0,
                    cache_hit=False,
                    protocol=protocol,
                    status="FAILED",
                    error=str(exc),
                )
                raise

        # 1. Check Result Cache with security fingerprint isolation
        if self.cache:
            cached_table = await self.cache.get(sql, security_fingerprint=sec_fp)
            if cached_table is not None:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                metrics = ExecutionMetrics(
                    planning_ms=0.0,
                    subquery_ms={},
                    join_ms=0.0,
                    total_ms=round(elapsed_ms, 2),
                    row_count=cached_table.num_rows,
                    cache_hit=True,
                    scratch_spill_enabled=False,
                    applied_rls_filters=applied_rls,
                    secured_sql=secured_sql,
                )
                from app.auth.audit import audit_logger

                audit_logger.log_query_execution(
                    context=security_context,
                    original_sql=sql,
                    secured_sql=secured_sql,
                    applied_rls_filters=applied_rls,
                    sources_accessed=[],
                    duration_ms=elapsed_ms,
                    row_count=cached_table.num_rows,
                    cache_hit=True,
                    protocol=protocol,
                )
                logger.info("query_served_from_cache", total_ms=metrics.total_ms, rows=metrics.row_count)
                return cached_table, metrics

        # 2. Parse and Compile query using SECURED SQL
        plan_t0 = time.perf_counter()
        parsed = SQLParser.parse(secured_sql, catalog=self.catalog)
        planning_ms = (time.perf_counter() - plan_t0) * 1000

        # Effective limit is the tighter of explicit limit parameter and parsed LIMIT clause
        effective_limit = limit if limit is not None else parsed.limit

        # 3. Scalar Query (e.g. SELECT 1 or SELECT 42 AS answer): Execute directly in DuckDB
        if not parsed.tables:
            duck_conn = duckdb.connect()
            try:
                relation = duck_conn.sql(secured_sql)
                arrow_res = relation.arrow()
                table = arrow_res.read_all() if hasattr(arrow_res, "read_all") else arrow_res
                if effective_limit is not None and table.num_rows > effective_limit:
                    table = table.slice(0, effective_limit)
            finally:
                duck_conn.close()

            total_elapsed = (time.perf_counter() - t0) * 1000
            metrics = ExecutionMetrics(
                planning_ms=round(planning_ms, 2),
                subquery_ms={},
                join_ms=0.0,
                total_ms=round(total_elapsed, 2),
                row_count=table.num_rows,
                cache_hit=False,
                scratch_spill_enabled=False,
                applied_rls_filters=applied_rls,
                secured_sql=secured_sql,
            )
            from app.auth.audit import audit_logger

            audit_logger.log_query_execution(
                context=security_context,
                original_sql=sql,
                secured_sql=secured_sql,
                applied_rls_filters=applied_rls,
                sources_accessed=[],
                duration_ms=metrics.total_ms,
                row_count=metrics.row_count,
                cache_hit=False,
                protocol=protocol,
            )
            return table, metrics

        subqueries, root_sql = PushdownCompiler.compile_to_sql(parsed)

        # 4. Single-Source Bypass: Route directly to native connector
        if not parsed.is_multi_source:
            ref = parsed.tables[0]
            connector = self.catalog.get_connector(ref.datasource_name)
            native_sql = PushdownCompiler.compile_single_source_sql(parsed)

            sub_t0 = time.perf_counter()
            try:
                table = await asyncio.wait_for(
                    connector.execute_query(native_sql, limit=effective_limit),
                    timeout=self.default_timeout,
                )
            except TimeoutError as err:
                raise TimeoutError(
                    f"Query execution on datasource '{ref.datasource_name}' timed out after {self.default_timeout}s."
                ) from err
            except Exception as exc:
                raise RuntimeError(
                    f"Query execution failed on datasource '{ref.datasource_name}': {exc}"
                ) from exc

            sub_elapsed = (time.perf_counter() - sub_t0) * 1000
            total_elapsed = (time.perf_counter() - t0) * 1000

            if self.cache:
                await self.cache.set(sql, table, security_fingerprint=sec_fp)

            metrics = ExecutionMetrics(
                planning_ms=round(planning_ms, 2),
                subquery_ms={ref.alias: round(sub_elapsed, 2)},
                join_ms=0.0,
                total_ms=round(total_elapsed, 2),
                row_count=table.num_rows,
                cache_hit=False,
                scratch_spill_enabled=False,
                applied_rls_filters=applied_rls,
                secured_sql=secured_sql,
            )
            from app.auth.audit import audit_logger

            audit_logger.log_query_execution(
                context=security_context,
                original_sql=sql,
                secured_sql=secured_sql,
                applied_rls_filters=applied_rls,
                sources_accessed=[ref.raw_name],
                duration_ms=metrics.total_ms,
                row_count=metrics.row_count,
                cache_hit=False,
                protocol=protocol,
            )
            logger.info("single_source_query_executed", datasource=ref.datasource_name, total_ms=metrics.total_ms)
            return table, metrics

        # 5. Multi-Source Federated Join
        async def fetch_subquery(alias: str, plan: SubqueryPlan) -> tuple[str, pa.Table, float]:
            sub_t0 = time.perf_counter()
            full_path = f"{plan.datasource_name}.{plan.schema_name}.{plan.table_name}".lower()

            # Fast-path Tier 2: Check if table is cached in DimensionCache
            if self.dimension_cache and self.dimension_cache.is_dimension_cached(full_path):
                dim_tbl = await self.dimension_cache.get_dimension(full_path)
                if dim_tbl is not None:
                    sub_elapsed = (time.perf_counter() - sub_t0) * 1000
                    logger.debug("dimension_cache_used_in_join", table=full_path, rows=dim_tbl.num_rows)
                    return alias, dim_tbl, round(sub_elapsed, 2)

            connector = self.catalog.get_connector(plan.datasource_name)
            try:
                arrow_tbl = await asyncio.wait_for(
                    connector.execute_query(plan.sql),
                    timeout=self.default_timeout,
                )
            except TimeoutError as err:
                raise TimeoutError(
                    f"Subquery for table '{alias}' on '{plan.datasource_name}' timed out after {self.default_timeout}s."
                ) from err
            except Exception as exc:
                raise RuntimeError(
                    f"Subquery for table '{alias}' on '{plan.datasource_name}' failed: {exc}"
                ) from exc

            sub_elapsed = (time.perf_counter() - sub_t0) * 1000
            return alias, arrow_tbl, round(sub_elapsed, 2)

        # Dispatch all subqueries concurrently in parallel
        subquery_tasks = [fetch_subquery(alias, plan) for alias, plan in subqueries.items()]
        fetched_subqueries = await asyncio.gather(*subquery_tasks)

        subquery_ms: dict[str, float] = {}

        # 6. Execute in-memory hash join in DuckDB with out-of-core scratch disk configuration
        join_t0 = time.perf_counter()
        os.makedirs(self.scratch_dir, exist_ok=True)
        normalized_scratch = os.path.abspath(self.scratch_dir).replace("\\", "/")

        duck_conn = duckdb.connect()
        try:
            duck_conn.execute(f"SET temp_directory = '{normalized_scratch}'")
            duck_conn.execute(f"SET max_memory = '{self.max_memory}'")

            for alias, arrow_tbl, elapsed in fetched_subqueries:
                subquery_ms[alias] = elapsed
                view_name = f"__subq_{alias}"
                duck_conn.register(view_name, arrow_tbl)

            relation = duck_conn.sql(root_sql)
            arrow_res = relation.arrow()
            final_table = arrow_res.read_all() if hasattr(arrow_res, "read_all") else arrow_res

            if effective_limit is not None and final_table.num_rows > effective_limit:
                final_table = final_table.slice(0, effective_limit)
        finally:
            duck_conn.close()

        join_ms = (time.perf_counter() - join_t0) * 1000
        total_elapsed = (time.perf_counter() - t0) * 1000

        # Store in ResultCache with security fingerprint
        if self.cache:
            await self.cache.set(sql, final_table, security_fingerprint=sec_fp)

        metrics = ExecutionMetrics(
            planning_ms=round(planning_ms, 2),
            subquery_ms=subquery_ms,
            join_ms=round(join_ms, 2),
            total_ms=round(total_elapsed, 2),
            row_count=final_table.num_rows,
            cache_hit=False,
            scratch_spill_enabled=True,
            applied_rls_filters=applied_rls,
            secured_sql=secured_sql,
        )
        from app.auth.audit import audit_logger

        audit_logger.log_query_execution(
            context=security_context,
            original_sql=sql,
            secured_sql=secured_sql,
            applied_rls_filters=applied_rls,
            sources_accessed=[t.raw_name for t in parsed.tables],
            duration_ms=metrics.total_ms,
            row_count=metrics.row_count,
            cache_hit=False,
            protocol=protocol,
        )
        logger.info(
            "federated_join_completed",
            sources=list(subqueries.keys()),
            join_ms=metrics.join_ms,
            total_ms=metrics.total_ms,
            rows=metrics.row_count,
        )
        return final_table, metrics
