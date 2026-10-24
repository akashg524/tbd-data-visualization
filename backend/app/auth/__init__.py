"""Authentication and Role-Based Access Control module."""

from app.auth.entra import EntraIDAuthenticator, authenticator
from app.auth.rbac import Role, require_roles

__all__ = [
    "EntraIDAuthenticator",
    "Role",
    "authenticator",
    "require_roles",
]
