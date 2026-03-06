/**
 * BudgetTreemap - Simple treemap of budget allocation using nested divs.
 *
 * Each agent gets a proportional-width div colored by usage level:
 * green < 50%, yellow < 80%, red >= 80%.
 */

import type { BudgetPoolSnapshot } from '../../lib/agent-graph-types';
import { formatTokens } from '../../lib/utils';
import { cn } from '../../lib/utils';

interface BudgetTreemapProps {
  budgetPool: BudgetPoolSnapshot | null;
}

function usageColor(used: number, allocated: number): string {
  if (allocated === 0) return 'bg-gray-700';
  const ratio = used / allocated;
  if (ratio >= 0.8) return 'bg-red-600/60';
  if (ratio >= 0.5) return 'bg-yellow-600/60';
  return 'bg-green-600/60';
}

function usageBorderColor(used: number, allocated: number): string {
  if (allocated === 0) return 'border-gray-600';
  const ratio = used / allocated;
  if (ratio >= 0.8) return 'border-red-500/50';
  if (ratio >= 0.5) return 'border-yellow-500/50';
  return 'border-green-500/50';
}

export function BudgetTreemap({ budgetPool }: BudgetTreemapProps) {
  if (!budgetPool) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Budget Allocation</h3>
        <div className="flex items-center justify-center h-24 text-gray-500 text-sm">
          No budget data
        </div>
      </div>
    );
  }

  const totalAllocated = budgetPool.allocations.reduce((sum, a) => sum + a.tokensAllocated, 0);
  const poolUsagePercent = budgetPool.poolTotal > 0
    ? ((budgetPool.poolUsed / budgetPool.poolTotal) * 100).toFixed(1)
    : '0';

  // Sort allocations by tokens allocated (largest first) for better treemap layout
  const sorted = [...budgetPool.allocations].sort((a, b) => b.tokensAllocated - a.tokensAllocated);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-400">Budget Allocation</h3>
        <span className="text-[10px] text-gray-500">
          {formatTokens(budgetPool.poolUsed)} / {formatTokens(budgetPool.poolTotal)} ({poolUsagePercent}%)
        </span>
      </div>

      {/* Overall pool bar */}
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden mb-3">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-300',
            budgetPool.poolTotal > 0 && (budgetPool.poolUsed / budgetPool.poolTotal) >= 0.8
              ? 'bg-red-500'
              : budgetPool.poolTotal > 0 && (budgetPool.poolUsed / budgetPool.poolTotal) >= 0.5
                ? 'bg-yellow-500'
                : 'bg-green-500'
          )}
          style={{
            width: budgetPool.poolTotal > 0
              ? `${Math.min(100, (budgetPool.poolUsed / budgetPool.poolTotal) * 100)}%`
              : '0%',
          }}
        />
      </div>

      {/* Treemap: proportional-width divs */}
      {sorted.length > 0 && totalAllocated > 0 && (
        <div className="flex gap-1 h-16 rounded overflow-hidden">
          {sorted.map((alloc) => {
            const widthPercent = (alloc.tokensAllocated / totalAllocated) * 100;
            const usagePercent = alloc.tokensAllocated > 0
              ? ((alloc.tokensUsed / alloc.tokensAllocated) * 100).toFixed(0)
              : '0';

            // Skip tiny allocations that would be invisible
            if (widthPercent < 2) return null;

            return (
              <div
                key={alloc.agentId}
                className={cn(
                  'flex flex-col justify-center items-center rounded border px-1 min-w-0 overflow-hidden',
                  usageColor(alloc.tokensUsed, alloc.tokensAllocated),
                  usageBorderColor(alloc.tokensUsed, alloc.tokensAllocated)
                )}
                style={{ width: `${widthPercent}%` }}
                title={`${alloc.agentId}: ${formatTokens(alloc.tokensUsed)} / ${formatTokens(alloc.tokensAllocated)}`}
              >
                <span className="text-[9px] text-white font-medium truncate w-full text-center">
                  {alloc.agentId.length > 10 ? alloc.agentId.slice(0, 8) + '..' : alloc.agentId}
                </span>
                <span className="text-[8px] text-gray-200/80 truncate w-full text-center">
                  {formatTokens(alloc.tokensUsed)}/{formatTokens(alloc.tokensAllocated)}
                </span>
                <span className="text-[8px] text-gray-200/60">
                  {usagePercent}%
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Agent list for small allocations */}
      {sorted.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {sorted.filter((a) => totalAllocated > 0 && (a.tokensAllocated / totalAllocated) * 100 < 2).map((alloc) => (
            <div key={alloc.agentId} className="flex items-center gap-2 text-[10px]">
              <span
                className={cn(
                  'h-2 w-2 rounded-sm shrink-0',
                  usageColor(alloc.tokensUsed, alloc.tokensAllocated)
                )}
              />
              <span className="text-gray-400 truncate">{alloc.agentId}</span>
              <span className="text-gray-500 ml-auto">
                {formatTokens(alloc.tokensUsed)}/{formatTokens(alloc.tokensAllocated)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Updated timestamp */}
      {budgetPool.updatedAt && (
        <div className="mt-2 text-[10px] text-gray-600 text-right">
          Updated: {new Date(budgetPool.updatedAt).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
