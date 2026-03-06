/**
 * FlowLegend - Legend for edge types and packet colors.
 *
 * Maps over FLOW_TYPE_STYLES to render color + label pairs.
 */

import { FLOW_TYPE_STYLES, type DataFlowType } from '../../lib/agent-graph-types';

export function FlowLegend() {
  const entries = Object.entries(FLOW_TYPE_STYLES) as [DataFlowType, typeof FLOW_TYPE_STYLES[DataFlowType]][];

  return (
    <div className="flex flex-wrap items-center gap-3 px-3 py-2 bg-gray-900/50 border border-gray-800 rounded-lg">
      <span className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">Data Flows</span>
      {entries.map(([type, style]) => (
        <div key={type} className="flex items-center gap-1.5">
          <svg width="20" height="8" className="shrink-0">
            <line
              x1="0"
              y1="4"
              x2="20"
              y2="4"
              stroke={style.color}
              strokeWidth="2"
              strokeDasharray={style.dash || undefined}
            />
          </svg>
          <span className="text-[11px] text-gray-400">{style.label}</span>
        </div>
      ))}
    </div>
  );
}
