"""Tests for SQLGlot AST Security Rewriter (Gate 1 RBAC and Gate 2 Dynamic RLS)."""

from __future__ import annotations

import pytest

from app.auth import SecurityContext
from app.federation.rewriter import ASTRewriter


def test_scalar_query_passthrough():
    """Verify scalar queries without tables pass through untouched."""
    ctx = SecurityContext(user_id="trader1", roles=["Trader"], trading_desks=["FX"])
    sql = "SELECT 1 AS num, 'hello' AS greeting"
    rewritten_sql, applied_rules = ASTRewriter.rewrite(sql, ctx)
    assert rewritten_sql == sql
    assert applied_rules == []


def test_gate1_rbac_denial():
    """Verify Gate 1 blocks unauthorized table access with PermissionError."""
    # User lacks MNA_Auditor role
    trader_ctx = SecurityContext(user_id="trader1", roles=["Trader"], trading_desks=["FX"])
    sql = "SELECT * FROM adls_lake.corporate.mna_deals"

    with pytest.raises(PermissionError) as exc_info:
        ASTRewriter.rewrite(sql, trader_ctx)
    assert "Access denied" in str(exc_info.value)
    assert "MNA_Auditor" in str(exc_info.value)


def test_gate1_rbac_permitted():
    """Verify Gate 1 permits authorized user to query RBAC-gated table."""
    auditor_ctx = SecurityContext(user_id="auditor1", roles=["MNA_Auditor"])
    sql = "SELECT * FROM adls_lake.corporate.mna_deals"
    rewritten_sql, applied_rules = ASTRewriter.rewrite(sql, auditor_ctx)
    assert "mna_deals" in rewritten_sql
    assert applied_rules == []  # RBAC_ONLY table has no row-level predicates


def test_single_table_direct_rls_injection():
    """Verify single table RLS injection with direct desk matching."""
    ctx = SecurityContext(
        user_id="trader1",
        roles=["Trader"],
        trading_desks=["FX"],
    )
    sql = "SELECT trade_id, amount FROM trades"
    rewritten_sql, applied_rules = ASTRewriter.rewrite(sql, ctx)
    assert "trades.desk_code = 'FX'" in rewritten_sql
    assert any("desk_code" in r for r in applied_rules)


def test_translation_strategy_rls_injection():
    """Verify text region names ('US', 'EMEA') translate into integer IDs (1, 2)."""
    ctx = SecurityContext(
        user_id="trader1",
        roles=["Trader"],
        regions=["US", "EMEA"],
    )
    sql = "SELECT trade_id, amount FROM trades"
    rewritten_sql, _ = ASTRewriter.rewrite(sql, ctx)
    assert "region_id IN (1, 2)" in rewritten_sql


def test_composite_acl_injection():
    """Verify both desk and translated region predicates combine in WHERE clause."""
    ctx = SecurityContext(
        user_id="trader1",
        roles=["Trader"],
        trading_desks=["FX"],
        regions=["US"],
        allowed_accounts=["ACC-101", "ACC-102"],
    )
    sql = "SELECT trade_id, amount FROM trades"
    rewritten_sql, _ = ASTRewriter.rewrite(sql, ctx)
    assert "trades.desk_code = 'FX'" in rewritten_sql
    assert "trades.region_id = 1" in rewritten_sql or "trades.region_id IN (1)" in rewritten_sql
    assert "trades.account_no IN ('ACC-101', 'ACC-102')" in rewritten_sql


def test_table_alias_qualification_in_joins():
    """Verify table aliases qualify injected predicates in multi-table joins."""
    ctx = SecurityContext(
        user_id="trader1",
        roles=["Trader", "FinancialAnalyst"],
        trading_desks=["FX"],
        regions=["EMEA"],
    )
    sql = "SELECT t.trade_id, c.name FROM trades t JOIN counterparties c ON t.cid = c.id"
    rewritten_sql, _ = ASTRewriter.rewrite(sql, ctx)
    # trades has alias 't'
    assert "t.desk_code = 'FX'" in rewritten_sql
    # counterparties has alias 'c' and region translated (EMEA -> 2)
    assert "c.region_id = 2" in rewritten_sql or "c.region_id IN (2)" in rewritten_sql


def test_existing_where_clause_combination():
    """Verify RLS predicates combine with existing user WHERE clauses using AND."""
    ctx = SecurityContext(
        user_id="trader1",
        roles=["Trader"],
        trading_desks=["FX"],
    )
    sql = "SELECT * FROM trades WHERE amount > 50000"
    rewritten_sql, _ = ASTRewriter.rewrite(sql, ctx)
    assert "amount > 50000" in rewritten_sql
    assert "trades.desk_code = 'FX'" in rewritten_sql
    assert "AND" in rewritten_sql


def test_cte_subquery_injection():
    """Verify RLS predicates inject into inner CTE table definition."""
    ctx = SecurityContext(
        user_id="trader1",
        roles=["Trader"],
        trading_desks=["EQUITY"],
    )
    sql = "WITH cte_trades AS (SELECT * FROM trades) SELECT * FROM cte_trades"
    rewritten_sql, _ = ASTRewriter.rewrite(sql, ctx)
    # Predicate must be inside the CTE definition
    assert "WITH cte_trades AS (SELECT * FROM trades WHERE trades.desk_code = 'EQUITY')" in rewritten_sql


def test_union_query_branches():
    """Verify RLS predicates inject into all branches of a UNION query."""
    ctx = SecurityContext(
        user_id="trader1",
        roles=["Trader"],
        trading_desks=["FX"],
    )
    sql = "SELECT trade_id FROM trades UNION ALL SELECT trade_id FROM trades"
    rewritten_sql, _ = ASTRewriter.rewrite(sql, ctx)
    # Both select blocks must contain the desk filter
    assert rewritten_sql.count("desk_code = 'FX'") == 2


def test_fail_closed_empty_claims():
    """Verify fail-closed rule: user with no desk/region claims gets 1 = 0 (zero rows)."""
    ctx = SecurityContext(
        user_id="unassigned_user",
        roles=["Trader"],
        trading_desks=[],  # Empty desks!
        regions=[],
    )
    sql = "SELECT * FROM trades"
    rewritten_sql, applied_rules = ASTRewriter.rewrite(sql, ctx)
    assert "1 = 0" in rewritten_sql
    assert any("FAIL_CLOSED" in r for r in applied_rules)


def test_compliance_admin_exemption():
    """Verify ComplianceAdmin and SecurityAdmin bypass all RLS rewriting."""
    compliance_ctx = SecurityContext(
        user_id="compliance_officer",
        roles=["ComplianceAdmin"],
        trading_desks=[],
    )
    sql = "SELECT * FROM trades WHERE amount > 100"
    rewritten_sql, applied_rules = ASTRewriter.rewrite(sql, compliance_ctx)
    assert rewritten_sql == sql
    assert applied_rules == []
