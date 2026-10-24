import type {
  HealthResponse,
  QueryRequest,
  QueryResponse,
  ViewListResponse,
} from './types'

const API_BASE = '/api/v1'

/**
 * Execute a SQL query against the backend analytics engine.
 */
export async function executeQuery(request: QueryRequest): Promise<QueryResponse> {
  const res = await fetch(`${API_BASE}/query/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail || 'Query execution failed')
  }
  return res.json()
}

/**
 * Fetch all available catalog views.
 */
export async function fetchViews(): Promise<ViewListResponse> {
  const res = await fetch(`${API_BASE}/views`)
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail || 'Failed to fetch catalog views')
  }
  return res.json()
}

/**
 * Get direct download URL for Power BI .pbids file.
 */
export function getPbidsUrl(port: number = 5433, database: string = 'federated'): string {
  return `${API_BASE}/launchers/pbids?port=${port}&database=${encodeURIComponent(database)}`
}

/**
 * Get direct download URL for Microsoft Excel .odc connection file.
 */
export function getOdcUrl(schema?: string, table?: string): string {
  if (schema && table) {
    return `${API_BASE}/launchers/odc?schema=${encodeURIComponent(schema)}&table=${encodeURIComponent(table)}`
  }
  return `${API_BASE}/launchers/odc`
}

/**
 * Get direct URL for streaming query export.
 */
export function getExportUrl(
  sql: string,
  format: 'csv' | 'parquet' | 'ndjson',
  filename: string = 'export'
): string {
  const params = new URLSearchParams({
    sql,
    format,
    filename,
  })
  return `${API_BASE}/export/query?${params.toString()}`
}

/**
 * Check API server health.
 */
export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`)
  return res.json()
}

/**
 * Check analytics engine readiness.
 */
export async function checkReady(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/ready`)
  return res.json()
}
