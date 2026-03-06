/**
 * TaskNode - Visual node representation for DAG
 */

import { cn } from '../../lib/utils';
import type { SwarmTask, SwarmTaskStatus } from '../../lib/swarm-types';
import { SWARM_STATUS_COLORS } from '../../lib/swarm-types';
import { formatDuration } from '../../lib/utils';

interface TaskNodeProps {
  task: SwarmTask;
  x: number;
  y: number;
  onClick?: (taskId: string) => void;
  selected?: boolean;
}

function shortModelName(model: string): string {
  if (!model) return '';
  const parts = model.split('/');
  const name = parts[parts.length - 1];
  return name.length > 12 ? name.slice(0, 10) + '..' : name;
}

const STATUS_BG: Record<SwarmTaskStatus, string> = {
  pending: 'bg-gray-800 border-gray-600',
  ready: 'bg-blue-900/30 border-blue-500/50',
  dispatched: 'bg-amber-900/30 border-amber-500/50',
  completed: 'bg-emerald-900/30 border-emerald-500/50',
  failed: 'bg-red-900/30 border-red-500/50',
  skipped: 'bg-gray-800/50 border-gray-600/50',
};

export function TaskNode({ task, onClick, selected }: TaskNodeProps) {
  const desc = task.description.length > 40 ? task.description.slice(0, 37) + '...' : task.description;

  return (
    <div
      className={cn(
        'w-44 rounded-lg border px-2.5 py-2 cursor-pointer transition-all hover:ring-1 hover:ring-white/20',
        STATUS_BG[task.status],
        selected && 'ring-2 ring-blue-400',
        task.status === 'skipped' && 'opacity-50 line-through'
      )}
      onClick={() => onClick?.(task.id)}
    >
      {/* Header */}
      <div className="flex items-center gap-1.5 mb-1">
        <span
          className="h-2 w-2 rounded-full shrink-0"
          style={{ backgroundColor: SWARM_STATUS_COLORS[task.status] }}
        />
        <span className="text-[10px] font-mono text-gray-400">{task.id}</span>
        {task.assignedModel && (
          <span className="text-[9px] text-gray-500 ml-auto">{shortModelName(task.assignedModel)}</span>
        )}
      </div>

      {/* Description */}
      <div className="text-xs text-gray-300 leading-tight">{desc}</div>

      {/* Footer */}
      {task.result && (
        <div className="mt-1 flex items-center gap-2 text-[10px] text-gray-500">
          <span>{formatDuration(task.result.durationMs)}</span>
          {task.result.qualityScore !== undefined && (
            <span className="text-yellow-400/70">{task.result.qualityScore}/5</span>
          )}
        </div>
      )}

      {/* Active indicator */}
      {task.status === 'dispatched' && (
        <div className="mt-1 h-0.5 bg-amber-500/30 rounded overflow-hidden">
          <div className="h-full w-1/3 bg-amber-500 rounded animate-pulse" />
        </div>
      )}
    </div>
  );
}
