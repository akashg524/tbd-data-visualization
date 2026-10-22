# Phase 1: High-Performance Read-Only Connectors & Iceberg Catalog — Research

## Standard Stack

| Layer | Library / Tool | Version | Role & Justification |
| :--- | :--- | :--- | :--- |
| **Credential Vault** | `azure-keyvault-secrets` + `azure-identity` | `^4.11` / `^1.26` | Resolves database passwords and storage keys from Azure Key Vault via `DefaultAzureCredential` (Managed Identity on AKS). Fallback to local `.env` mock for offline development. |
| **Lakehouse Catalog** | `pyiceberg` + `duckdb` (iceberg extension) | `^0.12` / `^1.5` | `pyiceberg` inspects Iceberg table metadata, manifests, and snapshots on ADLS Gen2 without listing directories. DuckDB executes vectorized C++ scans directly against the pruned Parquet byte ranges. |
| **Oracle Connector** | `oracledb` (Thin Mode) | `^26.0` | Pure Python thin-mode driver from Oracle. Eliminates the need to install or configure Oracle Instant Client binary C-libraries on Windows or Linux containers. Supports `read_only=True` session modes. |
| **SQL Server Connector**| `pymssql` / `SQLAlchemy` | `^2.4` / `^2.1` | Connects with `ApplicationIntent=ReadOnly` in connection string to route traffic to AlwaysOn readable secondary replicas. |
| **Azure SQL Connector** | `asyncpg` / `SQLAlchemy` | `^0.32` / `^2.1` | Native async connection pooling with read-only transaction defaults. |
| **Cosmos DB Connector** | `azure-cosmos` | `^4.17` | Official Azure Cosmos DB Python SDK with partition-key routing and schema sampling. |
| **Vector Engine** | `pyarrow` + `duckdb` | `^19.0` / `^1.5` | In-memory zero-copy columnar memory format. DuckDB attaches connectors and consumes Arrow RecordBatches natively. |

---

## Architecture Patterns

### 1. Pluggable Connector Interface
All connectors inherit from an abstract `BaseConnector`:
```python
class BaseConnector(ABC):
    @abstractmethod
    async def test_connection(self) -> ConnectionStatus: ...
    
    @abstractmethod
    async def introspect_schemas(self) -> list[str]: ...
    
    @abstractmethod
    async def introspect_tables(self, schema: str) -> list[TableMetadata]: ...
    
    @abstractmethod
    async def get_table_schema(self, schema: str, table: str) -> TableSchema: ...
    
    @abstractmethod
    async def execute_query(self, query: str, limit: int | None = None) -> pa.Table: ...
```

### 2. Strictly Enforced Read-Only Guardrails
Upstream systems are strictly read-only:
* **Oracle:** Execute `ALTER SESSION SET TRANSACTION READ ONLY` on connection checkout, preventing any `INSERT`, `UPDATE`, `DELETE`, or `MERGE` statement.
* **SQL Server:** Set `ApplicationIntent=ReadOnly` to ensure queries land on non-primary replicas; use `TRANSACTION ISOLATION LEVEL READ UNCOMMITTED` for non-blocking analytical scans.
* **DuckDB Iceberg Scanner:** Scans ADLS Parquet files in read-only binary mode (`r`).

### 3. Unified Schema Catalog Registry
A central thread-safe registry caches metadata for all registered datasources:
```
UnifiedCatalogRegistry
  ├── Namespace: "adls_iceberg" -> IcebergConnector
  │     └── Table: "trades" (columns, types, partition_keys)
  ├── Namespace: "oracle_onprem" -> OracleConnector
  │     └── Table: "counterparties" (columns, types, keys)
  ├── Namespace: "mssql_onprem" -> SQLServerConnector
  │     └── Table: "gl_accounts" (columns, types)
  └── Namespace: "cosmos_db" -> CosmosDBConnector
        └── Table: "audit_events" (columns, types, partition_key)
```

---

## Don't Hand-Roll

* **DO NOT write a custom Iceberg metadata parser:** Use `pyiceberg` and DuckDB's official `iceberg` extension (`SELECT * FROM iceberg_scan(...)`). Hand-rolling Avro/JSON manifest parsers will fail on schema evolution and partition transforms.
* **DO NOT hand-roll credential encryption:** Use `azure-identity` (`DefaultAzureCredential`) for cloud identity and `cryptography.fernet.Fernet` for local secret fallback.
* **DO NOT write custom database wire parsers:** Use standard drivers (`oracledb`, `pymssql`, `asyncpg`) and stream them directly into `pyarrow.Table`.
* **DO NOT require Oracle Instant Client binaries:** Rely strictly on `oracledb` thin mode (which speaks the Oracle Net protocol directly over TCP without external client DLLs/SOs).

---

## Common Pitfalls & How to Avoid Them

### 1. Oracle Thick vs. Thin Mode
* *Pitfall:* Attempting to call `oracledb.init_oracle_client()` requires proprietary C shared libraries (`oci.dll` or `libclntsh.so`), causing container build failures and Windows path headaches.
* *Solution:* Use default **Thin mode** (`oracledb.connect(...)` without calling `init_oracle_client`). Thin mode supports 100% of standard SQL execution, encryption, and read-only sessions without external binaries.

### 2. ADLS Gen2 Iceberg Authentication
* *Pitfall:* Attempting to query ADLS Gen2 via DuckDB `httpfs` without setting Azure storage credentials fails with `403 Forbidden`.
* *Solution:* DuckDB requires `SET azure_storage_connection_string='...'` or setting `azure_account_name` and `azure_account_key` / token. The connector manager must inject these session parameters into the DuckDB connection upon startup.

### 3. Cosmos DB Request Unit (RU) Exhaustion
* *Pitfall:* Running `SELECT * FROM c` across an entire Cosmos DB container triggers a high-cost multi-partition fanout scan.
* *Solution:* The Cosmos DB introspector must inspect container partition key definition (`/id` or `/portfolioId`) and sample only `TOP 50` documents with `max_item_count=50` to derive schema without burning RUs.

### 4. SQL Server Application Intent
* *Pitfall:* Connecting to SQL Server without `ApplicationIntent=ReadOnly` routes queries to the primary write replica, creating lock contention with OLTP workloads.
* *Solution:* Explicitly inject `ApplicationIntent=ReadOnly` into the connection parameters.

---

## Code Examples

### A. Oracle Read-Only Thin Connection
```python
import oracledb

async def get_oracle_connection(config: OracleConfig):
    # Pure Python thin mode (no Instant Client needed)
    conn = oracledb.connect(
        user=config.username,
        password=config.password,
        dsn=f"{config.host}:{config.port}/{config.service_name}",
    )
    # Enforce read-only transaction mode
    cursor = conn.cursor()
    cursor.execute("ALTER SESSION SET TRANSACTION READ ONLY")
    return conn
```

### B. DuckDB Native Iceberg Scan
```python
import duckdb

def scan_iceberg_table(conn: duckdb.DuckDBPyConnection, metadata_file_path: str):
    return conn.sql(f"SELECT * FROM iceberg_scan('{metadata_file_path}')")
```

### C. Azure Key Vault Resolver with Mock Fallback
```python
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import os

class CredentialVault:
    def __init__(self, vault_url: str | None = None):
        self.vault_url = vault_url
        self._client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential()) if vault_url else None

    def get_secret(self, secret_name: str) -> str:
        if self._client:
            return self._client.get_secret(secret_name).value
        # Local development / CI fallback
        return os.environ.get(secret_name.upper().replace("-", "_"), "")
```

---

## Validation Architecture

### Test Infrastructure
- **Framework**: `pytest` 8.4+ with `pytest-asyncio`
- **Configuration**: `pyproject.toml` (`[tool.pytest.ini_options]`)
- **Quick Run Command**: `.\.venv\Scripts\pytest.exe tests/ -q`
- **Full Suite Command**: `.\.venv\Scripts\pytest.exe tests/ -v --cov=backend/app`
- **Estimated Runtime**: ~5 seconds

### Automated Verification Targets
1. `tests/test_vault.py`: Secret resolution, cache hits, local env fallback.
2. `tests/test_base_connector.py`: Abstract interface compliance and model serialization.
3. `tests/test_iceberg_adls.py`: Iceberg manifest inspection, schema discovery, and DuckDB `iceberg_scan()`.
4. `tests/test_cosmos.py`: Cosmos DB container discovery, partition key mapping, and schema sampling.
5. `tests/test_relational_connectors.py`: Oracle thin-mode read-only enforcement, SQL Server `ApplicationIntent=ReadOnly`, and Arrow table conversions.
6. `tests/test_catalog.py`: Unified namespace (`catalog.schema.table`) registration and path resolution.

