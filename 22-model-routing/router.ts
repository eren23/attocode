/**
 * Lesson 22: Model Router
 *
 * Intelligent routing of tasks to models based on rules,
 * capabilities, and optimization goals.
 */

import type {
  ModelRouter,
  TaskContext,
  RoutingDecision,
  RoutingRule,
  FallbackConfig,
  CostConfig,
  RouterStats,
  RouterEvent,
  RouterEventListener,
  ModelRegistry,
} from './types.js';
import {
  CapabilityMatcher,
  SimpleModelRegistry,
  calculateComplexityScore,
  getComplexityLevel,
  type ScoringWeights,
  SCORING_PRESETS,
} from './capability-matcher.js';

// =============================================================================
// SMART ROUTER
// =============================================================================

/**
 * Intelligent model router implementation.
 */
export class SmartRouter implements ModelRouter {
  private registry: ModelRegistry;
  private matcher: CapabilityMatcher;
  private rules: RoutingRule[] = [];
  private fallbackConfig?: FallbackConfig;
  private costConfig?: CostConfig;
  private listeners: Set<RouterEventListener> = new Set();

  // Statistics
  private stats: RouterStats = {
    totalRequests: 0,
    routingsByModel: {},
    averageLatencyMs: 0,
    fallbackRate: 0,
    totalCost: 0,
    costByModel: {},
    ruleHitRate: {},
  };

  private latencyHistory: number[] = [];
  private fallbackCount = 0;

  constructor(
    registry: ModelRegistry = new SimpleModelRegistry(),
    weights?: ScoringWeights
  ) {
    this.registry = registry;
    this.matcher = new CapabilityMatcher(registry, weights);
    this.initializeDefaultRules();
  }

  /**
   * Route a task to the best model.
   */
  async route(task: TaskContext): Promise<RoutingDecision> {
    const startTime = Date.now();
    this.stats.totalRequests++;

    // 1. Check rules first (explicit routing)
    const ruleMatch = this.matchRule(task);
    if (ruleMatch) {
      const decision = this.createDecisionFromRule(ruleMatch, task);
      this.recordRouting(decision, Date.now() - startTime);
      return decision;
    }

    // 2. Use capability matching
    const topModels = this.matcher.findTopModels(task, 5);

    if (topModels.length === 0) {
      throw new Error('No suitable models found for task');
    }

    const best = topModels[0];
    const alternatives = this.matcher.scoresToAlternatives(topModels.slice(1));

    // Calculate estimated cost
    const capability = this.registry.getCapability(best.model);
    const estimatedCost = capability
      ? this.estimateCost(task, capability)
      : 0;

    // Check cost constraints
    if (this.costConfig && estimatedCost > (this.costConfig.perRequestBudget || Infinity)) {
      // Try to find cheaper alternative
      const cheaper = topModels.find((m) => {
        const cap = this.registry.getCapability(m.model);
        return cap && this.estimateCost(task, cap) <= (this.costConfig!.perRequestBudget || Infinity);
      });

      if (cheaper) {
        const cheaperCap = this.registry.getCapability(cheaper.model)!;
        const decision: RoutingDecision = {
          model: cheaper.model,
          reason: `Selected for cost (budget: $${this.costConfig.perRequestBudget})`,
          alternatives,
          estimatedCost: this.estimateCost(task, cheaperCap),
          confidence: cheaper.totalScore,
        };
        this.recordRouting(decision, Date.now() - startTime);
        return decision;
      }
    }

    const decision: RoutingDecision = {
      model: best.model,
      reason: best.reasons[0] || 'Best match for task requirements',
      alternatives,
      estimatedCost,
      confidence: best.totalScore,
    };

    this.recordRouting(decision, Date.now() - startTime);
    this.emit({ type: 'route.decision', decision, task });

    return decision;
  }

  /**
   * Add a routing rule.
   */
  addRule(rule: RoutingRule): void {
    this.rules.push(rule);
    this.rules.sort((a, b) => a.priority - b.priority);
    this.stats.ruleHitRate[rule.name] = 0;
  }

  /**
   * Remove a routing rule.
   */
  removeRule(name: string): boolean {
    const index = this.rules.findIndex((r) => r.name === name);
    if (index !== -1) {
      this.rules.splice(index, 1);
      delete this.stats.ruleHitRate[name];
      return true;
    }
    return false;
  }

  /**
   * Configure fallback chain.
   */
  withFallback(config: FallbackConfig): ModelRouter {
    this.fallbackConfig = config;
    return this;
  }

  /**
   * Configure cost optimization.
   */
  withCostOptimization(config: CostConfig): ModelRouter {
    this.costConfig = config;
    if (config.optimizeForCost) {
      this.matcher.usePreset('cost');
    }
    return this;
  }

  /**
   * Get routing statistics.
   */
  getStats(): RouterStats {
    return { ...this.stats };
  }

  /**
   * Subscribe to router events.
   */
  on(listener: RouterEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Get the fallback config.
   */
  getFallbackConfig(): FallbackConfig | undefined {
    return this.fallbackConfig;
  }

  /**
   * Get the matcher for external use.
   */
  getMatcher(): CapabilityMatcher {
    return this.matcher;
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  /**
   * Initialize default routing rules.
   */
  private initializeDefaultRules(): void {
    // Rule: Use fast model for simple tasks
    this.addRule({
      name: 'simple-task-fast-model',
      condition: (task) => {
        const complexity = calculateComplexityScore(task);
        return complexity < 0.3 && task.latencyRequirement === 'fast';
      },
      model: 'claude-3-haiku',
      priority: 10,
      enabled: true,
      description: 'Route simple, time-sensitive tasks to fast model',
    });

    // Rule: Use premium model for complex reasoning
    this.addRule({
      name: 'complex-reasoning-premium',
      condition: (task) => {
        return (
          task.taskType === 'reasoning' &&
          task.qualityRequirement === 'maximum'
        );
      },
      model: 'claude-3-opus',
      priority: 20,
      enabled: true,
      description: 'Route complex reasoning tasks to premium model',
    });

    // Rule: Use vision-capable model for vision tasks
    this.addRule({
      name: 'vision-task',
      condition: (task) => task.requiresVision,
      model: 'claude-3-sonnet',
      priority: 15,
      enabled: true,
      description: 'Route vision tasks to vision-capable model',
    });

    // Rule: Budget-conscious routing
    this.addRule({
      name: 'budget-conscious',
      condition: (task) => {
        return task.maxCost !== undefined && task.maxCost < 0.01;
      },
      model: 'claude-3-haiku',
      priority: 5,
      enabled: true,
      description: 'Route budget-constrained tasks to cheapest model',
    });
  }

  /**
   * Match a task against rules.
   */
  private matchRule(task: TaskContext): RoutingRule | null {
    for (const rule of this.rules) {
      if (rule.enabled && rule.condition(task)) {
        // Verify model exists and can handle task
        const capability = this.registry.getCapability(rule.model);
        if (capability && this.canHandle(capability, task)) {
          this.stats.ruleHitRate[rule.name] =
            (this.stats.ruleHitRate[rule.name] || 0) + 1;
          return rule;
        }
      }
    }
    return null;
  }

  /**
   * Check if a model can handle a task.
   */
  private canHandle(
    capability: { supportsTools: boolean; supportsVision: boolean; maxTokens: number },
    task: TaskContext
  ): boolean {
    if (task.requiresTools && !capability.supportsTools) return false;
    if (task.requiresVision && !capability.supportsVision) return false;
    if (task.estimatedInputTokens > capability.maxTokens) return false;
    return true;
  }

  /**
   * Create routing decision from matched rule.
   */
  private createDecisionFromRule(
    rule: RoutingRule,
    task: TaskContext
  ): RoutingDecision {
    const capability = this.registry.getCapability(rule.model);
    const estimatedCost = capability ? this.estimateCost(task, capability) : 0;

    // Get alternatives for comparison
    const allScores = this.matcher.scoreAllModels(task);
    const alternatives = this.matcher
      .scoresToAlternatives(allScores.filter((s) => s.model !== rule.model))
      .slice(0, 4);

    return {
      model: rule.model,
      reason: rule.description || `Matched rule: ${rule.name}`,
      matchedRule: rule.name,
      alternatives,
      estimatedCost,
      confidence: 0.9, // High confidence for explicit rules
    };
  }

  /**
   * Estimate cost for a task on a model.
   */
  private estimateCost(
    task: TaskContext,
    capability: { costPer1kInput: number; costPer1kOutput: number }
  ): number {
    const outputMultiplier = { small: 100, medium: 500, large: 2000 };
    const outputTokens = outputMultiplier[task.expectedOutputSize];

    return (
      (task.estimatedInputTokens / 1000) * capability.costPer1kInput +
      (outputTokens / 1000) * capability.costPer1kOutput
    );
  }

  /**
   * Record routing for statistics.
   */
  private recordRouting(decision: RoutingDecision, latencyMs: number): void {
    // Update model counts
    this.stats.routingsByModel[decision.model] =
      (this.stats.routingsByModel[decision.model] || 0) + 1;

    // Update cost tracking
    this.stats.totalCost += decision.estimatedCost;
    this.stats.costByModel[decision.model] =
      (this.stats.costByModel[decision.model] || 0) + decision.estimatedCost;

    // Update latency average
    this.latencyHistory.push(latencyMs);
    if (this.latencyHistory.length > 100) {
      this.latencyHistory.shift();
    }
    this.stats.averageLatencyMs =
      this.latencyHistory.reduce((a, b) => a + b, 0) / this.latencyHistory.length;

    // Update fallback rate
    this.stats.fallbackRate = this.fallbackCount / this.stats.totalRequests;
  }

  /**
   * Record a fallback event.
   */
  recordFallback(): void {
    this.fallbackCount++;
    this.stats.fallbackRate = this.fallbackCount / this.stats.totalRequests;
  }

  /**
   * Emit an event.
   */
  private emit(event: RouterEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Router listener error:', err);
      }
    }
  }
}

// =============================================================================
// RULE BUILDER
// =============================================================================

/**
 * Fluent builder for routing rules.
 */
export class RuleBuilder {
  private rule: Partial<RoutingRule> = {
    enabled: true,
    priority: 50,
  };

  /**
   * Set rule name.
   */
  name(name: string): RuleBuilder {
    this.rule.name = name;
    return this;
  }

  /**
   * Set condition function.
   */
  when(condition: (task: TaskContext) => boolean): RuleBuilder {
    this.rule.condition = condition;
    return this;
  }

  /**
   * Set target model.
   */
  routeTo(model: string): RuleBuilder {
    this.rule.model = model;
    return this;
  }

  /**
   * Set priority.
   */
  withPriority(priority: number): RuleBuilder {
    this.rule.priority = priority;
    return this;
  }

  /**
   * Set description.
   */
  describe(description: string): RuleBuilder {
    this.rule.description = description;
    return this;
  }

  /**
   * Enable or disable.
   */
  enabled(enabled: boolean): RuleBuilder {
    this.rule.enabled = enabled;
    return this;
  }

  /**
   * Build the rule.
   */
  build(): RoutingRule {
    if (!this.rule.name || !this.rule.condition || !this.rule.model) {
      throw new Error('Rule requires name, condition, and model');
    }

    return this.rule as RoutingRule;
  }
}

// =============================================================================
// COMPLEXITY-BASED ROUTER
// =============================================================================

/**
 * Simple router that routes based on complexity.
 */
export class ComplexityRouter {
  private modelMapping: Record<'simple' | 'moderate' | 'complex', string>;

  constructor(
    modelMapping: Record<'simple' | 'moderate' | 'complex', string> = {
      simple: 'claude-3-haiku',
      moderate: 'claude-3-sonnet',
      complex: 'claude-3-opus',
    }
  ) {
    this.modelMapping = modelMapping;
  }

  /**
   * Route based on task complexity.
   */
  route(task: TaskContext): string {
    const score = calculateComplexityScore(task);
    const level = getComplexityLevel(score);
    return this.modelMapping[level];
  }

  /**
   * Get routing explanation.
   */
  explain(task: TaskContext): { model: string; complexity: string; score: number } {
    const score = calculateComplexityScore(task);
    const level = getComplexityLevel(score);
    return {
      model: this.modelMapping[level],
      complexity: level,
      score,
    };
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createRouter(
  registry?: ModelRegistry,
  weights?: ScoringWeights
): SmartRouter {
  return new SmartRouter(registry, weights);
}

export function createRuleBuilder(): RuleBuilder {
  return new RuleBuilder();
}

export function createComplexityRouter(
  mapping?: Record<'simple' | 'moderate' | 'complex', string>
): ComplexityRouter {
  return new ComplexityRouter(mapping);
}
