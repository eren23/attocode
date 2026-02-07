/**
 * Swarm Mode Types
 *
 * Type definitions for the swarm experiment mode where one orchestrator
 * coordinates multiple small specialist worker models.
 */

import type { SubtaskType, SmartSubtask } from '../smart-decomposer.js';
import type { AgentOutput, SynthesisResult } from '../result-synthesizer.js';
import type { StructuredClosureReport } from '../agent-registry.js';
import type { ThrottleConfig } from './request-throttle.js';

// ─── Worker Roles ─────────────────────────────────────────────────────────

/** Hierarchical role for authority separation. */
export type WorkerRole = 'executor' | 'manager' | 'judge';

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

  /** Tool access mode: 'whitelist' uses worker.allowedTools, 'all' gives all tools including MCP (default: 'all') */
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
};

// ─── Worker Specification ──────────────────────────────────────────────────

/** Capability categories for worker models */
export type WorkerCapability = 'code' | 'research' | 'review' | 'test' | 'document';

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

  /** Hierarchical role (default: 'executor') */
  role?: WorkerRole;
}

// ─── Swarm Task ────────────────────────────────────────────────────────────

/** Status of a swarm task */
export type SwarmTaskStatus = 'pending' | 'ready' | 'dispatched' | 'completed' | 'failed' | 'skipped';

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

  /** Aggregated outputs from completed dependencies */
  dependencyContext?: string;

  /** Original SmartSubtask for reference */
  originalSubtask?: SmartSubtask;
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

  /** Model that executed this task */
  model: string;
}

// ─── Swarm Execution ───────────────────────────────────────────────────────

/**
 * Overall result of a swarm execution.
 */
export interface SwarmExecutionResult {
  /** Whether the swarm completed successfully */
  success: boolean;

  /** Synthesized output from all workers */
  synthesisResult?: SynthesisResult;

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
}

/** Serializable swarm state for persistence/resume. */
export interface SwarmCheckpoint {
  sessionId: string;
  timestamp: number;
  phase: SwarmStatus['phase'];
  plan?: SwarmPlan;
  taskStates: Array<{ id: string; status: SwarmTaskStatus; result?: SwarmTaskResult; attempts: number; wave: number; assignedModel?: string }>;
  waves: string[][];
  currentWave: number;
  stats: { totalTokens: number; totalCost: number; qualityRejections: number; retries: number };
  modelHealth: ModelHealthRecord[];
  decisions: OrchestratorDecision[];
  errors: SwarmError[];
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
 * Maps SubtaskType to WorkerCapability for task-worker matching.
 */
export const SUBTASK_TO_CAPABILITY: Record<SubtaskType, WorkerCapability> = {
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
  merge: 'code',
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
export function taskResultToAgentOutput(task: SwarmTask): AgentOutput | null {
  if (!task.result || !task.result.success) return null;

  return {
    agentId: `swarm-worker-${task.id}`,
    content: task.result.output,
    type: task.type === 'implement' || task.type === 'refactor' ? 'code'
      : task.type === 'research' || task.type === 'analysis' ? 'research'
      : task.type === 'review' ? 'review'
      : task.type === 'document' ? 'documentation'
      : task.type === 'test' ? 'code'
      : 'mixed',
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
