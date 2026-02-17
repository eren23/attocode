/**
 * Swarm Mode Types
 *
 * Type definitions for the swarm experiment mode where one orchestrator
 * coordinates multiple small specialist worker models.
 */

import type { SubtaskType, SmartSubtask } from '../tasks/smart-decomposer.js';
import type { AgentOutput, SynthesisResult } from '../agents/result-synthesizer.js';
import type { StructuredClosureReport } from '../agents/agent-registry.js';
import type { CodebaseContextManager } from '../context/codebase-context.js';
import type { ThrottleConfig } from './request-throttle.js';
import type { PolicyProfile } from '../../types.js';
import type { EconomicsTuning } from '../budget/economics.js';

// ─── Worker Roles ─────────────────────────────────────────────────────────

/** Hierarchical role for authority separation. */
export type WorkerRole = 'executor' | 'manager' | 'judge';

// ─── Worker Capability (hoisted for TaskTypeConfig) ──────────────────────

/** Capability categories for worker models */
export type WorkerCapability = 'code' | 'research' | 'review' | 'test' | 'document' | 'write';

// ─── Task Type Configuration ─────────────────────────────────────────────

/**
 * Per-task-type configuration. Everything is optional — omitted fields
 * fall back to built-in defaults or sensible fallbacks.
 */
export interface TaskTypeConfig {
  /** Timeout in ms (default: from taskTypeTimeouts or 300_000) */
  timeout?: number;
  /** Max iterations per worker (default: workerMaxIterations) */
  maxIterations?: number;
  /** Idle timeout in ms — time without tool calls before kill (default: 120_000) */
  idleTimeout?: number;
  /** Named policy profile (default: inferred from capability) */
  policyProfile?: string;
  /** Worker capability for task-worker matching (default: 'code') */
  capability?: WorkerCapability;
  /** Whether zero tool calls = hollow completion (default: true for action types) */
  requiresToolCalls?: boolean;
  /** Prompt template key: 'code' | 'research' | 'synthesis' | 'document' | custom (default: 'code') */
  promptTemplate?: string;
  /** Tool whitelist override */
  tools?: string[];
  /** Retry count override (default: workerRetries) */
  retries?: number;
  /** Token budget override per worker (default: maxTokensPerWorker) */
  tokenBudget?: number;
  /** F3: Token budget range — foundation tasks get max, leaf tasks get proportional.
   *  Falls back to tokenBudget or maxTokensPerWorker when not set. */
  tokenBudgetRange?: { min: number; max: number };
}

/**
 * Built-in task type configurations with sensible defaults.
 * Custom types that aren't in this map fall back to the 'implement' config.
 */
export const BUILTIN_TASK_TYPE_CONFIGS: Record<string, TaskTypeConfig> = {
  research:  { timeout: 300_000, capability: 'research', requiresToolCalls: false, promptTemplate: 'research', policyProfile: 'research-safe',     tokenBudgetRange: { min: 20_000, max: 80_000 } },
  analysis:  { timeout: 300_000, capability: 'research', requiresToolCalls: false, promptTemplate: 'research', policyProfile: 'research-safe',     tokenBudgetRange: { min: 20_000, max: 80_000 } },
  design:    { timeout: 300_000, capability: 'research', requiresToolCalls: false, promptTemplate: 'research', policyProfile: 'code-strict-bash',  tokenBudgetRange: { min: 20_000, max: 80_000 } },
  implement: { timeout: 300_000, capability: 'code',     requiresToolCalls: true,  promptTemplate: 'code',     policyProfile: 'code-strict-bash',  tokenBudgetRange: { min: 40_000, max: 150_000 } },
  test:      { timeout: 240_000, capability: 'test',     requiresToolCalls: true,  promptTemplate: 'code',     policyProfile: 'code-strict-bash',  tokenBudgetRange: { min: 20_000, max: 60_000 } },
  refactor:  { timeout: 240_000, capability: 'code',     requiresToolCalls: true,  promptTemplate: 'code',     policyProfile: 'code-strict-bash',  tokenBudgetRange: { min: 30_000, max: 100_000 } },
  review:    { timeout: 240_000, capability: 'review',   requiresToolCalls: false, promptTemplate: 'research', policyProfile: 'review-safe',       tokenBudgetRange: { min: 15_000, max: 50_000 } },
  document:  { timeout: 240_000, capability: 'document', requiresToolCalls: true,  promptTemplate: 'document', policyProfile: 'code-strict-bash',  tokenBudgetRange: { min: 15_000, max: 50_000 } },
  integrate: { timeout: 300_000, capability: 'code',     requiresToolCalls: true,  promptTemplate: 'code',     policyProfile: 'code-strict-bash',  tokenBudgetRange: { min: 40_000, max: 150_000 } },
  deploy:    { timeout: 240_000, capability: 'code',     requiresToolCalls: true,  promptTemplate: 'code',     policyProfile: 'code-strict-bash',  tokenBudgetRange: { min: 20_000, max: 60_000 } },
  merge:     { timeout: 180_000, capability: 'write',    requiresToolCalls: false, promptTemplate: 'synthesis', policyProfile: 'research-safe',    tokenBudgetRange: { min: 10_000, max: 30_000 } },
};

/**
 * Get the effective TaskTypeConfig for a task type, merging:
 *   user overrides (from swarmConfig.taskTypes) > built-in defaults > fallback
 */
export function getTaskTypeConfig(type: string, config?: SwarmConfig): TaskTypeConfig {
  const userConfig = config?.taskTypes?.[type] ?? {};
  const builtinConfig = BUILTIN_TASK_TYPE_CONFIGS[type] ?? {};
  const fallback = BUILTIN_TASK_TYPE_CONFIGS['implement']!;
  return { ...fallback, ...builtinConfig, ...userConfig };
}

// ─── Swarm Configuration ───────────────────────────────────────────────────

/**
 * Top-level swarm configuration.
 * Can be loaded from `.attocode/swarm.yaml` or auto-generated from CLI defaults.
 */
export interface SwarmConfig {
  /** Whether swarm mode is active */
  enabled: boolean;

  /** Model ID for the orchestrator (e.g., 'thudm/glm-4-32b') */
  orchestratorModel: string;

  /** Worker model definitions */
  workers: SwarmWorkerSpec[];

  /** Max concurrent workers (default: 5) */
  maxConcurrency: number;

  /** Total token budget across all workers (default: 2_000_000) */
  totalBudget: number;

  /** USD cost cap (default: 1.00) */
  maxCost: number;

  /** Fraction of budget reserved for orchestrator (default: 0.15) */
  orchestratorReserveRatio: number;

  /** Max tokens per individual worker (default: 20_000) */
  maxTokensPerWorker: number;

  /** Worker timeout in ms (default: 120_000) */
  workerTimeout: number;

  /** Max iterations per worker (default: 15) */
  workerMaxIterations: number;

  /** Whether to run quality gates on worker outputs (default: true) */
  qualityGates: boolean;

  /** Number of retries for failed workers (default: 1) */
  workerRetries: number;

  /** Strategy for handling file conflicts between workers */
  fileConflictStrategy: 'serialize' | 'claim-based' | 'orchestrator-merges';

  /** Delay between dispatching workers (ms) to avoid rate limits (default: 500) */
  dispatchStaggerMs: number;

  /** Request throttle: 'free' | 'paid' | ThrottleConfig | false (default: 'free') */
  throttle?: ThrottleConfig | 'free' | 'paid' | false;

  /** Base delay before re-dispatching rate-limited tasks in ms (default: 5000) */
  retryBaseDelayMs?: number;

  // ─── V2: Smart Orchestrator fields (all optional, backward-compatible) ───

  /** Whether orchestrator creates acceptance criteria per task (default: true) */
  enablePlanning?: boolean;

  /** Whether orchestrator reviews outputs after each wave (default: true) */
  enableWaveReview?: boolean;

  /** Whether to run integration checks before declaring done (default: true) */
  enableVerification?: boolean;

  /** Model for planning/review (defaults to orchestratorModel) */
  plannerModel?: string;

  /** Repeated tool calls before stuck warning (default: 3) */
  workerStuckThreshold?: number;

  /** Whether to checkpoint after each wave (default: true) */
  enablePersistence?: boolean;

  /** Directory for checkpoint files (default: '.agent/swarm-state') */
  stateDir?: string;

  /** Session ID to resume from (set by --swarm-resume) */
  resumeSessionId?: string;

  /** Tool access mode: 'whitelist' uses worker.allowedTools, 'all' gives all tools including MCP (default: 'whitelist') */
  toolAccessMode?: 'whitelist' | 'all';

  /** Tools to deny when toolAccessMode is 'all' */
  globalDeniedTools?: string[];

  /** Whether to switch models on 429/402 errors (default: true) */
  enableModelFailover?: boolean;

  /** Max verification fix-up retries (default: 2) */
  maxVerificationRetries?: number;

  /** Number of retries specifically for rate-limit (429/402) errors (default: 3) */
  rateLimitRetries?: number;

  /** Model to use for quality gates instead of orchestratorModel (default: orchestratorModel) */
  qualityGateModel?: string;

  /** Minimum quality score to pass (default: 3, range 1-5) */
  qualityThreshold?: number;

  /** F2: Enable concrete output validation (syntax checks on modified files). Default: true */
  enableConcreteValidation?: boolean;

  // ─── V3: Config, Hierarchy, Personas ────────────────────────────────────

  /** Development philosophy injected into ALL worker system prompts */
  philosophy?: string;

  /** Filter to paid models only (no free tier) */
  paidOnly?: boolean;

  /** Hierarchical authority roles (manager reviews waves, judge runs quality gates) */
  hierarchy?: {
    manager?: { model?: string; persona?: string };
    judge?: { model?: string; persona?: string };
  };

  /** Communication settings between workers */
  communication?: {
    blackboard?: boolean;
    dependencyContextMaxLength?: number;
    includeFileList?: boolean;
  };

  /** Preferred decomposition order (e.g., ['test', 'implement', 'document']) */
  decompositionPriorities?: string[];

  // ─── V4: Fact System ───────────────────────────────────────────────────

  /** Grounding facts injected into all worker and judge prompts.
   *  Auto-populated at startup; can be overridden/extended in swarm.yaml. */
  facts?: SwarmFacts;

  // ─── V6: Per-task-type timeout ──────────────────────────────────────────

  /** Per-task-type timeout overrides in ms (e.g., { research: 300000, code: 120000 }).
   *  Falls back to workerTimeout when a type is not specified.
   *  @deprecated Use taskTypes[type].timeout instead. Still works for backward compat. */
  taskTypeTimeouts?: Record<string, number>;

  /** Fraction of dependencies that must succeed for a dependent task to still run (default: 0.5).
   *  When a task's completed deps / total deps >= this threshold, the task runs with partial context
   *  instead of being cascade-skipped. Set to 1.0 for strict all-or-nothing behavior. */
  partialDependencyThreshold?: number;

  /** Staleness threshold for dispatched task leases in ms (default: 300000). */
  dispatchLeaseStaleMs?: number;

  /** Permission overrides for swarm workers (loaded from swarm.yaml permissions:) */
  permissions?: {
    /** Permission mode override for workers */
    mode?: 'auto-safe' | 'interactive' | 'strict' | 'yolo';
    /** Tools to auto-approve for all workers */
    autoApprove?: string[];
    /** Scoped approvals (tool -> { paths: string[] }) */
    scopedApprove?: Record<string, { paths: string[] }>;
    /** Tools requiring explicit approval */
    requireApproval?: string[];
    /** Additional commands to allow in sandbox */
    additionalAllowedCommands?: string[];
  };

  /** Named policy profiles for workers (overrides global defaults by name) */
  policyProfiles?: Record<string, PolicyProfile>;

  /** Additive extensions to built-in or named profiles (merge, not override) */
  profileExtensions?: Record<string, { addTools?: string[]; removeTools?: string[] }>;

  // ─── V7: Reliability & Custom Task Types ──────────────────────────────

  /** Hard cap on dispatch attempts per task, including retries (default: 5).
   *  Prevents any single task from burning budget with infinite retries. */
  maxDispatchesPerTask?: number;

  /** F25: Max consecutive timeouts per task before early-fail or model failover (default: 3).
   *  After this many consecutive timeouts, the orchestrator attempts model failover.
   *  If no alternative model is available, the task fails immediately instead of retrying. */
  consecutiveTimeoutLimit?: number;

  /** Fraction of total dispatches that are hollow before terminating (default: 0.7).
   *  Works across all models (unlike hollowStreak which only works for single-model swarms). */
  hollowTerminationRatio?: number;

  /** Minimum total dispatches before hollow ratio termination activates (default: 8). */
  hollowTerminationMinDispatches?: number;

  /** Character threshold for hollow completion detection (default: 120).
   *  Outputs shorter than this with 0 tool calls are considered hollow. */
  hollowOutputThreshold?: number;

  /** Per-task-type configuration (timeout, iterations, tools, prompt template, etc.).
   *  Keys are task type names — built-in types get defaults, custom types are first-class. */
  taskTypes?: Record<string, TaskTypeConfig>;

  /** Economics tuning overrides for all swarm workers (doom loop, exploration, zero-progress thresholds).
   *  Merged into each worker's AgentDefinition at dispatch time. */
  economicsTuning?: EconomicsTuning;

  /** Budget enforcement mode for swarm workers (default: 'doomloop_only').
   *  'doomloop_only': Only enforce doom loop detection, allow soft/hard budget overshoot with warnings.
   *  'strict': Enforce all budget limits strictly (may cause hollow completions on weak models).
   *  The swarm's own dispatch cap, timeout, and budget pool are sufficient hard stops,
   *  so workers default to 'doomloop_only' to avoid premature forceTextOnly. */
  workerEnforcementMode?: 'strict' | 'doomloop_only';

  /** D3: Whether to probe models for tool-calling capability before dispatch (default: true).
   *  Sends a cheap probe to each unique model; incapable models are marked unhealthy. */
  probeModels?: boolean;

  /** F15: When true, proceed with swarm even if all models fail capability probes.
   *  Default: false (abort swarm when zero models are healthy).
   *  @deprecated Use probeFailureStrategy: 'warn-and-try' instead. Still works for backward compat. */
  ignoreProbeFailures?: boolean;

  /** F23: Strategy when all models fail capability probes.
   *  - 'abort': Hard abort, no tasks dispatched (default for ignoreProbeFailures=false)
   *  - 'warn-and-try': Log warning, reset health, let real tasks prove/disprove capability
   *  Default: 'warn-and-try' */
  probeFailureStrategy?: 'abort' | 'warn-and-try';

  /** Timeout in ms for each model's capability probe (default: 60000).
   *  Increase for slow models or poor network conditions. */
  probeTimeoutMs?: number;

  /** Whether to check for filesystem artifacts before cascade-skipping dependent tasks (default: true).
   *  When a task "fails" but its targetFiles exist on disk with content, dependent tasks
   *  are kept ready instead of being cascade-skipped. */
  artifactAwareSkip?: boolean;

  /** If true, hollow streaks/ratio can terminate the swarm (skipRemainingTasks). Default: false.
   *  When false (default), hollow streaks enter stall mode instead of killing the swarm. */
  enableHollowTermination?: boolean;

  /** Completion safeguards to prevent "narrative success" with no concrete outcomes. */
  completionGuard?: {
    /** Require concrete filesystem artifacts for action-oriented tasks (default: true). */
    requireConcreteArtifactsForActionTasks?: boolean;
    /** Reject outputs that explicitly indicate pending future work (default: true). */
    rejectFutureIntentOutputs?: boolean;
  };

  /** Model validation behavior for malformed model IDs in config. */
  modelValidation?: {
    /** Auto-correct malformed IDs when possible, otherwise use fallback model (default: 'autocorrect'). */
    mode?: 'autocorrect' | 'strict';
    /** Warn or fail when model IDs are invalid (default: 'warn'). */
    onInvalid?: 'warn' | 'fail';
  };

  /** Codebase context manager — provides repo map for grounding decomposition in actual files */
  codebaseContext?: CodebaseContextManager;

  /** Pre-dispatch auto-split for critical-path bottleneck tasks.
   *  Proactively splits high-complexity foundation tasks before dispatch,
   *  using heuristic pre-filtering + LLM judgment. */
  autoSplit?: {
    /** Enable auto-split (default: true) */
    enabled?: boolean;
    /** Minimum complexity to consider for splitting (default: 6) */
    complexityFloor?: number;
    /** Max subtasks per split (default: 4) */
    maxSubtasks?: number;
    /** Task types eligible for splitting (default: ['implement', 'refactor', 'test']) */
    splittableTypes?: string[];
  };
}

/**
 * Grounding facts for temporal/project context.
 * Prevents workers from hallucinating dates or ignoring the real environment.
 */
export interface SwarmFacts {
  /** Current date in YYYY-MM-DD format (auto-populated from Date.now()) */
  currentDate?: string;

  /** Current year as number (auto-populated) */
  currentYear?: number;

  /** Working directory of the swarm (auto-populated from cwd) */
  workingDirectory?: string;

  /** Custom facts from swarm.yaml — free-form lines injected verbatim */
  custom?: string[];
}

/**
 * Default swarm configuration values.
 */
export const DEFAULT_SWARM_CONFIG: Omit<SwarmConfig, 'orchestratorModel' | 'workers'> = {
  enabled: true,
  maxConcurrency: 3,
  totalBudget: 5_000_000,
  maxCost: 10.00,
  orchestratorReserveRatio: 0.15,
  maxTokensPerWorker: 50_000,
  workerTimeout: 120_000,
  workerMaxIterations: 15,
  qualityGates: true,
  workerRetries: 2,
  fileConflictStrategy: 'claim-based',
  dispatchStaggerMs: 1500,
  dispatchLeaseStaleMs: 5 * 60 * 1000,
  throttle: 'free' as const,
  retryBaseDelayMs: 5000,
  enablePlanning: true,
  enableWaveReview: true,
  enableVerification: true,
  workerStuckThreshold: 3,
  enablePersistence: true,
  stateDir: '.agent/swarm-state',
  toolAccessMode: 'all' as const,
  enableModelFailover: true,
  maxVerificationRetries: 2,
  rateLimitRetries: 3,
  taskTypeTimeouts: {
    research: 300_000,      // 5 min for research (web searches take time)
    analysis: 300_000,
    design: 300_000,        // 5 min for design tasks
    merge: 180_000,         // 3 min for synthesis
    implement: 300_000,     // 5 min for implementation
    test: 240_000,          // 4 min for test writing
    refactor: 240_000,      // 4 min for refactoring
    integrate: 300_000,     // 5 min for integration
    deploy: 240_000,        // 4 min for deploy tasks
    document: 240_000,      // 4 min for documentation
    review: 240_000,        // 4 min for code review
  },
  completionGuard: {
    requireConcreteArtifactsForActionTasks: true,
    rejectFutureIntentOutputs: true,
  },
  modelValidation: {
    mode: 'autocorrect',
    onInvalid: 'warn',
  },
};

// ─── Worker Specification ──────────────────────────────────────────────────

/**
 * Definition for a swarm worker model.
 */
export interface SwarmWorkerSpec {
  /** Human-readable name (e.g., 'coder', 'researcher') */
  name: string;

  /** OpenRouter model ID (e.g., 'qwen/qwen-2.5-coder-32b-instruct') */
  model: string;

  /** Capabilities this worker is suited for */
  capabilities: WorkerCapability[];

  /** Context window size for compaction tuning */
  contextWindow?: number;

  /** Per-worker token limit override */
  maxTokens?: number;

  /** Whitelist of tools this worker can use */
  allowedTools?: string[];

  /** Blacklist of tools this worker cannot use */
  deniedTools?: string[];

  /** Per-worker behavioral instructions for system prompt */
  persona?: string;

  /** Additional tools to add to the resolved profile whitelist (merged, not override) */
  extraTools?: string[];

  /** Optional named policy profile (resolved against policyProfiles/defaults) */
  policyProfile?: string;

  /** Hierarchical role (default: 'executor') */
  role?: WorkerRole;

  /** D2: Override the prompt tier for this worker ('full' | 'reduced' | 'minimal').
   *  'minimal' is ideal for cheap/weak models — strips philosophy, delegation, quality self-assessment. */
  promptTier?: 'full' | 'reduced' | 'minimal';
}

// ─── Swarm Task ────────────────────────────────────────────────────────────

/** P6: Categorizes how a task failed, for failure-mode-aware cascade thresholds. */
export type TaskFailureMode = 'timeout' | 'rate-limit' | 'error' | 'quality' | 'hollow' | 'cascade';

/** Status of a swarm task */
export type SwarmTaskStatus = 'pending' | 'ready' | 'dispatched' | 'completed' | 'failed' | 'skipped' | 'decomposed';

/**
 * A task within the swarm execution pipeline.
 * Maps from SmartSubtask with added swarm-specific fields.
 */
export interface SwarmTask {
  /** Unique task ID (from SmartSubtask.id) */
  id: string;

  /** Task description */
  description: string;

  /** Task type from SmartDecomposer */
  type: SubtaskType;

  /** IDs of tasks this depends on */
  dependencies: string[];

  /** Current status */
  status: SwarmTaskStatus;

  /** Complexity rating 1-10 */
  complexity: number;

  /** Wave number (computed from parallelGroups) */
  wave: number;

  /** Files this task may modify */
  targetFiles?: string[];

  /** Files this task needs to read */
  readFiles?: string[];

  /** Model assigned to execute this task */
  assignedModel?: string;

  /** Result after execution */
  result?: SwarmTaskResult;

  /** Number of execution attempts */
  attempts: number;

  /** Earliest timestamp when this task can be re-dispatched (non-blocking cooldown) */
  retryAfter?: number;

  /** Timestamp when the task entered dispatched state */
  dispatchedAt?: number;

  /** Aggregated outputs from completed dependencies */
  dependencyContext?: string;

  /** Context from previous failed attempt (quality rejection or error) for retry prompts */
  retryContext?: { previousFeedback: string; previousScore: number; attempt: number; previousModel?: string; previousFiles?: string[]; swarmProgress?: string };

  /** Partial dependency context when some deps failed but threshold met.
   *  Lists which deps succeeded and which failed so the worker can adapt. */
  partialContext?: { succeeded: string[]; failed: string[]; ratio: number };

  /** Whether this is a foundation task (sole dependency of 3+ downstream tasks).
   *  Foundation tasks get extra retries, relaxed quality gates, and timeout scaling. */
  isFoundation?: boolean;

  /** Number of tools available to the worker (-1 = all tools) */
  toolCount?: number;

  /** List of tool names available to the worker */
  tools?: string[];

  /** Original SmartSubtask for reference */
  originalSubtask?: SmartSubtask;

  /** P6: How this task failed (used for failure-mode-aware cascade thresholds) */
  failureMode?: TaskFailureMode;

  /** F4: Set when a dependency fails while this task is dispatched.
   *  Instead of immediately skipping, the task's result is evaluated first.
   *  Good results are kept; hollow/garbage results honor the cascade skip. */
  pendingCascadeSkip?: boolean;

  /** Whether this task was accepted with degraded quality (partial work exists on disk
   *  but quality gate failed or hollow completion detected). Dependents get a warning. */
  degraded?: boolean;

  /** Context explaining why a cascade-skipped task was rescued and allowed to run. */
  rescueContext?: string;

  /** ID of the parent task that was micro-decomposed into this subtask. */
  parentTaskId?: string;

  /** IDs of subtasks created when this task was micro-decomposed. */
  subtaskIds?: string[];
}

/**
 * Result of a completed swarm task.
 */
export interface SwarmTaskResult {
  /** Whether the task succeeded */
  success: boolean;

  /** Output content from the worker */
  output: string;

  /** Structured closure report from the worker (if available) */
  closureReport?: StructuredClosureReport;

  /** Quality gate score (1-5, if quality gates enabled) */
  qualityScore?: number;

  /** Quality gate feedback */
  qualityFeedback?: string;

  /** Token usage */
  tokensUsed: number;

  /** Cost in USD */
  costUsed: number;

  /** Duration in ms */
  durationMs: number;

  /** Files modified by this worker */
  filesModified?: string[];

  /** Findings posted to blackboard */
  findings?: string[];

  /** Number of tool calls made by the worker */
  toolCalls?: number;

  /** Model that executed this task */
  model: string;

  /** Whether this result was accepted with degraded quality (partial work, not full pass). */
  degraded?: boolean;

  /** Per-worker budget utilization from WorkerBudgetTracker (orchestrator-side tracking). */
  budgetUtilization?: { tokenPercent: number; iterationPercent: number };
}

// ─── Artifact Inventory ─────────────────────────────────────────────────────

/** A single file artifact discovered on disk after swarm execution. */
export interface ArtifactEntry {
  /** Relative file path (as declared in task targetFiles/readFiles) */
  path: string;
  /** File size in bytes */
  sizeBytes: number;
  /** Whether the file exists on disk */
  exists: true;
}

/** Inventory of filesystem artifacts produced during swarm execution. */
export interface ArtifactInventory {
  /** Files found on disk with non-zero content */
  files: ArtifactEntry[];
  /** Total number of artifact files */
  totalFiles: number;
  /** Total size in bytes */
  totalBytes: number;
}

// ─── Swarm Execution ───────────────────────────────────────────────────────

/**
 * Overall result of a swarm execution.
 */
export interface SwarmExecutionResult {
  /** Whether the swarm produced usable output (at least one task completed) */
  success: boolean;

  /** Whether no tasks completed but filesystem artifacts exist (workers produced files despite failing quality/timeout) */
  partialSuccess?: boolean;

  /** Whether some tasks failed despite overall success (partial results) */
  partialFailure?: boolean;

  /** Synthesized output from all workers */
  synthesisResult?: SynthesisResult;

  /** Filesystem artifacts found on disk after execution (files created by workers regardless of task status) */
  artifactInventory?: ArtifactInventory;

  /** Summary of what was accomplished */
  summary: string;

  /** All task results */
  tasks: SwarmTask[];

  /** Execution statistics */
  stats: SwarmExecutionStats;

  /** Errors encountered */
  errors: SwarmError[];
}

/**
 * Statistics from a swarm execution.
 */
export interface SwarmExecutionStats {
  /** Total number of tasks */
  totalTasks: number;

  /** Number of completed tasks */
  completedTasks: number;

  /** Number of failed tasks */
  failedTasks: number;

  /** Number of skipped tasks (due to dependency failures) */
  skippedTasks: number;

  /** Total waves executed */
  totalWaves: number;

  /** Total tokens consumed across all workers */
  totalTokens: number;

  /** Total cost in USD */
  totalCost: number;

  /** Wall-clock duration in ms */
  totalDurationMs: number;

  /** Number of quality gate rejections */
  qualityRejections: number;

  /** Number of retries */
  retries: number;

  /** Workers by model */
  modelUsage: Map<string, { tasks: number; tokens: number; cost: number }>;

  /** Usage breakdown by role */
  roleUsage?: Map<WorkerRole, { calls: number; tokens: number; cost: number }>;
}

/**
 * Swarm error with context.
 */
export interface SwarmError {
  /** Task ID that caused the error (if applicable) */
  taskId?: string;

  /** Phase where error occurred */
  phase: 'decomposition' | 'scheduling' | 'dispatch' | 'execution' | 'quality-gate' | 'synthesis' | 'planning' | 'review' | 'verification' | 'persistence';

  /** Error message */
  message: string;

  /** Whether this error was recovered from */
  recovered: boolean;
}

// ─── Swarm Status (for TUI) ───────────────────────────────────────────────

/**
 * Live status of swarm execution for TUI display.
 */
export interface SwarmStatus {
  /** Current phase */
  phase: 'decomposing' | 'scheduling' | 'executing' | 'synthesizing' | 'completed' | 'failed' | 'planning' | 'reviewing' | 'verifying';

  /** Current wave number (1-indexed) */
  currentWave: number;

  /** Total waves */
  totalWaves: number;

  /** Active workers */
  activeWorkers: SwarmWorkerStatus[];

  /** Task queue stats */
  queue: {
    ready: number;
    running: number;
    completed: number;
    failed: number;
    skipped: number;
    total: number;
  };

  /** Budget status */
  budget: {
    tokensUsed: number;
    tokensTotal: number;
    costUsed: number;
    costTotal: number;
  };

  /** Orchestrator's own LLM usage (separate from worker usage) */
  orchestrator?: {
    tokens: number;
    cost: number;
    calls: number;
    model: string;
  };
}

/**
 * Status of an individual active worker.
 */
export interface SwarmWorkerStatus {
  /** Task ID being worked on */
  taskId: string;

  /** Task description */
  taskDescription: string;

  /** Model being used */
  model: string;

  /** Worker name (e.g., 'coder', 'researcher') */
  workerName: string;

  /** Time running in ms */
  elapsedMs: number;

  /** Start time */
  startedAt: number;

  /** Worker role in the hierarchy */
  role?: WorkerRole;
}

// ─── V2: Planning & Verification Types ────────────────────────────────────

/** Acceptance criteria for a single task, set by the orchestrator's planning phase. */
export interface TaskAcceptanceCriteria {
  taskId: string;
  criteria: string[];
}

/** A verification step (bash command) to run during integration checks. */
export interface VerificationStep {
  description: string;
  command: string;
  expectedResult?: string;
  required: boolean;
}

/** Plan for integration testing after all waves complete. */
export interface IntegrationTestPlan {
  description: string;
  steps: VerificationStep[];
  successCriteria: string;
}

/** Orchestrator's execution plan created during the planning phase. */
export interface SwarmPlan {
  acceptanceCriteria: TaskAcceptanceCriteria[];
  integrationTestPlan?: IntegrationTestPlan;
  reasoning: string;
}

/** Result of running verification steps. */
export interface VerificationResult {
  passed: boolean;
  stepResults: Array<{
    step: VerificationStep;
    passed: boolean;
    output: string;
  }>;
  summary: string;
}

/** Orchestrator's assessment after reviewing a completed wave. */
export interface WaveReviewResult {
  wave: number;
  assessment: 'good' | 'needs-fixes' | 'critical-issues';
  taskAssessments: Array<{
    taskId: string;
    passed: boolean;
    feedback?: string;
  }>;
  fixupTasks: FixupTask[];
}

/** A correction task spawned by wave review. */
export interface FixupTask extends SwarmTask {
  /** The original task this fixes */
  fixesTaskId: string;
  /** Specific fix instructions from the reviewer */
  fixInstructions: string;
}

/** Per-model health tracking for failover decisions. */
export interface ModelHealthRecord {
  model: string;
  successes: number;
  failures: number;
  rateLimits: number;
  lastRateLimit?: number;
  averageLatencyMs: number;
  healthy: boolean;
  qualityRejections?: number;
  /** Success rate (0.0-1.0) computed from successes/(successes+failures) */
  successRate?: number;
}

/** Serializable swarm state for persistence/resume. */
export interface SwarmCheckpoint {
  sessionId: string;
  timestamp: number;
  phase: SwarmStatus['phase'];
  plan?: SwarmPlan;
  taskStates: Array<{
    id: string;
    status: SwarmTaskStatus;
    result?: SwarmTaskResult;
    attempts: number;
    wave: number;
    assignedModel?: string;
    dispatchedAt?: number;
    // Full task data for resume (without these, restoreFromCheckpoint cannot recreate tasks)
    description?: string;
    type?: string;
    complexity?: number;
    dependencies?: string[];
    relevantFiles?: string[];
    isFoundation?: boolean;
  }>;
  waves: string[][];
  currentWave: number;
  stats: { totalTokens: number; totalCost: number; qualityRejections: number; retries: number };
  modelHealth: ModelHealthRecord[];
  decisions: OrchestratorDecision[];
  errors: SwarmError[];
  /** Original task prompt for re-planning on resume */
  originalPrompt?: string;
  /** Cross-worker failure learning state (Phase 3.1) */
  sharedContext?: { failures: unknown[]; references: [string, unknown][]; staticPrefix: string };
  /** Cross-worker doom loop aggregation state (Phase 3.2) */
  sharedEconomics?: { fingerprints: Array<{ fingerprint: string; count: number; workers: string[] }> };
}

/** Logged orchestrator decision with reasoning. */
export interface OrchestratorDecision {
  timestamp: number;
  phase: string;
  decision: string;
  reasoning: string;
}

/** Worker tool call/response log entry for per-worker conversation tracking. */
export interface WorkerConversationEntry {
  taskId: string;
  timestamp: number;
  type: 'tool_call' | 'tool_result' | 'llm_response';
  content: string;
}

// ─── Utility Types ─────────────────────────────────────────────────────────

/**
 * Maps known SubtaskTypes to WorkerCapability for task-worker matching.
 * Custom types not in this map use getTaskTypeConfig() for capability lookup.
 */
export const SUBTASK_TO_CAPABILITY: Record<string, WorkerCapability> = {
  research: 'research',
  analysis: 'research',
  design: 'research',
  implement: 'code',
  test: 'test',
  refactor: 'code',
  review: 'review',
  document: 'document',
  integrate: 'code',
  deploy: 'code',
  merge: 'write',
};

/**
 * Convert a SmartSubtask to a SwarmTask.
 */
export function subtaskToSwarmTask(subtask: SmartSubtask, wave: number): SwarmTask {
  return {
    id: subtask.id,
    description: subtask.description,
    type: subtask.type,
    dependencies: subtask.dependencies,
    status: subtask.dependencies.length === 0 ? 'ready' : 'pending',
    complexity: subtask.complexity,
    wave,
    targetFiles: subtask.modifies,
    readFiles: subtask.reads,
    attempts: 0,
    originalSubtask: subtask,
  };
}

/**
 * Convert a SwarmTaskResult to an AgentOutput for ResultSynthesizer.
 */
/**
 * Map a WorkerCapability to the AgentOutput 'type' field.
 * Uses configurable task type config instead of hardcoded type lists.
 */
function capabilityToOutputType(capability: WorkerCapability): 'code' | 'research' | 'review' | 'documentation' | 'mixed' {
  switch (capability) {
    case 'code':
    case 'test':
      return 'code';
    case 'research':
      return 'research';
    case 'review':
      return 'review';
    case 'document':
      return 'documentation';
    case 'write':
    default:
      return 'mixed';
  }
}

export function taskResultToAgentOutput(task: SwarmTask, swarmConfig?: SwarmConfig): AgentOutput | null {
  if (!task.result || !task.result.success) return null;

  const typeConfig = getTaskTypeConfig(task.type, swarmConfig);
  const outputType = capabilityToOutputType(typeConfig.capability ?? 'code');

  return {
    agentId: `swarm-worker-${task.id}`,
    content: task.result.output,
    type: outputType,
    confidence: task.result.qualityScore ? task.result.qualityScore / 5 : 0.7,
    findings: task.result.findings,
    metadata: {
      taskId: task.id,
      model: task.result.model,
      tokensUsed: task.result.tokensUsed,
      wave: task.wave,
    },
  };
}
