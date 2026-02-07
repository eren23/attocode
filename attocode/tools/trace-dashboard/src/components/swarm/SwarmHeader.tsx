/**
 * SwarmHeader - Phase badge, wave indicator, action buttons
 */

import { cn } from '../../lib/utils';
import type { SwarmLiveState, SwarmPhase } from '../../lib/swarm-types';
import { SWARM_PHASE_COLORS } from '../../lib/swarm-types';
import { Link } from 'react-router-dom';

interface SwarmHeaderProps {
  state: SwarmLiveState | null;
  connected: boolean;
}

const PHASE_LABELS: Record<SwarmPhase, string> = {
  decomposing: 'Decomposing',
  scheduling: 'Scheduling',
  executing: 'Executing',
  synthesizing: 'Synthesizing',
  completed: 'Completed',
  failed: 'Failed',
};

export function SwarmHeader({ state, connected }: SwarmHeaderProps) {
  const phase = state?.status?.phase ?? 'executing';
  const currentWave = state?.status?.currentWave ?? 0;
  const totalWaves = state?.status?.totalWaves ?? 0;

  return (
    <div className="flex items-center justify-between bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
      <div className="flex items-center gap-4">
        <h1 className="text-lg font-bold text-white">SWARM LIVE</h1>

        {/* Phase Badge */}
        <span
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold text-white"
          style={{ backgroundColor: SWARM_PHASE_COLORS[phase] }}
        >
          {state?.active && (
            <span className="h-2 w-2 rounded-full bg-white/70 animate-pulse" />
          )}
          {PHASE_LABELS[phase]}
        </span>

        {/* Wave indicator */}
        {totalWaves > 0 && (
          <span className="text-sm text-gray-400">
            Wave {currentWave}/{totalWaves}
          </span>
        )}

        {/* Connection status */}
        <span className={cn(
          'inline-flex items-center gap-1 text-xs',
          connected ? 'text-green-400' : 'text-red-400'
        )}>
          <span className={cn(
            'h-1.5 w-1.5 rounded-full',
            connected ? 'bg-green-400' : 'bg-red-400'
          )} />
          {connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      <div className="flex items-center gap-3">
        <Link
          to="/swarm/history"
          className="text-xs text-gray-400 hover:text-white transition-colors px-2 py-1 rounded hover:bg-gray-800"
        >
          History
        </Link>
      </div>
    </div>
  );
}
