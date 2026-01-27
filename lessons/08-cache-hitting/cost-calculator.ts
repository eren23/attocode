/**
 * Lesson 08: Cost Calculator
 *
 * Utilities for calculating and tracking LLM API costs with caching.
 */

// =============================================================================
// PRICING DATA
// =============================================================================

/**
 * Model pricing per 1M tokens (in USD).
 * Prices as of early 2025 - check provider docs for current rates.
 */
export interface ModelPricing {
  inputPer1M: number;
  outputPer1M: number;
  cachedInputPer1M: number;  // Usually ~10% of input price
  cacheWritePer1M?: number;  // Some providers charge for cache writes
}

/**
 * Common model pricing via OpenRouter.
 * Note: OpenRouter adds a small markup over direct API prices.
 */
export const MODEL_PRICING: Record<string, ModelPricing> = {
  // Anthropic Claude models
  'anthropic/claude-3.5-sonnet': {
    inputPer1M: 3.00,
    outputPer1M: 15.00,
    cachedInputPer1M: 0.30,  // 90% discount
    cacheWritePer1M: 3.75,   // 25% premium for cache write
  },
  'anthropic/claude-3-opus': {
    inputPer1M: 15.00,
    outputPer1M: 75.00,
    cachedInputPer1M: 1.50,
    cacheWritePer1M: 18.75,
  },
  'anthropic/claude-3-haiku': {
    inputPer1M: 0.25,
    outputPer1M: 1.25,
    cachedInputPer1M: 0.025,
    cacheWritePer1M: 0.30,
  },

  // Google Gemini models
  'google/gemini-2.0-flash-001': {
    inputPer1M: 0.10,
    outputPer1M: 0.40,
    cachedInputPer1M: 0.025,  // 75% discount
  },
  'google/gemini-1.5-pro': {
    inputPer1M: 1.25,
    outputPer1M: 5.00,
    cachedInputPer1M: 0.3125,
  },
  'google/gemini-1.5-flash': {
    inputPer1M: 0.075,
    outputPer1M: 0.30,
    cachedInputPer1M: 0.01875,
  },

  // OpenAI models (no native caching, but included for comparison)
  'openai/gpt-4-turbo': {
    inputPer1M: 10.00,
    outputPer1M: 30.00,
    cachedInputPer1M: 10.00,  // No caching discount
  },
  'openai/gpt-4o': {
    inputPer1M: 2.50,
    outputPer1M: 10.00,
    cachedInputPer1M: 1.25,  // 50% discount with predicted outputs
  },
  'openai/gpt-4o-mini': {
    inputPer1M: 0.15,
    outputPer1M: 0.60,
    cachedInputPer1M: 0.075,
  },

  // DeepSeek models
  'deepseek/deepseek-chat': {
    inputPer1M: 0.14,
    outputPer1M: 0.28,
    cachedInputPer1M: 0.014,  // 90% discount
  },
};

// =============================================================================
// COST CALCULATION
// =============================================================================

/**
 * Token usage for a single request.
 */
export interface RequestUsage {
  inputTokens: number;
  outputTokens: number;
  cachedTokens?: number;
  cacheWriteTokens?: number;
}

/**
 * Calculated cost breakdown.
 */
export interface CostBreakdown {
  /** Cost for uncached input tokens */
  inputCost: number;
  /** Cost for cached input tokens */
  cachedInputCost: number;
  /** Cost for cache write (if applicable) */
  cacheWriteCost: number;
  /** Cost for output tokens */
  outputCost: number;
  /** Total cost */
  totalCost: number;
  /** What it would have cost without caching */
  costWithoutCaching: number;
  /** Amount saved by caching */
  savings: number;
  /** Savings as a percentage */
  savingsPercent: number;
}

/**
 * Calculate cost for a single request.
 *
 * @param usage - Token usage from the API response
 * @param model - Model ID (must be in MODEL_PRICING)
 * @returns Detailed cost breakdown
 *
 * @example
 * ```typescript
 * const cost = calculateRequestCost(
 *   { inputTokens: 5000, outputTokens: 500, cachedTokens: 4000 },
 *   'anthropic/claude-3.5-sonnet'
 * );
 * console.log(`Saved $${cost.savings.toFixed(4)} (${cost.savingsPercent.toFixed(1)}%)`);
 * ```
 */
export function calculateRequestCost(
  usage: RequestUsage,
  model: string
): CostBreakdown {
  const pricing = MODEL_PRICING[model];

  if (!pricing) {
    // Return zero costs for unknown models
    return {
      inputCost: 0,
      cachedInputCost: 0,
      cacheWriteCost: 0,
      outputCost: 0,
      totalCost: 0,
      costWithoutCaching: 0,
      savings: 0,
      savingsPercent: 0,
    };
  }

  const cachedTokens = usage.cachedTokens ?? 0;
  const uncachedInputTokens = usage.inputTokens - cachedTokens;
  const cacheWriteTokens = usage.cacheWriteTokens ?? 0;

  // Calculate costs
  const inputCost = (uncachedInputTokens / 1_000_000) * pricing.inputPer1M;
  const cachedInputCost = (cachedTokens / 1_000_000) * pricing.cachedInputPer1M;
  const cacheWriteCost = pricing.cacheWritePer1M
    ? (cacheWriteTokens / 1_000_000) * pricing.cacheWritePer1M
    : 0;
  const outputCost = (usage.outputTokens / 1_000_000) * pricing.outputPer1M;

  const totalCost = inputCost + cachedInputCost + cacheWriteCost + outputCost;

  // What would it have cost without caching?
  const costWithoutCaching =
    (usage.inputTokens / 1_000_000) * pricing.inputPer1M +
    (usage.outputTokens / 1_000_000) * pricing.outputPer1M;

  const savings = costWithoutCaching - totalCost;
  const savingsPercent = costWithoutCaching > 0
    ? (savings / costWithoutCaching) * 100
    : 0;

  return {
    inputCost,
    cachedInputCost,
    cacheWriteCost,
    outputCost,
    totalCost,
    costWithoutCaching,
    savings,
    savingsPercent,
  };
}

// =============================================================================
// SESSION COST TRACKER
// =============================================================================

/**
 * Tracks costs across multiple requests in a session.
 *
 * @example
 * ```typescript
 * const tracker = new CostTracker('anthropic/claude-3.5-sonnet');
 *
 * // After each API call
 * tracker.addRequest(response.usage);
 *
 * // Check totals
 * console.log(tracker.getSummary());
 * // → { totalCost: 0.0234, totalSavings: 0.0456, ... }
 * ```
 */
export class CostTracker {
  private requests: CostBreakdown[] = [];
  private model: string;

  constructor(model: string) {
    this.model = model;
  }

  /**
   * Record a request's usage.
   */
  addRequest(usage: RequestUsage): CostBreakdown {
    const cost = calculateRequestCost(usage, this.model);
    this.requests.push(cost);
    return cost;
  }

  /**
   * Get summary of all tracked requests.
   */
  getSummary(): {
    requestCount: number;
    totalCost: number;
    totalSavings: number;
    totalSavingsPercent: number;
    costWithoutCaching: number;
    averageCostPerRequest: number;
  } {
    const totals = this.requests.reduce(
      (acc, req) => ({
        totalCost: acc.totalCost + req.totalCost,
        totalSavings: acc.totalSavings + req.savings,
        costWithoutCaching: acc.costWithoutCaching + req.costWithoutCaching,
      }),
      { totalCost: 0, totalSavings: 0, costWithoutCaching: 0 }
    );

    return {
      requestCount: this.requests.length,
      totalCost: totals.totalCost,
      totalSavings: totals.totalSavings,
      totalSavingsPercent: totals.costWithoutCaching > 0
        ? (totals.totalSavings / totals.costWithoutCaching) * 100
        : 0,
      costWithoutCaching: totals.costWithoutCaching,
      averageCostPerRequest: this.requests.length > 0
        ? totals.totalCost / this.requests.length
        : 0,
    };
  }

  /**
   * Reset the tracker.
   */
  reset(): void {
    this.requests = [];
  }

  /**
   * Get detailed breakdown of all requests.
   */
  getDetails(): CostBreakdown[] {
    return [...this.requests];
  }
}

// =============================================================================
// PROJECTION UTILITIES
// =============================================================================

/**
 * Project costs for a conversation of given length.
 *
 * @param systemPromptTokens - Size of system prompt (cached)
 * @param avgUserMessageTokens - Average user message size
 * @param avgAssistantTokens - Average assistant response size
 * @param turns - Number of conversation turns
 * @param model - Model to use for pricing
 * @returns Projected costs with and without caching
 */
export function projectConversationCost(
  systemPromptTokens: number,
  avgUserMessageTokens: number,
  avgAssistantTokens: number,
  turns: number,
  model: string
): {
  withCaching: number;
  withoutCaching: number;
  savings: number;
  savingsPercent: number;
} {
  const pricing = MODEL_PRICING[model];

  if (!pricing) {
    return {
      withCaching: 0,
      withoutCaching: 0,
      savings: 0,
      savingsPercent: 0,
    };
  }

  let withCaching = 0;
  let withoutCaching = 0;

  // First turn: cache write
  const firstTurnInput = systemPromptTokens + avgUserMessageTokens;
  withCaching += (firstTurnInput / 1_000_000) * pricing.inputPer1M;
  if (pricing.cacheWritePer1M) {
    withCaching += (systemPromptTokens / 1_000_000) * pricing.cacheWritePer1M;
  }
  withCaching += (avgAssistantTokens / 1_000_000) * pricing.outputPer1M;
  withoutCaching += (firstTurnInput / 1_000_000) * pricing.inputPer1M;
  withoutCaching += (avgAssistantTokens / 1_000_000) * pricing.outputPer1M;

  // Subsequent turns: cache hits
  for (let turn = 2; turn <= turns; turn++) {
    // With caching: system prompt is cached, history grows
    const historyTokens = (turn - 1) * (avgUserMessageTokens + avgAssistantTokens);
    const cachedTokens = systemPromptTokens;
    const uncachedTokens = historyTokens + avgUserMessageTokens;

    withCaching += (cachedTokens / 1_000_000) * pricing.cachedInputPer1M;
    withCaching += (uncachedTokens / 1_000_000) * pricing.inputPer1M;
    withCaching += (avgAssistantTokens / 1_000_000) * pricing.outputPer1M;

    // Without caching: everything is full price
    const totalInput = systemPromptTokens + historyTokens + avgUserMessageTokens;
    withoutCaching += (totalInput / 1_000_000) * pricing.inputPer1M;
    withoutCaching += (avgAssistantTokens / 1_000_000) * pricing.outputPer1M;
  }

  const savings = withoutCaching - withCaching;
  const savingsPercent = withoutCaching > 0
    ? (savings / withoutCaching) * 100
    : 0;

  return {
    withCaching,
    withoutCaching,
    savings,
    savingsPercent,
  };
}

/**
 * Format cost as a human-readable string.
 */
export function formatCost(cost: number): string {
  if (cost < 0.01) {
    return `$${(cost * 1000).toFixed(3)}m`; // millicents
  }
  if (cost < 1) {
    return `$${cost.toFixed(4)}`;
  }
  return `$${cost.toFixed(2)}`;
}

/**
 * Print a cost comparison table.
 */
export function printCostComparison(
  systemPromptTokens: number,
  turns: number,
  models: string[]
): void {
  console.log('\n╔════════════════════════════════════════════════════════════════╗');
  console.log('║                    Cost Comparison Table                       ║');
  console.log('╠════════════════════════════════════════════════════════════════╣');
  console.log(`║  System prompt: ${systemPromptTokens} tokens, ${turns} turns                        ║`);
  console.log('╠════════════════════════════════════════════════════════════════╣');
  console.log('║  Model                    │ No Cache │ Cached  │ Savings      ║');
  console.log('╟───────────────────────────┼──────────┼─────────┼──────────────╢');

  for (const model of models) {
    const projection = projectConversationCost(
      systemPromptTokens,
      100,  // avg user message
      500,  // avg assistant response
      turns,
      model
    );

    const modelName = model.split('/')[1]?.slice(0, 23) ?? model.slice(0, 23);
    const noCacheCost = formatCost(projection.withoutCaching).padStart(8);
    const cachedCost = formatCost(projection.withCaching).padStart(7);
    const savings = `${projection.savingsPercent.toFixed(1)}%`.padStart(12);

    console.log(`║  ${modelName.padEnd(23)} │ ${noCacheCost} │ ${cachedCost} │ ${savings} ║`);
  }

  console.log('╚════════════════════════════════════════════════════════════════╝');
}
