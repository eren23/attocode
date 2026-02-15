/**
 * DataFlowEdge - SVG edge between agents, styled by DataFlowType.
 *
 * Uses FLOW_TYPE_STYLES for stroke/dash/color. Draws a cubic bezier curve
 * between source and target node positions with an arrow marker at the target.
 */

import { FLOW_TYPE_STYLES, type DataFlowType } from '../../lib/agent-graph-types';

interface DataFlowEdgeProps {
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  type: DataFlowType;
  /** Whether to highlight this edge (e.g., when a packet is traveling) */
  active?: boolean;
  /** Unique ID for this edge's path (used by getPointAtLength) */
  pathId: string;
  /** Ref callback for the path element */
  pathRef?: (el: SVGPathElement | null) => void;
}

/** Compute a cubic bezier path between two points with vertical bias */
function computePath(
  sx: number,
  sy: number,
  tx: number,
  ty: number
): string {
  const dy = ty - sy;
  const dx = tx - sx;

  // Vertical layout: curves go top-to-bottom
  if (Math.abs(dy) > Math.abs(dx) * 0.3) {
    const cy1 = sy + dy * 0.4;
    const cy2 = sy + dy * 0.6;
    return `M ${sx} ${sy} C ${sx} ${cy1}, ${tx} ${cy2}, ${tx} ${ty}`;
  }

  // Horizontal or mixed: standard cubic bezier
  const cx1 = sx + dx * 0.3;
  const cx2 = sx + dx * 0.7;
  return `M ${sx} ${sy} C ${cx1} ${sy}, ${cx2} ${ty}, ${tx} ${ty}`;
}

/** Map flow type color to arrow marker ID */
function colorToArrowId(color: string): string {
  const map: Record<string, string> = {
    '#3b82f6': 'arrow-glow-blue',
    '#6b7280': 'arrow-glow-gray',
    '#22c55e': 'arrow-glow-green',
    '#f59e0b': 'arrow-glow-amber',
    '#10b981': 'arrow-glow-emerald',
    '#8b5cf6': 'arrow-glow-violet',
  };
  return map[color] || 'arrow-default';
}

export function DataFlowEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  type,
  active,
  pathId,
  pathRef,
}: DataFlowEdgeProps) {
  const style = FLOW_TYPE_STYLES[type];
  const d = computePath(sourceX, sourceY, targetX, targetY);
  const arrowId = colorToArrowId(style.color);

  return (
    <g>
      {/* Wider invisible hit area for hover/debug */}
      <path
        d={d}
        fill="none"
        stroke="transparent"
        strokeWidth={12}
      />

      {/* Visible edge */}
      <path
        id={pathId}
        ref={pathRef}
        d={d}
        fill="none"
        stroke={style.color}
        strokeWidth={active ? 2.5 : 1.5}
        strokeDasharray={style.dash || undefined}
        strokeOpacity={active ? 1 : 0.5}
        markerEnd={`url(#${arrowId})`}
      />
    </g>
  );
}

export { computePath };
