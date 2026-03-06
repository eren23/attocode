/**
 * Token Analyzer
 *
 * Analyzes token flow and usage patterns across a session.
 */

import type { ParsedSession, TokenFlowAnalysis } from '../types.js';

// =============================================================================
// MODEL PRICING
// =============================================================================

/**
 * Model pricing data (per 1K tokens).
 * Source: OpenRouter API / provider documentation.
 */
interface ModelPricing {
  inputPer1k: number;
  outputPer1k: number;
  cachedPer1k: number;
}

/**
 * Known model pricing (per 1K tokens).
 * Prices sourced from OpenRouter API and provider docs.
 */
const MODEL_PRICING: Record<string, ModelPricing> = {
  // Claude models (Anthropic)
  'claude-3-5-sonnet-20241022': { inputPer1k: 0.003, outputPer1k: 0.015, cachedPer1k: 0.0003 },
  'claude-3-sonnet': { inputPer1k: 0.003, outputPer1k: 0.015, cachedPer1k: 0.0003 },
  'claude-3-5-haiku-20241022': { inputPer1k: 0.0008, outputPer1k: 0.004, cachedPer1k: 0.00008 },
  'claude-3-haiku': { inputPer1k: 0.00025, outputPer1k: 0.00125, cachedPer1k: 0.000025 },
  'claude-3-opus': { inputPer1k: 0.015, outputPer1k: 0.075, cachedPer1k: 0.0015 },
  'anthropic/claude-3.5-sonnet': { inputPer1k: 0.003, outputPer1k: 0.015, cachedPer1k: 0.0003 },
  'anthropic/claude-3-sonnet': { inputPer1k: 0.003, outputPer1k: 0.015, cachedPer1k: 0.0003 },

  // GPT models (OpenAI)
  'gpt-4o': { inputPer1k: 0.0025, outputPer1k: 0.01, cachedPer1k: 0.00125 },
  'gpt-4o-mini': { inputPer1k: 0.00015, outputPer1k: 0.0006, cachedPer1k: 0.000075 },
  'gpt-4-turbo': { inputPer1k: 0.01, outputPer1k: 0.03, cachedPer1k: 0.005 },
  'openai/gpt-4o': { inputPer1k: 0.0025, outputPer1k: 0.01, cachedPer1k: 0.00125 },
  'openai/gpt-4o-mini': { inputPer1k: 0.00015, outputPer1k: 0.0006, cachedPer1k: 0.000075 },

  // GLM models (Z-AI / Zhipu)
  'z-ai/glm-4.7': { inputPer1k: 0.0001, outputPer1k: 0.0002, cachedPer1k: 0.00001 },
  'glm-4': { inputPer1k: 0.0001, outputPer1k: 0.0002, cachedPer1k: 0.00001 },

  // Gemini models (Google)
  'google/gemini-pro': { inputPer1k: 0.000125, outputPer1k: 0.000375, cachedPer1k: 0.0000125 },
  'google/gemini-flash-1.5': { inputPer1k: 0.000075, outputPer1k: 0.0003, cachedPer1k: 0.0000075 },

  // DeepSeek
  'deepseek/deepseek-chat': { inputPer1k: 0.00014, outputPer1k: 0.00028, cachedPer1k: 0.000014 },
  'deepseek/deepseek-coder': { inputPer1k: 0.00014, outputPer1k: 0.00028, cachedPer1k: 0.000014 },

  // Llama models (Meta via providers)
  'meta-llama/llama-3.1-70b-instruct': { inputPer1k: 0.00052, outputPer1k: 0.00075, cachedPer1k: 0.000052 },
  'meta-llama/llama-3.1-8b-instruct': { inputPer1k: 0.00006, outputPer1k: 0.00006, cachedPer1k: 0.000006 },

  // Qwen models
  'qwen/qwen-2.5-72b-instruct': { inputPer1k: 0.00035, outputPer1k: 0.0004, cachedPer1k: 0.000035 },
};

/**
 * Default pricing (Gemini Flash tier - conservative mid-tier estimate).
 * This prevents massive overestimation for unknown models.
 */
const DEFAULT_PRICING: ModelPricing = {
  inputPer1k: 0.000075,
  outputPer1k: 0.0003,
  cachedPer1k: 0.0000075,
};

/**
 * Get pricing for a model.
 * Tries exact match, then partial match, then falls back to default.
 */
function getModelPricing(modelId: string): ModelPricing {
  // Exact match
  if (MODEL_PRICING[modelId]) {
    return MODEL_PRICING[modelId];
  }

  // Try lowercase
  const lower = modelId.toLowerCase();
  if (MODEL_PRICING[lower]) {
    return MODEL_PRICING[lower];
  }

  // Partial match (e.g., "claude-3-5-sonnet" matches "claude-3-5-sonnet-20241022")
  for (const [key, pricing] of Object.entries(MODEL_PRICING)) {
    if (lower.includes(key) || key.includes(lower)) {
      return pricing;
    }
  }

  // Match by key terms
  if (lower.includes('sonnet')) {
    return MODEL_PRICING['claude-3-sonnet'];
  }
  if (lower.includes('haiku')) {
    return MODEL_PRICING['claude-3-haiku'];
  }
  if (lower.includes('opus')) {
    return MODEL_PRICING['claude-3-opus'];
  }
  if (lower.includes('gpt-4o-mini')) {
    return MODEL_PRICING['gpt-4o-mini'];
  }
  if (lower.includes('gpt-4o') || lower.includes('gpt4o')) {
    return MODEL_PRICING['gpt-4o'];
  }
  if (lower.includes('glm')) {
    return MODEL_PRICING['z-ai/glm-4.7'];
  }
  if (lower.includes('gemini')) {
    return MODEL_PRICING['google/gemini-flash-1.5'];
  }
  if (lower.includes('deepseek')) {
    return MODEL_PRICING['deepseek/deepseek-chat'];
  }
  if (lower.includes('llama')) {
    return MODEL_PRICING['meta-llama/llama-3.1-70b-instruct'];
  }
  if (lower.includes('qwen')) {
    return MODEL_PRICING['qwen/qwen-2.5-72b-instruct'];
  }

  return DEFAULT_PRICING;
}

/**
 * Analyzes token flow in a session.
 */
export class TokenAnalyzer {
  constructor(private session: ParsedSession) {}

  /**
   * Perform full token flow analysis.
   */
  analyze(): TokenFlowAnalysis {
    return {
      perIteration: this.analyzePerIteration(),
      cumulative: this.analyzeCumulative(),
      costBreakdown: this.calculateCostBreakdown(),
    };
  }

  /**
   * Analyze tokens per iteration.
   */
  private analyzePerIteration(): TokenFlowAnalysis['perIteration'] {
    return this.session.iterations.map(iter => {
      const input = iter.metrics.inputTokens;
      const output = iter.metrics.outputTokens;
      const hitRate = iter.metrics.cacheHitRate;
      const cached = Math.round(input * hitRate);
      const fresh = input - cached;

      return {
        iteration: iter.number,
        input,
        output,
        thinking: iter.thinking?.estimatedTokens,
        cached,
        fresh,
      };
    });
  }

  /**
   * Analyze cumulative token usage.
   */
  private analyzeCumulative(): TokenFlowAnalysis['cumulative'] {
    let totalInput = 0;
    let totalOutput = 0;
    let totalCached = 0;

    return this.session.iterations.map(iter => {
      totalInput += iter.metrics.inputTokens;
      totalOutput += iter.metrics.outputTokens;
      totalCached += Math.round(iter.metrics.inputTokens * iter.metrics.cacheHitRate);

      return {
        iteration: iter.number,
        totalInput,
        totalOutput,
        totalCached,
      };
    });
  }

  /**
   * Calculate cost breakdown using model-specific pricing.
   */
  private calculateCostBreakdown(): TokenFlowAnalysis['costBreakdown'] {
    const metrics = this.session.metrics;
    const pricing = getModelPricing(this.session.model);

    const cachedTokens = metrics.tokensSavedByCache;
    const freshInput = metrics.inputTokens - cachedTokens;

    const inputCost = (freshInput / 1000) * pricing.inputPer1k;
    const outputCost = (metrics.outputTokens / 1000) * pricing.outputPer1k;
    const cachedCost = (cachedTokens / 1000) * pricing.cachedPer1k;
    const totalCost = inputCost + outputCost + cachedCost;

    // What it would have cost without caching
    const fullInputCost = (metrics.inputTokens / 1000) * pricing.inputPer1k;
    const savings = fullInputCost - inputCost - cachedCost;

    return {
      inputCost,
      outputCost,
      cachedCost,
      totalCost,
      savings,
    };
  }

  /**
   * Get token usage trend.
   */
  getTokenTrend(): 'increasing' | 'stable' | 'decreasing' {
    const iterations = this.session.iterations;
    if (iterations.length < 3) return 'stable';

    const firstHalf = iterations.slice(0, Math.floor(iterations.length / 2));
    const secondHalf = iterations.slice(Math.floor(iterations.length / 2));

    const firstAvg = firstHalf.reduce((sum, i) => sum + i.metrics.inputTokens, 0) / firstHalf.length;
    const secondAvg = secondHalf.reduce((sum, i) => sum + i.metrics.inputTokens, 0) / secondHalf.length;

    const change = (secondAvg - firstAvg) / firstAvg;
    if (change > 0.2) return 'increasing';
    if (change < -0.2) return 'decreasing';
    return 'stable';
  }

  /**
   * Get peak token usage iteration.
   */
  getPeakIteration(): { iteration: number; tokens: number } {
    let peak = { iteration: 0, tokens: 0 };

    for (const iter of this.session.iterations) {
      const total = iter.metrics.inputTokens + iter.metrics.outputTokens;
      if (total > peak.tokens) {
        peak = { iteration: iter.number, tokens: total };
      }
    }

    return peak;
  }

  /**
   * Format token count for display.
   */
  static formatTokens(count: number): string {
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
    return count.toString();
  }
}

/**
 * Factory function.
 */
export function createTokenAnalyzer(session: ParsedSession): TokenAnalyzer {
  return new TokenAnalyzer(session);
}
