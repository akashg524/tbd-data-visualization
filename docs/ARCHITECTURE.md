# Enterprise Federated Semantic Data Hub & Governance Architecture

This document provides complete, presentation-grade architecture blueprints, UML diagrams, sequence flows, and infographic summaries for the **Federated Financial Data Hub & Dynamic Governance Layer**.

---

## 1. High-Level System Architecture

The platform acts as a zero-ETL federated semantic query layer connecting **10 TB – 100 TB of heterogeneous, read-only financial data** across cloud and on-premises systems directly into Power BI, Excel, and analytical clients without commercial virtualization licensing fees.

```mermaid
flowchart TD
    subgraph Clients["Consumption Layer (Power BI, Excel, Web Studio)"]
        PBI_DQ["Power BI Desktop / Service (DirectQuery via PostgreSQL :5433)"]
        PBI_IMP["Power BI Scheduled Import (Arrow Flight :5005 / OData :8000)"]
        EXCEL["Microsoft Excel (OData v4 Feed / CSV Stream)"]
        STUDIO["Internal Monaco Web SQL Studio (React 18 + Vite)"]
    end

    subgraph ServingGateways["Multi-Protocol Serving Gateway Layer"]
        PGWIRE["PostgreSQL Wire Protocol Gateway (BuenaVista v3.0 :5433)"]
        FLIGHT["Apache Arrow Flight gRPC Server (Multi-GB/s Columnar :5005)"]
        REST_API["FastAPI REST Endpoints (/api/v1/query, /views, /export)"]
        ODATA["OData v4 Protocol Engine (/api/v1/odata/$metadata, entity sets)"]
    end

    subgraph SecurityLayer["Enterprise Governance & Two-Gate Policy Engine"]
        ENTRA["Microsoft Entra ID (Azure AD) JWT RS256 Verification"]
        GATE1["Gate 1: Coarse-Grained Table RBAC (Allowed Roles Validator)"]
        GATE2["Gate 2: Fine-Grained Dynamic RLS & ACL Predicate Synthesizer"]
        REWRITER["SQLGlot AST Rewriter (Alias Qualification & Fail-Closed 1=0)"]
        AUDIT["SOX/FINRA/Sentinel Structured Audit Logger (Event Hub / Structlog)"]
    end

    subgraph SpeedAndExecution["Federated Planning & Execution Engine"]
        CACHE["Two-Tier Result & Dimension Cache (Isolated by Security Fingerprint)"]
        PARSER["SQL Parser & Pushdown Decomposer (SQLGlot AST)"]
        PUSHDOWN["Native Pushdown Compilers (Oracle, SQL Server, Cosmos SQL)"]
        DUCKDB["DuckDB In-Memory Vectorized Hash Joiner (Arrow Batch Streaming)"]
        SPILL["Local NVMe SSD Scratch Store (/scratch for Multi-GB Spills)"]
    end

    subgraph DataSources["Read-Only Upstream Financial Data Sources"]
        ADLS["ADLS Gen2 Azure Data Lake (Apache Iceberg / Parquet)"]
        ORACLE["On-Premises Oracle 19c (Risk DW, Read-Only Replicas)"]
        MSSQL["On-Premises SQL Server (Trade Ledger, Read-Only Intent)"]
        AZSQL["Azure SQL Database (Reference Data & Account Masters)"]
        COSMOS["Azure Cosmos DB (High-Frequency Market Ticks, Partition Keys)"]
    end

    %% Client to Gateway connections
    PBI_DQ -->|TCP 5433| PGWIRE
    PBI_IMP -->|gRPC 5005| FLIGHT
    EXCEL -->|HTTP 8000| ODATA
    STUDIO -->|HTTP / JSON| REST_API

    %% Gateway to Security & Execution
    PGWIRE --> ENTRA
    FLIGHT --> ENTRA
    REST_API --> ENTRA
    ODATA --> ENTRA

    ENTRA --> GATE1
    GATE1 -->|Permission Check| GATE2
    GATE2 -->|AST Rewrite| REWRITER
    REWRITER --> AUDIT
    REWRITER --> CACHE

    CACHE -->|Cache Miss| PARSER
    PARSER --> PUSHDOWN
    PUSHDOWN -->|Parallel Pushdown Subqueries| DataSources

    DataSources -->|Arrow Record Batches| DUCKDB
    DUCKDB -.->|Out-of-Core Spill| SPILL
    DUCKDB --> CACHE
    CACHE -->|Secured Arrow Table| ServingGateways
```

---

## 2. Two-Gate Security & Dynamic RLS Architecture

```mermaid
flowchart LR
    subgraph Input["User Request"]
        REQ["SQL Query + Entra ID JWT Bearer Token"]
    end

    subgraph AuthClaimExtraction["Identity Resolution"]
        TOKEN["JWT Claims Extraction"]
        CTX["SecurityContext:\n• user_id: 'trader1'\n• roles: ['Trader']\n• trading_desks: ['FX']\n• regions: ['US']\n• SHA-256 Fingerprint"]
    end

    subgraph Gate1["Gate 1: Coarse-Grained Table RBAC"]
        TABLE_CHECK{"User has role\nfor table?"}
        DENY_403["Throw PermissionError\n(HTTP 403 Forbidden)"]
    end

    subgraph Gate2["Gate 2: Dynamic RLS AST Rewrite"]
        ADMIN_CHECK{"ComplianceAdmin\nor SecurityAdmin?"}
        BYPASS["Bypass RLS\n(Raw Unrestricted SQL)"]
        EMPTY_CHECK{"Has any ACL\nclaim?"}
        FAIL_CLOSED["Inject 1 = 0\n(Fail-Closed 0 Rows)"]
        PRED_SYNTH["Synthesize Predicates:\n• t.desk_code = 'FX'\n• t.region_id IN (1)"]
    end

    subgraph Output["Output SQL"]
        SECURED_SQL["Secured AST SQL to Planner\n+ Structured Audit Log Entry"]
    end

    REQ --> TOKEN --> CTX
    CTX --> TABLE_CHECK
    TABLE_CHECK -->|No| DENY_403
    TABLE_CHECK -->|Yes| ADMIN_CHECK
    ADMIN_CHECK -->|Yes| BYPASS --> SECURED_SQL
    ADMIN_CHECK -->|No| EMPTY_CHECK
    EMPTY_CHECK -->|No claims on governed table| FAIL_CLOSED --> SECURED_SQL
    EMPTY_CHECK -->|Valid claims| PRED_SYNTH --> SECURED_SQL
```

---

## 3. UML Class Diagram: Governance, Federation & Serving

```mermaid
classDiagram
    class SecurityContext {
        +str user_id
        +str username
        +list~str~ roles
        +list~str~ groups
        +list~str~ trading_desks
        +list~str~ regions
        +list~str~ allowed_accounts
        +str fingerprint
        +has_any_role(required_roles) bool
        +is_exempt(exempt_roles) bool
        +get_effective_claims(claim_field) list
    }

    class TableSecurityPolicy {
        +str table_pattern
        +GateType gate
        +list~str~ required_roles
        +list~str~ exempt_roles
        +list~AclRule~ acl_rules
        +str acl_combination
        +bool fail_closed
    }

    class AclRule {
        +str claim_field
        +str target_column
        +PolicyStrategy strategy
        +dict lookup_map
        +str relationship_query
    }

    class GovernancePolicyRegistry {
        -list~TableSecurityPolicy~ _policies
        +register_policy(policy) void
        +get_policy_for_table(table_name) TableSecurityPolicy
    }

    class ASTRewriter {
        +rewrite(sql, context, catalog, registry)* tuple~str, list~
    }

    class AuditLogger {
        +log_query_execution(context, original_sql, secured_sql, applied_rls, duration_ms, row_count, protocol)* dict
        +log_export_event(context, format, row_count, filename, protocol)* dict
    }

    class FederatedExecutor {
        -UnifiedCatalogRegistry catalog
        -ResultCache cache
        +execute(sql, limit, scratch_spill, security_context, protocol) tuple~Table, ExecutionMetrics~
    }

    class SQLParser {
        +parse(sql, catalog)* ParsedQuery
    }

    class ResultCache {
        -CacheBackend backend
        +compute_fingerprint(sql, security_fingerprint)* str
        +get(sql, security_fingerprint) Table
        +set(sql, table, ttl_seconds, security_fingerprint) void
    }

    SecurityContext <-- ASTRewriter : consumes
    TableSecurityPolicy *-- AclRule : aggregates
    GovernancePolicyRegistry o-- TableSecurityPolicy : manages
    ASTRewriter --> GovernancePolicyRegistry : queries
    FederatedExecutor --> ASTRewriter : invokes
    FederatedExecutor --> AuditLogger : emits to
    FederatedExecutor --> ResultCache : queries/stores
    FederatedExecutor --> SQLParser : compiles with
```

---

## 4. Sequence Diagram: End-to-End Secured Analytical Query Execution

```mermaid
sequenceDiagram
    autonumber
    actor Analyst as Power BI / Web Studio
    participant Gateway as Serving Gateway (REST / PGWire / Flight)
    participant Auth as Entra ID & RBAC
    participant Rewriter as SQLGlot AST Rewriter
    participant Cache as Result Cache (Fingerprinted)
    participant Planner as Query Planner & Pushdown Compiler
    participant ADLS as ADLS Gen2 Iceberg
    participant Oracle as Oracle Risk DW
    participant DuckDB as DuckDB Vectorized Hash Joiner
    participant Audit as SOX/FINRA Audit Logger

    Analyst->>Gateway: Submit Query (SQL + JWT Bearer)
    Gateway->>Auth: Authenticate & Build SecurityContext
    Auth-->>Gateway: SecurityContext(roles=['Trader'], desks=['FX'], regions=['US'])

    Gateway->>Rewriter: ASTRewriter.rewrite(sql, sec_context)
    Note over Rewriter: Gate 1: Check Table RBAC<br/>Gate 2: Inject WHERE t.desk_code = 'FX' AND t.region_id IN (1)
    Rewriter-->>Gateway: secured_sql, applied_rls_filters

    Gateway->>Cache: Check Cache (hash(secured_sql + sec_fingerprint))
    alt Cache Hit (<5ms)
        Cache-->>Gateway: Return Cached Arrow Table
    else Cache Miss
        Gateway->>Planner: Parse & Compile Subqueries (secured_sql)
        Planner-->>Gateway: ExecutionPlan(ADLS Subquery, Oracle Subquery, Join Spec)

        par Parallel Subquery Pushdown
            Gateway->>ADLS: Scan Iceberg Parquet (Filter: amount > 1000 AND desk_code = 'FX')
            ADLS-->>DuckDB: Stream Arrow RecordBatch [Trades]
        and
            Gateway->>Oracle: Pushdown SQL (SELECT id, name FROM counterparties WHERE region_id IN (1))
            Oracle-->>DuckDB: Stream Arrow RecordBatch [Counterparties]
        end

        Gateway->>DuckDB: Execute Vectorized Hash Join (trades.counterparty_id = counterparties.id)
        DuckDB-->>Gateway: Result Arrow Table (Aggregated & Sorted)

        Gateway->>Cache: Store Result in Cache (TTL=300s, key=sec_fingerprint)
    end

    Gateway->>Audit: Emit analytical_query_execution event (Sentinel/Event Hub)
    Gateway-->>Analyst: Stream Columnar Results (Arrow / PGWire Tuples / CSV)
```

---

## 5. Sequence Diagram: Data Export Lifecycle with Compliance Audit

```mermaid
sequenceDiagram
    autonumber
    actor Analyst as Financial Analyst
    participant ExportAPI as REST Export API (/api/v1/export/query)
    participant Executor as FederatedExecutor
    participant Rewriter as ASTRewriter
    participant Audit as AuditLogger (Sentinel Integration)

    Analyst->>ExportAPI: GET /query?sql=...&format=parquet&filename=q3_trades
    ExportAPI->>Executor: execute(sql, security_context, protocol="Export")
    Executor->>Rewriter: rewrite(sql, security_context)
    Rewriter-->>Executor: secured_sql (RLS applied)
    Executor->>Executor: Execute query & collect PyArrow Table
    Executor-->>ExportAPI: PyArrow Table (N rows)
    ExportAPI->>Audit: log_export_event(user, format="parquet", rows=N, filename="q3_trades.parquet")
    Note over Audit: Emits structured event to Microsoft Sentinel & local audit log
    ExportAPI-->>Analyst: 200 OK + Streamed application/vnd.apache.parquet attachment
```

---

## 6. State Diagram: Query Security Lifecycle

```mermaid
stateDiagram-v2
    [*] --> InboundQuery: Client connects (REST / PGWire / Flight)
    InboundQuery --> Authenticating: Extract JWT Token

    state Authenticating {
        [*] --> TokenVerify: Cryptographic RS256 JWKS Check
        TokenVerify --> ExtractClaims: Extract roles, desks, regions, accounts
        ExtractClaims --> FingerprintGen: Compute deterministic SHA-256 hash
    }

    Authenticating --> Gate1_RBAC: SecurityContext Resolved
    Gate1_RBAC --> Unauthorized403: User lacks table roles
    Unauthorized403 --> AuditLogEmission: Log FAILED Security Denial
    AuditLogEmission --> [*]: Terminate with 403 Forbidden

    Gate1_RBAC --> Gate2_RLS: Authorized on all tables
    state Gate2_RLS {
        [*] --> AdminCheck
        AdminCheck --> Unrestricted: Role in [ComplianceAdmin, SecurityAdmin]
        AdminCheck --> CheckClaims: Regular Analyst / Trader
        CheckClaims --> FailClosedZero: No matching claims on governed table
        CheckClaims --> InjectPredicates: Claims match policy rules
    }

    Gate2_RLS --> CacheLookup: Query Secured
    CacheLookup --> CacheHit: Key found for security fingerprint
    CacheLookup --> PlanAndPushdown: Cache miss

    PlanAndPushdown --> ParallelFetch: Dispatch to ADLS / Oracle / MSSQL
    ParallelFetch --> InMemoryJoin: Stream Arrow batches into DuckDB
    InMemoryJoin --> CachePopulate: Store in ResultCache
    CachePopulate --> ServingFormat: Serialize to PGWire / Flight / CSV / Parquet
    CacheHit --> ServingFormat

    ServingFormat --> AuditLogEmission: Log SUCCESS Analytical Query Event
    AuditLogEmission --> ClientDelivered: Complete
    ClientDelivered --> [*]
```

---

## 7. Architectural Comparison: In-House Engine vs. Commercial Alternatives

| Dimension | In-House Hub (Built Solution) | Denodo / Dremio | Direct Power BI Import (ETL) |
|---|---|---|---|
| **Licensing Cost** | **\$0 (100% Open Source: DuckDB, PyArrow, FastAPI, SQLGlot)** | \$150k – \$500k+ / year recurring core licensing | Power BI Premium / Fabric capacity costs |
| **Catalog Modification** | **Zero Modification** (Read-Only metadata & data lake inspection) | Requires catalog registration & view publishing | Requires heavy scheduled ingestion pipelines |
| **Row-Level Security** | **Dynamic AST Rewrite** (Two-gate coarse RBAC + fine ACL injection) | Custom proprietary VQL security wrappers | Static Power BI DAX RLS (brittle at 100 TB scale) |
| **Memory Architecture** | **In-Memory Arrow Streaming** + NVMe SSD local spill joins | Heavy JVM server clusters (GBs of overhead) | In-memory VertiPaq limited by RAM capacity |
| **Serving Interfaces** | **PGWire (:5433), Arrow Flight (:5005), OData, REST, Monaco Studio** | Proprietary JDBC/ODBC drivers required | Standard Power BI Desktop only |
| **Regulatory Audit** | **SOX/FINRA native JSON** direct to Microsoft Sentinel & Event Hub | Clunky local syslog / database audit logs | Activity logs with limited query visibility |
