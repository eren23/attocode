/**
 * InteractionTimeline - Horizontal swimlane timeline
 *
 * Shows one lane per agent with colored dots for events along a time axis.
 * Supports zoom via mousewheel and pan via drag.
 */

import { useMemo, useRef, useState, useCallback } from 'react';
import type { AgentNode, DataFlow, DataFlowType } from '../../lib/agent-graph-types';

interface InteractionTimelineProps {
  agents: AgentNode[];
  dataFlows: DataFlow[];
}

const EVENT_TYPE_COLORS: Record<DataFlowType, string> = {
  finding: '#3b82f6',       // blue
  file_share: '#6b7280',    // gray
  budget_transfer: '#10b981', // green
  context_injection: '#f59e0b', // amber
  task_assignment: '#f59e0b', // amber
  result_return: '#22c55e',   // green
};

const EVENT_TYPE_LABELS: Record<DataFlowType, string> = {
  finding: 'Finding',
  file_share: 'File',
  budget_transfer: 'Budget',
  context_injection: 'Context',
  task_assignment: 'Task',
  result_return: 'Result',
};

const LANE_HEIGHT = 36;
const DOT_RADIUS = 5;
const HEADER_WIDTH = 140;
const PADDING_TOP = 30;
const PADDING_BOTTOM = 30;
const MIN_TIMELINE_WIDTH = 400;

interface TooltipState {
  flow: DataFlow;
  x: number;
  y: number;
}

export function InteractionTimeline({ agents, dataFlows }: InteractionTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  // Compute time bounds
  const { minTime, duration } = useMemo(() => {
    if (dataFlows.length === 0) {
      return { minTime: 0, maxTime: 1000, duration: 1000 };
    }
    const timestamps = dataFlows.map((f) => f.timestamp);
    const min = Math.min(...timestamps);
    const max = Math.max(...timestamps);
    const dur = Math.max(max - min, 1);
    return { minTime: min, duration: dur };
  }, [dataFlows]);

  // Create agent index map
  const agentIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    agents.forEach((a, i) => map.set(a.id, i));
    return map;
  }, [agents]);

  const totalHeight = PADDING_TOP + agents.length * LANE_HEIGHT + PADDING_BOTTOM;
  const timelineWidth = Math.max(MIN_TIMELINE_WIDTH, MIN_TIMELINE_WIDTH * zoom);

  // Time to X position
  const timeToX = useCallback(
    (timestamp: number) => {
      const ratio = (timestamp - minTime) / duration;
      return HEADER_WIDTH + ratio * timelineWidth;
    },
    [minTime, duration, timelineWidth]
  );

  // Zoom handler
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      setZoom((prev) => Math.max(0.5, Math.min(5, prev + delta)));
    },
    []
  );

  // Generate time axis ticks
  const ticks = useMemo(() => {
    const tickCount = Math.max(4, Math.floor(timelineWidth / 80));
    const result: { x: number; label: string }[] = [];
    for (let i = 0; i <= tickCount; i++) {
      const t = minTime + (duration * i) / tickCount;
      const x = timeToX(t);
      const elapsedMs = t - minTime;
      let label: string;
      if (elapsedMs < 1000) {
        label = `${Math.round(elapsedMs)}ms`;
      } else if (elapsedMs < 60000) {
        label = `${(elapsedMs / 1000).toFixed(1)}s`;
      } else {
        label = `${(elapsedMs / 60000).toFixed(1)}m`;
      }
      result.push({ x, label });
    }
    return result;
  }, [minTime, duration, timelineWidth, timeToX]);

  if (agents.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        No interaction data
      </div>
    );
  }

  return (
    <div className="relative">
      {/* Zoom control */}
      <div className="flex items-center justify-end gap-2 mb-2 text-[10px] text-gray-500">
        <button
          onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
          className="px-1.5 py-0.5 bg-gray-800 rounded hover:bg-gray-700 transition-colors"
        >
          -
        </button>
        <span className="tabular-nums">{(zoom * 100).toFixed(0)}%</span>
        <button
          onClick={() => setZoom((z) => Math.min(5, z + 0.25))}
          className="px-1.5 py-0.5 bg-gray-800 rounded hover:bg-gray-700 transition-colors"
        >
          +
        </button>
        <button
          onClick={() => setZoom(1)}
          className="px-1.5 py-0.5 bg-gray-800 rounded hover:bg-gray-700 transition-colors"
        >
          Reset
        </button>
      </div>

      {/* Scrollable container */}
      <div
        ref={containerRef}
        className="overflow-x-auto overflow-y-hidden"
        onWheel={handleWheel}
      >
        <svg
          width={HEADER_WIDTH + timelineWidth + 20}
          height={totalHeight}
          className="select-none"
        >
          {/* Background lanes */}
          {agents.map((agent, i) => (
            <g key={agent.id}>
              {/* Lane background - alternating shade */}
              <rect
                x={0}
                y={PADDING_TOP + i * LANE_HEIGHT}
                width={HEADER_WIDTH + timelineWidth + 20}
                height={LANE_HEIGHT}
                fill={i % 2 === 0 ? 'rgba(31,41,55,0.3)' : 'transparent'}
              />
              {/* Agent label */}
              <text
                x={8}
                y={PADDING_TOP + i * LANE_HEIGHT + LANE_HEIGHT / 2}
                dominantBaseline="middle"
                className="fill-gray-400 text-[11px] font-mono"
              >
                {agent.label.length > 16 ? agent.label.slice(0, 15) + '...' : agent.label}
              </text>
              {/* Lane separator */}
              <line
                x1={HEADER_WIDTH}
                y1={PADDING_TOP + i * LANE_HEIGHT}
                x2={HEADER_WIDTH + timelineWidth + 20}
                y2={PADDING_TOP + i * LANE_HEIGHT}
                stroke="#374151"
                strokeWidth={0.5}
              />
            </g>
          ))}

          {/* Time axis */}
          <line
            x1={HEADER_WIDTH}
            y1={PADDING_TOP - 2}
            x2={HEADER_WIDTH + timelineWidth}
            y2={PADDING_TOP - 2}
            stroke="#4b5563"
            strokeWidth={1}
          />
          {ticks.map((tick, i) => (
            <g key={i}>
              <line
                x1={tick.x}
                y1={PADDING_TOP - 6}
                x2={tick.x}
                y2={PADDING_TOP - 2}
                stroke="#4b5563"
                strokeWidth={1}
              />
              <text
                x={tick.x}
                y={PADDING_TOP - 10}
                textAnchor="middle"
                className="fill-gray-500 text-[9px]"
              >
                {tick.label}
              </text>
              {/* Grid line */}
              <line
                x1={tick.x}
                y1={PADDING_TOP}
                x2={tick.x}
                y2={PADDING_TOP + agents.length * LANE_HEIGHT}
                stroke="#1f2937"
                strokeWidth={0.5}
                strokeDasharray="2,4"
              />
            </g>
          ))}

          {/* Data flow arrows between agents */}
          {dataFlows.map((flow) => {
            const sourceIdx = agentIndexMap.get(flow.sourceAgentId);
            const targetIdx = agentIndexMap.get(flow.targetAgentId);
            if (sourceIdx === undefined || targetIdx === undefined) return null;

            const x = timeToX(flow.timestamp);
            const y1 = PADDING_TOP + sourceIdx * LANE_HEIGHT + LANE_HEIGHT / 2;
            const y2 = PADDING_TOP + targetIdx * LANE_HEIGHT + LANE_HEIGHT / 2;
            const color = EVENT_TYPE_COLORS[flow.type];

            // If same agent, just show a dot
            if (sourceIdx === targetIdx) {
              return (
                <circle
                  key={flow.id}
                  cx={x}
                  cy={y1}
                  r={DOT_RADIUS}
                  fill={color}
                  className="cursor-pointer opacity-70 hover:opacity-100 transition-opacity"
                  onMouseEnter={(e) => {
                    const rect = (e.target as SVGElement).getBoundingClientRect();
                    setTooltip({ flow, x: rect.right + 4, y: rect.top - 10 });
                  }}
                  onMouseLeave={() => setTooltip(null)}
                />
              );
            }

            // Arrow from source to target
            const midY = (y1 + y2) / 2;
            return (
              <g
                key={flow.id}
                className="cursor-pointer opacity-70 hover:opacity-100 transition-opacity"
                onMouseEnter={(e) => {
                  const rect = (e.target as SVGElement).getBoundingClientRect();
                  setTooltip({ flow, x: rect.right + 4, y: rect.top - 10 });
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                <circle cx={x} cy={y1} r={DOT_RADIUS - 1} fill={color} />
                <line
                  x1={x}
                  y1={y1 + DOT_RADIUS}
                  x2={x}
                  y2={y2 - DOT_RADIUS}
                  stroke={color}
                  strokeWidth={1.5}
                  strokeDasharray="3,3"
                  opacity={0.5}
                />
                <circle cx={x} cy={y2} r={DOT_RADIUS - 1} fill={color} />
                {/* Arrowhead */}
                <polygon
                  points={`${x - 3},${y2 - 8} ${x + 3},${y2 - 8} ${x},${y2 - 4}`}
                  fill={color}
                  transform={y2 > y1 ? '' : `rotate(180 ${x} ${midY})`}
                />
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-gray-500">
        {(Object.entries(EVENT_TYPE_COLORS) as [DataFlowType, string][]).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
            {EVENT_TYPE_LABELS[type]}
          </span>
        ))}
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 bg-gray-800 border border-gray-700 rounded-lg shadow-xl p-3 max-w-xs pointer-events-none"
          style={{ left: Math.min(tooltip.x, window.innerWidth - 280), top: tooltip.y }}
        >
          <div className="text-xs text-gray-200 font-medium mb-1">
            {EVENT_TYPE_LABELS[tooltip.flow.type]}
          </div>
          <div className="text-[10px] text-gray-400 space-y-0.5">
            <div>{tooltip.flow.payload.summary}</div>
            <div className="flex gap-2">
              <span>From: <span className="text-gray-300">{tooltip.flow.sourceAgentId}</span></span>
              <span>To: <span className="text-gray-300">{tooltip.flow.targetAgentId}</span></span>
            </div>
            {tooltip.flow.payload.size !== undefined && (
              <div>Size: <span className="text-gray-300">{tooltip.flow.payload.size.toLocaleString()}</span></div>
            )}
            {tooltip.flow.payload.topic && (
              <div>Topic: <span className="text-gray-300">{tooltip.flow.payload.topic}</span></div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
