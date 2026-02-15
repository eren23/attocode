/**
 * SvgFilters - Shared SVG <defs> with glow filters for animated packets.
 *
 * Each filter creates a colored glow effect using Gaussian blur + flood fill.
 * Filters are named by color key for easy reference from DataPacket components.
 */

export function SvgFilters(): JSX.Element {
  const filters: Array<{ id: string; color: string }> = [
    { id: 'glow-blue', color: '#3b82f6' },
    { id: 'glow-gray', color: '#6b7280' },
    { id: 'glow-green', color: '#22c55e' },
    { id: 'glow-amber', color: '#f59e0b' },
    { id: 'glow-emerald', color: '#10b981' },
    { id: 'glow-violet', color: '#8b5cf6' },
  ];

  return (
    <defs>
      {filters.map(({ id, color }) => (
        <filter key={id} id={id} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
          <feFlood floodColor={color} floodOpacity="0.6" result="color" />
          <feComposite in="color" in2="blur" operator="in" result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      ))}

      {/* Arrow markers for each flow color */}
      {filters.map(({ id, color }) => (
        <marker
          key={`arrow-${id}`}
          id={`arrow-${id}`}
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" fill={color} fillOpacity="0.7" />
        </marker>
      ))}

      {/* Default arrow marker */}
      <marker
        id="arrow-default"
        markerWidth="8"
        markerHeight="6"
        refX="8"
        refY="3"
        orient="auto"
      >
        <polygon points="0 0, 8 3, 0 6" fill="#4b5563" />
      </marker>
    </defs>
  );
}
