/**
 * Shared TypeScript types for the data visualization platform.
 */

/** A configured datasource connection. */
export interface Datasource {
  id: string
  name: string
  type: DatasourceType
  host?: string
  port?: number
  database?: string
  uri?: string
  created_at: string
}

export type DatasourceType =
  | 'adls_iceberg'
  | 'oracle'
  | 'sqlserver'
  | 'cosmos'
  | 'postgresql'
  | 'mysql'
  | 'mssql'
  | 'sqlite'
  | 'clickhouse'
  | 'snowflake'
  | 'bigquery'
  | 'mongodb'
  | 'elasticsearch'
  | 's3'
  | 'azure_blob'
  | 'gcs'
  | 'local_file'
  | 'rest_api'

/** Column metadata from schema introspection. */
export interface ColumnInfo {
  name: string
  type: string
  nullable: boolean
}

/** Table metadata from schema introspection. */
export interface TableInfo {
  schema: string
  name: string
  columns: ColumnInfo[]
  row_count?: number
}

/** Summary of a discovered catalog table view. */
export interface ViewSummary {
  catalog: string
  schema_name: string
  table_name: string
  full_path: string
  format?: string | null
  url: string
}

export interface ViewListResponse {
  count: number
  views: ViewSummary[]
}

/** Fine-grained execution metrics returned by FederatedExecutor. */
export interface ExecutionMetrics {
  planning_ms: number
  subquery_ms: Record<string, number>
  join_ms: number
  total_ms: number
  row_count: number
  cache_hit: boolean
  scratch_spill_enabled: boolean
}

export interface QueryRequest {
  sql: string
  limit?: number
}

export interface QueryResponse {
  columns: string[]
  rows: (string | number | boolean | null)[][]
  row_count: number
  metrics?: ExecutionMetrics | null
}

export interface HealthResponse {
  status: string
  detail?: string
}

/** Hierarchical catalog tree structures for UI navigation. */
export interface SchemaNode {
  name: string
  tables: ViewSummary[]
}

export interface DatasourceGroup {
  name: string
  type: string
  schemas: Record<string, SchemaNode>
}
