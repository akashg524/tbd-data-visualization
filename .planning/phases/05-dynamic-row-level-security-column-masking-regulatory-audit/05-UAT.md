---
status: complete
phase: 05-dynamic-row-level-security-column-masking-regulatory-audit
source:
  - 05-01-SUMMARY.md
  - 05-02-SUMMARY.md
  - 05-03-SUMMARY.md
started: 2026-10-25T04:30:00Z
updated: 2026-10-25T05:15:00Z
---

## Current Test

number: 3
name: Cross-Protocol Policy Enforcement, Cache Isolation & Audit Trail
expected: |
  All Phase 5 user acceptance criteria completed and verified 100% passing across 130 unit and integration tests.
awaiting: none

## Tests

### 1. Entra ID Claim Mapping & Two-Gate Declarative Policy Engine
expected: Declarative TableSecurityPolicy registry supporting Gate 1 coarse-grained Azure RBAC and Gate 2 fine-grained ACL/RLS with direct, translation, and relationship strategies. SecurityContext mapping user claims with deterministic SHA-256 fingerprint generation. Default policies for `*.mna_deals`, `*.trades`, and `*.counterparties`.
result: pass

### 2. SQLGlot AST RLS Rewriter & Pluggable Filter Injection
expected: AST-based rewriter intercepting SQL queries, rejecting unauthorized table access (Gate 1 RBAC), qualifying table aliases, and synthesizing RLS WHERE predicates (Gate 2 ACL) with direct value injection, name-to-ID value translation (e.g. region names to integer IDs), subquery/CTE handling, fail-closed empty-claim security (`1 = 0`), and ComplianceAdmin unrestricted review exemption.
result: pass

### 3. Cross-Protocol Policy Enforcement, Cache Isolation & Regulatory Audit Trail
expected: Consistent policy enforcement across all serving protocols (REST Query, Table Views, OData v4, Chunked Export, PGWire, Arrow Flight). Security fingerprint isolation on result caching preventing data leaks across different entitlement profiles. Structured compliance audit logging emitting `analytical_query_execution` and `analytical_data_export` events for SIEM/Sentinel integration, with transparent explain telemetry in query responses.
result: pass
