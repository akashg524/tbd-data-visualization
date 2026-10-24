import type { Monaco } from '@monaco-editor/react'
import type { IDisposable, Position, editor } from 'monaco-editor'
import type { ViewSummary } from './types'

const SQL_KEYWORDS = [
  'SELECT',
  'FROM',
  'JOIN',
  'INNER JOIN',
  'LEFT JOIN',
  'RIGHT JOIN',
  'FULL JOIN',
  'ON',
  'WHERE',
  'GROUP BY',
  'HAVING',
  'ORDER BY',
  'LIMIT',
  'OFFSET',
  'ASC',
  'DESC',
  'AS',
  'AND',
  'OR',
  'NOT',
  'IN',
  'LIKE',
  'IS NULL',
  'IS NOT NULL',
  'COUNT',
  'SUM',
  'AVG',
  'MIN',
  'MAX',
  'COALESCE',
  'CASE',
  'WHEN',
  'THEN',
  'ELSE',
  'END',
  'DISTINCT',
  'UNION ALL',
]

/**
 * Register dynamic catalog completion items in Monaco for SQL language.
 */
export function registerCatalogCompletions(monaco: Monaco, views: ViewSummary[]): IDisposable {
  return monaco.languages.registerCompletionItemProvider('sql', {
    provideCompletionItems: (model: editor.ITextModel, position: Position) => {
      const word = model.getWordUntilPosition(position)
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      }

      // 1. Catalog table suggestions
      const tableSuggestions = views.flatMap((v) => [
        {
          label: v.full_path,
          kind: monaco.languages.CompletionItemKind.Class,
          insertText: v.full_path,
          detail: `Virtual Table (${v.catalog})`,
          documentation: `Datasource: ${v.catalog}\nSchema: ${v.schema_name}\nFormat: ${v.format || 'standard'}`,
          range,
        },
        {
          label: `${v.schema_name}.${v.table_name}`,
          kind: monaco.languages.CompletionItemKind.Class,
          insertText: `${v.schema_name}.${v.table_name}`,
          detail: `2-Part Table (${v.catalog})`,
          documentation: `Target: ${v.full_path}`,
          range,
        },
        {
          label: v.table_name,
          kind: monaco.languages.CompletionItemKind.Field,
          insertText: v.table_name,
          detail: `Table (${v.schema_name})`,
          documentation: `Full path: ${v.full_path}`,
          range,
        },
      ])

      // 2. Standard SQL keywords
      const keywordSuggestions = SQL_KEYWORDS.map((kw) => ({
        label: kw,
        kind: monaco.languages.CompletionItemKind.Keyword,
        insertText: kw,
        detail: 'SQL Keyword',
        range,
      }))

      // Deduplicate by label
      const seen = new Set<string>()
      const uniqueSuggestions = [...tableSuggestions, ...keywordSuggestions].filter((item) => {
        if (seen.has(item.label)) return false
        seen.add(item.label)
        return true
      })

      return {
        suggestions: uniqueSuggestions,
      }
    },
  })
}
