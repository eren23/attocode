/**
 * TaskDAGPanel - Task dependency graph visualization
 *
 * Uses a simple wave-based layout where tasks are arranged in columns by wave,
 * with SVG arrows for dependency edges.
 */

import { useMemo, useState } from 'react';
import type { SwarmTask } from '../../lib/swarm-types';
import { SWARM_STATUS_COLORS } from '../../lib/swarm-types';
import { TaskNode } from './TaskNode';
import { TaskInspector } from './TaskInspector';

interface TaskDAGPanelProps {
  tasks: SwarmTask[];
  edges: [string, string][];
}

// Layout constants
const NODE_WIDTH = 176; // w-44 = 11rem = 176px
const NODE_HEIGHT = 72;
const H_GAP = 40;
const V_GAP = 16;
const PADDING = 20;

interface NodePosition {
  id: string;
  x: number;
  y: number;
}

function computeLayout(tasks: SwarmTask[]): NodePosition[] {
  // Group tasks by wave
  const waveGroups = new Map<number, SwarmTask[]>();
  for (const task of tasks) {
    const wave = task.wave;
    if (!waveGroups.has(wave)) waveGroups.set(wave, []);
    waveGroups.get(wave)!.push(task);
  }

  const positions: NodePosition[] = [];
  const waves = Array.from(waveGroups.keys()).sort((a, b) => a - b);

  for (let col = 0; col < waves.length; col++) {
    const waveTasks = waveGroups.get(waves[col])!;
    const x = PADDING + col * (NODE_WIDTH + H_GAP);

    for (let row = 0; row < waveTasks.length; row++) {
      const y = PADDING + row * (NODE_HEIGHT + V_GAP);
      positions.push({ id: waveTasks[row].id, x, y });
    }
  }

  return positions;
}

export function TaskDAGPanel({ tasks, edges }: TaskDAGPanelProps) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  const positions = useMemo(() => computeLayout(tasks), [tasks]);

  const positionMap = useMemo(() => {
    const map = new Map<string, NodePosition>();
    for (const pos of positions) {
      map.set(pos.id, pos);
    }
    return map;
  }, [positions]);

  const taskMap = useMemo(() => {
    const map = new Map<string, SwarmTask>();
    for (const task of tasks) map.set(task.id, task);
    return map;
  }, [tasks]);

  const selectedTask = selectedTaskId ? taskMap.get(selectedTaskId) ?? null : null;

  // Compute SVG dimensions
  const maxX = positions.reduce((max, p) => Math.max(max, p.x), 0) + NODE_WIDTH + PADDING;
  const maxY = positions.reduce((max, p) => Math.max(max, p.y), 0) + NODE_HEIGHT + PADDING;

  if (tasks.length === 0) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Task DAG</h3>
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
          No tasks yet
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-400 mb-3">Task DAG</h3>

      <div className="overflow-auto max-h-96" style={{ maxWidth: '100%' }}>
        <div className="relative" style={{ width: maxX, height: maxY, minWidth: '100%' }}>
          {/* SVG layer for edges */}
          <svg
            className="absolute inset-0 pointer-events-none"
            width={maxX}
            height={maxY}
          >
            <defs>
              <marker
                id="arrowhead"
                markerWidth="8"
                markerHeight="6"
                refX="8"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill="#6b7280" />
              </marker>
            </defs>
            {edges.map(([from, to], i) => {
              const fromPos = positionMap.get(from);
              const toPos = positionMap.get(to);
              if (!fromPos || !toPos) return null;

              const x1 = fromPos.x + NODE_WIDTH;
              const y1 = fromPos.y + NODE_HEIGHT / 2;
              const x2 = toPos.x;
              const y2 = toPos.y + NODE_HEIGHT / 2;

              // Check if the edge connects to an active task
              const fromTask = taskMap.get(from);
              const toTask = taskMap.get(to);
              const isActive = fromTask?.status === 'dispatched' || toTask?.status === 'dispatched';

              return (
                <path
                  key={i}
                  d={`M ${x1} ${y1} C ${x1 + H_GAP / 2} ${y1}, ${x2 - H_GAP / 2} ${y2}, ${x2} ${y2}`}
                  fill="none"
                  stroke={isActive ? '#f59e0b' : '#4b5563'}
                  strokeWidth={isActive ? 2 : 1}
                  markerEnd="url(#arrowhead)"
                  className={isActive ? 'animate-pulse' : ''}
                />
              );
            })}
          </svg>

          {/* Task nodes */}
          {positions.map((pos) => {
            const task = taskMap.get(pos.id);
            if (!task) return null;
            return (
              <div
                key={pos.id}
                className="absolute"
                style={{ left: pos.x, top: pos.y }}
              >
                <TaskNode
                  task={task}
                  x={pos.x}
                  y={pos.y}
                  onClick={setSelectedTaskId}
                  selected={selectedTaskId === pos.id}
                />
              </div>
            );
          })}
        </div>
      </div>

      {/* Wave labels */}
      <div className="mt-2 flex gap-1 text-[10px] text-gray-500">
        <span>Status:</span>
        {(['pending', 'ready', 'dispatched', 'completed', 'failed'] as const).map((s) => (
          <span key={s} className="flex items-center gap-0.5">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: SWARM_STATUS_COLORS[s] }} />
            {s}
          </span>
        ))}
      </div>

      {/* Task Inspector slide-out */}
      <TaskInspector task={selectedTask} onClose={() => setSelectedTaskId(null)} />
    </div>
  );
}
