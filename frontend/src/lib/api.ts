const API_BASE = '/api/v1'

export interface QueryRequest {
  sql: string
  limit?: number
}

export interface QueryResponse {
  columns: string[]
  rows: unknown[][]
  row_count: number
}

export interface HealthResponse {
  status: string
  detail?: string
}

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
