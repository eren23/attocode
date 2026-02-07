/**
 * ModelDistributionPanel - Pie chart + stats table for model usage
 */

import { useMemo } from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { formatTokens, formatCost } from '../../lib/utils';
import type { SwarmLiveState, ModelUsageEntry } from '../../lib/swarm-types';

interface ModelDistributionPanelProps {
  state: SwarmLiveState | null;
}

const MODEL_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
];

function shortModelName(model: string): string {
  const parts = model.split('/');
  return parts[parts.length - 1];
}

export function ModelDistributionPanel({ state }: ModelDistributionPanelProps) {
  const modelUsage = useMemo((): ModelUsageEntry[] => {
    if (!state?.tasks) return [];

    const map = new Map<string, { tasks: number; tokens: number; cost: number; qualityScores: number[] }>();

    for (const task of state.tasks) {
      const model = task.assignedModel ?? task.result?.model;
      if (!model) continue;

      if (!map.has(model)) {
        map.set(model, { tasks: 0, tokens: 0, cost: 0, qualityScores: [] });
      }
      const entry = map.get(model)!;
      entry.tasks++;
      if (task.result) {
        entry.tokens += task.result.tokensUsed;
        entry.cost += task.result.costUsed;
        if (task.result.qualityScore !== undefined) {
          entry.qualityScores.push(task.result.qualityScore);
        }
      }
    }

    return Array.from(map.entries()).map(([model, data]) => ({
      model,
      tasks: data.tasks,
      tokensUsed: data.tokens,
      costUsed: data.cost,
      avgQualityScore:
        data.qualityScores.length > 0
          ? data.qualityScores.reduce((a, b) => a + b, 0) / data.qualityScores.length
          : null,
    }));
  }, [state?.tasks]);

  const pieData = modelUsage.map((m) => ({
    name: shortModelName(m.model),
    value: m.tasks,
  }));

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-400 mb-3">Model Distribution</h3>

      {modelUsage.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
          No model data
        </div>
      ) : (
        <>
          <div className="h-36">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={30}
                  outerRadius={55}
                  dataKey="value"
                  strokeWidth={1}
                  stroke="#1f2937"
                >
                  {pieData.map((_entry, i) => (
                    <Cell key={i} fill={MODEL_COLORS[i % MODEL_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: '6px' }}
                  labelStyle={{ color: '#9ca3af' }}
                  itemStyle={{ color: '#e5e7eb' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Stats table */}
          <div className="mt-2 space-y-1">
            {modelUsage.map((m, i) => (
              <div key={m.model} className="flex items-center gap-2 text-xs">
                <span
                  className="h-2.5 w-2.5 rounded-sm shrink-0"
                  style={{ backgroundColor: MODEL_COLORS[i % MODEL_COLORS.length] }}
                />
                <span className="text-gray-300 truncate flex-1">{shortModelName(m.model)}</span>
                <span className="text-gray-500">{m.tasks}t</span>
                <span className="text-gray-500">{formatTokens(m.tokensUsed)}</span>
                <span className="text-gray-500">{formatCost(m.costUsed)}</span>
                {m.avgQualityScore !== null && (
                  <span className="text-gray-500">{m.avgQualityScore.toFixed(1)}</span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
