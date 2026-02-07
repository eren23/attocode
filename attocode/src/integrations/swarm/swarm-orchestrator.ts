/**
 * Swarm Orchestrator V2
 *
 * The main orchestration loop that ties together:
 * - SmartDecomposer for task breakdown
 * - SwarmTaskQueue for wave-based scheduling
 * - SwarmWorkerPool for concurrent worker dispatch
 * - SwarmQualityGate for output validation
 * - ResultSynthesizer for merging outputs
 *
 * V2 additions:
 * - Planning phase with acceptance criteria
 * - Post-wave review with fix-up task generation
 * - Integration verification with bash commands
 * - Model health tracking and failover
 * - State persistence and resume
 * - Orchestrator decision logging
 */

import type { LLMProvider } from '../../providers/types.js';
import type { AgentRegistry } from '../agent-registry.js';
import type { SharedBlackboard } from '../shared-blackboard.js';
import { createSmartDecomposer, parseDecompositionResponse, type LLMDecomposeFunction } from '../smart-decomposer.js';
import { createResultSynthesizer } from '../result-synthesizer.js';
import type {
  SwarmConfig,
  SwarmExecutionResult,
  SwarmExecutionStats,
  SwarmError,
  SwarmStatus,
  SwarmTask,
  SwarmPlan,
  WaveReviewResult,
  VerificationResult,
  FixupTask,
  OrchestratorDecision,
  WorkerCapability,
} from './types.js';
import { taskResultToAgentOutput, DEFAULT_SWARM_CONFIG, SUBTASK_TO_CAPABILITY } from './types.js';
import { SwarmTaskQueue, createSwarmTaskQueue } from './task-queue.js';
import { createSwarmBudgetPool, type SwarmBudgetPool } from './swarm-budget.js';
import { SwarmWorkerPool, createSwarmWorkerPool, type SpawnAgentFn } from './worker-pool.js';
import { evaluateWorkerOutput, type QualityGateConfig } from './swarm-quality-gate.js';
import { ModelHealthTracker, selectAlternativeModel } from './model-selector.js';
import { SwarmStateStore } from './swarm-state-store.js';
import type { SwarmEvent } from './swarm-events.js';

// ─── Event Emitter ─────────────────────────────────────────────────────────

export type SwarmEventListener = (event: SwarmEvent) => void;

// ─── Orchestrator ──────────────────────────────────────────────────────────

export class SwarmOrchestrator {
  private config: SwarmConfig;
  private provider: LLMProvider;
  private blackboard?: SharedBlackboard;

  private taskQueue: SwarmTaskQueue;
  private budgetPool: SwarmBudgetPool;
  private workerPool: SwarmWorkerPool;
  private _decomposer!: ReturnType<typeof createSmartDecomposer>;
  private synthesizer!: ReturnType<typeof createResultSynthesizer>;

  private listeners: SwarmEventListener[] = [];
  private errors: SwarmError[] = [];
  private cancelled = false;

  // M5: Explicit phase tracking for TUI status
  private currentPhase: SwarmStatus['phase'] = 'decomposing';

  // Stats tracking
  private totalTokens = 0;
  private totalCost = 0;
  private qualityRejections = 0;
  private retries = 0;
  private startTime = 0;
  private modelUsage = new Map<string, { tasks: number; tokens: number; cost: number }>();

  // V2: Planning, review, verification, health, persistence
  private plan?: SwarmPlan;
  private waveReviews: WaveReviewResult[] = [];
  private verificationResult?: VerificationResult;
  private orchestratorDecisions: OrchestratorDecision[] = [];
  private healthTracker: ModelHealthTracker;
  private stateStore?: SwarmStateStore;
  private spawnAgentFn: SpawnAgentFn;

  // Circuit breaker: pause all dispatch after too many 429s
  private recentRateLimits: number[] = [];
  private circuitBreakerUntil = 0;
  private static readonly CIRCUIT_BREAKER_WINDOW_MS = 30_000;
  private static readonly CIRCUIT_BREAKER_THRESHOLD = 3;
  private static readonly CIRCUIT_BREAKER_PAUSE_MS = 15_000;

  constructor(
    config: SwarmConfig,
    provider: LLMProvider,
    agentRegistry: AgentRegistry,
    spawnAgentFn: SpawnAgentFn,
    blackboard?: SharedBlackboard,
  ) {
    this.config = { ...DEFAULT_SWARM_CONFIG, ...config };
    this.provider = provider;
    this.blackboard = blackboard;
    this.spawnAgentFn = spawnAgentFn;
    this.healthTracker = new ModelHealthTracker();

    this.taskQueue = createSwarmTaskQueue();
    this.budgetPool = createSwarmBudgetPool(this.config);
    this.workerPool = createSwarmWorkerPool(
      this.config,
      agentRegistry,
      spawnAgentFn,
      this.budgetPool,
    );

    // Initialize state store if persistence enabled
    if (this.config.enablePersistence) {
      this.stateStore = new SwarmStateStore(
        this.config.stateDir ?? '.agent/swarm-state',
        this.config.resumeSessionId,
      );
    }

    // C1: Build LLM decompose function with explicit JSON schema
    const llmDecompose: LLMDecomposeFunction = async (task, _context) => {
      const systemPrompt = `You are a task decomposition expert. Break down the given task into well-defined subtasks with clear dependencies.

Respond with valid JSON matching this exact schema:
{
  "subtasks": [
    {
      "description": "Clear description of what this subtask does",
      "type": "implement" | "research" | "analysis" | "design" | "test" | "refactor" | "review" | "document" | "integrate" | "deploy" | "merge",
      "complexity": 1-10,
      "dependencies": ["description of dependency task or index like '0'"],
      "parallelizable": true | false,
      "relevantFiles": ["src/path/to/file.ts"]
    }
  ],
  "strategy": "sequential" | "parallel" | "hierarchical" | "adaptive" | "pipeline",
  "reasoning": "Brief explanation of why this decomposition was chosen"
}

Rules:
- Each subtask must have a clear, actionable description
- Dependencies reference other subtask descriptions or zero-based indices
- Mark subtasks as parallelizable: true if they don't depend on each other
- Complexity 1-3: simple, 4-6: moderate, 7-10: complex
- Return at least 2 subtasks for non-trivial tasks`;

      const response = await this.provider.chat(
        [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: task },
        ],
        {
          model: this.config.orchestratorModel,
          maxTokens: 4000,
          temperature: 0.3,
        },
      );

      // Use parseDecompositionResponse which handles markdown code blocks and edge cases
      return parseDecompositionResponse(response.content);
    };

    // Configure decomposer for swarm use
    const decomposer = createSmartDecomposer({
      useLLM: true,
      maxSubtasks: 30,
      detectConflicts: true,
      llmProvider: llmDecompose,
    });
    this._decomposer = decomposer;
    this.synthesizer = createResultSynthesizer();
  }

  /**
   * Get the swarm budget pool (used by parent agent to override its own pool).
   */
  getBudgetPool(): SwarmBudgetPool {
    return this.budgetPool;
  }

  /**
   * Subscribe to swarm events.
   */
  subscribe(listener: SwarmEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Emit a swarm event to all listeners.
   */
  private emit(event: SwarmEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Don't let listener errors break the orchestrator
      }
    }
  }

  /**
   * Execute the full swarm pipeline for a task.
   *
   * V2 pipeline:
   *   1. Check for resume
   *   2. Decompose
   *   3. Plan (acceptance criteria + verification plan)
   *   4. Schedule into waves
   *   5. Execute waves with review
   *   6. Verify integration
   *   7. Fix-up loop if verification fails
   *   8. Synthesize
   *   9. Checkpoint (final)
   */
  async execute(task: string): Promise<SwarmExecutionResult> {
    this.startTime = Date.now();

    try {
      // V2: Check for resume
      if (this.config.resumeSessionId && this.stateStore) {
        return await this.resumeExecution(task);
      }

      // Phase 1: Decompose
      this.currentPhase = 'decomposing';
      const decomposition = await this.decompose(task);
      if (!decomposition) {
        this.currentPhase = 'failed';
        return this.buildErrorResult('Decomposition failed — task may be too simple for swarm mode');
      }

      // Phase 2: Schedule into waves
      this.currentPhase = 'scheduling';
      this.taskQueue.loadFromDecomposition(decomposition, this.config);
      const stats = this.taskQueue.getStats();

      // V2: Phase 2.5: Plan execution (acceptance criteria)
      if (this.config.enablePlanning) {
        this.currentPhase = 'planning';
        await this.planExecution(task, decomposition);
      }

      this.emit({
        type: 'swarm.start',
        taskCount: stats.total,
        waveCount: this.taskQueue.getTotalWaves(),
        config: {
          maxConcurrency: this.config.maxConcurrency,
          totalBudget: this.config.totalBudget,
          maxCost: this.config.maxCost,
        },
      });

      // Emit tasks AFTER swarm.start so the bridge has already initialized
      // (swarm.start clears tasks/edges, so loading before it would lose them)
      this.emit({
        type: 'swarm.tasks.loaded',
        tasks: this.taskQueue.getAllTasks(),
      });

      // Phase 3: Execute waves (V2: with review after each wave)
      this.currentPhase = 'executing';
      await this.executeWaves();

      // V2: Phase 3.5: Verify integration
      if (this.config.enableVerification && this.plan?.integrationTestPlan) {
        this.currentPhase = 'verifying';
        const verification = await this.verifyIntegration(this.plan.integrationTestPlan);

        if (!verification.passed) {
          await this.handleVerificationFailure(verification, task);
        }
      }

      // Phase 4: Synthesize results
      this.currentPhase = 'synthesizing';
      const synthesisResult = await this.synthesize();

      this.currentPhase = 'completed';
      const executionStats = this.buildStats();

      // V2: Final checkpoint
      this.checkpoint('final');

      this.emit({ type: 'swarm.complete', stats: executionStats, errors: this.errors });

      return {
        success: executionStats.completedTasks > 0,
        synthesisResult: synthesisResult ?? undefined,
        summary: this.buildSummary(executionStats),
        tasks: this.taskQueue.getAllTasks(),
        stats: executionStats,
        errors: this.errors,
      };
    } catch (error) {
      this.currentPhase = 'failed';
      const message = (error as Error).message;
      this.errors.push({
        phase: 'execution',
        message,
        recovered: false,
      });
      this.emit({ type: 'swarm.error', error: message, phase: 'execution' });
      return this.buildErrorResult(message);
    } finally {
      this.workerPool.cleanup();
    }
  }

  /**
   * Phase 1: Decompose the task into subtasks.
   */
  private async decompose(task: string) {
    try {
      const result = await this._decomposer.decompose(task);

      if (result.subtasks.length < 2) {
        // Too simple for swarm mode
        return null;
      }

      return result;
    } catch (error) {
      this.errors.push({
        phase: 'decomposition',
        message: (error as Error).message,
        recovered: false,
      });
      this.emit({ type: 'swarm.error', error: (error as Error).message, phase: 'decomposition' });
      return null;
    }
  }

  // ─── V2: Planning Phase ───────────────────────────────────────────────

  /**
   * Create acceptance criteria and integration test plan.
   * Graceful: if planning fails, continues without criteria.
   */
  private async planExecution(task: string, decomposition: { subtasks: Array<{ id: string; description: string; type: string }> }): Promise<void> {
    try {
      // V3: Manager role handles planning
      const plannerModel = this.config.hierarchy?.manager?.model
        ?? this.config.plannerModel ?? this.config.orchestratorModel;

      this.emit({ type: 'swarm.role.action', role: 'manager', action: 'plan', model: plannerModel });
      this.logDecision('planning', `Creating acceptance criteria (manager: ${plannerModel})`,
        `Task has ${decomposition.subtasks.length} subtasks, planning to ensure quality`);
      const taskList = decomposition.subtasks
        .map(s => `- [${s.id}] (${s.type}): ${s.description}`)
        .join('\n');

      const response = await this.provider.chat(
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

      const parsed = this.parseJSON(response.content);
      if (parsed) {
        this.plan = {
          acceptanceCriteria: parsed.acceptanceCriteria ?? [],
          integrationTestPlan: parsed.integrationTestPlan,
          reasoning: parsed.reasoning ?? '',
        };
        this.emit({
          type: 'swarm.plan.complete',
          criteriaCount: this.plan.acceptanceCriteria.length,
          hasIntegrationPlan: !!this.plan.integrationTestPlan,
        });
      }
    } catch (error) {
      // Graceful fallback: continue without plan
      this.errors.push({
        phase: 'planning',
        message: `Planning failed (non-fatal): ${(error as Error).message}`,
        recovered: true,
      });
    }
  }

  // ─── V2: Wave Review ──────────────────────────────────────────────────

  /**
   * Review completed wave outputs against acceptance criteria.
   * May spawn fix-up tasks for issues found.
   */
  private async reviewWave(waveIndex: number): Promise<WaveReviewResult | null> {
    if (!this.config.enableWaveReview) return null;

    try {
      // V3: Manager role handles wave review
      const managerModel = this.config.hierarchy?.manager?.model
        ?? this.config.plannerModel ?? this.config.orchestratorModel;
      const managerPersona = this.config.hierarchy?.manager?.persona;

      this.emit({ type: 'swarm.role.action', role: 'manager', action: 'review', model: managerModel, wave: waveIndex + 1 });
      this.emit({ type: 'swarm.review.start', wave: waveIndex + 1 });
      this.logDecision('review', `Reviewing wave ${waveIndex + 1} outputs (manager: ${managerModel})`, 'Checking task outputs against acceptance criteria');

      const completedTasks = this.taskQueue.getAllTasks()
        .filter(t => t.status === 'completed' && t.wave === waveIndex);

      if (completedTasks.length === 0) {
        return { wave: waveIndex, assessment: 'good', taskAssessments: [], fixupTasks: [] };
      }

      // Build review prompt
      const taskSummaries = completedTasks.map(t => {
        const criteria = this.plan?.acceptanceCriteria.find(c => c.taskId === t.id);
        return `Task ${t.id}: ${t.description}
  Output: ${t.result?.output?.slice(0, 500) ?? 'No output'}
  Acceptance criteria: ${criteria?.criteria.join('; ') ?? 'None set'}`;
      }).join('\n\n');

      const reviewModel = managerModel;
      const reviewSystemPrompt = managerPersona
        ? `${managerPersona}\n\nYou are reviewing completed worker outputs. Assess each task against its acceptance criteria.\nRespond with JSON:`
        : `You are reviewing completed worker outputs. Assess each task against its acceptance criteria.\nRespond with JSON:`;

      const response = await this.provider.chat(
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

      const parsed = this.parseJSON(response.content);
      if (!parsed) return null;

      // Create fix-up tasks
      const fixupTasks: FixupTask[] = [];
      if (parsed.fixupInstructions) {
        for (const fix of parsed.fixupInstructions) {
          const fixupId = `fixup-${fix.fixesTaskId}-${Date.now()}`;
          const originalTask = this.taskQueue.getTask(fix.fixesTaskId);
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
          this.emit({ type: 'swarm.fixup.spawned', taskId: fixupId, fixesTaskId: fix.fixesTaskId, description: fix.description });
        }

        if (fixupTasks.length > 0) {
          this.taskQueue.addFixupTasks(fixupTasks);
        }
      }

      const result: WaveReviewResult = {
        wave: waveIndex,
        assessment: parsed.assessment ?? 'good',
        taskAssessments: parsed.taskAssessments ?? [],
        fixupTasks,
      };

      this.waveReviews.push(result);
      this.emit({
        type: 'swarm.review.complete',
        wave: waveIndex + 1,
        assessment: result.assessment,
        fixupCount: fixupTasks.length,
      });

      return result;
    } catch (error) {
      // Graceful: continue without review
      this.errors.push({
        phase: 'review',
        message: `Wave review failed (non-fatal): ${(error as Error).message}`,
        recovered: true,
      });
      return null;
    }
  }

  // ─── V2: Verification Phase ───────────────────────────────────────────

  /**
   * Run integration verification steps.
   */
  private async verifyIntegration(testPlan: NonNullable<SwarmPlan['integrationTestPlan']>): Promise<VerificationResult> {
    // V3: Judge role handles verification
    const verifyModel = this.config.hierarchy?.judge?.model
      ?? this.config.qualityGateModel ?? this.config.orchestratorModel;
    this.emit({ type: 'swarm.role.action', role: 'judge', action: 'verify', model: verifyModel });
    this.emit({ type: 'swarm.verify.start', stepCount: testPlan.steps.length });
    this.logDecision('verification', `Running ${testPlan.steps.length} verification steps (judge: ${verifyModel})`, testPlan.description);

    const stepResults: VerificationResult['stepResults'] = [];
    let allRequiredPassed = true;

    for (let i = 0; i < testPlan.steps.length; i++) {
      const step = testPlan.steps[i];
      try {
        // Use spawnAgent to execute verification command safely
        const verifierName = `swarm-verifier-${i}`;
        const result = await this.spawnAgentFn(verifierName,
          `Run this command and report the result: ${step.command}\nExpected: ${step.expectedResult ?? 'success'}`);

        const passed = result.success;
        stepResults.push({ step, passed, output: result.output.slice(0, 500) });

        if (!passed && step.required) {
          allRequiredPassed = false;
        }

        this.emit({ type: 'swarm.verify.step', stepIndex: i, description: step.description, passed });
      } catch (error) {
        const output = `Error: ${(error as Error).message}`;
        stepResults.push({ step, passed: false, output });
        if (step.required) allRequiredPassed = false;
        this.emit({ type: 'swarm.verify.step', stepIndex: i, description: step.description, passed: false });
      }
    }

    const verificationResult: VerificationResult = {
      passed: allRequiredPassed,
      stepResults,
      summary: allRequiredPassed
        ? `All ${stepResults.filter(r => r.passed).length}/${stepResults.length} steps passed`
        : `${stepResults.filter(r => !r.passed).length}/${stepResults.length} steps failed`,
    };

    this.verificationResult = verificationResult;
    this.emit({ type: 'swarm.verify.complete', result: verificationResult });

    return verificationResult;
  }

  /**
   * Handle verification failure: create fix-up tasks and re-verify.
   */
  private async handleVerificationFailure(verification: VerificationResult, task: string): Promise<void> {
    const maxRetries = this.config.maxVerificationRetries ?? 2;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      this.logDecision('verification',
        `Verification failed, fix-up attempt ${attempt + 1}/${maxRetries}`,
        `${verification.stepResults.filter(r => !r.passed).length} steps failed`);

      // Ask orchestrator what to fix
      try {
        const failedSteps = verification.stepResults
          .filter(r => !r.passed)
          .map(r => `- ${r.step.description}: ${r.output}`)
          .join('\n');

        const response = await this.provider.chat(
          [
            {
              role: 'system',
              content: `Verification failed. Analyze the failures and create fix-up tasks.
Respond with JSON: { "fixups": [{ "description": "what to fix", "type": "implement" }] }`,
            },
            { role: 'user', content: `Original task: ${task}\n\nFailed verifications:\n${failedSteps}` },
          ],
          { model: this.config.plannerModel ?? this.config.orchestratorModel, maxTokens: 1500, temperature: 0.3 },
        );

        const parsed = this.parseJSON(response.content);
        if (parsed?.fixups && parsed.fixups.length > 0) {
          const fixupTasks: FixupTask[] = parsed.fixups.map((f: { description: string; type?: string }, i: number) => ({
            id: `verify-fix-${attempt}-${i}-${Date.now()}`,
            description: f.description,
            type: (f.type ?? 'implement') as FixupTask['type'],
            dependencies: [],
            status: 'ready' as const,
            complexity: 4,
            wave: this.taskQueue.getCurrentWave(),
            attempts: 0,
            fixesTaskId: 'verification',
            fixInstructions: f.description,
          }));

          this.taskQueue.addFixupTasks(fixupTasks);

          // Execute fix-up wave
          this.currentPhase = 'executing';
          await this.executeWave(fixupTasks);

          // Re-verify
          this.currentPhase = 'verifying';
          verification = await this.verifyIntegration(this.plan!.integrationTestPlan!);
          if (verification.passed) return;
        }
      } catch {
        // Continue to next attempt
      }
    }
  }

  // ─── V2: Resume ───────────────────────────────────────────────────────

  /**
   * Resume execution from a saved checkpoint.
   */
  private async resumeExecution(task: string): Promise<SwarmExecutionResult> {
    const checkpoint = SwarmStateStore.loadLatest(
      this.config.stateDir ?? '.agent/swarm-state',
      this.config.resumeSessionId!,
    );

    if (!checkpoint) {
      this.logDecision('resume', 'No checkpoint found, starting fresh', `Session: ${this.config.resumeSessionId}`);
      // Clear resume flag and execute normally
      this.config.resumeSessionId = undefined;
      return this.execute(task);
    }

    this.logDecision('resume', `Resuming from wave ${checkpoint.currentWave}`, `Session: ${checkpoint.sessionId}`);
    this.emit({ type: 'swarm.state.resume', sessionId: checkpoint.sessionId, fromWave: checkpoint.currentWave });

    // Restore state
    if (checkpoint.plan) this.plan = checkpoint.plan;
    if (checkpoint.modelHealth.length > 0) this.healthTracker.restore(checkpoint.modelHealth);
    this.orchestratorDecisions = checkpoint.decisions ?? [];
    this.errors = checkpoint.errors ?? [];
    this.totalTokens = checkpoint.stats.totalTokens;
    this.totalCost = checkpoint.stats.totalCost;
    this.qualityRejections = checkpoint.stats.qualityRejections;
    this.retries = checkpoint.stats.retries;

    // Restore task queue
    this.taskQueue.restoreFromCheckpoint({
      taskStates: checkpoint.taskStates,
      waves: checkpoint.waves,
      currentWave: checkpoint.currentWave,
    });

    // Continue from where we left off
    this.currentPhase = 'executing';
    await this.executeWaves();

    // Continue with verification and synthesis as normal
    if (this.config.enableVerification && this.plan?.integrationTestPlan) {
      this.currentPhase = 'verifying';
      const verification = await this.verifyIntegration(this.plan.integrationTestPlan);
      if (!verification.passed) {
        await this.handleVerificationFailure(verification, task);
      }
    }

    this.currentPhase = 'synthesizing';
    const synthesisResult = await this.synthesize();

    this.currentPhase = 'completed';
    const executionStats = this.buildStats();
    this.checkpoint('final');
    this.emit({ type: 'swarm.complete', stats: executionStats, errors: this.errors });

    return {
      success: executionStats.completedTasks > 0,
      synthesisResult: synthesisResult ?? undefined,
      summary: this.buildSummary(executionStats),
      tasks: this.taskQueue.getAllTasks(),
      stats: executionStats,
      errors: this.errors,
    };
  }

  // ─── Wave Execution ───────────────────────────────────────────────────

  /**
   * Execute all waves in sequence, with review after each.
   */
  private async executeWaves(): Promise<void> {
    let waveIndex = this.taskQueue.getCurrentWave();
    const totalWaves = this.taskQueue.getTotalWaves();

    while (waveIndex < totalWaves && !this.cancelled) {
      const readyTasks = this.taskQueue.getReadyTasks();
      const queueStats = this.taskQueue.getStats();

      this.emit({
        type: 'swarm.wave.start',
        wave: waveIndex + 1,
        totalWaves,
        taskCount: readyTasks.length,
      });

      // Dispatch tasks up to concurrency limit
      await this.executeWave(readyTasks);

      // Wave complete stats
      const afterStats = this.taskQueue.getStats();
      const waveCompleted = afterStats.completed - (queueStats.completed);
      const waveFailed = afterStats.failed - (queueStats.failed);
      const waveSkipped = afterStats.skipped - (queueStats.skipped);

      this.emit({
        type: 'swarm.wave.complete',
        wave: waveIndex + 1,
        totalWaves,
        completed: waveCompleted,
        failed: waveFailed,
        skipped: waveSkipped,
      });

      // V2: Review wave outputs
      const review = await this.reviewWave(waveIndex);
      if (review && review.fixupTasks.length > 0) {
        // Execute fix-up tasks immediately
        await this.executeWave(review.fixupTasks);
      }

      // V2: Checkpoint after each wave
      this.checkpoint(`wave-${waveIndex}`);

      // Advance to next wave
      if (!this.taskQueue.advanceWave()) break;
      waveIndex++;
    }
  }

  /**
   * Execute a single wave's tasks with concurrency control.
   */
  private async executeWave(tasks: SwarmTask[]): Promise<void> {
    // Dispatch initial batch with stagger to avoid rate limit storms
    let taskIndex = 0;
    while (taskIndex < tasks.length && this.workerPool.availableSlots > 0 && !this.cancelled) {
      // Circuit breaker: wait if tripped
      if (this.isCircuitBreakerActive()) {
        const waitMs = this.circuitBreakerUntil - Date.now();
        if (waitMs > 0) await new Promise(resolve => setTimeout(resolve, waitMs));
        continue; // Re-check after wait
      }

      const task = tasks[taskIndex];
      await this.dispatchTask(task);
      taskIndex++;

      // Stagger dispatches to avoid rate limit storms
      if (taskIndex < tasks.length && this.workerPool.availableSlots > 0) {
        await new Promise(resolve => setTimeout(resolve, this.config.dispatchStaggerMs ?? 500));
      }
    }

    // Process completions and dispatch more tasks as slots open
    while (this.workerPool.activeCount > 0 && !this.cancelled) {
      const completed = await this.workerPool.waitForAny();
      if (!completed) break;

      // H2: Use per-task startedAt for accurate duration (not orchestrator startTime)
      await this.handleTaskCompletion(completed.taskId, completed.result, completed.startedAt);

      // Emit budget update
      this.emitBudgetUpdate();

      // Emit status update
      this.emitStatusUpdate();

      // Dispatch more tasks if slots available and tasks remain
      while (taskIndex < tasks.length && this.workerPool.availableSlots > 0 && !this.cancelled) {
        const task = tasks[taskIndex];
        if (task.status === 'ready') {
          await this.dispatchTask(task);
          // Stagger dispatches to avoid rate limit storms
          if (taskIndex + 1 < tasks.length && this.workerPool.availableSlots > 0) {
            await new Promise(resolve => setTimeout(resolve, this.config.dispatchStaggerMs ?? 500));
          }
        }
        taskIndex++;
      }

      // Also check for cross-wave ready tasks to fill slots (skip if circuit breaker active)
      if (this.workerPool.availableSlots > 0 && !this.isCircuitBreakerActive()) {
        const moreReady = this.taskQueue.getAllReadyTasks()
          .filter(t => !this.workerPool.getActiveWorkerStatus().some(w => w.taskId === t.id));

        for (let i = 0; i < moreReady.length; i++) {
          if (this.workerPool.availableSlots <= 0) break;
          await this.dispatchTask(moreReady[i]);
          // Stagger dispatches to avoid rate limit storms
          if (i + 1 < moreReady.length && this.workerPool.availableSlots > 0) {
            await new Promise(resolve => setTimeout(resolve, this.config.dispatchStaggerMs ?? 500));
          }
        }
      }
    }
  }

  /**
   * Dispatch a single task to a worker.
   */
  private async dispatchTask(task: SwarmTask): Promise<void> {
    const worker = this.workerPool.selectWorker(task);
    if (!worker) {
      // M2: Emit error and mark task failed instead of silently returning
      this.taskQueue.markFailed(task.id, 0);
      this.emit({
        type: 'swarm.task.failed',
        taskId: task.id,
        error: `No worker available for task type: ${task.type}`,
        attempt: 0,
        maxAttempts: 0,
        willRetry: false,
      });
      return;
    }

    try {
      this.taskQueue.markDispatched(task.id, worker.model);
      await this.workerPool.dispatch(task);

      this.emit({
        type: 'swarm.task.dispatched',
        taskId: task.id,
        description: task.description,
        model: worker.model,
        workerName: worker.name,
      });
    } catch (error) {
      this.errors.push({
        taskId: task.id,
        phase: 'dispatch',
        message: (error as Error).message,
        recovered: false,
      });
      this.emit({
        type: 'swarm.task.failed',
        taskId: task.id,
        error: (error as Error).message,
        attempt: task.attempts,
        maxAttempts: 1 + this.config.workerRetries,
        willRetry: false,
      });
      this.taskQueue.markFailed(task.id, 0);
    }
  }

  /**
   * Handle a completed task: quality gate, bookkeeping, retry logic, model health, failover.
   */
  private async handleTaskCompletion(taskId: string, spawnResult: import('../agent-registry.js').SpawnResult, startedAt: number): Promise<void> {
    const task = this.taskQueue.getTask(taskId);
    if (!task) return;

    const durationMs = Date.now() - startedAt;
    const taskResult = this.workerPool.toTaskResult(spawnResult, task, durationMs);

    // Track model usage
    const model = task.assignedModel ?? 'unknown';
    const usage = this.modelUsage.get(model) ?? { tasks: 0, tokens: 0, cost: 0 };
    usage.tasks++;
    usage.tokens += taskResult.tokensUsed;
    usage.cost += taskResult.costUsed;
    this.modelUsage.set(model, usage);

    this.totalTokens += taskResult.tokensUsed;
    this.totalCost += taskResult.costUsed;

    if (!spawnResult.success) {
      // V2: Record model health
      const errorMsg = spawnResult.output.toLowerCase();
      const is429 = errorMsg.includes('429') || errorMsg.includes('rate');
      const is402 = errorMsg.includes('402') || errorMsg.includes('spend limit');
      const errorType = is429 ? '429' : is402 ? '402' : 'error';
      this.healthTracker.recordFailure(model, errorType as '429' | '402' | 'error');
      this.emit({ type: 'swarm.model.health', record: { model, ...this.getModelHealthSummary(model) } });

      // Feed circuit breaker
      if (is429 || is402) {
        this.recordRateLimit();
      }

      // V2: Model failover on rate limits
      if ((is429 || is402) && this.config.enableModelFailover) {
        const capability: WorkerCapability = SUBTASK_TO_CAPABILITY[task.type] ?? 'code';
        const alternative = selectAlternativeModel(this.config.workers, model, capability, this.healthTracker);
        if (alternative) {
          this.emit({
            type: 'swarm.model.failover',
            taskId,
            fromModel: model,
            toModel: alternative.model,
            reason: errorType,
          });
          task.assignedModel = alternative.model;
          this.logDecision('failover', `Switched ${taskId} from ${model} to ${alternative.model}`, `${errorType} error`);
        }
      }

      // Worker failed — use higher retry limit for rate limit errors
      const retryLimit = (is429 || is402)
        ? (this.config.rateLimitRetries ?? 3)
        : this.config.workerRetries;
      const canRetry = this.taskQueue.markFailed(taskId, retryLimit);
      if (canRetry) {
        this.retries++;

        // Non-blocking cooldown: set retryAfter timestamp instead of blocking
        if (is429 || is402) {
          const baseDelay = this.config.retryBaseDelayMs ?? 5000;
          const cooldownMs = Math.min(baseDelay * Math.pow(2, task.attempts - 1), 30000);
          this.taskQueue.setRetryAfter(taskId, cooldownMs);
        }
      }

      this.emit({
        type: 'swarm.task.failed',
        taskId,
        error: spawnResult.output.slice(0, 200),
        attempt: task.attempts,
        maxAttempts: 1 + this.config.workerRetries,
        willRetry: canRetry,
      });
      return;
    }

    // V2: Record model health on success
    this.healthTracker.recordSuccess(model, durationMs);

    // Run quality gate if enabled — skip under API pressure or on retried tasks
    const recentRLCount = this.recentRateLimits.filter(t => t > Date.now() - 30_000).length;
    const shouldRunQualityGate = this.config.qualityGates
      && task.attempts <= 1
      && Date.now() >= this.circuitBreakerUntil
      && recentRLCount < 2;

    if (shouldRunQualityGate) {
      // V3: Judge role handles quality gates
      const judgeModel = this.config.hierarchy?.judge?.model
        ?? this.config.qualityGateModel ?? this.config.orchestratorModel;
      const judgeConfig: QualityGateConfig = {
        model: judgeModel,
        persona: this.config.hierarchy?.judge?.persona,
      };

      this.emit({ type: 'swarm.role.action', role: 'judge', action: 'quality-gate', model: judgeModel, taskId });

      const quality = await evaluateWorkerOutput(
        this.provider,
        judgeModel,
        task,
        taskResult,
        judgeConfig,
      );

      taskResult.qualityScore = quality.score;
      taskResult.qualityFeedback = quality.feedback;

      if (!quality.passed) {
        this.qualityRejections++;
        const canRetry = this.taskQueue.markFailed(taskId, this.config.workerRetries);
        if (canRetry) {
          this.retries++;
        }

        // M1: Only emit quality.rejected (not duplicate task.failed)
        this.emit({
          type: 'swarm.quality.rejected',
          taskId,
          score: quality.score,
          feedback: quality.feedback,
        });
        return;
      }
    }

    // Task passed — mark completed
    this.taskQueue.markCompleted(taskId, taskResult);

    // H6: Post findings to blackboard with error handling
    if (this.blackboard && taskResult.findings) {
      try {
        for (const finding of taskResult.findings) {
          this.blackboard.post(`swarm-worker-${taskId}`, {
            topic: `swarm.task.${task.type}`,
            content: finding,
            type: 'progress',
            confidence: (taskResult.qualityScore ?? 3) / 5,
            tags: ['swarm', task.type],
            relatedFiles: task.targetFiles,
          });
        }
      } catch {
        // Don't crash orchestrator on blackboard failures
        this.errors.push({
          taskId,
          phase: 'execution',
          message: 'Failed to post findings to blackboard',
          recovered: true,
        });
      }
    }

    this.emit({
      type: 'swarm.task.completed',
      taskId,
      success: true,
      tokensUsed: taskResult.tokensUsed,
      costUsed: taskResult.costUsed,
      durationMs: taskResult.durationMs,
      qualityScore: taskResult.qualityScore,
    });
  }

  /**
   * Phase 4: Synthesize all completed task outputs.
   */
  private async synthesize() {
    const tasks = this.taskQueue.getAllTasks();
    const outputs = tasks
      .filter(t => t.status === 'completed')
      .map(t => taskResultToAgentOutput(t))
      .filter((o): o is NonNullable<typeof o> => o !== null);

    if (outputs.length === 0) return null;

    try {
      return await this.synthesizer.synthesize(outputs);
    } catch (error) {
      this.errors.push({
        phase: 'synthesis',
        message: (error as Error).message,
        recovered: true,
      });
      // Fallback: concatenate outputs
      return this.synthesizer.synthesizeFindings(outputs);
    }
  }

  /**
   * Get live status for TUI.
   */
  // M5: Use explicit phase tracking instead of inferring from queue state
  getStatus(): SwarmStatus {
    const stats = this.taskQueue.getStats();

    return {
      phase: this.cancelled ? 'failed' : this.currentPhase,
      currentWave: this.taskQueue.getCurrentWave() + 1,
      totalWaves: this.taskQueue.getTotalWaves(),
      activeWorkers: this.workerPool.getActiveWorkerStatus(),
      queue: stats,
      budget: {
        tokensUsed: this.totalTokens,
        tokensTotal: this.config.totalBudget,
        costUsed: this.totalCost,
        costTotal: this.config.maxCost,
      },
    };
  }

  /**
   * Cancel the swarm execution.
   * M6: Wait for active workers before cleanup.
   */
  async cancel(): Promise<void> {
    this.cancelled = true;
    this.currentPhase = 'failed';
    await this.workerPool.cancelAll();
  }

  // ─── Circuit Breaker ────────────────────────────────────────────────

  /**
   * Record a rate limit hit and check if the circuit breaker should trip.
   */
  private recordRateLimit(): void {
    const now = Date.now();
    this.recentRateLimits.push(now);

    // Prune entries older than the window
    const cutoff = now - SwarmOrchestrator.CIRCUIT_BREAKER_WINDOW_MS;
    this.recentRateLimits = this.recentRateLimits.filter(t => t > cutoff);

    if (this.recentRateLimits.length >= SwarmOrchestrator.CIRCUIT_BREAKER_THRESHOLD) {
      this.circuitBreakerUntil = now + SwarmOrchestrator.CIRCUIT_BREAKER_PAUSE_MS;
      this.emit({
        type: 'swarm.circuit.open',
        recentCount: this.recentRateLimits.length,
        pauseMs: SwarmOrchestrator.CIRCUIT_BREAKER_PAUSE_MS,
      });
      this.logDecision('circuit-breaker', 'Tripped — pausing all dispatch',
        `${this.recentRateLimits.length} rate limits in ${SwarmOrchestrator.CIRCUIT_BREAKER_WINDOW_MS / 1000}s window`);
    }
  }

  /**
   * Check if the circuit breaker is currently active.
   * Returns true if dispatch should be paused.
   */
  private isCircuitBreakerActive(): boolean {
    if (Date.now() < this.circuitBreakerUntil) return true;
    if (this.circuitBreakerUntil > 0) {
      // Circuit just closed
      this.circuitBreakerUntil = 0;
      this.emit({ type: 'swarm.circuit.closed' });
    }
    return false;
  }

  // ─── V2: Decision Logging ─────────────────────────────────────────────

  private logDecision(phase: string, decision: string, reasoning: string): void {
    const entry: OrchestratorDecision = {
      timestamp: Date.now(),
      phase,
      decision,
      reasoning,
    };
    this.orchestratorDecisions.push(entry);
    this.emit({ type: 'swarm.orchestrator.decision', decision: entry });
  }

  // ─── V2: Persistence ──────────────────────────────────────────────────

  private checkpoint(_label: string): void {
    if (!this.config.enablePersistence || !this.stateStore) return;

    try {
      const queueState = this.taskQueue.getCheckpointState();
      this.stateStore.saveCheckpoint({
        sessionId: this.stateStore.id,
        timestamp: Date.now(),
        phase: this.currentPhase,
        plan: this.plan,
        taskStates: queueState.taskStates,
        waves: queueState.waves,
        currentWave: queueState.currentWave,
        stats: {
          totalTokens: this.totalTokens,
          totalCost: this.totalCost,
          qualityRejections: this.qualityRejections,
          retries: this.retries,
        },
        modelHealth: this.healthTracker.getAllRecords(),
        decisions: this.orchestratorDecisions,
        errors: this.errors,
      });

      this.emit({
        type: 'swarm.state.checkpoint',
        sessionId: this.stateStore.id,
        wave: this.taskQueue.getCurrentWave(),
      });
    } catch (error) {
      this.errors.push({
        phase: 'persistence',
        message: `Checkpoint failed (non-fatal): ${(error as Error).message}`,
        recovered: true,
      });
    }
  }

  // ─── Private Helpers ───────────────────────────────────────────────────

  private emitBudgetUpdate(): void {
    this.emit({
      type: 'swarm.budget.update',
      tokensUsed: this.totalTokens,
      tokensTotal: this.config.totalBudget,
      costUsed: this.totalCost,
      costTotal: this.config.maxCost,
    });
  }

  private emitStatusUpdate(): void {
    this.emit({ type: 'swarm.status', status: this.getStatus() });
  }

  private buildStats(): SwarmExecutionStats {
    const queueStats = this.taskQueue.getStats();
    return {
      totalTasks: queueStats.total,
      completedTasks: queueStats.completed,
      failedTasks: queueStats.failed,
      skippedTasks: queueStats.skipped,
      totalWaves: this.taskQueue.getTotalWaves(),
      totalTokens: this.totalTokens,
      totalCost: this.totalCost,
      totalDurationMs: Date.now() - this.startTime,
      qualityRejections: this.qualityRejections,
      retries: this.retries,
      modelUsage: this.modelUsage,
    };
  }

  private buildSummary(stats: SwarmExecutionStats): string {
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
    if (this.verificationResult) {
      parts.push(`  Verification: ${this.verificationResult.passed ? 'PASSED' : 'FAILED'}`);
    }

    return parts.join('\n');
  }

  private buildErrorResult(message: string): SwarmExecutionResult {
    return {
      success: false,
      summary: `Swarm failed: ${message}`,
      tasks: this.taskQueue.getAllTasks(),
      stats: this.buildStats(),
      errors: this.errors,
    };
  }

  /** Parse JSON from LLM response, handling markdown code blocks. */
  private parseJSON(content: string): Record<string, any> | null {
    try {
      // Strip markdown code blocks if present
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

  /** Get a model health summary for emitting events. */
  private getModelHealthSummary(model: string): Omit<import('./types.js').ModelHealthRecord, 'model'> {
    const records = this.healthTracker.getAllRecords();
    const record = records.find(r => r.model === model);
    return record
      ? { successes: record.successes, failures: record.failures, rateLimits: record.rateLimits, lastRateLimit: record.lastRateLimit, averageLatencyMs: record.averageLatencyMs, healthy: record.healthy }
      : { successes: 0, failures: 0, rateLimits: 0, averageLatencyMs: 0, healthy: true };
  }
}

/**
 * Factory function.
 */
export function createSwarmOrchestrator(
  config: SwarmConfig,
  provider: LLMProvider,
  agentRegistry: AgentRegistry,
  spawnAgentFn: SpawnAgentFn,
  blackboard?: SharedBlackboard,
): SwarmOrchestrator {
  return new SwarmOrchestrator(config, provider, agentRegistry, spawnAgentFn, blackboard);
}
