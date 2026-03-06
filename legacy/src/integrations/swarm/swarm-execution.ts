/**
 * Swarm Execution — Task dispatch loop, wave management, and completion handling.
 *
 * Extracted from swarm-orchestrator.ts (Phase 3a).
 * Contains: executeWaves, executeWave, dispatchTask, handleTaskCompletion.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { SwarmConfig, SwarmTask, SwarmTaskResult, WorkerCapability } from './types.js';
import { getTaskTypeConfig } from './types.js';
import { selectAlternativeModel } from './model-selector.js';
import {
  evaluateWorkerOutput,
  runPreFlightChecks,
  checkArtifacts,
  checkArtifactsEnhanced,
  runConcreteChecks,
  type QualityGateConfig,
} from './swarm-quality-gate.js';
import { classifySwarmFailure } from './failure-classifier.js';
import type { SpawnResult } from '../agents/agent-registry.js';
import type { OrchestratorInternals } from './swarm-orchestrator.js';
import {
  isHollowCompletion,
  FAILURE_INDICATORS,
  hasFutureIntentLanguage,
} from './swarm-helpers.js';
import {
  reviewWave,
  saveCheckpoint,
  emitBudgetUpdate,
  getEffectiveRetries,
  getSwarmProgressSummary,
  getModelHealthSummary,
  extractFileArtifacts,
} from './swarm-lifecycle.js';
import type { SwarmRecoveryState } from './swarm-recovery.js';
import {
  tryResilienceRecovery,
  rescueCascadeSkipped,
  assessAndAdapt,
  shouldAutoSplit,
  judgeSplit,
  recordRateLimit,
  isCircuitBreakerActive,
  increaseStagger,
  decreaseStagger,
  getStaggerMs,
} from './swarm-recovery.js';

// ─── Wave Execution ─────────────────────────────────────────────────────

/**
 * Execute all waves in sequence, with review after each.
 */
export async function executeWaves(
  ctx: OrchestratorInternals,
  recoveryState: SwarmRecoveryState,
  getStatus: () => import('./types.js').SwarmStatus,
): Promise<void> {
  let waveIndex = ctx.taskQueue.getCurrentWave();
  const totalWaves = ctx.taskQueue.getTotalWaves();
  const dispatchLeaseStaleMs = ctx.config.dispatchLeaseStaleMs ?? 5 * 60 * 1000;

  while (waveIndex < totalWaves && !ctx.cancelled) {
    const activeTaskIds = new Set(ctx.workerPool.getActiveWorkerStatus().map((w) => w.taskId));
    const recovered = ctx.taskQueue.reconcileStaleDispatched({
      staleAfterMs: dispatchLeaseStaleMs,
      activeTaskIds,
    });
    if (recovered.length > 0) {
      ctx.logDecision(
        'lease-recovery',
        `Recovered ${recovered.length} stale dispatched task(s)`,
        recovered.join(', '),
      );
    }
    const readyTasks = ctx.taskQueue.getReadyTasks();
    const queueStats = ctx.taskQueue.getStats();

    // F18: Skip empty waves
    if (readyTasks.length === 0 && queueStats.running === 0 && queueStats.ready === 0) {
      ctx.logDecision(
        'wave-skip',
        `Skipping waves ${waveIndex + 1}-${totalWaves}: no dispatchable tasks remain`,
        `Stats: ${queueStats.completed} completed, ${queueStats.failed} failed, ${queueStats.skipped} skipped`,
      );
      break;
    }

    ctx.emit({
      type: 'swarm.wave.start',
      wave: waveIndex + 1,
      totalWaves,
      taskCount: readyTasks.length,
    });

    // Dispatch tasks up to concurrency limit
    await executeWave(ctx, recoveryState, readyTasks, getStatus);

    // Wave complete stats
    const afterStats = ctx.taskQueue.getStats();
    const waveCompleted = afterStats.completed - queueStats.completed;
    const waveFailed = afterStats.failed - queueStats.failed;
    const waveSkipped = afterStats.skipped - queueStats.skipped;

    ctx.emit({
      type: 'swarm.wave.complete',
      wave: waveIndex + 1,
      totalWaves,
      completed: waveCompleted,
      failed: waveFailed,
      skipped: waveSkipped,
    });

    // Wave failure recovery: if ALL tasks in a wave failed, retry with adapted context
    if (waveCompleted === 0 && waveFailed > 0 && readyTasks.length > 0) {
      ctx.emit({ type: 'swarm.wave.allFailed', wave: waveIndex + 1 });
      ctx.logDecision(
        'wave-recovery',
        `Entire wave ${waveIndex + 1} failed (${waveFailed} tasks)`,
        'Checking if budget allows retry with adapted strategy',
      );

      const budgetRemaining = ctx.budgetPool.hasCapacity();
      const failedWaveTasks = readyTasks.filter((t) => {
        const task = ctx.taskQueue.getTask(t.id);
        return task && task.status === 'failed' && task.attempts < ctx.config.workerRetries + 1;
      });

      if (budgetRemaining && failedWaveTasks.length > 0) {
        for (const t of failedWaveTasks) {
          const task = ctx.taskQueue.getTask(t.id);
          if (!task) continue;
          task.status = 'ready';
          task.retryContext = {
            previousFeedback:
              'All tasks in this batch failed. Try a fundamentally different approach — the previous strategy did not work.',
            previousScore: 0,
            attempt: task.attempts,
            previousModel: task.assignedModel,
            swarmProgress: getSwarmProgressSummary(ctx),
          };
        }
        ctx.logDecision(
          'wave-recovery',
          `Re-queued ${failedWaveTasks.length} tasks with adapted retry context`,
          'Budget allows retry',
        );
        await executeWave(
          ctx,
          recoveryState,
          failedWaveTasks
            .map((t) => ctx.taskQueue.getTask(t.id)!)
            .filter((t) => t.status === 'ready'),
          getStatus,
        );
      }
    }

    // F5: Adaptive re-decomposition signal
    const waveTotal = waveCompleted + waveFailed + waveSkipped;
    const waveSuccessRate = waveTotal > 0 ? waveCompleted / waveTotal : 0;
    if (waveSuccessRate < 0.5 && waveTotal >= 2) {
      ctx.logDecision(
        'decomposition-quality',
        `Wave ${waveIndex + 1} success rate ${(waveSuccessRate * 100).toFixed(0)}% (${waveCompleted}/${waveTotal})`,
        'Low success rate may indicate decomposition quality issues',
      );
    }

    // V2: Review wave outputs
    const review = await reviewWave(ctx, waveIndex);
    if (review && review.fixupTasks.length > 0) {
      await executeWave(ctx, recoveryState, review.fixupTasks, getStatus);
    }

    // Rescue cascade-skipped tasks that can still run
    const rescued = rescueCascadeSkipped(ctx);
    if (rescued.length > 0) {
      ctx.logDecision(
        'cascade-rescue',
        `Rescued ${rescued.length} cascade-skipped tasks after wave ${waveIndex + 1}`,
        rescued.map((t) => t.id).join(', '),
      );
      await executeWave(ctx, recoveryState, rescued, getStatus);
    }

    // Reset quality circuit breaker at wave boundary
    if (recoveryState.qualityGateDisabledModels.size > 0) {
      recoveryState.qualityGateDisabledModels.clear();
      recoveryState.perModelQualityRejections.clear();
      ctx.logDecision(
        'quality-circuit-breaker',
        `Re-enabled quality gates for all models at wave ${waveIndex + 1} boundary`,
        'Each wave gets a fresh quality evaluation window',
      );
    }

    // F3: Log budget reallocation after wave completion
    const budgetStats = ctx.budgetPool.getStats();
    ctx.logDecision(
      'budget-reallocation',
      `After wave ${waveIndex + 1}: ${budgetStats.tokensRemaining} tokens remaining (${(budgetStats.utilization * 100).toFixed(0)}% utilized)`,
      '',
    );
    ctx.budgetPool.reallocateUnused(budgetStats.tokensRemaining);

    // F21: Mid-swarm situational assessment
    await assessAndAdapt(ctx, recoveryState, waveIndex);

    // V2: Checkpoint after each wave
    saveCheckpoint(ctx, `wave-${waveIndex}`);

    // Advance to next wave
    if (!ctx.taskQueue.advanceWave()) break;
    waveIndex++;
  }
}

/**
 * Execute a single wave's tasks with concurrency control.
 */
export async function executeWave(
  ctx: OrchestratorInternals,
  recoveryState: SwarmRecoveryState,
  tasks: SwarmTask[],
  getStatus: () => import('./types.js').SwarmStatus,
): Promise<void> {
  // Dispatch initial batch with stagger
  let taskIndex = 0;
  while (taskIndex < tasks.length && ctx.workerPool.availableSlots > 0 && !ctx.cancelled) {
    if (isCircuitBreakerActive(recoveryState, ctx)) {
      const waitMs = recoveryState.circuitBreakerUntil - Date.now();
      if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs));
      continue;
    }

    const task = tasks[taskIndex];
    await dispatchTask(ctx, recoveryState, task, getStatus);
    taskIndex++;

    if (taskIndex < tasks.length && ctx.workerPool.availableSlots > 0) {
      await new Promise((resolve) => setTimeout(resolve, getStaggerMs(recoveryState)));
    }
  }

  // Process completions and dispatch more tasks as slots open
  while (ctx.workerPool.activeCount > 0 && !ctx.cancelled) {
    const completed = await ctx.workerPool.waitForAny();
    if (!completed) break;

    await handleTaskCompletion(
      ctx,
      recoveryState,
      completed.taskId,
      completed.result,
      completed.startedAt,
      getStatus,
    );

    emitBudgetUpdate(ctx);
    ctx.emit({ type: 'swarm.status', status: getStatus() });

    // Dispatch more tasks if slots available and tasks remain
    while (taskIndex < tasks.length && ctx.workerPool.availableSlots > 0 && !ctx.cancelled) {
      const task = tasks[taskIndex];
      if (task.status === 'ready') {
        await dispatchTask(ctx, recoveryState, task, getStatus);
        if (taskIndex + 1 < tasks.length && ctx.workerPool.availableSlots > 0) {
          await new Promise((resolve) => setTimeout(resolve, getStaggerMs(recoveryState)));
        }
      }
      taskIndex++;
    }

    // Also check for cross-wave ready tasks to fill slots
    if (ctx.workerPool.availableSlots > 0 && !isCircuitBreakerActive(recoveryState, ctx)) {
      const moreReady = ctx.taskQueue
        .getAllReadyTasks()
        .filter((t) => !ctx.workerPool.getActiveWorkerStatus().some((w) => w.taskId === t.id));

      for (let i = 0; i < moreReady.length; i++) {
        if (ctx.workerPool.availableSlots <= 0) break;
        await dispatchTask(ctx, recoveryState, moreReady[i], getStatus);
        if (i + 1 < moreReady.length && ctx.workerPool.availableSlots > 0) {
          await new Promise((resolve) => setTimeout(resolve, getStaggerMs(recoveryState)));
        }
      }
    }
  }

  // F20: Re-dispatch pass — after all workers finish, budget may have been freed
  if (!ctx.cancelled && ctx.budgetPool.hasCapacity()) {
    const stillReady = ctx.taskQueue
      .getAllReadyTasks()
      .filter((t) => !ctx.workerPool.getActiveWorkerStatus().some((w) => w.taskId === t.id));

    if (stillReady.length > 0) {
      ctx.logDecision(
        'budget-redispatch',
        `Budget freed after wave — re-dispatching ${stillReady.length} ready task(s)`,
        `Budget: ${JSON.stringify(ctx.budgetPool.getStats())}`,
      );

      for (const task of stillReady) {
        if (ctx.workerPool.availableSlots <= 0 || !ctx.budgetPool.hasCapacity()) break;
        await dispatchTask(ctx, recoveryState, task, getStatus);
        if (ctx.workerPool.availableSlots > 0) {
          await new Promise((resolve) => setTimeout(resolve, getStaggerMs(recoveryState)));
        }
      }

      while (ctx.workerPool.activeCount > 0 && !ctx.cancelled) {
        const completed = await ctx.workerPool.waitForAny();
        if (!completed) break;
        await handleTaskCompletion(
          ctx,
          recoveryState,
          completed.taskId,
          completed.result,
          completed.startedAt,
          getStatus,
        );
        emitBudgetUpdate(ctx);
        ctx.emit({ type: 'swarm.status', status: getStatus() });
      }
    }
  }
}

// ─── Task Dispatch ──────────────────────────────────────────────────────

/**
 * Dispatch a single task to a worker.
 */
export async function dispatchTask(
  ctx: OrchestratorInternals,
  recoveryState: SwarmRecoveryState,
  task: SwarmTask,
  _getStatus: () => import('./types.js').SwarmStatus,
): Promise<void> {
  const worker = ctx.workerPool.selectWorker(task);
  if (!worker) {
    ctx.logDecision('no-worker', `${task.id}: no worker for type ${task.type}`, '');
    if (task.attempts > 0) {
      const syntheticTaskResult: SwarmTaskResult = {
        success: false,
        output: '',
        tokensUsed: 0,
        costUsed: 0,
        durationMs: 0,
        model: 'none',
      };
      const syntheticSpawn: SpawnResult = {
        success: false,
        output: '',
        metrics: { tokens: 0, duration: 0, toolCalls: 0 },
      };
      if (
        await tryResilienceRecovery(
          ctx,
          recoveryState,
          task,
          task.id,
          syntheticTaskResult,
          syntheticSpawn,
        )
      ) {
        return;
      }
    }
    ctx.taskQueue.markFailedWithoutCascade(task.id, 0);
    ctx.taskQueue.triggerCascadeSkip(task.id);
    ctx.emit({
      type: 'swarm.task.failed',
      taskId: task.id,
      error: `No worker available for task type: ${task.type}`,
      attempt: task.attempts,
      maxAttempts: 0,
      willRetry: false,
      failureMode: 'error',
    });
    return;
  }

  try {
    // Pre-dispatch auto-split for critical-path bottlenecks
    if (shouldAutoSplit(ctx, task)) {
      try {
        const splitResult = await judgeSplit(ctx, task);
        if (splitResult.shouldSplit && splitResult.subtasks) {
          task.status = 'dispatched';
          ctx.taskQueue.replaceWithSubtasks(task.id, splitResult.subtasks);
          ctx.emit({
            type: 'swarm.task.resilience',
            taskId: task.id,
            strategy: 'auto-split',
            succeeded: true,
            reason: `Pre-dispatch split into ${splitResult.subtasks.length} parallel subtasks`,
            artifactsFound: 0,
            toolCalls: 0,
          });
          return;
        }
      } catch (err) {
        ctx.logDecision(
          'auto-split',
          `${task.id}: split judge failed — ${(err as Error).message}`,
          '',
        );
      }
    }

    ctx.totalDispatches++;
    const dispatchedModel = task.assignedModel ?? worker.model;
    ctx.taskQueue.markDispatched(task.id, dispatchedModel);
    if (task.assignedModel && task.assignedModel !== worker.model) {
      ctx.logDecision(
        'failover',
        `Dispatching ${task.id} with failover model ${task.assignedModel} (worker default: ${worker.model})`,
        'Retry model override is active',
      );
    }
    await ctx.workerPool.dispatch(task, worker);

    ctx.emit({
      type: 'swarm.task.dispatched',
      taskId: task.id,
      description: task.description,
      model: dispatchedModel,
      workerName: worker.name,
      toolCount: worker.allowedTools?.length ?? -1,
      tools: worker.allowedTools,
      retryContext: task.retryContext,
      fromModel: task.retryContext ? task.retryContext.previousModel : undefined,
      attempts: task.attempts,
    });
  } catch (error) {
    const errorMsg = (error as Error).message;

    // F20: Budget exhaustion is NOT a task failure
    if (errorMsg.includes('Budget pool exhausted')) {
      task.status = 'ready';
      ctx.logDecision(
        'budget-pause',
        `Cannot dispatch ${task.id}: budget exhausted — task kept ready for potential re-dispatch`,
        `Budget stats: ${JSON.stringify(ctx.budgetPool.getStats())}`,
      );
      return;
    }

    ctx.errors.push({
      taskId: task.id,
      phase: 'dispatch',
      message: errorMsg,
      recovered: false,
    });
    ctx.logDecision(
      'dispatch-error',
      `${task.id}: dispatch failed: ${errorMsg.slice(0, 100)}`,
      `attempts: ${task.attempts}`,
    );

    if (task.attempts > 0) {
      const syntheticTaskResult: SwarmTaskResult = {
        success: false,
        output: '',
        tokensUsed: 0,
        costUsed: 0,
        durationMs: 0,
        model: 'none',
      };
      const syntheticSpawn: SpawnResult = {
        success: false,
        output: '',
        metrics: { tokens: 0, duration: 0, toolCalls: 0 },
      };
      if (
        await tryResilienceRecovery(
          ctx,
          recoveryState,
          task,
          task.id,
          syntheticTaskResult,
          syntheticSpawn,
        )
      ) {
        ctx.errors[ctx.errors.length - 1].recovered = true;
        return;
      }
    }

    ctx.taskQueue.markFailedWithoutCascade(task.id, 0);
    ctx.taskQueue.triggerCascadeSkip(task.id);
    ctx.emit({
      type: 'swarm.task.failed',
      taskId: task.id,
      error: errorMsg,
      attempt: task.attempts,
      maxAttempts: 1 + ctx.config.workerRetries,
      willRetry: false,
      failureMode: 'error',
    });
  }
}

// ─── Task Completion Handling ───────────────────────────────────────────

/**
 * Handle a completed task: quality gate, bookkeeping, retry logic, model health, failover.
 */
export async function handleTaskCompletion(
  ctx: OrchestratorInternals,
  recoveryState: SwarmRecoveryState,
  taskId: string,
  spawnResult: SpawnResult,
  startedAt: number,
  _getStatus: () => import('./types.js').SwarmStatus,
): Promise<void> {
  const task = ctx.taskQueue.getTask(taskId);
  if (!task) return;

  // Guard: task was terminally resolved while its worker was running
  if ((task.status === 'skipped' || task.status === 'failed') && !task.pendingCascadeSkip) return;

  // V7: Global dispatch cap
  const maxDispatches = ctx.config.maxDispatchesPerTask ?? 5;
  if (task.attempts >= maxDispatches) {
    const durationMs = Date.now() - startedAt;
    const taskResult = ctx.workerPool.toTaskResult(spawnResult, task, durationMs);
    ctx.totalTokens += taskResult.tokensUsed;
    ctx.totalCost += taskResult.costUsed;

    if (await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)) {
      return;
    }

    ctx.taskQueue.markFailedWithoutCascade(taskId, 0);
    ctx.taskQueue.triggerCascadeSkip(taskId);
    ctx.emit({
      type: 'swarm.task.failed',
      taskId,
      error: `Dispatch cap reached (${maxDispatches} attempts)`,
      attempt: task.attempts,
      maxAttempts: maxDispatches,
      willRetry: false,
      failureMode: task.failureMode,
    });
    ctx.logDecision(
      'dispatch-cap',
      `${taskId}: hard cap reached (${task.attempts}/${maxDispatches})`,
      'No more retries — resilience recovery also failed',
    );
    return;
  }

  const durationMs = Date.now() - startedAt;
  const taskResult = ctx.workerPool.toTaskResult(spawnResult, task, durationMs);

  // Track model usage
  const model = task.assignedModel ?? 'unknown';
  const usage = ctx.modelUsage.get(model) ?? { tasks: 0, tokens: 0, cost: 0 };
  usage.tasks++;
  usage.tokens += taskResult.tokensUsed;
  usage.cost += taskResult.costUsed;
  ctx.modelUsage.set(model, usage);

  ctx.totalTokens += taskResult.tokensUsed;
  ctx.totalCost += taskResult.costUsed;

  if (taskResult.budgetUtilization) {
    ctx.logDecision(
      'budget-utilization',
      `${taskId}: token ${taskResult.budgetUtilization.tokenPercent}%, iter ${taskResult.budgetUtilization.iterationPercent}%`,
      `model=${model}, tokens=${taskResult.tokensUsed}, duration=${durationMs}ms`,
    );
  }

  // V10: Emit per-attempt event
  ctx.emit({
    type: 'swarm.task.attempt',
    taskId,
    attempt: task.attempts,
    model,
    success: spawnResult.success,
    durationMs,
    toolCalls: spawnResult.metrics.toolCalls ?? 0,
    failureMode: !spawnResult.success ? task.failureMode : undefined,
    qualityScore: taskResult.qualityScore,
    output: taskResult.output.slice(0, 500),
  });

  if (!spawnResult.success) {
    return handleFailedCompletion(
      ctx,
      recoveryState,
      task,
      taskId,
      spawnResult,
      taskResult,
      model,
      durationMs,
      startedAt,
      maxDispatches,
    );
  }

  // V6: Hollow completion detection
  if (isHollowCompletion(spawnResult, task.type, ctx.config)) {
    return handleHollowCompletion(
      ctx,
      recoveryState,
      task,
      taskId,
      spawnResult,
      taskResult,
      model,
      maxDispatches,
    );
  }

  // F4: Task had pendingCascadeSkip but produced non-hollow results
  if (task.pendingCascadeSkip) {
    const cachedReport = checkArtifacts(task);
    const preFlight = runPreFlightChecks(task, taskResult, ctx.config, cachedReport);
    if (preFlight && !preFlight.passed) {
      task.pendingCascadeSkip = undefined;
      task.status = 'skipped';
      ctx.logDecision(
        'cascade-skip',
        `${taskId}: pending cascade skip honored (pre-flight failed: ${preFlight.feedback})`,
        '',
      );
      ctx.emit({
        type: 'swarm.task.skipped',
        taskId,
        reason: `cascade skip honored — output failed pre-flight: ${preFlight.feedback}`,
      });
      return;
    }
    task.pendingCascadeSkip = undefined;
    task.status = 'dispatched';
    ctx.logDecision(
      'cascade-skip',
      `${taskId}: pending cascade skip overridden — worker produced valid output`,
      '',
    );
  }

  // Record model health on success
  ctx.healthTracker.recordSuccess(model, durationMs);
  decreaseStagger(recoveryState);

  // Run quality gate if enabled
  const effectiveRetries = getEffectiveRetries(ctx, task);
  const recentRLCount = recoveryState.recentRateLimits.filter(
    (t) => t > Date.now() - 30_000,
  ).length;
  const isLastAttempt = task.attempts >= effectiveRetries + 1;
  const shouldRunQualityGate =
    ctx.config.qualityGates &&
    !recoveryState.qualityGateDisabledModels.has(model) &&
    !isLastAttempt &&
    Date.now() >= recoveryState.circuitBreakerUntil &&
    recentRLCount < 2;

  const cachedArtifactReport = checkArtifacts(task);

  if (shouldRunQualityGate) {
    const rejected = await runQualityGate(
      ctx,
      recoveryState,
      task,
      taskId,
      spawnResult,
      taskResult,
      model,
      effectiveRetries,
      cachedArtifactReport,
    );
    if (rejected) return;
  }

  // F7: When quality gate was skipped, still run pre-flight + concrete checks
  if (!shouldRunQualityGate && ctx.config.qualityGates) {
    const preFlight = runPreFlightChecks(task, taskResult, ctx.config, cachedArtifactReport);
    if (preFlight && !preFlight.passed) {
      taskResult.qualityScore = preFlight.score;
      taskResult.qualityFeedback = preFlight.feedback;
      ctx.qualityRejections++;
      const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
      if (canRetry) {
        ctx.retries++;
      } else {
        ctx.logDecision(
          'preflight-reject',
          `${taskId}: pre-flight failed: ${preFlight.feedback}`,
          '',
        );
        if (
          await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)
        ) {
          return;
        }
        ctx.taskQueue.triggerCascadeSkip(taskId);
      }
      ctx.emit({
        type: 'swarm.quality.rejected',
        taskId,
        score: preFlight.score,
        feedback: preFlight.feedback,
        artifactCount: 0,
        outputLength: taskResult.output.length,
        preFlightReject: true,
      });
      return;
    }

    // F2: Run concrete validation when pre-flight passes but gate was skipped
    if (ctx.config.enableConcreteValidation !== false) {
      const concreteResult = runConcreteChecks(task, taskResult);
      if (!concreteResult.passed) {
        taskResult.qualityScore = 2;
        taskResult.qualityFeedback = `Concrete validation failed: ${concreteResult.issues.join('; ')}`;
        ctx.qualityRejections++;
        const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
        if (canRetry) {
          ctx.retries++;
        } else {
          ctx.logDecision(
            'concrete-reject',
            `${taskId}: concrete validation failed: ${concreteResult.issues.join('; ')}`,
            '',
          );
          if (
            await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)
          ) {
            return;
          }
          ctx.taskQueue.triggerCascadeSkip(taskId);
        }
        ctx.emit({
          type: 'swarm.quality.rejected',
          taskId,
          score: 2,
          feedback: taskResult.qualityFeedback,
          artifactCount: 0,
          outputLength: taskResult.output.length,
          preFlightReject: false,
        });
        return;
      }
    }
  }

  // Final completion guard: block "narrative success" for action tasks
  const completionGuard = ctx.config.completionGuard ?? {};
  const rejectFutureIntentOutputs = completionGuard.rejectFutureIntentOutputs ?? true;
  const requireConcreteArtifactsForActionTasks =
    completionGuard.requireConcreteArtifactsForActionTasks ?? true;
  const typeConfig = getTaskTypeConfig(task.type, ctx.config);
  const artifactReport = checkArtifactsEnhanced(task, taskResult);
  const filesOnDisk = artifactReport.files.filter((f) => f.exists && f.sizeBytes > 0).length;
  const hasConcreteArtifacts = filesOnDisk > 0 || (taskResult.filesModified?.length ?? 0) > 0;
  const isActionTask = !!typeConfig.requiresToolCalls;

  if (rejectFutureIntentOutputs && hasFutureIntentLanguage(taskResult.output ?? '')) {
    taskResult.qualityScore = 1;
    taskResult.qualityFeedback = 'Completion rejected: output indicates pending, unexecuted work';
    const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
    if (canRetry) {
      ctx.retries++;
    } else {
      if (await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)) {
        return;
      }
      ctx.taskQueue.triggerCascadeSkip(taskId);
    }
    ctx.emit({
      type: 'swarm.quality.rejected',
      taskId,
      score: 1,
      feedback: taskResult.qualityFeedback,
      artifactCount: filesOnDisk,
      outputLength: taskResult.output.length,
      preFlightReject: true,
      filesOnDisk,
    });
    return;
  }

  if (requireConcreteArtifactsForActionTasks && isActionTask && !hasConcreteArtifacts) {
    taskResult.qualityScore = 1;
    taskResult.qualityFeedback = 'Completion rejected: action task produced no concrete artifacts';
    const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
    if (canRetry) {
      ctx.retries++;
    } else {
      if (await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)) {
        return;
      }
      ctx.taskQueue.triggerCascadeSkip(taskId);
    }
    ctx.emit({
      type: 'swarm.quality.rejected',
      taskId,
      score: 1,
      feedback: taskResult.qualityFeedback,
      artifactCount: filesOnDisk,
      outputLength: taskResult.output.length,
      preFlightReject: true,
      filesOnDisk,
    });
    return;
  }

  // Task passed — mark completed
  ctx.taskQueue.markCompleted(taskId, taskResult);
  ctx.hollowStreak = 0;
  recoveryState.taskTimeoutCounts.delete(taskId);

  // H6: Post findings to blackboard
  if (ctx.blackboard && taskResult.findings) {
    try {
      for (const finding of taskResult.findings) {
        ctx.blackboard.post(`swarm-worker-${taskId}`, {
          topic: `swarm.task.${task.type}`,
          content: finding,
          type: 'progress',
          confidence: (taskResult.qualityScore ?? 3) / 5,
          tags: ['swarm', task.type],
          relatedFiles: task.targetFiles,
        });
      }
    } catch {
      ctx.errors.push({
        taskId,
        phase: 'execution',
        message: 'Failed to post findings to blackboard',
        recovered: true,
      });
    }
  }

  ctx.emit({
    type: 'swarm.task.completed',
    taskId,
    success: true,
    tokensUsed: taskResult.tokensUsed,
    costUsed: taskResult.costUsed,
    durationMs: taskResult.durationMs,
    qualityScore: taskResult.qualityScore,
    qualityFeedback: taskResult.qualityFeedback,
    output: taskResult.output,
    closureReport: taskResult.closureReport,
    toolCalls: spawnResult.metrics.toolCalls,
  });
}

// ─── Internal Helpers ───────────────────────────────────────────────────

/**
 * Handle the case where a worker fails (spawnResult.success === false).
 */
async function handleFailedCompletion(
  ctx: OrchestratorInternals,
  recoveryState: SwarmRecoveryState,
  task: SwarmTask,
  taskId: string,
  spawnResult: SpawnResult,
  taskResult: SwarmTaskResult,
  model: string,
  durationMs: number,
  startedAt: number,
  maxDispatches: number,
): Promise<void> {
  const failure = classifySwarmFailure(spawnResult.output, spawnResult.metrics.toolCalls);
  const { failureClass, retryable, errorType, failureMode, reason } = failure;
  const isTimeout = failureMode === 'timeout';
  const isRateLimited = failureClass === 'rate_limited';
  const isSpendLimit = failureClass === 'provider_spend_limit';
  const isNonRetryable = !retryable;
  ctx.healthTracker.recordFailure(model, errorType);
  ctx.emit({ type: 'swarm.model.health', record: { model, ...getModelHealthSummary(ctx, model) } });

  task.failureMode = failureMode;

  if (isRateLimited) {
    recordRateLimit(recoveryState, ctx);
  }

  // F25a: Consecutive timeout tracking
  if (isTimeout) {
    const count = (recoveryState.taskTimeoutCounts.get(taskId) ?? 0) + 1;
    recoveryState.taskTimeoutCounts.set(taskId, count);
    const timeoutLimit = ctx.config.consecutiveTimeoutLimit ?? 3;
    ctx.logDecision(
      'timeout-tracking',
      `${taskId}: consecutive timeout ${count}/${timeoutLimit}`,
      '',
    );

    if (count >= timeoutLimit) {
      let failoverSucceeded = false;
      if (ctx.config.enableModelFailover) {
        const capability: WorkerCapability =
          getTaskTypeConfig(task.type, ctx.config).capability ?? 'code';
        const alternative = selectAlternativeModel(
          ctx.config.workers,
          model,
          capability,
          ctx.healthTracker,
        );
        if (alternative) {
          ctx.emit({
            type: 'swarm.model.failover',
            taskId,
            fromModel: model,
            toModel: alternative.model,
            reason: 'consecutive-timeouts',
          });
          task.assignedModel = alternative.model;
          recoveryState.taskTimeoutCounts.set(taskId, 0);
          ctx.logDecision(
            'failover',
            `Timeout failover ${taskId}: ${model} → ${alternative.model}`,
            `${count} consecutive timeouts`,
          );
          failoverSucceeded = true;
        }
      }

      if (!failoverSucceeded) {
        task.failureMode = 'timeout';
        const timeoutTaskResult = ctx.workerPool.toTaskResult(
          spawnResult,
          task,
          Date.now() - startedAt,
        );
        if (
          await tryResilienceRecovery(
            ctx,
            recoveryState,
            task,
            taskId,
            timeoutTaskResult,
            spawnResult,
          )
        ) {
          recoveryState.taskTimeoutCounts.delete(taskId);
          return;
        }

        ctx.taskQueue.markFailedWithoutCascade(taskId, 0);
        ctx.taskQueue.triggerCascadeSkip(taskId);
        ctx.emit({
          type: 'swarm.task.failed',
          taskId,
          error: `${count} consecutive timeouts — no alternative model available`,
          attempt: task.attempts,
          maxAttempts: maxDispatches,
          willRetry: false,
          failureMode: 'timeout',
          failureClass: 'timeout',
          retrySuppressed: true,
          retryReason: 'Consecutive timeout limit reached with no alternative model',
        });
        ctx.logDecision(
          'timeout-early-fail',
          `${taskId}: ${count} consecutive timeouts, no alt model — resilience recovery also failed`,
          '',
        );
        recoveryState.taskTimeoutCounts.delete(taskId);
        return;
      }
    }
  } else {
    recoveryState.taskTimeoutCounts.delete(taskId);
  }

  // V2: Model failover on retryable rate limits
  if (isRateLimited && ctx.config.enableModelFailover) {
    const capability: WorkerCapability =
      getTaskTypeConfig(task.type, ctx.config).capability ?? 'code';
    const alternative = selectAlternativeModel(
      ctx.config.workers,
      model,
      capability,
      ctx.healthTracker,
    );
    if (alternative) {
      ctx.emit({
        type: 'swarm.model.failover',
        taskId,
        fromModel: model,
        toModel: alternative.model,
        reason: errorType,
      });
      task.assignedModel = alternative.model;
      ctx.logDecision(
        'failover',
        `Switched ${taskId} from ${model} to ${alternative.model}`,
        `${errorType} error`,
      );
    }
  }

  // V5/V7: Store error context so retry gets different prompt
  if (!(isRateLimited || isSpendLimit)) {
    const timeoutSeconds = isTimeout ? Math.round(durationMs / 1000) : 0;
    task.retryContext = {
      previousFeedback: isTimeout
        ? `Previous attempt timed out after ${timeoutSeconds}s. You must complete this task more efficiently — work faster, use fewer tool calls, and produce your result sooner.`
        : spawnResult.output.slice(0, 2000),
      previousScore: 0,
      attempt: task.attempts,
      previousModel: model,
      previousFiles: taskResult.filesModified,
      swarmProgress: getSwarmProgressSummary(ctx),
    };
    ctx.sharedContextEngine.reportFailure(taskId, {
      action: task.description.slice(0, 200),
      error: spawnResult.output.slice(0, 500),
    });
  }

  // V7: Reset hollow streak on non-hollow failure
  ctx.hollowStreak = 0;

  // Worker failed — use higher retry limit for rate limit errors
  const baseRetries = getEffectiveRetries(ctx, task);
  const retryLimit = isNonRetryable
    ? 0
    : isRateLimited
      ? Math.min(ctx.config.rateLimitRetries ?? 3, baseRetries + 1)
      : baseRetries;
  const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, retryLimit);
  if (isNonRetryable) {
    ctx.logDecision('retry-suppressed', `${taskId}: ${failureClass}`, reason);
  }
  if (canRetry) {
    ctx.retries++;

    if (isRateLimited) {
      const baseDelay = ctx.config.retryBaseDelayMs ?? 5000;
      const cooldownMs = Math.min(baseDelay * Math.pow(2, task.attempts - 1), 30000);
      ctx.taskQueue.setRetryAfter(taskId, cooldownMs);
      ctx.logDecision(
        'rate-limit-cooldown',
        `${taskId}: ${errorType} cooldown ${cooldownMs}ms, model ${model}`,
        '',
      );
    }
  } else if (!isRateLimited) {
    if (await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)) {
      return;
    }
    ctx.taskQueue.triggerCascadeSkip(taskId);
  } else {
    ctx.taskQueue.triggerCascadeSkip(taskId);
  }

  ctx.emit({
    type: 'swarm.task.failed',
    taskId,
    error: spawnResult.output.slice(0, 200),
    attempt: task.attempts,
    maxAttempts: 1 + ctx.config.workerRetries,
    willRetry: canRetry,
    toolCalls: spawnResult.metrics.toolCalls,
    failoverModel: task.assignedModel !== model ? task.assignedModel : undefined,
    failureMode: task.failureMode,
    failureClass,
    retrySuppressed: isNonRetryable,
    retryReason: reason,
  });
}

/**
 * Handle hollow completion — workers that "succeed" without doing any work.
 */
async function handleHollowCompletion(
  ctx: OrchestratorInternals,
  recoveryState: SwarmRecoveryState,
  task: SwarmTask,
  taskId: string,
  spawnResult: SpawnResult,
  taskResult: SwarmTaskResult,
  model: string,
  maxDispatches: number,
): Promise<void> {
  // F4: Hollow result + pendingCascadeSkip
  if (task.pendingCascadeSkip) {
    task.pendingCascadeSkip = undefined;
    task.status = 'skipped';
    ctx.totalHollows++;
    ctx.logDecision(
      'cascade-skip',
      `${taskId}: pending cascade skip honored (hollow completion)`,
      '',
    );
    ctx.emit({
      type: 'swarm.task.skipped',
      taskId,
      reason: 'cascade skip honored — hollow completion',
    });
    return;
  }

  task.failureMode = 'hollow';
  ctx.healthTracker.recordHollow(model);

  const admitsFailure =
    spawnResult.success &&
    FAILURE_INDICATORS.some((f) => (spawnResult.output ?? '').toLowerCase().includes(f));
  task.retryContext = {
    previousFeedback: admitsFailure
      ? 'Previous attempt reported success but admitted failure (e.g., "budget exhausted", "unable to complete"). You MUST execute tool calls and produce concrete output this time.'
      : 'Previous attempt produced no meaningful output. Try again with a concrete approach.',
    previousScore: 1,
    attempt: task.attempts,
    previousModel: model,
    previousFiles: taskResult.filesModified,
    swarmProgress: getSwarmProgressSummary(ctx),
  };
  ctx.sharedContextEngine.reportFailure(taskId, {
    action: task.description.slice(0, 200),
    error: 'Hollow completion: worker produced no meaningful output',
  });

  // Model failover for hollow completions
  if (ctx.config.enableModelFailover) {
    const capability: WorkerCapability =
      getTaskTypeConfig(task.type, ctx.config).capability ?? 'code';
    const alternative = selectAlternativeModel(
      ctx.config.workers,
      model,
      capability,
      ctx.healthTracker,
    );
    if (alternative) {
      ctx.emit({
        type: 'swarm.model.failover',
        taskId,
        fromModel: model,
        toModel: alternative.model,
        reason: 'hollow-completion',
      });
      task.assignedModel = alternative.model;
      ctx.logDecision(
        'failover',
        `Hollow failover ${taskId}: ${model} → ${alternative.model}`,
        'Model produced hollow completion',
      );
    }
  }

  const hollowRetries = getEffectiveRetries(ctx, task);
  const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, hollowRetries);
  if (canRetry) {
    ctx.retries++;
  } else {
    if (await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)) {
      return;
    }
    ctx.taskQueue.triggerCascadeSkip(taskId);
  }
  ctx.emit({
    type: 'swarm.task.failed',
    taskId,
    error: 'Hollow completion: worker used no tools',
    attempt: task.attempts,
    maxAttempts: 1 + ctx.config.workerRetries,
    willRetry: canRetry,
    toolCalls: spawnResult.metrics.toolCalls,
    failoverModel: task.assignedModel !== model ? task.assignedModel : undefined,
    failureMode: 'hollow',
  });
  ctx.hollowStreak++;
  ctx.totalHollows++;
  ctx.logDecision(
    'hollow-completion',
    `${taskId}: worker completed with 0 tool calls (streak: ${ctx.hollowStreak}, total hollows: ${ctx.totalHollows}/${ctx.totalDispatches})`,
    canRetry ? 'Marking as failed for retry' : 'Retries exhausted — hard fail',
  );

  // B2: Hollow streak handling
  const HOLLOW_STREAK_THRESHOLD = 3;
  if (ctx.hollowStreak >= HOLLOW_STREAK_THRESHOLD) {
    const uniqueModels = new Set(ctx.config.workers.map((w) => w.model));
    const singleModel = uniqueModels.size === 1;
    const onlyModel = [...uniqueModels][0];
    const modelUnhealthy =
      singleModel && !ctx.healthTracker.getAllRecords().find((r) => r.model === onlyModel)?.healthy;

    if (singleModel && modelUnhealthy) {
      if (ctx.config.enableHollowTermination) {
        ctx.logDecision(
          'early-termination',
          `Terminating swarm: ${ctx.hollowStreak} consecutive hollow completions on sole model ${onlyModel}`,
          'Single-model swarm with unhealthy model — enableHollowTermination is on',
        );
        skipRemainingTasksInternal(
          ctx,
          `Single-model hollow streak (${ctx.hollowStreak}x on ${onlyModel})`,
        );
      } else {
        ctx.logDecision(
          'stall-mode',
          `${ctx.hollowStreak} consecutive hollows on sole model ${onlyModel} — entering stall mode`,
          'Will attempt model failover or simplified retry on next dispatch',
        );
        ctx.hollowStreak = 0;
      }
    }
  }

  // V7: Multi-model hollow ratio
  const minDispatches = ctx.config.hollowTerminationMinDispatches ?? 8;
  const threshold = ctx.config.hollowTerminationRatio ?? 0.55;
  if (ctx.totalDispatches >= minDispatches) {
    const ratio = ctx.totalHollows / ctx.totalDispatches;
    if (ratio > threshold) {
      if (ctx.config.enableHollowTermination) {
        ctx.logDecision(
          'early-termination',
          `Terminating swarm: hollow ratio ${(ratio * 100).toFixed(0)}% (${ctx.totalHollows}/${ctx.totalDispatches})`,
          `Exceeds threshold ${(threshold * 100).toFixed(0)}% after ${minDispatches}+ dispatches — enableHollowTermination is on`,
        );
        skipRemainingTasksInternal(
          ctx,
          `Hollow ratio ${(ratio * 100).toFixed(0)}% — models cannot execute tasks`,
        );
      } else if (!recoveryState.hollowRatioWarned) {
        recoveryState.hollowRatioWarned = true;
        ctx.logDecision(
          'stall-warning',
          `Hollow ratio ${(ratio * 100).toFixed(0)}% (${ctx.totalHollows}/${ctx.totalDispatches})`,
          'High hollow rate but continuing — tasks may still recover via resilience',
        );
      }
    }
  }
}

/**
 * Run the quality gate (LLM judge) on a task completion.
 * Returns true if the task was rejected (caller should return), false if it passed.
 */
async function runQualityGate(
  ctx: OrchestratorInternals,
  recoveryState: SwarmRecoveryState,
  task: SwarmTask,
  taskId: string,
  spawnResult: SpawnResult,
  taskResult: SwarmTaskResult,
  model: string,
  effectiveRetries: number,
  cachedArtifactReport: ReturnType<typeof checkArtifacts>,
): Promise<boolean> {
  const judgeModel =
    ctx.config.hierarchy?.judge?.model ??
    ctx.config.qualityGateModel ??
    ctx.config.orchestratorModel;
  const judgeConfig: QualityGateConfig = {
    model: judgeModel,
    persona: ctx.config.hierarchy?.judge?.persona,
  };

  ctx.emit({
    type: 'swarm.role.action',
    role: 'judge',
    action: 'quality-gate',
    model: judgeModel,
    taskId,
  });

  const fileArtifacts = extractFileArtifacts(ctx, task, taskResult);

  const baseThreshold = ctx.config.qualityThreshold ?? 3;
  const qualityThreshold = task.isFoundation ? Math.max(2, baseThreshold - 1) : baseThreshold;

  const quality = await evaluateWorkerOutput(
    ctx.provider,
    judgeModel,
    task,
    taskResult,
    judgeConfig,
    qualityThreshold,
    (resp, purpose) => ctx.trackOrchestratorUsage(resp, purpose),
    fileArtifacts,
    ctx.config,
    cachedArtifactReport,
  );

  taskResult.qualityScore = quality.score;
  taskResult.qualityFeedback = quality.feedback;

  // F11: Foundation tasks that barely pass
  if (quality.passed && task.isFoundation && quality.score <= baseThreshold - 1) {
    const concreteResult = runConcreteChecks(task, taskResult);
    if (!concreteResult.passed) {
      quality.passed = false;
      quality.feedback += ` [F11: foundation task barely passed (${quality.score}/${baseThreshold}) but concrete validation failed: ${concreteResult.issues.join('; ')}]`;
      ctx.logDecision(
        'foundation-concrete-gate',
        `${taskId}: foundation task scored ${quality.score} (relaxed threshold ${qualityThreshold}) but concrete checks failed — rejecting`,
        concreteResult.issues.join('; '),
      );
    }
  }

  if (!quality.passed) {
    // F7: Gate error fallback
    if (quality.gateError && ctx.config.enableConcreteValidation !== false) {
      const concreteResult = runConcreteChecks(task, taskResult);
      if (concreteResult.passed) {
        ctx.logDecision(
          'gate-error-fallback',
          `${taskId}: gate error but concrete checks passed — tentatively accepting`,
          quality.gateErrorMessage ?? 'unknown',
        );
        taskResult.qualityScore = quality.score;
        taskResult.qualityFeedback = `${quality.feedback} [concrete validation passed — tentative accept]`;
        recoveryState.perModelQualityRejections.delete(model);
        return false; // passed
      } else {
        ctx.logDecision(
          'gate-error-fallback',
          `${taskId}: gate error AND concrete checks failed — rejecting`,
          `Concrete issues: ${concreteResult.issues.join('; ')}`,
        );

        ctx.qualityRejections++;
        task.failureMode = 'quality';
        ctx.healthTracker.recordQualityRejection(model, quality.score);
        ctx.emit({
          type: 'swarm.model.health',
          record: { model, ...getModelHealthSummary(ctx, model) },
        });
        ctx.hollowStreak = 0;

        task.retryContext = {
          previousFeedback: `Gate error + concrete validation failed: ${concreteResult.issues.join('; ')}`,
          previousScore: quality.score,
          attempt: task.attempts,
          previousModel: model,
          previousFiles: taskResult.filesModified,
          swarmProgress: getSwarmProgressSummary(ctx),
        };

        const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
        if (canRetry) {
          ctx.retries++;
        } else {
          if (
            await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)
          ) {
            return true;
          }
          ctx.taskQueue.triggerCascadeSkip(taskId);
        }

        ctx.emit({
          type: 'swarm.quality.rejected',
          taskId,
          score: quality.score,
          feedback: quality.feedback,
          artifactCount: fileArtifacts.length,
          outputLength: taskResult.output.length,
          preFlightReject: false,
          filesOnDisk: checkArtifactsEnhanced(task, taskResult).files.filter(
            (f) => f.exists && f.sizeBytes > 0,
          ).length,
        });
        return true;
      }
    } else if (!quality.gateError) {
      // Normal quality rejection
      ctx.qualityRejections++;
      task.failureMode = 'quality';
      ctx.healthTracker.recordQualityRejection(model, quality.score);
      ctx.emit({
        type: 'swarm.model.health',
        record: { model, ...getModelHealthSummary(ctx, model) },
      });
      ctx.hollowStreak = 0;

      // F7: Per-model circuit breaker
      if (!quality.preFlightReject) {
        const QUALITY_CIRCUIT_BREAKER_THRESHOLD = 5;
        const modelRejections = (recoveryState.perModelQualityRejections.get(model) ?? 0) + 1;
        recoveryState.perModelQualityRejections.set(model, modelRejections);

        if (modelRejections >= QUALITY_CIRCUIT_BREAKER_THRESHOLD) {
          recoveryState.qualityGateDisabledModels.add(model);
          ctx.logDecision(
            'quality-circuit-breaker',
            `Switched model ${model} to pre-flight-only mode after ${modelRejections} rejections`,
            'Skipping LLM judge but keeping pre-flight checks mandatory',
          );
        }
      }

      task.retryContext = {
        previousFeedback: quality.feedback,
        previousScore: quality.score,
        attempt: task.attempts,
        previousModel: model,
        previousFiles: taskResult.filesModified,
        swarmProgress: getSwarmProgressSummary(ctx),
      };
      ctx.sharedContextEngine.reportFailure(taskId, {
        action: task.description.slice(0, 200),
        error: `Quality gate rejection (score ${quality.score}): ${quality.feedback.slice(0, 300)}`,
      });

      // V5: Model failover on quality rejection
      if (
        quality.score < qualityThreshold &&
        ctx.config.enableModelFailover &&
        !quality.artifactAutoFail
      ) {
        const capability: WorkerCapability =
          getTaskTypeConfig(task.type, ctx.config).capability ?? 'code';
        const alternative = selectAlternativeModel(
          ctx.config.workers,
          model,
          capability,
          ctx.healthTracker,
        );
        if (alternative) {
          ctx.emit({
            type: 'swarm.model.failover',
            taskId,
            fromModel: model,
            toModel: alternative.model,
            reason: `quality-score-${quality.score}`,
          });
          task.assignedModel = alternative.model;
          ctx.logDecision(
            'failover',
            `Quality failover ${taskId}: ${model} → ${alternative.model}`,
            `Score ${quality.score}/5`,
          );
        }
      }

      const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
      if (canRetry) {
        ctx.retries++;
      } else {
        if (
          await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)
        ) {
          return true;
        }
        ctx.taskQueue.triggerCascadeSkip(taskId);
      }

      ctx.emit({
        type: 'swarm.quality.rejected',
        taskId,
        score: quality.score,
        feedback: quality.feedback,
        artifactCount: fileArtifacts.length,
        outputLength: taskResult.output.length,
        preFlightReject: quality.preFlightReject,
        filesOnDisk: checkArtifactsEnhanced(task, taskResult).files.filter(
          (f) => f.exists && f.sizeBytes > 0,
        ).length,
      });
      return true;
    } else {
      // gateError=true but concrete validation disabled
      ctx.qualityRejections++;
      task.failureMode = 'quality';
      ctx.hollowStreak = 0;

      task.retryContext = {
        previousFeedback: quality.feedback,
        previousScore: quality.score,
        attempt: task.attempts,
        previousModel: model,
        previousFiles: taskResult.filesModified,
        swarmProgress: getSwarmProgressSummary(ctx),
      };

      const canRetry = ctx.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
      if (canRetry) {
        ctx.retries++;
      } else {
        if (
          await tryResilienceRecovery(ctx, recoveryState, task, taskId, taskResult, spawnResult)
        ) {
          return true;
        }
        ctx.taskQueue.triggerCascadeSkip(taskId);
      }

      ctx.emit({
        type: 'swarm.quality.rejected',
        taskId,
        score: quality.score,
        feedback: quality.feedback,
        artifactCount: fileArtifacts.length,
        outputLength: taskResult.output.length,
        preFlightReject: false,
        filesOnDisk: checkArtifactsEnhanced(task, taskResult).files.filter(
          (f) => f.exists && f.sizeBytes > 0,
        ).length,
      });
      return true;
    }
  }

  // Quality passed — reset per-model rejection counter
  recoveryState.perModelQualityRejections.delete(model);
  return false; // passed
}

/** Internal helper for skipRemainingTasks within execution context */
function skipRemainingTasksInternal(ctx: OrchestratorInternals, reason: string): void {
  for (const task of ctx.taskQueue.getAllTasks()) {
    if (task.status === 'pending' || task.status === 'ready') {
      task.status = 'skipped';
      ctx.emit({ type: 'swarm.task.skipped', taskId: task.id, reason });
    }
  }
}
