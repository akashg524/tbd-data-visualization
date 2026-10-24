import { useEffect, useState } from 'react'
import {
  Activity,
  AlertCircle,
  Database,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { ExplainTimeline } from './components/ExplainTimeline'
import { LaunchersBar } from './components/LaunchersBar'
import { ResultsGrid } from './components/ResultsGrid'
import { SchemaTree } from './components/SchemaTree'
import { SqlEditor } from './components/SqlEditor'
import { checkHealth, checkReady, executeQuery, fetchViews } from './lib/api'
import type { ExecutionMetrics, ViewSummary } from './lib/types'

const DEFAULT_SAMPLE_SQL = `-- Cross-source federated analytical query
-- Joins 10 TB ADLS Iceberg trades with on-premises Oracle counterparties
SELECT 
  t.trade_id,
  c.name AS counterparty_name,
  c.country,
  t.amount,
  t.status
FROM adls_lake.equity.trades t
JOIN oracle_dw.risk.counterparties c ON t.counterparty_id = c.id
ORDER BY t.amount DESC
LIMIT 50;`

export function App() {
  const [health, setHealth] = useState<{ api: string; engine: string }>({
    api: 'checking',
    engine: 'checking',
  })
  const [views, setViews] = useState<ViewSummary[]>([])
  const [loadingViews, setLoadingViews] = useState(true)

  const [sql, setSql] = useState<string>(DEFAULT_SAMPLE_SQL)
  const [isExecuting, setIsExecuting] = useState(false)
  const [columns, setColumns] = useState<string[]>([])
  const [rows, setRows] = useState<(string | number | boolean | null)[][]>([])
  const [metrics, setMetrics] = useState<ExecutionMetrics | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Initial health check and catalog discovery
  useEffect(() => {
    const init = async () => {
      try {
        const [h, r] = await Promise.all([checkHealth(), checkReady()])
        setHealth({
          api: h.status === 'ok' ? 'online' : 'degraded',
          engine: r.status === 'ready' ? 'ready' : 'not_ready',
        })
      } catch {
        setHealth({ api: 'offline', engine: 'offline' })
      }

      try {
        setLoadingViews(true)
        const viewData = await fetchViews()
        setViews(viewData.views || [])
      } catch (err: any) {
        console.warn('Catalog discovery notice:', err.message)
      } finally {
        setLoadingViews(false)
      }
    }
    init()
  }, [])

  const handleExecute = async () => {
    if (!sql.trim()) return
    setIsExecuting(true)
    setErrorMessage(null)

    try {
      const res = await executeQuery({ sql: sql.trim(), limit: 1000 })
      setColumns(res.columns || [])
      setRows(res.rows || [])
      setMetrics(res.metrics || null)
    } catch (err: any) {
      setErrorMessage(err.message || 'Query execution failed')
    } finally {
      setIsExecuting(false)
    }
  }

  const handleSelectTable = (tablePath: string) => {
    setSql(`SELECT * FROM ${tablePath} LIMIT 50;`)
  }

  return (
    <div className="flex flex-col h-screen w-screen bg-zinc-950 text-zinc-100 overflow-hidden font-sans">
      {/* Top Navigation Bar */}
      <header className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800 z-20">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-tight text-white leading-tight">
                Federated Financial Data Hub
              </h1>
              <p className="text-[10px] text-zinc-400 leading-tight">
                Semantic Speed Layer &amp; Power BI Studio
              </p>
            </div>
          </div>
        </div>

        {/* System & Identity Indicators */}
        <div className="flex items-center gap-2.5">
          {/* API Health */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-950 border border-zinc-800 rounded-full text-[11px]">
            <Activity
              className={`h-3 w-3 ${
                health.api === 'online' ? 'text-emerald-400' : 'text-amber-400 animate-pulse'
              }`}
            />
            <span className="text-zinc-400">API:</span>
            <span
              className={`font-semibold capitalize ${
                health.api === 'online' ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {health.api}
            </span>
          </div>

          {/* DuckDB Engine Health */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-950 border border-zinc-800 rounded-full text-[11px]">
            <Database
              className={`h-3 w-3 ${
                health.engine === 'ready' ? 'text-sky-400' : 'text-amber-400 animate-pulse'
              }`}
            />
            <span className="text-zinc-400">DuckDB:</span>
            <span
              className={`font-semibold capitalize ${
                health.engine === 'ready' ? 'text-sky-400' : 'text-amber-400'
              }`}
            >
              {health.engine}
            </span>
          </div>

          {/* Entra ID User Role Pill */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-950/60 border border-emerald-800/80 rounded-full text-[11px] text-emerald-300">
            <ShieldCheck className="h-3 w-3 text-emerald-400" />
            <span className="font-medium">Dev Analyst</span>
            <span className="text-[9px] px-1 py-0.2 rounded bg-emerald-900/80 text-emerald-300 font-mono">
              FinancialAnalyst
            </span>
          </div>
        </div>
      </header>

      {/* Main Studio Grid: Sidebar + Cockpit Workspace */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Left Sidebar: Schema Tree & Launchers */}
        <aside className="w-64 lg:w-72 flex flex-col h-full flex-shrink-0">
          <div className="flex-1 min-h-0">
            <SchemaTree
              views={views}
              loading={loadingViews}
              onSelectTable={handleSelectTable}
            />
          </div>
          <LaunchersBar />
        </aside>

        {/* Center / Right Cockpit Workspace */}
        <main className="flex-1 flex flex-col min-h-0 bg-zinc-950 overflow-hidden">
          {/* SQL Editor Area */}
          <div className="h-56 lg:h-64 flex-shrink-0">
            <SqlEditor
              value={sql}
              onChange={setSql}
              onExecute={handleExecute}
              isExecuting={isExecuting}
              views={views}
            />
          </div>

          {/* Error Banner */}
          {errorMessage && (
            <div className="px-4 py-2.5 bg-rose-950/80 border-b border-rose-800 text-xs text-rose-200 flex items-center justify-between gap-2 flex-shrink-0 animate-in fade-in">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-rose-400 flex-shrink-0" />
                <span className="font-mono">{errorMessage}</span>
              </div>
              <button
                type="button"
                onClick={() => setErrorMessage(null)}
                className="text-[10px] text-rose-400 hover:text-white px-2 py-0.5 rounded bg-rose-900/60 transition"
              >
                Dismiss
              </button>
            </div>
          )}

          {/* Execution Plan Flame Bar */}
          <div className="flex-shrink-0">
            <ExplainTimeline metrics={metrics} />
          </div>

          {/* Results Data Grid */}
          <div className="flex-1 min-h-0 flex flex-col">
            <ResultsGrid columns={columns} rows={rows} currentSql={sql} />
          </div>
        </main>
      </div>
    </div>
  )
}

export default App
