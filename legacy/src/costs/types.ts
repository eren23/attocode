/**
 * Model configuration with pricing information.
 */
export interface ModelConfig {
  /** Unique model identifier (e.g., 'claude-3-5-sonnet-20241022') */
  modelId: string;
  /** Provider name (e.g., 'anthropic', 'openai', 'openrouter') */
  provider: 'anthropic' | 'openai' | 'openrouter' | string;
  /** Human-readable display name */
  displayName: string;
  /** Pricing per million tokens */
  pricing: {
    promptPerMillion: number;
    completionPerMillion: number;
    /** Cache read pricing (if supported) */
    cacheReadPerMillion?: number;
    /** Cache write pricing (if supported) */
    cacheWritePerMillion?: number;
  };
  /** Model capabilities */
  capabilities: {
    maxContextTokens: number;
    maxOutputTokens: number;
    supportsVision?: boolean;
    supportsTools?: boolean;
    supportsCaching?: boolean;
  };
}

/**
 * Usage record for cost calculation.
 */
export interface UsageRecord {
  modelId: string;
  promptTokens: number;
  completionTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
}

/**
 * Calculated cost breakdown.
 */
export interface CostBreakdown {
  promptCost: number;
  completionCost: number;
  cacheCost: number;
  totalCost: number;
  /** Cost formatted as string (e.g., '$0.0123') */
  formatted: string;
}
