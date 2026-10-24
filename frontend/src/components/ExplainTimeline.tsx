import React from 'react'
import {
  Clock,
  Cpu,
  Database,
  HardDrive,
  Rows,
  Zap,
} from 'lucide-react'
import type { ExecutionMetrics } from '../lib/types'

interface ExplainTimelineProps {
  metrics: ExecutionMetrics | null | undefined
}

export const ExplainTimeline: React.FC<ExplainTimelineProps> = ({ metrics }) => {
  if (!metrics) {
    return (
      <div className="px-4 py-2 bg-zinc-900 border-b border-zinc-800 text-xs text-zinc-500 flex items-center gap-2">
        <Clock className="h-3.5 w-3.5 text-zinc-600" />
        Execute a query to inspect execution plan metrics and subquery pushdown timing.
      </div>
    )
  }

  const {
    planning_ms,
    subquery_ms,
    join_ms,
    total_ms,
    row_count,
    cache_hit,
    scratch_spill_enabled,
  } = metrics

  // Compute maximum subquery duration for proportional bar
  const subqEntries = Object.entries(subquery_ms || {})
  const totalSubqMs = subqEntries.reduce((acc, [, ms]) => acc + ms, 0)

  // Safe percentages
  const safeTotal = Math.max(total_ms, 0.1)
  const planningPct = Math.min(100, Math.max(2, (planning_ms / safeTotal) * 100))
  const subqPct = Math.min(100, Math.max(2, (totalSubqMs / safeTotal) * 100))
  const joinPct = Math.min(100, Math.max(2, (join_ms / safeTotal) * 100))

  return (
    <div className="flex flex-col bg-zinc-900 border-b border-zinc-800 p-3 space-y-2.5">
      {/* Top Status & KPI Badges */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        {/* KPI Pills */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-950 border border-zinc-800 rounded font-mono text-zinc-200">
            <Clock className="h-3.5 w-3.5 text-emerald-400" />
            <span className="font-semibold">{total_ms.toFixed(2)}</span>
            <span className="text-[10px] text-zinc-500">ms total</span>
          </div>

          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-950 border border-zinc-800 rounded font-mono text-zinc-200">
            <Rows className="h-3.5 w-3.5 text-sky-400" />
            <span className="font-semibold">{row_count.toLocaleString()}</span>
            <span className="text-[10px] text-zinc-500">rows</span>
          </div>
        </div>

        {/* Feature & Optimization Badges */}
        <div className="flex items-center gap-1.5">
          {cache_hit ? (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
              <Zap className="h-3 w-3 fill-current" />
              Tier 1 Cache Hit (&lt;5ms)
            </span>
          ) : (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-zinc-800 text-zinc-400 border border-zinc-700">
              Cache Miss
            </span>
          )}

          {join_ms === 0 ? (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-sky-950 text-sky-400 border border-sky-800">
              <Database className="h-3 w-3" />
              Direct Pushdown
            </span>
          ) : (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-indigo-950 text-indigo-400 border border-indigo-800">
              <Cpu className="h-3 w-3" />
              DuckDB Vectorized Join
            </span>
          )}

          {scratch_spill_enabled && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-950 text-amber-400 border border-amber-800">
              <HardDrive className="h-3 w-3" />
              Out-of-Core SSD Spilling
            </span>
          )}
        </div>
      </div>

      {/* Visual Timeline Bar */}
      <div className="space-y-1">
        <div className="w-full h-2 rounded-full overflow-hidden bg-zinc-950 flex border border-zinc-800">
          <div
            style={{ width: `${planningPct}%` }}
            className="bg-cyan-500 transition-all duration-300"
            title={`Planning: ${planning_ms.toFixed(2)}ms`}
          />
          <div
            style={{ width: `${subqPct}%` }}
            className="bg-purple-500 transition-all duration-300"
            title={`Remote Subqueries: ${totalSubqMs.toFixed(2)}ms`}
          />
          <div
            style={{ width: `${joinPct}%` }}
            className="bg-emerald-500 transition-all duration-300"
            title={`DuckDB Join: ${join_ms.toFixed(2)}ms`}
          />
        </div>

        {/* Legend / Metrics Breakdown */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zinc-400 pt-0.5">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-cyan-500 inline-block" />
            Planning: <strong className="text-zinc-200 font-mono">{planning_ms.toFixed(2)}ms</strong>
          </span>

          {subqEntries.map(([alias, ms]) => (
            <span key={alias} className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-purple-500 inline-block" />
              Subquery ({alias}):{' '}
              <strong className="text-zinc-200 font-mono">{ms.toFixed(2)}ms</strong>
            </span>
          ))}

          {join_ms > 0 && (
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-emerald-500 inline-block" />
              Vectorized Join:{' '}
              <strong className="text-zinc-200 font-mono">{join_ms.toFixed(2)}ms</strong>
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
