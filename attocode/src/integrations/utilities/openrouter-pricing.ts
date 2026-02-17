/**
 * OpenRouter Pricing Integration
 *
 * Fetches and caches real pricing data from OpenRouter's API
 * for accurate cost estimation.
 */

import { logger } from './logger.js';

// =============================================================================
// TYPES
// =============================================================================

export interface ModelPricing {
  prompt: number;      // Cost per token (input)
  completion: number;  // Cost per token (output)
  request: number;     // Per-request cost (if any)
  image: number;       // Cost per image token
}

export interface ModelInfo {
  id: string;
  name: string;
  pricing: ModelPricing;
  contextLength: number;
}

interface OpenRouterModel {
  id: string;
  name: string;
  pricing: {
    prompt: string;
    completion: string;
    request?: string;
    image?: string;
  };
  context_length: number;
}

interface OpenRouterModelsResponse {
  data: OpenRouterModel[];
}

// =============================================================================
// MODEL INFO CACHE
// =============================================================================

let pricingCache: Map<string, ModelPricing> = new Map();
let contextLengthCache: Map<string, number> = new Map();
let cacheTimestamp: number = 0;
const CACHE_TTL = 3600000; // 1 hour

// Default fallback pricing - conservative mid-tier estimate
// Using Gemini Flash tier pricing as default since it's the default model
// This prevents massive overestimation when actual pricing can't be fetched
const DEFAULT_PRICING: ModelPricing = {
  prompt: 0.000000075,    // $0.075 per million tokens (Gemini Flash tier)
  completion: 0.0000003,  // $0.30 per million tokens (Gemini Flash tier)
  request: 0,
  image: 0,
};

// =============================================================================
// FETCH PRICING
// =============================================================================

/**
 * Result of fetching OpenRouter model data.
 */
interface OpenRouterModelData {
  pricing: Map<string, ModelPricing>;
  contextLengths: Map<string, number>;
}

/**
 * Fetch model data (pricing + context lengths) from OpenRouter API.
 */
export async function fetchOpenRouterModels(): Promise<OpenRouterModelData> {
  const apiKey = process.env.OPENROUTER_API_KEY;

  if (!apiKey) {
    logger.info('⚠️  No OPENROUTER_API_KEY - using default estimates');
    return { pricing: new Map(), contextLengths: new Map() };
  }

  try {
    const response = await fetch('https://openrouter.ai/api/v1/models', {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`OpenRouter API error: ${response.status}`);
    }

    const data = await response.json() as OpenRouterModelsResponse;
    const pricing = new Map<string, ModelPricing>();
    const contextLengths = new Map<string, number>();

    for (const model of data.data) {
      pricing.set(model.id, {
        prompt: parseFloat(model.pricing.prompt) || 0,
        completion: parseFloat(model.pricing.completion) || 0,
        request: parseFloat(model.pricing.request || '0'),
        image: parseFloat(model.pricing.image || '0'),
      });

      // Store context length
      if (model.context_length) {
        contextLengths.set(model.id, model.context_length);
      }
    }

    return { pricing, contextLengths };
  } catch (error) {
    logger.info(`⚠️  Failed to fetch OpenRouter models: ${(error as Error).message}`);
    return { pricing: new Map(), contextLengths: new Map() };
  }
}

/**
 * @deprecated Use fetchOpenRouterModels() instead
 */
export async function fetchOpenRouterPricing(): Promise<Map<string, ModelPricing>> {
  const { pricing } = await fetchOpenRouterModels();
  return pricing;
}

/**
 * Initialize or refresh the model info cache (pricing + context lengths).
 */
export async function initModelCache(): Promise<void> {
  const now = Date.now();

  // Only refresh if cache is stale
  if (pricingCache.size > 0 && (now - cacheTimestamp) < CACHE_TTL) {
    return;
  }

  const { pricing, contextLengths } = await fetchOpenRouterModels();
  if (pricing.size > 0) {
    pricingCache = pricing;
    contextLengthCache = contextLengths;
    cacheTimestamp = now;
    logger.info(`💰 Loaded ${pricing.size} models from OpenRouter (pricing + context limits)`);
  }
}

/**
 * @deprecated Use initModelCache() instead
 */
export async function initPricingCache(): Promise<void> {
  return initModelCache();
}

// =============================================================================
// PRICING LOOKUP
// =============================================================================

/**
 * Get pricing for a specific model.
 */
export function getModelPricing(modelId: string): ModelPricing {
  // Direct lookup
  if (pricingCache.has(modelId)) {
    return pricingCache.get(modelId)!;
  }

  // Try without provider prefix (e.g., "gpt-4" instead of "openai/gpt-4")
  const shortId = modelId.split('/').pop() || modelId;
  for (const [id, pricing] of pricingCache) {
    if (id.endsWith(shortId) || id.includes(shortId)) {
      return pricing;
    }
  }

  // Return default
  return DEFAULT_PRICING;
}

/**
 * Get context length (max tokens) for a specific model.
 * Returns undefined if the model is not in the cache.
 */
export function getModelContextLength(modelId: string): number | undefined {
  // Direct lookup
  if (contextLengthCache.has(modelId)) {
    return contextLengthCache.get(modelId);
  }

  // Try without provider prefix (e.g., "gpt-4" instead of "openai/gpt-4")
  const shortId = modelId.split('/').pop() || modelId;
  for (const [id, contextLength] of contextLengthCache) {
    if (id.endsWith(shortId) || id.includes(shortId)) {
      return contextLength;
    }
  }

  return undefined;
}

/**
 * Check if model cache has been initialized.
 */
export function isModelCacheInitialized(): boolean {
  return pricingCache.size > 0;
}

/**
 * Calculate cost for a completion.
 */
export function calculateCost(
  modelId: string,
  inputTokens: number,
  outputTokens: number
): number {
  const pricing = getModelPricing(modelId);

  const inputCost = inputTokens * pricing.prompt;
  const outputCost = outputTokens * pricing.completion;
  const requestCost = pricing.request;

  return inputCost + outputCost + requestCost;
}

/**
 * Format cost for display.
 */
export function formatCost(cost: number): string {
  if (cost < 0.0001) {
    return `$${(cost * 1000000).toFixed(2)}µ`; // Microdollars for tiny amounts
  }
  if (cost < 0.01) {
    return `$${cost.toFixed(6)}`;
  }
  return `$${cost.toFixed(4)}`;
}

// =============================================================================
// EXPORTS
// =============================================================================

export { pricingCache, contextLengthCache, DEFAULT_PRICING };
