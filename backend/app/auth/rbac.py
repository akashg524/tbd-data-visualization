"""Role-Based Access Control (RBAC) enforcement dependencies."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from fastapi import Depends, HTTPException, status

from app.auth.entra import authenticator


class Role(StrEnum):
    """Standard enterprise roles for Federated Semantic Data Hub."""

    FINANCIAL_ANALYST = "FinancialAnalyst"
    DATA_ENGINEER = "DataEngineer"
    SECURITY_ADMIN = "SecurityAdmin"


def require_roles(*allowed_roles: str | Role) -> Callable[..., dict[str, Any]]:
    """FastAPI dependency factory enforcing that the authenticated user possesses at least one allowed role."""
    allowed_set = {str(r.value if isinstance(r, Role) else r) for r in allowed_roles}

    async def role_checker(claims: dict[str, Any] = Depends(authenticator)) -> dict[str, Any]:  # noqa: B008
        # Extract roles from token claims - Entra ID tokens provide `roles` (app) or `groups` (AD)
        user_roles = claims.get("roles", [])
        if isinstance(user_roles, str):
            user_roles = [user_roles]

        user_groups = claims.get("groups", [])
        if isinstance(user_groups, str):
            user_groups = [user_groups]

        combined = set(user_roles) | set(user_groups)

        # Check for intersection
        if not allowed_set.intersection(combined):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role permissions. Required one of: {sorted(allowed_set)}",
            )

        return claims

    return role_checker
