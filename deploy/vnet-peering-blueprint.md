# Azure VNet Peering & On-Premises Hybrid Connectivity Blueprint

## 1. Architectural Overview

The Federated Semantic Financial Data Hub is deployed on Azure Kubernetes Service (AKS) within an isolated spoke virtual network (`vnet-aks-spoke`). It federates queries across:
1. **Azure Cloud-Native Lakehouses**: ADLS Gen2 Iceberg, Cosmos DB, and Azure SQL via Azure Private Endpoints (`privatelink`).
2. **On-Premises Relational Databases**: Oracle Exadata / DB servers (Port 1521) and Microsoft SQL Server clusters (Port 1433) routed through an enterprise Hub VNet via Azure ExpressRoute / VPN Gateway.

```
                              Corporate WAN / DirectQuery / Flight Clients
                                                 │
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │    Azure Virtual WAN / Hub VNet       │
                             │            10.0.0.0/8                 │
                             │  ┌─────────────────────────────────┐  │
                             │  │ Azure ExpressRoute Gateway      │  │
                             │  │ / Site-to-Site VPN Gateway      │  │
                             │  └────────────────┬────────────────┘  │
                             └───────────────────┼───────────────────┘
                                                 │
                             ┌───────────────────┴───────────────────┐
                             │       Bi-Directional VNet Peering     │
                             │       (AllowGatewayTransit=true)      │
                             └───────────────────┬───────────────────┘
                                                 │
    ┌────────────────────────────────────────────▼────────────────────────────────────────────┐
    │  AKS Spoke Virtual Network: 10.240.0.0/16                                               │
    │                                                                                         │
    │  ┌───────────────────────────┐         ┌──────────────────────────────────────────────┐ │
    │  │ aks-system-subnet         │         │ aks-data-hub-nodepool-subnet                 │ │
    │  │ 10.240.0.0/24             │         │ 10.240.4.0/22 (NVMe Scratch Nodes)           │ │
    │  │ - CoreDNS, Cilium CNI     │         │ - data-hub-backend (DuckDB/Arrow/Buenavista) │ │
    │  │ - Ingress Controllers     │         │ - Local /scratch emptyDir NVMe Volume        │ │
    │  └───────────────────────────┘         └──────────────────────┬───────────────────────┘ │
    │                                                               │                         │
    │  ┌────────────────────────────────────────────────────────────┼───────────────────────┐ │
    │  │ privatelink-subnet: 10.240.8.0/24                          │                       │ │
    │  │ ┌──────────────────────┐ ┌──────────────────────┐ ┌────────┴─────────────┐         │ │
    │  │ │ ADLS Gen2 Blob/DFS   │ │ Azure SQL Database   │ │ Azure Cosmos DB      │         │ │
    │  │ │ Private Endpoint    │ │ Private Endpoint    │ │ Private Endpoint     │         │ │
    │  │ └──────────────────────┘ └──────────────────────┘ └──────────────────────┘         │ │
    │  └────────────────────────────────────────────────────────────────────────────────────┘ │
    └────────────────────────────────────────────┬────────────────────────────────────────────┘
                                                 │
                                     ExpressRoute Circuit (10 Gbps)
                                                 │
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │       On-Premises Corporate DC        │
                             │  ┌─────────────────────────────────┐  │
                             │  │ Oracle RAC Cluster (Port 1521)  │  │
                             │  │ SQL Server AG (Port 1433)       │  │
                             │  └─────────────────────────────────┘  │
                             └───────────────────────────────────────┘
```

---

## 2. VNet Topology & Address Allocation

| Network Zone | Resource Name | CIDR Prefix | Purpose |
|--------------|---------------|-------------|---------|
| **Hub VNet** | `vnet-hub-prod` | `10.0.0.0/8` | Central transit network housing ExpressRoute Gateways and Azure Firewall |
| **AKS Spoke VNet** | `vnet-aks-spoke` | `10.240.0.0/16` | Isolated container runtime network |
| **System Subnet** | `snet-aks-system` | `10.240.0.0/24` | AKS control plane pods and ingress ingress-nginx controllers |
| **Worker Subnet** | `snet-aks-compute` | `10.240.4.0/22` | Storage-optimized Azure VMs (e.g. `Standard_L8s_v3` with direct-attached NVMe SSDs) |
| **Private Link Subnet**| `snet-privatelink` | `10.240.8.0/24` | Private endpoints for Azure PaaS data stores |

---

## 3. Network Security Group (NSG) Rules: `nsg-aks-compute`

Strict egress and ingress filtering ensures zero data leakage and enforces read-only pushdowns:

### Inbound Rules
| Priority | Name | Protocol | Source | Destination | Port | Action |
|----------|------|----------|--------|-------------|------|--------|
| 100 | `Allow_Ingress_HTTP` | TCP | `10.240.0.0/24` | `10.240.4.0/22` | `8000` | Allow |
| 110 | `Allow_PowerBI_PGWire`| TCP | `10.0.0.0/8` (Corporate WAN)| `10.240.4.0/22` | `5433` | Allow |
| 120 | `Allow_Flight_gRPC` | TCP | `10.0.0.0/8` (Corporate WAN)| `10.240.4.0/22` | `5005` | Allow |
| 4096 | `Deny_All_Other_Inbound` | Any | Any | Any | Any | Deny |

### Outbound Rules
| Priority | Name | Protocol | Destination | Port | Purpose | Action |
|----------|------|----------|-------------|------|---------|--------|
| 200 | `Allow_OnPrem_Oracle` | TCP | `10.100.0.0/16` (DC Oracle) | `1521` | Oracle thin client pushdown | Allow |
| 210 | `Allow_OnPrem_MSSQL` | TCP | `10.100.0.0/16` (DC MSSQL) | `1433` | SQL Server pymssql pushdown | Allow |
| 220 | `Allow_PrivateLink_Storage` | TCP | `10.240.8.0/24` (Private Link) | `443` | ADLS Gen2 Iceberg & Cosmos DB | Allow |
| 230 | `Allow_Entra_JWKS` | TCP | AzureActiveDirectory Tag | `443` | Entra ID token discovery keys | Allow |
| 4096 | `Deny_Direct_Internet_Outbound` | Any | Internet | Any | Prevent analytical data exfiltration | Deny |

---

## 4. Azure Private DNS Zones

Private resolution is mapped to the spoke VNet to ensure zero public IP exposure:
- `privatelink.blob.core.windows.net` -> A Record pointing to `10.240.8.10`
- `privatelink.dfs.core.windows.net`  -> A Record pointing to `10.240.8.11`
- `privatelink.documents.azure.com`   -> A Record pointing to `10.240.8.12`
- `privatelink.database.windows.net`  -> A Record pointing to `10.240.8.13`

---

## 5. Local NVMe Scratch Disk & DuckDB Out-of-Core Spill Configuration

When running federated joins across 10 TB - 100 TB datasets:
1. AKS nodes use storage-optimized VM SKUs (e.g., `Standard_L16s_v3` with 1.9 TB local NVMe SSD).
2. The NVMe drive is formatted and presented to Kubernetes as an `emptyDir` scratch volume.
3. In `deployment-backend.yaml`, `scratch-volume` is mounted at `/scratch` with `sizeLimit: 100Gi`.
4. The environment variable `DUCKDB_TEMP_DIRECTORY=/scratch` instructs DuckDB's buffer manager to spill intermediate hash join partitions directly to NVMe SSD at >2 GB/s write throughput whenever queries exceed physical RAM.
