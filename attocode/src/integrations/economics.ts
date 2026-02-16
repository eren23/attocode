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
import type { SharedEconomicsState } from '../shared/shared-economics-state.js';

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

/**
 * Doom loop prompt - injected when same tool called repeatedly.
 */
const DOOM_LOOP_PROMPT = (tool: string, count: number) =>
`[System] You've called ${tool} with the same arguments ${count} times. This indicates a stuck state. Either:
1. Try a DIFFERENT approach or tool
2. If blocked, explain what's preventing progress
3. If the task is complete, say so explicitly`;

/**
 * Global doom loop prompt - injected when the same tool call is repeated across multiple workers.
 */
const GLOBAL_DOOM_LOOP_PROMPT = (tool: string, workerCount: number, totalCalls: number) =>
  `[System] GLOBAL DOOM LOOP: ${totalCalls} calls to ${tool} across ${workerCount} workers. The entire swarm is stuck on this approach.
1. Try a fundamentally different strategy
2. Do NOT retry the same tool/parameters
3. Consider whether the task goal itself needs re-evaluation`;

/**
 * Exploration saturation prompt - gentle nudge to start making edits.
 */
const EXPLORATION_NUDGE_PROMPT = (filesRead: number, iterations: number) =>
`[System] You've read ${filesRead} files across ${iterations} iterations. If you understand the issue:
- Make the code changes now
- Run tests to verify
If you're still gathering context, briefly explain what you're looking for.`;

/**
 * Test-fix rethink prompt - injected after consecutive test failures.
 */
const TEST_FIX_RETHINK_PROMPT = (failures: number) =>
`[System] You've had ${failures} consecutive test failures. Step back and rethink:
1. Re-read the error messages carefully
2. Consider whether your approach is fundamentally wrong
3. Try a DIFFERENT fix strategy instead of iterating on the same one
Do not retry the same fix. Try a new approach.`;

/**
 * Phase budget exploration exceeded prompt.
 */
/** Detect bash commands that are doing file write operations (write/append/redirect/heredoc). */
const BASH_FILE_WRITE_RE = /^\s*(cat|echo|printf)\b.*(?:>>?|<<)\s*/;

/** Check whether a bash command is attempting file operations that should use dedicated tools. */
function isBashFileOperation(command: string): boolean {
  return BASH_FILE_READ_RE.test(command) || BASH_FILE_WRITE_RE.test(command) || /heredoc|EOF/i.test(command);
}

const BASH_FAILURE_CASCADE_PROMPT = (failures: number, lastCommand?: string) => {
  const isFileOp = lastCommand && isBashFileOperation(lastCommand);
  if (isFileOp) {
    return `[System] ${failures} consecutive bash commands have failed trying to do file operations.
STOP using bash for file operations. Use the correct tool:
- To CREATE a file: write_file (not cat/echo with redirect)
- To MODIFY a file: edit_file (not sed/awk)
- To READ a file: read_file (not cat/head/tail)
Switch to the correct tool NOW.`;
  }
  return `[System] ${failures} consecutive bash commands have failed. STOP and:
1. Explain what you're trying to accomplish
2. Try a DIFFERENT approach or tool
3. Do not run another bash command with the same pattern`;
};

const SUMMARY_LOOP_PROMPT =
`[System] You've produced text-only responses without using tools. You should be DOING work, not summarizing it.
Pick the most important remaining task and start working on it NOW using your tools (write_file, edit_file, bash, etc.).
Do NOT output another status summary or task list.`;

const EXPLORATION_BUDGET_EXCEEDED_PROMPT = (pct: number) =>
`[System] You've spent ${pct}% of your iterations in exploration. Start making edits NOW.
Do not read more files. Use what you know to make the fix.`;

/**
 * Phase budget verification reserve prompt.
 */
const VERIFICATION_RESERVE_PROMPT =
`[System] You are running low on iterations. Run your tests NOW to verify your changes.
Do not make more edits until you've confirmed whether the current fix works.`;

const BUDGET_ADVISORY_PROMPT = (reason: string) =>
`[System] Budget advisory (${reason}) detected. Continue execution and focus on concrete tool actions to complete the task.`;

/**
 * Extract success and output from a bash tool result.
 * In production, bash results are objects `{ success, output, metadata }`.
 * Tests may pass strings directly. This normalizes both.
 */
export function extractBashResult(result: unknown): { success: boolean; output: string } {
  if (result && typeof result === 'object') {
    const obj = result as Record<string, unknown>;
    return {
      success: obj.success !== false,
      output: typeof obj.output === 'string' ? obj.output : '',
    };
  }
  if (typeof result === 'string') {
    return { success: true, output: result };
  }
  return { success: true, output: '' };
}

/**
 * Regex for common bash file-read commands (simple, no pipes/redirects).
 * Captures the file path for normalized doom loop fingerprinting.
 */
const BASH_FILE_READ_RE = /^\s*(cat|head|tail|wc|less|more|file|stat|md5sum|sha256sum)\b(?:\s+-[^\s]+)*\s+((?:\/|\.\/|\.\.\/)[\w.\/\-@]+|[\w.\-@][\w.\/\-@]*)\s*$/;

/**
 * Extract the file target from a simple bash file-read command.
 * Returns null for complex commands (pipes, redirects, non-file-read commands).
 * Used to normalize doom loop fingerprints across cat/head/tail/wc targeting the same file.
 */
export function extractBashFileTarget(command: string): string | null {
  if (/[|;&<>]/.test(command)) return null; // pipes/redirects = complex, skip
  const match = command.match(BASH_FILE_READ_RE);
  return match ? match[2] : null;
}

/**
 * Primary argument keys that identify the *target* of a tool call.
 * Used for fuzzy doom loop detection — ignoring secondary/optional args.
 */
const PRIMARY_KEYS = ['path', 'file_path', 'command', 'pattern', 'query', 'url', 'content', 'filename'];

/**
 * Compute a structural fingerprint for a tool call.
 * Extracts only the primary argument (path, command, pattern, query) and ignores
 * secondary arguments (encoding, timeout, flags). This catches near-identical calls
 * that differ only in optional parameters.
 */
export function computeToolFingerprint(toolName: string, argsStr: string): string {
  try {
    const args = JSON.parse(argsStr || '{}') as Record<string, unknown>;

    // W1: Normalize bash file-read commands so cat/head/tail/wc targeting the same file
    // produce the same fingerprint, triggering doom loop detection.
    if (toolName === 'bash' && typeof args.command === 'string') {
      const fileTarget = extractBashFileTarget(args.command);
      if (fileTarget) return `bash:file_read:${fileTarget}`;
    }

    const primaryArgs: Record<string, unknown> = {};
    for (const key of PRIMARY_KEYS) {
      if (key in args) {
        primaryArgs[key] = args[key];
      }
    }

    // If no primary keys found, fall back to full args
    if (Object.keys(primaryArgs).length === 0) {
      return `${toolName}:${stableStringify(args)}`;
    }

    return `${toolName}:${stableStringify(primaryArgs)}`;
  } catch {
    // If args can't be parsed, use raw string
    return `${toolName}:${argsStr}`;
  }
}

/**
 * ExecutionEconomicsManager handles budget tracking and progress detection.
 */
export class ExecutionEconomicsManager {
  private budget: ExecutionBudget;
  private usage: ExecutionUsage;
  private progress: ProgressState;
  private loopState: LoopDetectionState;
  private phaseState: PhaseState;
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
    };

    this.progress = {
      filesRead: new Set(),
      filesModified: new Set(),
      commandsRun: [],
      recentToolCalls: [],
      lastMeaningfulProgress: Date.now(),
      stuckCount: 0,
    };

    // Initialize doom loop detection state (thresholds configurable via tuning)
    this.loopState = {
      doomLoopDetected: false,
      lastTool: null,
      consecutiveCount: 0,
      threshold: tuning?.doomLoopThreshold ?? 3,
      fuzzyThreshold: tuning?.doomLoopFuzzyThreshold ?? (tuning?.doomLoopThreshold ? tuning.doomLoopThreshold + 1 : 4),
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
      lastTestPassed: null,
      consecutiveTestFailures: 0,
      inTestFixCycle: false,
      consecutiveBashFailures: 0,
      consecutiveTextOnlyTurns: 0,
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
   * Configure phase-aware budget allocation.
   * Only active when enabled=true (eval mode). TUI mode leaves it off.
   */
  setPhaseBudget(config: PhaseBudgetConfig): void {
    this.phaseBudget = config;
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
   * Record a text-only turn (LLM response with no tool calls).
   * Increments the consecutive text-only turn counter for summary-loop detection.
   */
  recordTextOnlyTurn(): void {
    this.phaseState.consecutiveTextOnlyTurns++;
  }

  /**
   * Record a tool call for progress tracking and loop detection.
   */
  recordToolCall(toolName: string, args: Record<string, unknown>, _result?: unknown): void {
    this.usage.toolCalls++;
    this.usage.iterations++;

    // Any tool call resets the text-only turn counter
    this.phaseState.consecutiveTextOnlyTurns = 0;

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

    // Report to shared economics for cross-worker doom loop aggregation
    if (this.sharedEconomics) {
      const fingerprint = computeToolFingerprint(toolName, argsStr);
      this.sharedEconomics.recordToolCall(this.workerId, fingerprint);
    }

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

      // Extract result from bash tool output (object or string)
      const bashResult = extractBashResult(_result);

      // Track consecutive bash failures (any bash command, not just tests)
      if (_result !== undefined) {
        if (!bashResult.success) {
          this.phaseState.consecutiveBashFailures++;
        } else {
          this.phaseState.consecutiveBashFailures = 0;
        }
      }

      // Detect test runs and track outcomes
      if (command.includes('test') || command.includes('pytest') || command.includes('npm test') || command.includes('jest')) {
        this.phaseState.testsRun++;
        // Transition to verifying phase when tests are run after edits
        if (this.phaseState.phase === 'acting' && this.phaseState.filesModified.size > 0) {
          this.transitionPhase('verifying', 'Tests run after edits');
        }

        // Fix: extract output from result object, not treat as string
        if (bashResult.output) {
          this.parseTestOutcome(command, bashResult.output);
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
   * Uses two-tier detection:
   * 1. Exact match: same tool+args string (threshold: 3)
   * 2. Fuzzy match: same tool + same primary args, ignoring optional params (threshold: 4)
   */
  private updateDoomLoopState(toolName: string, argsStr: string): void {
    const currentCall = `${toolName}:${argsStr}`;
    const recentCalls = this.progress.recentToolCalls;

    // === EXACT MATCH: Count consecutive identical calls from the end ===
    let consecutiveCount = 0;
    for (let i = recentCalls.length - 1; i >= 0; i--) {
      const call = recentCalls[i];
      if (`${call.tool}:${call.args}` === currentCall) {
        consecutiveCount++;
      } else {
        break;
      }
    }

    // === FUZZY MATCH: Catches near-identical calls that differ only in optional params ===
    // Only check if exact match didn't already trigger
    if (consecutiveCount < this.loopState.threshold) {
      const currentFingerprint = computeToolFingerprint(toolName, argsStr);
      let fuzzyCount = 0;
      for (let i = recentCalls.length - 1; i >= 0; i--) {
        const call = recentCalls[i];
        const callFingerprint = computeToolFingerprint(call.tool, call.args);
        if (callFingerprint === currentFingerprint) {
          fuzzyCount++;
        } else {
          break;
        }
      }
      // Use fuzzy count if it exceeds the fuzzy threshold
      if (fuzzyCount >= this.loopState.fuzzyThreshold) {
        consecutiveCount = Math.max(consecutiveCount, fuzzyCount);
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

    // After N+ unique files without edits, suggest transition (configurable, default: 10)
    const fileThreshold = this.budget.tuning?.explorationFileThreshold ?? 10;
    if (uniqueFilesRead.size >= fileThreshold && filesModified.size === 0) {
      this.phaseState.shouldTransition = true;
      this.emit({
        type: 'exploration.saturation',
        filesRead: uniqueFilesRead.size,
        iterations: iterationsInPhase,
      });
      return;
    }

    // After N+ iterations in exploration with diminishing returns (configurable, default: 15)
    const iterThreshold = this.budget.tuning?.explorationIterThreshold ?? 15;
    if (iterationsInPhase >= iterThreshold && recentNewFiles < 2 && filesModified.size === 0) {
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
    const strictBudgetEnforcement = (this.budget.enforcementMode ?? 'strict') === 'strict';

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
      };
    }

    // Max iterations reached — allow exactly ONE more turn for summary, then terminate.
    // First time at maxIterations: canContinue=true + forceTextOnly for a clean summary.
    // Beyond maxIterations: canContinue=false to stop the loop.
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
      };
    }

    // =========================================================================
    // ZERO PROGRESS DETECTION — nudge workers making no tool calls (D1)
    // Raised threshold to 10 (from 5) to give agents more time to plan.
    // No longer forces text-only — instead injects a strong nudge while
    // still allowing tool calls so the agent can recover.
    // =========================================================================
    const zeroProgressThreshold = this.budget.tuning?.zeroProgressThreshold ?? 10;
    if (this.usage.iterations >= zeroProgressThreshold && this.usage.toolCalls === 0) {
      // Only force text-only after 2x the threshold (complete stall)
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
    // ADAPTIVE ITERATION BUDGET — reversible reduction at checkpoint (D4)
    // Stores original maxIterations so it can be restored if tools resume.
    // =========================================================================
    const checkpoint = this.budget.tuning?.progressCheckpoint ?? 10;
    if (this.usage.iterations === checkpoint && this.usage.toolCalls === 0) {
      if (!this.originalMaxIterations) {
        this.originalMaxIterations = this.budget.maxIterations;
      }
      const reducedMax = checkpoint + 5; // give 5 more iterations (up from 3)
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

    // =========================================================================
    // TEST-FIX CYCLE - Nudge to rethink after 3+ consecutive failures
    // =========================================================================
    if (this.phaseState.consecutiveTestFailures >= 3) {
      return {
        canContinue: true,
        reason: `${this.phaseState.consecutiveTestFailures} consecutive test failures`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: TEST_FIX_RETHINK_PROMPT(this.phaseState.consecutiveTestFailures),
      };
    }

    // =========================================================================
    // BASH FAILURE CASCADE - Strong intervention after 3+ consecutive failures
    // =========================================================================
    if (this.phaseState.consecutiveBashFailures >= 3) {
      // Extract last bash command for tool-aware remediation
      let lastBashCommand: string | undefined;
      for (let i = this.progress.recentToolCalls.length - 1; i >= 0; i--) {
        if (this.progress.recentToolCalls[i].tool === 'bash') {
          try {
            const parsed = JSON.parse(this.progress.recentToolCalls[i].args);
            lastBashCommand = parsed.command;
          } catch { /* ignore parse errors */ }
          break;
        }
      }
      return {
        canContinue: true,
        reason: `${this.phaseState.consecutiveBashFailures} consecutive bash failures`,
        budgetType: 'iterations',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed: (this.usage.iterations / this.budget.targetIterations) * 100,
        suggestedAction: 'warn',
        injectedPrompt: BASH_FAILURE_CASCADE_PROMPT(this.phaseState.consecutiveBashFailures, lastBashCommand),
      };
    }

    // =========================================================================
    // SUMMARY LOOP DETECTION - Nudge after 2+ consecutive text-only turns
    // Skip when close to budget limit — the agent can't "start working" if
    // forceTextOnly would be set on the next check (contradictory nudge).
    // =========================================================================
    if (this.phaseState.consecutiveTextOnlyTurns >= 2) {
      const nearBudgetLimit = this.usage.iterations >= this.budget.maxIterations - 1;
      if (!nearBudgetLimit) {
        return {
          canContinue: true,
          reason: `${this.phaseState.consecutiveTextOnlyTurns} consecutive text-only turns (summary loop)`,
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
      const explorationPct = this.phaseState.phase === 'exploring'
        ? (this.phaseState.iterationsInPhase / this.budget.maxIterations) * 100
        : 0;

      // Too much time in exploration
      if (explorationPct > this.phaseBudget.maxExplorationPercent && this.phaseState.filesModified.size === 0) {
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
          && this.phaseState.phase !== 'verifying'
          && this.phaseState.filesModified.size > 0
          && this.phaseState.testsRun === 0) {
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
    // Two-tier approach: 67-79% = warning, 80%+ = forceTextOnly to prevent overshoot
    if (this.usage.tokens >= this.budget.softTokenLimit) {
      const remaining = this.budget.maxTokens - this.usage.tokens;
      const percentUsed = Math.round((this.usage.tokens / this.budget.maxTokens) * 100);
      this.emit({ type: 'budget.warning', budgetType: 'tokens', percentUsed, remaining });

      // If 80%+ used, force text-only to prevent overshoot past hard limit
      const forceTextOnly = percentUsed >= 80;

      return {
        canContinue: true,
        reason: `Token budget at ${percentUsed}%`,
        budgetType: 'tokens',
        isHardLimit: false,
        isSoftLimit: true,
        percentUsed,
        suggestedAction: forceTextOnly ? 'stop' : 'request_extension',
        forceTextOnly,
        injectedPrompt: forceTextOnly
          ? `⚠️ **BUDGET CRITICAL**: ${percentUsed}% used (${this.usage.tokens.toLocaleString()}/${this.budget.maxTokens.toLocaleString()}). ` +
            `WRAP UP IMMEDIATELY. Return a concise summary. Do NOT call any tools.`
          : `⚠️ **BUDGET WARNING**: You have used ${percentUsed}% of your token budget (${this.usage.tokens.toLocaleString()}/${this.budget.maxTokens.toLocaleString()} tokens). ` +
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
    const remainingSec = budget.maxDuration === Infinity
      ? Infinity
      : Math.max(0, Math.round((budget.maxDuration - usage.duration) / 1000));

    // Determine urgency level
    let urgency = '';
    if (tokenPct >= 90) {
      urgency = '⚠️ CRITICAL: ';
    } else if (tokenPct >= 70) {
      urgency = '⚡ WARNING: ';
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
    lastTestPassed: boolean | null;
    consecutiveTestFailures: number;
    inTestFixCycle: boolean;
    consecutiveBashFailures: number;
  } {
    return {
      phase: this.phaseState.phase,
      uniqueFilesRead: this.phaseState.uniqueFilesRead.size,
      uniqueSearches: this.phaseState.uniqueSearches.size,
      filesModified: this.phaseState.filesModified.size,
      testsRun: this.phaseState.testsRun,
      shouldTransition: this.phaseState.shouldTransition,
      iterationsInPhase: this.phaseState.iterationsInPhase,
      lastTestPassed: this.phaseState.lastTestPassed,
      consecutiveTestFailures: this.phaseState.consecutiveTestFailures,
      inTestFixCycle: this.phaseState.inTestFixCycle,
      consecutiveBashFailures: this.phaseState.consecutiveBashFailures,
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

    // Reset loop detection state (preserve tuning thresholds)
    const tuning = this.budget.tuning;
    this.loopState = {
      doomLoopDetected: false,
      lastTool: null,
      consecutiveCount: 0,
      threshold: tuning?.doomLoopThreshold ?? 3,
      fuzzyThreshold: tuning?.doomLoopFuzzyThreshold ?? (tuning?.doomLoopThreshold ? tuning.doomLoopThreshold + 1 : 4),
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
      lastTestPassed: null,
      consecutiveTestFailures: 0,
      inTestFixCycle: false,
      consecutiveBashFailures: 0,
      consecutiveTextOnlyTurns: 0,
    };

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

  /**
   * Parse test outcome from bash command output.
   * Updates phaseState test tracking fields.
   */
  private parseTestOutcome(_command: string, output: string): void {
    if (!output) return;

    // Detect pass/fail from pytest-style output
    const hasPassed = /(\d+)\s+passed/.test(output) || output.includes('PASSED');
    const hasFailed = /(\d+)\s+failed/.test(output) || output.includes('FAILED') || output.includes('ERROR');

    if (hasFailed && !hasPassed) {
      // Pure failure
      this.phaseState.lastTestPassed = false;
      this.phaseState.consecutiveTestFailures++;
      this.phaseState.inTestFixCycle = true;
    } else if (hasPassed && !hasFailed) {
      // Pure pass
      this.phaseState.lastTestPassed = true;
      this.phaseState.consecutiveTestFailures = 0;
      this.phaseState.inTestFixCycle = false;
    } else if (hasPassed && hasFailed) {
      // Mixed - some passed, some failed
      this.phaseState.lastTestPassed = false;
      this.phaseState.consecutiveTestFailures++;
      this.phaseState.inTestFixCycle = true;
    }
    // If no clear signal, don't update
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
  maxTokens: 250000,        // 250k tokens — coders need room for explore + code
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
  maxDuration: Infinity,      // No time limit — run as long as tasks remain
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
