/**
 * Swarm Lifecycle — Startup, shutdown, cleanup, and LLM-driven phases.
 *
 * Extracted from swarm-orchestrator.ts (Phase 3a).
 * Contains: decomposition, planning, wave review, verification,
 * resume, synthesis, checkpoint, and utility helpers.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { createSmartDecomposer, parseDecompositionResponse, type SmartDecompositionResult, type SmartSubtask } from '../tasks/smart-decomposer.js';
import type {
  SwarmConfig,
  SwarmExecutionResult,
  SwarmExecutionStats,
  SwarmPlan,
  WaveReviewResult,
  VerificationResult,
  FixupTask,
  SwarmTask,
  SwarmTaskResult,
  ArtifactInventory,
  ArtifactEntry,
} from './types.js';
import { taskResultToAgentOutput } from './types.js';
import { SwarmStateStore } from './swarm-state-store.js';
import type { OrchestratorInternals } from './swarm-orchestrator.js';

// ─── Decomposition ──────────────────────────────────────────────────────

export function classifyDecompositionFailure(message: string): 'rate_limit' | 'provider_budget_limit' | 'parse_failure' | 'validation_failure' | 'other' {
  const m = message.toLowerCase();
  if (m.includes('429') || m.includes('too many requests') || m.includes('rate limit')) {
    return 'rate_limit';
  }
  if (m.includes('402') || m.includes('spend limit') || m.includes('key limit exceeded') || m.includes('insufficient credits')) {
    return 'provider_budget_limit';
  }
  if (m.includes('parse') || m.includes('json') || m.includes('subtasks')) {
    return 'parse_failure';
  }
  if (m.includes('invalid') || m.includes('validation')) {
    return 'validation_failure';
  }
  return 'other';
}

/**
 * Deterministic decomposition fallback when all LLM decomposition paths fail.
 * Keeps swarm mode alive with visible scaffolding tasks instead of aborting.
 */
export function buildEmergencyDecomposition(ctx: OrchestratorInternals, task: string, _reason: string): SmartDecompositionResult {
  const normalizer = createSmartDecomposer({ detectConflicts: true });
  const taskLabel = task.trim().slice(0, 140) || 'requested task';
  const repoMap = ctx.config.codebaseContext?.getRepoMap();
  const topFiles = repoMap
    ? Array.from(repoMap.chunks.values())
      .sort((a, b) => b.importance - a.importance)
      .slice(0, 10)
      .map(c => c.filePath)
    : [];

  const subtasks: SmartSubtask[] = [
    {
      id: 'task-fb-0',
      description: `Scaffold implementation plan and identify target files for: ${taskLabel}`,
      status: 'ready',
      dependencies: [],
      complexity: 2,
      type: 'design',
      parallelizable: true,
      relevantFiles: topFiles.slice(0, 5),
    },
    {
      id: 'task-fb-1',
      description: `Implement core code changes for: ${taskLabel}`,
      status: 'blocked',
      dependencies: ['task-fb-0'],
      complexity: 5,
      type: 'implement',
      parallelizable: false,
      relevantFiles: topFiles.slice(0, 8),
    },
    {
      id: 'task-fb-2',
      description: `Add or update tests and run validation for: ${taskLabel}`,
      status: 'blocked',
      dependencies: ['task-fb-1'],
      complexity: 3,
      type: 'test',
      parallelizable: false,
      relevantFiles: topFiles.slice(0, 8),
    },
    {
      id: 'task-fb-3',
      description: `Integrate results and produce final summary for: ${taskLabel}`,
      status: 'blocked',
      dependencies: ['task-fb-1', 'task-fb-2'],
      complexity: 2,
      type: 'integrate',
      parallelizable: false,
      relevantFiles: topFiles.slice(0, 5),
    },
  ];

  const dependencyGraph = normalizer.buildDependencyGraph(subtasks);
  const conflicts = normalizer.detectConflicts(subtasks);

  return {
    originalTask: task,
    subtasks,
    dependencyGraph,
    conflicts,
    strategy: 'adaptive',
    totalComplexity: subtasks.reduce((sum, s) => sum + s.complexity, 0),
    totalEstimatedTokens: subtasks.length * 4000,
    metadata: {
      decomposedAt: new Date(),
      codebaseAware: !!repoMap,
      llmAssisted: false,
    },
  };
}

/**
 * Last-resort decomposition: radically simplified prompt that even weak models can handle.
 */
export async function lastResortDecompose(ctx: OrchestratorInternals, task: string): Promise<SmartDecompositionResult | null> {
  let codebaseHint = '';
  const repoMap = ctx.config.codebaseContext?.getRepoMap();
  if (repoMap) {
    const topFiles = Array.from(repoMap.chunks.values())
      .sort((a, b) => b.importance - a.importance)
      .slice(0, 10)
      .map(c => c.filePath);
    codebaseHint = `\nKey project files: ${topFiles.join(', ')}\nReference actual files in subtask descriptions.`;
  }

  const simplifiedPrompt = `Break this task into 2-6 subtasks. Return ONLY raw JSON, no markdown.

{"subtasks":[{"description":"...","type":"implement","complexity":3,"dependencies":[],"parallelizable":true,"relevantFiles":["src/..."]}],"strategy":"adaptive","reasoning":"..."}

Rules:
- dependencies: integer indices (e.g. [0] means depends on first subtask)
- type: one of research/implement/test/design/refactor/integrate/merge
- At least 2 subtasks${codebaseHint}`;

  const response = await ctx.provider.chat(
    [
      { role: 'system', content: simplifiedPrompt },
      { role: 'user', content: task },
    ],
    {
      model: ctx.config.orchestratorModel,
      maxTokens: 4096,
      temperature: 0.1,
    },
  );
  ctx.trackOrchestratorUsage(response as any, 'decompose-last-resort');

  const parsed = parseDecompositionResponse(response.content);
  if (parsed.subtasks.length < 2) return null;

  const decomposer = createSmartDecomposer({ detectConflicts: true });
  const subtasks = parsed.subtasks.map((s, index) => ({
    id: `task-lr-${index}`,
    description: s.description,
    status: (s.dependencies.length > 0 ? 'blocked' : 'ready') as import('../tasks/smart-decomposer.js').SubtaskStatus,
    dependencies: s.dependencies.map((d: number | string) => `task-lr-${d}`),
    complexity: s.complexity,
    type: s.type,
    parallelizable: s.parallelizable,
    relevantFiles: s.relevantFiles,
    suggestedRole: s.suggestedRole,
  }));

  const dependencyGraph = decomposer.buildDependencyGraph(subtasks);
  const conflicts = decomposer.detectConflicts(subtasks);

  return {
    originalTask: task,
    subtasks,
    dependencyGraph,
    conflicts,
    strategy: parsed.strategy,
    totalComplexity: subtasks.reduce((sum, t) => sum + t.complexity, 0),
    totalEstimatedTokens: subtasks.length * 5000,
    metadata: {
      decomposedAt: new Date(),
      codebaseAware: false,
      llmAssisted: true,
    },
  };
}

/**
 * Phase 1: Decompose the task into subtasks.
 */
export async function decomposeTask(ctx: OrchestratorInternals, task: string): Promise<{ result: SmartDecompositionResult; failureReason?: undefined } | { result: null; failureReason: string }> {
  try {
    const repoMap = ctx.config.codebaseContext?.getRepoMap() ?? undefined;
    const result = await ctx.decomposer.decompose(task, {
      repoMap,
    });

    if (result.subtasks.length < 2) {
      const reason = result.subtasks.length === 0
        ? `Decomposition produced 0 subtasks (model: ${ctx.config.orchestratorModel}).`
        : `Decomposition produced only ${result.subtasks.length} subtask — too few for swarm mode.`;
      ctx.logDecision('decomposition', `Insufficient subtasks: ${result.subtasks.length}`, reason);

      try {
        const lastResortResult = await lastResortDecompose(ctx, task);
        if (lastResortResult && lastResortResult.subtasks.length >= 2) {
          ctx.logDecision('decomposition',
            `Last-resort decomposition succeeded: ${lastResortResult.subtasks.length} subtasks`,
            'Recovered from insufficient primary decomposition');
          return { result: lastResortResult };
        }
      } catch (error) {
        ctx.logDecision('decomposition',
          'Last-resort decomposition failed after insufficient primary decomposition',
          (error as Error).message);
      }

      const fallback = buildEmergencyDecomposition(ctx, task, reason);
      ctx.emit({
        type: 'swarm.phase.progress',
        phase: 'decomposing',
        message: `Using emergency decomposition fallback (${classifyDecompositionFailure(reason)})`,
      });
      ctx.logDecision('decomposition',
        `Using emergency scaffold decomposition: ${fallback.subtasks.length} subtasks`,
        'Swarm will continue with deterministic fallback tasks');
      return { result: fallback };
    }

    if (!result.metadata.llmAssisted) {
      ctx.logDecision('decomposition',
        'Heuristic decomposition detected — attempting last-resort simplified LLM decomposition',
        `Model: ${ctx.config.orchestratorModel}`);

      try {
        const lastResortResult = await lastResortDecompose(ctx, task);
        if (lastResortResult && lastResortResult.subtasks.length >= 2) {
          ctx.logDecision('decomposition',
            `Last-resort decomposition succeeded: ${lastResortResult.subtasks.length} subtasks`,
            'Simplified prompt worked');
          return { result: lastResortResult };
        }
      } catch (error) {
        ctx.logDecision('decomposition',
          'Last-resort decomposition also failed',
          (error as Error).message);
      }

      ctx.logDecision('decomposition',
        `Continuing with heuristic decomposition: ${result.subtasks.length} subtasks`,
        'Fallback is acceptable; do not abort swarm');
      ctx.emit({
        type: 'swarm.phase.progress',
        phase: 'decomposing',
        message: `Continuing with heuristic decomposition (${classifyDecompositionFailure('heuristic fallback')})`,
      });
      return { result };
    }

    // Flat-DAG detection
    const hasAnyDependency = result.subtasks.some(s => s.dependencies.length > 0);
    if (!hasAnyDependency && result.subtasks.length >= 3) {
      ctx.logDecision('decomposition',
        `Flat DAG: ${result.subtasks.length} tasks, zero dependencies`,
        'All tasks will execute in wave 0 without ordering');
    }

    return { result };
  } catch (error) {
    const message = (error as Error).message;
    ctx.errors.push({
      phase: 'decomposition',
      message,
      recovered: true,
    });
    const fallback = buildEmergencyDecomposition(ctx, task, `Decomposition threw an error: ${message}`);
    ctx.emit({
      type: 'swarm.phase.progress',
      phase: 'decomposing',
      message: `Decomposition fallback due to ${classifyDecompositionFailure(message)}`,
    });
    ctx.logDecision('decomposition',
      `Decomposition threw error; using emergency scaffold decomposition (${fallback.subtasks.length} subtasks)`,
      message);
    return { result: fallback };
  }
}

// ─── Planning Phase ─────────────────────────────────────────────────────

/**
 * Create acceptance criteria and integration test plan.
 * Graceful: if planning fails, continues without criteria.
 */
export async function planExecution(ctx: OrchestratorInternals, task: string, decomposition: { subtasks: Array<{ id: string; description: string; type: string }> }): Promise<void> {
  try {
    const plannerModel = ctx.config.hierarchy?.manager?.model
      ?? ctx.config.plannerModel ?? ctx.config.orchestratorModel;

    ctx.emit({ type: 'swarm.role.action', role: 'manager', action: 'plan', model: plannerModel });
    ctx.logDecision('planning', `Creating acceptance criteria (manager: ${plannerModel})`,
      `Task has ${decomposition.subtasks.length} subtasks, planning to ensure quality`);
    const taskList = decomposition.subtasks
      .map(s => `- [${s.id}] (${s.type}): ${s.description}`)
      .join('\n');

    const response = await ctx.provider.chat(
      [
        {
          role: 'system',
          content: `You are a project quality planner. Given a task and its decomposition into subtasks, create:
1. Acceptance criteria for each subtask (what "done" looks like)
2. An integration test plan (bash commands to verify the combined result works)

Respond with valid JSON:
{
  "acceptanceCriteria": [
    { "taskId": "st-0", "criteria": ["criterion 1", "criterion 2"] }
  ],
  "integrationTestPlan": {
    "description": "What this test plan verifies",
    "steps": [
      { "description": "Check if files exist", "command": "ls src/parser.js", "expectedResult": "file listed", "required": true }
    ],
    "successCriteria": "All required steps pass"
  },
  "reasoning": "Why this plan was chosen"
}`,
        },
        {
          role: 'user',
          content: `Task: ${task}\n\nSubtasks:\n${taskList}`,
        },
      ],
      {
        model: plannerModel,
        maxTokens: 3000,
        temperature: 0.3,
      },
    );

    ctx.trackOrchestratorUsage(response as any, 'plan');

    const parsed = parseJSON(response.content);
    if (parsed) {
      ctx.plan = {
        acceptanceCriteria: parsed.acceptanceCriteria ?? [],
        integrationTestPlan: parsed.integrationTestPlan,
        reasoning: parsed.reasoning ?? '',
      };
      ctx.emit({
        type: 'swarm.plan.complete',
        criteriaCount: ctx.plan.acceptanceCriteria.length,
        hasIntegrationPlan: !!ctx.plan.integrationTestPlan,
      });
    }
  } catch (error) {
    ctx.errors.push({
      phase: 'planning',
      message: `Planning failed (non-fatal): ${(error as Error).message}`,
      recovered: true,
    });
  }
}

// ─── Wave Review ────────────────────────────────────────────────────────

/**
 * Review completed wave outputs against acceptance criteria.
 * May spawn fix-up tasks for issues found.
 */
export async function reviewWave(ctx: OrchestratorInternals, waveIndex: number): Promise<WaveReviewResult | null> {
  if (!ctx.config.enableWaveReview) return null;

  try {
    const managerModel = ctx.config.hierarchy?.manager?.model
      ?? ctx.config.plannerModel ?? ctx.config.orchestratorModel;
    const managerPersona = ctx.config.hierarchy?.manager?.persona;

    ctx.emit({ type: 'swarm.role.action', role: 'manager', action: 'review', model: managerModel, wave: waveIndex + 1 });
    ctx.emit({ type: 'swarm.review.start', wave: waveIndex + 1 });
    ctx.logDecision('review', `Reviewing wave ${waveIndex + 1} outputs (manager: ${managerModel})`, 'Checking task outputs against acceptance criteria');

    const completedTasks = ctx.taskQueue.getAllTasks()
      .filter(t => t.status === 'completed' && t.wave === waveIndex);

    if (completedTasks.length === 0) {
      return { wave: waveIndex, assessment: 'good', taskAssessments: [], fixupTasks: [] };
    }

    const taskSummaries = completedTasks.map(t => {
      const criteria = ctx.plan?.acceptanceCriteria.find(c => c.taskId === t.id);
      return `Task ${t.id}: ${t.description}
  Output: ${t.result?.output?.slice(0, 500) ?? 'No output'}
  Acceptance criteria: ${criteria?.criteria.join('; ') ?? 'None set'}`;
    }).join('\n\n');

    const reviewModel = managerModel;
    const reviewSystemPrompt = managerPersona
      ? `${managerPersona}\n\nYou are reviewing completed worker outputs. Assess each task against its acceptance criteria.\nRespond with JSON:`
      : `You are reviewing completed worker outputs. Assess each task against its acceptance criteria.\nRespond with JSON:`;

    const response = await ctx.provider.chat(
      [
        {
          role: 'system',
          content: `${reviewSystemPrompt}
{
  "assessment": "good" | "needs-fixes" | "critical-issues",
  "taskAssessments": [
    { "taskId": "st-0", "passed": true, "feedback": "optional feedback" }
  ],
  "fixupInstructions": [
    { "fixesTaskId": "st-0", "description": "What to fix", "instructions": "Specific fix instructions" }
  ]
}`,
        },
        { role: 'user', content: `Review these wave ${waveIndex + 1} outputs:\n\n${taskSummaries}` },
      ],
      { model: reviewModel, maxTokens: 2000, temperature: 0.3 },
    );

    ctx.trackOrchestratorUsage(response as any, 'review');

    const parsed = parseJSON(response.content);
    if (!parsed) return null;

    const fixupTasks: FixupTask[] = [];
    if (parsed.fixupInstructions) {
      for (const fix of parsed.fixupInstructions) {
        const fixupId = `fixup-${fix.fixesTaskId}-${Date.now()}`;
        const originalTask = ctx.taskQueue.getTask(fix.fixesTaskId);
        const fixupTask: FixupTask = {
          id: fixupId,
          description: fix.description,
          type: originalTask?.type ?? 'implement',
          dependencies: [fix.fixesTaskId],
          status: 'ready',
          complexity: 3,
          wave: waveIndex,
          attempts: 0,
          fixesTaskId: fix.fixesTaskId,
          fixInstructions: fix.instructions,
        };
        fixupTasks.push(fixupTask);
        ctx.emit({ type: 'swarm.fixup.spawned', taskId: fixupId, fixesTaskId: fix.fixesTaskId, description: fix.description });
      }

      if (fixupTasks.length > 0) {
        ctx.taskQueue.addFixupTasks(fixupTasks);
        ctx.emit({
          type: 'swarm.tasks.loaded',
          tasks: ctx.taskQueue.getAllTasks(),
        });
      }
    }

    const result: WaveReviewResult = {
      wave: waveIndex,
      assessment: parsed.assessment ?? 'good',
      taskAssessments: parsed.taskAssessments ?? [],
      fixupTasks,
    };

    ctx.waveReviews.push(result);
    ctx.emit({
      type: 'swarm.review.complete',
      wave: waveIndex + 1,
      assessment: result.assessment,
      fixupCount: fixupTasks.length,
    });

    return result;
  } catch (error) {
    ctx.errors.push({
      phase: 'review',
      message: `Wave review failed (non-fatal): ${(error as Error).message}`,
      recovered: true,
    });
    return null;
  }
}

// ─── Verification ───────────────────────────────────────────────────────

/**
 * Run integration verification steps.
 */
export async function verifyIntegration(ctx: OrchestratorInternals, testPlan: NonNullable<SwarmPlan['integrationTestPlan']>): Promise<VerificationResult> {
  const verifyModel = ctx.config.hierarchy?.judge?.model
    ?? ctx.config.qualityGateModel ?? ctx.config.orchestratorModel;
  ctx.emit({ type: 'swarm.role.action', role: 'judge', action: 'verify', model: verifyModel });
  ctx.emit({ type: 'swarm.verify.start', stepCount: testPlan.steps.length });
  ctx.logDecision('verification', `Running ${testPlan.steps.length} verification steps (judge: ${verifyModel})`, testPlan.description);

  const stepResults: VerificationResult['stepResults'] = [];
  let allRequiredPassed = true;

  for (let i = 0; i < testPlan.steps.length; i++) {
    const step = testPlan.steps[i];
    try {
      const verifierName = `swarm-verifier-${i}`;
      const result = await ctx.spawnAgentFn(verifierName,
        `Run this command and report the result: ${step.command}\nExpected: ${step.expectedResult ?? 'success'}`);

      const passed = result.success;
      stepResults.push({ step, passed, output: result.output.slice(0, 500) });

      if (!passed && step.required) {
        allRequiredPassed = false;
      }

      ctx.emit({ type: 'swarm.verify.step', stepIndex: i, description: step.description, passed });
    } catch (error) {
      const output = `Error: ${(error as Error).message}`;
      stepResults.push({ step, passed: false, output });
      if (step.required) allRequiredPassed = false;
      ctx.emit({ type: 'swarm.verify.step', stepIndex: i, description: step.description, passed: false });
    }
  }

  const verificationResult: VerificationResult = {
    passed: allRequiredPassed,
    stepResults,
    summary: allRequiredPassed
      ? `All ${stepResults.filter(r => r.passed).length}/${stepResults.length} steps passed`
      : `${stepResults.filter(r => !r.passed).length}/${stepResults.length} steps failed`,
  };

  ctx.verificationResult = verificationResult;
  ctx.emit({ type: 'swarm.verify.complete', result: verificationResult });

  return verificationResult;
}

/**
 * Handle verification failure: create fix-up tasks and re-verify.
 */
export async function handleVerificationFailure(ctx: OrchestratorInternals, verification: VerificationResult, task: string): Promise<void> {
  const maxRetries = ctx.config.maxVerificationRetries ?? 2;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    ctx.logDecision('verification',
      `Verification failed, fix-up attempt ${attempt + 1}/${maxRetries}`,
      `${verification.stepResults.filter(r => !r.passed).length} steps failed`);

    try {
      const failedSteps = verification.stepResults
        .filter(r => !r.passed)
        .map(r => `- ${r.step.description}: ${r.output}`)
        .join('\n');

      const response = await ctx.provider.chat(
        [
          {
            role: 'system',
            content: `Verification failed. Analyze the failures and create fix-up tasks.
Respond with JSON: { "fixups": [{ "description": "what to fix", "type": "implement" }] }`,
          },
          { role: 'user', content: `Original task: ${task}\n\nFailed verifications:\n${failedSteps}` },
        ],
        { model: ctx.config.plannerModel ?? ctx.config.orchestratorModel, maxTokens: 1500, temperature: 0.3 },
      );

      ctx.trackOrchestratorUsage(response as any, 'verification-fixup');

      const parsed = parseJSON(response.content);
      if (parsed?.fixups && parsed.fixups.length > 0) {
        const fixupTasks: FixupTask[] = parsed.fixups.map((f: { description: string; type?: string }, i: number) => ({
          id: `verify-fix-${attempt}-${i}-${Date.now()}`,
          description: f.description,
          type: (f.type ?? 'implement') as FixupTask['type'],
          dependencies: [],
          status: 'ready' as const,
          complexity: 4,
          wave: ctx.taskQueue.getCurrentWave(),
          attempts: 0,
          fixesTaskId: 'verification',
          fixInstructions: f.description,
        }));

        ctx.taskQueue.addFixupTasks(fixupTasks);
        ctx.emit({
          type: 'swarm.tasks.loaded',
          tasks: ctx.taskQueue.getAllTasks(),
        });

        ctx.currentPhase = 'executing';
        await ctx.executeWave(fixupTasks);

        ctx.currentPhase = 'verifying';
        verification = await verifyIntegration(ctx, ctx.plan!.integrationTestPlan!);
        if (verification.passed) return;
      }
    } catch {
      // Continue to next attempt
    }
  }
}

// ─── Resume ─────────────────────────────────────────────────────────────

/**
 * Resume execution from a saved checkpoint.
 * Returns null if no checkpoint found (caller should fall through to normal execute).
 */
export async function resumeExecution(ctx: OrchestratorInternals, task: string, midSwarmReplan: () => Promise<void>): Promise<SwarmExecutionResult | null> {
  const checkpoint = SwarmStateStore.loadLatest(
    ctx.config.stateDir ?? '.agent/swarm-state',
    ctx.config.resumeSessionId!,
  );

  if (!checkpoint) {
    ctx.logDecision('resume', 'No checkpoint found, starting fresh', `Session: ${ctx.config.resumeSessionId}`);
    ctx.config.resumeSessionId = undefined;
    return null;
  }

  ctx.logDecision('resume', `Resuming from wave ${checkpoint.currentWave}`, `Session: ${checkpoint.sessionId}`);
  ctx.emit({ type: 'swarm.state.resume', sessionId: checkpoint.sessionId, fromWave: checkpoint.currentWave });

  // Restore state
  if (checkpoint.originalPrompt) ctx.originalPrompt = checkpoint.originalPrompt;
  if (checkpoint.plan) ctx.plan = checkpoint.plan;
  if (checkpoint.modelHealth.length > 0) ctx.healthTracker.restore(checkpoint.modelHealth);
  ctx.orchestratorDecisions = checkpoint.decisions ?? [];
  ctx.errors = checkpoint.errors ?? [];
  ctx.totalTokens = checkpoint.stats.totalTokens;
  ctx.totalCost = checkpoint.stats.totalCost;
  ctx.qualityRejections = checkpoint.stats.qualityRejections;
  ctx.retries = checkpoint.stats.retries;

  if (checkpoint.sharedContext) {
    ctx.sharedContextState.restoreFrom(checkpoint.sharedContext as Parameters<typeof ctx.sharedContextState.restoreFrom>[0]);
  }
  if (checkpoint.sharedEconomics) {
    ctx.sharedEconomicsState.restoreFrom(checkpoint.sharedEconomics);
  }

  ctx.taskQueue.restoreFromCheckpoint({
    taskStates: checkpoint.taskStates,
    waves: checkpoint.waves,
    currentWave: checkpoint.currentWave,
  });

  const resetIds = ctx.taskQueue.reconcileStaleDispatched({
    staleAfterMs: 0,
    activeTaskIds: new Set<string>(),
  });
  const resetCount = resetIds.length;
  for (const taskId of resetIds) {
    const t = ctx.taskQueue.getTask(taskId);
    if (!t) continue;
    t.attempts = Math.min(t.attempts, Math.max(0, ctx.config.workerRetries - 1));
  }
  if (resetCount > 0) {
    ctx.logDecision('resume', `Reset ${resetCount} orphaned dispatched tasks to ready`, 'Workers died with previous process');
  }

  let unskippedCount = 0;
  for (const t of ctx.taskQueue.getAllTasks()) {
    if (t.status === 'skipped') {
      const deps = t.dependencies.map(id => ctx.taskQueue.getTask(id));
      const allDepsSatisfied = deps.every(d =>
        d && (d.status === 'completed' || d.status === 'decomposed'),
      );
      if (allDepsSatisfied) {
        t.status = 'ready';
        t.attempts = 0;
        t.rescueContext = 'Recovered on resume — dependencies now satisfied';
        unskippedCount++;
      }
    }
  }
  for (const t of ctx.taskQueue.getAllTasks()) {
    if (t.status === 'failed') {
      t.status = 'ready';
      t.attempts = Math.min(t.attempts, Math.max(0, ctx.config.workerRetries - 1));
      unskippedCount++;
    }
  }
  if (unskippedCount > 0) {
    ctx.logDecision('resume', `Recovered ${unskippedCount} skipped/failed tasks`, 'Fresh retry on resume');
  }

  const resumeStats = ctx.taskQueue.getStats();
  const stuckCount = resumeStats.failed + resumeStats.skipped;
  const totalAttempted = resumeStats.completed + stuckCount;
  if (totalAttempted > 0 && stuckCount / totalAttempted > 0.4) {
    ctx.logDecision('resume-replan',
      `${stuckCount}/${totalAttempted} tasks still stuck after resume — triggering re-plan`, '');
    ctx.hasReplanned = false;
    await midSwarmReplan();
  }

  ctx.currentPhase = 'executing';
  await ctx.executeWaves();

  if (!ctx.cancelled) await ctx.finalRescuePass();

  ctx.artifactInventory = buildArtifactInventory(ctx);

  if (ctx.config.enableVerification && ctx.plan?.integrationTestPlan) {
    ctx.currentPhase = 'verifying';
    const ver = await verifyIntegration(ctx, ctx.plan.integrationTestPlan);
    if (!ver.passed) {
      await handleVerificationFailure(ctx, ver, task);
    }
  }

  ctx.currentPhase = 'synthesizing';
  const synthesisResult = await synthesizeOutputs(ctx);

  ctx.currentPhase = 'completed';
  const executionStats = buildStats(ctx);
  saveCheckpoint(ctx, 'final');

  const hasArtifacts = (ctx.artifactInventory?.totalFiles ?? 0) > 0;
  ctx.emit({ type: 'swarm.complete', stats: executionStats, errors: ctx.errors, artifactInventory: ctx.artifactInventory });

  const completionRatio = executionStats.totalTasks > 0
    ? executionStats.completedTasks / executionStats.totalTasks
    : 0;
  const isSuccess = completionRatio >= 0.7;
  const isPartialSuccess = !isSuccess && executionStats.completedTasks > 0;

  return {
    success: isSuccess,
    partialSuccess: isPartialSuccess || (!executionStats.completedTasks && hasArtifacts),
    partialFailure: executionStats.failedTasks > 0,
    synthesisResult: synthesisResult ?? undefined,
    artifactInventory: ctx.artifactInventory,
    summary: buildSummary(ctx, executionStats),
    tasks: ctx.taskQueue.getAllTasks(),
    stats: executionStats,
    errors: ctx.errors,
  };
}

// ─── Synthesis ──────────────────────────────────────────────────────────

/**
 * Phase 4: Synthesize all completed task outputs.
 */
export async function synthesizeOutputs(ctx: OrchestratorInternals) {
  const tasks = ctx.taskQueue.getAllTasks();
  const outputs = tasks
    .filter(t => t.status === 'completed')
    .map(t => taskResultToAgentOutput(t, ctx.config))
    .filter((o): o is NonNullable<typeof o> => o !== null);

  if (outputs.length === 0) return null;

  try {
    return await ctx.synthesizer.synthesize(outputs);
  } catch (error) {
    ctx.errors.push({
      phase: 'synthesis',
      message: (error as Error).message,
      recovered: true,
    });
    return ctx.synthesizer.synthesizeFindings(outputs);
  }
}

// ─── Persistence ────────────────────────────────────────────────────────

export function saveCheckpoint(ctx: OrchestratorInternals, _label: string): void {
  if (!ctx.config.enablePersistence || !ctx.stateStore) return;

  try {
    const queueState = ctx.taskQueue.getCheckpointState();
    ctx.stateStore.saveCheckpoint({
      sessionId: ctx.stateStore.id,
      timestamp: Date.now(),
      phase: ctx.currentPhase,
      plan: ctx.plan,
      taskStates: queueState.taskStates,
      waves: queueState.waves,
      currentWave: queueState.currentWave,
      stats: {
        totalTokens: ctx.totalTokens + ctx.orchestratorTokens,
        totalCost: ctx.totalCost + ctx.orchestratorCost,
        qualityRejections: ctx.qualityRejections,
        retries: ctx.retries,
      },
      modelHealth: ctx.healthTracker.getAllRecords(),
      decisions: ctx.orchestratorDecisions,
      errors: ctx.errors,
      originalPrompt: ctx.originalPrompt,
      sharedContext: ctx.sharedContextState.toJSON(),
      sharedEconomics: ctx.sharedEconomicsState.toJSON(),
    });

    ctx.emit({
      type: 'swarm.state.checkpoint',
      sessionId: ctx.stateStore.id,
      wave: ctx.taskQueue.getCurrentWave(),
    });
  } catch (error) {
    ctx.errors.push({
      phase: 'persistence',
      message: `Checkpoint failed (non-fatal): ${(error as Error).message}`,
      recovered: true,
    });
  }
}

// ─── Utility Helpers ────────────────────────────────────────────────────

/** Parse JSON from LLM response, handling markdown code blocks. */
export function parseJSON(content: string): Record<string, any> | null {
  try {
    let json = content;
    const codeBlockMatch = content.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/);
    if (codeBlockMatch) {
      json = codeBlockMatch[1];
    }
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export function buildStats(ctx: OrchestratorInternals): SwarmExecutionStats {
  const queueStats = ctx.taskQueue.getStats();
  return {
    totalTasks: queueStats.total,
    completedTasks: queueStats.completed,
    failedTasks: queueStats.failed,
    skippedTasks: queueStats.skipped,
    totalWaves: ctx.taskQueue.getTotalWaves(),
    totalTokens: ctx.totalTokens + ctx.orchestratorTokens,
    totalCost: ctx.totalCost + ctx.orchestratorCost,
    totalDurationMs: Date.now() - ctx.startTime,
    qualityRejections: ctx.qualityRejections,
    retries: ctx.retries,
    modelUsage: ctx.modelUsage,
  };
}

export function buildSummary(ctx: OrchestratorInternals, stats: SwarmExecutionStats): string {
  const parts: string[] = [
    `Swarm execution complete:`,
    `  Tasks: ${stats.completedTasks}/${stats.totalTasks} completed, ${stats.failedTasks} failed, ${stats.skippedTasks} skipped`,
    `  Waves: ${stats.totalWaves}`,
    `  Tokens: ${(stats.totalTokens / 1000).toFixed(0)}k`,
    `  Cost: $${stats.totalCost.toFixed(4)}`,
    `  Duration: ${(stats.totalDurationMs / 1000).toFixed(1)}s`,
  ];

  if (stats.qualityRejections > 0) {
    parts.push(`  Quality rejections: ${stats.qualityRejections}`);
  }
  if (stats.retries > 0) {
    parts.push(`  Retries: ${stats.retries}`);
  }
  if (ctx.verificationResult) {
    parts.push(`  Verification: ${ctx.verificationResult.passed ? 'PASSED' : 'FAILED'}`);
  }

  if (ctx.artifactInventory && ctx.artifactInventory.totalFiles > 0) {
    parts.push(`  Files on disk: ${ctx.artifactInventory.totalFiles} files (${(ctx.artifactInventory.totalBytes / 1024).toFixed(1)}KB)`);
    for (const f of ctx.artifactInventory.files.slice(0, 15)) {
      parts.push(`    ${f.path}: ${f.sizeBytes}B`);
    }
    if (ctx.artifactInventory.files.length > 15) {
      parts.push(`    ... and ${ctx.artifactInventory.files.length - 15} more`);
    }
  }

  return parts.join('\n');
}

export function buildErrorResult(ctx: OrchestratorInternals, message: string): SwarmExecutionResult {
  return {
    success: false,
    summary: `Swarm failed: ${message}`,
    tasks: ctx.taskQueue.getAllTasks(),
    stats: buildStats(ctx),
    errors: ctx.errors,
  };
}

/**
 * Detect foundation tasks: tasks that are a dependency of 2+ downstream tasks.
 */
export function detectFoundationTasks(ctx: OrchestratorInternals): void {
  const allTasks = ctx.taskQueue.getAllTasks();
  const dependentCounts = new Map<string, number>();

  for (const task of allTasks) {
    for (const depId of task.dependencies) {
      dependentCounts.set(depId, (dependentCounts.get(depId) ?? 0) + 1);
    }
  }

  for (const task of allTasks) {
    const dependentCount = dependentCounts.get(task.id) ?? 0;
    if (dependentCount >= 2) {
      task.isFoundation = true;
      ctx.logDecision('scheduling',
        `Foundation task: ${task.id} (${dependentCount} dependents)`,
        'Extra retries and relaxed quality threshold applied');
    }
  }
}

/**
 * Extract file artifacts from a worker's output for quality gate visibility.
 */
export function extractFileArtifacts(ctx: OrchestratorInternals, task: SwarmTask, taskResult: SwarmTaskResult): Array<{ path: string; preview: string }> {
  const artifacts: Array<{ path: string; preview: string }> = [];
  const seen = new Set<string>();

  const candidatePaths: string[] = [];

  if (taskResult.filesModified) {
    candidatePaths.push(...taskResult.filesModified);
  }
  if (task.targetFiles) {
    candidatePaths.push(...task.targetFiles);
  }

  const filePathPattern = /(?:created|wrote|modified|edited|updated)\s+["`']?([^\s"`',]+\.\w+)/gi;
  let match;
  while ((match = filePathPattern.exec(taskResult.output)) !== null) {
    candidatePaths.push(match[1]);
  }

  const baseDir = ctx.config.facts?.workingDirectory ?? process.cwd();

  for (const filePath of candidatePaths) {
    if (seen.has(filePath)) continue;
    seen.add(filePath);

    try {
      const resolved = path.resolve(baseDir, filePath);
      if (fs.existsSync(resolved)) {
        const content = fs.readFileSync(resolved, 'utf-8');
        if (content.length > 0) {
          artifacts.push({ path: filePath, preview: content.slice(0, 2000) });
        }
      }
    } catch {
      // Skip unreadable files
    }

    if (artifacts.length >= 10) break;
  }

  return artifacts;
}

/**
 * Build an inventory of filesystem artifacts produced during swarm execution.
 */
export function buildArtifactInventory(ctx: OrchestratorInternals): ArtifactInventory {
  const allFiles = new Set<string>();
  for (const task of ctx.taskQueue.getAllTasks()) {
    for (const f of (task.targetFiles ?? [])) allFiles.add(f);
    for (const f of (task.readFiles ?? [])) allFiles.add(f);
  }

  const baseDir = ctx.config.facts?.workingDirectory ?? process.cwd();
  const artifacts: ArtifactEntry[] = [];

  for (const filePath of allFiles) {
    try {
      const resolved = path.resolve(baseDir, filePath);
      if (fs.existsSync(resolved)) {
        const stats = fs.statSync(resolved);
        if (stats.isFile() && stats.size > 0) {
          artifacts.push({ path: filePath, sizeBytes: stats.size, exists: true });
        }
      }
    } catch { /* skip unreadable files */ }
  }

  return {
    files: artifacts,
    totalFiles: artifacts.length,
    totalBytes: artifacts.reduce((s, a) => s + a.sizeBytes, 0),
  };
}

/**
 * Skip all remaining pending/ready tasks (used for early termination).
 */
export function skipRemainingTasks(ctx: OrchestratorInternals, reason: string): void {
  for (const task of ctx.taskQueue.getAllTasks()) {
    if (task.status === 'pending' || task.status === 'ready') {
      task.status = 'skipped';
      ctx.emit({ type: 'swarm.task.skipped', taskId: task.id, reason });
    }
  }
}

export function emitBudgetUpdate(ctx: OrchestratorInternals): void {
  ctx.emit({
    type: 'swarm.budget.update',
    tokensUsed: ctx.totalTokens + ctx.orchestratorTokens,
    tokensTotal: ctx.config.totalBudget,
    costUsed: ctx.totalCost + ctx.orchestratorCost,
    costTotal: ctx.config.maxCost,
  });
}

/**
 * V7: Compute effective retry limit for a task.
 */
export function getEffectiveRetries(ctx: OrchestratorInternals, task: SwarmTask): number {
  const isFixup = 'fixesTaskId' in task;
  if (isFixup) return 2;
  return task.isFoundation ? ctx.config.workerRetries + 1 : ctx.config.workerRetries;
}

/**
 * F22: Build a brief summary of swarm progress for retry context.
 */
export function getSwarmProgressSummary(ctx: OrchestratorInternals): string {
  const allTasks = ctx.taskQueue.getAllTasks();
  const completed = allTasks.filter(t => t.status === 'completed');

  if (completed.length === 0) return '';

  const lines: string[] = [];
  for (const task of completed) {
    const score = task.result?.qualityScore ? ` (${task.result.qualityScore}/5)` : '';
    lines.push(`- ${task.id}: ${task.description.slice(0, 80)}${score}`);
  }

  const files = new Set<string>();
  const baseDir = ctx.config.facts?.workingDirectory ?? process.cwd();
  for (const task of completed) {
    for (const f of (task.result?.filesModified ?? [])) files.add(f);
    for (const f of (task.targetFiles ?? [])) {
      try {
        const resolved = path.resolve(baseDir, f);
        if (fs.existsSync(resolved)) files.add(f);
      } catch { /* skip */ }
    }
  }

  const parts = [`The following tasks have completed successfully:\n${lines.join('\n')}`];
  if (files.size > 0) {
    parts.push(`Files already created/modified: ${[...files].slice(0, 20).join(', ')}`);
    parts.push('You can build on these existing files.');
  }

  return parts.join('\n');
}

/** Get a model health summary for emitting events. */
export function getModelHealthSummary(ctx: OrchestratorInternals, model: string): Omit<import('./types.js').ModelHealthRecord, 'model'> {
  const records = ctx.healthTracker.getAllRecords();
  const record = records.find(r => r.model === model);
  return record
    ? { successes: record.successes, failures: record.failures, rateLimits: record.rateLimits, lastRateLimit: record.lastRateLimit, averageLatencyMs: record.averageLatencyMs, healthy: record.healthy }
    : { successes: 0, failures: 0, rateLimits: 0, averageLatencyMs: 0, healthy: true };
}
