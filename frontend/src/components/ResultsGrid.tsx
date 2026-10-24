import React, { useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  Copy,
  Download,
  FileCode,
  FileSpreadsheet,
  Search,
} from 'lucide-react'
import { getExportUrl } from '../lib/api'

interface ResultsGridProps {
  columns: string[]
  rows: (string | number | boolean | null)[][]
  currentSql: string
}

export const ResultsGrid: React.FC<ResultsGridProps> = ({ columns, rows, currentSql }) => {
  const [filterText, setFilterText] = useState('')
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortAsc, setSortAsc] = useState(true)
  const [copiedCell, setCopiedCell] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const pageSize = 100

  // Filter rows
  const filteredRows = useMemo(() => {
    if (!filterText.trim()) return rows
    const term = filterText.toLowerCase()
    return rows.filter((r) =>
      r.some((val) => (val !== null && val !== undefined ? String(val).toLowerCase().includes(term) : false))
    )
  }, [rows, filterText])

  // Sort rows
  const sortedRows = useMemo(() => {
    if (sortCol === null) return filteredRows
    return [...filteredRows].sort((a, b) => {
      const valA = a[sortCol]
      const valB = b[sortCol]
      if (valA === valB) return 0
      if (valA === null || valA === undefined) return 1
      if (valB === null || valB === undefined) return -1
      if (typeof valA === 'number' && typeof valB === 'number') {
        return sortAsc ? valA - valB : valB - valA
      }
      const strA = String(valA)
      const strB = String(valB)
      return sortAsc ? strA.localeCompare(strB) : strB.localeCompare(strA)
    })
  }, [filteredRows, sortCol, sortAsc])

  // Paginate rows for smooth rendering
  const paginatedRows = useMemo(() => {
    const start = page * pageSize
    return sortedRows.slice(start, start + pageSize)
  }, [sortedRows, page])

  const totalPages = Math.ceil(sortedRows.length / pageSize)

  const handleSort = (colIndex: number) => {
    if (sortCol === colIndex) {
      if (sortAsc) {
        setSortAsc(false)
      } else {
        setSortCol(null)
        setSortAsc(true)
      }
    } else {
      setSortCol(colIndex)
      setSortAsc(true)
    }
  }

  const copyToClipboard = (text: string, cellKey: string) => {
    navigator.clipboard.writeText(text)
    setCopiedCell(cellKey)
    setTimeout(() => setCopiedCell(null), 1500)
  }

  const triggerExport = (format: 'csv' | 'parquet' | 'ndjson') => {
    if (!currentSql.trim()) return
    const url = getExportUrl(currentSql, format, 'query_result')
    window.open(url, '_blank')
  }

  if (columns.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center bg-zinc-950 p-8 text-xs text-zinc-500">
        No query results to display. Run a SQL query to view output.
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-zinc-950">
      {/* Table Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-zinc-900 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          {/* Filter Input */}
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
            <input
              type="text"
              placeholder="Filter result rows..."
              value={filterText}
              onChange={(e) => {
                setFilterText(e.target.value)
                setPage(0)
              }}
              className="pl-8 pr-3 py-1 bg-zinc-950 border border-zinc-800 rounded text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-emerald-500"
            />
          </div>

          <span className="text-xs text-zinc-400">
            Showing <strong className="text-zinc-200">{sortedRows.length}</strong> rows
          </span>
        </div>

        {/* Export Buttons */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => triggerExport('csv')}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-zinc-800 text-zinc-300 hover:text-white hover:bg-zinc-700 transition"
            title="Download CSV file"
          >
            <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-400" />
            CSV
          </button>

          <button
            type="button"
            onClick={() => triggerExport('parquet')}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-zinc-800 text-zinc-300 hover:text-white hover:bg-zinc-700 transition"
            title="Download Columnar Parquet file"
          >
            <Download className="h-3.5 w-3.5 text-sky-400" />
            Parquet
          </button>

          <button
            type="button"
            onClick={() => triggerExport('ndjson')}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-zinc-800 text-zinc-300 hover:text-white hover:bg-zinc-700 transition"
            title="Download Newline-Delimited JSON stream"
          >
            <FileCode className="h-3.5 w-3.5 text-purple-400" />
            NDJSON
          </button>
        </div>
      </div>

      {/* Virtualized/Scrollable Data Table */}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full border-collapse text-left text-xs font-mono">
          <thead className="bg-zinc-900/90 backdrop-blur sticky top-0 z-10 border-b border-zinc-800">
            <tr>
              <th className="py-2 px-3 text-[11px] font-semibold text-zinc-500 border-r border-zinc-800 w-12 text-right">
                #
              </th>
              {columns.map((col, idx) => (
                <th
                  key={col}
                  onClick={() => handleSort(idx)}
                  className="py-2 px-3 text-[11px] font-semibold text-zinc-300 border-r border-zinc-800 cursor-pointer hover:bg-zinc-800/80 transition select-none"
                >
                  <div className="flex items-center justify-between gap-1.5">
                    <span className="truncate">{col}</span>
                    {sortCol === idx ? (
                      sortAsc ? (
                        <ArrowUp className="h-3 w-3 text-emerald-400" />
                      ) : (
                        <ArrowDown className="h-3 w-3 text-emerald-400" />
                      )
                    ) : (
                      <ArrowUpDown className="h-3 w-3 text-zinc-600 hover:text-zinc-400" />
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-900">
            {paginatedRows.length === 0 ? (
              <tr>
                <td colSpan={columns.length + 1} className="p-6 text-center text-zinc-500 text-xs">
                  No matching rows found for filter.
                </td>
              </tr>
            ) : (
              paginatedRows.map((row, rIdx) => {
                const globalRowIdx = page * pageSize + rIdx + 1
                return (
                  <tr key={globalRowIdx} className="hover:bg-zinc-900/50 transition">
                    <td className="py-1.5 px-3 text-[10px] text-zinc-600 border-r border-zinc-900/50 text-right bg-zinc-950/40">
                      {globalRowIdx}
                    </td>
                    {row.map((cell, cIdx) => {
                      const cellKey = `${globalRowIdx}-${cIdx}`
                      const cellStr = cell === null || cell === undefined ? 'NULL' : String(cell)
                      const isNull = cell === null || cell === undefined
                      const isCopied = copiedCell === cellKey

                      return (
                        <td
                          key={columns[cIdx] || cIdx}
                          onClick={() => copyToClipboard(cellStr, cellKey)}
                          className={`py-1.5 px-3 border-r border-zinc-900/50 truncate max-w-xs group cursor-pointer hover:bg-emerald-950/20 transition ${
                            isNull ? 'text-zinc-600 italic' : 'text-zinc-300'
                          }`}
                          title={`Click to copy: ${cellStr}`}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="truncate">{cellStr}</span>
                            <span className="opacity-0 group-hover:opacity-100 transition text-zinc-500">
                              {isCopied ? (
                                <Check className="h-3 w-3 text-emerald-400" />
                              ) : (
                                <Copy className="h-3 w-3" />
                              )}
                            </span>
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-zinc-900 border-t border-zinc-800 text-xs text-zinc-400">
          <span>
            Page {page + 1} of {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed text-xs transition"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed text-xs transition"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
