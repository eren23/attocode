/**
 * DataPacket - Animated packet SVG element.
 *
 * Renders a small circle with glow filter and trailing circles behind it.
 */

interface DataPacketProps {
  x: number;
  y: number;
  color: string;
  size: number;
  opacity: number;
  /** Previous positions for trail effect */
  trail?: Array<{ x: number; y: number }>;
  /** Filter ID for glow effect */
  filterId?: string;
}

/** Map a hex color to the nearest glow filter ID */
function colorToFilterId(color: string): string {
  const map: Record<string, string> = {
    '#3b82f6': 'glow-blue',
    '#6b7280': 'glow-gray',
    '#22c55e': 'glow-green',
    '#f59e0b': 'glow-amber',
    '#10b981': 'glow-emerald',
    '#8b5cf6': 'glow-violet',
  };
  return map[color] || 'glow-blue';
}

export function DataPacket({ x, y, color, size, opacity, trail, filterId }: DataPacketProps) {
  const resolvedFilter = filterId || colorToFilterId(color);

  return (
    <g>
      {/* Trail circles (fading) */}
      {trail && trail.map((pos, i) => {
        const trailOpacity = opacity * (0.15 + (i / trail.length) * 0.25);
        const trailSize = size * (0.4 + (i / trail.length) * 0.3);
        return (
          <circle
            key={i}
            cx={pos.x}
            cy={pos.y}
            r={trailSize}
            fill={color}
            opacity={trailOpacity}
          />
        );
      })}

      {/* Main packet circle with glow */}
      <circle
        cx={x}
        cy={y}
        r={size}
        fill={color}
        opacity={opacity}
        filter={`url(#${resolvedFilter})`}
      />
    </g>
  );
}
