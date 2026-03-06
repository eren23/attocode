/**
 * QualityHeatmapPanel - Color grid showing quality scores per task
 */

import { useState } from 'react';
import type { SwarmTask } from '../../lib/swarm-types';
import { cn } from '../../lib/utils';

interface QualityHeatmapPanelProps {
  tasks: SwarmTask[];
  onTaskClick?: (taskId: string) => void;
}

function getQualityColor(score: number | undefined): string {
  if (score === undefined) return 'bg-gray-700';
  if (score >= 5) return 'bg-green-500';
  if (score >= 4) return 'bg-lime-500';
  if (score >= 3) return 'bg-yellow-500';
  if (score >= 2) return 'bg-orange-500';
  return 'bg-red-500';
}

export function QualityHeatmapPanel({ tasks, onTaskClick }: QualityHeatmapPanelProps) {
  const [hoveredTask, setHoveredTask] = useState<SwarmTask | null>(null);

  const scoredTasks = tasks.filter((t) => t.status === 'completed' || t.status === 'failed' || t.result);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-400 mb-3">Quality Heatmap</h3>

      {scoredTasks.length === 0 ? (
        <div className="flex items-center justify-center h-24 text-gray-500 text-sm">
          No quality data
        </div>
      ) : (
        <div className="relative">
          <div className="grid grid-cols-6 gap-1">
            {tasks.map((task) => (
              <button
                key={task.id}
                className={cn(
                  'h-8 rounded-sm cursor-pointer transition-all hover:ring-1 hover:ring-white/30',
                  getQualityColor(task.result?.qualityScore),
                  task.status === 'pending' || task.status === 'ready' ? 'opacity-30' : '',
                  task.status === 'skipped' ? 'opacity-20 line-through' : ''
                )}
                onMouseEnter={() => setHoveredTask(task)}
                onMouseLeave={() => setHoveredTask(null)}
                onClick={() => onTaskClick?.(task.id)}
                title={`${task.id}: ${task.description.slice(0, 50)}`}
              />
            ))}
          </div>

          {/* Hover tooltip */}
          {hoveredTask && (
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 bg-gray-800 border border-gray-700 rounded-lg p-2 text-xs z-10 w-60 shadow-lg">
              <div className="font-medium text-white truncate">{hoveredTask.description}</div>
              <div className="mt-1 flex items-center gap-2 text-gray-400">
                <span>Task {hoveredTask.id}</span>
                <span>Wave {hoveredTask.wave}</span>
                {hoveredTask.result?.qualityScore !== undefined && (
                  <span className="text-yellow-400">
                    Score: {hoveredTask.result.qualityScore}/5
                  </span>
                )}
              </div>
              {hoveredTask.result?.qualityFeedback && (
                <div className="mt-1 text-gray-500 truncate">
                  {hoveredTask.result.qualityFeedback}
                </div>
              )}
            </div>
          )}

          {/* Legend */}
          <div className="mt-2 flex items-center gap-1 text-[10px] text-gray-500">
            <span>Quality:</span>
            <span className="h-2 w-4 bg-red-500 rounded-sm" />1
            <span className="h-2 w-4 bg-orange-500 rounded-sm" />2
            <span className="h-2 w-4 bg-yellow-500 rounded-sm" />3
            <span className="h-2 w-4 bg-lime-500 rounded-sm" />4
            <span className="h-2 w-4 bg-green-500 rounded-sm" />5
            <span className="h-2 w-4 bg-gray-700 rounded-sm" />N/A
          </div>
        </div>
      )}
    </div>
  );
}
