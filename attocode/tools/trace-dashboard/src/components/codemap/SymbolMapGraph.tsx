import { useMemo } from 'react';
import type { CodeMapData } from '../../lib/codemap-types';

interface SymbolMapGraphProps {
  data: CodeMapData;
  selectedFile: string | null;
  onSelectFile: (filePath: string | null) => void;
}

const KIND_COLORS: Record<string, string> = {
  function: '#f59e0b',
  class: '#a855f7',
  interface: '#06b6d4',
  type: '#3b82f6',
  const: '#10b981',
  variable: '#10b981',
  enum: '#f97316',
  symbol: '#9ca3af',
};

export function SymbolMapGraph({ data, selectedFile, onSelectFile }: SymbolMapGraphProps) {
  const selected = useMemo(
    () => data.files.find((f) => f.filePath === selectedFile) ?? data.files[0] ?? null,
    [data.files, selectedFile],
  );

  if (!selected) {
    return <div className="flex-1 min-h-0 rounded-lg border border-gray-800 bg-gray-900/40" />;
  }

  const symbols = selected.symbols.slice(0, 120);
  const cx = 440;
  const cy = 280;
  const ring = Math.max(140, Math.min(260, 120 + symbols.length * 2));

  return (
    <div className="flex-1 min-h-0 rounded-lg border border-gray-800 bg-gray-900/40 overflow-hidden">
      <div className="px-3 py-2 border-b border-gray-800 text-xs text-gray-400">
        Detailed Symbol Map: <span className="text-gray-300 font-mono">{selected.filePath}</span>
      </div>

      <svg viewBox="0 0 900 620" className="w-full h-[calc(100%-2.25rem)]">
        {symbols.map((sym, i) => {
          const angle = (i / Math.max(1, symbols.length)) * Math.PI * 2;
          const x = cx + Math.cos(angle) * ring;
          const y = cy + Math.sin(angle) * ring;
          const color = KIND_COLORS[sym.kind] ?? KIND_COLORS.symbol;

          return (
            <g key={`${sym.name}-${sym.line}-${i}`}>
              <line x1={cx} y1={cy} x2={x} y2={y} stroke={color} strokeOpacity={0.35} />
              <circle cx={x} cy={y} r={8} fill={color} fillOpacity={0.85} />
              <text x={x + 12} y={y + 4} fill="#cbd5e1" fontSize="10" fontFamily="ui-monospace">
                {sym.name}
              </text>
            </g>
          );
        })}

        <g>
          <rect
            x={cx - 130}
            y={cy - 26}
            width={260}
            height={52}
            rx={8}
            fill="#0f172a"
            stroke="#475569"
            onClick={() => onSelectFile(selected.filePath)}
            className="cursor-pointer"
          />
          <text x={cx} y={cy - 2} fill="#e2e8f0" fontSize="12" textAnchor="middle" fontFamily="ui-monospace">
            {selected.fileName}
          </text>
          <text x={cx} y={cy + 15} fill="#64748b" fontSize="10" textAnchor="middle">
            {selected.symbols.length} symbols
          </text>
        </g>
      </svg>
    </div>
  );
}
