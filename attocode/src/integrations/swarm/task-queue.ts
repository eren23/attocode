/**
 * Swarm Task Queue
 *
 * Wave-based task scheduling with dependency resolution.
 * Uses SmartDecomposer's parallelGroups to organize tasks into waves,
 * manages status transitions, and builds dependency context for workers.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { SmartDecompositionResult, ResourceConflict } from '../smart-decomposer.js';
import type { SwarmTask, SwarmTaskResult, SwarmConfig, FixupTask, SwarmCheckpoint, TaskFailureMode } from './types.js';
import { subtaskToSwarmTask } from './types.js';

/** P6: Failure-mode-specific thresholds — more lenient for external failures, stricter for quality. */
const FAILURE_MODE_THRESHOLDS: Record<TaskFailureMode, number> = {
  'timeout': 0.3,
  'rate-limit': 0.3,
  'error': 0.5,
  'quality': 0.7,
  'hollow': 0.7,
  'cascade': 0.8,
};

/** P6: Get the effective threshold for a task based on its failed dependencies' failure modes.
 *  Uses the most lenient (lowest) threshold among failed deps, since that indicates
 *  the least fault in the workers. Falls back to the configured threshold. */
function getEffectiveThreshold(failedDeps: SwarmTask[], configuredThreshold: number): number {
  if (failedDeps.length === 0) return configuredThreshold;
  let minThreshold = configuredThreshold;
  for (const dep of failedDeps) {
    if (dep.failureMode) {
      const modeThreshold = FAILURE_MODE_THRESHOLDS[dep.failureMode];
      if (modeThreshold < minThreshold) minThreshold = modeThreshold;
    }
  }
  return minThreshold;
}

export interface ReconcileStaleDispatchedOptions {
  staleAfterMs: number;
  now?: number;
  activeTaskIds?: Set<string>;
}

// ─── Task Queue ────────────────────────────────────────────────────────────

export class SwarmTaskQueue {
  private tasks: Map<string, SwarmTask> = new Map();
  private waves: string[][] = [];
  private conflicts: ResourceConflict[] = [];
  private currentWave = 0;
  private onCascadeSkipCallback?: (taskId: string, reason: string) => void;
  private partialDependencyThreshold = 0.5;
  private artifactAwareSkip = true;
  private workingDirectory = process.cwd();

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
    this.artifactAwareSkip = config.artifactAwareSkip ?? true;
    if (config.facts?.workingDirectory) this.workingDirectory = config.facts.workingDirectory;

    const { subtasks, dependencyGraph } = result;
    let parallelGroups = dependencyGraph.parallelGroups;

    // Defensive: if parallelGroups is empty but subtasks exist, fall back to
    // single-wave scheduling so tasks aren't silently dropped.
    if (parallelGroups.length === 0 && subtasks.length > 0) {
      parallelGroups = [subtasks.map(s => s.id)];
    }

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

        if (dep.status === 'completed' || dep.status === 'decomposed') {
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
        // P6: Some deps failed — check failure-mode-aware threshold
        const failedDepTasks = task.dependencies
          .map(id => this.tasks.get(id))
          .filter((d): d is SwarmTask => !!d && (d.status === 'failed' || d.status === 'skipped'));
        const effectiveThreshold = getEffectiveThreshold(failedDepTasks, this.partialDependencyThreshold);
        const ratio = completedCount / task.dependencies.length;
        if (ratio >= effectiveThreshold) {
          // Enough succeeded — dispatch with partial context
          task.status = 'ready';
          task.partialContext = { succeeded: succeededDeps, failed: failedDeps, ratio };
          task.dependencyContext = this.buildDependencyContext(task);
        } else {
          // Too many failures — skip
          task.status = 'skipped';
          this.onCascadeSkipCallback?.(task.id,
            `${failedDeps.length}/${task.dependencies.length} dependencies failed (ratio ${ratio.toFixed(2)} < threshold ${effectiveThreshold.toFixed(2)})`);
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

    // Add rescue context warning if this task was un-skipped
    if (task.rescueContext) {
      parts.push(
        `⚠ RESCUED TASK: ${task.rescueContext}`,
        'Some dependencies may be missing or degraded. Check file artifacts on disk before assuming output exists.',
        '',
      );
    }

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

      // F24b: Append files created/modified by this dependency
      const fileList = dep.result.filesModified?.length
        ? `\nFiles created/modified: ${dep.result.filesModified.join(', ')}`
        : '';

      // Degraded dependency warning — task completed but quality was low
      const degradedWarning = dep.degraded
        ? '\n⚠ DEGRADED: This dependency was accepted with partial/low-quality output. Verify its artifacts before relying on them.'
        : '';

      // V6: Detect hollow dependency output — both conditions must be true:
      // short output AND budget/unable failures (so legitimate short completions pass through)
      const isHollow = summary.trim().length < 100 &&
        (dep.result.closureReport?.failures?.some(f => /budget|unable|not completed/i.test(f)) ?? false);

      if (isHollow) {
        emptyDeps.push(dep.description);
      } else {
        parts.push(`[Dependency: ${dep.description}]${degradedWarning}\n${summary}${fileList}`);
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
    task.dispatchedAt = Date.now();
  }

  /**
   * Mark a task as completed with its result.
   */
  markCompleted(taskId: string, result: SwarmTaskResult): void {
    const task = this.tasks.get(taskId);
    if (!task) return;
    // Don't overwrite terminal states (unless pendingCascadeSkip — see F4)
    if (task.status === 'skipped' || task.status === 'failed') return;
    task.status = 'completed';
    task.dispatchedAt = undefined;
    task.result = result;
    // F4: Clear pendingCascadeSkip since we accepted the result
    task.pendingCascadeSkip = undefined;

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
      task.dispatchedAt = undefined;
      return true;
    }

    task.status = 'failed';
    task.dispatchedAt = undefined;

    // Cascade: skip all dependents of a failed task
    this.cascadeSkip(taskId);
    return false;
  }

  /**
   * Mark a task as failed WITHOUT triggering cascade skip.
   * Returns true if the task can be retried (attempts < maxAttempts).
   * Caller is responsible for calling triggerCascadeSkip() if recovery fails.
   */
  markFailedWithoutCascade(taskId: string, maxRetries: number): boolean {
    const task = this.tasks.get(taskId);
    if (!task) return false;

    if (task.attempts <= maxRetries) {
      task.status = 'ready';
      task.dispatchedAt = undefined;
      return true;
    }

    task.status = 'failed';
    task.dispatchedAt = undefined;
    // Do NOT call cascadeSkip — caller will trigger it manually after recovery attempt
    return false;
  }

  /**
   * Requeue stale dispatched tasks back to ready when no active worker owns them.
   * Returns recovered task IDs.
   */
  reconcileStaleDispatched(options: ReconcileStaleDispatchedOptions): string[] {
    const now = options.now ?? Date.now();
    const active = options.activeTaskIds ?? new Set<string>();
    const recovered: string[] = [];

    for (const task of this.tasks.values()) {
      if (task.status !== 'dispatched') continue;
      if (active.has(task.id)) continue;
      const dispatchedAt = task.dispatchedAt ?? 0;
      if (dispatchedAt <= 0 || now - dispatchedAt < options.staleAfterMs) continue;
      task.status = 'ready';
      task.dispatchedAt = undefined;
      recovered.push(task.id);
    }

    return recovered;
  }

  /**
   * Manually trigger cascade skip for a failed task's dependents.
   * Call this after resilience recovery has been attempted and failed.
   */
  triggerCascadeSkip(taskId: string): void {
    this.cascadeSkip(taskId);
  }

  /**
   * Un-skip dependents of a task that was recovered (e.g., via resilience recovery).
   * Checks if all dependencies are now satisfied and restores skipped tasks to ready.
   */
  unSkipDependents(taskId: string): void {
    for (const [, task] of this.tasks) {
      if (task.status === 'skipped' && task.dependencies.includes(taskId)) {
        const allDepsSatisfied = task.dependencies.every(depId => {
          const dep = this.tasks.get(depId);
          return dep && (dep.status === 'completed' || dep.status === 'decomposed');
        });
        if (allDepsSatisfied) {
          task.status = 'ready';
          task.dependencyContext = this.buildDependencyContext(task);
        }
      }
    }
  }

  /**
   * Cascade failure to dependent tasks, respecting partial dependency threshold.
   * Tasks with enough successful deps are kept ready/pending rather than skipped.
   */
  private cascadeSkip(failedTaskId: string): void {
    for (const [, task] of this.tasks) {
      // H5: Also handle dispatched tasks whose dependency failed
      if (task.status !== 'pending' && task.status !== 'ready' && task.status !== 'dispatched') continue;

      // Only consider direct dependents — transitive deps are handled recursively
      // when a direct dependent gets skipped (it will trigger another cascadeSkip)
      if (!this.dependsOn(task.id, failedTaskId)) continue;

      // Artifact-aware skip: before cascade-skipping, check if the failed dependency's
      // target files already exist on disk with content. If they do, the worker DID produce
      // the files even though the task "failed" (timeout, quality gate, etc.).
      if (this.artifactAwareSkip) {
        const failedTask = this.tasks.get(failedTaskId);
        const targetFiles = failedTask?.targetFiles ?? [];
        if (targetFiles.length > 0) {
          const existingCount = targetFiles.filter(f => {
            try {
              const resolved = path.resolve(this.workingDirectory, f);
              return fs.statSync(resolved).size > 0;
            } catch { return false; }
          }).length;
          if (existingCount >= targetFiles.length * 0.5) {
            // Most target files exist — treat failure as less severe, keep dependent ready
            const succeededDeps: string[] = [];
            const failedDeps: string[] = [];
            for (const depId of task.dependencies) {
              const dep = this.tasks.get(depId);
              if (!dep) continue;
              if (dep.status === 'completed') succeededDeps.push(dep.description);
              else failedDeps.push(`${dep.description} (failed but ${existingCount}/${targetFiles.length} files exist)`);
            }
            task.status = 'ready';
            task.partialContext = {
              succeeded: succeededDeps,
              failed: failedDeps,
              ratio: succeededDeps.length / task.dependencies.length,
            };
            task.dependencyContext = this.buildDependencyContext(task);
            continue;
          }
        }
      }

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

        const failedDepTasks = task.dependencies
          .map(id => this.tasks.get(id))
          .filter((d): d is SwarmTask => !!d && (d.status === 'failed' || d.status === 'skipped'));
        const effectiveThreshold = getEffectiveThreshold(failedDepTasks, this.partialDependencyThreshold);
        const ratio = completedCount / task.dependencies.length;
        if (ratio >= effectiveThreshold) {
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

      // F25c: Timeout-lenient cascade — when a dependency failed due to timeout,
      // don't cascade-skip dependents. Instead mark them ready with partial context.
      // Timeouts mean the worker was working but ran out of time — the dependent
      // worker can discover what files actually exist and compensate.
      const failedTask = this.tasks.get(failedTaskId);
      if (failedTask?.failureMode === 'timeout') {
        if (task.status === 'dispatched') {
          // Already running — don't interfere
          this.onCascadeSkipCallback?.(task.id,
            `dependency ${failedTaskId} timed out — dispatched task allowed to complete`);
          continue;
        }
        const succeededDeps: string[] = [];
        const failedDeps: string[] = [];
        for (const depId of task.dependencies) {
          const dep = this.tasks.get(depId);
          if (!dep) continue;
          if (dep.status === 'completed') succeededDeps.push(dep.description);
          else failedDeps.push(`${dep.description} (timed out — output may be incomplete)`);
        }
        task.status = 'ready';
        task.partialContext = {
          succeeded: succeededDeps,
          failed: failedDeps,
          ratio: succeededDeps.length / task.dependencies.length,
        };
        task.dependencyContext = this.buildDependencyContext(task);
        this.onCascadeSkipCallback?.(task.id,
          `dependency ${failedTaskId} timed out — proceeding with partial context`);
        continue;
      }

      // F4: For dispatched tasks (worker still running), set pendingCascadeSkip
      // instead of immediately skipping. The result will be evaluated when it arrives.
      if (task.status === 'dispatched') {
        task.pendingCascadeSkip = true;
        this.onCascadeSkipCallback?.(task.id, `dependency ${failedTaskId} failed (pending — worker still running)`);
      } else {
        task.status = 'skipped';
        this.onCascadeSkipCallback?.(task.id, `dependency ${failedTaskId} failed`);
      }
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
      return task && (task.status === 'completed' || task.status === 'failed' || task.status === 'skipped' || task.status === 'decomposed');
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
   * Replace a task with subtasks from micro-decomposition.
   * Marks original task as 'decomposed', inserts subtasks into its wave,
   * and updates dependency graph so anything depending on the original
   * now depends on ALL subtasks.
   */
  replaceWithSubtasks(originalTaskId: string, subtasks: SwarmTask[]): void {
    const original = this.tasks.get(originalTaskId);
    if (!original) return;

    original.status = 'decomposed';
    original.subtaskIds = subtasks.map(s => s.id);

    // Insert subtasks
    for (const sub of subtasks) {
      sub.parentTaskId = originalTaskId;
      // Subtasks inherit the original's dependencies
      sub.dependencies = [...original.dependencies];
      sub.wave = original.wave;
      this.tasks.set(sub.id, sub);
    }

    // Update dependency graph: anything that depended on original now depends on ALL subtasks
    for (const [, task] of this.tasks) {
      if (task.id === originalTaskId) continue;
      if (task.subtaskIds?.length) continue; // Skip the original itself
      const depIndex = task.dependencies.indexOf(originalTaskId);
      if (depIndex !== -1) {
        task.dependencies.splice(depIndex, 1, ...subtasks.map(s => s.id));
      }
    }

    // Add subtask IDs to the wave
    const waveIdx = original.wave;
    if (waveIdx < this.waves.length) {
      this.waves[waveIdx].push(...subtasks.map(s => s.id));
    }

    this.updateReadyStatus();
  }

  /**
   * Get all tasks that were cascade-skipped.
   */
  getSkippedTasks(): SwarmTask[] {
    return [...this.tasks.values()].filter(t => t.status === 'skipped');
  }

  /**
   * Un-skip a task, setting it to 'ready' with rescue context.
   */
  rescueTask(taskId: string, rescueContext: string): void {
    const task = this.tasks.get(taskId);
    if (!task || task.status !== 'skipped') return;
    task.status = 'ready';
    task.rescueContext = rescueContext;
    task.dependencyContext = this.buildDependencyContext(task);
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
        case 'decomposed': completed++; break; // Decomposed tasks count as completed (replaced by subtasks)
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
      dispatchedAt: t.dispatchedAt,
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
        task.dispatchedAt = ts.dispatchedAt;
      }
    }
  }

  /**
   * Add re-planned tasks from mid-swarm re-planning.
   * Inserts new tasks into the specified wave and marks them ready.
   */
  addReplanTasks(subtasks: Array<{ description: string; type: string; complexity: number; dependencies: string[]; relevantFiles?: string[] }>, wave: number): SwarmTask[] {
    const newTasks: SwarmTask[] = [];
    for (const st of subtasks) {
      const id = `replan-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const task: SwarmTask = {
        id,
        description: st.description,
        type: st.type as SwarmTask['type'],
        dependencies: st.dependencies,
        status: 'ready',
        complexity: Math.max(3, st.complexity),
        wave,
        targetFiles: st.relevantFiles,
        attempts: 1,
        rescueContext: 'Re-planned from stalled swarm',
      };
      this.tasks.set(id, task);
      newTasks.push(task);
    }
    // Add to wave
    if (!this.waves[wave]) this.waves[wave] = [];
    this.waves[wave].push(...newTasks.map(t => t.id));
    return newTasks;
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
