# Plan 05-01 Summary: Entra ID Governance Claim Mapping & Two-Gate Declarative Policy Engine

## Completed Tasks
1. **Governance Data Models & SecurityContext**:
   - Implemented `backend/app/auth/governance.py`:
     - Defined `GateType` (`RBAC_ONLY` vs `RBAC_AND_ACL`) and `PolicyStrategy` (`DIRECT`, `TRANSLATION`, `RELATIONSHIP`).
     - Defined `AclRule` supporting claim-to-column mappings with dictionary or table translation lookups.
     - Defined `TableSecurityPolicy` encapsulating Gate 1 RBAC requirements and Gate 2 ACL rules with fail-closed semantics.
     - Defined `SecurityContext` model extracting user identities, roles, groups, trading desks, regions, and allowed accounts, with hierarchical claim resolution.
     - Implemented deterministic SHA-256 `fingerprint` property on `SecurityContext` to isolate cache keys across tenants, desks, and accounts.

2. **Declarative GovernancePolicyRegistry**:
   - Built `GovernancePolicyRegistry` singleton managing table security policies.
   - Pre-registered standard institutional governance policies:
     - `*.mna_deals`: Gate 1 `RBAC_ONLY`, requires `MNA_Auditor` or `SecurityAdmin`.
     - `*.trades`: Gate 1 `RBAC_AND_ACL`, requires `FinancialAnalyst` or `Trader`, Gate 2 ACL rules for `trading_desks -> desk_code` (DIRECT), `regions -> region_id` (TRANSLATION `{"US": 1, "EMEA": 2, "APAC": 3, "LATAM": 4}`), and `allowed_accounts -> account_no` (DIRECT).
     - `*.counterparties`: Gate 1 `RBAC_AND_ACL`, requires `FinancialAnalyst`, Gate 2 ACL for `regions -> region_id` (TRANSLATION).
   - Provided `validate_rbac_gate` to evaluate Gate 1 table access.

3. **RBAC Extensions & FastAPI Dependency**:
   - Updated `backend/app/auth/rbac.py`:
     - Added `Role.COMPLIANCE_ADMIN`, `Role.TRADER`, and `Role.MNA_AUDITOR`.
     - Implemented `get_security_context` dependency extracting `SecurityContext` from Entra ID bearer tokens.
   - Updated `backend/app/auth/entra.py` with mock governance claims in dev bypass mode.
   - Exported public symbols in `backend/app/auth/__init__.py`.

4. **Comprehensive Test Suite**:
   - Implemented `tests/test_governance.py` with 8 test cases covering:
     - Context normalization and attribute extraction.
     - Fingerprint determinism (different desks/regions = different hashes, identical scopes = identical hashes).
     - Gate 1 RBAC validation and table gating.
     - Gate 2 ACL policy resolution with wildcard pattern matching.
     - Name-to-ID value translation strategy.
     - Exemption logic for `ComplianceAdmin`.
     - FastAPI `get_security_context` dependency execution.

## Verification
- `pytest tests/test_governance.py tests/test_auth.py -v`: All 19 tests passed in 7.42s.
- `ruff check backend/ tests/`: 0 errors, 0 warnings.
