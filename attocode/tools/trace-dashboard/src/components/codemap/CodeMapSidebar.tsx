/**
 * CodeMapSidebar - Detail panel shown when a file is selected
 *
 * Displays file path, type badge, token count, importance score,
 * symbols list, and dependency information (imports / imported by).
 */

import type { CodeMapData, CodeMapFile } from '../../lib/codemap-types';
import { SymbolList } from './SymbolList';
import { TYPE_COLORS } from './FileNode';
import { formatTokens } from '../../lib/utils';

interface CodeMapSidebarProps {
  data: CodeMapData;
  selectedFile: string | null;
  onClose: () => void;
}

const TYPE_LABELS: Record<CodeMapFile['type'], string> = {
  entry_point: 'Entry Point',
  core_module: 'Core Module',
  types: 'Types',
  test: 'Test',
  utility: 'Utility',
  config: 'Config',
  other: 'Other',
};

export function CodeMapSidebar({
  data,
  selectedFile,
  onClose,
}: CodeMapSidebarProps) {
  if (!selectedFile) return null;

  const file = data.files.find((f) => f.filePath === selectedFile);
  if (!file) return null;

  // Find files that import this file
  const importedBy = data.dependencyEdges
    .filter((e) => e.target === selectedFile)
    .map((e) => ({
      filePath: e.source,
      names: e.importedNames,
    }));

  // Find files this file imports
  const imports = data.dependencyEdges
    .filter((e) => e.source === selectedFile)
    .map((e) => ({
      filePath: e.target,
      names: e.importedNames,
    }));

  const borderColor = TYPE_COLORS[file.type];

  return (
    <div className="w-[300px] bg-gray-900 border border-gray-800 rounded-lg flex flex-col overflow-hidden shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <h3 className="text-sm font-medium text-white truncate">
          File Details
        </h3>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-300 transition-colors"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* File info */}
        <div>
          <div
            className="text-xs font-mono text-gray-300 break-all leading-relaxed border-l-2 pl-2"
            style={{ borderColor }}
          >
            {file.filePath}
          </div>

          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <span
              className="inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded border"
              style={{
                borderColor,
                color: borderColor,
                backgroundColor: `${borderColor}15`,
              }}
            >
              {TYPE_LABELS[file.type]}
            </span>
          </div>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-gray-800/50 rounded px-2 py-1.5">
            <div className="text-[10px] text-gray-500 uppercase">Tokens</div>
            <div className="text-sm text-gray-200 font-medium">
              {formatTokens(file.tokenCount)}
            </div>
          </div>
          <div className="bg-gray-800/50 rounded px-2 py-1.5">
            <div className="text-[10px] text-gray-500 uppercase">
              Importance
            </div>
            <div className="text-sm text-gray-200 font-medium">
              {(file.importance * 100).toFixed(0)}%
            </div>
          </div>
          <div className="bg-gray-800/50 rounded px-2 py-1.5">
            <div className="text-[10px] text-gray-500 uppercase">In-Degree</div>
            <div className="text-sm text-gray-200 font-medium">
              {file.inDegree}
            </div>
          </div>
          <div className="bg-gray-800/50 rounded px-2 py-1.5">
            <div className="text-[10px] text-gray-500 uppercase">
              Out-Degree
            </div>
            <div className="text-sm text-gray-200 font-medium">
              {file.outDegree}
            </div>
          </div>
        </div>

        {/* Symbols */}
        <div>
          <h4 className="text-xs font-medium text-gray-400 uppercase mb-1.5">
            Symbols ({file.symbols.length})
          </h4>
          <SymbolList symbols={file.symbols} />
        </div>

        {/* Imported By */}
        <div>
          <h4 className="text-xs font-medium text-gray-400 uppercase mb-1.5">
            Imported By ({importedBy.length})
          </h4>
          {importedBy.length === 0 ? (
            <div className="text-xs text-gray-600 italic">
              No files import this module
            </div>
          ) : (
            <div className="space-y-1">
              {importedBy.map((dep, i) => (
                <div
                  key={`${dep.filePath}-${i}`}
                  className="text-[11px] py-0.5"
                >
                  <div className="text-gray-300 font-mono truncate">
                    {dep.filePath}
                  </div>
                  {dep.names.length > 0 && (
                    <div className="text-gray-600 text-[10px] truncate">
                      {dep.names.join(', ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Imports */}
        <div>
          <h4 className="text-xs font-medium text-gray-400 uppercase mb-1.5">
            Imports ({imports.length})
          </h4>
          {imports.length === 0 ? (
            <div className="text-xs text-gray-600 italic">
              No imports from tracked files
            </div>
          ) : (
            <div className="space-y-1">
              {imports.map((dep, i) => (
                <div
                  key={`${dep.filePath}-${i}`}
                  className="text-[11px] py-0.5"
                >
                  <div className="text-gray-300 font-mono truncate">
                    {dep.filePath}
                  </div>
                  {dep.names.length > 0 && (
                    <div className="text-gray-600 text-[10px] truncate">
                      {dep.names.join(', ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
