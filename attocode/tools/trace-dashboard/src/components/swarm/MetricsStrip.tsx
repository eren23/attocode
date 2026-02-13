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
  const orchestrator = state?.status?.orchestrator;
  const queue = state?.status?.queue;
  const workers = state?.status?.activeWorkers ?? [];

  const tokenPercent = budget ? budget.tokensUsed / Math.max(budget.tokensTotal, 1) : 0;
  const costPercent = budget ? budget.costUsed / Math.max(budget.costTotal, 0.01) : 0;

  // Compute orchestrator vs worker breakdown if orchestrator data is available
  const orchCost = orchestrator?.cost ?? 0;
  const workerCost = budget ? budget.costUsed - orchCost : 0;
  const orchTokens = orchestrator?.tokens ?? 0;
  const workerTokens = budget ? budget.tokensUsed - orchTokens : 0;

  const tokenBreakdown = orchestrator && budget
    ? `Orch: ${formatTokens(orchTokens)} | Workers: ${formatTokens(workerTokens)}`
    : undefined;

  const costBreakdown = orchestrator && budget
    ? `Orch: ${formatCost(orchCost)} | Workers: ${formatCost(workerCost)}`
    : undefined;

  return (
    <div className="grid grid-cols-4 gap-3">
      <MetricCard
        label="Tokens"
        value={budget ? formatTokens(budget.tokensUsed) : '—'}
        subtext={tokenBreakdown ?? (budget ? `/ ${formatTokens(budget.tokensTotal)}` : undefined)}
        status={tokenPercent > 0.9 ? 'bad' : tokenPercent > 0.7 ? 'warn' : 'neutral'}
      />
      <MetricCard
        label="Cost"
        value={budget ? formatCost(budget.costUsed) : '—'}
        subtext={costBreakdown ?? (budget ? `/ ${formatCost(budget.costTotal)}` : undefined)}
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
