/**
 * Cost tracking and model registry module.
 * Provides model configuration, pricing, and cost calculation utilities.
 *
 * @example
 * ```typescript
 * import { modelRegistry, type UsageRecord } from './costs/index.js';
 *
 * const usage: UsageRecord = {
 *   modelId: 'claude-3-5-sonnet-20241022',
 *   promptTokens: 1000,
 *   completionTokens: 500,
 *   cacheReadTokens: 200,
 * };
 *
 * const cost = modelRegistry.calculateCost(usage);
 * console.log(cost.formatted); // '$0.0195'
 * ```
 */

export * from './types.js';
export * from './model-registry.js';
