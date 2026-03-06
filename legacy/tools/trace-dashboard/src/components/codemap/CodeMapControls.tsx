/**
 * CodeMapControls - Top controls bar for the code map visualization
 *
 * Provides filter by type, minimum importance slider, layout toggle,
 * zoom controls, and file count display.
 */

import type { CodeMapFile } from '../../lib/codemap-types';
import { TYPE_COLORS } from './FileNode';

export type LayoutMode = 'force' | 'directory';
export type DetailMode = 'overview' | 'detailed';

interface CodeMapControlsProps {
  totalFiles: number;
  visibleFiles: number;
  detailMode: DetailMode;
  onDetailModeChange: (mode: DetailMode) => void;
  typeFilters: Set<CodeMapFile['type']>;
  onToggleType: (type: CodeMapFile['type']) => void;
  minImportance: number;
  onMinImportanceChange: (value: number) => void;
  layoutMode: LayoutMode;
  onLayoutModeChange: (mode: LayoutMode) => void;
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
}

const ALL_TYPES: { type: CodeMapFile['type']; label: string }[] = [
  { type: 'entry_point', label: 'Entry' },
  { type: 'core_module', label: 'Core' },
  { type: 'types', label: 'Types' },
  { type: 'test', label: 'Test' },
  { type: 'utility', label: 'Utility' },
  { type: 'config', label: 'Config' },
  { type: 'other', label: 'Other' },
];

export function CodeMapControls({
  totalFiles,
  visibleFiles,
  detailMode,
  onDetailModeChange,
  typeFilters,
  onToggleType,
  minImportance,
  onMinImportanceChange,
  layoutMode,
  onLayoutModeChange,
  zoom,
  onZoomIn,
  onZoomOut,
  onZoomReset,
}: CodeMapControlsProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 flex items-center gap-4 flex-wrap">
      {/* View mode */}
      <div className="flex items-center gap-1 bg-gray-800/50 rounded-md p-0.5">
        <button
          onClick={() => onDetailModeChange('overview')}
          className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
            detailMode === 'overview'
              ? 'bg-gray-700 text-white'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          Overview
        </button>
        <button
          onClick={() => onDetailModeChange('detailed')}
          className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
            detailMode === 'detailed'
              ? 'bg-gray-700 text-white'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          Detailed
        </button>
      </div>

      {/* Separator */}
      <div className="w-px h-5 bg-gray-800" />

      {/* Type filters */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-gray-500 uppercase font-medium">
          Type
        </span>
        <div className="flex items-center gap-1">
          {ALL_TYPES.map(({ type, label }) => {
            const active = typeFilters.has(type);
            const color = TYPE_COLORS[type];
            return (
              <button
                key={type}
                onClick={() => onToggleType(type)}
                className={`px-1.5 py-0.5 text-[10px] rounded border transition-colors ${
                  active
                    ? 'border-opacity-60 text-white'
                    : 'border-transparent text-gray-600 hover:text-gray-400'
                }`}
                style={{
                  borderColor: active ? color : 'transparent',
                  backgroundColor: active ? `${color}20` : 'transparent',
                }}
              >
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full mr-1"
                  style={{ backgroundColor: color, opacity: active ? 1 : 0.3 }}
                />
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Separator */}
      <div className="w-px h-5 bg-gray-800" />

      {/* Importance slider */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-gray-500 uppercase font-medium">
          Min Importance
        </span>
        <input
          type="range"
          min="0"
          max="100"
          value={Math.round(minImportance * 100)}
          onChange={(e) => onMinImportanceChange(Number(e.target.value) / 100)}
          className="w-20 h-1 accent-blue-500"
        />
        <span className="text-[10px] text-gray-400 w-8">
          {Math.round(minImportance * 100)}%
        </span>
      </div>

      {/* Separator */}
      <div className="w-px h-5 bg-gray-800" />

      {/* Layout toggle */}
      <div className="flex items-center gap-1 bg-gray-800/50 rounded-md p-0.5">
        <button
          onClick={() => onLayoutModeChange('force')}
          className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
            layoutMode === 'force'
              ? 'bg-gray-700 text-white'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          Force
        </button>
        <button
          onClick={() => onLayoutModeChange('directory')}
          className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
            layoutMode === 'directory'
              ? 'bg-gray-700 text-white'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          Directory
        </button>
      </div>

      {/* Separator */}
      <div className="w-px h-5 bg-gray-800" />

      {/* Zoom controls */}
      <div className="flex items-center gap-1">
        <button
          onClick={onZoomOut}
          className="w-6 h-6 flex items-center justify-center text-gray-500 hover:text-gray-300 bg-gray-800/50 rounded transition-colors text-xs"
        >
          -
        </button>
        <button
          onClick={onZoomReset}
          className="px-1.5 h-6 flex items-center justify-center text-[10px] text-gray-400 hover:text-gray-300 bg-gray-800/50 rounded transition-colors min-w-[36px]"
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          onClick={onZoomIn}
          className="w-6 h-6 flex items-center justify-center text-gray-500 hover:text-gray-300 bg-gray-800/50 rounded transition-colors text-xs"
        >
          +
        </button>
      </div>

      {/* File count */}
      <div className="ml-auto text-[10px] text-gray-500">
        {visibleFiles} / {totalFiles} files
      </div>
    </div>
  );
}
