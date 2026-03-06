/**
 * WorkerTimelinePanel - Gantt-style horizontal bar chart for task execution
 *
 * V9: Shows dispatched (in-progress) tasks with estimated elapsed time,
 * not just completed tasks.
 */

import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import type { SwarmTask } from '../../lib/swarm-types';
import { formatDuration } from '../../lib/utils';

interface WorkerTimelinePanelProps {
  tasks: SwarmTask[];
}

const MODEL_COLORS: Record<string, string> = {};
const COLOR_PALETTE = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
];
let colorIdx = 0;

function getModelColor(model: string): string {
  if (!MODEL_COLORS[model]) {
    MODEL_COLORS[model] = COLOR_PALETTE[colorIdx % COLOR_PALETTE.length];
    colorIdx++;
  }
  return MODEL_COLORS[model];
}

function shortModelName(model: string): string {
  const parts = model.split('/');
  const name = parts[parts.length - 1];
  return name.length > 20 ? name.slice(0, 17) + '...' : name;
}

interface TimelineBar {
  name: string;
  duration: number;
  model: string;
  status: string;
  wave: number;
  inProgress: boolean;
}

export function WorkerTimelinePanel({ tasks }: WorkerTimelinePanelProps) {
  const data = useMemo((): TimelineBar[] => {
    const now = Date.now();
    return tasks
      .filter((t) => t.result?.durationMs || t.status === 'dispatched')
      .sort((a, b) => a.wave - b.wave || a.id.localeCompare(b.id))
      .map((t) => {
        const isDispatched = t.status === 'dispatched';
        // For dispatched tasks, estimate elapsed time from dispatchedAt or fallback
        const durationMs = isDispatched
          ? (t.dispatchedAt ? now - t.dispatchedAt : 0)
          : t.result!.durationMs;
        return {
          name: t.id,
          duration: durationMs / 1000,
          model: t.assignedModel ?? t.result?.model ?? 'unknown',
          status: t.status,
          wave: t.wave,
          inProgress: isDispatched,
        };
      });
  }, [tasks]);

  if (data.length === 0) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Worker Timeline</h3>
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
          No execution data yet
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-400 mb-3">Worker Timeline</h3>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 40, right: 10 }}>
            <XAxis
              type="number"
              tickFormatter={(v: number) => `${v.toFixed(0)}s`}
              stroke="#6b7280"
              tick={{ fill: '#9ca3af', fontSize: 10 }}
            />
            <YAxis
              type="category"
              dataKey="name"
              stroke="#6b7280"
              tick={{ fill: '#9ca3af', fontSize: 10 }}
              width={40}
            />
            <Tooltip
              contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: '6px' }}
              labelStyle={{ color: '#9ca3af' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(value: any, _name: any, props: any) => {
                const v = Number(value);
                const entry = props?.payload as TimelineBar | undefined;
                if (!entry) return [`${formatDuration(v * 1000)}`, 'Duration'];
                const suffix = entry.inProgress ? ' (in progress)' : '';
                return [
                  `${formatDuration(v * 1000)} — ${shortModelName(entry.model)} (Wave ${entry.wave})${suffix}`,
                  'Duration',
                ];
              }}
            />
            <Bar dataKey="duration" radius={[0, 4, 4, 0]}>
              {data.map((entry, i) => (
                <Cell
                  key={i}
                  fill={getModelColor(entry.model)}
                  opacity={entry.inProgress ? 0.5 : 1}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="mt-2 flex flex-wrap gap-2">
        {Array.from(new Set(data.map((d) => d.model))).map((model) => (
          <div key={model} className="flex items-center gap-1 text-[10px] text-gray-400">
            <span
              className="h-2 w-3 rounded-sm"
              style={{ backgroundColor: getModelColor(model) }}
            />
            {shortModelName(model)}
          </div>
        ))}
      </div>
    </div>
  );
}
