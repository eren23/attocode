/**
 * EventRow - Single event in the feed
 */

import type { TimestampedSwarmEvent, SwarmEventType } from '../../lib/swarm-types';
import { getEventMessage } from '../../lib/swarm-types';
import { cn } from '../../lib/utils';

interface EventRowProps {
  event: TimestampedSwarmEvent;
}

const EVENT_TYPE_COLORS: Partial<Record<SwarmEventType, string>> = {
  'swarm.start': 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  'swarm.wave.start': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'swarm.wave.complete': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  'swarm.task.dispatched': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  'swarm.task.completed': 'bg-green-500/20 text-green-400 border-green-500/30',
  'swarm.task.failed': 'bg-red-500/20 text-red-400 border-red-500/30',
  'swarm.task.skipped': 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  'swarm.quality.rejected': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  'swarm.budget.update': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  'swarm.complete': 'bg-green-500/20 text-green-400 border-green-500/30',
  'swarm.error': 'bg-red-500/20 text-red-400 border-red-500/30',
};

function getShortType(type: string): string {
  return type.replace('swarm.', '');
}

function formatRelativeTime(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 5) return 'now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  return d.toLocaleTimeString();
}

export function EventRow({ event }: EventRowProps) {
  const colorClass = EVENT_TYPE_COLORS[event.event.type as SwarmEventType] ?? 'bg-gray-500/20 text-gray-400 border-gray-500/30';
  const message = getEventMessage(event);

  return (
    <div className="flex items-start gap-2 py-1.5 px-2 hover:bg-gray-800/50 rounded text-xs">
      <span className="text-gray-500 shrink-0 w-12 text-right tabular-nums">
        {formatRelativeTime(event.ts)}
      </span>
      <span className={cn('shrink-0 px-1.5 py-0.5 rounded border text-[10px] font-mono', colorClass)}>
        {getShortType(event.event.type)}
      </span>
      <span className="text-gray-300 truncate">{message}</span>
    </div>
  );
}
