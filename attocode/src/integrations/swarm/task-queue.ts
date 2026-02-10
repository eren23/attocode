/**
 * Swarm Task Queue
 *
 * Wave-based task scheduling with dependency resolution.
 * Uses SmartDecomposer's parallelGroups to organize tasks into waves,
 * manages status transitions, and builds dependency context for workers.
 */

import type { SmartDecompositionResult, ResourceConflict } from '../smart-decomposer.js';
import type { SwarmTask, SwarmTaskResult, SwarmConfig, FixupTask, SwarmCheckpoint } from './types.js';
import { subtaskToSwarmTask } from './types.js';

// ─── Task Queue ────────────────────────────────────────────────────────────

export class SwarmTaskQueue {
  private tasks: Map<string, SwarmTask> = new Map();
  private waves: string[][] = [];
  private conflicts: ResourceConflict[] = [];
  private currentWave = 0;
  private onCascadeSkipCallback?: (taskId: string, reason: string) => void;
  private partialDependencyThreshold = 0.5;

  /**
   * Load tasks from a SmartDecompositionResult.
   * Converts subtasks to SwarmTasks and organizes them into waves
   * based on the dependency graph's parallelGroups.
   */
  loadFromDecomposition(result: SmartDecompositionResult, config: SwarmConfig): void {
    this.tasks.clear();
    this.waves = [];
    this.conflicts = result.conflicts;
    this.partialDependencyThreshold = config.partialDependencyThreshold ?? 0.5;

    const { subtasks, dependencyGraph } = result;
    const parallelGroups = dependencyGraph.parallelGroups;

    // Map subtask IDs to wave numbers
    const taskWaveMap = new Map<string, number>();
    for (let wave = 0; wave < parallelGroups.length; wave++) {
      for (const taskId of parallelGroups[wave]) {
        taskWaveMap.set(taskId, wave);
      }
    }

    // Handle file conflicts: if 'serialize' strategy, move conflicting tasks to later waves
    const serializedMoves = new Map<string, number>();
    if (config.fileConflictStrategy === 'serialize') {
      for (const conflict of this.conflicts) {
        if (conflict.type === 'write-write') {
          // Keep first task in its wave, push subsequent ones to later waves
          for (let i = 1; i < conflict.taskIds.length; i++) {
            const taskId = conflict.taskIds[i];
            const currentWave = taskWaveMap.get(taskId) ?? 0;
            const prevTaskWave = taskWaveMap.get(conflict.taskIds[i - 1]) ?? 0;
            const newWave = Math.max(currentWave, prevTaskWave + 1);
            serializedMoves.set(taskId, newWave);
            taskWaveMap.set(taskId, newWave);
          }
        }
      }
    }

    // Convert subtasks to SwarmTasks with wave assignments
    for (const subtask of subtasks) {
      const wave = taskWaveMap.get(subtask.id) ?? 0;
      const swarmTask = subtaskToSwarmTask(subtask, wave);

      // Apply serialization if needed
      if (serializedMoves.has(subtask.id)) {
        swarmTask.wave = serializedMoves.get(subtask.id)!;
      }

      this.tasks.set(subtask.id, swarmTask);
    }

    // Build wave groups from assigned waves
    this.rebuildWaves();

    // Set initial ready status for tasks with no dependencies
    this.updateReadyStatus();
  }

  /**
   * Rebuild wave arrays from task wave assignments.
   */
  private rebuildWaves(): void {
    const waveMap = new Map<number, string[]>();
    for (const [id, task] of this.tasks) {
      const wave = task.wave;
      if (!waveMap.has(wave)) waveMap.set(wave, []);
      waveMap.get(wave)!.push(id);
    }

    // Sort by wave number and convert to array
    const sortedWaves = [...waveMap.entries()].sort((a, b) => a[0] - b[0]);
    this.waves = sortedWaves.map(([, ids]) => ids);
  }

  /**
   * Update task ready status based on dependency completion.
   * Supports partial dependency tolerance: if enough deps succeeded (>= threshold),
   * the task runs with partial context instead of being cascade-skipped.
   */
  private updateReadyStatus(): void {
    for (const [, task] of this.tasks) {
      if (task.status !== 'pending') continue;

      if (task.dependencies.length === 0) {
        task.status = 'ready';
        continue;
      }

      let completedCount = 0;
      let failedCount = 0;
      let resolvedCount = 0;
      const succeededDeps: string[] = [];
      const failedDeps: string[] = [];

      for (const depId of task.dependencies) {
        const dep = this.tasks.get(depId);
        if (!dep) continue;

        if (dep.status === 'completed') {
          completedCount++;
          resolvedCount++;
          succeededDeps.push(dep.description);
        } else if (dep.status === 'failed') {
          failedCount++;
          resolvedCount++;
          failedDeps.push(dep.description);
        } else if (dep.status === 'skipped') {
          resolvedCount++;
          failedDeps.push(dep.description);
        }
      }

      const allResolved = resolvedCount === task.dependencies.length;
      if (!allResolved) continue;

      const noFailures = failedCount === 0 && failedDeps.length === 0;

      if (noFailures) {
        // All deps succeeded — standard path
        task.status = 'ready';
        task.dependencyContext = this.buildDependencyContext(task);
      } else {
        // Some deps failed — check partial threshold
        const ratio = completedCount / task.dependencies.length;
        if (ratio >= this.partialDependencyThreshold) {
          // Enough succeeded — dispatch with partial context
          task.status = 'ready';
          task.partialContext = { succeeded: succeededDeps, failed: failedDeps, ratio };
          task.dependencyContext = this.buildDependencyContext(task);
        } else {
          // Too many failures — skip
          task.status = 'skipped';
          this.onCascadeSkipCallback?.(task.id,
            `${failedDeps.length}/${task.dependencies.length} dependencies failed (ratio ${ratio.toFixed(2)} < threshold ${this.partialDependencyThreshold})`);
        }
      }
    }
  }

  /**
   * Build context string from completed dependency outputs.
   * Includes partial dependency warnings when some deps failed.
   */
  private buildDependencyContext(task: SwarmTask): string {
    const parts: string[] = [];
    const emptyDeps: string[] = [];

    // Add partial dependency warning if applicable
    if (task.partialContext) {
      const { succeeded, failed, ratio } = task.partialContext;
      parts.push(
        `WARNING: ${succeeded.length}/${succeeded.length + failed.length} dependency tasks completed (${(ratio * 100).toFixed(0)}%).`,
        `Missing data from: ${failed.join(', ')}.`,
        'Synthesize from available results only — do not attempt to fill gaps with speculation.',
        '',
      );
    }

    for (const depId of task.dependencies) {
      const dep = this.tasks.get(depId);
      if (!dep || !dep.result || !dep.result.success) continue;

      const summary = dep.result.closureReport
        ? dep.result.closureReport.findings.join('\n') + '\n' + dep.result.closureReport.actionsTaken.join('\n')
        : dep.result.output.slice(0, 500);

      // V6: Detect hollow dependency output — both conditions must be true:
      // short output AND budget/unable failures (so legitimate short completions pass through)
      const isHollow = summary.trim().length < 100 &&
        (dep.result.closureReport?.failures?.some(f => /budget|unable|not completed/i.test(f)) ?? false);

      if (isHollow) {
        emptyDeps.push(dep.description);
      } else {
        parts.push(`[Dependency: ${dep.description}]\n${summary}`);
      }
    }

    if (emptyDeps.length > 0) {
      parts.unshift(`WARNING: ${emptyDeps.length} dependencies completed without meaningful output: ${emptyDeps.join(', ')}. You may need to do additional research to compensate.`);
    }

    return parts.length > 0 ? parts.join('\n\n') : '';
  }

  /**
   * Get all tasks ready for dispatch in the current wave.
   * Filters out tasks with a retryAfter timestamp in the future.
   */
  getReadyTasks(): SwarmTask[] {
    if (this.currentWave >= this.waves.length) return [];

    const now = Date.now();
    const waveTaskIds = this.waves[this.currentWave];
    return waveTaskIds
      .map(id => this.tasks.get(id)!)
      .filter(task => task.status === 'ready' && !(task.retryAfter && now < task.retryAfter));
  }

  /**
   * Get all tasks across all waves that are ready (for filling slots).
   * Filters out tasks with a retryAfter timestamp in the future.
   */
  getAllReadyTasks(): SwarmTask[] {
    const now = Date.now();
    const ready: SwarmTask[] = [];
    for (const [, task] of this.tasks) {
      if (task.status === 'ready' && !(task.retryAfter && now < task.retryAfter)) {
        ready.push(task);
      }
    }
    // Sort by wave (prefer current wave), then by complexity (harder first)
    return ready.sort((a, b) => {
      if (a.wave !== b.wave) return a.wave - b.wave;
      return b.complexity - a.complexity;
    });
  }

  /**
   * Set a non-blocking cooldown on a task before it can be re-dispatched.
   */
  setRetryAfter(taskId: string, delayMs: number): void {
    const task = this.tasks.get(taskId);
    if (task) {
      task.retryAfter = Date.now() + delayMs;
    }
  }

  /**
   * Register a callback invoked for each task cascade-skipped due to a dependency failure.
   */
  setOnCascadeSkip(callback: (taskId: string, reason: string) => void): void {
    this.onCascadeSkipCallback = callback;
  }

  /**
   * Mark a task as dispatched.
   */
  markDispatched(taskId: string, model: string): void {
    const task = this.tasks.get(taskId);
    if (!task) return;
    task.status = 'dispatched';
    task.assignedModel = model;
    task.attempts++;
  }

  /**
   * Mark a task as completed with its result.
   */
  markCompleted(taskId: string, result: SwarmTaskResult): void {
    const task = this.tasks.get(taskId);
    if (!task) return;
    // Don't overwrite terminal states (task may have been cascade-skipped while worker was running)
    if (task.status === 'skipped' || task.status === 'failed') return;
    task.status = 'completed';
    task.result = result;

    // Update dependent tasks' ready status
    this.updateReadyStatus();
  }

  /**
   * Mark a task as failed.
   * Returns true if the task can be retried (attempts < maxAttempts).
   */
  markFailed(taskId: string, maxRetries: number): boolean {
    const task = this.tasks.get(taskId);
    if (!task) return false;

    if (task.attempts <= maxRetries) {
      // Reset to ready for retry
      task.status = 'ready';
      return true;
    }

    task.status = 'failed';

    // Cascade: skip all dependents of a failed task
    this.cascadeSkip(taskId);
    return false;
  }

  /**
   * Cascade failure to dependent tasks, respecting partial dependency threshold.
   * Tasks with enough successful deps are kept ready/pending rather than skipped.
   */
  private cascadeSkip(failedTaskId: string): void {
    for (const [, task] of this.tasks) {
      // H5: Also skip dispatched tasks whose dependency failed
      if (task.status !== 'pending' && task.status !== 'ready' && task.status !== 'dispatched') continue;

      // Only consider direct dependents — transitive deps are handled recursively
      // when a direct dependent gets skipped (it will trigger another cascadeSkip)
      if (!this.dependsOn(task.id, failedTaskId)) continue;

      // Check partial dependency threshold
      if (task.dependencies.length > 1) {
        let completedCount = 0;
        let failedOrSkippedCount = 0;

        for (const depId of task.dependencies) {
          const dep = this.tasks.get(depId);
          if (!dep) continue;
          if (dep.status === 'completed') completedCount++;
          if (dep.status === 'failed' || dep.status === 'skipped') failedOrSkippedCount++;
        }

        // Not all deps resolved yet — don't skip prematurely, updateReadyStatus will handle it
        const resolvedCount = completedCount + failedOrSkippedCount;
        if (resolvedCount < task.dependencies.length) continue;

        const ratio = completedCount / task.dependencies.length;
        if (ratio >= this.partialDependencyThreshold) {
          // Enough deps succeeded — mark ready with partial context instead of skipping
          const succeededDeps: string[] = [];
          const failedDeps: string[] = [];
          for (const depId of task.dependencies) {
            const dep = this.tasks.get(depId);
            if (!dep) continue;
            if (dep.status === 'completed') succeededDeps.push(dep.description);
            else failedDeps.push(dep.description);
          }
          task.status = 'ready';
          task.partialContext = { succeeded: succeededDeps, failed: failedDeps, ratio };
          task.dependencyContext = this.buildDependencyContext(task);
          continue;
        }
      }

      task.status = 'skipped';
      this.onCascadeSkipCallback?.(task.id, `dependency ${failedTaskId} failed`);
    }
  }

  /**
   * Check if taskId transitively depends on depId.
   */
  private dependsOn(taskId: string, depId: string, visited = new Set<string>()): boolean {
    if (visited.has(taskId)) return false;
    visited.add(taskId);

    const task = this.tasks.get(taskId);
    if (!task) return false;

    if (task.dependencies.includes(depId)) return true;

    return task.dependencies.some(d => this.dependsOn(d, depId, visited));
  }

  /**
   * Check if the current wave is complete (all tasks resolved).
   */
  isCurrentWaveComplete(): boolean {
    if (this.currentWave >= this.waves.length) return true;

    const waveTaskIds = this.waves[this.currentWave];
    return waveTaskIds.every(id => {
      const task = this.tasks.get(id);
      return task && (task.status === 'completed' || task.status === 'failed' || task.status === 'skipped');
    });
  }

  /**
   * Advance to the next wave. Returns true if there are more waves.
   */
  advanceWave(): boolean {
    this.currentWave++;
    if (this.currentWave < this.waves.length) {
      this.updateReadyStatus();
      return true;
    }
    return false;
  }

  /**
   * Check if all tasks are resolved (no more work to do).
   */
  isComplete(): boolean {
    for (const [, task] of this.tasks) {
      if (task.status === 'pending' || task.status === 'ready' || task.status === 'dispatched') {
        return false;
      }
    }
    return true;
  }

  /**
   * Get a task by ID.
   */
  getTask(taskId: string): SwarmTask | undefined {
    return this.tasks.get(taskId);
  }

  /**
   * Get all tasks.
   */
  getAllTasks(): SwarmTask[] {
    return [...this.tasks.values()];
  }

  /**
   * Get the current wave number (0-indexed).
   */
  getCurrentWave(): number {
    return this.currentWave;
  }

  /**
   * Get total number of waves.
   */
  getTotalWaves(): number {
    return this.waves.length;
  }

  /**
   * Get task count by status.
   */
  getStats(): { ready: number; running: number; completed: number; failed: number; skipped: number; total: number } {
    let ready = 0, running = 0, completed = 0, failed = 0, skipped = 0;

    for (const [, task] of this.tasks) {
      switch (task.status) {
        case 'ready': ready++; break;
        case 'dispatched': running++; break;
        case 'completed': completed++; break;
        case 'failed': failed++; break;
        case 'skipped': skipped++; break;
      }
    }

    return { ready, running, completed, failed, skipped, total: this.tasks.size };
  }

  /**
   * Get conflicts for reference.
   */
  getConflicts(): ResourceConflict[] {
    return this.conflicts;
  }

  // ─── V2: Checkpoint & Restore ─────────────────────────────────────────

  /**
   * Export current state for checkpoint serialization.
   */
  getCheckpointState(): Pick<SwarmCheckpoint, 'taskStates' | 'waves' | 'currentWave'> {
    const taskStates = [...this.tasks.values()].map(t => ({
      id: t.id,
      status: t.status,
      result: t.result,
      attempts: t.attempts,
      wave: t.wave,
      assignedModel: t.assignedModel,
    }));

    return {
      taskStates,
      waves: this.waves,
      currentWave: this.currentWave,
    };
  }

  /**
   * Restore state from a checkpoint. Merges checkpoint state into existing tasks.
   */
  restoreFromCheckpoint(state: Pick<SwarmCheckpoint, 'taskStates' | 'waves' | 'currentWave'>): void {
    this.waves = state.waves;
    this.currentWave = state.currentWave;

    for (const ts of state.taskStates) {
      const task = this.tasks.get(ts.id);
      if (task) {
        task.status = ts.status;
        task.result = ts.result;
        task.attempts = ts.attempts;
        task.wave = ts.wave;
        task.assignedModel = ts.assignedModel;
      }
    }
  }

  /**
   * Add fix-up tasks from wave review. Inserted into the current wave.
   */
  addFixupTasks(tasks: FixupTask[]): void {
    const currentWaveIds = this.waves[this.currentWave] ?? [];
    for (const task of tasks) {
      this.tasks.set(task.id, task);
      currentWaveIds.push(task.id);
    }
    if (this.currentWave < this.waves.length) {
      this.waves[this.currentWave] = currentWaveIds;
    } else {
      this.waves.push(currentWaveIds);
    }
  }
}

/**
 * Factory function.
 */
export function createSwarmTaskQueue(): SwarmTaskQueue {
  return new SwarmTaskQueue();
}
