/**
 * Lesson 25: Execution Economics System
 *
 * Replaces hard-coded iteration limits with intelligent budget management:
 * - Token budgets (primary constraint)
 * - Cost budgets (maps to real API costs)
 * - Time budgets (wall-clock limits)
 * - Progress detection (stuck vs productive)
 * - Adaptive limits with extension requests
 *
 * Phase 3b: Core manager + presets. Loop detection and phase tracking
 * are extracted into loop-detector.ts and phase-tracker.ts respectively.
 */

import { stableStringify } from '../context/context-engineering.js';
import { calculateCost } from '../utilities/openrouter-pricing.js';
import type { SharedEconomicsState } from '../../shared/shared-economics-state.js';

// Re-export from extracted modules for backward compatibility
export {
  computeToolFingerprint,
  extractBashResult,
  extractBashFileTarget,
  LoopDetector,
  type RecentToolCall,
} from './loop-detector.js';

export { PhaseTracker } from './phase-tracker.js';

// Import from extracted modules for internal use
import {
  computeToolFingerprint,
  extractBashResult,
  LoopDetector,
  DOOM_LOOP_PROMPT,
  GLOBAL_DOOM_LOOP_PROMPT,
  TEST_FIX_RETHINK_PROMPT,
  BASH_FAILURE_CASCADE_PROMPT,
  SUMMARY_LOOP_PROMPT,
} from './loop-detector.js';

import {
  PhaseTracker,
  EXPLORATION_NUDGE_PROMPT,
  EXPLORATION_BUDGET_EXCEEDED_PROMPT,
  VERIFICATION_RESERVE_PROMPT,
} from './phase-tracker.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configurable economics thresholds for tuning doom loop and exploration detection.
 * Passed via ExecutionBudget.tuning; defaults are used when omitted.
 */
export interface EconomicsTuning {
  /** Threshold for exact doom loop detection (default: 3) */
  doomLoopThreshold?: number;
  /** Threshold for fuzzy doom loop detection (default: doomLoopThreshold + 1) */
  doomLoopFuzzyThreshold?: number;
  /** Unique files read before exploration saturation warning (default: 10) */
  explorationFileThreshold?: number;
  /** Iterations in exploration with diminishing returns before warning (default: 5) */
  explorationIterThreshold?: number;
  /** Iterations with zero tool calls before forceTextOnly (default: 5) */
  zeroProgressThreshold?: number;
  /** Iteration checkpoint for adaptive budget reduction (default: 5) */
  progressCheckpoint?: number;
  /** Max tool calls to execute from a single LLM response (default: 25) */
  maxToolCallsPerResponse?: number;
  /** Max consecutive tool failures before circuit breaker trips (default: 5) */
  circuitBreakerFailureThreshold?: number;
}

/**
 * Execution budget configuration.
 */
export interface ExecutionBudget {
  /** Enforcement policy for hard token/cost/duration limits. */
  enforcementMode?: 'strict' | 'doomloop_only';

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

  /** Configurable thresholds for economics behavior tuning */
  tuning?: EconomicsTuning;
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
  /** Baseline context tokens (not counted toward budget) */
  baselineContextTokens: number;
  /** Running total of all input tokens across all LLM calls (for debugging) */
  cumulativeInputTokens: number;
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
  /** Threshold for fuzzy doom loop detection (default: threshold + 1) */
  fuzzyThreshold: number;
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
  /** Whether the last test passed */
  lastTestPassed: boolean | null;
  /** Consecutive test failures count */
  consecutiveTestFailures: number;
  /** Whether agent is in a test-fix cycle */
  inTestFixCycle: boolean;
  /** Consecutive bash command failures (any command, not just tests) */
  consecutiveBashFailures: number;
  /** Consecutive turns where LLM produced text only (no tool calls) */
  consecutiveTextOnlyTurns: number;
}

/**
 * Phase-aware budget allocation config.
 * Prevents spending too long in exploration and reserves time for verification.
 */
export interface PhaseBudgetConfig {
  /** Max percent of iterations for exploration (default: 30%) */
  maxExplorationPercent: number;
  /** Percent of iterations reserved for verification (default: 20%) */
  reservedVerificationPercent: number;
  /** Whether phase budget enforcement is enabled */
  enabled: boolean;
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
  /** Graduated budget severity level */
  budgetMode?: 'none' | 'warn' | 'restricted' | 'hard';
  /** Whether task-switching is allowed (false only at hard limits) */
  allowTaskContinuation?: boolean;
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
// PROMPT CONSTANTS (kept in manager for budget-level prompts)
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
 * Timeout wrapup prompt - injected when a subagent is about to be stopped due to timeout.
 * Forces a structured JSON summary so the parent agent can make intelligent follow-up decisions.
 */
export const TIMEOUT_WRAPUP_PROMPT = `[System] You are about to be stopped due to timeout. You MUST respond with a structured summary NOW.

Respond with ONLY this JSON (no tool calls):
{
  "findings": ["what you discovered or accomplished"],
  "actionsTaken": ["files read, modifications made, commands run"],
  "failures": ["what failed or was blocked"],
  "remainingWork": ["what you didn't finish"],
  "suggestedNextSteps": ["what the parent agent should do next"]
}`;

const BUDGET_ADVISORY_PROMPT = (reason: string) =>
`[System] Budget advisory (${reason}) detected. Continue execution and focus on concrete tool actions to complete the task.`;

// =============================================================================
// ECONOMICS MANAGER
// =============================================================================

/**
 * ExecutionEconomicsManager handles budget tracking and progress detection.
 *
 * Delegates loop detection to LoopDetector and phase tracking to PhaseTracker.
 */
export class ExecutionEconomicsManager {
  private budget: ExecutionBudget;
  private usage: ExecutionUsage;
  private progress: ProgressState;
  private loopDetector: LoopDetector;
  private phaseTracker: PhaseTracker;
  private phaseBudget: PhaseBudgetConfig | null = null;
  private startTime: number;
  private pausedDuration = 0;
  private pauseStart: number | null = null;
  private listeners: EconomicsEventListener[] = [];
  private extensionHandler?: (request: ExtensionRequest) => Promise<Partial<ExecutionBudget> | null>;

  // Shared economics state for cross-worker doom loop aggregation
  private sharedEconomics: SharedEconomicsState | null;
  private workerId: string;

  // Adaptive budget: stores original maxIterations for reversible reduction
  private originalMaxIterations: number | null = null;

  // Incremental token accounting
  private baseline = 0;
  private lastInputTokens = 0;

  constructor(budget?: Partial<ExecutionBudget>, sharedEconomics?: SharedEconomicsState, workerId?: string) {
    this.sharedEconomics = sharedEconomics ?? null;
    this.workerId = workerId ?? 'root';
    const tuning = budget?.tuning;

    this.budget = {
      enforcementMode: budget?.enforcementMode ?? 'strict',
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

      // Tuning
      tuning,
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
      baselineContextTokens: 0,
      cumulativeInputTokens: 0,
    };

    this.progress = {
      filesRead: new Set(),
      filesModified: new Set(),
      commandsRun: [],
      recentToolCalls: [],
      lastMeaningfulProgress: Date.now(),
      stuckCount: 0,
    };

    // Initialize extracted modules
    this.loopDetector = new LoopDetector(tuning);
    this.phaseTracker = new PhaseTracker(tuning, (event) => this.emit(event));

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
   * Configure phase-aware budget allocation.
   * Only active when enabled=true (eval mode). TUI mode leaves it off.
   */
  setPhaseBudget(config: PhaseBudgetConfig): void {
    this.phaseBudget = config;
  }

  /**
   * Set baseline context tokens for incremental accounting.
   * Tokens up to this baseline are not counted toward the budget.
   */
  setBaseline(tokens: number): void {
    this.baseline = tokens;
    this.usage.baselineContextTokens = tokens;
  }

  /**
   * Get current baseline context tokens.
   */
  getBaseline(): number {
    return this.baseline;
  }

  /**
   * Update baseline after compaction reduces context size.
   */
  updateBaseline(tokens: number): void {
    this.baseline = tokens;
    this.usage.baselineContextTokens = tokens;
  }

  /**
   * Estimate the incremental cost of the next LLM call.
   * Subtracts baseline from input tokens to give incremental cost.
   */
  estimateNextCallCost(inputTokens: number, outputTokens: number): number {
    const incrementalInput = Math.max(0, inputTokens - this.baseline);
    return incrementalInput + outputTokens;
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
   * When a baseline is set, uses incremental accounting: only tokens beyond what
   * was seen in the previous call are counted toward the budget.
   * @param inputTokens - Number of input tokens
   * @param outputTokens - Number of output tokens
   * @param model - Model name (for fallback pricing calculation)
   * @param actualCost - Actual cost from provider (e.g., OpenRouter returns this directly)
   * @param cacheReadTokens - Tokens served from cache (deducted from incremental input)
   */
  recordLLMUsage(inputTokens: number, outputTokens: number, model?: string, actualCost?: number, cacheReadTokens?: number): void {
    // Track cumulative input for debugging (always the full input)
    this.usage.cumulativeInputTokens += inputTokens;

    // On the very first LLM call, refine the baseline from the actual
    // API-reported input tokens. The initial estimate (from systemPrompt
    // char count) may miss tool definitions, rules, etc. Using the real
    // value makes the first call "free" (all context is baseline) and
    // subsequent calls only pay the marginal token growth.
    if (this.baseline > 0 && this.usage.llmCalls === 0) {
      this.baseline = inputTokens;
      this.usage.baselineContextTokens = inputTokens;
    }

    // Incremental accounting: only count new tokens since last call
    let effectiveInput: number;
    if (this.baseline > 0) {
      const incrementalInput = Math.max(0, inputTokens - this.lastInputTokens);
      effectiveInput = Math.max(0, incrementalInput - (cacheReadTokens ?? 0));
    } else {
      // No baseline: cumulative mode (backward compat)
      effectiveInput = cacheReadTokens ? Math.max(0, inputTokens - cacheReadTokens) : inputTokens;
    }

    this.lastInputTokens = inputTokens;
    this.usage.inputTokens += effectiveInput;
    this.usage.outputTokens += outputTokens;
    this.usage.tokens += effectiveInput + outputTokens;
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
   * Record a text-only turn (LLM response with no tool calls).
   * Increments the consecutive text-only turn counter for summary-loop detection.
   */
  recordTextOnlyTurn(): void {
    this.phaseTracker.recordTextOnlyTurn();
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
    // DOOM LOOP DETECTION (delegated to LoopDetector)
    // =========================================================================
    const newDoomLoop = this.loopDetector.updateDoomLoopState(toolName, argsStr, this.progress.recentToolCalls);
    if (newDoomLoop) {
      this.emit({
        type: 'doom_loop.detected',
        tool: toolName,
        consecutiveCount: this.loopDetector.consecutiveCount,
      });
    }

    // Report to shared economics for cross-worker doom loop aggregation
    if (this.sharedEconomics) {
      const fingerprint = computeToolFingerprint(toolName, argsStr);
      this.sharedEconomics.recordToolCall(this.workerId, fingerprint);
    }

    // =========================================================================
    // PHASE TRACKING (delegated to PhaseTracker)
    // =========================================================================
    this.phaseTracker.onToolCall();

    // Track file operations
    if (toolName === 'read_file' && args.path) {
      const path = String(args.path);
      const isNewFile = !this.progress.filesRead.has(path);
      this.progress.filesRead.add(path);
      this.phaseTracker.trackFileRead(path);

      // Only count reads as progress during initial exploration (first 5 iterations)
      if (this.usage.iterations <= 5) {
        this.progress.lastMeaningfulProgress = now;
        this.progress.stuckCount = 0;
      }
    }

    // Track search operations
    if (['grep', 'search', 'glob', 'find_files', 'search_files'].includes(toolName)) {
      const query = String(args.pattern || args.query || args.path || '');
      this.phaseTracker.trackSearch(query);
    }

    if (['write_file', 'edit_file'].includes(toolName) && args.path) {
      this.progress.filesModified.add(String(args.path));
      this.phaseTracker.trackFileModified(String(args.path));
      this.progress.lastMeaningfulProgress = now;
      this.progress.stuckCount = 0;
    }

    if (toolName === 'bash' && args.command) {
      const command = String(args.command);
      this.progress.commandsRun.push(command);
      this.progress.lastMeaningfulProgress = now;
      this.progress.stuckCount = 0;

      // Extract result from bash tool output (object or string)
      const bashResult = extractBashResult(_result);

      // Track bash result in phase tracker (handles failures, test outcomes)
      if (_result !== undefined) {
        this.phaseTracker.trackBashResult(command, bashResult.success, bashResult.output);
      } else {
        // Detect test runs even without result (for phase transition)
        if (command.includes('test') || command.includes('pytest') || command.includes('npm test') || command.includes('jest')) {
          this.phaseTracker.trackBashResult(command, true, '');
        }
      }
    }

    // Update exploration saturation check
    this.phaseTracker.checkExplorationSaturation();

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
    this.usage.duration = this.getEffectiveDuration();
    const strictBudgetEnforcement = (this.budget.enforcementMode ?? 'strict') === 'strict';
    const phaseState = this.phaseTracker.rawState;

    // Check hard limits first
    if (this.usage.tokens >= this.budget.maxTokens) {
      this.emit({ type: 'budget.exceeded', budgetType: 'tokens', limit: this.budget.maxTokens, actual: this.usage.tokens });
      if (!strictBudgetEnforcement) {
        return {
          canContinue: true,
          reason: `Token budget exceeded (${this.usage.tokens.toLocaleString()} / ${this.budget.maxTokens.toLocaleString()})`,
          budgetType: 'tokens',
          isHardLimit: false,
          isSoftLimit: true,
          percentUsed: (this.usage.tokens / this.budget.maxTokens) * 100,
          suggestedAction: 'warn',
          injectedPrompt: BUDGET_ADVISORY_PROMPT('tokens'),
          budgetMode: 'warn',
          allowTaskContinuation: true,
        };
      }
      return {
        canContinue: false,
        reason: `Token budget exceeded (${this.usage.tokens.toLocaleString()} / ${this.budget.maxTokens.toLocaleString()})`,
        budgetType: 'tokens',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: (this.usage.tokens / this.budget.maxTokens) * 100,
        suggestedAction: 'stop',
        budgetMode: 'hard',
        allowTaskContinuation: false,
      };
    }

    if (this.usage.cost >= this.budget.maxCost) {
      this.emit({ type: 'budget.exceeded', budgetType: 'cost', limit: this.budget.maxCost, actual: this.usage.cost });
      if (!strictBudgetEnforcement) {
        return {
          canContinue: true,
          reason: `Cost budget exceeded ($${this.usage.cost.toFixed(2)} / $${this.budget.maxCost.toFixed(2)})`,
          budgetType: 'cost',
          isHardLimit: false,
          isSoftLimit: true,
          percentUsed: (this.usage.cost / this.budget.maxCost) * 100,
          suggestedAction: 'warn',
          injectedPrompt: BUDGET_ADVISORY_PROMPT('cost'),
          budgetMode: 'warn',
          allowTaskContinuation: true,
        };
      }
      return {
        canContinue: false,
        reason: `Cost budget exceeded ($${this.usage.cost.toFixed(2)} / $${this.budget.maxCost.toFixed(2)})`,
        budgetType: 'cost',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: (this.usage.cost / this.budget.maxCost) * 100,
        suggestedAction: 'stop',
        budgetMode: 'hard',
        allowTaskContinuation: false,
      };
    }

    if (this.usage.duration >= this.budget.maxDuration) {
      this.emit({ type: 'budget.exceeded', budgetType: 'duration', limit: this.budget.maxDuration, actual: this.usage.duration });
      if (!strictBudgetEnforcement) {
        return {
          canContinue: true,
          reason: `Duration limit exceeded (${Math.round(this.usage.duration / 1000)}s / ${Math.round(this.budget.maxDuration / 1000)}s)`,
          budgetType: 'duration',
          isHardLimit: false,
          isSoftLimit: true,
          percentUsed: (this.usage.duration / this.budget.maxDuration) * 100,
          suggestedAction: 'warn',
          injectedPrompt: BUDGET_ADVISORY_PROMPT('duration'),
          budgetMode: 'warn',
          allowTaskContinuation: true,
        };
      }
      return {
        canContinue: false,
        reason: `Duration limit exceeded (${Math.round(this.usage.duration / 1000)}s / ${Math.round(this.budget.maxDuration / 1000)}s)`,
        budgetType: 'duration',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: (this.usage.duration / this.budget.maxDuration) * 100,
        suggestedAction: 'stop',
        budgetMode: 'hard',
        allowTaskContinuation: false,
      };
    }

    // Max iterations reached -- allow exactly ONE more turn for summary, then terminate.
    if (this.usage.iterations >= this.budget.maxIterations) {
      const isFirstOverage = this.usage.iterations === this.budget.maxIterations;
      return {
        canContinue: isFirstOverage,  // Only allow one summary turn
        reason: `Maximum iterations reached (${this.usage.iterations} / ${this.budget.maxIterations})`,
        budgetType: 'iterations',
        isHardLimit: true,
        isSoftLimit: false,
        percentUsed: 100,
        suggestedAction: 'stop',
        forceTextOnly: true,  // No more tool calls
        injectedPrompt: MAX_STEPS_PROMPT,
        budgetMode: 'hard',
        allowTaskContinuation: false,
      };
    }

    // =========================================================================
    // ZERO PROGRESS DETECTION (D1)
    // =========================================================================
    const zeroProgressThreshold = this.budget.tuning?.zeroProgressThreshold ?? 10;
    if (this.usage.iterations >= zeroProgressThreshold && this.usage.toolCalls === 0) {
      const isCompleteStall = this.usage.iterations >= zeroProgressThreshold * 2;
      return {
        canContinue: true,
        reason: `Zero tool calls in ${this.usage.iterations} iterations`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.maxIterations) * 100,
        suggestedAction: isCompleteStall ? 'stop' : 'warn',
        forceTextOnly: isCompleteStall,
        injectedPrompt: `[System] WARNING: You have completed ${this.usage.iterations} iterations without making a single tool call. ` +
          `You MUST use your tools (read_file, write_file, grep, bash, etc.) to accomplish your task. ` +
          `Start by reading a relevant file or running a command NOW.` +
          (isCompleteStall ? ` This is your LAST chance — respond with a summary if you cannot proceed.` : ''),
      };
    }

    // =========================================================================
    // ADAPTIVE ITERATION BUDGET (D4)
    // =========================================================================
    const checkpoint = this.budget.tuning?.progressCheckpoint ?? 10;
    if (this.usage.iterations === checkpoint && this.usage.toolCalls === 0) {
      if (!this.originalMaxIterations) {
        this.originalMaxIterations = this.budget.maxIterations;
      }
      const reducedMax = checkpoint + 5;
      if (this.budget.maxIterations > reducedMax) {
        this.budget.maxIterations = reducedMax;
      }
    }
    // Restore original maxIterations if tools start being used after reduction
    if (this.originalMaxIterations && this.usage.toolCalls > 0 && this.budget.maxIterations < this.originalMaxIterations) {
      this.budget.maxIterations = this.originalMaxIterations;
      this.originalMaxIterations = null;
    }

    // =========================================================================
    // DOOM LOOP DETECTION - Strong intervention (delegated to LoopDetector)
    // =========================================================================
    if (this.loopDetector.isDoomLoop) {
      return {
        canContinue: true,
        reason: `Doom loop detected: ${this.loopDetector.lastTool} called ${this.loopDetector.consecutiveCount} times`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: DOOM_LOOP_PROMPT(this.loopDetector.lastTool || 'unknown', this.loopDetector.consecutiveCount),
        budgetMode: 'warn',
        allowTaskContinuation: true,
      };
    }

    // =========================================================================
    // GLOBAL DOOM LOOP DETECTION - Cross-worker stuck pattern
    // =========================================================================
    if (this.sharedEconomics && this.progress.recentToolCalls.length > 0) {
      const lastCall = this.progress.recentToolCalls[this.progress.recentToolCalls.length - 1];
      const fingerprint = computeToolFingerprint(lastCall.tool, lastCall.args);
      if (this.sharedEconomics.isGlobalDoomLoop(fingerprint)) {
        const info = this.sharedEconomics.getGlobalLoopInfo(fingerprint);
        return {
          canContinue: true,
          reason: `Global doom loop: ${lastCall.tool} repeated across ${info?.workerCount ?? 0} workers`,
          budgetType: 'iterations',
          isHardLimit: false,
          isSoftLimit: true,
          percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
          suggestedAction: 'warn',
          injectedPrompt: GLOBAL_DOOM_LOOP_PROMPT(
            lastCall.tool,
            info?.workerCount ?? 0,
            info?.count ?? 0,
          ),
        };
      }
    }

    // =========================================================================
    // EXPLORATION SATURATION - Gentle nudge (delegated to PhaseTracker)
    // =========================================================================
    if (phaseState.shouldTransition) {
      return {
        canContinue: true,
        reason: `Exploration saturation: ${phaseState.uniqueFilesRead.size} files read`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: EXPLORATION_NUDGE_PROMPT(
          phaseState.uniqueFilesRead.size,
          phaseState.iterationsInPhase
        ),
      };
    }

    // =========================================================================
    // TEST-FIX CYCLE - Nudge to rethink after 3+ consecutive failures
    // =========================================================================
    if (phaseState.consecutiveTestFailures >= 3) {
      return {
        canContinue: true,
        reason: `${phaseState.consecutiveTestFailures} consecutive test failures`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: TEST_FIX_RETHINK_PROMPT(phaseState.consecutiveTestFailures),
      };
    }

    // =========================================================================
    // BASH FAILURE CASCADE - Strong intervention after 3+ consecutive failures
    // =========================================================================
    if (phaseState.consecutiveBashFailures >= 3) {
      const lastBashCommand = this.loopDetector.extractLastBashCommand(this.progress.recentToolCalls);
      return {
        canContinue: true,
        reason: `${phaseState.consecutiveBashFailures} consecutive bash failures`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: BASH_FAILURE_CASCADE_PROMPT(phaseState.consecutiveBashFailures, lastBashCommand),
      };
    }

    // =========================================================================
    // SUMMARY LOOP DETECTION - Nudge after 2+ consecutive text-only turns
    // =========================================================================
    if (phaseState.consecutiveTextOnlyTurns >= 2) {
      const nearBudgetLimit = this.usage.iterations >= this.budget.maxIterations - 1;
      if (!nearBudgetLimit) {
        return {
          canContinue: true,
          reason: `${phaseState.consecutiveTextOnlyTurns} consecutive text-only turns (summary loop)`,
          budgetType: 'iterations',
          isHardLimit: false,
          isSoftLimit: true,
          percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
          suggestedAction: 'warn',
          injectedPrompt: SUMMARY_LOOP_PROMPT,
        };
      }
      // Near budget limit: skip nudge, let MAX_STEPS_PROMPT handle it next turn
    }

    // =========================================================================
    // PHASE-AWARE BUDGET ALLOCATION (opt-in, used in eval mode)
    // =========================================================================
    if (this.phaseBudget?.enabled) {
      const iterPct = (this.usage.iterations / this.budget.maxIterations) * 100;
      const explorationPct = phaseState.phase === 'exploring'
        ? (phaseState.iterationsInPhase / this.budget.maxIterations) * 100
        : 0;

      // Too much time in exploration
      if (explorationPct > this.phaseBudget.maxExplorationPercent && phaseState.filesModified.size === 0) {
        return {
          canContinue: true,
          reason: `Exploration exceeds ${this.phaseBudget.maxExplorationPercent}% of budget`,
          budgetType: 'iterations',
          isHardLimit: false,
          isSoftLimit: true,
          percentUsed: iterPct,
          suggestedAction: 'warn',
          injectedPrompt: EXPLORATION_BUDGET_EXCEEDED_PROMPT(Math.round(explorationPct)),
        };
      }

      // Only verification-reserve iterations remain
      const remainingPct = 100 - iterPct;
      if (remainingPct <= this.phaseBudget.reservedVerificationPercent
          && phaseState.phase !== 'verifying'
          && phaseState.filesModified.size > 0
          && phaseState.testsRun === 0) {
        return {
          canContinue: true,
          reason: `Only ${Math.round(remainingPct)}% budget remaining, verification needed`,
          budgetType: 'iterations',
          isHardLimit: false,
          isSoftLimit: true,
          percentUsed: iterPct,
          suggestedAction: 'warn',
          injectedPrompt: VERIFICATION_RESERVE_PROMPT,
        };
      }
    }

    // Check soft limits (warnings)
    if (this.usage.tokens >= this.budget.softTokenLimit) {
      const remaining = this.budget.maxTokens - this.usage.tokens;
      const percentUsed = Math.round((this.usage.tokens / this.budget.maxTokens) * 100);
      this.emit({ type: 'budget.warning', budgetType: 'tokens', percentUsed, remaining });

      // Only force text-only in strict mode. In doomloop_only mode,
      // soft limits warn but do not kill the agent.
      const forceTextOnly = strictBudgetEnforcement && percentUsed >= 80;

      return {
        canContinue: true,
        reason: `Token budget at ${percentUsed}%`,
        budgetType: 'tokens',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed,
        suggestedAction: forceTextOnly ? 'stop' : 'request_extension',
        forceTextOnly,
        budgetMode: forceTextOnly ? 'restricted' : 'warn',
        allowTaskContinuation: true,
        injectedPrompt: forceTextOnly
          ? `\u26a0\ufe0f **BUDGET CRITICAL**: ${percentUsed}% used (${this.usage.tokens.toLocaleString()}/${this.budget.maxTokens.toLocaleString()}). ` +
            `WRAP UP IMMEDIATELY. Return a concise summary. Do NOT call any tools.`
          : `\u26a0\ufe0f **BUDGET WARNING**: You have used ${percentUsed}% of your token budget (${this.usage.tokens.toLocaleString()}/${this.budget.maxTokens.toLocaleString()} tokens). ` +
            `Only ~${remaining.toLocaleString()} tokens remaining. Focus on completing current work. ` +
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
      budgetMode: 'none',
      allowTaskContinuation: true,
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
    const remainingSec = budget.maxDuration === Infinity
      ? Infinity
      : Math.max(0, Math.round((budget.maxDuration - usage.duration) / 1000));

    // Determine urgency level
    let urgency = '';
    if (tokenPct >= 90) {
      urgency = '\u26a0\ufe0f CRITICAL: ';
    } else if (tokenPct >= 70) {
      urgency = '\u26a1 WARNING: ';
    }

    const timeStr = remainingSec === Infinity ? 'no time limit' : `~${remainingSec}s remaining`;
    return `${urgency}Budget: ${usage.tokens.toLocaleString()}/${budget.maxTokens.toLocaleString()} tokens (${tokenPct}%), ${timeStr}. ${
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
   * Get actual file paths modified during this session.
   */
  getModifiedFilePaths(): string[] {
    return [...this.progress.filesModified];
  }

  /**
   * Get doom loop detection state.
   */
  getLoopState(): LoopDetectionState {
    return this.loopDetector.getState();
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
    lastTestPassed: boolean | null;
    consecutiveTestFailures: number;
    inTestFixCycle: boolean;
    consecutiveBashFailures: number;
  } {
    return this.phaseTracker.getSnapshot();
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
    this.baseline = 0;
    this.lastInputTokens = 0;
    this.usage = {
      tokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      cost: 0,
      duration: 0,
      iterations: 0,
      toolCalls: 0,
      llmCalls: 0,
      baselineContextTokens: 0,
      cumulativeInputTokens: 0,
    };
    this.progress = {
      filesRead: new Set(),
      filesModified: new Set(),
      commandsRun: [],
      recentToolCalls: [],
      lastMeaningfulProgress: Date.now(),
      stuckCount: 0,
    };

    // Reset extracted modules (preserve tuning thresholds)
    this.loopDetector.reset(this.budget.tuning);
    this.phaseTracker.reset();

    this.startTime = Date.now();
    this.pausedDuration = 0;
    this.pauseStart = null;
    this.originalMaxIterations = null;
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
    // Delegate repetition check to loop detector
    if (this.loopDetector.isStuckByRepetition(this.progress.recentToolCalls)) {
      return true;
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
  maxTokens: 250000,        // 250k tokens -- coders need room for explore + code
  softTokenLimit: 180000,   // Warn at 180k
  maxCost: 0.75,            // Increased ceiling for heavier workloads
  maxDuration: 480000,      // 8 minutes
  softDurationLimit: 420000, // Warn at 7 minutes
  targetIterations: 30,
  maxIterations: 60,
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
 * TUI root agent budget - no time limit, high iteration cap.
 * The TUI root agent must be able to run as long as needed (swarm tasks,
 * multi-step workflows). Duration is effectively unlimited; token/cost
 * limits still apply as a safety net.
 */
export const TUI_ROOT_BUDGET: Partial<ExecutionBudget> = {
  enforcementMode: 'doomloop_only',
  maxTokens: 500000,
  softTokenLimit: 400000,
  maxCost: 5.00,
  softCostLimit: 4.00,
  maxDuration: Infinity,      // No time limit -- run as long as tasks remain
  softDurationLimit: Infinity,
  targetIterations: 100,
  maxIterations: 500,
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

/**
 * Swarm worker budget - tight constraints for small specialist models.
 * Each worker gets a small slice of the total swarm budget.
 */
export const SWARM_WORKER_BUDGET: Partial<ExecutionBudget> = {
  maxTokens: 30000,
  softTokenLimit: 25000,
  maxCost: 0.08,
  maxDuration: 180000,      // 3 minutes
  softDurationLimit: 150000, // Warn at 2.5 min
  targetIterations: 15,
  maxIterations: 25,
};

/**
 * Swarm orchestrator budget - moderate budget for decomposition and quality gates.
 */
export const SWARM_ORCHESTRATOR_BUDGET: Partial<ExecutionBudget> = {
  maxTokens: 100000,
  softTokenLimit: 80000,
  maxCost: 0.25,
  maxDuration: 300000,     // 5 minutes
  softDurationLimit: 240000,
  targetIterations: 30,
  maxIterations: 50,
};
