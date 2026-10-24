# Phase 4: Web SQL Studio, Enterprise Security & AKS Production Deployment — Research

## Executive Summary

Phase 4 concludes the enterprise delivery of the Federated Financial Data Hub by delivering three critical production pillars:
1. **Web-Based Monaco SQL Studio**: An internal web application empowering financial analysts and data engineers to explore unified schemas, write complex federated queries with rich Monaco autocompletion, inspect execution metrics/timelines (pushdown vs local join breakdown), trigger instant exports (CSV, Parquet, NDJSON), and download one-click Power BI (`.pbids`) and Excel (`.odc`) connection files.
2. **Enterprise Azure Security & RBAC**: Microsoft Entra ID (Azure AD) Single Sign-On (SSO) with JWT bearer token validation, Azure Workload Identity for passwordless access to cloud resources, and Role-Based Access Control (`FinancialAnalyst`, `DataEngineer`, `SecurityAdmin`) with development bypass toggles.
3. **AKS Production Deployment & Helm Chart**: Production multi-stage containerization, Kubernetes Helm chart packaging, high-speed ephemeral NVMe/SSD scratch volume configuration for DuckDB out-of-core hash joins, multi-protocol service routing (HTTP 8000, PGWire 5433, Arrow Flight 5005), and Azure Virtual Network (VNet) peering blueprint for on-premises database connectivity via ExpressRoute.

---

## Standard Stack & Technology Decisions

| Layer / Component | Technology / Library | Version | Role & Justification |
| :--- | :--- | :--- | :--- |
| **SQL Editor** | `@monaco-editor/react` | `^4.7.0` | Industry-standard VS Code editor engine for web browsers. Provides syntax highlighting, auto-indentation, keyboard shortcuts (`Ctrl+Enter`), and dynamic schema-aware autocompletion without heavy custom code. |
| **Icons & UI** | `lucide-react` | `^1.16.0` | Lightweight, tree-shakeable SVG icon set for database engines, schemas, tables, execution metrics, and download actions. |
| **Frontend Framework** | React + Vite + Tailwind v4 | `19.3` / `8.3` / `4.3` | Ultra-fast bundle times, native TypeScript support, and zero-runtime Tailwind v4 styling with dark theme consistency. |
| **JWT & Token Validation** | `pyjwt[crypto]` | `^2.10.1` | RFC 7519 compliant JWT decoder supporting RSA-SHA256 (`RS256`) and dynamic public key resolution from Microsoft Entra ID discovery endpoints. |
| **Azure Identity** | `azure-identity` | `^1.26` | Implements `DefaultAzureCredential` supporting Azure Workload Identity in AKS, environment variables, and Azure CLI for local developer authentication. |
| **Container Engine** | Multi-stage Docker | `3.13-slim` / `node:20` | Minimal attack surface, non-root execution, separated build-time dependencies from production runtimes. |
| **Kubernetes Packaging** | Helm v3 | `v3.16+` | Standardized parameterization of AKS deployments, ingress routing, multi-port services, horizontal pod autoscaling, and scratch volumes. |

---

## Architecture Patterns

### 1. Web SQL Studio UI Layout & Component Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Top Bar: Brand, Health Indicators (API, DuckDB), Entra ID User Pill (Role: FinancialAnalyst), Theme   │
├──────────────────────────┬─────────────────────────────────────────────────────────────────────────────┤
│ Left Panel: Catalog Tree │ Center / Right Panel: Studio Cockpit                                        │
│                          │                                                                             │
│ [Search Tables...]       │ ┌─────────────────────────────────────────────────────────────────────────┐ │
│                          │ │ Monaco Editor (SQL)                                                     │ │
│ ▼ adls_lake (Iceberg)    │ │ SELECT t.trade_id, c.name, t.amount                                     │ │
│   ▼ equity               │ │ FROM adls_lake.equity.trades t                                         │ │
│     ▼ trades             │ │ JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id        │ │
│       # trade_id (int)   │ │ ORDER BY t.trade_id LIMIT 100                                           │ │
│       T counterparty     │ └─────────────────────────────────────────────────────────────────────────┘ │
│       $ amount (float)   │ Action Bar: [▶ Run (Ctrl+Enter)] [Format SQL] [Clear]   [Export CSV/Parquet]│
│                          ├─────────────────────────────────────────────────────────────────────────────┤
│ ▼ oracle_dw (Relational) │ Execution Metrics & Explain Timeline Bar:                                   │
│   ▼ risk                 │ ● Planning: 1.2ms │ ● Oracle Subq: 18ms │ ● ADLS Subq: 22ms │ ● Join: 4.1ms │
│     ▶ counterparties     │ Total: 45.3ms │ Rows: 100 │ Cache: MISS │ Spill: DISABLED               │
│                          ├─────────────────────────────────────────────────────────────────────────────┤
│ 1-Click Launchers:       │ Results Data Grid (Virtualized Table):                                      │
│ [⬇ .pbids (Power BI)]    │ ┌──────────┬─────────────────────────────┬────────────────────────────┐      │
│ [⬇ .odc (Excel)]         │ │ trade_id │ name                        │ amount                     │      │
│                          │ ├──────────┼─────────────────────────────┼────────────────────────────┤      │
│                          │ │ 1        │ Alpha Corp                  │ 1,500.00                   │      │
│                          │ │ 2        │ Beta LLC                    │ 2,500.00                   │      │
│                          │ └──────────┴─────────────────────────────┴────────────────────────────┘      │
└──────────────────────────┴─────────────────────────────────────────────────────────────────────────────┘
```

#### Key Frontend Modules:
1. **`SchemaTree`**: Fetches tree from `GET /api/v1/views` and renders datasource badges (Iceberg, Relational, Document). Clicking a table inserts a template into the editor or previews schema columns.
2. **`SqlEditor`**: Wraps `@monaco-editor/react`. Registers a completion item provider for `sql` language that injects table paths (`adls_lake.equity.trades`) and column suggestions as the user types.
3. **`ExplainTimeline`**: Visual progress-flame bar displaying execution breakdown (`planning_ms`, `subquery_ms` per remote source, `join_ms`), cache hit indicator, and scratch spill warnings.
4. **`ResultsGrid`**: Virtualized table component rendering columns and rows returned by `POST /api/v1/query/execute`. Includes quick filtering and column sorting.
5. **`LaunchersBar`**: Dedicated launcher widgets linking to `GET /api/v1/launchers/pbids` and `GET /api/v1/launchers/odc`.

---

### 2. Microsoft Entra ID (Azure AD) SSO & RBAC Architecture

```
                    ┌───────────────────────────┐
                    │     Client / Browser      │
                    └─────────────┬─────────────┘
                                  │
                  1. Authorization Code + PKCE
                  2. Bearer JWT (Access Token)
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │    FastAPI Auth Gateway   │
                    └─────────────┬─────────────┘
                                  │
                        3. Decode & Verify
                           - Issuer: https://login.microsoftonline.com/{tenant_id}/v2.0
                           - Audience: api://{client_id}
                           - Signature: Entra ID JWKS Keys
                                  │
                        4. Extract Roles & Claims
                           - sub: user@enterprise.com
                           - roles: ["FinancialAnalyst"]
                                  │
         ┌────────────────────────┴────────────────────────┐
         │                                                 │
         ▼                                                 ▼
[FinancialAnalyst]                                 [DataEngineer]
- POST /api/v1/query/execute                       - All FinancialAnalyst endpoints
- GET  /api/v1/views/**                            - POST /api/v1/cache/refresh
- GET  /api/v1/export/query                        - POST /api/v1/datasources/refresh
- GET  /api/v1/launchers/**                        - POST /api/v1/cache/dimension/**
```

#### Token Verification Strategy:
- In production, Entra ID issues signed JWTs. The backend fetches public keys from `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys` using `PyJWKClient` (with caching and automatic key rotation).
- In development/testing environments, `AUTH_ENABLED=false` allows requests without headers, injecting a default `DevAdminUser` to ensure unit tests and local CLI tools continue to run without live Azure subscriptions.

---

### 3. AKS Production Deployment & High-Speed Scratch Architecture

```
                               ┌────────────────────────────────────────────────────────┐
                               │                    Azure Cloud                         │
                               │                                                        │
                               │   ┌────────────────────────────────────────────────┐   │
                               │   │           Azure Kubernetes Service (AKS)       │   │
                               │   │                                                │   │
                               │   │   Pod: federated-data-hub                      │   │
                               │   │   ┌────────────────────────────────────────┐   │   │
                               │   │   │  Container: backend                    │   │   │
                               │   │   │  - Port 8000: REST API & Studio        │   │   │
                               │   │   │  - Port 5433: PGWire (Power BI DQ)     │   │   │
                               │   │   │  - Port 5005: Arrow Flight (gRPC)      │   │   │
                               │   │   └──────────────────┬─────────────────────┘   │   │
                               │   │                      │                         │   │
                               │   │                      ▼                         │   │
                               │   │      [Local NVMe/SSD Scratch Volume]           │   │
                               │   │      - emptyDir backed by node ephemeral disk  │   │
                               │   │      - Mounted at /scratch                     │   │
                               │   │      - DuckDB temp_directory out-of-core spill │   │
                               │   └──────────────────────┬─────────────────────────┘   │
                               │                          │                             │
                               │                          ▼                             │
                               │   [Azure VNet 10.240.0.0/16]                           │
                               │        │ Private Endpoints (ADLS Gen2, Azure SQL)      │
                               │        │ VNet Peering                                  │
                               └────────┼───────────────────────────────────────────────┘
                                        │
                         ExpressRoute / Site-to-Site VPN
                                        │
                                        ▼
                   ┌────────────────────────────────────────┐
                   │    On-Premises Enterprise Datacenter   │
                   │    - Oracle Financials (10.0.1.50:1521) │
                   │    - SQL Server GL     (10.0.2.80:1433) │
                   └────────────────────────────────────────┘
```

#### Why Local NVMe/SSD `emptyDir` for DuckDB Scratch?
When joining multi-gigabyte subqueries, in-memory limits (`max_memory=32GB`) may be exceeded. If DuckDB attempts to spill out-of-core to standard Azure Blob CSI storage or NFS, network latency will degrade join performance by 100x. By mounting a local node NVMe/SSD `emptyDir` volume at `/scratch` and setting DuckDB's `SET temp_directory = '/scratch'`, out-of-core spills occur at **multi-gigabyte/second NVMe bus speeds**, avoiding OOM kills and maintaining fast join completion.

---

## Don't Hand-Roll

- **DO NOT hand-roll SQL syntax parsers or code editors in React**: Building a textarea-based SQL editor requires complex tokenizers, selection range handlers, and bracket matching. Use `@monaco-editor/react`, which embeds the battle-tested VS Code editor with full language features.
- **DO NOT hardcode Azure AD public keys or parse raw JWT signatures with custom RSA math**: Use `jwt.PyJWKClient` from `PyJWT`, which automatically downloads, parses, and caches Azure's JWKS keys according to the `kid` header parameter.
- **DO NOT use network-attached PVCs (Azure Files/Blob) for DuckDB scratch space**: Network latency and locks cause DuckDB disk spills to hang. Always use local ephemeral SSD storage (`emptyDir`).
- **DO NOT expose PGWire (port 5433) and Arrow Flight (port 5005) through standard HTTP Ingress controllers**: Standard HTTP Ingress (like Nginx Ingress or Azure Application Gateway) expects HTTP/1.1 or HTTP/2 web traffic. For PGWire (raw TCP) and Arrow Flight (gRPC over HTTP/2), configure an AKS `LoadBalancer` Service or internal LoadBalancer with dedicated port bindings.

---

## Common Pitfalls & How to Avoid Them

### 1. Monaco Editor Bundle Size & Worker Ingestion
- *Pitfall:* Bundling Monaco directly into client-side Vite builds can dramatically inflate initial bundle size (>5MB) if worker assets are loaded synchronously.
- *Mitigation:* `@monaco-editor/react` uses a lazy-loading CDN or local Vite dynamic chunking mechanism (`@monaco-editor/react` loads the Monaco core asynchronously on first mount).

### 2. Multi-Port Service Exposure on AKS
- *Pitfall:* Power BI connecting to PGWire requires TCP port `5433`, while analytical notebooks connecting to Arrow Flight require gRPC port `5005`. An HTTP-only Ingress cannot route PostgreSQL wire protocol traffic.
- *Mitigation:* In the Helm chart, deploy a dual strategy:
  1. `Ingress`: For Web SQL Studio and REST API (ports 80/443).
  2. `Service` of type `LoadBalancer` (or Internal LoadBalancer for intranet): Exposing TCP port `5433` and gRPC port `5005`.

### 3. Entra ID App Roles Claim Format
- *Pitfall:* In Microsoft Entra ID access tokens, assigned application roles can appear either in the `roles` claim (for app roles) or in the `groups` claim (for security groups). If the backend strictly searches `roles` and the tenant uses group claims, users get 403 Forbidden.
- *Mitigation:* The auth middleware inspects both `claims.get("roles", [])` and `claims.get("groups", [])`, mapping them against configurable role mappings in `Settings`.

### 4. VNet Peering MTU & Jumbo Frames
- *Pitfall:* When streaming multi-GB Arrow record batches across on-premises VPN/ExpressRoute gateways, default MTU mismatch (1500 vs 1400) can cause packet fragmentation and severe throughput degradation.
- *Mitigation:* Ensure Kubernetes pod MTU and Azure VNet ExpressRoute configurations align with corporate network standards.

---

## Detailed Implementation Blueprints

### A. Monaco Completion Provider for Unified Catalog (`frontend/src/lib/monaco.ts`)

```typescript
import type { Monaco } from '@monaco-editor/react'
import type { ViewSummary } from './types'

export function registerCatalogCompletions(monaco: Monaco, views: ViewSummary[]) {
  return monaco.languages.registerCompletionItemProvider('sql', {
    provideCompletionItems: (model, position) => {
      const word = model.getWordUntilPosition(position)
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      }

      const suggestions = views.map((v) => ({
        label: v.full_path,
        kind: monaco.languages.CompletionItemKind.Class,
        insertText: v.full_path,
        detail: `Virtual Table (${v.catalog}.${v.schema_name})`,
        documentation: `Format: ${v.format || 'unknown'}\nRoute: ${v.url}`,
        range,
      }))

      return { suggestions }
    },
  })
}
```

### B. Microsoft Entra ID JWT Validator Middleware (`backend/app/auth/entra.py`)

```python
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import get_settings

security = HTTPBearer(auto_error=False)

class EntraIDAuthenticator:
    def __init__(self):
        settings = get_settings()
        self.enabled = settings.auth_enabled
        self.tenant_id = settings.entra_tenant_id
        self.client_id = settings.entra_client_id
        if self.enabled and self.tenant_id:
            jwks_url = f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys"
            self.jwks_client = PyJWKClient(jwks_url)

    async def __call__(self, creds: HTTPAuthorizationCredentials | None = Security(security)):
        if not self.enabled:
            return {"sub": "dev-admin@enterprise.com", "roles": ["FinancialAnalyst", "DataEngineer", "SecurityAdmin"]}

        if not creds:
            raise HTTPException(status_code=401, detail="Missing Authorization Bearer token.")

        token = creds.credentials
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            data = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=f"https://login.microsoftonline.com/{self.tenant_id}/v2.0",
            )
            return data
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid authentication token: {exc}")
```

### C. AKS Helm Values & Scratch Volume (`deploy/helm/data-hub/values.yaml`)

```yaml
global:
  environment: production

backend:
  replicaCount: 2
  image:
    repository: enterprise-acr.azurecr.io/federated-data-hub/backend
    tag: v1.0.0
    pullPolicy: IfNotPresent

  resources:
    requests:
      cpu: "4000m"
      memory: "16Gi"
    limits:
      cpu: "8000m"
      memory: "32Gi"

  scratchVolume:
    enabled: true
    mountPath: /scratch
    sizeLimit: 100Gi
    storageMedium: "" # uses local node NVMe/SSD

  security:
    authEnabled: true
    entraTenantId: "00000000-0000-0000-0000-000000000000"
    entraClientId: "api://federated-data-hub"

  service:
    type: LoadBalancer # internal Azure LB with ports 8000, 5433, 5005
    annotations:
      service.beta.kubernetes.io/azure-load-balancer-internal: "true"
    ports:
      http: 8000
      pgwire: 5433
      flight: 5005

frontend:
  replicaCount: 2
  image:
    repository: enterprise-acr.azurecr.io/federated-data-hub/frontend
    tag: v1.0.0
```

---

## Validation Architecture

### Verification Map for Phase 4

| Task / Capability | Verification Method | Pass Criteria |
| :--- | :--- | :--- |
| **Monaco SQL Studio UI** | Vite Build & React Component Tests | TypeScript compiles with zero errors, components render schema tree, Monaco editor accepts SQL, and results table virtualizes. |
| **Intellisense Autocomplete** | Catalog completion unit tests | Suggestions list matches `default_catalog.get_unified_tree()` entries. |
| **Entra ID JWT Validator** | Pytest mock token verification | Valid tokens decode claims; expired/invalid signature tokens yield 401; roles enforce 403 on restricted endpoints; dev mode bypass works. |
| **Production Dockerfiles** | Multi-stage Docker build & dry-run | Backend and Frontend Docker images build cleanly with non-root security contexts. |
| **Helm Chart Packaging** | `helm lint` and template dry-run | Chart templates render valid Kubernetes manifests with multi-port service and `/scratch` emptyDir volume. |
