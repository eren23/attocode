/**
 * Shared Budget Pool
 *
 * Enables parent-child budget sharing for multi-agent workflows.
 * Instead of each subagent getting an independent budget (leading to 250%+ exposure),
 * subagents draw from a shared pool that the parent allocates from its own budget.
 *
 * Model:
 *   Parent budget: 200K tokens
 *   Parent reserves: 50K (for synthesis after subagents complete)
 *   Subagent pool: 150K (shared among all children)
 *
 * Each child can draw up to `maxPerChild` tokens from the pool, but the combined
 * consumption never exceeds the pool total. This ensures total tree cost stays
 * bounded by the parent's budget.
 */

// =============================================================================
// TYPES
// =============================================================================

export interface BudgetPoolConfig {
  /** Total tokens available in the pool */
  totalTokens: number;
  /** Maximum tokens any single child can consume */
  maxPerChild: number;
  /** Total cost cap for the pool */
  totalCost?: number;
  /** Maximum cost any single child can incur */
  maxCostPerChild?: number;
}

export interface BudgetAllocation {
  /** Unique ID for this allocation */
  id: string;
  /** Tokens allocated (upper bound) */
  tokenBudget: number;
  /** Cost allocated (upper bound) */
  costBudget: number;
  /** Tokens actually consumed so far */
  tokensUsed: number;
  /** Cost actually incurred so far */
  costUsed: number;
}

export interface BudgetPoolStats {
  /** Total pool capacity */
  totalTokens: number;
  /** Total tokens consumed across all children */
  tokensUsed: number;
  /** Tokens remaining in pool */
  tokensRemaining: number;
  /** Number of active allocations */
  activeAllocations: number;
  /** Utilization ratio (0-1) */
  utilization: number;
}

// =============================================================================
// SHARED BUDGET POOL
// =============================================================================

export class SharedBudgetPool {
  private readonly config: BudgetPoolConfig;
  private allocations = new Map<string, BudgetAllocation>();
  private totalTokensUsed = 0;
  private totalCostUsed = 0;
  /** Tokens reserved by active allocations (pessimistic accounting) */
  private totalTokensReserved = 0;
  private totalCostReserved = 0;

  constructor(config: BudgetPoolConfig) {
    this.config = config;
  }

  /**
   * Reserve a budget allocation for a child agent.
   * Uses pessimistic accounting: reserved tokens count against pool capacity
   * until actual usage is recorded via recordUsage() + release().
   * Returns the allocation if there's enough room, or null if the pool is exhausted.
   */
  reserve(childId: string): BudgetAllocation | null {
    // Account for both consumed AND reserved-but-not-yet-consumed tokens
    const committed = Math.max(this.totalTokensUsed, this.totalTokensReserved);
    const remaining = this.config.totalTokens - committed;
    if (remaining <= 0) {
      return null;
    }

    // Allocate up to maxPerChild or whatever remains, whichever is smaller
    const tokenBudget = Math.min(this.config.maxPerChild, remaining);
    const committedCost = Math.max(this.totalCostUsed, this.totalCostReserved);
    const costRemaining = this.config.totalCost
      ? this.config.totalCost - committedCost
      : Infinity;
    const costBudget = Math.min(
      this.config.maxCostPerChild ?? Infinity,
      costRemaining > 0 ? costRemaining : 0,
    );

    if (tokenBudget <= 0 || (this.config.totalCost && costBudget <= 0)) {
      return null;
    }

    const allocation: BudgetAllocation = {
      id: childId,
      tokenBudget,
      costBudget,
      tokensUsed: 0,
      costUsed: 0,
    };

    // Track reservation pessimistically
    this.totalTokensReserved += tokenBudget;
    this.totalCostReserved += costBudget;
    this.allocations.set(childId, allocation);
    return allocation;
  }

  /**
   * Record token consumption for a child agent.
   * Returns false if the child has exceeded its allocation.
   */
  recordUsage(childId: string, tokens: number, cost: number): boolean {
    const allocation = this.allocations.get(childId);
    if (!allocation) {
      return false;
    }

    allocation.tokensUsed += tokens;
    allocation.costUsed += cost;
    this.totalTokensUsed += tokens;
    this.totalCostUsed += cost;

    return allocation.tokensUsed <= allocation.tokenBudget;
  }

  /**
   * Release an allocation, adjusting reserved totals to reflect actual usage.
   * Must be called after recordUsage() to return unused budget to the pool.
   */
  release(childId: string): void {
    const allocation = this.allocations.get(childId);
    if (allocation) {
      // Release the pessimistic reservation, keeping only actual usage
      this.totalTokensReserved -= allocation.tokenBudget;
      this.totalCostReserved -= allocation.costBudget;
      this.allocations.delete(childId);
    }
  }

  /**
   * Get remaining tokens for a specific child allocation.
   */
  getRemainingForChild(childId: string): number {
    const allocation = this.allocations.get(childId);
    if (!allocation) return 0;
    return Math.max(0, allocation.tokenBudget - allocation.tokensUsed);
  }

  /**
   * Get overall pool statistics.
   */
  getStats(): BudgetPoolStats {
    const committed = Math.max(this.totalTokensUsed, this.totalTokensReserved);
    return {
      totalTokens: this.config.totalTokens,
      tokensUsed: this.totalTokensUsed,
      tokensRemaining: Math.max(0, this.config.totalTokens - committed),
      activeAllocations: this.allocations.size,
      utilization: this.config.totalTokens > 0
        ? committed / this.config.totalTokens
        : 0,
    };
  }

  /**
   * Check if the pool has enough budget for at least one more child.
   */
  hasCapacity(): boolean {
    const committed = Math.max(this.totalTokensUsed, this.totalTokensReserved);
    return (this.config.totalTokens - committed) > 10000; // Minimum 10K tokens
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a budget pool from a parent's total budget.
 * Reserves a portion for the parent's own synthesis work.
 */
export function createBudgetPool(
  parentBudgetTokens: number,
  parentReserveRatio: number = 0.25, // Reserve 25% for parent synthesis
  maxPerChild: number = 100000,
): SharedBudgetPool {
  const parentReserve = Math.floor(parentBudgetTokens * parentReserveRatio);
  const poolTokens = parentBudgetTokens - parentReserve;

  return new SharedBudgetPool({
    totalTokens: poolTokens,
    maxPerChild: Math.min(maxPerChild, poolTokens),
    totalCost: 0.50, // Default cost cap
    maxCostPerChild: 0.25,
  });
}
