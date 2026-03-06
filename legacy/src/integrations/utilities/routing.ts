/**
 * Lesson 23: Routing Integration
 *
 * Integrates model routing (Lesson 22) into the production agent.
 * Provides intelligent model selection and fallback capabilities.
 */

import type { RoutingConfig, LLMProvider, Message, ChatResponse } from '../../types.js';
import type { MessageWithContent } from '../../providers/types.js';
import { logger } from './logger.js';

// =============================================================================
// MODEL CAPABILITY
// =============================================================================

interface ModelCapability {
  model: string;
  provider: LLMProvider;
  maxTokens: number;
  supportsTools: boolean;
  supportsVision: boolean;
  costPer1kInput: number;
  costPer1kOutput: number;
  latencyMs: number;
  qualityScore: number;
  available: boolean;
  errorCount: number;
  lastError?: Date;
}

// =============================================================================
// ROUTING MANAGER
// =============================================================================

/**
 * Manages model routing and fallbacks.
 */
export class RoutingManager {
  private config: RoutingConfig;
  private models: Map<string, ModelCapability> = new Map();
  private circuitState: Map<string, CircuitState> = new Map();

  constructor(config: RoutingConfig) {
    this.config = config;
    this.initializeModels();
  }

  /**
   * Initialize models from config.
   */
  private initializeModels(): void {
    for (const modelConfig of this.config.models || []) {
      const capability: ModelCapability = {
        model: modelConfig.id,
        provider: modelConfig.provider,
        maxTokens: modelConfig.maxTokens || 4096,
        supportsTools: modelConfig.capabilities?.includes('tools') ?? true,
        supportsVision: modelConfig.capabilities?.includes('vision') ?? false,
        costPer1kInput: modelConfig.costPer1kInput || 0.001,
        costPer1kOutput: modelConfig.costPer1kOutput || 0.002,
        latencyMs: 0, // Will be updated with actual measurements
        qualityScore: 0.8, // Default quality score
        available: true,
        errorCount: 0,
      };
      this.models.set(modelConfig.id, capability);

      // Initialize circuit breaker state
      this.circuitState.set(modelConfig.id, {
        state: 'closed',
        failures: 0,
        lastFailure: undefined,
        nextAttempt: undefined,
      });
    }
  }

  /**
   * Select best model for a task.
   */
  selectModel(context: TaskContext): string | null {
    // Check routing rules first (function-based from RoutingConfig)
    for (const rule of this.config.rules || []) {
      // RoutingRule.condition is a function that takes RoutingContext
      const routingContext = {
        task: context.task,
        complexity: context.complexity,
        requiredCapabilities: context.hasTools ? ['tools'] : [],
      };
      if (rule.condition(routingContext)) {
        const model = this.models.get(rule.model);
        if (model && this.isModelAvailable(rule.model)) {
          return rule.model;
        }
      }
    }

    // Use strategy-based selection
    const availableModels = Array.from(this.models.entries())
      .filter(([id]) => this.isModelAvailable(id))
      .map(([_, model]) => model);

    if (availableModels.length === 0) {
      return null;
    }

    switch (this.config.strategy) {
      case 'cost':
        return this.selectByCost(availableModels, context);
      case 'quality':
        return this.selectByQuality(availableModels, context);
      case 'latency':
        return this.selectByLatency(availableModels, context);
      case 'balanced':
      default:
        return this.selectBalanced(availableModels, context);
    }
  }

  /**
   * Evaluate an internal routing rule (object-based conditions).
   * Used for internal rule processing when function-based rules
   * are converted or for custom internal rules.
   */
  private evaluateInternalRule(rule: InternalRoutingRule, context: TaskContext): boolean {
    // Check complexity threshold
    if (rule.condition.minComplexity !== undefined) {
      if (context.complexity < rule.condition.minComplexity) {
        return false;
      }
    }

    if (rule.condition.maxComplexity !== undefined) {
      if (context.complexity > rule.condition.maxComplexity) {
        return false;
      }
    }

    // Check tool requirement
    if (rule.condition.requiresTools && !context.hasTools) {
      return false;
    }

    // Check vision requirement
    if (rule.condition.requiresVision && !context.hasImages) {
      return false;
    }

    // Check task type
    if (rule.condition.taskTypes && rule.condition.taskTypes.length > 0) {
      if (!rule.condition.taskTypes.includes(context.taskType)) {
        return false;
      }
    }

    return true;
  }

  /**
   * Select model by cost (cheapest first).
   */
  private selectByCost(models: ModelCapability[], context: TaskContext): string {
    const estimated = context.estimatedTokens || 1000;
    const sorted = [...models].sort((a, b) => {
      const costA = (estimated / 1000) * (a.costPer1kInput + a.costPer1kOutput);
      const costB = (estimated / 1000) * (b.costPer1kInput + b.costPer1kOutput);
      return costA - costB;
    });
    return sorted[0].model;
  }

  /**
   * Select model by quality (highest first).
   */
  private selectByQuality(models: ModelCapability[], context: TaskContext): string {
    const sorted = [...models].sort((a, b) => b.qualityScore - a.qualityScore);
    return sorted[0].model;
  }

  /**
   * Select model by latency (fastest first).
   */
  private selectByLatency(models: ModelCapability[], context: TaskContext): string {
    const sorted = [...models].sort((a, b) => a.latencyMs - b.latencyMs);
    return sorted[0].model;
  }

  /**
   * Balanced selection considering all factors.
   */
  private selectBalanced(models: ModelCapability[], context: TaskContext): string {
    const estimated = context.estimatedTokens || 1000;

    const scored = models.map((model) => {
      // Normalize scores to 0-1 range
      const costScore =
        1 -
        Math.min(((estimated / 1000) * (model.costPer1kInput + model.costPer1kOutput)) / 0.1, 1);
      const qualityScore = model.qualityScore;
      const latencyScore = 1 - Math.min(model.latencyMs / 5000, 1);

      // Weight based on context
      let costWeight = 0.3;
      let qualityWeight = 0.5;
      let latencyWeight = 0.2;

      if (context.complexity > 7) {
        qualityWeight = 0.7;
        costWeight = 0.15;
        latencyWeight = 0.15;
      } else if (context.complexity < 3) {
        costWeight = 0.5;
        qualityWeight = 0.3;
        latencyWeight = 0.2;
      }

      const score =
        costScore * costWeight + qualityScore * qualityWeight + latencyScore * latencyWeight;

      return { model: model.model, score };
    });

    scored.sort((a, b) => b.score - a.score);
    return scored[0].model;
  }

  /**
   * Check if model is available (circuit breaker).
   */
  isModelAvailable(modelId: string): boolean {
    if (!this.config.circuitBreaker) {
      const model = this.models.get(modelId);
      return model?.available ?? false;
    }

    const circuit = this.circuitState.get(modelId);
    if (!circuit) return false;

    switch (circuit.state) {
      case 'closed':
        return true;
      case 'open':
        // Check if we should try half-open
        if (circuit.nextAttempt && Date.now() >= circuit.nextAttempt.getTime()) {
          circuit.state = 'half-open';
          return true;
        }
        return false;
      case 'half-open':
        return true;
    }
  }

  /**
   * Record successful call.
   */
  recordSuccess(modelId: string): void {
    const circuit = this.circuitState.get(modelId);
    if (!circuit) return;

    circuit.failures = 0;

    if (circuit.state === 'half-open') {
      circuit.state = 'closed';
    }

    const model = this.models.get(modelId);
    if (model) {
      model.errorCount = 0;
    }
  }

  /**
   * Record failed call.
   */
  recordFailure(modelId: string, error: Error): void {
    const circuit = this.circuitState.get(modelId);
    if (!circuit) return;

    circuit.failures++;
    circuit.lastFailure = new Date();

    const model = this.models.get(modelId);
    if (model) {
      model.errorCount++;
      model.lastError = new Date();
    }

    // Open circuit after threshold
    const threshold = 3;
    if (circuit.failures >= threshold) {
      circuit.state = 'open';
      // Try again after 30 seconds
      circuit.nextAttempt = new Date(Date.now() + 30000);
    }
  }

  /**
   * Get provider for a model.
   */
  getProvider(modelId: string): LLMProvider | null {
    const model = this.models.get(modelId);
    return model?.provider || null;
  }

  /**
   * Execute with fallback chain.
   */
  async executeWithFallback(
    messages: (Message | MessageWithContent)[],
    context: TaskContext,
  ): Promise<{ response: ChatResponse; model: string }> {
    // Build fallback chain
    const chain = this.config.fallbackChain?.length
      ? this.config.fallbackChain
      : Array.from(this.models.keys());

    let lastError: Error | null = null;

    for (const modelId of chain) {
      if (!this.isModelAvailable(modelId)) {
        continue;
      }

      const provider = this.getProvider(modelId);
      if (!provider) continue;

      try {
        const response = await provider.chat(messages);
        this.recordSuccess(modelId);
        return { response, model: modelId };
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err));
        this.recordFailure(modelId, lastError);
        logger.warn(`[Routing] Model ${modelId} failed:`, { error: lastError.message });
      }
    }

    throw lastError || new Error('No available models');
  }

  /**
   * Get model statistics.
   */
  getStats(): ModelStats[] {
    return Array.from(this.models.values()).map((model) => ({
      model: model.model,
      available: this.isModelAvailable(model.model),
      circuitState: this.circuitState.get(model.model)?.state || 'unknown',
      errorCount: model.errorCount,
      lastError: model.lastError,
    }));
  }

  /**
   * Add or update a model.
   */
  addModel(capability: Omit<ModelCapability, 'available' | 'errorCount'>): void {
    this.models.set(capability.model, {
      ...capability,
      available: true,
      errorCount: 0,
    });

    this.circuitState.set(capability.model, {
      state: 'closed',
      failures: 0,
      lastFailure: undefined,
      nextAttempt: undefined,
    });
  }

  /**
   * Remove a model.
   */
  removeModel(modelId: string): void {
    this.models.delete(modelId);
    this.circuitState.delete(modelId);
  }

  /**
   * Estimate task complexity.
   */
  estimateComplexity(task: string): number {
    let score = 1;

    // Length-based complexity
    if (task.length > 100) score += 1;
    if (task.length > 200) score += 1;
    if (task.length > 500) score += 1;

    // Keyword-based complexity
    const complexKeywords = [
      'implement',
      'refactor',
      'migrate',
      'integrate',
      'build',
      'create',
      'design',
      'architect',
      'optimize',
      'debug',
      'analyze',
      'compare',
      'evaluate',
      'synthesize',
    ];

    for (const keyword of complexKeywords) {
      if (task.toLowerCase().includes(keyword)) {
        score += 0.5;
      }
    }

    // Multi-step indicators
    if (task.includes(' and ') || task.includes(' then ')) score += 1;
    if (/\d\./.test(task) || task.includes('first')) score += 1;

    return Math.min(Math.round(score), 10);
  }
}

// =============================================================================
// TYPES
// =============================================================================

interface TaskContext {
  task: string;
  complexity: number;
  hasTools: boolean;
  hasImages: boolean;
  taskType: string;
  estimatedTokens?: number;
}

/**
 * Internal routing rule with structured conditions.
 * Different from types.ts RoutingRule which uses function-based conditions.
 */
interface InternalRoutingRule {
  condition: {
    minComplexity?: number;
    maxComplexity?: number;
    requiresTools?: boolean;
    requiresVision?: boolean;
    taskTypes?: string[];
  };
  model: string;
  priority: number;
}

interface CircuitState {
  state: 'closed' | 'open' | 'half-open';
  failures: number;
  lastFailure?: Date;
  nextAttempt?: Date;
}

interface ModelStats {
  model: string;
  available: boolean;
  circuitState: string;
  errorCount: number;
  lastError?: Date;
}

// =============================================================================
// FACTORY
// =============================================================================

export function createRoutingManager(config: RoutingConfig): RoutingManager {
  return new RoutingManager(config);
}
