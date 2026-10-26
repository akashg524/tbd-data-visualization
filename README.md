# Enterprise Federated Financial Data Hub & Semantic Query Layer

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.1+-FFF000.svg)](https://duckdb.org/)
[![PyArrow](https://img.shields.io/badge/PyArrow-18.0+-E05D44.svg)](https://arrow.apache.org/)
[![Tests](https://img.shields.io/badge/tests-130%20passed%20(100%25)-brightgreen.svg)]()
[![License Cost](https://img.shields.io/badge/licensing-%240%20(Open%20Source)-success.svg)]()
[![Upstream Safety](https://img.shields.io/badge/upstream-100%25%20Read--Only-informational.svg)]()

An enterprise-grade, zero-ETL federated semantic query engine and financial data hub connecting **10 TB – 100 TB of heterogeneous, read-only financial data** across Azure (ADLS Gen2 Iceberg, Cosmos DB, Azure SQL) and on-premises relational databases (Oracle 19c, SQL Server) directly to Power BI, Excel, and analytical consumers without commercial virtualization licensing fees.

---

## 📑 Table of Contents

- [Key Capabilities](#-key-capabilities)
- [System Architecture](#-system-architecture)
- [Two-Gate Security & Governance Engine](#-two-gate-security--governance-engine)
- [Multi-Protocol Serving Gateways](#-multi-protocol-serving-gateways)
- [Architecture Documentation & Slide Deck](#-architecture-documentation--slide-deck)
- [Quick Start](#-quick-start)
  - [Prerequisites](#prerequisites)
  - [Backend Setup](#backend-setup)
  - [Running Tests](#running-tests)
  - [Frontend Web SQL Studio](#frontend-web-sql-studio)
  - [Docker & Kubernetes Deployment](#docker--kubernetes-deployment)
- [Project Structure](#-project-structure)
- [Commercial ROI & Comparison](#-commercial-roi--comparison)
- [Verification & Quality Metrics](#-verification--quality-metrics)

---

## ⚡ Key Capabilities

- **100% Read-Only Zero-ETL Federation:** Connects to ADLS Gen2 Iceberg/Parquet, Oracle 19c, SQL Server, Azure SQL, and Cosmos DB in place. Strictly enforces read-only connections (`ApplicationIntent=ReadOnly`, read-only replicas) with **zero catalog modifications**.
- **Two-Gate Dynamic Security Engine:** 
  - **Gate 1 (Coarse-Grained Table RBAC):** Validates table permissions before query planning, immediately rejecting unauthorized access with HTTP 403.
  - **Gate 2 (Fine-Grained Dynamic RLS):** SQLGlot AST rewriter injects user claim-based row filters (`desk_code`, `region_id`) with table-alias qualification, name-to-ID value translation, and strict **fail-closed (`1 = 0`)** protection.
- **Fingerprint-Isolated Result Caching:** Caches query results under composite keys (`hash(SQL + security_fingerprint)`), guaranteeing sub-5ms repeated queries with zero cross-tenant/cross-desk data leakage.
- **Power BI DirectQuery Without Custom Drivers:** Built-in PostgreSQL wire protocol gateway (:5433) allowing Power BI Desktop and Service to issue real-time DirectQuery requests using the default out-of-the-box PostgreSQL connector.
- **High-Throughput Arrow Flight gRPC (:5005):** Multi-GB/s zero-copy columnar batch transport for scheduled bulk data ingestion into Power BI and data science notebooks.
- **SOX, FINRA & Basel III Compliance Audit:** Asynchronously emits structured JSON query execution and export audit events directly to **Microsoft Sentinel** and Azure Event Hub, capturing raw SQL, secured SQL, injected predicates, row counts, and caller claims.
- **Monaco Web SQL Studio:** Integrated web query cockpit featuring Monaco editor, 3-part virtual namespace autocompletion (`catalog.schema.table`), visual execution plan flame bars, virtualized grid, and 1-click Power BI (`.pbids`) and Excel (`.odc`) launchers.

---

## 🏛️ System Architecture

The platform operates across 5 decoupled tiers:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Tier 1: Consumption Layer                                                                       │
│  Power BI DirectQuery (:5433)  •  Arrow Flight (:5005)  •  Excel OData (:8000)  •  Monaco Studio │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 2: Multi-Protocol Serving Gateways                                                         │
│  BuenaVista PGWire Gateway     •  Arrow Flight Server   •  OData v4 & Chunked Export Engine      │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 3: Enterprise Governance & Two-Gate Security Engine                                        │
│  Gate 1: Table RBAC Check      •  Gate 2: SQLGlot AST RLS Rewriter  •  Sentinel Audit Logger     │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 4: Speed Layer & Federated Execution Engine                                                │
│  Security Fingerprint Cache    •  Pushdown Compiler    •  DuckDB In-Memory Vectorized Hash Joiner│
│  Local NVMe SSD Scratch Spill (/scratch) for out-of-core multi-million row joins                 │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│  Tier 5: 100% Read-Only Financial Data Stores                                                    │
│  ADLS Gen2 Iceberg (Parquet)   •  Oracle 19c (Risk DW) •  SQL Server  •  Azure SQL  •  Cosmos DB │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

For the comprehensive technical specification, see **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.

---

## 🛡️ Two-Gate Security & Governance Engine

| Security Gate | Level | Mechanism | Behavior |
|---|---|---|---|
| **Gate 1: Table RBAC** | Coarse-Grained | Pre-Planning Role Check | Checks caller roles against `TableSecurityPolicy.required_roles`. Throws `PermissionError` (HTTP 403) before any data scan if unauthorized. |
| **Gate 2: Dynamic RLS** | Fine-Grained | SQLGlot AST Rewrite | Walks `exp.Table` nodes, qualifies table aliases, and appends predicates to enclosing `WHERE` clauses based on Entra ID claims. |
| **Fail-Closed Security** | Policy Rule | AST Fallback Injection | If an authenticated user possesses zero matching entitlement claims on a governed table, injects `1 = 0` (returns 0 rows safely). |
| **Compliance Bypass** | Privileged Role | Role Exemption Check | Users with `ComplianceAdmin` or `SecurityAdmin` roles bypass RLS filter injection for complete regulatory audit reviews. |

---

## 🔌 Multi-Protocol Serving Gateways

| Protocol | Port | Primary Consumer | Key Characteristics |
|---|---|---|---|
| **PostgreSQL Wire (PGWire)** | `5433` | Power BI DirectQuery | Emulates PostgreSQL 14.0 via BuenaVista. Intercepts `information_schema` / `pg_catalog` for Navigator introspection and routes queries to federated planner. Zero custom client drivers required. |
| **Apache Arrow Flight** | `5005` | Power BI Import / Python | Zero-copy gRPC columnar stream delivering multi-GB/s throughput without row serialization overhead. |
| **OData v4 Feed** | `8000` | Microsoft Excel | Complete EDM XML metadata (`/$metadata`) and entity sets supporting `$filter`, `$select`, `$top`, and `$skip`. |
| **REST & Chunked Export** | `8000` | Web Applications | `/api/v1/query/execute` with transparent explain metrics, alongside streaming chunked exports in CSV, Parquet, and NDJSON. |

---

## 📊 Architecture Documentation & Slide Deck

- 📘 **[Detailed Architecture & UML Specification](docs/ARCHITECTURE.md):** Complete Mermaid flowcharts, class diagrams, sequence flows, state machine diagrams, and comparison matrices.
- 📽️ **[Interactive 16:9 Presentation Deck](docs/presentation/federated-data-hub-presentation.html):** Modern 12-slide presentation with keyboard navigation (`←`/`→`/`Space`), speaker notes (`N`), and fullscreen mode (`F`).
- 🖥️ **[Monaco Web SQL Studio Live Preview](docs/presentation/web-sql-studio-preview.html):** Live visual simulation of the Web SQL Studio interface.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+ (Python 3.13 recommended)
- Node.js 20+ & npm (for frontend studio)
- Git

### Backend Setup

```bash
# Clone the repository
git clone https://github.com/akashg524/tbd-data-visualization.git
cd tbd-data-visualization

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# Install package dependencies
pip install -e ".[dev]"

# Set PYTHONPATH and start the multi-protocol engine
$env:PYTHONPATH="backend"     # Windows PowerShell
# export PYTHONPATH="backend" # Linux / macOS
python backend/app/main.py
```

The servers will bind to the following ports:
- **FastAPI REST & OData:** `http://localhost:8000`
- **PGWire Gateway (Power BI DirectQuery):** `localhost:5433`
- **Arrow Flight Gateway:** `grpc://localhost:5005`

### Running Tests

The test suite contains **130 unit and integration tests** verifying connectors, query pushdown, caching, two-gate RLS, and protocol gateways:

```bash
# Run complete test suite
pytest tests/ -v

# Run code health and formatting checks
ruff check backend/ tests/
```

### Frontend Web SQL Studio

```bash
cd frontend
npm install
npm run dev
```

Navigate to `http://localhost:5173` to access the Monaco Web SQL Studio with catalog autocompletion and execution timeline.

### Docker & Kubernetes Deployment

```bash
# Full-stack local Docker container
docker compose up --build

# Production Kubernetes deployment via Helm chart
helm upgrade --install financial-data-hub helm/financial-data-hub \
  --namespace analytics --create-namespace \
  -f helm/financial-data-hub/values-production.yaml
```

The AKS Helm chart configures multi-port Kubernetes services, non-root Alpine containers (`appuser` UID 10001), horizontal pod autoscalers (HPA), and mounts an NVMe SSD `emptyDir` scratch volume at `/scratch` for DuckDB out-of-core spill joins.

---

## 📁 Project Structure

```
tbd-data-visualization/
├── backend/
│   └── app/
│       ├── api/               # REST API, Table Views, OData v4 endpoints
│       ├── auth/              # Entra ID SSO, RBAC, Two-Gate Policy Registry, Sentinel Audit
│       ├── cache.py           # ResultCache with security fingerprint isolation
│       ├── catalog.py         # UnifiedCatalogRegistry (3-part namespace)
│       ├── config.py          # Environment settings & Key Vault resolution
│       ├── connectors/        # Read-only connectors (Iceberg ADLS, Oracle, MSSQL, Azure SQL, Cosmos)
│       ├── engine.py          # DuckDB vectorized analytics engine
│       ├── federation/        # SQLParser, PushdownCompiler, ASTRewriter, FederatedExecutor
│       └── serving/           # PGWire (BuenaVista), Arrow Flight, Streaming Export
├── docs/                      # Architectural specs, UML diagrams & presentation slide decks
│   ├── ARCHITECTURE.md
│   └── presentation/
├── frontend/                  # React 18 + TypeScript + Vite Monaco Web Studio
│   └── src/components/       # SchemaTree, SqlEditor, ExplainTimeline, ResultsGrid, LaunchersBar
├── helm/                      # Production AKS Helm deployment manifests
├── tests/                     # 130 Pytest test suites across all components
├── pyproject.toml             # Python build & dependency specification
└── docker-compose.yml         # Container orchestration
```

---

## 💰 Commercial ROI & Comparison

| Dimension | In-House Hub (Built Solution) | Denodo Virtualization | Dremio Cloud | Traditional ETL Marts |
|---|---|---|---|---|
| **Software Licensing** | **$0 (100% Open Source Core)** | $200k – $500k / year | $100k+ Dremio Units | Heavy pipeline runtime costs |
| **Catalog Modification** | **Zero (100% Read-Only)** | Requires VQL modeling | Requires Iceberg catalog writes | High (Daily duplicate tables) |
| **Row-Level Security** | **Dynamic AST Rewrite (Two-Gate)** | Proprietary VQL wrappers | SQL UDF row policies | Power BI DAX RLS (brittle) |
| **Power BI DirectQuery** | **Native PGWire v3.0 (:5433)** | Custom Denodo connector | Dremio ODBC connector | Direct SQL Server / Lakehouse |
| **Join Engine** | **DuckDB C++ + NVMe SSD Spill** | JVM cluster execution | Arrow Gandiva C++ | Spark / Synapse clusters |
| **Audit & Compliance** | **Native Sentinel / Event Hub JSON** | Database server logs | Cloud audit logs | Fragmented pipeline logs |

**Estimated 3-Year Savings:** **$750,000+** in commercial licensing and redundant cloud storage fees.

---

## ✅ Verification & Quality Metrics

- **Total Test Cases:** 130 passing (`pytest tests/ -v`)
- **Code Linter Score:** 0 errors, 0 warnings (`ruff check backend/ tests/`)
- **Memory Safety:** 100% read-only upstream queries (`ApplicationIntent=ReadOnly`, zero locks)
- **Security Posture:** Strict fail-closed fallback (`1 = 0`) on missing user claims
- **Query Performance:** Sub-5ms response for cached dashboard queries, sub-2s for 10M-row federated joins
