/**
 * Swarm Budget Pool
 *
 * Wraps SharedBudgetPool with swarm-specific defaults for managing
 * budgets across 10-20+ tiny workers.
 */

import {
  createBudgetPool,
  type SharedBudgetPool,
  type BudgetPoolStats,
} from '../budget/budget-pool.js';
import type { SwarmConfig } from './types.js';

// ─── Swarm Budget ──────────────────────────────────────────────────────────

export interface SwarmBudgetPool {
  /** Underlying budget pool */
  pool: SharedBudgetPool;

  /** Reserve budget for the orchestrator (quality gates, synthesis) */
  orchestratorReserve: number;

  /** Max tokens per individual worker */
  maxPerWorker: number;

  /** Max cost per worker */
  maxCostPerWorker: number;

  /** Get pool stats */
  getStats(): BudgetPoolStats;

  /** Check if there's budget remaining for more workers */
  hasCapacity(): boolean;

  /** F3: Reallocate unused tokens from completed wave back to pool.
   *  This is a no-op on SharedBudgetPool since release() already handles it,
   *  but explicitly logs the reallocation for observability. */
  reallocateUnused(unusedTokens: number): void;
}

/**
 * Create a swarm budget pool from SwarmConfig.
 *
 * Splits the total budget between:
 * - Orchestrator reserve (default 15%): for decomposition, quality gates, synthesis
 * - Worker pool (remaining 85%): shared among all workers with per-worker caps
 */
export function createSwarmBudgetPool(config: SwarmConfig): SwarmBudgetPool {
  const orchestratorReserve = Math.floor(config.totalBudget * config.orchestratorReserveRatio);
  const workerPoolBudget = config.totalBudget - orchestratorReserve;

  // Per-worker cost cap: total cost divided by expected workers, with safety margin
  const estimatedWorkers = Math.max(5, config.maxConcurrency * 3);
  const maxCostPerWorker = config.maxCost / estimatedWorkers;

  const pool = createBudgetPool(
    workerPoolBudget,
    0, // No additional reserve within the pool (already reserved at swarm level)
    config.maxTokensPerWorker,
  );

  return {
    pool,
    orchestratorReserve,
    maxPerWorker: config.maxTokensPerWorker,
    maxCostPerWorker,

    getStats(): BudgetPoolStats {
      return pool.getStats();
    },

    hasCapacity(): boolean {
      return pool.hasCapacity();
    },

    reallocateUnused(unusedTokens: number): void {
      // F3: SharedBudgetPool already handles reallocation via release().
      // This method exists for observability — the orchestrator logs it.
      // No additional action needed since release() adjusts totalTokensReserved.
      void unusedTokens;
    },
  };
}
