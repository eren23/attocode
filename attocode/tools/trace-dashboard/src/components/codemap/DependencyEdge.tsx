/**
 * DependencyEdge - SVG edge between file nodes in the code map
 *
 * Renders a bezier curve with an arrowhead, using the same pattern as TaskDAGPanel.
 * Test->non-test edges use a dashed stroke.
 */

interface DependencyEdgeProps {
  /** Source node center X */
  x1: number;
  /** Source node center Y */
  y1: number;
  /** Target node center X */
  x2: number;
  /** Target node center Y */
  y2: number;
  /** Whether this edge is highlighted (connected to hovered/selected node) */
  highlighted: boolean;
  /** Whether source is a test file */
  isTestEdge: boolean;
  /** Unique key for the arrowhead marker */
  markerId: string;
}

export function DependencyEdge({
  x1,
  y1,
  x2,
  y2,
  highlighted,
  isTestEdge,
  markerId,
}: DependencyEdgeProps) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const dist = Math.sqrt(dx * dx + dy * dy);

  // Compute control points for a smooth bezier curve
  const curvature = Math.min(dist * 0.3, 80);
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;

  // Offset perpendicular to the line to create a slight arc
  const perpX = -dy / (dist || 1);
  const perpY = dx / (dist || 1);
  const offsetAmount = curvature * 0.3;

  const cx = midX + perpX * offsetAmount;
  const cy = midY + perpY * offsetAmount;

  const strokeColor = highlighted ? '#94a3b8' : '#4b5563';
  const strokeWidth = highlighted ? 1.5 : 0.8;
  const strokeOpacity = highlighted ? 0.9 : 0.4;

  return (
    <>
      <defs>
        <marker
          id={markerId}
          markerWidth="6"
          markerHeight="5"
          refX="6"
          refY="2.5"
          orient="auto"
        >
          <polygon
            points="0 0, 6 2.5, 0 5"
            fill={strokeColor}
            opacity={strokeOpacity}
          />
        </marker>
      </defs>
      <path
        d={`M ${x1} ${y1} Q ${cx} ${cy}, ${x2} ${y2}`}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeOpacity={strokeOpacity}
        strokeDasharray={isTestEdge ? '4,3' : 'none'}
        markerEnd={`url(#${markerId})`}
      />
    </>
  );
}
