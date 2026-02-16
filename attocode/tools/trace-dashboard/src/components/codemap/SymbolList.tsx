/**
 * SymbolList - Expandable symbol list grouped by kind
 *
 * Shows functions, classes, interfaces, types, and consts with
 * collapsible sections, line numbers, and exported badges.
 */

import { useState } from 'react';

interface Symbol {
  name: string;
  kind: string;
  exported: boolean;
  line: number;
}

interface SymbolListProps {
  symbols: Symbol[];
}

const KIND_ORDER = ['class', 'interface', 'type', 'function', 'const'];
const KIND_LABELS: Record<string, string> = {
  class: 'Classes',
  interface: 'Interfaces',
  type: 'Types',
  function: 'Functions',
  const: 'Constants',
};
const KIND_COLORS: Record<string, string> = {
  class: 'text-purple-400',
  interface: 'text-cyan-400',
  type: 'text-blue-400',
  function: 'text-amber-400',
  const: 'text-green-400',
};

export function SymbolList({ symbols }: SymbolListProps) {
  const [expandedKinds, setExpandedKinds] = useState<Set<string>>(
    new Set(KIND_ORDER)
  );

  if (symbols.length === 0) {
    return (
      <div className="text-xs text-gray-500 italic">No symbols extracted</div>
    );
  }

  // Group by kind
  const grouped = new Map<string, Symbol[]>();
  for (const sym of symbols) {
    const kind = KIND_ORDER.includes(sym.kind) ? sym.kind : 'const';
    if (!grouped.has(kind)) grouped.set(kind, []);
    grouped.get(kind)!.push(sym);
  }

  // Sort groups by KIND_ORDER
  const sortedKinds = [...grouped.keys()].sort(
    (a, b) => KIND_ORDER.indexOf(a) - KIND_ORDER.indexOf(b)
  );

  const toggleKind = (kind: string) => {
    setExpandedKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) {
        next.delete(kind);
      } else {
        next.add(kind);
      }
      return next;
    });
  };

  return (
    <div className="space-y-1">
      {sortedKinds.map((kind) => {
        const syms = grouped.get(kind)!;
        const expanded = expandedKinds.has(kind);
        const label = KIND_LABELS[kind] || kind;
        const color = KIND_COLORS[kind] || 'text-gray-400';

        return (
          <div key={kind}>
            <button
              onClick={() => toggleKind(kind)}
              className="flex items-center gap-1.5 w-full text-left py-0.5 hover:bg-gray-800/30 rounded px-1 -mx-1 transition-colors"
            >
              <svg
                className={`w-3 h-3 text-gray-500 transition-transform ${
                  expanded ? 'rotate-90' : ''
                }`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 5l7 7-7 7"
                />
              </svg>
              <span className={`text-[11px] font-medium ${color}`}>
                {label}
              </span>
              <span className="text-[10px] text-gray-600">{syms.length}</span>
            </button>

            {expanded && (
              <div className="ml-4 space-y-0.5 mt-0.5">
                {syms
                  .sort((a, b) => a.line - b.line)
                  .map((sym, i) => (
                    <div
                      key={`${sym.name}-${i}`}
                      className="flex items-center gap-1.5 text-[11px] py-0.5"
                    >
                      <span className="text-gray-300 font-mono">
                        {sym.name}
                      </span>
                      {sym.exported && (
                        <span className="px-1 py-0 text-[9px] rounded bg-blue-900/50 text-blue-400 border border-blue-800/50">
                          export
                        </span>
                      )}
                      <span className="text-gray-600 ml-auto text-[10px] font-mono">
                        L{sym.line}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
