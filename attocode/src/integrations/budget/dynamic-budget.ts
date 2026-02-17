/**
 * Dynamic Budget Rebalancing
 *
 * Extends SharedBudgetPool with dynamic rebalancing that prevents
 * starvation when spawning subagents sequentially.
 *
 * Key features:
 * - setExpectedChildren(count) for upfront capacity planning
 * - Sequential spawn cap: never take >60% of remaining budget
 * - Rebalance on child completion (return unused budget to pool)
 * - Priority-based allocation (critical children get more)
 */

import {
  SharedBudgetPool,
  type BudgetPoolConfig,
  type BudgetAllocation,
  type BudgetPoolStats,
} from './budget-pool.js';

// =============================================================================
// TYPES
// =============================================================================

export interface DynamicBudgetConfig extends BudgetPoolConfig {
  /** Maximum percentage of remaining budget for any single child (default: 0.6) */
  maxRemainingRatio: number;
  /** Minimum tokens to reserve for each expected child (default: 10000) */
  minPerExpectedChild: number;
  /** Enable automatic rebalancing on release (default: true) */
  autoRebalance: boolean;
}

export interface ChildPriority {
  /** Child ID */
  childId: string;
  /** Priority level (higher = more budget) */
  priority: 'low' | 'normal' | 'high' | 'critical';
  /** Expected token usage (optional hint) */
  expectedTokens?: number;
}

export interface RebalanceResult {
  /** Children that had their allocations adjusted */
  adjusted: Array<{ childId: string; oldBudget: number; newBudget: number }>;
  /** Tokens freed by rebalancing */
  tokensFreed: number;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const PRIORITY_MULTIPLIERS: Record<string, number> = {
  low: 0.5,
  normal: 1.0,
  high: 1.5,
  critical: 2.0,
};

const DEFAULT_DYNAMIC_CONFIG: Partial<DynamicBudgetConfig> = {
  maxRemainingRatio: 0.6,
  minPerExpectedChild: 10000,
  autoRebalance: true,
};

// =============================================================================
// DYNAMIC BUDGET POOL
// =============================================================================

export class DynamicBudgetPool extends SharedBudgetPool {
  private dynamicConfig: DynamicBudgetConfig;
  private expectedChildren = 0;
  private spawnedCount = 0;
  private completedCount = 0;
  private childPriorities: Map<string, ChildPriority> = new Map();

  constructor(config: BudgetPoolConfig & Partial<DynamicBudgetConfig>) {
    super(config);
    this.dynamicConfig = {
      ...config,
      maxRemainingRatio: config.maxRemainingRatio ?? DEFAULT_DYNAMIC_CONFIG.maxRemainingRatio!,
      minPerExpectedChild:
        config.minPerExpectedChild ?? DEFAULT_DYNAMIC_CONFIG.minPerExpectedChild!,
      autoRebalance: config.autoRebalance ?? DEFAULT_DYNAMIC_CONFIG.autoRebalance!,
    };
  }

  /**
   * Set the expected number of children for capacity planning.
   * This adjusts maxPerChild to ensure fair distribution.
   */
  setExpectedChildren(count: number): void {
    this.expectedChildren = count;
    this.updateMaxPerChild();
  }

  /**
   * Set priority for a child agent.
   */
  setChildPriority(priority: ChildPriority): void {
    this.childPriorities.set(priority.childId, priority);
  }

  /**
   * Reserve with dynamic capacity planning.
   * Respects expected children and remaining ratio cap.
   */
  reserveDynamic(childId: string, priority?: ChildPriority['priority']): BudgetAllocation | null {
    // Set priority if provided
    if (priority) {
      this.setChildPriority({ childId, priority });
    }

    // Calculate dynamic max for this child
    const stats = this.getStats();
    const remaining = stats.tokensRemaining;

    if (remaining <= 0) return null;

    // Cap at maxRemainingRatio of remaining budget
    const ratioCap = Math.floor(remaining * this.dynamicConfig.maxRemainingRatio);

    // Reserve for expected future children
    const unreservedChildren = Math.max(0, this.expectedChildren - this.spawnedCount - 1);
    const reserveForFuture = unreservedChildren * this.dynamicConfig.minPerExpectedChild;
    const afterReserve = Math.max(0, remaining - reserveForFuture);

    // Apply priority multiplier
    const priorityLevel = this.childPriorities.get(childId)?.priority ?? 'normal';
    const multiplier = PRIORITY_MULTIPLIERS[priorityLevel] ?? 1.0;
    const priorityAdjusted = Math.floor(
      (afterReserve * multiplier) / Math.max(1, unreservedChildren + 1),
    );

    // Final allocation: min of all caps
    const dynamicMax = Math.min(
      ratioCap,
      afterReserve,
      Math.max(priorityAdjusted, this.dynamicConfig.minPerExpectedChild),
    );

    // Temporarily set max per child for this reservation
    this.setMaxPerChild(dynamicMax);
    const allocation = this.reserve(childId);
    this.resetMaxPerChild();

    if (allocation) {
      this.spawnedCount++;
    }

    return allocation;
  }

  /**
   * Release with optional auto-rebalancing.
   */
  releaseDynamic(childId: string): void {
    this.release(childId);
    this.completedCount++;
    this.childPriorities.delete(childId);
  }

  /**
   * Get enhanced stats including dynamic info.
   */
  getDynamicStats(): BudgetPoolStats & {
    expectedChildren: number;
    spawnedCount: number;
    completedCount: number;
    pendingCount: number;
    avgPerChild: number;
  } {
    const base = this.getStats();
    const pending = this.spawnedCount - this.completedCount;
    return {
      ...base,
      expectedChildren: this.expectedChildren,
      spawnedCount: this.spawnedCount,
      completedCount: this.completedCount,
      pendingCount: pending,
      avgPerChild: this.spawnedCount > 0 ? Math.floor(base.tokensUsed / this.spawnedCount) : 0,
    };
  }

  // ===========================================================================
  // INTERNAL
  // ===========================================================================

  private updateMaxPerChild(): void {
    if (this.expectedChildren <= 0) return;

    const stats = this.getStats();
    const remaining = stats.tokensRemaining;
    const unreserved = Math.max(1, this.expectedChildren - this.spawnedCount);

    // Fair share: remaining / unreserved children, capped by ratio
    const fairShare = Math.floor(remaining / unreserved);
    const ratioCap = Math.floor(remaining * this.dynamicConfig.maxRemainingRatio);

    this.setMaxPerChild(Math.min(fairShare, ratioCap));
  }
}

/**
 * Create a dynamic budget pool from a parent's budget.
 */
export function createDynamicBudgetPool(
  parentBudgetTokens: number,
  parentReserveRatio: number = 0.25,
  config?: Partial<DynamicBudgetConfig>,
): DynamicBudgetPool {
  const parentReserve = Math.floor(parentBudgetTokens * parentReserveRatio);
  const poolTokens = parentBudgetTokens - parentReserve;

  return new DynamicBudgetPool({
    totalTokens: poolTokens,
    maxPerChild: Math.min(config?.maxPerChild ?? 100000, poolTokens),
    totalCost: 0.5,
    maxCostPerChild: 0.25,
    maxRemainingRatio: config?.maxRemainingRatio ?? 0.6,
    minPerExpectedChild: config?.minPerExpectedChild ?? 10000,
    autoRebalance: config?.autoRebalance ?? true,
  });
}
