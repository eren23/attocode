/**
 * WaveProgressStrip - Horizontal strip showing wave progress
 */

import type { SwarmLiveState, SwarmTask } from '../../lib/swarm-types';
import { cn } from '../../lib/utils';

interface WaveProgressStripProps {
  state: SwarmLiveState | null;
}

interface WaveInfo {
  wave: number;
  total: number;
  completed: number;
  failed: number;
  isCurrent: boolean;
}

export function WaveProgressStrip({ state }: WaveProgressStripProps) {
  if (!state || !state.status) return null;

  const { currentWave, totalWaves } = state.status;
  const tasks = state.tasks;

  // Group tasks by wave
  const waveMap = new Map<number, SwarmTask[]>();
  for (const task of tasks) {
    const wave = task.wave;
    if (!waveMap.has(wave)) waveMap.set(wave, []);
    waveMap.get(wave)!.push(task);
  }

  const waves: WaveInfo[] = [];
  for (let w = 1; w <= totalWaves; w++) {
    const waveTasks = waveMap.get(w) ?? [];
    waves.push({
      wave: w,
      total: waveTasks.length,
      completed: waveTasks.filter((t) => t.status === 'completed').length,
      failed: waveTasks.filter((t) => t.status === 'failed').length,
      isCurrent: w === currentWave,
    });
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
      <div className="flex items-center gap-2">
        {waves.map((w) => {
          const percent = w.total > 0 ? (w.completed + w.failed) / w.total : 0;
          const failPercent = w.total > 0 ? w.failed / w.total : 0;

          return (
            <div key={w.wave} className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className={cn(
                  'text-[10px] font-medium',
                  w.isCurrent ? 'text-white' : 'text-gray-500'
                )}>
                  W{w.wave}
                </span>
                <span className="text-[10px] text-gray-500">
                  {w.completed}/{w.total}
                </span>
              </div>
              <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                <div className="h-full flex">
                  {/* Green (completed) */}
                  <div
                    className="bg-emerald-500 transition-all duration-300"
                    style={{ width: `${((percent - failPercent) * 100)}%` }}
                  />
                  {/* Red (failed) */}
                  {failPercent > 0 && (
                    <div
                      className="bg-red-500 transition-all duration-300"
                      style={{ width: `${(failPercent * 100)}%` }}
                    />
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
