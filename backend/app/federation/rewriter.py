"""SQL AST security rewriter enforcing Gate 1 RBAC and Gate 2 dynamic RLS predicate injection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlglot
import structlog
from sqlglot import exp

from app.auth.governance import (
    GateType,
    GovernancePolicyRegistry,
    PolicyStrategy,
    SecurityContext,
)
from app.auth.governance import (
    governance_registry as default_registry,
)

if TYPE_CHECKING:
    from app.catalog import UnifiedCatalogRegistry

logger = structlog.get_logger(__name__)


class ASTRewriter:
    """Interprets and rewrites SQLGlot ASTs to enforce two-gate enterprise security policies."""

    @classmethod
    def rewrite(
        cls,
        sql: str,
        context: SecurityContext,
        catalog: UnifiedCatalogRegistry | None = None,
        registry: GovernancePolicyRegistry | None = None,
    ) -> tuple[str, list[str]]:
        """Rewrite SQL query to enforce Gate 1 RBAC and inject Gate 2 RLS predicates.

        Returns:
            tuple[str, list[str]]: (secured_sql, applied_rls_filters)
        """
        policy_registry = registry or default_registry
        applied_rules: list[str] = []

        try:
            ast = sqlglot.parse_one(sql)
        except Exception as exc:
            logger.warning("ast_parse_failure_in_rewriter", error=str(exc))
            return sql, []

        # Scalar queries (e.g. SELECT 1 or SELECT 42 AS answer) have no tables to govern
        tables = list(ast.find_all(exp.Table))
        if not tables:
            return sql, []

        # Privileged compliance / security admin bypass
        if context.is_exempt({"ComplianceAdmin", "SecurityAdmin"}):
            logger.info("governance_bypass_for_privileged_role", user=context.user_id, roles=context.roles)
            return sql, []

        # Extract CTE names so we don't treat CTE aliases as physical tables
        cte_names = {c.alias.lower() for c in ast.find_all(exp.CTE) if c.alias}

        for table_node in tables:
            raw_table_name = table_node.name.lower()
            if raw_table_name in cte_names:
                continue

            # Build full table path (catalog.schema.table or schema.table or table)
            parts: list[str] = []
            if table_node.catalog:
                parts.append(table_node.catalog)
            if table_node.db:
                parts.append(table_node.db)
            parts.append(table_node.name)
            table_path = ".".join(parts)

            policy = policy_registry.get_policy_for_table(table_path)
            if policy is None:
                continue

            # --- Gate 1: Coarse-Grained Table RBAC Validation ---
            if not context.is_exempt(policy.exempt_roles) and not context.has_any_role(policy.required_roles):
                logger.warning(
                    "gate1_rbac_denial",
                    user=context.user_id,
                    table=table_path,
                    required_roles=policy.required_roles,
                )
                raise PermissionError(
                    f"Access denied: Table '{table_path}' requires one of roles: {policy.required_roles}"
                )

            # If Gate 1 is RBAC_ONLY, no row-level predicates to synthesize
            if policy.gate == GateType.RBAC_ONLY:
                continue

            # --- Gate 2: Fine-Grained ACL / RLS Synthesis ---
            select_node = table_node.find_ancestor(exp.Select)
            if select_node is None:
                continue

            table_qualifier = table_node.alias or table_node.name

            # Check if user has any claims matching this policy's ACL rules
            has_any_claim = any(
                bool(context.get_effective_claims(r.claim_field)) for r in policy.acl_rules
            )

            if not has_any_claim:
                if policy.fail_closed:
                    fail_pred = exp.Literal.number(1).eq(exp.Literal.number(0))
                    select_node.where(fail_pred, copy=False)
                    applied_rules.append(f"{table_qualifier} -> FAIL_CLOSED (1 = 0)")
                continue

            for rule in policy.acl_rules:
                raw_values = context.get_effective_claims(rule.claim_field)
                if not raw_values:
                    continue

                effective_values: list[Any] = []
                if rule.strategy == PolicyStrategy.TRANSLATION:
                    if rule.lookup_map:
                        effective_values = [
                            rule.lookup_map[v] for v in raw_values if v in rule.lookup_map
                        ]
                    if not effective_values and policy.fail_closed:
                        fail_pred = exp.Literal.number(1).eq(exp.Literal.number(0))
                        select_node.where(fail_pred, copy=False)
                        applied_rules.append(f"{table_qualifier}.{rule.target_column} -> TRANSLATION_EMPTY (1 = 0)")
                        continue
                else:
                    # DIRECT strategy
                    effective_values = raw_values

                col_expr = exp.column(rule.target_column, table=table_qualifier)

                if len(effective_values) == 1:
                    val = effective_values[0]
                    val_lit = (
                        exp.Literal.number(val)
                        if isinstance(val, (int, float))
                        else exp.Literal.string(str(val))
                    )
                    pred = col_expr.eq(val_lit)
                else:
                    val_lits = [
                        exp.Literal.number(v)
                        if isinstance(v, (int, float))
                        else exp.Literal.string(str(v))
                        for v in effective_values
                    ]
                    pred = col_expr.isin(*val_lits)

                select_node.where(pred, copy=False)
                rule_desc = f"{table_qualifier}.{rule.target_column} IN {effective_values}"
                applied_rules.append(rule_desc)

        secured_sql = ast.sql()
        return secured_sql, applied_rules
