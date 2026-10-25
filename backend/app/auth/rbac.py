"""Role-Based Access Control (RBAC) enforcement and SecurityContext resolution."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from fastapi import Depends, HTTPException, status

from app.auth.entra import authenticator
from app.auth.governance import SecurityContext


class Role(StrEnum):
    """Standard enterprise roles for Federated Semantic Data Hub."""

    FINANCIAL_ANALYST = "FinancialAnalyst"
    DATA_ENGINEER = "DataEngineer"
    SECURITY_ADMIN = "SecurityAdmin"
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    TRADER = "Trader"
    MNA_AUDITOR = "MNA_Auditor"


def require_roles(*allowed_roles: str | Role) -> Callable[..., dict[str, Any]]:
    """FastAPI dependency factory enforcing that the authenticated user possesses at least one allowed role."""
    allowed_set = {str(r.value if isinstance(r, Role) else r) for r in allowed_roles}

    async def role_checker(claims: dict[str, Any] = Depends(authenticator)) -> dict[str, Any]:  # noqa: B008
        user_roles = claims.get("roles", [])
        if isinstance(user_roles, str):
            user_roles = [user_roles]

        user_groups = claims.get("groups", [])
        if isinstance(user_groups, str):
            user_groups = [user_groups]

        combined = set(user_roles) | set(user_groups)

        if not allowed_set.intersection(combined):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role permissions. Required one of: {sorted(allowed_set)}",
            )

        return claims

    return role_checker


async def get_security_context(claims: dict[str, Any] = Depends(authenticator)) -> SecurityContext:  # noqa: B008
    """FastAPI dependency resolving normalized SecurityContext from authenticated claims."""
    user_roles = claims.get("roles", [])
    if isinstance(user_roles, str):
        user_roles = [user_roles]

    user_groups = claims.get("groups", [])
    if isinstance(user_groups, str):
        user_groups = [user_groups]

    trading_desks = claims.get("trading_desks", claims.get("trading_desk", []))
    if isinstance(trading_desks, str):
        trading_desks = [trading_desks]

    regions = claims.get("regions", claims.get("region", []))
    if isinstance(regions, str):
        regions = [regions]

    allowed_accounts = claims.get("allowed_accounts", claims.get("accounts", []))
    if isinstance(allowed_accounts, str):
        allowed_accounts = [allowed_accounts]

    return SecurityContext(
        user_id=claims.get("sub", "anonymous"),
        username=claims.get("preferred_username", claims.get("name", "anonymous")),
        roles=user_roles,
        groups=user_groups,
        trading_desks=trading_desks,
        regions=regions,
        allowed_accounts=allowed_accounts,
        clearance_level=claims.get("clearance_level", "STANDARD"),
        attributes=claims,
    )
