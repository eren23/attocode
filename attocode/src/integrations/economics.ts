/**
 * Lesson 25: Execution Economics System
 *
 * Replaces hard-coded iteration limits with intelligent budget management:
 * - Token budgets (primary constraint)
 * - Cost budgets (maps to real API costs)
 * - Time budgets (wall-clock limits)
 * - Progress detection (stuck vs productive)
 * - Adaptive limits with extension requests
 */

import { stableStringify } from './context-engineering.js';
import { getModelPricing, calculateCost } from './openrouter-pricing.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Execution budget configuration.
 */
export interface ExecutionBudget {
  // Hard limits (will force stop)
  maxTokens: number;           // e.g., 200000
  maxCost: number;             // e.g., 0.50 USD
  maxDuration: number;         // e.g., 300000ms (5 min)

  // Soft limits (will warn/prompt for extension)
  softTokenLimit: number;      // e.g., 150000
  softCostLimit: number;       // e.g., 0.30 USD
  softDurationLimit: number;   // e.g., 180000ms (3 min)

  // Iteration is now soft guidance (not hard limit)
  targetIterations: number;    // e.g., 20 (advisory)
  maxIterations: number;       // e.g., 100 (absolute safety cap)
}

/**
 * Current execution usage.
 */
export interface ExecutionUsage {
  tokens: number;
  inputTokens: number;
  outputTokens: number;
  cost: number;
  duration: number;
  iterations: number;
  toolCalls: number;
  llmCalls: number;
}

/**
 * Progress tracking state.
 */
export interface ProgressState {
  filesRead: Set<string>;
  filesModified: Set<string>;
  commandsRun: string[];
  recentToolCalls: Array<{ tool: string; args: string }>;
  lastMeaningfulProgress: number;
  stuckCount: number;
}

/**
 * Budget check result.
 */
export interface BudgetCheckResult {
  canContinue: boolean;
  reason?: string;
  budgetType?: 'tokens' | 'cost' | 'duration' | 'iterations';
  isHardLimit: boolean;
  isSoftLimit: boolean;
  percentUsed: number;
  suggestedAction?: 'continue' | 'request_extension' | 'stop' | 'warn';
}

/**
 * Extension request.
 */
export interface ExtensionRequest {
  currentUsage: ExecutionUsage;
  budget: ExecutionBudget;
  reason: string;
  suggestedExtension: Partial<ExecutionBudget>;
}

/**
 * Economics events.
 */
export type EconomicsEvent =
  | { type: 'budget.warning'; budgetType: string; percentUsed: number; remaining: number }
  | { type: 'budget.exceeded'; budgetType: string; limit: number; actual: number }
  | { type: 'progress.stuck'; stuckCount: number; lastProgress: number }
  | { type: 'progress.made'; filesRead: number; filesModified: number }
  | { type: 'extension.requested'; request: ExtensionRequest }
  | { type: 'extension.granted'; extension: Partial<ExecutionBudget> }
  | { type: 'extension.denied'; reason: string };

export type EconomicsEventListener = (event: EconomicsEvent) => void;

// =============================================================================
// ECONOMICS MANAGER
// =============================================================================

/**
 * ExecutionEconomicsManager handles budget tracking and progress detection.
 */
export class ExecutionEconomicsManager {
  private budget: ExecutionBudget;
  private usage: ExecutionUsage;
  private progress: ProgressState;
  private startTime: number;
  private listeners: EconomicsEventListener[] = [];
  private extensionHandler?: (request: ExtensionRequest) => Promise<Partial<ExecutionBudget> | null>;

  constructor(budget?: Partial<ExecutionBudget>) {
    this.budget = {
      // Hard limits
      maxTokens: budget?.maxTokens ?? 200000,
      maxCost: budget?.maxCost ?? 1.00,
      maxDuration: budget?.maxDuration ?? 300000, // 5 minutes

      // Soft limits (80% of hard limits)
      softTokenLimit: budget?.softTokenLimit ?? 150000,
      softCostLimit: budget?.softCostLimit ?? 0.75,
      softDurationLimit: budget?.softDurationLimit ?? 240000, // 4 minutes

      // Iteration guidance
      targetIterations: budget?.targetIterations ?? 20,
      maxIterations: budget?.maxIterations ?? 100,
    };

    this.usage = {
      tokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      cost: 0,
      duration: 0,
      iterations: 0,
      toolCalls: 0,
      llmCalls: 0,
    };

    this.progress = {
      filesRead: new Set(),
      filesModified: new Set(),
      commandsRun: [],
      recentToolCalls: [],
      lastMeaningfulProgress: Date.now(),
      stuckCount: 0,
    };

    this.startTime = Date.now();
  }

  /**
   * Set the extension request handler.
   */
  setExtensionHandler(
    handler: (request: ExtensionRequest) => Promise<Partial<ExecutionBudget> | null>
  ): void {
    this.extensionHandler = handler;
  }

  /**
   * Record token usage from an LLM call.
   * @param inputTokens - Number of input tokens
   * @param outputTokens - Number of output tokens
   * @param model - Model name (for fallback pricing calculation)
   * @param actualCost - Actual cost from provider (e.g., OpenRouter returns this directly)
   */
  recordLLMUsage(inputTokens: number, outputTokens: number, model?: string, actualCost?: number): void {
    this.usage.inputTokens += inputTokens;
    this.usage.outputTokens += outputTokens;
    this.usage.tokens += inputTokens + outputTokens;
    this.usage.llmCalls++;

    // Use actual cost from provider if available, otherwise calculate
    if (actualCost !== undefined && actualCost !== null) {
      this.usage.cost += actualCost;
    } else {
      // Fallback: Calculate cost using model pricing (less accurate for unknown models)
      this.usage.cost += calculateCost(model || '', inputTokens, outputTokens);
    }

    // Update duration
    this.usage.duration = Date.now() - this.startTime;
  }

  /**
   * Record a tool call for progress tracking.
   */
  recordToolCall(toolName: string, args: Record<string, unknown>, result?: unknown): void {
    this.usage.toolCalls++;
    this.usage.iterations++;

    // Track for loop detection (stableStringify ensures consistent ordering for comparison)
    const argsStr = stableStringify(args);
    this.progress.recentToolCalls.push({ tool: toolName, args: argsStr });

    // Keep only last 10 for loop detection
    if (this.progress.recentToolCalls.length > 10) {
      this.progress.recentToolCalls.shift();
    }

    // Track file operations
    if (toolName === 'read_file' && args.path) {
      this.progress.filesRead.add(String(args.path));
      // Only count reads as progress during initial exploration (first 5 iterations)
      // After that, we need actual edits to reset the stuck counter
      if (this.usage.iterations <= 5) {
        this.progress.lastMeaningfulProgress = Date.now();
        this.progress.stuckCount = 0;
      }
    }

    if (['write_file', 'edit_file'].includes(toolName) && args.path) {
      this.progress.filesModified.add(String(args.path));
      this.progress.lastMeaningfulProgress = Date.now();
      this.progress.stuckCount = 0;
    }

    if (toolName === 'bash' && args.command) {
      this.progress.commandsRun.push(String(args.command));
      this.progress.lastMeaningfulProgress = Date.now();
      this.progress.stuckCount = 0;
    }

    // Check for stuck state
    if (this.isStuck()) {
      this.progress.stuckCount++;
      this.emit({ type: 'progress.stuck', stuckCount: this.progress.stuckCount, lastProgress: this.progress.lastMeaningfulProgress });
    } else {
      this.emit({
        type: 'progress.made',
        filesRead: this.progress.filesRead.size,
        filesModified: this.progress.filesModified.size,
      });
    }
  }

  /**
   * Check if execution can continue.
   */
  checkBudget(): BudgetCheckResult {
    this.usage.duration = Date.now() - this.startTime;

    // Check hard limits first
    if (this.usage.tokens >= this.budget.maxTokens) {
      this.emit({ type: 'budget.exceeded', budgetType: 'tokens', limit: this.budget.maxTokens, actual: this.usage.tokens });
      return {
        canContinue: false,
        reason: `Token budget exceeded (${this.usage.tokens.toLocaleString()} / ${this.budget.maxTokens.toLocaleString()})`,
        budgetType: 'tokens',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: (this.usage.tokens / this.budget.maxTokens) * 100,
        suggestedAction: 'stop',
      };
    }

    if (this.usage.cost >= this.budget.maxCost) {
      this.emit({ type: 'budget.exceeded', budgetType: 'cost', limit: this.budget.maxCost, actual: this.usage.cost });
      return {
        canContinue: false,
        reason: `Cost budget exceeded ($${this.usage.cost.toFixed(2)} / $${this.budget.maxCost.toFixed(2)})`,
        budgetType: 'cost',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: (this.usage.cost / this.budget.maxCost) * 100,
        suggestedAction: 'stop',
      };
    }

    if (this.usage.duration >= this.budget.maxDuration) {
      this.emit({ type: 'budget.exceeded', budgetType: 'duration', limit: this.budget.maxDuration, actual: this.usage.duration });
      return {
        canContinue: false,
        reason: `Duration limit exceeded (${Math.round(this.usage.duration / 1000)}s / ${Math.round(this.budget.maxDuration / 1000)}s)`,
        budgetType: 'duration',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: (this.usage.duration / this.budget.maxDuration) * 100,
        suggestedAction: 'stop',
      };
    }

    if (this.usage.iterations >= this.budget.maxIterations) {
      return {
        canContinue: false,
        reason: `Maximum iterations reached (${this.usage.iterations} / ${this.budget.maxIterations})`,
        budgetType: 'iterations',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: 100,
        suggestedAction: 'stop',
      };
    }

    // Check soft limits (warnings)
    if (this.usage.tokens >= this.budget.softTokenLimit) {
      const remaining = this.budget.maxTokens - this.usage.tokens;
      this.emit({ type: 'budget.warning', budgetType: 'tokens', percentUsed: (this.usage.tokens / this.budget.maxTokens) * 100, remaining });
      return {
        canContinue: true,
        reason: `Token budget at ${Math.round((this.usage.tokens / this.budget.maxTokens) * 100)}%`,
        budgetType: 'tokens',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.tokens / this.budget.maxTokens) * 100,
        suggestedAction: 'request_extension',
      };
    }

    if (this.usage.cost >= this.budget.softCostLimit) {
      const remaining = this.budget.maxCost - this.usage.cost;
      this.emit({ type: 'budget.warning', budgetType: 'cost', percentUsed: (this.usage.cost / this.budget.maxCost) * 100, remaining });
      return {
        canContinue: true,
        reason: `Cost budget at ${Math.round((this.usage.cost / this.budget.maxCost) * 100)}%`,
        budgetType: 'cost',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.cost / this.budget.maxCost) * 100,
        suggestedAction: 'warn',
      };
    }

    // Check if stuck
    if (this.progress.stuckCount >= 3) {
      return {
        canContinue: true,
        reason: `Agent appears stuck (${this.progress.stuckCount} iterations without progress)`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'request_extension',
      };
    }

    // All good
    return {
      canContinue: true,
      isHardLimit: false,
      isSoftLimit: false,
      percentUsed: Math.max(
        (this.usage.tokens / this.budget.maxTokens) * 100,
        (this.usage.cost / this.budget.maxCost) * 100,
        (this.usage.duration / this.budget.maxDuration) * 100
      ),
      suggestedAction: 'continue',
    };
  }

  /**
   * Request a budget extension.
   */
  async requestExtension(reason: string): Promise<boolean> {
    if (!this.extensionHandler) {
      return false;
    }

    const request: ExtensionRequest = {
      currentUsage: { ...this.usage },
      budget: { ...this.budget },
      reason,
      suggestedExtension: {
        maxTokens: Math.round(this.budget.maxTokens * 1.5),
        maxCost: this.budget.maxCost * 1.5,
        maxDuration: this.budget.maxDuration * 1.5,
        maxIterations: Math.round(this.budget.maxIterations * 1.5),
      },
    };

    this.emit({ type: 'extension.requested', request });

    try {
      const extension = await this.extensionHandler(request);
      if (extension) {
        this.extendBudget(extension);
        this.emit({ type: 'extension.granted', extension });
        return true;
      } else {
        this.emit({ type: 'extension.denied', reason: 'User declined' });
        return false;
      }
    } catch (err) {
      this.emit({ type: 'extension.denied', reason: String(err) });
      return false;
    }
  }

  /**
   * Extend the budget.
   */
  extendBudget(extension: Partial<ExecutionBudget>): void {
    if (extension.maxTokens) this.budget.maxTokens = extension.maxTokens;
    if (extension.maxCost) this.budget.maxCost = extension.maxCost;
    if (extension.maxDuration) this.budget.maxDuration = extension.maxDuration;
    if (extension.maxIterations) this.budget.maxIterations = extension.maxIterations;
    if (extension.softTokenLimit) this.budget.softTokenLimit = extension.softTokenLimit;
    if (extension.softCostLimit) this.budget.softCostLimit = extension.softCostLimit;
    if (extension.softDurationLimit) this.budget.softDurationLimit = extension.softDurationLimit;
    if (extension.targetIterations) this.budget.targetIterations = extension.targetIterations;
  }

  /**
   * Get current usage.
   */
  getUsage(): ExecutionUsage {
    this.usage.duration = Date.now() - this.startTime;
    return { ...this.usage };
  }

  /**
   * Get current budget.
   */
  getBudget(): ExecutionBudget {
    return { ...this.budget };
  }

  /**
   * Get progress state.
   */
  getProgress(): {
    filesRead: number;
    filesModified: number;
    commandsRun: number;
    isStuck: boolean;
    stuckCount: number;
  } {
    return {
      filesRead: this.progress.filesRead.size,
      filesModified: this.progress.filesModified.size,
      commandsRun: this.progress.commandsRun.length,
      isStuck: this.isStuck(),
      stuckCount: this.progress.stuckCount,
    };
  }

  /**
   * Subscribe to events.
   */
  on(listener: EconomicsEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Reset usage (start new task).
   */
  reset(): void {
    this.usage = {
      tokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      cost: 0,
      duration: 0,
      iterations: 0,
      toolCalls: 0,
      llmCalls: 0,
    };
    this.progress = {
      filesRead: new Set(),
      filesModified: new Set(),
      commandsRun: [],
      recentToolCalls: [],
      lastMeaningfulProgress: Date.now(),
      stuckCount: 0,
    };
    this.startTime = Date.now();
  }

  // -------------------------------------------------------------------------
  // PRIVATE METHODS
  // -------------------------------------------------------------------------

  private emit(event: EconomicsEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  private isStuck(): boolean {
    // Check for repeated tool calls
    if (this.progress.recentToolCalls.length >= 3) {
      const last3 = this.progress.recentToolCalls.slice(-3);
      const unique = new Set(last3.map(tc => `${tc.tool}:${tc.args}`));
      if (unique.size === 1) {
        return true; // Same call 3 times in a row
      }
    }

    // Check for no progress in time
    const timeSinceProgress = Date.now() - this.progress.lastMeaningfulProgress;
    if (timeSinceProgress > 60000 && this.usage.iterations > 5) {
      return true; // No progress for 1 minute with 5+ iterations
    }

    return false;
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create an economics manager with optional budget configuration.
 */
export function createEconomicsManager(
  budget?: Partial<ExecutionBudget>
): ExecutionEconomicsManager {
  return new ExecutionEconomicsManager(budget);
}

// =============================================================================
// PRESET BUDGETS
// =============================================================================

/**
 * Quick task budget - for simple queries.
 */
export const QUICK_BUDGET: Partial<ExecutionBudget> = {
  maxTokens: 50000,
  maxCost: 0.10,
  maxDuration: 60000, // 1 minute
  targetIterations: 5,
  maxIterations: 20,
};

/**
 * Standard task budget - for typical development tasks.
 */
export const STANDARD_BUDGET: Partial<ExecutionBudget> = {
  maxTokens: 200000,
  maxCost: 0.50,
  maxDuration: 300000, // 5 minutes
  targetIterations: 20,
  maxIterations: 50,
};

/**
 * Large task budget - for complex multi-step tasks.
 */
export const LARGE_BUDGET: Partial<ExecutionBudget> = {
  maxTokens: 500000,
  maxCost: 2.00,
  maxDuration: 900000, // 15 minutes
  targetIterations: 50,
  maxIterations: 200,
};

/**
 * Unlimited budget - no limits (use with caution).
 */
export const UNLIMITED_BUDGET: Partial<ExecutionBudget> = {
  maxTokens: Infinity,
  maxCost: Infinity,
  maxDuration: Infinity,
  targetIterations: Infinity,
  maxIterations: Infinity,
};
