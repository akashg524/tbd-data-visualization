"""Tests for SecurityContext, Two-Gate Governance Policy Registry, and Entra ID Claim Mapping."""

from __future__ import annotations

import pytest

from app.auth import (
    AclRule,
    GateType,
    GovernancePolicyRegistry,
    PolicyStrategy,
    Role,
    SecurityContext,
    TableSecurityPolicy,
    get_security_context,
)


def test_security_context_normalization():
    """Verify SecurityContext handles empty, single string, or list claims."""
    ctx = SecurityContext(
        user_id="trader123",
        username="trader@enterprise.com",
        roles=["FinancialAnalyst"],
        groups=["TradersGroup"],
        trading_desks=["FX", "EQUITY"],
        regions=["US", "EMEA"],
        allowed_accounts=["ACC-101"],
    )
    assert ctx.user_id == "trader123"
    assert "FX" in ctx.trading_desks
    assert ctx.clearance_level == "STANDARD"


def test_security_context_fingerprint():
    """Verify distinct security attributes yield different fingerprints;
    identical attributes yield identical fingerprints.
    """
    ctx1 = SecurityContext(
        user_id="user1",
        roles=["FinancialAnalyst"],
        trading_desks=["FX"],
        regions=["US"],
    )
    ctx2 = SecurityContext(
        user_id="user2",  # Different user ID, but identical governance attributes
        roles=["FinancialAnalyst"],
        trading_desks=["FX"],
        regions=["US"],
    )
    ctx3 = SecurityContext(
        user_id="user1",
        roles=["FinancialAnalyst"],
        trading_desks=["EQUITY"],  # Different desk
        regions=["US"],
    )
    ctx4 = SecurityContext(
        user_id="user1",
        roles=["FinancialAnalyst"],
        trading_desks=["FX"],
        regions=["EMEA"],  # Different region
    )

    # Identical security scope must produce identical fingerprint for cache sharing within same desk
    assert ctx1.fingerprint == ctx2.fingerprint
    # Different desk must produce different fingerprint to prevent cross-tenant cache leaks
    assert ctx1.fingerprint != ctx3.fingerprint
    # Different region must produce different fingerprint
    assert ctx1.fingerprint != ctx4.fingerprint


def test_gate1_rbac_validation():
    """Verify Gate 1: Pure RBAC access control on restricted tables."""
    registry = GovernancePolicyRegistry()

    # User with MNA_Auditor role
    mna_auditor = SecurityContext(
        user_id="auditor1",
        roles=["MNA_Auditor"],
    )
    # Standard trader without MNA role
    trader = SecurityContext(
        user_id="trader1",
        roles=["Trader"],
    )
    # ComplianceAdmin has universal exemption
    compliance_admin = SecurityContext(
        user_id="admin1",
        roles=["ComplianceAdmin"],
    )

    # Table *.mna_deals requires MNA_Auditor or SecurityAdmin
    table = "adls_lake.corporate.mna_deals"
    assert registry.validate_rbac_gate(table, mna_auditor) is True
    assert registry.validate_rbac_gate(table, trader) is False
    assert registry.validate_rbac_gate(table, compliance_admin) is True

    # Non-governed tables allow standard access
    assert registry.validate_rbac_gate("adls_lake.public.currencies", trader) is True


def test_gate2_acl_policy_resolution():
    """Verify Gate 2: Table policy resolution, wildcard pattern matching, and rule lookup."""
    registry = GovernancePolicyRegistry()

    # Pattern *.trades should match various namespaces
    policy = registry.get_policy_for_table("adls_lake.equity.trades")
    assert policy is not None
    assert policy.gate == GateType.RBAC_AND_ACL
    assert "Trader" in policy.required_roles
    assert len(policy.acl_rules) == 3

    # Check ACL rule definitions
    desk_rule = next(r for r in policy.acl_rules if r.claim_field == "trading_desks")
    assert desk_rule.target_column == "desk_code"
    assert desk_rule.strategy == PolicyStrategy.DIRECT

    region_rule = next(r for r in policy.acl_rules if r.claim_field == "regions")
    assert region_rule.target_column == "region_id"
    assert region_rule.strategy == PolicyStrategy.TRANSLATION
    assert region_rule.lookup_map == {"US": 1, "EMEA": 2, "APAC": 3, "LATAM": 4}


def test_custom_policy_registration():
    """Verify custom policies can be registered and take precedence."""
    registry = GovernancePolicyRegistry()

    custom_policy = TableSecurityPolicy(
        table_pattern="oracle.treasury.bonds",
        gate=GateType.RBAC_AND_ACL,
        required_roles=["BondTrader"],
        acl_rules=[
            AclRule(
                claim_field="trading_desks",
                target_column="desk_name",
                strategy=PolicyStrategy.DIRECT,
            )
        ],
    )
    registry.register_policy(custom_policy)

    resolved = registry.get_policy_for_table("oracle.treasury.bonds")
    assert resolved is not None
    assert resolved.table_pattern == "oracle.treasury.bonds"
    assert "BondTrader" in resolved.required_roles


def test_hierarchical_claim_resolution():
    """Verify hierarchical priority resolution."""
    ctx = SecurityContext(
        user_id="user1",
        roles=["Trader"],
        trading_desks=["FX"],
        regions=["US", "EMEA"],
        allowed_accounts=["ACC-001"],
    )
    assert ctx.get_effective_claims("trading_desks") == ["FX"]
    assert ctx.get_effective_claims("regions") == ["US", "EMEA"]
    assert ctx.get_effective_claims("allowed_accounts") == ["ACC-001"]


@pytest.mark.asyncio
async def test_get_security_context_dependency():
    """Verify FastAPI dependency parses JWT claims into SecurityContext."""
    mock_claims = {
        "sub": "trader@firm.com",
        "preferred_username": "trader@firm.com",
        "roles": ["Trader", "FinancialAnalyst"],
        "groups": ["AD_TradingGroup"],
        "trading_desks": ["FX"],
        "regions": ["US"],
        "allowed_accounts": ["ACC-101", "ACC-102"],
        "clearance_level": "RESTRICTED",
    }
    ctx = await get_security_context(mock_claims)
    assert ctx.user_id == "trader@firm.com"
    assert "Trader" in ctx.roles
    assert "AD_TradingGroup" in ctx.groups
    assert ctx.trading_desks == ["FX"]
    assert ctx.regions == ["US"]
    assert ctx.allowed_accounts == ["ACC-101", "ACC-102"]
    assert ctx.clearance_level == "RESTRICTED"


def test_role_enum_values():
    """Verify standard enterprise role enum members."""
    assert Role.COMPLIANCE_ADMIN == "ComplianceAdmin"
    assert Role.TRADER == "Trader"
    assert Role.MNA_AUDITOR == "MNA_Auditor"
    assert Role.FINANCIAL_ANALYST == "FinancialAnalyst"
    assert Role.SECURITY_ADMIN == "SecurityAdmin"
