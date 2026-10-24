# Plan 04-02 Summary: Microsoft Entra ID SSO & Role-Based Access Control

## Completed Tasks
1. **Application Authentication Configuration**:
   - Updated `backend/app/config.py` with `auth_enabled: bool = False`, `entra_tenant_id: str`, `entra_client_id: str`, and `entra_jwks_cache_ttl: int = 86400`.
   - Maintained default dev bypass mode (`auth_enabled=False`) so unit testing and local development run smoothly without requiring active Azure subscriptions or tokens.

2. **Entra ID JWT Validator with Discovery Keys**:
   - Implemented `backend/app/auth/entra.py` providing `EntraIDAuthenticator` class:
     - Leverages `PyJWKClient` pointing to `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys` with 24-hour in-memory JWKS caching.
     - Performs RS256 signature verification, token expiration checking (`exp`), and audience/issuer validation against `entra_client_id` and Microsoft tenant endpoints.
     - When `auth_enabled=False`, injects default developer identity with roles `["FinancialAnalyst", "DataEngineer", "SecurityAdmin"]`.

3. **Role-Based Access Control (RBAC)**:
   - Implemented `backend/app/auth/rbac.py` defining standard enterprise roles (`FinancialAnalyst`, `DataEngineer`, `SecurityAdmin`).
   - Implemented `require_roles(*allowed_roles)` dependency inspecting both application `roles` and Active Directory `groups` claims.
   - Raises HTTP 403 Forbidden with actionable error messages when the caller lacks required role claims.
   - Exported public symbols via `backend/app/auth/__init__.py`.

4. **Endpoint Protection Across Data and Serving Surfaces**:
   - Protected `/api/v1/query/execute` in `backend/app/api/query.py` with `require_roles("FinancialAnalyst", "DataEngineer")`.
   - Protected `/api/v1/views` and `/api/v1/views/{schema}/{table}` in `backend/app/api/views.py`.
   - Protected `/api/v1/odata`, `$metadata`, and entity set queries in `backend/app/api/odata.py`.
   - Protected `/api/v1/export/query` in `backend/app/serving/export.py`.

5. **Comprehensive Auth Test Suite**:
   - Implemented `tests/test_auth.py` covering 11 test scenarios with cryptographic RS256 key generation and PyJWKClient mocking:
     - Dev bypass mode validation.
     - Missing Authorization header (401).
     - Malformed bearer token (401).
     - Expired JWT token (401).
     - Audience mismatch (401).
     - Issuer mismatch (401).
     - Insufficient role permission rejection (403).
     - Successful authorization with `FinancialAnalyst` role (200).
     - Successful authorization with `DataEngineer` in `groups` claim (200).
     - Guarded views, odata, and export endpoint testing.
     - `Role` enum constant validation.

## Verification
- `pytest tests/test_auth.py -v`: All 11 tests passed in 8.74s.
- Full test suite: 96 passed in 42.87s.
- `ruff check backend/ tests/`: All checks passed, 0 errors, 0 warnings.
