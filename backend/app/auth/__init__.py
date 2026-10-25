"""Authentication, Role-Based Access Control, and Data Governance module."""

from app.auth.audit import AuditLogger, audit_logger
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
    "AuditLogger",
    "EntraIDAuthenticator",
    "GateType",
    "GovernancePolicyRegistry",
    "PolicyStrategy",
    "Role",
    "SecurityContext",
    "TableSecurityPolicy",
    "audit_logger",
    "authenticator",
    "get_security_context",
    "governance_registry",
    "require_roles",
]
