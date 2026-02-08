/**
 * Batch Orchestrator
 *
 * Runs multiple evaluation tasks in parallel with configurable isolation.
 * Uses a Promise.race dispatch loop to maintain maximum parallelism.
 *
 * Key features:
 * - Configurable parallelism (1-N concurrent tasks)
 * - Staggered starts to avoid API rate limit bursts
 * - Cost tracking with budget enforcement
 * - Progress reporting events
 * - Graceful shutdown on SIGINT
 */

import type { EvalTask, EvalResult, EvalRunConfig } from '../types.js';
import type {
  IsolationProvider,
  TaskEnvironment,
  BatchConfig,
  TaskDescriptor,
} from '../isolation/types.js';
import { createIsolationProvider } from '../isolation/index.js';
import { ProductionAgentRunner } from './agent-runner.js';

// =============================================================================
// TYPES
// =============================================================================

export interface BatchOrchestratorOptions {
  /** Batch execution configuration */
  batchConfig: BatchConfig;

  /** Eval run configuration (model, provider, etc.) */
  evalConfig: EvalRunConfig;

  /** Output directory for results */
  outputDir?: string;

  /** Event handler for progress updates */
  onProgress?: (event: BatchProgressEvent) => void;
}

export type BatchProgressEvent =
  | { type: 'batch.start'; totalTasks: number; parallelism: number }
  | { type: 'task.start'; taskId: string; slotId: string; index: number; total: number }
  | { type: 'task.complete'; taskId: string; result: EvalResult; index: number; total: number }
  | { type: 'task.error'; taskId: string; error: string; index: number; total: number }
  | { type: 'batch.progress'; completed: number; total: number; passed: number; failed: number; cost: number }
  | { type: 'batch.complete'; results: EvalResult[]; duration: number };

// =============================================================================
// BATCH ORCHESTRATOR
// =============================================================================

export class BatchOrchestrator {
  private options: BatchOrchestratorOptions;
  private provider: IsolationProvider;
  private shutdownRequested = false;
  private activeSlots: Map<string, { promise: Promise<EvalResult>; taskId: string }> = new Map();

  constructor(options: BatchOrchestratorOptions) {
    this.options = options;
    this.provider = createIsolationProvider(
      options.batchConfig.isolation,
      { maxSlots: options.batchConfig.parallelism },
    );
  }

  /**
   * Run all tasks with parallel execution.
   */
  async run(tasks: EvalTask[]): Promise<EvalResult[]> {
    const { batchConfig, evalConfig } = this.options;
    const startTime = Date.now();

    // Setup graceful shutdown
    const shutdownHandler = () => {
      console.log('\n[BatchOrchestrator] Shutdown requested. Finishing active tasks...');
      this.shutdownRequested = true;
    };
    process.on('SIGINT', shutdownHandler);

    try {
      // Convert tasks to descriptors for isolation provider
      const descriptors = tasks.map((t) => this.taskToDescriptor(t));

      // Initialize isolation provider (clones repos, pre-warms pools)
      console.log(`[BatchOrchestrator] Initializing isolation (${batchConfig.isolation})...`);
      await this.provider.init(descriptors);

      this.emitProgress({
        type: 'batch.start',
        totalTasks: tasks.length,
        parallelism: batchConfig.parallelism,
      });

      // Dispatch loop
      const results = await this.dispatchLoop(tasks, evalConfig);

      const duration = Date.now() - startTime;
      this.emitProgress({ type: 'batch.complete', results, duration });

      return results;
    } finally {
      process.removeListener('SIGINT', shutdownHandler);

      // Clean up isolation provider
      console.log('[BatchOrchestrator] Cleaning up isolation environments...');
      await this.provider.destroyAll();
    }
  }

  // ---------------------------------------------------------------------------
  // DISPATCH LOOP
  // ---------------------------------------------------------------------------

  private async dispatchLoop(
    tasks: EvalTask[],
    evalConfig: EvalRunConfig,
  ): Promise<EvalResult[]> {
    const { batchConfig } = this.options;
    const results: EvalResult[] = [];
    let taskIndex = 0;
    let totalCost = 0;
    let passed = 0;
    let failed = 0;

    while (taskIndex < tasks.length || this.activeSlots.size > 0) {
      // Check shutdown
      if (this.shutdownRequested && this.activeSlots.size === 0) {
        console.log('[BatchOrchestrator] All active tasks finished. Stopping.');
        break;
      }

      // Fill available slots (unless shutdown requested - don't start new tasks)
      while (
        !this.shutdownRequested &&
        taskIndex < tasks.length &&
        this.activeSlots.size < batchConfig.parallelism
      ) {
        // Check cost limit
        if (batchConfig.costLimit && totalCost >= batchConfig.costLimit) {
          console.log(`[BatchOrchestrator] Cost limit reached ($${totalCost.toFixed(4)}). No more tasks.`);
          taskIndex = tasks.length; // Skip remaining
          break;
        }

        const task = tasks[taskIndex];
        const currentIndex = taskIndex;
        taskIndex++;

        // Stagger starts to avoid API bursts
        if (this.activeSlots.size > 0 && batchConfig.staggerDelayMs) {
          await this.delay(batchConfig.staggerDelayMs);
        }

        // Launch task
        const slotPromise = this.runTaskInIsolation(task, evalConfig, currentIndex, tasks.length);
        this.activeSlots.set(task.id, { promise: slotPromise, taskId: task.id });
      }

      // Wait for any task to complete
      if (this.activeSlots.size > 0) {
        const entries = Array.from(this.activeSlots.entries());
        const promises = entries.map(([id, { promise }]) =>
          promise.then((result) => ({ id, result })),
        );

        const { id, result } = await Promise.race(promises);
        this.activeSlots.delete(id);
        results.push(result);

        // Track metrics
        totalCost += result.metrics.estimated_cost;
        if (result.success) passed++;
        else failed++;

        this.emitProgress({
          type: 'batch.progress',
          completed: results.length,
          total: tasks.length,
          passed,
          failed,
          cost: totalCost,
        });
      }
    }

    return results;
  }

  // ---------------------------------------------------------------------------
  // TASK EXECUTION
  // ---------------------------------------------------------------------------

  private async runTaskInIsolation(
    task: EvalTask,
    evalConfig: EvalRunConfig,
    index: number,
    total: number,
  ): Promise<EvalResult> {
    let env: TaskEnvironment | null = null;

    try {
      // Acquire isolated environment
      const descriptor = this.taskToDescriptor(task);
      env = await this.provider.acquire(descriptor);

      this.emitProgress({
        type: 'task.start',
        taskId: task.id,
        slotId: env.slotId,
        index,
        total,
      });

      console.log(`[${index + 1}/${total}] Starting: ${task.id} (slot: ${env.slotId})`);

      // Create a runner scoped to this workspace
      const runner = new ProductionAgentRunner({
        workdir: env.workspacePath,
        outputDir: this.options.outputDir,
      });

      // Override the task's setup workdir to use our isolated environment
      const isolatedTask: EvalTask = {
        ...task,
        setup: {
          ...task.setup,
          workdir: env.workspacePath,
        },
      };

      const result = await runner.runTask(isolatedTask, evalConfig);

      this.emitProgress({
        type: 'task.complete',
        taskId: task.id,
        result,
        index,
        total,
      });

      return result;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);

      this.emitProgress({
        type: 'task.error',
        taskId: task.id,
        error: errorMessage,
        index,
        total,
      });

      return {
        task_id: task.id,
        model: evalConfig.model,
        provider: evalConfig.provider,
        success: false,
        partial_credit: 0,
        metrics: {
          tokens: { input: 0, output: 0, total: 0 },
          iterations: 0,
          tool_calls: 0,
          duration_ms: 0,
          estimated_cost: 0,
        },
        error: errorMessage,
        timestamp: new Date().toISOString(),
      };
    } finally {
      // Release environment back to pool
      if (env) {
        try {
          await this.provider.release(env);
        } catch (err) {
          console.warn(`[BatchOrchestrator] Failed to release slot ${env.slotId}:`, err);
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // HELPERS
  // ---------------------------------------------------------------------------

  private taskToDescriptor(task: EvalTask): TaskDescriptor {
    return {
      id: task.id,
      repo: task.expected?.swe_bench?.repo,
      baseCommit: task.expected?.swe_bench?.base_commit,
      setupCommands: task.setup?.commands,
      setupFiles: task.setup?.files,
      workdir: task.setup?.workdir,
    };
  }

  private emitProgress(event: BatchProgressEvent): void {
    this.options.onProgress?.(event);
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
