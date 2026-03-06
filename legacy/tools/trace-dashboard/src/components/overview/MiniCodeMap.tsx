/**
 * MiniCodeMap - Compact top-30 files visualization
 *
 * Shows horizontal bar chart of the most important files, colored by type.
 * Bar length proportional to token count, with file name and count labels.
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { CodeMapData, CodeMapFile } from '../../lib/codemap-types';
import { formatTokens, cn } from '../../lib/utils';

interface MiniCodeMapProps {
  data: CodeMapData;
  sessionId?: string;
}

const FILE_TYPE_COLORS: Record<CodeMapFile['type'], string> = {
  entry_point: '#a855f7', // code-entry
  core_module: '#3b82f6', // code-core
  types: '#06b6d4',       // code-types
  test: '#10b981',        // code-test
  utility: '#f59e0b',
  config: '#6b7280',
  other: '#4b5563',
};

const FILE_TYPE_BG: Record<CodeMapFile['type'], string> = {
  entry_point: 'bg-code-entry/20',
  core_module: 'bg-code-core/20',
  types: 'bg-code-types/20',
  test: 'bg-code-test/20',
  utility: 'bg-yellow-500/20',
  config: 'bg-gray-500/20',
  other: 'bg-gray-600/20',
};

interface TooltipState {
  file: CodeMapFile;
  x: number;
  y: number;
}

export function MiniCodeMap({ data, sessionId }: MiniCodeMapProps) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const topFiles = useMemo(() => {
    return [...data.files]
      .sort((a, b) => b.tokenCount - a.tokenCount)
      .slice(0, 30);
  }, [data.files]);

  const maxTokens = useMemo(() => {
    return topFiles.length > 0 ? topFiles[0].tokenCount : 1;
  }, [topFiles]);

  if (topFiles.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        No code map data
      </div>
    );
  }

  return (
    <div className="relative">
      {/* View Full link */}
      {sessionId && (
        <div className="flex justify-end mb-2">
          <Link
            to={`/codemap/${encodeURIComponent(sessionId)}`}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            View Full →
          </Link>
        </div>
      )}
      {/* File bars */}
      <div className="space-y-1">
        {topFiles.map((file) => {
          const widthPercent = Math.max(2, (file.tokenCount / maxTokens) * 100);
          const shortName = file.fileName;

          return (
            <div
              key={file.filePath}
              className="flex items-center gap-2 group cursor-pointer"
              onMouseEnter={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                setTooltip({ file, x: rect.right + 8, y: rect.top });
              }}
              onMouseLeave={() => setTooltip(null)}
            >
              {/* File name */}
              <span className="text-[11px] text-gray-400 font-mono truncate w-36 flex-shrink-0 text-right group-hover:text-gray-200 transition-colors">
                {shortName}
              </span>

              {/* Bar */}
              <div className="flex-1 h-4 bg-gray-800/50 rounded overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded transition-all duration-300',
                    FILE_TYPE_BG[file.type],
                    'group-hover:brightness-125'
                  )}
                  style={{
                    width: `${widthPercent}%`,
                    backgroundColor: FILE_TYPE_COLORS[file.type],
                    opacity: 0.6,
                  }}
                />
              </div>

              {/* Token count */}
              <span className="text-[10px] text-gray-500 tabular-nums w-10 text-right flex-shrink-0">
                {formatTokens(file.tokenCount)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-3 pt-2 border-t border-gray-800 flex flex-wrap gap-3 text-[10px] text-gray-500">
        {(
          [
            ['entry_point', 'Entry Point'],
            ['core_module', 'Core'],
            ['types', 'Types'],
            ['test', 'Test'],
            ['utility', 'Utility'],
            ['config', 'Config'],
          ] as [CodeMapFile['type'], string][]
        ).map(([type, label]) => (
          <span key={type} className="flex items-center gap-1">
            <span
              className="w-2 h-2 rounded-sm"
              style={{ backgroundColor: FILE_TYPE_COLORS[type] }}
            />
            {label}
          </span>
        ))}
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl p-3 max-w-xs pointer-events-none"
          style={{ left: Math.min(tooltip.x, window.innerWidth - 320), top: tooltip.y }}
        >
          <div className="text-xs font-mono text-gray-200 mb-1 truncate">
            {tooltip.file.filePath}
          </div>
          <div className="text-[10px] text-gray-400 space-y-0.5">
            <div>Type: <span className="text-gray-300">{tooltip.file.type.replace('_', ' ')}</span></div>
            <div>Tokens: <span className="text-gray-300">{tooltip.file.tokenCount.toLocaleString()}</span></div>
            <div>Importance: <span className="text-gray-300">{(tooltip.file.importance * 100).toFixed(0)}%</span></div>
            <div>In-degree: <span className="text-gray-300">{tooltip.file.inDegree}</span> / Out-degree: <span className="text-gray-300">{tooltip.file.outDegree}</span></div>
            {tooltip.file.symbols.length > 0 && (
              <div className="mt-1 pt-1 border-t border-gray-700">
                <div className="text-gray-400 mb-0.5">Symbols ({tooltip.file.symbols.length}):</div>
                {tooltip.file.symbols
                  .filter((s) => s.exported)
                  .slice(0, 8)
                  .map((sym) => (
                    <div key={`${sym.name}-${sym.line}`} className="text-gray-300 font-mono truncate">
                      {sym.kind} {sym.name}
                    </div>
                  ))}
                {tooltip.file.symbols.filter((s) => s.exported).length > 8 && (
                  <div className="text-gray-500">
                    +{tooltip.file.symbols.filter((s) => s.exported).length - 8} more
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
