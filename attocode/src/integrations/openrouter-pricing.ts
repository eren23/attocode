/**
 * OpenRouter Pricing Integration
 *
 * Fetches and caches real pricing data from OpenRouter's API
 * for accurate cost estimation.
 */

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
// PRICING CACHE
// =============================================================================

let pricingCache: Map<string, ModelPricing> = new Map();
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
 * Fetch pricing data from OpenRouter API.
 */
export async function fetchOpenRouterPricing(): Promise<Map<string, ModelPricing>> {
  const apiKey = process.env.OPENROUTER_API_KEY;

  if (!apiKey) {
    console.log('⚠️  No OPENROUTER_API_KEY - using default pricing estimates');
    return new Map();
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

    for (const model of data.data) {
      pricing.set(model.id, {
        prompt: parseFloat(model.pricing.prompt) || 0,
        completion: parseFloat(model.pricing.completion) || 0,
        request: parseFloat(model.pricing.request || '0'),
        image: parseFloat(model.pricing.image || '0'),
      });
    }

    return pricing;
  } catch (error) {
    console.log(`⚠️  Failed to fetch OpenRouter pricing: ${(error as Error).message}`);
    return new Map();
  }
}

/**
 * Initialize or refresh the pricing cache.
 */
export async function initPricingCache(): Promise<void> {
  const now = Date.now();

  // Only refresh if cache is stale
  if (pricingCache.size > 0 && (now - cacheTimestamp) < CACHE_TTL) {
    return;
  }

  const pricing = await fetchOpenRouterPricing();
  if (pricing.size > 0) {
    pricingCache = pricing;
    cacheTimestamp = now;
    console.log(`💰 Loaded pricing for ${pricing.size} models from OpenRouter`);
  }
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

export { pricingCache, DEFAULT_PRICING };
