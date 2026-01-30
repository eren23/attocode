/**
 * Timeline Component
 *
 * Displays session events in chronological order.
 */

import { useState } from 'react';
import { cn, formatDuration, getNodeTypeColor } from '../lib/utils';
import type { TimelineEntry } from '../lib/types';

interface TimelineProps {
  entries: TimelineEntry[];
  startTime: string;
}

export function Timeline({ entries, startTime }: TimelineProps) {
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const toggleExpand = (index: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const importanceColors = {
    high: 'border-red-500',
    normal: 'border-gray-600',
    low: 'border-gray-700',
  };

  const typeIcons: Record<string, JSX.Element> = {
    'iteration.start': (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 9l3 3m0 0l-3 3m3-3H8m13 0a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    'llm.request': (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    ),
    'llm.response': (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    'tool.execution': (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    error: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    ),
    decision: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  };

  const getIcon = (type: string) => {
    for (const [key, icon] of Object.entries(typeIcons)) {
      if (type.includes(key)) return icon;
    }
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    );
  };

  return (
    <div className="relative">
      {/* Vertical line */}
      <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-gray-700" />

      <div className="space-y-4">
        {entries.map((entry, index) => {
          const isExpanded = expandedIds.has(index);
          const hasDetails = entry.details && Object.keys(entry.details).length > 0;

          return (
            <div
              key={index}
              className={cn(
                'relative pl-14',
                hasDetails && 'cursor-pointer'
              )}
              onClick={() => hasDetails && toggleExpand(index)}
            >
              {/* Timeline dot */}
              <div
                className={cn(
                  'absolute left-4 w-5 h-5 rounded-full border-2 bg-gray-900 flex items-center justify-center',
                  importanceColors[entry.importance]
                )}
              >
                <div className="text-gray-400">
                  {getIcon(entry.type)}
                </div>
              </div>

              {/* Content */}
              <div
                className={cn(
                  'bg-gray-800/50 border border-gray-700 rounded-lg p-3',
                  hasDetails && 'hover:border-gray-600 transition-colors'
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'text-xs font-medium px-2 py-0.5 rounded',
                        getNodeTypeColor(entry.type.split('.')[0])
                      )}
                    >
                      {entry.type}
                    </span>
                    {entry.iteration !== undefined && (
                      <span className="text-xs text-gray-500">
                        Iteration #{entry.iteration}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span>+{formatDuration(entry.relativeMs)}</span>
                    {entry.durationMs !== undefined && (
                      <span className="text-gray-600">
                        ({formatDuration(entry.durationMs)})
                      </span>
                    )}
                  </div>
                </div>

                <p className="mt-1 text-sm text-gray-300">{entry.description}</p>

                {/* Expanded details */}
                {isExpanded && hasDetails && (
                  <div className="mt-3 pt-3 border-t border-gray-700">
                    <pre className="text-xs text-gray-400 overflow-x-auto">
                      {JSON.stringify(entry.details, null, 2)}
                    </pre>
                  </div>
                )}

                {hasDetails && (
                  <div className="mt-2 text-xs text-gray-500">
                    {isExpanded ? 'Click to collapse' : 'Click to expand details'}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
