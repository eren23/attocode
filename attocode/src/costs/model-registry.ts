import type { ModelConfig, UsageRecord, CostBreakdown } from './types.js';

/**
 * Default model configurations with current pricing (2024/2025).
 * Pricing sourced from official provider documentation.
 */
const DEFAULT_MODELS: ModelConfig[] = [
  // Claude models (Anthropic)
  {
    modelId: 'claude-3-5-sonnet-20241022',
    provider: 'anthropic',
    displayName: 'Claude 3.5 Sonnet',
    pricing: {
      promptPerMillion: 3.0,
      completionPerMillion: 15.0,
      cacheReadPerMillion: 0.30,
      cacheWritePerMillion: 3.75,
    },
    capabilities: {
      maxContextTokens: 200000,
      maxOutputTokens: 8192,
      supportsVision: true,
      supportsTools: true,
      supportsCaching: true,
    },
  },
  {
    modelId: 'claude-3-5-haiku-20241022',
    provider: 'anthropic',
    displayName: 'Claude 3.5 Haiku',
    pricing: {
      promptPerMillion: 0.80,
      completionPerMillion: 4.0,
      cacheReadPerMillion: 0.08,
      cacheWritePerMillion: 1.0,
    },
    capabilities: {
      maxContextTokens: 200000,
      maxOutputTokens: 8192,
      supportsVision: true,
      supportsTools: true,
      supportsCaching: true,
    },
  },
  {
    modelId: 'claude-3-opus-20240229',
    provider: 'anthropic',
    displayName: 'Claude 3 Opus',
    pricing: {
      promptPerMillion: 15.0,
      completionPerMillion: 75.0,
      cacheReadPerMillion: 1.50,
      cacheWritePerMillion: 18.75,
    },
    capabilities: {
      maxContextTokens: 200000,
      maxOutputTokens: 4096,
      supportsVision: true,
      supportsTools: true,
      supportsCaching: true,
    },
  },
  // GPT-4o models (OpenAI)
  {
    modelId: 'gpt-4o',
    provider: 'openai',
    displayName: 'GPT-4o',
    pricing: {
      promptPerMillion: 2.50,
      completionPerMillion: 10.0,
    },
    capabilities: {
      maxContextTokens: 128000,
      maxOutputTokens: 16384,
      supportsVision: true,
      supportsTools: true,
    },
  },
  {
    modelId: 'gpt-4o-mini',
    provider: 'openai',
    displayName: 'GPT-4o Mini',
    pricing: {
      promptPerMillion: 0.15,
      completionPerMillion: 0.60,
    },
    capabilities: {
      maxContextTokens: 128000,
      maxOutputTokens: 16384,
      supportsVision: true,
      supportsTools: true,
    },
  },
  {
    modelId: 'gpt-4-turbo',
    provider: 'openai',
    displayName: 'GPT-4 Turbo',
    pricing: {
      promptPerMillion: 10.0,
      completionPerMillion: 30.0,
    },
    capabilities: {
      maxContextTokens: 128000,
      maxOutputTokens: 4096,
      supportsVision: true,
      supportsTools: true,
    },
  },
];

/**
 * Registry for model configurations with caching and cost calculation.
 * Provides a centralized way to manage model metadata and pricing.
 */
export class ModelRegistry {
  private models: Map<string, ModelConfig> = new Map();
  private cacheTimestamp: number = 0;
  private readonly cacheDurationMs: number;

  /**
   * Creates a new ModelRegistry instance.
   * @param cacheDurationMs - How long to cache model configs (default: 24 hours)
   */
  constructor(cacheDurationMs: number = 24 * 60 * 60 * 1000) {
    this.cacheDurationMs = cacheDurationMs;
    this.loadDefaults();
  }

  /**
   * Loads default model configurations into the registry.
   */
  private loadDefaults(): void {
    for (const model of DEFAULT_MODELS) {
      this.models.set(model.modelId, model);
    }
    this.cacheTimestamp = Date.now();
  }

  /**
   * Gets a model configuration by ID.
   * @param modelId - The unique model identifier
   * @returns The model config or undefined if not found
   */
  getModel(modelId: string): ModelConfig | undefined {
    return this.models.get(modelId);
  }

  /**
   * Gets all registered models.
   * @returns Array of all model configurations
   */
  getAllModels(): ModelConfig[] {
    return Array.from(this.models.values());
  }

  /**
   * Gets models filtered by provider.
   * @param provider - The provider name to filter by
   * @returns Array of models from the specified provider
   */
  getModelsByProvider(provider: string): ModelConfig[] {
    return this.getAllModels().filter(m => m.provider === provider);
  }

  /**
   * Adds or updates a model configuration.
   * @param config - The model configuration to set
   */
  setModel(config: ModelConfig): void {
    this.models.set(config.modelId, config);
  }

  /**
   * Calculates cost breakdown for a usage record.
   * Uses default pricing if model is not found in registry.
   * @param usage - The usage record with token counts
   * @returns Cost breakdown with prompt, completion, cache, and total costs
   */
  calculateCost(usage: UsageRecord): CostBreakdown {
    const model = this.getModel(usage.modelId);

    // Default pricing if model not found (Claude 3.5 Sonnet pricing as fallback)
    const pricing = model?.pricing ?? {
      promptPerMillion: 3.0,
      completionPerMillion: 15.0,
    };

    const promptCost = (usage.promptTokens / 1_000_000) * pricing.promptPerMillion;
    const completionCost = (usage.completionTokens / 1_000_000) * pricing.completionPerMillion;

    let cacheCost = 0;
    if (usage.cacheReadTokens && pricing.cacheReadPerMillion) {
      cacheCost += (usage.cacheReadTokens / 1_000_000) * pricing.cacheReadPerMillion;
    }
    if (usage.cacheWriteTokens && pricing.cacheWritePerMillion) {
      cacheCost += (usage.cacheWriteTokens / 1_000_000) * pricing.cacheWritePerMillion;
    }

    const totalCost = promptCost + completionCost + cacheCost;

    return {
      promptCost,
      completionCost,
      cacheCost,
      totalCost,
      formatted: `$${totalCost.toFixed(4)}`,
    };
  }

  /**
   * Checks if the cache needs to be refreshed based on cache duration.
   * @returns True if cache is stale and needs refresh
   */
  needsRefresh(): boolean {
    return Date.now() - this.cacheTimestamp > this.cacheDurationMs;
  }

  /**
   * Refreshes the cache timestamp.
   * In future, this could fetch updated pricing from an API.
   */
  refreshCache(): void {
    // In future, this could fetch from an API
    // For now, just reset the timestamp
    this.cacheTimestamp = Date.now();
  }

  /**
   * Exports the current cache state for persistence.
   * @returns Object containing models array and timestamp
   */
  exportCache(): { models: ModelConfig[]; timestamp: number } {
    return {
      models: this.getAllModels(),
      timestamp: this.cacheTimestamp,
    };
  }

  /**
   * Imports a previously exported cache.
   * @param cache - The cache object to import
   */
  importCache(cache: { models: ModelConfig[]; timestamp: number }): void {
    this.models.clear();
    for (const model of cache.models) {
      this.models.set(model.modelId, model);
    }
    this.cacheTimestamp = cache.timestamp;
  }
}

/**
 * Singleton instance of ModelRegistry for global access.
 * Use this for shared model configuration across the application.
 */
export const modelRegistry = new ModelRegistry();
