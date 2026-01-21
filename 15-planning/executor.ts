/**
 * Lesson 15: Plan Executor
 *
 * Executes plans by running tasks in dependency order.
 * Supports concurrent execution, failure handling, and progress tracking.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The dependency resolution logic determines which tasks can run.
 * You could implement:
 * - Parallel execution with concurrency limits
 * - Priority-based task selection
 * - Resource-aware scheduling
 */

import type {
  Plan,
  Task,
  TaskResult,
  TaskStatus,
  ExecutorConfig,
  PlanExecutionEvent,
  ExecutionEventListener,
  ExecutionProgress,
  DEFAULT_EXECUTOR_CONFIG,
} from './types.js';

// =============================================================================
// EXECUTOR
// =============================================================================

/**
 * Executes plans by running tasks in order.
 */
export class PlanExecutor {
  private config: ExecutorConfig;
  private listeners: Set<ExecutionEventListener> = new Set();

  constructor(config: Partial<ExecutorConfig> = {}) {
    this.config = {
      concurrency: config.concurrency ?? 1,
      stopOnFailure: config.stopOnFailure ?? false,
      retry: {
        maxAttempts: config.retry?.maxAttempts ?? 2,
        backoffMs: config.retry?.backoffMs ?? 1000,
      },
      timeout: config.timeout ?? 60000,
    };
  }

  // =============================================================================
  // EXECUTION
  // =============================================================================

  /**
   * Execute a plan.
   */
  async execute(
    plan: Plan,
    taskRunner: TaskRunner
  ): Promise<Plan> {
    this.emit({ type: 'plan.started', planId: plan.id });

    // Update plan status
    plan.status = 'executing';

    // Track execution
    let hasFailure = false;

    // Execute until all tasks are done
    while (!this.isComplete(plan) && !hasFailure) {
      // Get tasks that are ready to run
      const readyTasks = this.getReadyTasks(plan);

      if (readyTasks.length === 0) {
        // No ready tasks but not complete = deadlock
        if (!this.isComplete(plan)) {
          console.error('Deadlock detected: no tasks ready but plan not complete');
          break;
        }
        break;
      }

      // Execute ready tasks (with concurrency limit)
      const tasksToRun = readyTasks.slice(0, this.config.concurrency);

      const results = await Promise.all(
        tasksToRun.map((task) => this.executeTask(task, taskRunner))
      );

      // Check for failures
      for (let i = 0; i < results.length; i++) {
        const task = tasksToRun[i];
        const result = results[i];

        if (!result.success) {
          hasFailure = true;

          // Skip downstream tasks if configured
          if (this.config.stopOnFailure) {
            this.skipDependentTasks(plan, task.id);
            break;
          }
        }
      }

      plan.actualSteps++;
    }

    // Update plan status
    plan.status = hasFailure ? 'failed' : 'completed';

    this.emit({
      type: 'plan.completed',
      planId: plan.id,
      success: !hasFailure,
    });

    return plan;
  }

  /**
   * Execute a single task.
   */
  private async executeTask(
    task: Task,
    runner: TaskRunner
  ): Promise<TaskResult> {
    task.status = 'in_progress';
    task.startedAt = new Date();

    this.emit({ type: 'task.started', taskId: task.id });

    let result: TaskResult;
    let attempt = 0;

    while (attempt < this.config.retry.maxAttempts) {
      attempt++;

      try {
        result = await this.runWithTimeout(
          runner(task),
          this.config.timeout
        );

        if (result.success) {
          break;
        }

        // Retry on failure if we have attempts left
        if (attempt < this.config.retry.maxAttempts) {
          await this.delay(this.config.retry.backoffMs * attempt);
        }
      } catch (err) {
        result = {
          success: false,
          output: err instanceof Error ? err.message : String(err),
          durationMs: 0,
        };
      }
    }

    // Update task
    task.result = result!;
    task.completedAt = new Date();
    task.status = result!.success ? 'completed' : 'failed';

    if (result!.success) {
      this.emit({ type: 'task.completed', taskId: task.id, result: result! });
    } else {
      this.emit({ type: 'task.failed', taskId: task.id, error: new Error(result!.output) });
    }

    return result!;
  }

  /**
   * Run a promise with timeout.
   */
  private async runWithTimeout<T>(
    promise: Promise<T>,
    timeoutMs: number
  ): Promise<T> {
    return Promise.race([
      promise,
      new Promise<never>((_, reject) => {
        setTimeout(() => reject(new Error('Task timeout')), timeoutMs);
      }),
    ]);
  }

  /**
   * Delay for retry backoff.
   */
  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // =============================================================================
  // TASK SELECTION
  // =============================================================================

  /**
   * Get tasks that are ready to run.
   */
  getReadyTasks(plan: Plan): Task[] {
    const completedIds = new Set(
      plan.tasks
        .filter((t) => t.status === 'completed')
        .map((t) => t.id)
    );

    return plan.tasks.filter((task) => {
      // Must be pending or ready
      if (task.status !== 'pending' && task.status !== 'ready' && task.status !== 'blocked') {
        return false;
      }

      // All dependencies must be complete
      return task.dependencies.every((depId) => completedIds.has(depId));
    }).map((task) => {
      // Update status to ready
      task.status = 'ready';
      return task;
    });
  }

  /**
   * Check if plan execution is complete.
   */
  isComplete(plan: Plan): boolean {
    return plan.tasks.every(
      (t) =>
        t.status === 'completed' ||
        t.status === 'failed' ||
        t.status === 'skipped'
    );
  }

  /**
   * Skip tasks that depend on a failed task.
   */
  private skipDependentTasks(plan: Plan, failedTaskId: string): void {
    const toSkip = new Set<string>();

    // Find all tasks that depend on the failed task
    const findDependents = (taskId: string) => {
      for (const task of plan.tasks) {
        if (task.dependencies.includes(taskId) && !toSkip.has(task.id)) {
          toSkip.add(task.id);
          findDependents(task.id);
        }
      }
    };

    findDependents(failedTaskId);

    // Skip them
    for (const task of plan.tasks) {
      if (toSkip.has(task.id)) {
        task.status = 'skipped';
        this.emit({
          type: 'task.skipped',
          taskId: task.id,
          reason: `Dependency "${failedTaskId}" failed`,
        });
      }
    }
  }

  // =============================================================================
  // PROGRESS TRACKING
  // =============================================================================

  /**
   * Get current execution progress.
   */
  getProgress(plan: Plan): ExecutionProgress {
    const total = plan.tasks.length;
    const completed = plan.tasks.filter((t) => t.status === 'completed').length;
    const failed = plan.tasks.filter((t) => t.status === 'failed').length;
    const inProgress = plan.tasks.filter((t) => t.status === 'in_progress').length;
    const remaining = total - completed - failed - plan.tasks.filter((t) => t.status === 'skipped').length;

    return {
      total,
      completed,
      failed,
      inProgress,
      remaining,
      percentage: Math.round((completed / total) * 100),
    };
  }

  // =============================================================================
  // EVENT HANDLING
  // =============================================================================

  /**
   * Subscribe to execution events.
   */
  on(listener: ExecutionEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: PlanExecutionEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in execution listener:', err);
      }
    }
  }
}

// =============================================================================
// TASK RUNNER TYPE
// =============================================================================

/**
 * Function that executes a task.
 */
export type TaskRunner = (task: Task) => Promise<TaskResult>;

/**
 * Create a simple task runner for demonstration.
 */
export function createMockRunner(
  delay = 100,
  failureRate = 0
): TaskRunner {
  return async (task: Task): Promise<TaskResult> => {
    const startTime = performance.now();

    // Simulate work
    await new Promise((r) => setTimeout(r, delay + Math.random() * delay));

    // Random failure
    if (Math.random() < failureRate) {
      return {
        success: false,
        output: `Task "${task.id}" failed randomly`,
        durationMs: performance.now() - startTime,
      };
    }

    return {
      success: true,
      output: `Completed: ${task.description}`,
      durationMs: performance.now() - startTime,
    };
  };
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultExecutor = new PlanExecutor();
