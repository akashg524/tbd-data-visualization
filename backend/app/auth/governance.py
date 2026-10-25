"""Enterprise governance models, security context, and policy registry."""

from __future__ import annotations

import fnmatch
import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class GateType(StrEnum):
    """Gate access model."""

    RBAC_ONLY = "rbac_only"  # Access gated entirely at table level by Azure RBAC
    RBAC_AND_ACL = "rbac_and_acl"  # Gate 1 RBAC check + Gate 2 Row-Level ACL synthesis


class PolicyStrategy(StrEnum):
    """Strategy used to resolve and inject RLS predicates."""

    DIRECT = "direct"  # Claim values match table column values directly
    TRANSLATION = "translation"  # Text names/codes translated to IDs via mapping dictionary
    RELATIONSHIP = "relationship"  # Indirect foreign-key lookup via dimension table


class AclRule(BaseModel):
    """Fine-grained row-level security rule mapping identity claims to table columns."""

    claim_field: str
    target_column: str
    strategy: PolicyStrategy = PolicyStrategy.DIRECT
    lookup_map: dict[str, Any] | None = None
    lookup_table: str | None = None
    lookup_key_column: str | None = None
    lookup_val_column: str | None = None


class TableSecurityPolicy(BaseModel):
    """Security policy definition governing table access and row-level filtering."""

    table_pattern: str
    gate: GateType = GateType.RBAC_AND_ACL
    required_roles: list[str] = Field(default_factory=list)
    acl_rules: list[AclRule] = Field(default_factory=list)
    acl_combination: str = "AND"
    fail_closed: bool = True
    exempt_roles: set[str] = Field(default_factory=lambda: {"ComplianceAdmin", "SecurityAdmin"})


class SecurityContext(BaseModel):
    """Normalized security and entitlement context derived from Entra ID JWT claims."""

    user_id: str = "anonymous"
    username: str = "anonymous"
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    trading_desks: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    allowed_accounts: list[str] = Field(default_factory=list)
    clearance_level: str = "STANDARD"
    attributes: dict[str, Any] = Field(default_factory=dict)
    hierarchical_priority: bool = True

    @property
    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint for result cache key isolation."""
        payload = {
            "roles": sorted(self.roles),
            "groups": sorted(self.groups),
            "trading_desks": sorted(self.trading_desks),
            "regions": sorted(self.regions),
            "allowed_accounts": sorted(self.allowed_accounts),
            "clearance_level": self.clearance_level,
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def is_exempt(self, exempt_roles: set[str]) -> bool:
        """Check if user has an exempt compliance or security administration role."""
        user_roles = set(self.roles) | set(self.groups)
        return bool(user_roles.intersection(exempt_roles))

    def has_any_role(self, required_roles: list[str]) -> bool:
        """Verify whether user holds at least one of the required roles."""
        if not required_roles:
            return True
        user_roles = set(self.roles) | set(self.groups)
        return bool(user_roles.intersection(set(required_roles)))

    def get_effective_claims(self, claim_field: str) -> list[Any]:
        """Extract claim values respecting hierarchical priority rules."""
        if claim_field in ("trading_desks", "trading_desk"):
            return self.trading_desks
        if claim_field in ("regions", "region"):
            # When hierarchical priority is active and trading_desks are explicitly assigned,
            # desk-level constraints can supersede or refine broader regional access
            return self.regions
        if claim_field in ("allowed_accounts", "accounts", "account_no"):
            return self.allowed_accounts
        return self.attributes.get(claim_field, [])


class GovernancePolicyRegistry:
    """Central registry managing table security policies and policy resolution."""

    def __init__(self) -> None:
        self._policies: list[TableSecurityPolicy] = []
        self._initialize_default_policies()

    def _initialize_default_policies(self) -> None:
        """Pre-register default institutional governance policies."""
        # Standard region name-to-integer dictionary
        region_map = {"US": 1, "EMEA": 2, "APAC": 3, "LATAM": 4}

        # 1. Pure Azure RBAC Table: M&A deals gated by role
        self.register_policy(
            TableSecurityPolicy(
                table_pattern="*.mna_deals",
                gate=GateType.RBAC_ONLY,
                required_roles=["MNA_Auditor", "SecurityAdmin"],
            )
        )

        # 2. Hybrid RBAC + ACL Table: Trades table with desk, region, and account filters
        self.register_policy(
            TableSecurityPolicy(
                table_pattern="*.trades",
                gate=GateType.RBAC_AND_ACL,
                required_roles=["FinancialAnalyst", "Trader"],
                acl_rules=[
                    AclRule(
                        claim_field="trading_desks",
                        target_column="desk_code",
                        strategy=PolicyStrategy.DIRECT,
                    ),
                    AclRule(
                        claim_field="regions",
                        target_column="region_id",
                        strategy=PolicyStrategy.TRANSLATION,
                        lookup_map=region_map,
                    ),
                    AclRule(
                        claim_field="allowed_accounts",
                        target_column="account_no",
                        strategy=PolicyStrategy.DIRECT,
                    ),
                ],
                acl_combination="AND",
                fail_closed=True,
            )
        )

        # 3. Hybrid RBAC + ACL Table: Counterparties table with region filter
        self.register_policy(
            TableSecurityPolicy(
                table_pattern="*.counterparties",
                gate=GateType.RBAC_AND_ACL,
                required_roles=["FinancialAnalyst"],
                acl_rules=[
                    AclRule(
                        claim_field="regions",
                        target_column="region_id",
                        strategy=PolicyStrategy.TRANSLATION,
                        lookup_map=region_map,
                    ),
                ],
                acl_combination="AND",
                fail_closed=True,
            )
        )

    def register_policy(self, policy: TableSecurityPolicy) -> None:
        """Register or override a table security policy."""
        # Replace existing if table_pattern matches
        self._policies = [p for p in self._policies if p.table_pattern != policy.table_pattern]
        self._policies.append(policy)

    def get_policy_for_table(self, table_path: str) -> TableSecurityPolicy | None:
        """Find matching policy using pattern matching (e.g. *.trades matches adls_lake.equity.trades)."""
        normalized_path = table_path.lower()
        parts = normalized_path.split(".")
        simple_name = parts[-1] if parts else normalized_path

        for policy in self._policies:
            pat = policy.table_pattern.lower()
            if fnmatch.fnmatch(normalized_path, pat) or fnmatch.fnmatch(simple_name, pat):
                return policy
        return None

    def validate_rbac_gate(self, table_path: str, context: SecurityContext) -> bool:
        """Validate Gate 1: Check whether the user has required roles to access the table."""
        policy = self.get_policy_for_table(table_path)
        if policy is None:
            return True  # Non-governed tables allow standard access
        if context.is_exempt(policy.exempt_roles):
            return True
        return context.has_any_role(policy.required_roles)


# Global policy registry singleton
governance_registry = GovernancePolicyRegistry()
