"""Authentication, Role-Based Access Control, and Data Governance module."""

from app.auth.entra import EntraIDAuthenticator, authenticator
from app.auth.governance import (
    AclRule,
    GateType,
    GovernancePolicyRegistry,
    PolicyStrategy,
    SecurityContext,
    TableSecurityPolicy,
    governance_registry,
)
from app.auth.rbac import Role, get_security_context, require_roles

__all__ = [
    "AclRule",
    "EntraIDAuthenticator",
    "GateType",
    "GovernancePolicyRegistry",
    "PolicyStrategy",
    "Role",
    "SecurityContext",
    "TableSecurityPolicy",
    "authenticator",
    "get_security_context",
    "governance_registry",
    "require_roles",
]
