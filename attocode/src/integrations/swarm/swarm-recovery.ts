/**
 * Swarm Recovery — Error recovery, retry logic, resilience strategies.
 *
 * Extracted from swarm-orchestrator.ts (Phase 3a).
 * Contains: resilience recovery, micro-decomposition, auto-split,
 * cascade rescue, mid-swarm re-planning, circuit breaker, adaptive stagger.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { SwarmTask, SwarmTaskResult, WorkerCapability } from './types.js';
import { getTaskTypeConfig } from './types.js';
import { checkArtifacts, checkArtifactsEnhanced, runConcreteChecks } from './swarm-quality-gate.js';
import type { SpawnResult } from '../agents/agent-registry.js';
import type { OrchestratorInternals } from './swarm-orchestrator.js';
import { hasFutureIntentLanguage } from './swarm-helpers.js';
import {
  buildArtifactInventory,
  getSwarmProgressSummary,
  skipRemainingTasks,
} from './swarm-lifecycle.js';

// ─── Recovery State ─────────────────────────────────────────────────────

/**
 * Mutable state used by recovery functions.
 * Kept separate from OrchestratorInternals to group recovery-specific concerns.
 */
export interface SwarmRecoveryState {
  // Circuit breaker
  recentRateLimits: number[];
  circuitBreakerUntil: number;

  // Per-model quality gate circuit breaker
  perModelQualityRejections: Map<string, number>;
  qualityGateDisabledModels: Set<string>;

  // Adaptive stagger
  adaptiveStaggerMs: number;

  // Consecutive timeout tracking
  taskTimeoutCounts: Map<string, number>;

  // Hollow ratio warning
  hollowRatioWarned: boolean;
}

const CIRCUIT_BREAKER_WINDOW_MS = 30_000;
const CIRCUIT_BREAKER_THRESHOLD = 3;
const CIRCUIT_BREAKER_PAUSE_MS = 15_000;

// ─── Circuit Breaker ────────────────────────────────────────────────────

/**
 * Record a rate limit hit and check if the circuit breaker should trip.
 */
export function recordRateLimit(state: SwarmRecoveryState, ctx: OrchestratorInternals): void {
  const now = Date.now();
  state.recentRateLimits.push(now);
  increaseStagger(state);

  const cutoff = now - CIRCUIT_BREAKER_WINDOW_MS;
  state.recentRateLimits = state.recentRateLimits.filter(t => t > cutoff);

  if (state.recentRateLimits.length >= CIRCUIT_BREAKER_THRESHOLD) {
    state.circuitBreakerUntil = now + CIRCUIT_BREAKER_PAUSE_MS;
    ctx.emit({
      type: 'swarm.circuit.open',
      recentCount: state.recentRateLimits.length,
      pauseMs: CIRCUIT_BREAKER_PAUSE_MS,
    });
    ctx.logDecision('circuit-breaker', 'Tripped — pausing all dispatch',
      `${state.recentRateLimits.length} rate limits in ${CIRCUIT_BREAKER_WINDOW_MS / 1000}s window`);
  }
}

/**
 * Check if the circuit breaker is currently active.
 */
export function isCircuitBreakerActive(state: SwarmRecoveryState, ctx: OrchestratorInternals): boolean {
  if (Date.now() < state.circuitBreakerUntil) return true;
  if (state.circuitBreakerUntil > 0) {
    state.circuitBreakerUntil = 0;
    ctx.emit({ type: 'swarm.circuit.closed' });
  }
  return false;
}

// ─── Adaptive Stagger ───────────────────────────────────────────────────

/** Get current stagger delay. */
export function getStaggerMs(state: SwarmRecoveryState): number {
  return state.adaptiveStaggerMs;
}

/** Increase stagger on rate limit (x1.5, capped at 10s). */
export function increaseStagger(state: SwarmRecoveryState): void {
  state.adaptiveStaggerMs = Math.min(state.adaptiveStaggerMs * 1.5, 10_000);
}

/** Decrease stagger on success (x0.9, floor at 200ms). */
export function decreaseStagger(state: SwarmRecoveryState): void {
  state.adaptiveStaggerMs = Math.max(state.adaptiveStaggerMs * 0.9, 200);
}

// ─── Resilience Recovery ────────────────────────────────────────────────

/**
 * Try resilience recovery strategies before hard-failing a task.
 *
 * Strategies (in order):
 * 1. Micro-decomposition — break complex failing tasks into subtasks
 * 2. Degraded acceptance — accept partial work if artifacts exist on disk
 *
 * Returns true if recovery succeeded (caller should return), false if hard-fail should proceed.
 */
export async function tryResilienceRecovery(
  ctx: OrchestratorInternals,
  _recoveryState: SwarmRecoveryState,
  task: SwarmTask,
  taskId: string,
  taskResult: SwarmTaskResult,
  spawnResult: SpawnResult,
): Promise<boolean> {
  // Strategy 1: Micro-decompose complex tasks into smaller subtasks
  if ((task.complexity ?? 0) >= 4 && task.attempts >= 2 && ctx.budgetPool.hasCapacity()) {
    const subtasks = await microDecompose(ctx, task);
    if (subtasks && subtasks.length >= 2) {
      task.status = 'dispatched';
      ctx.taskQueue.replaceWithSubtasks(taskId, subtasks);
      ctx.logDecision('micro-decompose',
        `${taskId}: decomposed into ${subtasks.length} subtasks after ${task.attempts} failures`,
        subtasks.map(s => `${s.id}: ${s.description.slice(0, 60)}`).join('; '));
      ctx.emit({
        type: 'swarm.task.failed',
        taskId,
        error: `Micro-decomposed into ${subtasks.length} subtasks`,
        attempt: task.attempts,
        maxAttempts: ctx.config.maxDispatchesPerTask ?? 5,
        willRetry: false,
        toolCalls: spawnResult.metrics.toolCalls,
        failureMode: task.failureMode,
      });
      ctx.emit({
        type: 'swarm.task.resilience',
        taskId,
        strategy: 'micro-decompose',
        succeeded: true,
        reason: `Decomposed into ${subtasks.length} subtasks after ${task.attempts} failures`,
        artifactsFound: 0,
        toolCalls: spawnResult.metrics.toolCalls ?? 0,
      });
      return true;
    }
    if ((task.complexity ?? 0) < 4) {
      ctx.logDecision('resilience-skip', `${taskId}: skipped micro-decompose — complexity ${task.complexity} < 4`, '');
    }
  }

  // Strategy 2: Degraded acceptance
  const artifactReport = checkArtifactsEnhanced(task, taskResult);
  const existingArtifacts = artifactReport.files.filter(f => f.exists && f.sizeBytes > 0);
  const hasArtifacts = existingArtifacts.length > 0;
  const toolCalls = spawnResult.metrics.toolCalls ?? 0;
  const hadToolCalls = toolCalls > 0 || toolCalls === -1
    || (taskResult.filesModified && taskResult.filesModified.length > 0);

  const isNarrativeOnly = hasFutureIntentLanguage(taskResult.output ?? '');
  const typeConfig = getTaskTypeConfig(task.type, ctx.config);
  const actionTaskNeedsArtifacts = (ctx.config.completionGuard?.requireConcreteArtifactsForActionTasks ?? true)
    && !!typeConfig.requiresToolCalls;
  const allowDegradedWithoutArtifacts = !actionTaskNeedsArtifacts && hadToolCalls && !isNarrativeOnly;

  if (hasArtifacts || allowDegradedWithoutArtifacts) {
    taskResult.success = true;
    taskResult.degraded = true;
    taskResult.qualityScore = 2;
    taskResult.qualityFeedback = 'Degraded acceptance: retries exhausted but filesystem artifacts exist';
    task.degraded = true;
    task.status = 'dispatched';
    ctx.taskQueue.markCompleted(taskId, taskResult);
    ctx.hollowStreak = 0;
    ctx.logDecision('degraded-acceptance',
      `${taskId}: accepted as degraded — ${existingArtifacts.length} artifacts on disk, ${toolCalls} tool calls`,
      'Prevents cascade-skip of dependent tasks');
    ctx.emit({
      type: 'swarm.task.completed',
      taskId,
      success: true,
      tokensUsed: taskResult.tokensUsed,
      costUsed: taskResult.costUsed,
      durationMs: taskResult.durationMs,
      qualityScore: 2,
      qualityFeedback: 'Degraded acceptance',
      output: taskResult.output,
      toolCalls: spawnResult.metrics.toolCalls,
    });
    ctx.emit({
      type: 'swarm.task.resilience',
      taskId,
      strategy: 'degraded-acceptance',
      succeeded: true,
      reason: `${existingArtifacts.length} artifacts on disk, ${toolCalls} tool calls`,
      artifactsFound: existingArtifacts.length,
      toolCalls,
    });
    return true;
  }

  // Both strategies failed
  ctx.logDecision('resilience-exhausted',
    `${taskId}: no recovery — artifacts: ${existingArtifacts.length}, toolCalls: ${toolCalls}, filesModified: ${taskResult.filesModified?.length ?? 0}`,
    '');
  ctx.emit({
    type: 'swarm.task.resilience',
    taskId,
    strategy: 'none',
    succeeded: false,
    reason: `No artifacts found, toolCalls=${toolCalls}, filesModified=${taskResult.filesModified?.length ?? 0}`,
    artifactsFound: existingArtifacts.length,
    toolCalls,
  });
  return false;
}

// ─── Micro-Decomposition ────────────────────────────────────────────────

/**
 * Micro-decompose a complex task into 2-3 smaller subtasks using the LLM.
 */
async function microDecompose(ctx: OrchestratorInternals, task: SwarmTask): Promise<SwarmTask[] | null> {
  if ((task.complexity ?? 0) < 4) return null;

  try {
    const prompt = `Task "${task.description}" failed ${task.attempts} times on model ${task.assignedModel ?? 'unknown'}.
The task has complexity ${task.complexity}/10 and type "${task.type}".
${task.targetFiles?.length ? `Target files: ${task.targetFiles.join(', ')}` : ''}

Break this task into 2-3 smaller, independent subtasks that each handle a portion of the work.
Each subtask MUST be simpler (complexity <= ${Math.ceil(task.complexity / 2)}).
Each subtask should be self-contained and produce concrete file changes.

Return JSON ONLY (no markdown, no explanation):
{
  "subtasks": [
    { "description": "...", "type": "${task.type}", "targetFiles": ["..."], "complexity": <number> }
  ]
}`;

    const response = await ctx.provider.chat(
      [
        { role: 'system', content: 'You are a task decomposition assistant. Return only valid JSON.' },
        { role: 'user', content: prompt },
      ],
      {
        model: ctx.config.orchestratorModel,
        maxTokens: 2000,
        temperature: 0.3,
      },
    );

    ctx.trackOrchestratorUsage(response as any, 'micro-decompose');

    let jsonStr = response.content.trim();
    const codeBlockMatch = jsonStr.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (codeBlockMatch) jsonStr = codeBlockMatch[1].trim();

    const parsed = JSON.parse(jsonStr);
    if (!parsed.subtasks || !Array.isArray(parsed.subtasks) || parsed.subtasks.length < 2) {
      return null;
    }

    const subtasks: SwarmTask[] = parsed.subtasks.map((sub: any, idx: number) => ({
      id: `${task.id}-sub${idx + 1}`,
      description: sub.description,
      type: sub.type ?? task.type,
      dependencies: [],
      status: 'ready' as const,
      complexity: Math.min(sub.complexity ?? Math.ceil(task.complexity / 2), task.complexity - 1),
      wave: task.wave,
      targetFiles: sub.targetFiles ?? [],
      readFiles: task.readFiles,
      attempts: 0,
    }));

    return subtasks;
  } catch (error) {
    ctx.logDecision('micro-decompose',
      `${task.id}: micro-decomposition failed — ${(error as Error).message}`,
      'Falling through to normal failure path');
    return null;
  }
}

// ─── Pre-Dispatch Auto-Split ────────────────────────────────────────────

/**
 * Heuristic pre-filter: should this task be considered for auto-split?
 */
export function shouldAutoSplit(ctx: OrchestratorInternals, task: SwarmTask): boolean {
  const cfg = ctx.config.autoSplit;
  if (cfg?.enabled === false) return false;

  const floor = cfg?.complexityFloor ?? 6;
  const splittable = cfg?.splittableTypes ?? ['implement', 'refactor', 'test'];

  if (task.attempts > 0) return false;
  if ((task.complexity ?? 0) < floor) return false;
  if (!splittable.includes(task.type)) return false;
  if (!task.isFoundation) return false;
  if (!ctx.budgetPool.hasCapacity()) return false;

  return true;
}

/**
 * LLM judge call: ask the orchestrator model whether and how to split a task.
 */
export async function judgeSplit(ctx: OrchestratorInternals, task: SwarmTask): Promise<{ shouldSplit: boolean; subtasks?: SwarmTask[] }> {
  const maxSubs = ctx.config.autoSplit?.maxSubtasks ?? 4;

  const prompt = `You are evaluating whether a task should be split into parallel subtasks before dispatch.

TASK: "${task.description}"
TYPE: ${task.type}
COMPLEXITY: ${task.complexity}/10
TARGET FILES: ${task.targetFiles?.join(', ') || 'none specified'}
DOWNSTREAM DEPENDENTS: This is a foundation task — other tasks are waiting on it.

Should this task be split into 2-${maxSubs} parallel subtasks that different workers can execute simultaneously?

SPLIT if:
- The task involves multiple independent pieces of work (e.g., different files, different functions, different concerns)
- Parallel execution would meaningfully reduce wall-clock time
- The subtasks can produce useful output independently

DO NOT SPLIT if:
- The work is conceptually atomic (one function, one algorithm, tightly coupled logic)
- The subtasks would need to coordinate on the same files/functions
- Splitting would add more overhead than it saves

Return JSON ONLY:
{
  "shouldSplit": true/false,
  "reason": "brief explanation",
  "subtasks": [
    { "description": "...", "type": "${task.type}", "targetFiles": ["..."], "complexity": <number 1-10> }
  ]
}
If shouldSplit is false, omit subtasks.`;

  const response = await ctx.provider.chat(
    [
      { role: 'system', content: 'You are a task planning judge. Return only valid JSON.' },
      { role: 'user', content: prompt },
    ],
    {
      model: ctx.config.orchestratorModel,
      maxTokens: 1500,
      temperature: 0.2,
    },
  );
  ctx.trackOrchestratorUsage(response as any, 'auto-split-judge');

  let jsonStr = response.content.trim();
  const codeBlockMatch = jsonStr.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (codeBlockMatch) jsonStr = codeBlockMatch[1].trim();

  const parsed = JSON.parse(jsonStr);
  if (!parsed.shouldSplit) {
    ctx.logDecision('auto-split', `${task.id}: judge says no split — ${parsed.reason}`, '');
    return { shouldSplit: false };
  }
  if (!parsed.subtasks || !Array.isArray(parsed.subtasks) || parsed.subtasks.length < 2) {
    return { shouldSplit: false };
  }

  const subtasks: SwarmTask[] = parsed.subtasks.slice(0, maxSubs).map((sub: any, idx: number) => ({
    id: `${task.id}-split${idx + 1}`,
    description: sub.description,
    type: sub.type ?? task.type,
    dependencies: [],
    status: 'ready' as const,
    complexity: Math.max(3, Math.min(sub.complexity ?? Math.ceil(task.complexity / 2), task.complexity - 1)),
    wave: task.wave,
    targetFiles: sub.targetFiles ?? [],
    readFiles: task.readFiles,
    attempts: 0,
    rescueContext: `Auto-split from ${task.id} (original complexity ${task.complexity})`,
  }));

  ctx.logDecision('auto-split',
    `${task.id}: split into ${subtasks.length} subtasks — ${parsed.reason}`,
    subtasks.map(s => `${s.id}: ${s.description.slice(0, 60)}`).join('; '));

  return { shouldSplit: true, subtasks };
}

// ─── Cascade Rescue ─────────────────────────────────────────────────────

/**
 * Rescue cascade-skipped tasks that can still run.
 */
export function rescueCascadeSkipped(ctx: OrchestratorInternals, lenient = false): SwarmTask[] {
  const skippedTasks = ctx.taskQueue.getSkippedTasks();
  const rescued: SwarmTask[] = [];

  for (const task of skippedTasks) {
    if (task.dependencies.length === 0) continue;

    let completedDeps = 0;
    let failedDepsWithArtifacts = 0;
    let failedDepsWithoutArtifacts = 0;
    let skippedDepsBlockedBySkipped = 0;
    let totalDeps = 0;
    const failedDepDescriptions: string[] = [];

    for (const depId of task.dependencies) {
      const dep = ctx.taskQueue.getTask(depId);
      if (!dep) continue;
      totalDeps++;

      if (dep.status === 'completed' || dep.status === 'decomposed') {
        completedDeps++;
      } else if (dep.status === 'failed' || dep.status === 'skipped') {
        const artifactReport = lenient ? checkArtifactsEnhanced(dep) : checkArtifacts(dep);
        if (artifactReport && artifactReport.files.filter(f => f.exists && f.sizeBytes > 0).length > 0) {
          failedDepsWithArtifacts++;
          failedDepDescriptions.push(`${dep.description} (failed but ${artifactReport.files.filter(f => f.exists && f.sizeBytes > 0).length} artifacts exist)`);
        } else {
          const targetFiles = dep.targetFiles ?? [];
          const existingFiles = targetFiles.filter(f => {
            try {
              const resolved = path.resolve(ctx.config.facts?.workingDirectory ?? process.cwd(), f);
              return fs.statSync(resolved).size > 0;
            } catch { return false; }
          });
          if (existingFiles.length > 0) {
            failedDepsWithArtifacts++;
            failedDepDescriptions.push(`${dep.description} (failed but ${existingFiles.length}/${targetFiles.length} target files exist)`);
          } else {
            const taskTargets = new Set(task.targetFiles ?? []);
            const depTargets = new Set(dep.targetFiles ?? []);
            const hasOverlap = [...taskTargets].some(f => depTargets.has(f));
            if (!hasOverlap && taskTargets.size > 0) {
              failedDepsWithArtifacts++;
              failedDepDescriptions.push(`${dep.description} (failed, no file overlap — likely independent)`);
            } else if (lenient && dep.status === 'skipped') {
              skippedDepsBlockedBySkipped++;
              failedDepDescriptions.push(`${dep.description} (skipped — transitive cascade victim)`);
            } else {
              failedDepsWithoutArtifacts++;
            }
          }
        }
      }
    }

    const effectiveWithout = failedDepsWithoutArtifacts;
    const maxMissing = lenient ? 1 : 0;
    const hasEnoughContext = lenient ? (completedDeps + failedDepsWithArtifacts + skippedDepsBlockedBySkipped > 0) : (completedDeps > 0);

    if (totalDeps > 0 && effectiveWithout <= maxMissing && hasEnoughContext) {
      const rescueContext = `Rescued from cascade-skip${lenient ? ' (lenient)' : ''}: ${completedDeps}/${totalDeps} deps completed, ` +
        `${failedDepsWithArtifacts} failed deps have artifacts${skippedDepsBlockedBySkipped > 0 ? `, ${skippedDepsBlockedBySkipped} transitive cascade victims` : ''}. ${failedDepDescriptions.join('; ')}`;
      ctx.taskQueue.rescueTask(task.id, rescueContext);
      rescued.push(task);
      ctx.logDecision('cascade-rescue',
        `${task.id}: rescued from cascade-skip${lenient ? ' (lenient)' : ''}`,
        rescueContext);
    }
  }

  return rescued;
}

/**
 * Final rescue pass — runs after executeWaves() finishes.
 */
export async function finalRescuePass(ctx: OrchestratorInternals, executeWaveFn: (tasks: SwarmTask[]) => Promise<void>): Promise<void> {
  const skipped = ctx.taskQueue.getSkippedTasks();
  if (skipped.length === 0) return;

  ctx.logDecision('final-rescue', `${skipped.length} skipped tasks — running final rescue pass`, '');
  const rescued = rescueCascadeSkipped(ctx, true);
  if (rescued.length > 0) {
    ctx.logDecision('final-rescue', `Rescued ${rescued.length} tasks`, rescued.map(t => t.id).join(', '));
    await executeWaveFn(rescued);
  }
}

// ─── Mid-Swarm Assessment & Re-Planning ─────────────────────────────────

/**
 * F21: Mid-swarm situational assessment after each wave.
 */
export async function assessAndAdapt(ctx: OrchestratorInternals, _recoveryState: SwarmRecoveryState, waveIndex: number): Promise<void> {
  const stats = ctx.taskQueue.getStats();
  const budgetStats = ctx.budgetPool.getStats();

  const successRate = stats.completed / Math.max(1, stats.completed + stats.failed + stats.skipped);
  const tokensPerTask = stats.completed > 0
    ? (ctx.totalTokens / stats.completed)
    : Infinity;

  const remainingTasks = stats.total - stats.completed - stats.failed - stats.skipped;
  const estimatedTokensNeeded = remainingTasks * tokensPerTask;
  const budgetSufficient = budgetStats.tokensRemaining > estimatedTokensNeeded * 0.5;

  ctx.logDecision('mid-swarm-assessment',
    `After wave ${waveIndex + 1}: ${stats.completed}/${stats.total} completed (${(successRate * 100).toFixed(0)}%), ` +
    `${remainingTasks} remaining, ${budgetStats.tokensRemaining} tokens left`,
    budgetSufficient ? 'Budget looks sufficient' : 'Budget may be insufficient for remaining tasks');

  if (!budgetSufficient && remainingTasks > 1 && stats.completed > 0) {
    const runningCount = stats.running ?? 0;
    if (runningCount > 0) {
      ctx.logDecision('budget-wait',
        'Budget tight but workers still running — waiting for budget release',
        `${runningCount} workers active, ${budgetStats.tokensRemaining} tokens remaining`);
      return;
    }

    const expendableTasks = findExpendableTasks(ctx);
    const maxSkips = Math.max(1, Math.floor(remainingTasks * 0.2));
    if (expendableTasks.length > 0) {
      let currentEstimate = estimatedTokensNeeded;
      let skipped = 0;
      for (const task of expendableTasks) {
        if (skipped >= maxSkips) break;
        if (currentEstimate * 0.7 <= budgetStats.tokensRemaining) break;
        task.status = 'skipped';
        skipped++;
        ctx.emit({ type: 'swarm.task.skipped', taskId: task.id,
          reason: 'Budget conservation: skipping low-priority task to protect critical path' });
        ctx.logDecision('budget-triage',
          `Skipping ${task.id} (${task.type}, complexity ${task.complexity}) to conserve budget`,
          `${remainingTasks} tasks remain, ${budgetStats.tokensRemaining} tokens`);
        currentEstimate -= tokensPerTask;
      }
    }
  }

  // Stall detection
  const attemptedTasks = stats.completed + stats.failed + stats.skipped;
  if (attemptedTasks >= 5) {
    const progressRatio = stats.completed / Math.max(1, attemptedTasks);
    if (progressRatio < 0.4) {
      ctx.logDecision('stall-detected',
        `Progress stalled: ${stats.completed}/${attemptedTasks} tasks succeeded (${(progressRatio * 100).toFixed(0)}%)`,
        'Triggering mid-swarm re-plan');
      ctx.emit({
        type: 'swarm.stall',
        progressRatio,
        attempted: attemptedTasks,
        completed: stats.completed,
      });
      await midSwarmReplan(ctx);
    }
  }
}

/**
 * Find expendable tasks — leaf tasks with lowest complexity.
 */
function findExpendableTasks(ctx: OrchestratorInternals): SwarmTask[] {
  const allTasks = ctx.taskQueue.getAllTasks();

  const dependentCounts = new Map<string, number>();
  for (const task of allTasks) {
    for (const depId of task.dependencies) {
      dependentCounts.set(depId, (dependentCounts.get(depId) ?? 0) + 1);
    }
  }

  return allTasks
    .filter(t =>
      (t.status === 'pending' || t.status === 'ready') &&
      t.attempts === 0 &&
      !t.isFoundation &&
      (t.complexity ?? 5) <= 2 &&
      (dependentCounts.get(t.id) ?? 0) === 0,
    )
    .sort((a, b) => (a.complexity ?? 5) - (b.complexity ?? 5));
}

/**
 * Mid-swarm re-planning: when progress stalls, ask LLM to re-plan remaining work.
 */
export async function midSwarmReplan(ctx: OrchestratorInternals): Promise<void> {
  if (ctx.hasReplanned) return;
  ctx.hasReplanned = true;

  const allTasks = ctx.taskQueue.getAllTasks();
  const completed = allTasks.filter(t => t.status === 'completed' || t.status === 'decomposed');
  const stuck = allTasks.filter(t => t.status === 'failed' || t.status === 'skipped');

  if (stuck.length === 0) return;

  const completedSummary = completed.map(t =>
    `- ${t.description} [${t.type}] → completed${t.degraded ? ' (degraded)' : ''}`,
  ).join('\n') || '(none)';
  const stuckSummary = stuck.map(t =>
    `- ${t.description} [${t.type}] → ${t.status} (${t.failureMode ?? 'unknown'})`,
  ).join('\n');
  const artifactInventoryData = buildArtifactInventory(ctx);
  const artifactSummary = artifactInventoryData.files.map(f => `- ${f.path} (${f.sizeBytes}B)`).join('\n') || '(none)';

  const replanPrompt = `The swarm is stalled. Here's the situation:

COMPLETED WORK:
${completedSummary}

FILES ON DISK:
${artifactSummary}

STUCK TASKS (failed or skipped):
${stuckSummary}

Re-plan the remaining work. Create new subtasks that:
1. Build on what's already completed (don't redo work)
2. Are more focused in scope (but assign realistic complexity for the work involved — don't underestimate)
3. Can succeed independently (minimize dependencies)

Return JSON: { "subtasks": [{ "description": "...", "type": "implement|test|research|review|document|refactor", "complexity": 1-5, "dependencies": [], "relevantFiles": [] }] }
Return ONLY the JSON object, no other text.`;

  try {
    const response = await ctx.provider.chat([{ role: 'user', content: replanPrompt }]);
    ctx.trackOrchestratorUsage(response as any, 'mid-swarm-replan');

    const content = response.content ?? '';
    const jsonMatch = content.match(/\{[\s\S]*"subtasks"[\s\S]*\}/);
    if (!jsonMatch) {
      ctx.logDecision('replan-failed', 'LLM produced no parseable re-plan JSON', content.slice(0, 200));
      return;
    }

    const parsed = JSON.parse(jsonMatch[0]) as { subtasks: Array<{ description: string; type: string; complexity: number; dependencies: string[]; relevantFiles?: string[] }> };
    if (!parsed.subtasks || parsed.subtasks.length === 0) {
      ctx.logDecision('replan-failed', 'LLM produced empty subtask list', '');
      return;
    }

    const newTasks = ctx.taskQueue.addReplanTasks(parsed.subtasks, ctx.taskQueue.getCurrentWave());
    ctx.logDecision('replan-success',
      `Re-planned ${stuck.length} stuck tasks into ${newTasks.length} new tasks`,
      newTasks.map(t => t.description).join('; '));

    ctx.emit({
      type: 'swarm.replan',
      stuckCount: stuck.length,
      newTaskCount: newTasks.length,
    });

    ctx.emit({
      type: 'swarm.orchestrator.decision',
      decision: {
        timestamp: Date.now(),
        phase: 'replan',
        decision: `Re-planned ${stuck.length} stuck tasks into ${newTasks.length} new tasks`,
        reasoning: newTasks.map(t => `${t.id}: ${t.description}`).join('; '),
      },
    });
  } catch (error) {
    ctx.logDecision('replan-failed', `Re-plan LLM call failed: ${(error as Error).message}`, '');
  }
}
