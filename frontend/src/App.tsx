import { useEffect, useState } from 'react'

interface HealthStatus {
  api: 'checking' | 'ok' | 'error'
  engine: 'checking' | 'ready' | 'not_ready'
}

function App() {
  const [health, setHealth] = useState<HealthStatus>({
    api: 'checking',
    engine: 'checking',
  })

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const [healthRes, readyRes] = await Promise.all([
          fetch('/api/v1/health'),
          fetch('/api/v1/ready'),
        ])
        const healthData = await healthRes.json()
        const readyData = await readyRes.json()
        setHealth({
          api: healthData.status === 'ok' ? 'ok' : 'error',
          engine: readyData.status === 'ready' ? 'ready' : 'not_ready',
        })
      } catch {
        setHealth({ api: 'error', engine: 'not_ready' })
      }
    }
    checkHealth()
  }, [])

  const statusColor = (status: string) => {
    if (status === 'ok' || status === 'ready') return 'text-emerald-400'
    if (status === 'checking') return 'text-amber-400 animate-pulse'
    return 'text-red-400'
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-primary)]">
      <div className="w-full max-w-lg rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-8 shadow-2xl">
        <h1 className="mb-2 text-3xl font-bold tracking-tight text-white">
          TBD Data Visualization
        </h1>
        <p className="mb-6 text-sm text-[var(--color-text-secondary)]">
          Enterprise Financial Analytics Platform
        </p>

        <div className="space-y-3 rounded-lg bg-[var(--color-bg-secondary)] p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-[var(--color-text-secondary)]">API Server</span>
            <span className={`text-sm font-medium ${statusColor(health.api)}`}>
              ● {health.api}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-[var(--color-text-secondary)]">Analytics Engine</span>
            <span className={`text-sm font-medium ${statusColor(health.engine)}`}>
              ● {health.engine}
            </span>
          </div>
        </div>

        <p className="mt-6 text-xs text-[var(--color-text-secondary)]">
          Tooling ready — FastAPI + DuckDB + React + Vite + Tailwind CSS
        </p>
      </div>
    </div>
  )
}

export default App
