/**
 * BudgetPanel - Token + cost radial gauges with burn rate
 */

import { RadialGauge } from './RadialGauge';
import { formatTokens, formatCost } from '../../lib/utils';
import type { SwarmLiveState } from '../../lib/swarm-types';

interface BudgetPanelProps {
  state: SwarmLiveState | null;
}

export function BudgetPanel({ state }: BudgetPanelProps) {
  const budget = state?.status?.budget;

  if (!budget) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Budget</h3>
        <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
          No budget data
        </div>
      </div>
    );
  }

  // Compute burn rate from timeline
  const timeline = state?.timeline ?? [];
  let burnRateLabel = '';
  if (timeline.length >= 2) {
    const first = timeline[0];
    const last = timeline[timeline.length - 1];
    const timeDiffMs = new Date(last.ts).getTime() - new Date(first.ts).getTime();
    if (timeDiffMs > 0) {
      const tokenRate = (last.tokensUsed - first.tokensUsed) / (timeDiffMs / 1000);
      const remaining = budget.tokensTotal - budget.tokensUsed;
      if (tokenRate > 0) {
        const etaSec = remaining / tokenRate;
        burnRateLabel = etaSec > 3600
          ? `~${(etaSec / 3600).toFixed(1)}h remaining`
          : etaSec > 60
            ? `~${(etaSec / 60).toFixed(0)}m remaining`
            : `~${etaSec.toFixed(0)}s remaining`;
      }
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-400 mb-3">Budget</h3>
      <div className="flex items-center justify-around">
        <div className="relative">
          <RadialGauge
            value={budget.tokensUsed}
            max={budget.tokensTotal}
            label="Tokens"
            sublabel={`${formatTokens(budget.tokensUsed)} / ${formatTokens(budget.tokensTotal)}`}
          />
        </div>
        <div className="relative">
          <RadialGauge
            value={budget.costUsed}
            max={budget.costTotal}
            label="Cost"
            sublabel={`${formatCost(budget.costUsed)} / ${formatCost(budget.costTotal)}`}
          />
        </div>
      </div>
      {burnRateLabel && (
        <div className="mt-3 text-center text-xs text-gray-500">
          {burnRateLabel}
        </div>
      )}
    </div>
  );
}
