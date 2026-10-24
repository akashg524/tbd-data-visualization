"""Microsoft Entra ID (Azure AD) JWT token authenticator."""

from __future__ import annotations

from typing import Any

import jwt
import structlog
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import get_settings

logger = structlog.get_logger(__name__)

security_bearer = HTTPBearer(auto_error=False)


class EntraIDAuthenticator:
    """Authenticates Microsoft Entra ID bearer tokens against official JWKS discovery keys."""

    def __init__(self) -> None:
        self._jwks_client: PyJWKClient | None = None
        self._tenant_id: str = ""

    def get_jwks_client(self, tenant_id: str, cache_ttl: int = 86400) -> PyJWKClient:
        """Obtain or cache PyJWKClient for Entra ID tenant."""
        if self._jwks_client is None or self._tenant_id != tenant_id:
            jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
            self._jwks_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=cache_ttl)
            self._tenant_id = tenant_id
        return self._jwks_client

    async def __call__(
        self,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Security(security_bearer),  # noqa: B008
    ) -> dict[str, Any]:
        """Validate bearer token from incoming request or return dev bypass identity."""
        settings = get_settings()

        # Dev bypass mode: allow unauthenticated requests for local testing and dev
        if not settings.auth_enabled:
            return {
                "sub": "dev-analyst@enterprise.com",
                "name": "Dev Analyst",
                "preferred_username": "dev-analyst@enterprise.com",
                "roles": ["FinancialAnalyst", "DataEngineer", "SecurityAdmin"],
            }

        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided in Authorization header.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        if not settings.entra_tenant_id or not settings.entra_client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Entra ID tenant_id or client_id is not configured on server.",
            )

        try:
            jwks_client = self.get_jwks_client(settings.entra_tenant_id, settings.entra_jwks_cache_ttl)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            issuer = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0"
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.entra_client_id,
                issuer=issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
            return claims
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid authentication token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except Exception as exc:
            logger.error("entra_token_validation_error", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token validation failed: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc


authenticator = EntraIDAuthenticator()
