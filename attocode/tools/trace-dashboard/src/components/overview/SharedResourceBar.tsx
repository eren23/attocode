/**
 * SharedResourceBar - Stacked bar showing shared resource usage
 *
 * Uses Recharts BarChart with 3 stacked segments for Blackboard Findings,
 * Cache Entries, and Budget Used percentage.
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

interface SharedResourceBarProps {
  blackboardFindings: number;
  cacheEntries: number;
  budgetUsedPercent: number;
}

const COLORS = {
  findings: '#a855f7',  // purple
  cache: '#06b6d4',     // cyan
  budget: '#22c55e',    // green
};

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    name: string;
    value: number;
    payload: { name: string; value: number; color: string; unit: string };
  }>;
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0].payload;
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg shadow-xl p-2 text-xs">
      <div className="text-gray-200 font-medium">{item.name}</div>
      <div className="text-gray-400">
        {item.value}{item.unit}
      </div>
    </div>
  );
}

export function SharedResourceBar({
  blackboardFindings,
  cacheEntries,
  budgetUsedPercent,
}: SharedResourceBarProps) {
  const data = [
    {
      name: 'Blackboard Findings',
      value: blackboardFindings,
      color: COLORS.findings,
      unit: ' findings',
    },
    {
      name: 'Cache Entries',
      value: cacheEntries,
      color: COLORS.cache,
      unit: ' entries',
    },
    {
      name: 'Budget Used',
      value: Math.round(budgetUsedPercent),
      color: COLORS.budget,
      unit: '%',
    },
  ];

  return (
    <div>
      {/* Bar chart */}
      <ResponsiveContainer width="100%" height={80}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            width={130}
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <RechartsTooltip
            content={<CustomTooltip />}
            cursor={{ fill: 'rgba(107, 114, 128, 0.1)' }}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={16}>
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.color} fillOpacity={0.7} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Inline values */}
      <div className="flex items-center justify-between mt-2 px-1">
        {data.map((item) => (
          <div key={item.name} className="flex items-center gap-1.5">
            <span
              className="w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: item.color }}
            />
            <span className="text-[10px] text-gray-400">{item.name}:</span>
            <span className="text-[10px] text-gray-200 font-medium tabular-nums">
              {item.value}{item.unit}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
