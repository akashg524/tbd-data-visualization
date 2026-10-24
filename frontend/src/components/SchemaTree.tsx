import React, { useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Database,
  Folder,
  Layers,
  Search,
  Table as TableIcon,
} from 'lucide-react'
import type { ViewSummary } from '../lib/types'

interface SchemaTreeProps {
  views: ViewSummary[]
  loading: boolean
  onSelectTable: (tablePath: string) => void
}

interface GroupedTree {
  [catalog: string]: {
    [schema: string]: ViewSummary[]
  }
}

export const SchemaTree: React.FC<SchemaTreeProps> = ({ views, loading, onSelectTable }) => {
  const [searchTerm, setSearchTerm] = useState('')
  const [collapsedCatalogs, setCollapsedCatalogs] = useState<Record<string, boolean>>({})
  const [collapsedSchemas, setCollapsedSchemas] = useState<Record<string, boolean>>({})

  // Filter views by search query
  const filteredViews = useMemo(() => {
    if (!searchTerm.trim()) return views
    const term = searchTerm.toLowerCase()
    return views.filter(
      (v) =>
        v.catalog.toLowerCase().includes(term) ||
        v.schema_name.toLowerCase().includes(term) ||
        v.table_name.toLowerCase().includes(term) ||
        v.full_path.toLowerCase().includes(term)
    )
  }, [views, searchTerm])

  // Group views hierarchically: Catalog -> Schema -> Tables
  const tree: GroupedTree = useMemo(() => {
    const res: GroupedTree = {}
    for (const v of filteredViews) {
      if (!res[v.catalog]) res[v.catalog] = {}
      if (!res[v.catalog][v.schema_name]) res[v.catalog][v.schema_name] = []
      res[v.catalog][v.schema_name].push(v)
    }
    return res
  }, [filteredViews])

  const toggleCatalog = (cat: string) => {
    setCollapsedCatalogs((prev) => ({ ...prev, [cat]: !prev[cat] }))
  }

  const toggleSchema = (schemaKey: string) => {
    setCollapsedSchemas((prev) => ({ ...prev, [schemaKey]: !prev[schemaKey] }))
  }

  const getFormatBadge = (format?: string | null) => {
    const f = (format || '').toLowerCase()
    if (f.includes('iceberg')) return 'bg-sky-950 text-sky-400 border-sky-800'
    if (f.includes('relation') || f.includes('oracle') || f.includes('sql')) {
      return 'bg-amber-950 text-amber-400 border-amber-800'
    }
    if (f.includes('cosmos') || f.includes('doc')) {
      return 'bg-emerald-950 text-emerald-400 border-emerald-800'
    }
    return 'bg-zinc-800 text-zinc-400 border-zinc-700'
  }

  return (
    <div className="flex flex-col h-full bg-zinc-900 border-r border-zinc-800 select-none">
      {/* Search Header */}
      <div className="p-3 border-b border-zinc-800">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-zinc-500" />
          <input
            type="text"
            placeholder="Search catalog tables..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 bg-zinc-950 border border-zinc-800 rounded-md text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-emerald-500"
          />
        </div>
      </div>

      {/* Tree View Content */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {loading ? (
          <div className="p-4 text-xs text-zinc-500 text-center animate-pulse">
            Loading catalog schemas...
          </div>
        ) : Object.keys(tree).length === 0 ? (
          <div className="p-4 text-xs text-zinc-500 text-center">
            {searchTerm ? 'No matching tables found.' : 'No catalog tables discovered.'}
          </div>
        ) : (
          Object.entries(tree).map(([catalogName, schemas]) => {
            const isCatCollapsed = !!collapsedCatalogs[catalogName]
            return (
              <div key={catalogName} className="space-y-0.5">
                {/* Catalog Level */}
                <button
                  type="button"
                  onClick={() => toggleCatalog(catalogName)}
                  className="w-full flex items-center gap-1.5 px-2 py-1 rounded text-xs font-semibold text-zinc-300 hover:bg-zinc-800/60 transition"
                >
                  {isCatCollapsed ? (
                    <ChevronRight className="h-3.5 w-3.5 text-zinc-500" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />
                  )}
                  <Database className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="truncate">{catalogName}</span>
                </button>

                {/* Schemas */}
                {!isCatCollapsed && (
                  <div className="pl-3 space-y-0.5">
                    {Object.entries(schemas).map(([schemaName, tables]) => {
                      const schemaKey = `${catalogName}.${schemaName}`
                      const isSchemaCollapsed = !!collapsedSchemas[schemaKey]

                      return (
                        <div key={schemaKey} className="space-y-0.5">
                          {/* Schema Level */}
                          <button
                            type="button"
                            onClick={() => toggleSchema(schemaKey)}
                            className="w-full flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium text-zinc-400 hover:bg-zinc-800/40 transition"
                          >
                            {isSchemaCollapsed ? (
                              <ChevronRight className="h-3 w-3 text-zinc-600" />
                            ) : (
                              <ChevronDown className="h-3 w-3 text-zinc-600" />
                            )}
                            <Folder className="h-3 w-3 text-amber-400/80" />
                            <span className="truncate">{schemaName}</span>
                            <span className="ml-auto text-[10px] text-zinc-600">
                              {tables.length}
                            </span>
                          </button>

                          {/* Tables */}
                          {!isSchemaCollapsed && (
                            <div className="pl-4 space-y-0.5">
                              {tables.map((t) => (
                                <button
                                  key={t.full_path}
                                  type="button"
                                  onClick={() => onSelectTable(t.full_path)}
                                  className="w-full flex items-center gap-1.5 px-2 py-1 rounded text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white transition group text-left"
                                  title={`Click to query: ${t.full_path}`}
                                >
                                  <TableIcon className="h-3 w-3 text-zinc-500 group-hover:text-emerald-400" />
                                  <span className="truncate flex-1">{t.table_name}</span>
                                  {t.format && (
                                    <span
                                      className={`text-[9px] px-1 py-0.2 rounded border uppercase font-mono ${getFormatBadge(
                                        t.format
                                      )}`}
                                    >
                                      {t.format}
                                    </span>
                                  )}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>

      {/* Footer Info */}
      <div className="p-2 border-t border-zinc-800 bg-zinc-950/60 text-[10px] text-zinc-500 flex items-center justify-between">
        <span className="flex items-center gap-1">
          <Layers className="h-3 w-3 text-emerald-500" />
          Virtual Catalog
        </span>
        <span>{views.length} tables</span>
      </div>
    </div>
  )
}
