/**
 * MetricsStrip - 4 metric cards for tokens, cost, tasks, workers
 */

import { MetricCard } from '../MetricCard';
import { formatTokens, formatCost } from '../../lib/utils';
import type { SwarmLiveState } from '../../lib/swarm-types';

interface MetricsStripProps {
  state: SwarmLiveState | null;
}

export function MetricsStrip({ state }: MetricsStripProps) {
  const budget = state?.status?.budget;
  const queue = state?.status?.queue;
  const workers = state?.status?.activeWorkers ?? [];

  const tokenPercent = budget ? budget.tokensUsed / Math.max(budget.tokensTotal, 1) : 0;
  const costPercent = budget ? budget.costUsed / Math.max(budget.costTotal, 0.01) : 0;

  return (
    <div className="grid grid-cols-4 gap-3">
      <MetricCard
        label="Tokens"
        value={budget ? formatTokens(budget.tokensUsed) : '—'}
        subtext={budget ? `/ ${formatTokens(budget.tokensTotal)}` : undefined}
        status={tokenPercent > 0.9 ? 'bad' : tokenPercent > 0.7 ? 'warn' : 'neutral'}
      />
      <MetricCard
        label="Cost"
        value={budget ? formatCost(budget.costUsed) : '—'}
        subtext={budget ? `/ ${formatCost(budget.costTotal)}` : undefined}
        status={costPercent > 0.9 ? 'bad' : costPercent > 0.7 ? 'warn' : 'neutral'}
      />
      <MetricCard
        label="Tasks"
        value={queue ? `${queue.completed}/${queue.total}` : '—'}
        subtext={queue && queue.failed > 0 ? `${queue.failed} failed` : undefined}
        status={queue && queue.failed > 0 ? 'warn' : 'neutral'}
      />
      <MetricCard
        label="Workers"
        value={`${workers.length}`}
        subtext={state?.config ? `/ ${state.config.maxConcurrency} max` : undefined}
        status={workers.length > 0 ? 'good' : 'neutral'}
      />
    </div>
  );
}
