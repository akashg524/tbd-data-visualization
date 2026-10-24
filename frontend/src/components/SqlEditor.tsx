import React, { useEffect, useRef } from 'react'
import Editor, { type Monaco, type OnMount } from '@monaco-editor/react'
import { Eraser, Play, Sparkles } from 'lucide-react'
import { registerCatalogCompletions } from '../lib/monaco'
import type { ViewSummary } from '../lib/types'

interface SqlEditorProps {
  value: string
  onChange: (val: string) => void
  onExecute: () => void
  isExecuting: boolean
  views: ViewSummary[]
}

export const SqlEditor: React.FC<SqlEditorProps> = ({
  value,
  onChange,
  onExecute,
  isExecuting,
  views,
}) => {
  const monacoRef = useRef<Monaco | null>(null)
  const editorRef = useRef<any>(null)

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    monacoRef.current = monaco

    // Keyboard shortcut: Ctrl+Enter or Cmd+Enter to execute query
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      onExecute()
    })
  }

  // Update catalog autocompletion provider whenever views change
  useEffect(() => {
    if (!monacoRef.current || views.length === 0) return
    const disposable = registerCatalogCompletions(monacoRef.current, views)
    return () => disposable.dispose()
  }, [views])

  const handleFormat = () => {
    if (editorRef.current) {
      editorRef.current.getAction('editor.action.formatDocument')?.run()
    }
  }

  const handleClear = () => {
    onChange('')
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950 border-b border-zinc-800">
      {/* Editor Action Bar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-zinc-900 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onExecute}
            disabled={isExecuting || !value.trim()}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold text-white transition shadow-sm ${
              isExecuting || !value.trim()
                ? 'bg-zinc-700 opacity-60 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700'
            }`}
          >
            <Play className={`h-3.5 w-3.5 ${isExecuting ? 'animate-spin' : 'fill-current'}`} />
            {isExecuting ? 'Executing...' : 'Run Query'}
          </button>

          <span className="text-[11px] text-zinc-500 font-mono">
            <kbd className="px-1 py-0.5 bg-zinc-800 border border-zinc-700 rounded text-[10px] text-zinc-400">
              Ctrl+Enter
            </kbd>
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={handleFormat}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
            title="Format SQL (Alt+Shift+F)"
          >
            <Sparkles className="h-3.5 w-3.5 text-zinc-400" />
            Format
          </button>

          <button
            type="button"
            onClick={handleClear}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs text-zinc-400 hover:text-rose-400 hover:bg-zinc-800 transition"
            title="Clear Editor"
          >
            <Eraser className="h-3.5 w-3.5" />
            Clear
          </button>
        </div>
      </div>

      {/* Monaco Editor Container */}
      <div className="flex-1 min-h-[160px]">
        <Editor
          height="100%"
          language="sql"
          theme="vs-dark"
          value={value}
          onChange={(val) => onChange(val || '')}
          onMount={handleEditorMount}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            suggestOnTriggerCharacters: true,
            quickSuggestions: {
              other: true,
              comments: false,
              strings: true,
            },
            wordWrap: 'on',
            padding: { top: 8, bottom: 8 },
          }}
        />
      </div>
    </div>
  )
}
