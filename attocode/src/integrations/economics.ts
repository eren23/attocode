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
  recentToolCalls: Array<{ tool: string; args: string; timestamp: number }>;
  lastMeaningfulProgress: number;
  stuckCount: number;
}

/**
 * Doom loop detection state (OpenCode pattern).
 * Detects when agent is stuck calling the same tool repeatedly.
 */
export interface LoopDetectionState {
  /** Whether a doom loop was detected */
  doomLoopDetected: boolean;
  /** The tool that's being called repeatedly */
  lastTool: string | null;
  /** How many consecutive times the same call was made */
  consecutiveCount: number;
  /** Threshold for doom loop detection (default: 3) */
  threshold: number;
  /** Timestamp of last doom loop warning */
  lastWarningTime: number;
}

/**
 * Exploration phase state - tracks whether agent is gathering info vs taking action.
 */
export interface PhaseState {
  /** Current phase of execution */
  phase: 'exploring' | 'planning' | 'acting' | 'verifying';
  /** Iteration when exploration started */
  explorationStartIteration: number;
  /** Unique files read during exploration */
  uniqueFilesRead: Set<string>;
  /** Unique search queries performed */
  uniqueSearches: Set<string>;
  /** Files that have been modified */
  filesModified: Set<string>;
  /** Number of test runs */
  testsRun: number;
  /** Whether phase transition is recommended */
  shouldTransition: boolean;
  /** Iterations spent in current phase */
  iterationsInPhase: number;
  /** Files read in recent iterations (for diminishing returns) */
  recentNewFiles: number;
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
  /** Force text-only response (no tool calls allowed) */
  forceTextOnly?: boolean;
  /** Prompt to inject for contextual guidance */
  injectedPrompt?: string;
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
  | { type: 'extension.denied'; reason: string }
  | { type: 'doom_loop.detected'; tool: string; consecutiveCount: number }
  | { type: 'phase.transition'; from: string; to: string; reason: string }
  | { type: 'exploration.saturation'; filesRead: number; iterations: number };

export type EconomicsEventListener = (event: EconomicsEvent) => void;

// =============================================================================
// ECONOMICS MANAGER
// =============================================================================

/**
 * Max steps prompt - injected when iteration limit reached.
 * Forces a summary response instead of more tool calls.
 */
const MAX_STEPS_PROMPT = `[System] Maximum steps reached. You must now:
1. Summarize what you've accomplished
2. List any remaining work
3. Explain any blockers encountered

Do NOT call any more tools. Respond with text only.`;

/**
 * Doom loop prompt - injected when same tool called repeatedly.
 */
const DOOM_LOOP_PROMPT = (tool: string, count: number) =>
`[System] You've called ${tool} with the same arguments ${count} times. This indicates a stuck state. Either:
1. Try a DIFFERENT approach or tool
2. If blocked, explain what's preventing progress
3. If the task is complete, say so explicitly`;

/**
 * Exploration saturation prompt - gentle nudge to start making edits.
 */
const EXPLORATION_NUDGE_PROMPT = (filesRead: number, iterations: number) =>
`[System] You've read ${filesRead} files across ${iterations} iterations. If you understand the issue:
- Make the code changes now
- Run tests to verify
If you're still gathering context, briefly explain what you're looking for.`;

/**
 * ExecutionEconomicsManager handles budget tracking and progress detection.
 */
export class ExecutionEconomicsManager {
  private budget: ExecutionBudget;
  private usage: ExecutionUsage;
  private progress: ProgressState;
  private loopState: LoopDetectionState;
  private phaseState: PhaseState;
  private startTime: number;
  private pausedDuration = 0;
  private pauseStart: number | null = null;
  private listeners: EconomicsEventListener[] = [];
  private extensionHandler?: (request: ExtensionRequest) => Promise<Partial<ExecutionBudget> | null>;

  constructor(budget?: Partial<ExecutionBudget>) {
    this.budget = {
      // Hard limits
      maxTokens: budget?.maxTokens ?? 200000,
      maxCost: budget?.maxCost ?? 1.00,
      maxDuration: budget?.maxDuration ?? 900000, // 15 minutes (up from 5min to support subagent tasks)

      // Soft limits (80% of hard limits)
      softTokenLimit: budget?.softTokenLimit ?? 150000,
      softCostLimit: budget?.softCostLimit ?? 0.75,
      softDurationLimit: budget?.softDurationLimit ?? 720000, // 12 minutes

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

    // Initialize doom loop detection state
    this.loopState = {
      doomLoopDetected: false,
      lastTool: null,
      consecutiveCount: 0,
      threshold: 3,
      lastWarningTime: 0,
    };

    // Initialize phase tracking state
    this.phaseState = {
      phase: 'exploring',
      explorationStartIteration: 0,
      uniqueFilesRead: new Set(),
      uniqueSearches: new Set(),
      filesModified: new Set(),
      testsRun: 0,
      shouldTransition: false,
      iterationsInPhase: 0,
      recentNewFiles: 0,
    };

    this.startTime = Date.now();
  }

  /**
   * Pause duration tracking (e.g., while subagents are running).
   * Prevents the parent agent's wall-clock timer from advancing
   * during subagent execution.
   */
  pauseDuration(): void {
    if (this.pauseStart === null) {
      this.pauseStart = Date.now();
    }
  }

  /**
   * Resume duration tracking after subagent completes.
   */
  resumeDuration(): void {
    if (this.pauseStart !== null) {
      this.pausedDuration += Date.now() - this.pauseStart;
      this.pauseStart = null;
    }
  }

  /**
   * Get the effective duration accounting for paused time.
   */
  private getEffectiveDuration(): number {
    const currentPaused = this.pauseStart !== null ? Date.now() - this.pauseStart : 0;
    return Date.now() - this.startTime - this.pausedDuration - currentPaused;
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
    this.usage.duration = this.getEffectiveDuration();
  }

  /**
   * Record a tool call for progress tracking and loop detection.
   */
  recordToolCall(toolName: string, args: Record<string, unknown>, _result?: unknown): void {
    this.usage.toolCalls++;
    this.usage.iterations++;

    const now = Date.now();

    // Track for loop detection (stableStringify ensures consistent ordering for comparison)
    const argsStr = stableStringify(args);
    this.progress.recentToolCalls.push({ tool: toolName, args: argsStr, timestamp: now });

    // Keep only last 10 for loop detection
    if (this.progress.recentToolCalls.length > 10) {
      this.progress.recentToolCalls.shift();
    }

    // =========================================================================
    // DOOM LOOP DETECTION (OpenCode pattern)
    // =========================================================================
    this.updateDoomLoopState(toolName, argsStr);

    // =========================================================================
    // PHASE TRACKING
    // =========================================================================
    this.updatePhaseState(toolName, args);

    // Track file operations
    if (toolName === 'read_file' && args.path) {
      const path = String(args.path);
      const isNewFile = !this.progress.filesRead.has(path);
      this.progress.filesRead.add(path);
      this.phaseState.uniqueFilesRead.add(path);

      // Track new files for diminishing returns detection
      if (isNewFile) {
        this.phaseState.recentNewFiles++;
      }

      // Only count reads as progress during initial exploration (first 5 iterations)
      if (this.usage.iterations <= 5) {
        this.progress.lastMeaningfulProgress = now;
        this.progress.stuckCount = 0;
      }
    }

    // Track search operations
    if (['grep', 'search', 'glob', 'find_files', 'search_files'].includes(toolName)) {
      const query = String(args.pattern || args.query || args.path || '');
      this.phaseState.uniqueSearches.add(query);
    }

    if (['write_file', 'edit_file'].includes(toolName) && args.path) {
      this.progress.filesModified.add(String(args.path));
      this.phaseState.filesModified.add(String(args.path));
      this.progress.lastMeaningfulProgress = now;
      this.progress.stuckCount = 0;

      // Transition to acting phase when first edit is made
      if (this.phaseState.phase === 'exploring' || this.phaseState.phase === 'planning') {
        this.transitionPhase('acting', 'First file edit made');
      }
    }

    if (toolName === 'bash' && args.command) {
      const command = String(args.command);
      this.progress.commandsRun.push(command);
      this.progress.lastMeaningfulProgress = now;
      this.progress.stuckCount = 0;

      // Detect test runs
      if (command.includes('test') || command.includes('pytest') || command.includes('npm test') || command.includes('jest')) {
        this.phaseState.testsRun++;
        // Transition to verifying phase when tests are run after edits
        if (this.phaseState.phase === 'acting' && this.phaseState.filesModified.size > 0) {
          this.transitionPhase('verifying', 'Tests run after edits');
        }
      }
    }

    // Update exploration saturation check
    this.checkExplorationSaturation();

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
   * Update doom loop detection state.
   * Detects when the same tool+args are called consecutively.
   */
  private updateDoomLoopState(toolName: string, argsStr: string): void {
    const currentCall = `${toolName}:${argsStr}`;
    const recentCalls = this.progress.recentToolCalls;

    // Count consecutive identical calls from the end
    let consecutiveCount = 0;
    for (let i = recentCalls.length - 1; i >= 0; i--) {
      const call = recentCalls[i];
      if (`${call.tool}:${call.args}` === currentCall) {
        consecutiveCount++;
      } else {
        break;
      }
    }

    this.loopState.consecutiveCount = consecutiveCount;
    this.loopState.lastTool = toolName;

    // Detect doom loop when threshold reached
    const wasDoomLoop = this.loopState.doomLoopDetected;
    this.loopState.doomLoopDetected = consecutiveCount >= this.loopState.threshold;

    // Emit event when doom loop first detected (not on every check)
    if (this.loopState.doomLoopDetected && !wasDoomLoop) {
      this.emit({
        type: 'doom_loop.detected',
        tool: toolName,
        consecutiveCount,
      });
    }
  }

  /**
   * Update phase tracking state.
   */
  private updatePhaseState(_toolName: string, _args: Record<string, unknown>): void {
    this.phaseState.iterationsInPhase++;

    // Reset recentNewFiles counter every 3 iterations for diminishing returns check
    if (this.phaseState.iterationsInPhase % 3 === 0) {
      this.phaseState.recentNewFiles = 0;
    }
  }

  /**
   * Transition to a new phase.
   */
  private transitionPhase(newPhase: PhaseState['phase'], reason: string): void {
    const oldPhase = this.phaseState.phase;
    if (oldPhase === newPhase) return;

    this.emit({
      type: 'phase.transition',
      from: oldPhase,
      to: newPhase,
      reason,
    });

    this.phaseState.phase = newPhase;
    this.phaseState.iterationsInPhase = 0;
    this.phaseState.recentNewFiles = 0;

    if (newPhase === 'exploring') {
      this.phaseState.explorationStartIteration = this.usage.iterations;
    }
  }

  /**
   * Check for exploration saturation (reading too many files without action).
   */
  private checkExplorationSaturation(): void {
    const { phase, uniqueFilesRead, iterationsInPhase, recentNewFiles, filesModified } = this.phaseState;

    // Only check during exploration phase
    if (phase !== 'exploring') {
      this.phaseState.shouldTransition = false;
      return;
    }

    // After reading 10+ unique files without edits, suggest transition
    if (uniqueFilesRead.size >= 10 && filesModified.size === 0) {
      this.phaseState.shouldTransition = true;
      this.emit({
        type: 'exploration.saturation',
        filesRead: uniqueFilesRead.size,
        iterations: iterationsInPhase,
      });
      return;
    }

    // After 5+ iterations in exploration with diminishing returns (< 2 new files)
    if (iterationsInPhase >= 5 && recentNewFiles < 2 && filesModified.size === 0) {
      this.phaseState.shouldTransition = true;
      this.emit({
        type: 'exploration.saturation',
        filesRead: uniqueFilesRead.size,
        iterations: iterationsInPhase,
      });
      return;
    }

    this.phaseState.shouldTransition = false;
  }

  /**
   * Check if execution can continue.
   */
  checkBudget(): BudgetCheckResult {
    this.usage.duration = this.getEffectiveDuration();

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

    // Max iterations reached - allow one more turn for summary (forceTextOnly)
    if (this.usage.iterations >= this.budget.maxIterations) {
      return {
        canContinue: true,  // Allow one more turn for summary
        reason: `Maximum iterations reached (${this.usage.iterations} / ${this.budget.maxIterations})`,
        budgetType: 'iterations',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: 100,
        suggestedAction: 'stop',
        forceTextOnly: true,  // No more tool calls
        injectedPrompt: MAX_STEPS_PROMPT,
      };
    }

    // =========================================================================
    // DOOM LOOP DETECTION - Strong intervention
    // =========================================================================
    if (this.loopState.doomLoopDetected) {
      return {
        canContinue: true,
        reason: `Doom loop detected: ${this.loopState.lastTool} called ${this.loopState.consecutiveCount} times`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: DOOM_LOOP_PROMPT(this.loopState.lastTool || 'unknown', this.loopState.consecutiveCount),
      };
    }

    // =========================================================================
    // EXPLORATION SATURATION - Gentle nudge
    // =========================================================================
    if (this.phaseState.shouldTransition) {
      return {
        canContinue: true,
        reason: `Exploration saturation: ${this.phaseState.uniqueFilesRead.size} files read`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: EXPLORATION_NUDGE_PROMPT(
          this.phaseState.uniqueFilesRead.size,
          this.phaseState.iterationsInPhase
        ),
      };
    }

    // Check soft limits (warnings)
    if (this.usage.tokens >= this.budget.softTokenLimit) {
      const remaining = this.budget.maxTokens - this.usage.tokens;
      const percentUsed = Math.round((this.usage.tokens / this.budget.maxTokens) * 100);
      this.emit({ type: 'budget.warning', budgetType: 'tokens', percentUsed, remaining });
      return {
        canContinue: true,
        reason: `Token budget at ${percentUsed}%`,
        budgetType: 'tokens',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed,
        suggestedAction: 'request_extension',
        // Inject warning prompt so agent knows to wrap up
        injectedPrompt: `⚠️ **BUDGET WARNING**: You have used ${percentUsed}% of your token budget (${this.usage.tokens.toLocaleString()}/${this.budget.maxTokens.toLocaleString()} tokens). ` +
          `Only ~${remaining.toLocaleString()} tokens remaining. WRAP UP NOW - summarize your findings and return a concise result. ` +
          `Do not start new explorations.`,
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
    this.usage.duration = this.getEffectiveDuration();
    return { ...this.usage };
  }

  /**
   * Get current budget.
   */
  getBudget(): ExecutionBudget {
    return { ...this.budget };
  }

  /**
   * Get a formatted budget status string for context awareness.
   * Used by subagents to understand their remaining resources.
   */
  getBudgetStatusString(): string {
    const usage = this.getUsage();
    const budget = this.budget;

    const tokenPct = Math.round((usage.tokens / budget.maxTokens) * 100);
    const remainingTokens = budget.maxTokens - usage.tokens;
    const remainingSec = Math.max(0, Math.round((budget.maxDuration - usage.duration) / 1000));

    // Determine urgency level
    let urgency = '';
    if (tokenPct >= 90) {
      urgency = '⚠️ CRITICAL: ';
    } else if (tokenPct >= 70) {
      urgency = '⚡ WARNING: ';
    }

    return `${urgency}Budget: ${usage.tokens.toLocaleString()}/${budget.maxTokens.toLocaleString()} tokens (${tokenPct}%), ~${remainingSec}s remaining. ${
      tokenPct >= 70 ? 'Wrap up soon!' : ''
    }`.trim();
  }

  /**
   * Check if approaching budget limit (for proactive warnings).
   */
  isApproachingLimit(): { approaching: boolean; metric: string; percentUsed: number } {
    const usage = this.getUsage();
    const budget = this.budget;

    const tokenPct = (usage.tokens / budget.maxTokens) * 100;
    const durationPct = (usage.duration / budget.maxDuration) * 100;

    if (tokenPct >= 80) {
      return { approaching: true, metric: 'tokens', percentUsed: tokenPct };
    }
    if (durationPct >= 80) {
      return { approaching: true, metric: 'duration', percentUsed: durationPct };
    }

    return { approaching: false, metric: '', percentUsed: Math.max(tokenPct, durationPct) };
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
   * Get doom loop detection state.
   */
  getLoopState(): LoopDetectionState {
    return { ...this.loopState };
  }

  /**
   * Get exploration phase state.
   */
  getPhaseState(): {
    phase: string;
    uniqueFilesRead: number;
    uniqueSearches: number;
    filesModified: number;
    testsRun: number;
    shouldTransition: boolean;
    iterationsInPhase: number;
  } {
    return {
      phase: this.phaseState.phase,
      uniqueFilesRead: this.phaseState.uniqueFilesRead.size,
      uniqueSearches: this.phaseState.uniqueSearches.size,
      filesModified: this.phaseState.filesModified.size,
      testsRun: this.phaseState.testsRun,
      shouldTransition: this.phaseState.shouldTransition,
      iterationsInPhase: this.phaseState.iterationsInPhase,
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

    // Reset loop detection state
    this.loopState = {
      doomLoopDetected: false,
      lastTool: null,
      consecutiveCount: 0,
      threshold: 3,
      lastWarningTime: 0,
    };

    // Reset phase tracking state
    this.phaseState = {
      phase: 'exploring',
      explorationStartIteration: 0,
      uniqueFilesRead: new Set(),
      uniqueSearches: new Set(),
      filesModified: new Set(),
      testsRun: 0,
      shouldTransition: false,
      iterationsInPhase: 0,
      recentNewFiles: 0,
    };

    this.startTime = Date.now();
    this.pausedDuration = 0;
    this.pauseStart = null;
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
  maxDuration: 600000, // 10 minutes (supports subagent workflows)
  targetIterations: 20,
  maxIterations: 50,
};

/**
 * Subagent budget - constrained budget for spawned subagents.
 * Smaller than STANDARD to ensure subagents don't consume all parent's resources.
 * The 100k token limit gives subagents room to work while leaving budget for the parent
 * and other parallel subagents.
 */
export const SUBAGENT_BUDGET: Partial<ExecutionBudget> = {
  maxTokens: 150000,       // 150k tokens (research agents need more room)
  softTokenLimit: 100000,  // Warn at 100k
  maxCost: 0.50,           // Match standard budget
  maxDuration: 360000,     // 6 minutes
  softDurationLimit: 300000, // Warn at 5 minutes
  targetIterations: 20,
  maxIterations: 40,
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
