import React from 'react'
import {
  Download,
  ExternalLink,
  FileSpreadsheet,
  Layers,
  Terminal,
} from 'lucide-react'
import { getOdcUrl, getPbidsUrl } from '../lib/api'

export const LaunchersBar: React.FC = () => {
  return (
    <div className="p-3 border-t border-zinc-800 bg-zinc-950/80 space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-300">
        <Layers className="h-3.5 w-3.5 text-emerald-400" />
        <span>1-Click Serving Launchers</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {/* Power BI PBIDS */}
        <a
          href={getPbidsUrl()}
          download="federated_data_hub.pbids"
          className="flex items-center justify-between p-2 rounded bg-zinc-900 border border-zinc-800 hover:border-amber-700/60 hover:bg-zinc-800/80 transition group text-left"
          title="Download pre-wired Power BI DirectQuery source descriptor"
        >
          <div>
            <div className="text-[11px] font-medium text-zinc-200 group-hover:text-amber-400 transition">
              Power BI
            </div>
            <div className="text-[9px] text-zinc-500">.pbids (DirectQuery)</div>
          </div>
          <Download className="h-3.5 w-3.5 text-zinc-500 group-hover:text-amber-400 transition" />
        </a>

        {/* Excel ODC */}
        <a
          href={getOdcUrl()}
          download="federated_data_hub.odc"
          className="flex items-center justify-between p-2 rounded bg-zinc-900 border border-zinc-800 hover:border-emerald-700/60 hover:bg-zinc-800/80 transition group text-left"
          title="Download pre-wired Microsoft Excel Office Data Connection"
        >
          <div>
            <div className="text-[11px] font-medium text-zinc-200 group-hover:text-emerald-400 transition">
              Excel ODC
            </div>
            <div className="text-[9px] text-zinc-500">.odc (OData Feed)</div>
          </div>
          <FileSpreadsheet className="h-3.5 w-3.5 text-zinc-500 group-hover:text-emerald-400 transition" />
        </a>
      </div>

      {/* Protocol Endpoints Info */}
      <div className="pt-1 text-[10px] text-zinc-500 space-y-1">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1">
            <Terminal className="h-3 w-3 text-sky-400" />
            PGWire Gateway:
          </span>
          <span className="font-mono text-zinc-400">port 5433</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1">
            <ExternalLink className="h-3 w-3 text-purple-400" />
            Arrow Flight:
          </span>
          <span className="font-mono text-zinc-400">port 5005</span>
        </div>
      </div>
    </div>
  )
}
