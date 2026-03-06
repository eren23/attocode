/**
 * Isolation Provider Types
 *
 * Types for the task isolation system that provides sandboxed environments
 * for parallel evaluation task execution.
 */

// =============================================================================
// TASK ENVIRONMENT
// =============================================================================

/**
 * An isolated environment for running a single evaluation task.
 * Created by an IsolationProvider, recycled via reset after use.
 */
export interface TaskEnvironment {
  /** Unique slot identifier within the pool */
  slotId: string;

  /** Absolute path to the isolated workspace directory */
  workspacePath: string;

  /** Environment variables scoped to this task */
  env?: Record<string, string>;

  /** Metadata about the environment (for logging/debugging) */
  metadata?: {
    /** Type of isolation (worktree, docker, none) */
    isolationType: IsolationType;
    /** Git branch name (for worktree isolation) */
    branch?: string;
    /** Container ID (for docker isolation) */
    containerId?: string;
    /** When this slot was created */
    createdAt: number;
    /** Number of times this slot has been reused */
    reuseCount: number;
  };
}

/**
 * Supported isolation types.
 */
export type IsolationType = 'worktree' | 'docker' | 'none';

// =============================================================================
// ISOLATION PROVIDER INTERFACE
// =============================================================================

/**
 * Task descriptor passed to the isolation provider.
 * Contains just enough info for the provider to set up the environment.
 */
export interface TaskDescriptor {
  /** Unique task identifier */
  id: string;

  /** Repository URL (for git-based isolation) */
  repo?: string;

  /** Base commit to checkout (for git-based isolation) */
  baseCommit?: string;

  /** Setup commands to run after environment creation */
  setupCommands?: string[];

  /** Files to create in the workspace */
  setupFiles?: Record<string, string>;

  /** Working directory override within the workspace */
  workdir?: string;

  /** Test patch to apply before agent runs (SWE-bench test_patch) */
  testPatch?: string;
}

/**
 * Interface for isolation providers that create sandboxed task environments.
 *
 * Lifecycle:
 *   init(tasks) → [acquire(task) → use → reset(env) → release(env)] × N → destroyAll()
 */
export interface IsolationProvider {
  /** Provider type identifier */
  readonly type: IsolationType;

  /**
   * Initialize the provider with the full task list.
   * This allows pre-warming (e.g., cloning repos, creating worktrees).
   */
  init(tasks: TaskDescriptor[]): Promise<void>;

  /**
   * Acquire an isolated environment for a task.
   * Blocks if no slots are available until one is released.
   */
  acquire(task: TaskDescriptor): Promise<TaskEnvironment>;

  /**
   * Reset an environment after task completion.
   * Restores it to a clean state for reuse (e.g., git reset --hard && clean).
   */
  reset(env: TaskEnvironment): Promise<void>;

  /**
   * Release an environment back to the pool.
   * The slot becomes available for the next acquire() call.
   */
  release(env: TaskEnvironment): Promise<void>;

  /**
   * Destroy all environments and clean up resources.
   * Called once when the batch run is complete.
   */
  destroyAll(): Promise<void>;

  /**
   * Get current pool statistics.
   */
  getStats(): PoolStats;
}

// =============================================================================
// POOL STATISTICS
// =============================================================================

/**
 * Statistics about the isolation pool.
 */
export interface PoolStats {
  /** Total number of slots in the pool */
  totalSlots: number;

  /** Number of currently active (in-use) slots */
  activeSlots: number;

  /** Number of available (idle) slots */
  availableSlots: number;

  /** Number of tasks waiting for a slot */
  pendingAcquires: number;

  /** Total number of acquire operations completed */
  totalAcquires: number;

  /** Total number of reset operations completed */
  totalResets: number;
}

// =============================================================================
// BATCH CONFIGURATION
// =============================================================================

/**
 * Configuration for batch execution.
 */
export interface BatchConfig {
  /** Maximum number of parallel tasks */
  parallelism: number;

  /** Isolation type to use */
  isolation: IsolationType;

  /** Maximum total cost in USD before stopping */
  costLimit?: number;

  /** Stagger delay between task starts (ms) to avoid API bursts */
  staggerDelayMs?: number;

  /** Whether to save intermediate results */
  saveIntermediate?: boolean;

  /** Output path for predictions.jsonl (SWE-bench) */
  predictionsPath?: string;
}
