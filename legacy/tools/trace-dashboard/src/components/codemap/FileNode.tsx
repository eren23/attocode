/**
 * FileNode - Individual file node for the code map graph
 *
 * Displays a file as a rounded rectangle with colored border by type,
 * token count label, and hover/selection states.
 */

import { useState } from 'react';
import { cn } from '../../lib/utils';
import type { CodeMapFile } from '../../lib/codemap-types';

interface FileNodeProps {
  file: CodeMapFile;
  x: number;
  y: number;
  width: number;
  height: number;
  selected: boolean;
  highlighted: boolean;
  opacity: number;
  onClick: (filePath: string) => void;
}

const TYPE_COLORS: Record<CodeMapFile['type'], string> = {
  entry_point: '#a855f7',
  core_module: '#3b82f6',
  types: '#06b6d4',
  test: '#10b981',
  utility: '#6b7280',
  config: '#f59e0b',
  other: '#4b5563',
};

const TYPE_BG: Record<CodeMapFile['type'], string> = {
  entry_point: 'bg-purple-900/40',
  core_module: 'bg-blue-900/40',
  types: 'bg-cyan-900/40',
  test: 'bg-emerald-900/40',
  utility: 'bg-gray-800/60',
  config: 'bg-amber-900/40',
  other: 'bg-gray-800/40',
};

function truncateFileName(name: string, maxLen: number): string {
  if (name.length <= maxLen) return name;
  const ext = name.lastIndexOf('.');
  if (ext > 0 && name.length - ext <= 4) {
    const base = name.slice(0, ext);
    const extension = name.slice(ext);
    const available = maxLen - extension.length - 2;
    if (available > 2) {
      return base.slice(0, available) + '..' + extension;
    }
  }
  return name.slice(0, maxLen - 2) + '..';
}

function formatTokenCount(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}K`;
  }
  return count.toString();
}

export function FileNode({
  file,
  x,
  y,
  width,
  height,
  selected,
  highlighted,
  opacity,
  onClick,
}: FileNodeProps) {
  const [hovered, setHovered] = useState(false);
  const borderColor = TYPE_COLORS[file.type];
  const displayName = truncateFileName(file.fileName, 12);

  const effectiveOpacity = highlighted || selected || hovered ? 1 : opacity;

  return (
    <div
      className={cn(
        'absolute rounded-lg border-l-[3px] px-2 py-1.5 cursor-pointer transition-all duration-150',
        TYPE_BG[file.type],
        selected ? 'ring-2 ring-blue-400 border-blue-400' : '',
        !selected && hovered ? 'ring-1 ring-white/20' : ''
      )}
      style={{
        left: x,
        top: y,
        width,
        height,
        borderLeftColor: borderColor,
        borderTopColor: selected ? undefined : 'rgb(55 65 81 / 0.5)',
        borderRightColor: selected ? undefined : 'rgb(55 65 81 / 0.5)',
        borderBottomColor: selected ? undefined : 'rgb(55 65 81 / 0.5)',
        borderTopWidth: selected ? undefined : '1px',
        borderRightWidth: selected ? undefined : '1px',
        borderBottomWidth: selected ? undefined : '1px',
        opacity: effectiveOpacity,
        transform: selected ? 'scale(1.05)' : 'scale(1)',
        zIndex: selected ? 20 : hovered ? 10 : 1,
      }}
      onClick={() => onClick(file.filePath)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={file.filePath}
    >
      <div className="text-[11px] text-gray-200 font-medium leading-tight truncate">
        {displayName}
      </div>
      <div className="text-[9px] text-gray-500 mt-0.5">
        {formatTokenCount(file.tokenCount)} tok
      </div>

      {/* Tooltip on hover */}
      {hovered && (
        <div
          className="absolute left-1/2 -translate-x-1/2 bottom-full mb-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-[10px] text-gray-300 whitespace-nowrap pointer-events-none z-50"
          style={{ maxWidth: '300px' }}
        >
          {file.filePath}
        </div>
      )}
    </div>
  );
}

export { TYPE_COLORS };
