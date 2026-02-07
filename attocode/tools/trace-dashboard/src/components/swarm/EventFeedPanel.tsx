/**
 * EventFeedPanel - Scrolling event log with filters
 */

import { useState, useRef, useEffect } from 'react';
import type { TimestampedSwarmEvent, SwarmEventType } from '../../lib/swarm-types';
import { EventRow } from './EventRow';
import { cn } from '../../lib/utils';

interface EventFeedPanelProps {
  events: TimestampedSwarmEvent[];
}

type FilterCategory = 'task' | 'wave' | 'quality' | 'error' | 'budget';

const CATEGORY_TYPES: Record<FilterCategory, SwarmEventType[]> = {
  task: ['swarm.task.dispatched', 'swarm.task.completed', 'swarm.task.failed', 'swarm.task.skipped'],
  wave: ['swarm.wave.start', 'swarm.wave.complete', 'swarm.start', 'swarm.complete'],
  quality: ['swarm.quality.rejected'],
  error: ['swarm.error', 'swarm.task.failed'],
  budget: ['swarm.budget.update'],
};

export function EventFeedPanel({ events }: EventFeedPanelProps) {
  const [filters, setFilters] = useState<Set<FilterCategory>>(
    new Set(['task', 'wave', 'quality', 'error'])
  );
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const toggleFilter = (cat: FilterCategory) => {
    setFilters((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) {
        next.delete(cat);
      } else {
        next.add(cat);
      }
      return next;
    });
  };

  // Compute allowed event types from active filters
  const allowedTypes = new Set<string>();
  for (const cat of filters) {
    for (const t of CATEGORY_TYPES[cat]) {
      allowedTypes.add(t);
    }
  }

  const filteredEvents = events.filter((e) => allowedTypes.has(e.event.type));

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredEvents.length, autoScroll]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-gray-400">Event Feed</h3>
        <div className="flex items-center gap-2">
          {(['task', 'wave', 'quality', 'error', 'budget'] as FilterCategory[]).map((cat) => (
            <button
              key={cat}
              onClick={() => toggleFilter(cat)}
              className={cn(
                'px-1.5 py-0.5 rounded text-[10px] font-medium border transition-colors',
                filters.has(cat)
                  ? 'bg-gray-700 text-gray-200 border-gray-600'
                  : 'bg-transparent text-gray-500 border-gray-700 hover:text-gray-400'
              )}
            >
              {cat}
            </button>
          ))}
          <button
            onClick={() => setAutoScroll((prev) => !prev)}
            className={cn(
              'px-1.5 py-0.5 rounded text-[10px] border',
              autoScroll
                ? 'text-blue-400 border-blue-500/30'
                : 'text-gray-500 border-gray-700'
            )}
          >
            auto-scroll
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-0 max-h-64 space-y-0"
      >
        {filteredEvents.length === 0 ? (
          <div className="flex items-center justify-center h-20 text-gray-500 text-xs">
            No events yet
          </div>
        ) : (
          filteredEvents.map((event, i) => (
            <EventRow key={`${event.seq}-${i}`} event={event} />
          ))
        )}
      </div>
    </div>
  );
}
