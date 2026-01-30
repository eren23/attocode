/**
 * Token Flow Chart Component
 *
 * Displays token usage over iterations using Recharts.
 */

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { formatTokens } from '../lib/utils';

interface TokenFlowData {
  perIteration: Array<{
    iteration: number;
    input: number;
    output: number;
    thinking?: number;
    cached: number;
    fresh: number;
  }>;
  cumulative: Array<{
    iteration: number;
    totalInput: number;
    totalOutput: number;
    totalCached: number;
  }>;
  costBreakdown: {
    inputCost: number;
    outputCost: number;
    cachedCost: number;
    totalCost: number;
    savings: number;
  };
}

interface TokenFlowChartProps {
  data: TokenFlowData;
  mode?: 'per-iteration' | 'cumulative';
}

export function TokenFlowChart({ data, mode = 'per-iteration' }: TokenFlowChartProps) {
  const chartData = mode === 'per-iteration'
    ? data.perIteration.map((d) => ({
        name: `#${d.iteration}`,
        input: d.input,
        output: d.output,
        cached: d.cached,
        thinking: d.thinking || 0,
      }))
    : data.cumulative.map((d) => ({
        name: `#${d.iteration}`,
        input: d.totalInput,
        output: d.totalOutput,
        cached: d.totalCached,
      }));

  const CustomTooltip = ({ active, payload, label }: {
    active?: boolean;
    payload?: Array<{ name: string; value: number; color: string }>;
    label?: string;
  }) => {
    if (!active || !payload) return null;

    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-lg">
        <p className="text-sm font-medium text-gray-200 mb-2">Iteration {label}</p>
        {payload.map((entry) => (
          <p key={entry.name} className="text-sm" style={{ color: entry.color }}>
            {entry.name}: {formatTokens(entry.value)}
          </p>
        ))}
      </div>
    );
  };

  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="colorInput" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.1} />
            </linearGradient>
            <linearGradient id="colorOutput" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#22c55e" stopOpacity={0.8} />
              <stop offset="95%" stopColor="#22c55e" stopOpacity={0.1} />
            </linearGradient>
            <linearGradient id="colorCached" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.8} />
              <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.1} />
            </linearGradient>
            <linearGradient id="colorThinking" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.8} />
              <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.1} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            dataKey="name"
            stroke="#9ca3af"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
          />
          <YAxis
            stroke="#9ca3af"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            tickFormatter={(value) => formatTokens(value)}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ paddingTop: 10 }}
            formatter={(value) => <span className="text-gray-300">{value}</span>}
          />
          <Area
            type="monotone"
            dataKey="cached"
            name="Cached"
            stackId="1"
            stroke="#8b5cf6"
            fill="url(#colorCached)"
          />
          <Area
            type="monotone"
            dataKey="input"
            name="Input"
            stackId="1"
            stroke="#3b82f6"
            fill="url(#colorInput)"
          />
          <Area
            type="monotone"
            dataKey="output"
            name="Output"
            stackId="1"
            stroke="#22c55e"
            fill="url(#colorOutput)"
          />
          {mode === 'per-iteration' && (
            <Area
              type="monotone"
              dataKey="thinking"
              name="Thinking"
              stackId="1"
              stroke="#f59e0b"
              fill="url(#colorThinking)"
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Cost Breakdown Chart
 */
interface CostBreakdownChartProps {
  costBreakdown: {
    inputCost: number;
    outputCost: number;
    cachedCost: number;
    totalCost: number;
    savings: number;
  };
}

export function CostBreakdownChart({ costBreakdown }: CostBreakdownChartProps) {
  const data = [
    { name: 'Input', value: costBreakdown.inputCost, fill: '#3b82f6' },
    { name: 'Output', value: costBreakdown.outputCost, fill: '#22c55e' },
    { name: 'Cached', value: costBreakdown.cachedCost, fill: '#8b5cf6' },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        {data.map((item) => (
          <div key={item.name} className="text-center">
            <div
              className="h-2 rounded-full mb-2"
              style={{ backgroundColor: item.fill }}
            />
            <p className="text-sm text-gray-400">{item.name}</p>
            <p className="text-lg font-bold text-white">${item.value.toFixed(4)}</p>
          </div>
        ))}
      </div>
      <div className="flex justify-between items-center pt-4 border-t border-gray-700">
        <div>
          <p className="text-sm text-gray-400">Total Cost</p>
          <p className="text-xl font-bold text-white">${costBreakdown.totalCost.toFixed(4)}</p>
        </div>
        <div className="text-right">
          <p className="text-sm text-gray-400">Saved by Cache</p>
          <p className="text-xl font-bold text-green-400">${costBreakdown.savings.toFixed(4)}</p>
        </div>
      </div>
    </div>
  );
}
