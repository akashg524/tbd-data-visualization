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

/** Supported chart types for financial data. */
export type ChartType =
  | 'line'
  | 'area'
  | 'bar'
  | 'candlestick'
  | 'scatter'
  | 'heatmap'
  | 'treemap'
  | 'waterfall'
  | 'donut'
  | 'table'
