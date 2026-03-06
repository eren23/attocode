/**
 * RadialGauge - Reusable SVG radial gauge component
 */

interface RadialGaugeProps {
  value: number;
  max: number;
  label: string;
  sublabel?: string;
  size?: number;
}

export function RadialGauge({ value, max, label, sublabel, size = 120 }: RadialGaugeProps) {
  const percent = max > 0 ? Math.min(value / max, 1) : 0;
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference * (1 - percent);
  const center = size / 2;

  // Color gradient: green → yellow → red
  const color = percent > 0.9
    ? '#ef4444'
    : percent > 0.7
      ? '#f59e0b'
      : percent > 0.4
        ? '#eab308'
        : '#10b981';

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} className="transform -rotate-90">
        {/* Background track */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#374151"
          strokeWidth={8}
        />
        {/* Filled arc */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          className="transition-all duration-500 ease-out"
        />
      </svg>
      {/* Center text */}
      <div className="absolute flex flex-col items-center justify-center" style={{ width: size, height: size }}>
        <span className="text-lg font-bold text-white">{(percent * 100).toFixed(0)}%</span>
      </div>
      <span className="mt-1 text-xs font-medium text-gray-400">{label}</span>
      {sublabel && <span className="text-xs text-gray-500">{sublabel}</span>}
    </div>
  );
}
