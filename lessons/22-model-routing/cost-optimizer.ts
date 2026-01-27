/**
 * Lesson 22: Cost Optimizer
 *
 * Cost-aware model selection and budget management.
 * Tracks spending and optimizes for cost/quality tradeoffs.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The cost optimization strategy can be customized.
 * Consider implementing:
 * - Time-of-day pricing adjustments
 * - Volume discounts
 * - Model switching based on remaining budget
 */

import type {
  CostConfig,
  CostState,
  CostEstimate,
  ModelCapability,
  TaskContext,
  RouterEvent,
  RouterEventListener,
  ModelRegistry,
} from './types.js';
import { SimpleModelRegistry } from './capability-matcher.js';

// =============================================================================
// COST TRACKER
// =============================================================================

/**
 * Tracks costs and enforces budgets.
 */
export class CostTracker {
  private state: CostState;
  private config: CostConfig;
  private listeners: Set<RouterEventListener> = new Set();

  constructor(config: CostConfig) {
    this.config = config;
    this.state = {
      dailySpend: 0,
      monthlySpend: 0,
      requestsToday: 0,
      lastReset: Date.now(),
      costByModel: {},
    };
  }

  /**
   * Record a cost.
   */
  recordCost(model: string, cost: number): void {
    this.maybeReset();

    this.state.dailySpend += cost;
    this.state.monthlySpend += cost;
    this.state.requestsToday++;
    this.state.costByModel[model] = (this.state.costByModel[model] || 0) + cost;

    // Check alert threshold
    const budgetPercent = this.state.dailySpend / this.config.dailyBudget;
    if (budgetPercent >= this.config.alertThreshold) {
      this.emit({
        type: 'cost.alert',
        current: this.state.dailySpend,
        threshold: this.config.alertThreshold,
        budget: this.config.dailyBudget,
      });
    }
  }

  /**
   * Check if a cost is within budget.
   */
  isWithinBudget(estimatedCost: number): boolean {
    this.maybeReset();

    // Check per-request budget
    if (
      this.config.perRequestBudget !== undefined &&
      estimatedCost > this.config.perRequestBudget
    ) {
      return false;
    }

    // Check daily budget
    if (this.state.dailySpend + estimatedCost > this.config.dailyBudget) {
      return false;
    }

    return true;
  }

  /**
   * Get remaining daily budget.
   */
  getRemainingBudget(): number {
    this.maybeReset();
    return Math.max(0, this.config.dailyBudget - this.state.dailySpend);
  }

  /**
   * Get current state.
   */
  getState(): CostState {
    this.maybeReset();
    return { ...this.state };
  }

  /**
   * Get config.
   */
  getConfig(): CostConfig {
    return { ...this.config };
  }

  /**
   * Update config.
   */
  updateConfig(updates: Partial<CostConfig>): void {
    this.config = { ...this.config, ...updates };
  }

  /**
   * Reset daily counters if needed.
   */
  private maybeReset(): void {
    const now = Date.now();
    const lastResetDate = new Date(this.state.lastReset);
    const today = new Date(now);

    // Reset if day changed
    if (
      lastResetDate.getDate() !== today.getDate() ||
      lastResetDate.getMonth() !== today.getMonth() ||
      lastResetDate.getFullYear() !== today.getFullYear()
    ) {
      this.state.dailySpend = 0;
      this.state.requestsToday = 0;
      this.state.lastReset = now;

      // Reset monthly if month changed
      if (lastResetDate.getMonth() !== today.getMonth()) {
        this.state.monthlySpend = 0;
        this.state.costByModel = {};
      }
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: RouterEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: RouterEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Cost tracker listener error:', err);
      }
    }
  }
}

// =============================================================================
// COST ESTIMATOR
// =============================================================================

/**
 * Estimates costs for tasks on different models.
 */
export class CostEstimator {
  private registry: ModelRegistry;

  constructor(registry: ModelRegistry = new SimpleModelRegistry()) {
    this.registry = registry;
  }

  /**
   * Estimate cost for a task on a specific model.
   */
  estimate(task: TaskContext, model: string): CostEstimate | null {
    const capability = this.registry.getCapability(model);
    if (!capability) return null;

    const outputTokens = this.estimateOutputTokens(task);
    const inputCost = (task.estimatedInputTokens / 1000) * capability.costPer1kInput;
    const outputCost = (outputTokens / 1000) * capability.costPer1kOutput;

    return {
      model,
      inputCost,
      outputCost,
      totalCost: inputCost + outputCost,
      isWithinBudget: true, // Caller should check with tracker
      budgetRemaining: 0, // Caller should fill in
    };
  }

  /**
   * Estimate costs for all available models.
   */
  estimateAll(task: TaskContext): CostEstimate[] {
    const models = this.registry.listModels();
    const estimates: CostEstimate[] = [];

    for (const model of models) {
      const estimate = this.estimate(task, model.model);
      if (estimate) {
        estimates.push(estimate);
      }
    }

    return estimates.sort((a, b) => a.totalCost - b.totalCost);
  }

  /**
   * Find cheapest model that meets requirements.
   */
  findCheapest(
    task: TaskContext,
    filter?: (capability: ModelCapability) => boolean
  ): CostEstimate | null {
    let models = this.registry.listModels();

    // Apply filter if provided
    if (filter) {
      models = models.filter(filter);
    }

    // Filter by task requirements
    models = models.filter((m) => this.meetsRequirements(m, task));

    if (models.length === 0) return null;

    // Sort by cost and return cheapest
    const estimates = models
      .map((m) => this.estimate(task, m.model))
      .filter((e): e is CostEstimate => e !== null);

    if (estimates.length === 0) return null;

    return estimates.sort((a, b) => a.totalCost - b.totalCost)[0];
  }

  /**
   * Check if model meets task requirements.
   */
  private meetsRequirements(
    model: ModelCapability,
    task: TaskContext
  ): boolean {
    if (task.requiresTools && !model.supportsTools) return false;
    if (task.requiresVision && !model.supportsVision) return false;
    if (task.estimatedInputTokens > model.maxTokens) return false;
    return true;
  }

  /**
   * Estimate output tokens based on task.
   */
  private estimateOutputTokens(task: TaskContext): number {
    const multipliers: Record<string, number> = {
      small: 100,
      medium: 500,
      large: 2000,
    };
    return multipliers[task.expectedOutputSize];
  }
}

// =============================================================================
// COST OPTIMIZER
// =============================================================================

/**
 * Optimization strategy.
 */
export type OptimizationStrategy =
  | 'minimize_cost'
  | 'maximize_quality'
  | 'balanced'
  | 'budget_aware';

/**
 * Optimizes model selection based on cost and quality.
 */
export class CostOptimizer {
  private tracker: CostTracker;
  private estimator: CostEstimator;
  private registry: ModelRegistry;
  private strategy: OptimizationStrategy;

  constructor(
    config: CostConfig,
    registry: ModelRegistry = new SimpleModelRegistry(),
    strategy: OptimizationStrategy = 'balanced'
  ) {
    this.tracker = new CostTracker(config);
    this.estimator = new CostEstimator(registry);
    this.registry = registry;
    this.strategy = strategy;
  }

  /**
   * Select optimal model for a task.
   */
  selectModel(task: TaskContext): { model: string; estimate: CostEstimate } | null {
    const models = this.registry.listModels().filter(
      (m) => this.canUseModel(m, task)
    );

    if (models.length === 0) return null;

    // Score each model
    const scored = models.map((m) => ({
      model: m,
      estimate: this.estimator.estimate(task, m.model)!,
      score: this.scoreModel(m, task),
    }));

    // Sort by score
    scored.sort((a, b) => b.score - a.score);

    const best = scored[0];
    return {
      model: best.model.model,
      estimate: best.estimate,
    };
  }

  /**
   * Score a model based on optimization strategy.
   */
  private scoreModel(model: ModelCapability, task: TaskContext): number {
    const estimate = this.estimator.estimate(task, model.model);
    if (!estimate) return 0;

    const costScore = 1 - Math.min(1, estimate.totalCost); // Lower cost = higher score
    const qualityScore = model.qualityScore / 100;
    const remainingBudget = this.tracker.getRemainingBudget();

    switch (this.strategy) {
      case 'minimize_cost':
        return costScore * 0.8 + qualityScore * 0.2;

      case 'maximize_quality':
        return qualityScore * 0.8 + costScore * 0.2;

      case 'balanced':
        return costScore * 0.5 + qualityScore * 0.5;

      case 'budget_aware':
        // Prefer cheaper models as budget runs low
        const budgetRatio = remainingBudget / this.tracker.getConfig().dailyBudget;
        if (budgetRatio < 0.2) {
          // Very low budget - prioritize cost heavily
          return costScore * 0.9 + qualityScore * 0.1;
        } else if (budgetRatio < 0.5) {
          // Medium budget - balance more toward cost
          return costScore * 0.7 + qualityScore * 0.3;
        } else {
          // Plenty of budget - balanced
          return costScore * 0.5 + qualityScore * 0.5;
        }

      default:
        return costScore * 0.5 + qualityScore * 0.5;
    }
  }

  /**
   * Check if a model can be used for a task.
   */
  private canUseModel(model: ModelCapability, task: TaskContext): boolean {
    // Check requirements
    if (task.requiresTools && !model.supportsTools) return false;
    if (task.requiresVision && !model.supportsVision) return false;
    if (task.estimatedInputTokens > model.maxTokens) return false;

    // Check minimum quality
    const minQuality = this.tracker.getConfig().minimumQualityScore;
    if (model.qualityScore < minQuality) return false;

    // Check budget
    const estimate = this.estimator.estimate(task, model.model);
    if (!estimate) return false;
    if (!this.tracker.isWithinBudget(estimate.totalCost)) return false;

    return true;
  }

  /**
   * Record that a model was used.
   */
  recordUsage(model: string, actualCost: number): void {
    this.tracker.recordCost(model, actualCost);
  }

  /**
   * Get cost tracker.
   */
  getTracker(): CostTracker {
    return this.tracker;
  }

  /**
   * Get estimator.
   */
  getEstimator(): CostEstimator {
    return this.estimator;
  }

  /**
   * Set optimization strategy.
   */
  setStrategy(strategy: OptimizationStrategy): void {
    this.strategy = strategy;
  }

  /**
   * Get current strategy.
   */
  getStrategy(): OptimizationStrategy {
    return this.strategy;
  }
}

// =============================================================================
// COST REPORT GENERATOR
// =============================================================================

/**
 * Generates cost reports.
 */
export class CostReportGenerator {
  /**
   * Generate a daily report.
   */
  static dailyReport(tracker: CostTracker): string {
    const state = tracker.getState();
    const config = tracker.getConfig();
    const remaining = tracker.getRemainingBudget();
    const usagePercent = ((state.dailySpend / config.dailyBudget) * 100).toFixed(1);

    const lines: string[] = [
      '═══════════════════════════════════════',
      '         DAILY COST REPORT',
      '═══════════════════════════════════════',
      '',
      `  Daily Budget:     $${config.dailyBudget.toFixed(2)}`,
      `  Daily Spend:      $${state.dailySpend.toFixed(4)}`,
      `  Remaining:        $${remaining.toFixed(4)}`,
      `  Usage:            ${usagePercent}%`,
      `  Requests Today:   ${state.requestsToday}`,
      '',
      '  Cost by Model:',
    ];

    for (const [model, cost] of Object.entries(state.costByModel)) {
      lines.push(`    ${model}: $${cost.toFixed(4)}`);
    }

    lines.push('');
    lines.push('═══════════════════════════════════════');

    return lines.join('\n');
  }

  /**
   * Generate a model comparison report.
   */
  static modelComparisonReport(
    estimator: CostEstimator,
    task: TaskContext
  ): string {
    const estimates = estimator.estimateAll(task);

    const lines: string[] = [
      '═══════════════════════════════════════',
      '      MODEL COST COMPARISON',
      '═══════════════════════════════════════',
      '',
      `  Task: ${task.task}`,
      `  Input tokens: ~${task.estimatedInputTokens}`,
      `  Output size: ${task.expectedOutputSize}`,
      '',
      '  Model               Input     Output    Total',
      '  ─────────────────────────────────────────────',
    ];

    for (const estimate of estimates) {
      const model = estimate.model.padEnd(18);
      const input = `$${estimate.inputCost.toFixed(4)}`.padStart(8);
      const output = `$${estimate.outputCost.toFixed(4)}`.padStart(8);
      const total = `$${estimate.totalCost.toFixed(4)}`.padStart(8);
      lines.push(`  ${model} ${input}   ${output}   ${total}`);
    }

    lines.push('');
    lines.push('═══════════════════════════════════════');

    return lines.join('\n');
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createCostTracker(config: CostConfig): CostTracker {
  return new CostTracker(config);
}

export function createCostEstimator(registry?: ModelRegistry): CostEstimator {
  return new CostEstimator(registry);
}

export function createCostOptimizer(
  config: CostConfig,
  registry?: ModelRegistry,
  strategy?: OptimizationStrategy
): CostOptimizer {
  return new CostOptimizer(config, registry, strategy);
}
