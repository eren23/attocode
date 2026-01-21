/**
 * Lesson 15: Planning & Decomposition Types
 *
 * Type definitions for task planning and decomposition.
 * Plans break complex goals into smaller, manageable tasks
 * with dependencies between them.
 */

// =============================================================================
// TASK TYPES
// =============================================================================

/**
 * A single task in a plan.
 */
export interface Task {
  /** Unique identifier */
  id: string;

  /** Human-readable description */
  description: string;

  /** Current execution status */
  status: TaskStatus;

  /** IDs of tasks that must complete before this one */
  dependencies: string[];

  /** Estimated complexity (1-10) */
  complexity?: number;

  /** Optional subtasks for hierarchical planning */
  subtasks?: Task[];

  /** Result after execution */
  result?: TaskResult;

  /** When the task started */
  startedAt?: Date;

  /** When the task completed */
  completedAt?: Date;

  /** Optional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Status of a task.
 */
export type TaskStatus =
  | 'pending'      // Not yet started
  | 'blocked'      // Waiting on dependencies
  | 'ready'        // Dependencies met, can start
  | 'in_progress'  // Currently executing
  | 'completed'    // Successfully finished
  | 'failed'       // Failed to complete
  | 'skipped';     // Skipped due to failure upstream

/**
 * Result of task execution.
 */
export interface TaskResult {
  /** Whether the task succeeded */
  success: boolean;

  /** Output or error message */
  output: string;

  /** Any artifacts produced */
  artifacts?: string[];

  /** Execution duration in milliseconds */
  durationMs: number;
}

// =============================================================================
// PLAN TYPES
// =============================================================================

/**
 * A complete plan for achieving a goal.
 */
export interface Plan {
  /** Unique identifier */
  id: string;

  /** The goal this plan achieves */
  goal: string;

  /** All tasks in the plan */
  tasks: Task[];

  /** Plan status */
  status: PlanStatus;

  /** When the plan was created */
  createdAt: Date;

  /** When the plan was last revised */
  revisedAt?: Date;

  /** Estimated total steps */
  estimatedSteps: number;

  /** Actual steps taken */
  actualSteps: number;

  /** Plan metadata */
  metadata?: PlanMetadata;
}

/**
 * Status of the overall plan.
 */
export type PlanStatus =
  | 'draft'        // Being created
  | 'ready'        // Ready to execute
  | 'executing'    // Currently running
  | 'paused'       // Temporarily stopped
  | 'completed'    // All tasks done
  | 'failed'       // Failed to complete
  | 'revised';     // Plan was modified

/**
 * Metadata about a plan.
 */
export interface PlanMetadata {
  /** Revision number */
  revision: number;

  /** Why the plan was created/revised */
  reason?: string;

  /** Estimated completion time */
  estimatedDurationMs?: number;

  /** Context that informed the plan */
  context?: string;
}

// =============================================================================
// PLANNER TYPES
// =============================================================================

/**
 * Configuration for the planner.
 */
export interface PlannerConfig {
  /** Maximum tasks in a plan */
  maxTasks: number;

  /** Maximum depth for hierarchical plans */
  maxDepth: number;

  /** Whether to validate plans before returning */
  validatePlans: boolean;

  /** Whether to estimate complexity */
  estimateComplexity: boolean;

  /** Default task timeout in milliseconds */
  defaultTimeout: number;
}

/**
 * Context provided to the planner.
 */
export interface PlanningContext {
  /** Current working directory */
  cwd: string;

  /** Available tools */
  availableTools: string[];

  /** Files already known about */
  knownFiles?: string[];

  /** Previous plans for reference */
  previousPlans?: Plan[];

  /** User preferences */
  preferences?: Record<string, unknown>;
}

/**
 * Result of plan validation.
 */
export interface ValidationResult {
  /** Whether the plan is valid */
  valid: boolean;

  /** Validation errors */
  errors: ValidationError[];

  /** Validation warnings */
  warnings: string[];
}

/**
 * A validation error.
 */
export interface ValidationError {
  type: 'missing_dependency' | 'circular_dependency' | 'invalid_task' | 'unreachable_task';
  taskId: string;
  message: string;
}

// =============================================================================
// DECOMPOSITION TYPES
// =============================================================================

/**
 * Options for task decomposition.
 */
export interface DecompositionOptions {
  /** Target granularity (1 = fine, 10 = coarse) */
  granularity: number;

  /** Maximum subtasks per task */
  maxSubtasks: number;

  /** Whether to flatten into a single list */
  flatten: boolean;

  /** Strategy for decomposition */
  strategy: DecompositionStrategy;
}

/**
 * Strategy for breaking down tasks.
 */
export type DecompositionStrategy =
  | 'sequential'   // Tasks must be done in order
  | 'parallel'     // Tasks can be done simultaneously
  | 'hierarchical' // Tasks have subtasks
  | 'adaptive';    // Strategy chosen based on task type

/**
 * Result of decomposition.
 */
export interface DecompositionResult {
  /** Original task */
  original: Task;

  /** Resulting subtasks */
  subtasks: Task[];

  /** Strategy used */
  strategy: DecompositionStrategy;

  /** Dependency graph */
  dependencies: Map<string, string[]>;
}

// =============================================================================
// EXECUTOR TYPES
// =============================================================================

/**
 * Configuration for the plan executor.
 */
export interface ExecutorConfig {
  /** Maximum concurrent tasks */
  concurrency: number;

  /** Whether to stop on first failure */
  stopOnFailure: boolean;

  /** Retry configuration */
  retry: {
    maxAttempts: number;
    backoffMs: number;
  };

  /** Task timeout in milliseconds */
  timeout: number;
}

/**
 * Events during plan execution.
 */
export type PlanExecutionEvent =
  | { type: 'plan.started'; planId: string }
  | { type: 'task.started'; taskId: string }
  | { type: 'task.completed'; taskId: string; result: TaskResult }
  | { type: 'task.failed'; taskId: string; error: Error }
  | { type: 'task.skipped'; taskId: string; reason: string }
  | { type: 'plan.completed'; planId: string; success: boolean }
  | { type: 'plan.revised'; planId: string; reason: string };

/**
 * Listener for execution events.
 */
export type ExecutionEventListener = (event: PlanExecutionEvent) => void;

/**
 * Execution progress information.
 */
export interface ExecutionProgress {
  /** Total tasks */
  total: number;

  /** Completed tasks */
  completed: number;

  /** Failed tasks */
  failed: number;

  /** Currently executing */
  inProgress: number;

  /** Remaining tasks */
  remaining: number;

  /** Percentage complete */
  percentage: number;

  /** Estimated time remaining in milliseconds */
  estimatedRemainingMs?: number;
}

// =============================================================================
// DEPENDENCY GRAPH TYPES
// =============================================================================

/**
 * A dependency graph for tasks.
 */
export interface DependencyGraph {
  /** All nodes (task IDs) */
  nodes: Set<string>;

  /** Edges (from -> to) */
  edges: Map<string, Set<string>>;

  /** Reverse edges (to -> from) */
  reverseEdges: Map<string, Set<string>>;
}

/**
 * Result of topological sort.
 */
export interface TopologicalSortResult {
  /** Whether a valid ordering exists */
  valid: boolean;

  /** Sorted task IDs (if valid) */
  order?: string[];

  /** Cycle detected (if invalid) */
  cycle?: string[];
}

// =============================================================================
// RE-PLANNING TYPES
// =============================================================================

/**
 * Reason for re-planning.
 */
export type ReplanReason =
  | 'task_failed'
  | 'new_information'
  | 'user_request'
  | 'timeout'
  | 'dependency_changed';

/**
 * Options for re-planning.
 */
export interface ReplanOptions {
  /** Preserve completed tasks */
  preserveCompleted: boolean;

  /** Maximum revision attempts */
  maxRevisions: number;

  /** Feedback to incorporate */
  feedback?: string;
}

/**
 * Result of re-planning.
 */
export interface ReplanResult {
  /** Whether re-planning succeeded */
  success: boolean;

  /** New plan (if successful) */
  newPlan?: Plan;

  /** What changed */
  changes: PlanChange[];

  /** Reason for failure (if unsuccessful) */
  failureReason?: string;
}

/**
 * A change made during re-planning.
 */
export interface PlanChange {
  type: 'added' | 'removed' | 'modified';
  taskId: string;
  description: string;
}

// =============================================================================
// DEFAULT VALUES
// =============================================================================

/**
 * Default planner configuration.
 */
export const DEFAULT_PLANNER_CONFIG: PlannerConfig = {
  maxTasks: 20,
  maxDepth: 3,
  validatePlans: true,
  estimateComplexity: true,
  defaultTimeout: 60000,
};

/**
 * Default executor configuration.
 */
export const DEFAULT_EXECUTOR_CONFIG: ExecutorConfig = {
  concurrency: 1,
  stopOnFailure: false,
  retry: {
    maxAttempts: 2,
    backoffMs: 1000,
  },
  timeout: 60000,
};
