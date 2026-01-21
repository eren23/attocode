/**
 * Trick B: Token Counting
 *
 * Estimate token counts and costs for LLM API calls.
 * Uses character-based heuristics (production would use tiktoken).
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Token count breakdown.
 */
export interface TokenCounts {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

/**
 * Model pricing configuration.
 */
export interface ModelPricing {
  inputPer1kTokens: number;
  outputPer1kTokens: number;
  cachePer1kTokens?: number;
}

/**
 * Cost estimate.
 */
export interface CostEstimate {
  inputCost: number;
  outputCost: number;
  totalCost: number;
  currency: string;
}

// =============================================================================
// MODEL PRICING DATABASE
// =============================================================================

const MODEL_PRICING: Record<string, ModelPricing> = {
  // OpenAI
  'gpt-4': { inputPer1kTokens: 0.03, outputPer1kTokens: 0.06 },
  'gpt-4-turbo': { inputPer1kTokens: 0.01, outputPer1kTokens: 0.03 },
  'gpt-4o': { inputPer1kTokens: 0.005, outputPer1kTokens: 0.015 },
  'gpt-4o-mini': { inputPer1kTokens: 0.00015, outputPer1kTokens: 0.0006 },
  'gpt-3.5-turbo': { inputPer1kTokens: 0.0005, outputPer1kTokens: 0.0015 },

  // Anthropic
  'claude-3-opus': { inputPer1kTokens: 0.015, outputPer1kTokens: 0.075 },
  'claude-3-sonnet': { inputPer1kTokens: 0.003, outputPer1kTokens: 0.015 },
  'claude-3-haiku': { inputPer1kTokens: 0.00025, outputPer1kTokens: 0.00125 },
  'claude-3.5-sonnet': { inputPer1kTokens: 0.003, outputPer1kTokens: 0.015 },

  // Default for unknown models
  default: { inputPer1kTokens: 0.01, outputPer1kTokens: 0.03 },
};

// =============================================================================
// TOKEN COUNTING
// =============================================================================

/**
 * Estimate token count for text.
 * Uses simple heuristic: ~4 characters per token for English.
 * Production should use tiktoken or model-specific tokenizer.
 */
export function countTokens(text: string, model: string = 'default'): number {
  // Model-specific adjustments
  const multiplier = getModelMultiplier(model);

  // Basic heuristic: ~4 chars per token
  // Adjust for whitespace and punctuation
  const baseCount = Math.ceil(text.length / 4);

  // Count special tokens (newlines, etc.)
  const newlines = (text.match(/\n/g) || []).length;
  const specialTokens = Math.ceil(newlines * 0.5);

  return Math.ceil((baseCount + specialTokens) * multiplier);
}

/**
 * Get model-specific multiplier for token estimation.
 */
function getModelMultiplier(model: string): number {
  // GPT-4 and Claude use similar tokenization
  if (model.includes('gpt') || model.includes('claude')) {
    return 1.0;
  }
  // Some models use different tokenizers
  if (model.includes('llama')) {
    return 1.1;
  }
  return 1.0;
}

/**
 * Count tokens for a conversation.
 */
export function countConversationTokens(
  messages: Array<{ role: string; content: string }>,
  model: string = 'default'
): number {
  let total = 0;

  for (const message of messages) {
    // Each message has overhead (~4 tokens for role, formatting)
    total += 4;
    total += countTokens(message.content, model);
  }

  // Add conversation overhead
  total += 3;

  return total;
}

// =============================================================================
// COST ESTIMATION
// =============================================================================

/**
 * Estimate cost for token usage.
 */
export function estimateCost(tokens: TokenCounts, model: string = 'default'): CostEstimate {
  const pricing = MODEL_PRICING[model] || MODEL_PRICING['default'];

  const inputCost = (tokens.inputTokens / 1000) * pricing.inputPer1kTokens;
  const outputCost = (tokens.outputTokens / 1000) * pricing.outputPer1kTokens;

  return {
    inputCost,
    outputCost,
    totalCost: inputCost + outputCost,
    currency: 'USD',
  };
}

/**
 * Format cost for display.
 */
export function formatCost(cost: CostEstimate): string {
  if (cost.totalCost < 0.01) {
    return `$${(cost.totalCost * 100).toFixed(4)}¢`;
  }
  return `$${cost.totalCost.toFixed(4)}`;
}

/**
 * Estimate cost for a prompt/response pair.
 */
export function estimateCallCost(
  prompt: string,
  response: string,
  model: string = 'default'
): CostEstimate {
  const tokens: TokenCounts = {
    inputTokens: countTokens(prompt, model),
    outputTokens: countTokens(response, model),
    totalTokens: 0,
  };
  tokens.totalTokens = tokens.inputTokens + tokens.outputTokens;

  return estimateCost(tokens, model);
}

// =============================================================================
// BUDGET TRACKING
// =============================================================================

/**
 * Simple budget tracker.
 */
export class BudgetTracker {
  private spent: number = 0;
  private limit: number;
  private history: Array<{ timestamp: Date; amount: number; model: string }> = [];

  constructor(limitUsd: number) {
    this.limit = limitUsd;
  }

  /**
   * Record a cost.
   */
  record(amount: number, model: string): void {
    this.spent += amount;
    this.history.push({ timestamp: new Date(), amount, model });
  }

  /**
   * Check if within budget.
   */
  isWithinBudget(): boolean {
    return this.spent < this.limit;
  }

  /**
   * Get remaining budget.
   */
  remaining(): number {
    return Math.max(0, this.limit - this.spent);
  }

  /**
   * Get usage summary.
   */
  summary(): { spent: number; limit: number; remaining: number; calls: number } {
    return {
      spent: this.spent,
      limit: this.limit,
      remaining: this.remaining(),
      calls: this.history.length,
    };
  }

  /**
   * Get cost breakdown by model.
   */
  byModel(): Record<string, number> {
    const result: Record<string, number> = {};
    for (const entry of this.history) {
      result[entry.model] = (result[entry.model] || 0) + entry.amount;
    }
    return result;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createBudgetTracker(limitUsd: number): BudgetTracker {
  return new BudgetTracker(limitUsd);
}

export function getModelPricing(model: string): ModelPricing {
  return MODEL_PRICING[model] || MODEL_PRICING['default'];
}

// Usage:
// const tokens = countTokens("Hello, how are you?", "gpt-4");
// const cost = estimateCost({ inputTokens: tokens, outputTokens: 50, totalTokens: tokens + 50 }, "gpt-4");
// console.log(formatCost(cost)); // "$0.0045"
