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

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { LLMProvider, LLMProviderWithTools, ToolDefinitionSchema } from '../../providers/types.js';
import type { AgentRegistry } from '../agent-registry.js';
import type { SharedBlackboard } from '../shared-blackboard.js';
import { createSmartDecomposer, parseDecompositionResponse, validateDecomposition, type LLMDecomposeFunction, type SmartDecompositionResult } from '../smart-decomposer.js';
import { createResultSynthesizer } from '../result-synthesizer.js';
import type {
  SwarmConfig,
  SwarmExecutionResult,
  SwarmExecutionStats,
  SwarmError,
  SwarmStatus,
  SwarmTask,
  SwarmTaskResult,
  SwarmPlan,
  WaveReviewResult,
  VerificationResult,
  FixupTask,
  OrchestratorDecision,
  WorkerCapability,
  ArtifactInventory,
  ArtifactEntry,
} from './types.js';
import { taskResultToAgentOutput, DEFAULT_SWARM_CONFIG, getTaskTypeConfig } from './types.js';
import { SwarmTaskQueue, createSwarmTaskQueue } from './task-queue.js';
import { createSwarmBudgetPool, type SwarmBudgetPool } from './swarm-budget.js';
import { SwarmWorkerPool, createSwarmWorkerPool, type SpawnAgentFn } from './worker-pool.js';
import { evaluateWorkerOutput, runPreFlightChecks, checkArtifacts, checkArtifactsEnhanced, runConcreteChecks, type QualityGateConfig } from './swarm-quality-gate.js';
import { ModelHealthTracker, selectAlternativeModel } from './model-selector.js';
import { SwarmStateStore } from './swarm-state-store.js';
import type { SwarmEvent } from './swarm-events.js';
import type { SpawnResult } from '../agent-registry.js';
import { createSharedContextState, type SharedContextState } from '../../shared/shared-context-state.js';
import { createSharedEconomicsState, type SharedEconomicsState } from '../../shared/shared-economics-state.js';
import { createSharedContextEngine, type SharedContextEngine } from '../../shared/context-engine.js';

// ─── Hollow Completion Detection ──────────────────────────────────────────

/**
 * V11: Hollow completion detection — catches empty completions AND "success" with failure language.
 * Zero tool calls AND trivial output is always hollow.
 * Additionally, success=true but output containing failure admissions is also hollow —
 * this catches workers that report success but actually did no useful work.
 */
const FAILURE_INDICATORS = [
  'budget exhausted', 'unable to complete', 'could not complete',
  'ran out of budget', 'no changes were made', 'no files were modified',
  'no files were created', 'failed to complete', 'before research could begin',
  'i was unable to', 'i could not', 'unfortunately i',
];

const BOILERPLATE_INDICATORS = [
  'task completed successfully', 'i have completed the task',
  'the task has been completed', 'done', 'completed', 'finished',
  'no issues found', 'everything looks good', 'all tasks completed',
];

export function isHollowCompletion(spawnResult: SpawnResult, taskType?: string, swarmConfig?: import('./types.js').SwarmConfig): boolean {
  // Timeout uses toolCalls === -1, not hollow
  if ((spawnResult.metrics.toolCalls ?? 0) === -1) return false;

  const toolCalls = spawnResult.metrics.toolCalls ?? 0;

  // Truly empty completions: zero tools AND trivial output
  // P4: Higher threshold (120 chars) + configurable via SwarmConfig
  const hollowThreshold = swarmConfig?.hollowOutputThreshold ?? 120;
  if (toolCalls === 0
    && (spawnResult.output?.trim().length ?? 0) < hollowThreshold) {
    return true;
  }

  // P4: Boilerplate detection — zero tools AND short output that's just boilerplate
  if (toolCalls === 0 && (spawnResult.output?.trim().length ?? 0) < 300) {
    const outputLower = (spawnResult.output ?? '').toLowerCase().trim();
    if (BOILERPLATE_INDICATORS.some(b => outputLower.includes(b))) {
      return true;
    }
  }

  // "Success" that admits failure: worker claims success but output contains failure language
  if (spawnResult.success) {
    const outputLower = (spawnResult.output ?? '').toLowerCase();
    if (FAILURE_INDICATORS.some(f => outputLower.includes(f))) {
      return true;
    }
  }

  // V7: Use configurable requiresToolCalls from TaskTypeConfig.
  // For action-oriented tasks (implement/test/refactor/etc), zero tool calls is ALWAYS hollow.
  if (taskType) {
    const typeConfig = getTaskTypeConfig(taskType, swarmConfig);
    if (typeConfig.requiresToolCalls && toolCalls === 0) {
      return true;
    }
  }

  return false;
}

// ─── Event Emitter ─────────────────────────────────────────────────────────

export type SwarmEventListener = (event: SwarmEvent) => void;

// ─── Orchestrator ──────────────────────────────────────────────────────────

export class SwarmOrchestrator {
  private config: SwarmConfig;
  private provider: LLMProvider;
  private blackboard?: SharedBlackboard;

  // Phase 3.1+3.2: Shared state for cross-worker learning
  private sharedContextState!: SharedContextState;
  private sharedEconomicsState!: SharedEconomicsState;
  private sharedContextEngine!: SharedContextEngine;

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

  // Orchestrator's own LLM usage (separate from worker usage)
  private orchestratorTokens = 0;
  private orchestratorCost = 0;
  private orchestratorCalls = 0;

  // V2: Planning, review, verification, health, persistence
  private plan?: SwarmPlan;
  private waveReviews: WaveReviewResult[] = [];
  private verificationResult?: VerificationResult;
  private artifactInventory?: ArtifactInventory;
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

  // P3: Per-model quality gate circuit breaker (replaces global circuit breaker)
  private perModelQualityRejections = new Map<string, number>();
  private qualityGateDisabledModels = new Set<string>();
  private static readonly QUALITY_CIRCUIT_BREAKER_THRESHOLD = 5;

  // Hollow completion streak: early termination when single-model swarm produces only hollows
  private hollowStreak = 0;
  private static readonly HOLLOW_STREAK_THRESHOLD = 3;

  // V7: Global dispatch + hollow ratio tracking for multi-model termination
  private totalDispatches = 0;
  private totalHollows = 0;

  // Hollow ratio warning (fired once, then suppressed to avoid log spam)
  private hollowRatioWarned = false;

  // P7: Adaptive dispatch stagger — increases on rate limits, decreases on success
  private adaptiveStaggerMs: number = 0; // Initialized from config in constructor

  // F25: Consecutive timeout tracking per task — early-fail after limit
  private taskTimeoutCounts = new Map<string, number>();

  // Original prompt for re-planning on resume
  private originalPrompt = '';

  // Mid-swarm re-planning: only once per swarm execution
  private hasReplanned = false;

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
    this.adaptiveStaggerMs = this.getStaggerMs();

    // Phase 3.1+3.2: Shared context & economics for cross-worker learning
    this.sharedContextState = createSharedContextState({
      staticPrefix: 'You are a swarm worker agent.',
      maxFailures: 100,
      maxReferences: 200,
    });
    this.sharedEconomicsState = createSharedEconomicsState({
      globalDoomLoopThreshold: 10,
    });
    this.sharedContextEngine = createSharedContextEngine(this.sharedContextState, {
      maxFailuresInPrompt: 5,
      includeInsights: true,
    });

    this.taskQueue = createSwarmTaskQueue();
    this.budgetPool = createSwarmBudgetPool(this.config);
    this.workerPool = createSwarmWorkerPool(
      this.config,
      agentRegistry,
      spawnAgentFn,
      this.budgetPool,
      this.healthTracker,
      this.sharedContextEngine,
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
      // V7: Dynamically build the allowed type list from built-in + user-defined types
      const builtinTypes = ['research', 'analysis', 'design', 'implement', 'test', 'refactor', 'review', 'document', 'integrate', 'deploy', 'merge'];
      const customTypes = Object.keys(this.config.taskTypes ?? {}).filter(t => !builtinTypes.includes(t));
      const allTypes = [...builtinTypes, ...customTypes];
      const typeListStr = allTypes.map(t => `"${t}"`).join(' | ');

      // Build custom type descriptions so the LLM knows when to use them
      let customTypeSection = '';
      if (customTypes.length > 0) {
        const descriptions = customTypes.map(t => {
          const cfg = this.config.taskTypes![t];
          const parts = [`  - "${t}"`];
          if (cfg.capability) parts.push(`(capability: ${cfg.capability})`);
          if (cfg.promptTemplate) parts.push(`— uses ${cfg.promptTemplate} workflow`);
          if (cfg.timeout) parts.push(`— timeout: ${Math.round(cfg.timeout / 60000)}min`);
          return parts.join(' ');
        }).join('\n');
        customTypeSection = `\n\nCustom task types available:\n${descriptions}\nUse these when their description matches the subtask's purpose.`;
      }

      const systemPrompt = `You are a task decomposition expert. Break down the given task into well-defined subtasks with clear dependencies.

CRITICAL: Dependencies MUST use zero-based integer indices referring to other subtasks in the array.

Respond with valid JSON matching this exact schema:
{
  "subtasks": [
    {
      "description": "Clear description of what this subtask does",
      "type": ${typeListStr},
      "complexity": 1-10,
      "dependencies": [0, 1],
      "parallelizable": true | false,
      "relevantFiles": ["src/path/to/file.ts"]
    }
  ],
  "strategy": "sequential" | "parallel" | "hierarchical" | "adaptive" | "pipeline",
  "reasoning": "Brief explanation of why this decomposition was chosen"
}${customTypeSection}

EXAMPLE 1 — Research task (3 parallel research + 1 merge):
{
  "subtasks": [
    { "description": "Research React state management", "type": "research", "complexity": 3, "dependencies": [], "parallelizable": true },
    { "description": "Research routing options", "type": "research", "complexity": 3, "dependencies": [], "parallelizable": true },
    { "description": "Research testing frameworks", "type": "research", "complexity": 2, "dependencies": [], "parallelizable": true },
    { "description": "Synthesize findings into recommendation", "type": "merge", "complexity": 4, "dependencies": [0, 1, 2], "parallelizable": false }
  ],
  "strategy": "parallel",
  "reasoning": "Independent research tasks feed into a single merge"
}

EXAMPLE 2 — Implementation task (sequential chain):
{
  "subtasks": [
    { "description": "Design API schema", "type": "design", "complexity": 4, "dependencies": [], "parallelizable": false },
    { "description": "Implement API endpoints", "type": "implement", "complexity": 6, "dependencies": [0], "parallelizable": false },
    { "description": "Write integration tests", "type": "test", "complexity": 3, "dependencies": [1], "parallelizable": false }
  ],
  "strategy": "sequential",
  "reasoning": "Each step depends on the previous"
}

Rules:
- Dependencies MUST be integer indices (e.g., [0, 1]), NOT descriptions or strings
- Each subtask must have a clear, actionable description
- Mark subtasks as parallelizable: true if they don't depend on each other
- If there are multiple independent subtasks, ALWAYS create a final merge task that depends on ALL of them
- Complexity 1-3: simple, 4-6: moderate, 7-10: complex
- Return at least 2 subtasks for non-trivial tasks`;

      const response = await this.provider.chat(
        [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: task },
        ],
        {
          model: this.config.orchestratorModel,
          maxTokens: 16000,
          temperature: 0.3,
        },
      );

      this.trackOrchestratorUsage(response as any, 'decompose');

      // Use parseDecompositionResponse which handles markdown code blocks and edge cases
      const result = parseDecompositionResponse(response.content);

      // If decomposition returned 0 subtasks, log diagnostics and retry with explicit JSON instruction
      if (result.subtasks.length === 0) {
        const snippet = response.content?.slice(0, 500) ?? '(empty response)';
        const parseError = result.parseError ?? 'unknown';
        this.errors.push({
          phase: 'decomposition',
          message: `LLM returned no subtasks. Parse error: ${parseError}. Response preview: ${snippet}`,
          recovered: true,
        });
        this.emit({
          type: 'swarm.orchestrator.decision' as any,
          decision: {
            timestamp: Date.now(),
            phase: 'decomposition',
            decision: `Empty decomposition — retrying with explicit JSON instruction`,
            reasoning: `Parse error: ${parseError}. Response preview (first 500 chars): ${snippet}`,
          },
        });

        // Retry with explicit JSON instruction — don't include previous truncated response (wastes input tokens)
        const retryResponse = await this.provider.chat(
          [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: `${task}\n\nIMPORTANT: Your previous attempt was truncated or could not be parsed (${parseError}). Return ONLY a raw JSON object with NO markdown formatting, NO explanation text, NO code fences. The JSON must have a "subtasks" array with at least 2 entries matching the schema above. Keep subtask descriptions concise to avoid truncation.` },
          ],
          {
            model: this.config.orchestratorModel,
            maxTokens: 16000,
            temperature: 0.2,
          },
        );
        this.trackOrchestratorUsage(retryResponse as any, 'decompose-retry');

        const retryResult = parseDecompositionResponse(retryResponse.content);
        if (retryResult.subtasks.length === 0) {
          const retrySnippet = retryResponse.content?.slice(0, 500) ?? '(empty response)';
          this.errors.push({
            phase: 'decomposition',
            message: `Retry also returned no subtasks. Response preview: ${retrySnippet}`,
            recovered: false,
          });
        }
        return retryResult;
      }

      return result;
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

  /** Get shared context state for cross-worker failure learning. */
  getSharedContextState(): SharedContextState {
    return this.sharedContextState;
  }

  /** Get shared economics state for cross-worker doom loop aggregation. */
  getSharedEconomicsState(): SharedEconomicsState {
    return this.sharedEconomicsState;
  }

  /** Get shared context engine for cross-worker failure learning. */
  getSharedContextEngine(): SharedContextEngine {
    return this.sharedContextEngine;
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
   * Track token usage from an orchestrator LLM call.
   */
  private trackOrchestratorUsage(response: { usage?: { total_tokens?: number; prompt_tokens?: number; completion_tokens?: number; inputTokens?: number; outputTokens?: number; cost?: number } }, purpose: string): void {
    if (!response.usage) return;
    // Handle both raw API fields (total_tokens, prompt_tokens, completion_tokens)
    // and ChatResponse fields (inputTokens, outputTokens)
    const input = response.usage.prompt_tokens ?? response.usage.inputTokens ?? 0;
    const output = response.usage.completion_tokens ?? response.usage.outputTokens ?? 0;
    const tokens = response.usage.total_tokens ?? (input + output);
    const cost = response.usage.cost ?? tokens * 0.000015; // ~$15/M tokens average for orchestrator models
    this.orchestratorTokens += tokens;
    this.orchestratorCost += cost;
    this.orchestratorCalls++;

    this.emit({
      type: 'swarm.orchestrator.llm' as any,
      model: this.config.orchestratorModel,
      purpose,
      tokens,
      cost,
    });
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
    this.originalPrompt = task;

    try {
      // V2: Check for resume
      if (this.config.resumeSessionId && this.stateStore) {
        return await this.resumeExecution(task);
      }

      // Phase 1: Decompose
      this.currentPhase = 'decomposing';
      this.emit({ type: 'swarm.phase.progress', phase: 'decomposing', message: 'Decomposing task into subtasks...' });
      let decomposeOutcome = await this.decompose(task);
      if (!decomposeOutcome.result) {
        this.currentPhase = 'failed';
        return this.buildErrorResult(`Decomposition failed: ${decomposeOutcome.failureReason}`);
      }
      let decomposition = decomposeOutcome.result;

      // F5: Validate decomposition — check for cycles, invalid deps, granularity
      const validation = validateDecomposition(decomposition);
      if (validation.warnings.length > 0) {
        this.logDecision('decomposition-validation',
          `Warnings: ${validation.warnings.join('; ')}`, '');
      }
      if (!validation.valid) {
        this.logDecision('decomposition-validation',
          `Invalid decomposition: ${validation.issues.join('; ')}`, 'Retrying...');
        // Retry decomposition once with feedback
        const retryOutcome = await this.decompose(
          `${task}\n\nIMPORTANT: Previous decomposition was invalid: ${validation.issues.join('. ')}. Fix these issues.`,
        );
        if (!retryOutcome.result) {
          this.currentPhase = 'failed';
          return this.buildErrorResult(`Decomposition validation failed: ${validation.issues.join('; ')}`);
        }
        decomposition = retryOutcome.result;
        const retryValidation = validateDecomposition(decomposition);
        if (!retryValidation.valid) {
          this.logDecision('decomposition-validation',
            `Retry still invalid: ${retryValidation.issues.join('; ')}`, 'Proceeding anyway');
        }
      }

      // Phase 2: Schedule into waves
      this.currentPhase = 'scheduling';
      this.emit({ type: 'swarm.phase.progress', phase: 'scheduling', message: `Scheduling ${decomposition.subtasks.length} subtasks into waves...` });
      this.taskQueue.loadFromDecomposition(decomposition, this.config);

      // F3: Dynamic orchestrator reserve scaling based on subtask count.
      // More subtasks = more quality gate calls, synthesis work, and review overhead.
      // Formula: max(configured ratio, 5% per subtask), capped at 40%.
      const subtaskCount = decomposition.subtasks.length;
      const dynamicReserveRatio = Math.min(0.40, Math.max(
        this.config.orchestratorReserveRatio,
        subtaskCount * 0.05,
      ));
      if (dynamicReserveRatio > this.config.orchestratorReserveRatio) {
        this.logDecision('budget-scaling',
          `Scaled orchestrator reserve from ${(this.config.orchestratorReserveRatio * 100).toFixed(0)}% to ${(dynamicReserveRatio * 100).toFixed(0)}% for ${subtaskCount} subtasks`,
          '');
      }

      // Foundation task detection: tasks that are the sole dependency of 3+ downstream
      // tasks are critical — if they fail, the entire swarm cascade-skips.
      // Give them extra retries and timeout scaling.
      this.detectFoundationTasks();

      // D3/F1: Probe model capability before dispatch (default: true)
      if (this.config.probeModels !== false) {
        await this.probeModelCapability();

        // F15/F23: Handle all-models-failed probe scenario
        // Resolve strategy: explicit probeFailureStrategy > legacy ignoreProbeFailures > default 'warn-and-try'
        const probeStrategy = this.config.probeFailureStrategy
          ?? (this.config.ignoreProbeFailures ? 'warn-and-try' : 'warn-and-try');
        const uniqueModels = [...new Set(this.config.workers.map(w => w.model))];
        const healthyModels = this.healthTracker.getHealthy(uniqueModels);

        if (healthyModels.length === 0 && uniqueModels.length > 0) {
          if (probeStrategy === 'abort') {
            // Hard abort — no tasks dispatched
            const reason = `All ${uniqueModels.length} worker model(s) failed capability probes — no model can make tool calls. Aborting swarm to prevent budget waste. Fix model configuration and retry.`;
            this.logDecision('probe-abort', reason, `Models tested: ${uniqueModels.join(', ')}`);
            this.emit({ type: 'swarm.abort', reason });
            this.skipRemainingTasks(reason);
            const totalTasks = this.taskQueue.getStats().total;
            const abortStats: SwarmExecutionStats = {
              completedTasks: 0, failedTasks: 0, skippedTasks: totalTasks,
              totalTasks, totalWaves: 0, totalTokens: 0, totalCost: 0,
              totalDurationMs: Date.now() - this.startTime,
              qualityRejections: 0, retries: 0,
              modelUsage: new Map(),
            };
            this.emit({ type: 'swarm.complete', stats: abortStats, errors: this.errors });
            return {
              success: false, summary: reason,
              tasks: this.taskQueue.getAllTasks(), stats: abortStats, errors: this.errors,
            };
          } else {
            // F23: warn-and-try — log warning, reset health, let real tasks prove capability
            this.logDecision('probe-warning',
              `All ${uniqueModels.length} model(s) failed probe — continuing anyway (strategy: warn-and-try)`,
              'Will abort after first real task failure if model cannot use tools');
            // Reset health so dispatch doesn't skip all models
            for (const model of uniqueModels) {
              this.healthTracker.recordSuccess(model, 0);
            }
          }
        }
      }

      // Emit skip events when tasks are cascade-skipped due to dependency failures
      this.taskQueue.setOnCascadeSkip((skippedTaskId, reason) => {
        this.emit({ type: 'swarm.task.skipped', taskId: skippedTaskId, reason });
      });

      const stats = this.taskQueue.getStats();
      this.emit({ type: 'swarm.phase.progress', phase: 'scheduling', message: `Scheduled ${stats.total} tasks in ${this.taskQueue.getTotalWaves()} waves` });

      // V2: Phase 2.5: Plan execution — fire in background, don't block waves
      let planPromise: Promise<void> | undefined;
      if (this.config.enablePlanning) {
        this.currentPhase = 'planning';
        this.emit({ type: 'swarm.phase.progress', phase: 'planning', message: 'Creating acceptance criteria...' });
        planPromise = this.planExecution(task, decomposition).catch(err => {
          this.logDecision('planning', 'Planning failed (non-fatal)', (err as Error).message);
        });
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

      // Phase 3: Execute waves (planning runs concurrently)
      this.currentPhase = 'executing';
      await this.executeWaves();

      // V10: Final rescue pass — attempt to recover cascade-skipped tasks with lenient mode
      if (!this.cancelled) await this.finalRescuePass();

      // Ensure planning completed before verification/synthesis
      if (planPromise) await planPromise;

      // Post-wave artifact audit: scan filesystem for files created by workers
      this.artifactInventory = this.buildArtifactInventory();

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

      const hasArtifacts = (this.artifactInventory?.totalFiles ?? 0) > 0;
      this.emit({ type: 'swarm.complete', stats: executionStats, errors: this.errors, artifactInventory: this.artifactInventory });

      return {
        success: executionStats.completedTasks > 0,
        partialSuccess: !executionStats.completedTasks && hasArtifacts,
        partialFailure: executionStats.failedTasks > 0,
        synthesisResult: synthesisResult ?? undefined,
        artifactInventory: this.artifactInventory,
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
  private async decompose(task: string): Promise<{ result: SmartDecompositionResult; failureReason?: undefined } | { result: null; failureReason: string }> {
    try {
      const result = await this._decomposer.decompose(task);

      if (result.subtasks.length < 2) {
        const reason = result.subtasks.length === 0
          ? `LLM decomposition produced 0 subtasks (model: ${this.config.orchestratorModel}). Check errors above for response details.`
          : `Decomposition produced only ${result.subtasks.length} subtask — too few for swarm mode.`;
        this.logDecision('decomposition', `Insufficient subtasks: ${result.subtasks.length}`, reason);
        return { result: null, failureReason: reason };
      }

      // Reject heuristic fallback — the generic 3-task chain is worse than aborting
      if (!result.metadata.llmAssisted) {
        const reason = `LLM decomposition failed (model: ${this.config.orchestratorModel}), and heuristic fallback DAG was rejected as not useful.`;
        this.logDecision('decomposition',
          'Rejected heuristic fallback DAG', reason);
        return { result: null, failureReason: reason };
      }

      // Flat-DAG detection: warn when all tasks land in wave 0 with no dependencies
      const hasAnyDependency = result.subtasks.some(s => s.dependencies.length > 0);
      if (!hasAnyDependency && result.subtasks.length >= 3) {
        this.logDecision('decomposition',
          `Flat DAG: ${result.subtasks.length} tasks, zero dependencies`,
          'All tasks will execute in wave 0 without ordering');
      }

      return { result };
    } catch (error) {
      const message = (error as Error).message;
      this.errors.push({
        phase: 'decomposition',
        message,
        recovered: false,
      });
      this.emit({ type: 'swarm.error', error: message, phase: 'decomposition' });
      return { result: null, failureReason: `Decomposition threw an error: ${message}` };
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

      this.trackOrchestratorUsage(response as any, 'plan');

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

      this.trackOrchestratorUsage(response as any, 'review');

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
          // V5: Re-emit full task list so dashboard picks up fixup tasks + edges
          this.emit({
            type: 'swarm.tasks.loaded',
            tasks: this.taskQueue.getAllTasks(),
          });
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

        this.trackOrchestratorUsage(response as any, 'verification-fixup');

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
          // V5: Re-emit full task list so dashboard picks up verification fixup tasks
          this.emit({
            type: 'swarm.tasks.loaded',
            tasks: this.taskQueue.getAllTasks(),
          });

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
    if (checkpoint.originalPrompt) this.originalPrompt = checkpoint.originalPrompt;
    if (checkpoint.plan) this.plan = checkpoint.plan;
    if (checkpoint.modelHealth.length > 0) this.healthTracker.restore(checkpoint.modelHealth);
    this.orchestratorDecisions = checkpoint.decisions ?? [];
    this.errors = checkpoint.errors ?? [];
    this.totalTokens = checkpoint.stats.totalTokens;
    this.totalCost = checkpoint.stats.totalCost;
    this.qualityRejections = checkpoint.stats.qualityRejections;
    this.retries = checkpoint.stats.retries;

    // Restore shared context & economics state from checkpoint
    if (checkpoint.sharedContext) {
      this.sharedContextState.restoreFrom(checkpoint.sharedContext as Parameters<typeof this.sharedContextState.restoreFrom>[0]);
    }
    if (checkpoint.sharedEconomics) {
      this.sharedEconomicsState.restoreFrom(checkpoint.sharedEconomics);
    }

    // Restore task queue
    this.taskQueue.restoreFromCheckpoint({
      taskStates: checkpoint.taskStates,
      waves: checkpoint.waves,
      currentWave: checkpoint.currentWave,
    });

    // Reset orphaned dispatched tasks — their workers died with the previous process
    let resetCount = 0;
    for (const task of this.taskQueue.getAllTasks()) {
      if (task.status === 'dispatched') {
        task.status = 'ready';
        // Preserve at least 1 retry attempt
        task.attempts = Math.min(task.attempts, Math.max(0, this.config.workerRetries - 1));
        resetCount++;
      }
    }
    if (resetCount > 0) {
      this.logDecision('resume', `Reset ${resetCount} orphaned dispatched tasks to ready`, 'Workers died with previous process');
    }

    // Reset skipped tasks whose dependencies are now satisfied
    let unskippedCount = 0;
    for (const task of this.taskQueue.getAllTasks()) {
      if (task.status === 'skipped') {
        const deps = task.dependencies.map(id => this.taskQueue.getTask(id));
        const allDepsSatisfied = deps.every(d =>
          d && (d.status === 'completed' || d.status === 'decomposed'),
        );
        if (allDepsSatisfied) {
          task.status = 'ready';
          task.attempts = 0;
          task.rescueContext = 'Recovered on resume — dependencies now satisfied';
          unskippedCount++;
        }
      }
    }
    // Also reset failed tasks that have retry budget
    for (const task of this.taskQueue.getAllTasks()) {
      if (task.status === 'failed') {
        task.status = 'ready';
        task.attempts = Math.min(task.attempts, Math.max(0, this.config.workerRetries - 1));
        unskippedCount++;
      }
    }
    if (unskippedCount > 0) {
      this.logDecision('resume', `Recovered ${unskippedCount} skipped/failed tasks`, 'Fresh retry on resume');
    }

    // If many tasks are still stuck after un-skip, trigger re-plan
    const resumeStats = this.taskQueue.getStats();
    const stuckCount = resumeStats.failed + resumeStats.skipped;
    const totalAttempted = resumeStats.completed + stuckCount;
    if (totalAttempted > 0 && stuckCount / totalAttempted > 0.4) {
      this.logDecision('resume-replan',
        `${stuckCount}/${totalAttempted} tasks still stuck after resume — triggering re-plan`, '');
      this.hasReplanned = false; // Allow re-plan on resume
      await this.midSwarmReplan();
    }

    // Continue from where we left off
    this.currentPhase = 'executing';
    await this.executeWaves();

    // V10: Final rescue pass — attempt to recover cascade-skipped tasks with lenient mode
    if (!this.cancelled) await this.finalRescuePass();

    // Post-wave artifact audit
    this.artifactInventory = this.buildArtifactInventory();

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

    const hasArtifacts = (this.artifactInventory?.totalFiles ?? 0) > 0;
    this.emit({ type: 'swarm.complete', stats: executionStats, errors: this.errors, artifactInventory: this.artifactInventory });

    return {
      success: executionStats.completedTasks > 0,
      partialSuccess: !executionStats.completedTasks && hasArtifacts,
      partialFailure: executionStats.failedTasks > 0,
      synthesisResult: synthesisResult ?? undefined,
      artifactInventory: this.artifactInventory,
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

      // F18: Skip empty waves — if no tasks are ready and none are running,
      // remaining tasks are all blocked/failed/skipped. Break instead of
      // running useless review cycles.
      if (readyTasks.length === 0 && queueStats.running === 0 && queueStats.ready === 0) {
        this.logDecision('wave-skip',
          `Skipping waves ${waveIndex + 1}-${totalWaves}: no dispatchable tasks remain`,
          `Stats: ${queueStats.completed} completed, ${queueStats.failed} failed, ${queueStats.skipped} skipped`);
        break;
      }

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

      // Wave failure recovery: if ALL tasks in a wave failed, retry with adapted context
      if (waveCompleted === 0 && waveFailed > 0 && readyTasks.length > 0) {
        this.emit({ type: 'swarm.wave.allFailed', wave: waveIndex + 1 });
        this.logDecision('wave-recovery',
          `Entire wave ${waveIndex + 1} failed (${waveFailed} tasks)`,
          'Checking if budget allows retry with adapted strategy');

        // Re-queue failed tasks with retry context if budget allows
        const budgetRemaining = this.budgetPool.hasCapacity();
        const failedWaveTasks = readyTasks.filter(t => {
          const task = this.taskQueue.getTask(t.id);
          return task && task.status === 'failed' && task.attempts < (this.config.workerRetries + 1);
        });

        if (budgetRemaining && failedWaveTasks.length > 0) {
          for (const t of failedWaveTasks) {
            const task = this.taskQueue.getTask(t.id);
            if (!task) continue;
            task.status = 'ready';
            task.retryContext = {
              previousFeedback: 'All tasks in this batch failed. Try a fundamentally different approach — the previous strategy did not work.',
              previousScore: 0,
              attempt: task.attempts,
              previousModel: task.assignedModel,
              swarmProgress: this.getSwarmProgressSummary(),
            };
          }
          this.logDecision('wave-recovery',
            `Re-queued ${failedWaveTasks.length} tasks with adapted retry context`,
            'Budget allows retry');
          // Re-execute the wave with adapted tasks
          await this.executeWave(failedWaveTasks.map(t => this.taskQueue.getTask(t.id)!).filter(t => t.status === 'ready'));
        }
      }

      // F5: Adaptive re-decomposition — if < 50% of wave tasks succeeded,
      // the decomposition may be structurally flawed. Log for observability.
      // (Full re-decomposition of remaining work would require re-architecting the queue,
      // so we log the signal and let wave retry + fixup handle recovery.)
      const waveTotal = waveCompleted + waveFailed + waveSkipped;
      const waveSuccessRate = waveTotal > 0 ? waveCompleted / waveTotal : 0;
      if (waveSuccessRate < 0.5 && waveTotal >= 2) {
        this.logDecision('decomposition-quality',
          `Wave ${waveIndex + 1} success rate ${(waveSuccessRate * 100).toFixed(0)}% (${waveCompleted}/${waveTotal})`,
          'Low success rate may indicate decomposition quality issues');
      }

      // V2: Review wave outputs
      const review = await this.reviewWave(waveIndex);
      if (review && review.fixupTasks.length > 0) {
        // Execute fix-up tasks immediately
        await this.executeWave(review.fixupTasks);
      }

      // Rescue cascade-skipped tasks that can still run
      // (after wave review + fixup, some skipped tasks may now be viable)
      const rescued = this.rescueCascadeSkipped();
      if (rescued.length > 0) {
        this.logDecision('cascade-rescue',
          `Rescued ${rescued.length} cascade-skipped tasks after wave ${waveIndex + 1}`,
          rescued.map(t => t.id).join(', '));
        await this.executeWave(rescued);
      }

      // Reset quality circuit breaker at wave boundary — each wave gets a fresh chance.
      // Within a wave, rejections accumulate properly so the breaker can trip.
      // Between waves, we reset so each wave gets a fresh quality evaluation window.
      // (The within-wave reset at quality-gate-passed is kept — that's correct.)
      if (this.qualityGateDisabledModels.size > 0) {
        this.qualityGateDisabledModels.clear();
        this.perModelQualityRejections.clear();
        this.logDecision('quality-circuit-breaker',
          `Re-enabled quality gates for all models at wave ${waveIndex + 1} boundary`,
          'Each wave gets a fresh quality evaluation window');
      }

      // F3: Log budget reallocation after wave completion.
      // SharedBudgetPool already returns unused tokens via release(), but we log it
      // for observability so operators can see how budget flows between waves.
      const budgetStats = this.budgetPool.getStats();
      this.logDecision('budget-reallocation',
        `After wave ${waveIndex + 1}: ${budgetStats.tokensRemaining} tokens remaining (${(budgetStats.utilization * 100).toFixed(0)}% utilized)`,
        '');
      this.budgetPool.reallocateUnused(budgetStats.tokensRemaining);

      // F21: Mid-swarm situational assessment — evaluate success rate and budget health,
      // optionally triage low-priority tasks to conserve budget for critical path.
      await this.assessAndAdapt(waveIndex);

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
        await new Promise(resolve => setTimeout(resolve, this.getStaggerMs()));
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
            await new Promise(resolve => setTimeout(resolve, this.getStaggerMs()));
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
            await new Promise(resolve => setTimeout(resolve, this.getStaggerMs()));
          }
        }
      }
    }

    // F20: Re-dispatch pass — after all workers finish, budget may have been freed
    // by completed tasks. Try to dispatch any still-ready tasks (e.g., those paused
    // by budget exhaustion earlier).
    if (!this.cancelled && this.budgetPool.hasCapacity()) {
      const stillReady = this.taskQueue.getAllReadyTasks()
        .filter(t => !this.workerPool.getActiveWorkerStatus().some(w => w.taskId === t.id));

      if (stillReady.length > 0) {
        this.logDecision('budget-redispatch',
          `Budget freed after wave — re-dispatching ${stillReady.length} ready task(s)`,
          `Budget: ${JSON.stringify(this.budgetPool.getStats())}`);

        for (const task of stillReady) {
          if (this.workerPool.availableSlots <= 0 || !this.budgetPool.hasCapacity()) break;
          await this.dispatchTask(task);
          if (this.workerPool.availableSlots > 0) {
            await new Promise(resolve => setTimeout(resolve, this.getStaggerMs()));
          }
        }

        // Wait for these re-dispatched tasks to complete
        while (this.workerPool.activeCount > 0 && !this.cancelled) {
          const completed = await this.workerPool.waitForAny();
          if (!completed) break;
          await this.handleTaskCompletion(completed.taskId, completed.result, completed.startedAt);
          this.emitBudgetUpdate();
          this.emitStatusUpdate();
        }
      }
    }
  }

  /**
   * Dispatch a single task to a worker.
   * Selects the worker once and passes it through to avoid double-selection.
   */
  private async dispatchTask(task: SwarmTask): Promise<void> {
    const worker = this.workerPool.selectWorker(task);
    if (!worker) {
      // M2: Emit error and mark task failed instead of silently returning
      // V10: Try resilience recovery if task had previous attempts (prior worker may have produced artifacts)
      this.logDecision('no-worker', `${task.id}: no worker for type ${task.type}`, '');
      if (task.attempts > 0) {
        const syntheticTaskResult: SwarmTaskResult = { success: false, output: '', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'none' };
        const syntheticSpawn: SpawnResult = { success: false, output: '', metrics: { tokens: 0, duration: 0, toolCalls: 0 } };
        if (await this.tryResilienceRecovery(task, task.id, syntheticTaskResult, syntheticSpawn)) {
          return;
        }
      }
      this.taskQueue.markFailedWithoutCascade(task.id, 0);
      this.taskQueue.triggerCascadeSkip(task.id);
      this.emit({
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
      if (this.shouldAutoSplit(task)) {
        try {
          const splitResult = await this.judgeSplit(task);
          if (splitResult.shouldSplit && splitResult.subtasks) {
            task.status = 'dispatched'; // Required for replaceWithSubtasks
            this.taskQueue.replaceWithSubtasks(task.id, splitResult.subtasks);
            this.emit({
              type: 'swarm.task.resilience',
              taskId: task.id,
              strategy: 'auto-split',
              succeeded: true,
              reason: `Pre-dispatch split into ${splitResult.subtasks.length} parallel subtasks`,
              artifactsFound: 0,
              toolCalls: 0,
            });
            return; // Subtasks now in queue, will be dispatched this wave
          }
        } catch (err) {
          this.logDecision('auto-split', `${task.id}: split judge failed — ${(err as Error).message}`, '');
          // Fall through to normal dispatch
        }
      }

      this.totalDispatches++;
      const dispatchedModel = task.assignedModel ?? worker.model;
      this.taskQueue.markDispatched(task.id, dispatchedModel);
      if (task.assignedModel && task.assignedModel !== worker.model) {
        this.logDecision(
          'failover',
          `Dispatching ${task.id} with failover model ${task.assignedModel} (worker default: ${worker.model})`,
          'Retry model override is active',
        );
      }
      // Pass the pre-selected worker to avoid double-selection in dispatch()
      await this.workerPool.dispatch(task, worker);

      this.emit({
        type: 'swarm.task.dispatched',
        taskId: task.id,
        description: task.description,
        model: dispatchedModel,
        workerName: worker.name,
        toolCount: worker.allowedTools?.length ?? -1,  // -1 = all tools
        tools: worker.allowedTools,
        retryContext: task.retryContext,
        fromModel: task.retryContext ? task.retryContext.previousModel : undefined,
        attempts: task.attempts,
      });
    } catch (error) {
      const errorMsg = (error as Error).message;

      // F20: Budget exhaustion is NOT a task failure — the task is fine, we just ran out of money.
      // Reset status to ready so it can be picked up if budget becomes available
      // (e.g., after tokens are released from completing tasks).
      if (errorMsg.includes('Budget pool exhausted')) {
        task.status = 'ready';
        this.logDecision('budget-pause',
          `Cannot dispatch ${task.id}: budget exhausted — task kept ready for potential re-dispatch`,
          `Budget stats: ${JSON.stringify(this.budgetPool.getStats())}`);
        return;
      }

      this.errors.push({
        taskId: task.id,
        phase: 'dispatch',
        message: errorMsg,
        recovered: false,
      });
      this.logDecision('dispatch-error', `${task.id}: dispatch failed: ${errorMsg.slice(0, 100)}`, `attempts: ${task.attempts}`);

      // V10: Try resilience recovery if task had previous attempts (prior worker may have produced artifacts)
      if (task.attempts > 0) {
        const syntheticTaskResult: SwarmTaskResult = { success: false, output: '', tokensUsed: 0, costUsed: 0, durationMs: 0, model: 'none' };
        const syntheticSpawn: SpawnResult = { success: false, output: '', metrics: { tokens: 0, duration: 0, toolCalls: 0 } };
        if (await this.tryResilienceRecovery(task, task.id, syntheticTaskResult, syntheticSpawn)) {
          this.errors[this.errors.length - 1].recovered = true;
          return;
        }
      }

      this.taskQueue.markFailedWithoutCascade(task.id, 0);
      this.taskQueue.triggerCascadeSkip(task.id);
      this.emit({
        type: 'swarm.task.failed',
        taskId: task.id,
        error: errorMsg,
        attempt: task.attempts,
        maxAttempts: 1 + this.config.workerRetries,
        willRetry: false,
        failureMode: 'error',
      });
    }
  }

  /**
   * Handle a completed task: quality gate, bookkeeping, retry logic, model health, failover.
   */
  private async handleTaskCompletion(taskId: string, spawnResult: SpawnResult, startedAt: number): Promise<void> {
    const task = this.taskQueue.getTask(taskId);
    if (!task) return;

    // Guard: task was terminally resolved while its worker was running — ignore the result
    // F4: But NOT if pendingCascadeSkip — those results are evaluated below
    if ((task.status === 'skipped' || task.status === 'failed') && !task.pendingCascadeSkip) return;

    // V7: Global dispatch cap — prevent any single task from burning budget.
    // Try resilience recovery (micro-decompose, degraded acceptance) before hard-failing.
    const maxDispatches = this.config.maxDispatchesPerTask ?? 5;
    if (task.attempts >= maxDispatches) {
      const durationMs = Date.now() - startedAt;
      const taskResult = this.workerPool.toTaskResult(spawnResult, task, durationMs);
      this.totalTokens += taskResult.tokensUsed;
      this.totalCost += taskResult.costUsed;

      // Try resilience recovery before hard fail
      if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
        return;
      }

      this.taskQueue.markFailedWithoutCascade(taskId, 0);
      this.taskQueue.triggerCascadeSkip(taskId);
      this.emit({
        type: 'swarm.task.failed',
        taskId,
        error: `Dispatch cap reached (${maxDispatches} attempts)`,
        attempt: task.attempts,
        maxAttempts: maxDispatches,
        willRetry: false,
        failureMode: task.failureMode,
      });
      this.logDecision('dispatch-cap', `${taskId}: hard cap reached (${task.attempts}/${maxDispatches})`, 'No more retries — resilience recovery also failed');
      return;
    }

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

    // Log per-worker budget utilization for orchestrator visibility
    if (taskResult.budgetUtilization) {
      this.logDecision('budget-utilization', `${taskId}: token ${taskResult.budgetUtilization.tokenPercent}%, iter ${taskResult.budgetUtilization.iterationPercent}%`, `model=${model}, tokens=${taskResult.tokensUsed}, duration=${durationMs}ms`);
    }

    // V10: Emit per-attempt event for full decision traceability
    this.emit({
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
      // V2: Record model health
      const errorMsg = spawnResult.output.toLowerCase();
      const is429 = errorMsg.includes('429') || errorMsg.includes('rate');
      const is402 = errorMsg.includes('402') || errorMsg.includes('spend limit');
      const isTimeout = spawnResult.metrics.toolCalls === -1;
      // F25: Use 'timeout' errorType for timeouts (was 'error')
      const errorType = is429 ? '429' : is402 ? '402' : isTimeout ? 'timeout' : 'error';
      this.healthTracker.recordFailure(model, errorType as '429' | '402' | 'timeout' | 'error');
      this.emit({ type: 'swarm.model.health', record: { model, ...this.getModelHealthSummary(model) } });

      // P6: Tag failure mode for cascade threshold awareness
      task.failureMode = (is429 || is402) ? 'rate-limit' : (spawnResult.metrics.toolCalls === -1 ? 'timeout' : 'error');

      // Feed circuit breaker
      if (is429 || is402) {
        this.recordRateLimit();
      }

      // F25a: Consecutive timeout tracking — early-fail after N consecutive timeouts
      if (isTimeout) {
        const count = (this.taskTimeoutCounts.get(taskId) ?? 0) + 1;
        this.taskTimeoutCounts.set(taskId, count);
        const timeoutLimit = this.config.consecutiveTimeoutLimit ?? 3;
        this.logDecision('timeout-tracking', `${taskId}: consecutive timeout ${count}/${timeoutLimit}`, '');

        if (count >= timeoutLimit) {
          // F25b: Try model failover before giving up
          let failoverSucceeded = false;
          if (this.config.enableModelFailover) {
            const capability: WorkerCapability = getTaskTypeConfig(task.type, this.config).capability ?? 'code';
            const alternative = selectAlternativeModel(this.config.workers, model, capability, this.healthTracker);
            if (alternative) {
              this.emit({
                type: 'swarm.model.failover',
                taskId,
                fromModel: model,
                toModel: alternative.model,
                reason: 'consecutive-timeouts',
              });
              task.assignedModel = alternative.model;
              this.taskTimeoutCounts.set(taskId, 0); // Reset counter for new model
              this.logDecision('failover', `Timeout failover ${taskId}: ${model} → ${alternative.model}`, `${count} consecutive timeouts`);
              failoverSucceeded = true;
            }
          }

          if (!failoverSucceeded) {
            // No alternative model — try resilience recovery before hard fail.
            // Timeouts often produce artifacts (worker WAS working, just ran out of time).
            task.failureMode = 'timeout';
            const taskResult = this.workerPool.toTaskResult(spawnResult, task, Date.now() - startedAt);
            if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
              this.taskTimeoutCounts.delete(taskId);
              return;
            }

            this.taskQueue.markFailedWithoutCascade(taskId, 0);
            this.taskQueue.triggerCascadeSkip(taskId);
            this.emit({
              type: 'swarm.task.failed',
              taskId,
              error: `${count} consecutive timeouts — no alternative model available`,
              attempt: task.attempts,
              maxAttempts: maxDispatches,
              willRetry: false,
              failureMode: 'timeout',
            });
            this.logDecision('timeout-early-fail', `${taskId}: ${count} consecutive timeouts, no alt model — resilience recovery also failed`, '');
            this.taskTimeoutCounts.delete(taskId);
            return;
          }
        }
      } else {
        // Non-timeout failure — reset the counter
        this.taskTimeoutCounts.delete(taskId);
      }

      // V2: Model failover on rate limits
      if ((is429 || is402) && this.config.enableModelFailover) {
        const capability: WorkerCapability = getTaskTypeConfig(task.type, this.config).capability ?? 'code';
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

      // V5/V7: Store error context so retry gets different prompt
      if (!(is429 || is402)) {
        // V7: Timeout-specific feedback — the worker WAS working, just ran out of time
        const timeoutSeconds = isTimeout ? Math.round(durationMs / 1000) : 0;
        task.retryContext = {
          previousFeedback: isTimeout
            ? `Previous attempt timed out after ${timeoutSeconds}s. You must complete this task more efficiently — work faster, use fewer tool calls, and produce your result sooner.`
            : spawnResult.output.slice(0, 2000),
          previousScore: 0,
          attempt: task.attempts,
          previousModel: model,
          previousFiles: taskResult.filesModified,
          swarmProgress: this.getSwarmProgressSummary(),
        };
        // Phase 3.1: Report failure to shared context engine for cross-worker learning
        this.sharedContextEngine.reportFailure(taskId, {
          action: task.description.slice(0, 200),
          error: spawnResult.output.slice(0, 500),
        });
      }

      // V7: Reset hollow streak on non-hollow failure (error is not a hollow completion)
      this.hollowStreak = 0;

      // Worker failed — use higher retry limit for rate limit errors.
      // V7: Fixup tasks get capped retries, foundation tasks get +1.
      const baseRetries = this.getEffectiveRetries(task);
      const retryLimit = (is429 || is402)
        ? Math.min(this.config.rateLimitRetries ?? 3, baseRetries + 1)
        : baseRetries;
      const canRetry = this.taskQueue.markFailedWithoutCascade(taskId, retryLimit);
      if (canRetry) {
        this.retries++;

        // Non-blocking cooldown: set retryAfter timestamp instead of blocking
        if (is429 || is402) {
          const baseDelay = this.config.retryBaseDelayMs ?? 5000;
          const cooldownMs = Math.min(baseDelay * Math.pow(2, task.attempts - 1), 30000);
          this.taskQueue.setRetryAfter(taskId, cooldownMs);
          this.logDecision('rate-limit-cooldown', `${taskId}: ${errorType} cooldown ${cooldownMs}ms, model ${model}`, '');
        }
      } else if (!(is429 || is402)) {
        // Resilience recovery for non-rate-limit errors (micro-decompose + degraded acceptance)
        if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
          return;
        }
        // Recovery failed — NOW trigger cascade
        this.taskQueue.triggerCascadeSkip(taskId);
      } else {
        // Rate-limit exhaustion — trigger cascade
        this.taskQueue.triggerCascadeSkip(taskId);
      }

      this.emit({
        type: 'swarm.task.failed',
        taskId,
        error: spawnResult.output.slice(0, 200),
        attempt: task.attempts,
        maxAttempts: 1 + this.config.workerRetries,
        willRetry: canRetry,
        toolCalls: spawnResult.metrics.toolCalls,
        failoverModel: task.assignedModel !== model ? task.assignedModel : undefined,
        failureMode: task.failureMode,
      });
      return;
    }

    // V6: Hollow completion detection — workers that "succeed" without doing any work
    // Must check BEFORE recording success, otherwise hollow completions inflate health scores
    if (isHollowCompletion(spawnResult, task.type, this.config)) {
      // F4: Hollow result + pendingCascadeSkip — honor the skip immediately, no retry
      if (task.pendingCascadeSkip) {
        task.pendingCascadeSkip = undefined;
        task.status = 'skipped';
        this.totalHollows++;
        this.logDecision('cascade-skip', `${taskId}: pending cascade skip honored (hollow completion)`, '');
        this.emit({ type: 'swarm.task.skipped', taskId, reason: 'cascade skip honored — hollow completion' });
        return;
      }
      // P6: Tag failure mode for cascade threshold awareness
      task.failureMode = 'hollow';
      // Record hollow completion so hollow-prone models accumulate hollow-specific records
      // and get deprioritized by the model selector (also records generic failure internally)
      this.healthTracker.recordHollow(model);

      const admitsFailure = spawnResult.success && FAILURE_INDICATORS.some(f => (spawnResult.output ?? '').toLowerCase().includes(f));
      task.retryContext = {
        previousFeedback: admitsFailure
          ? 'Previous attempt reported success but admitted failure (e.g., "budget exhausted", "unable to complete"). You MUST execute tool calls and produce concrete output this time.'
          : 'Previous attempt produced no meaningful output. Try again with a concrete approach.',
        previousScore: 1,
        attempt: task.attempts,
        previousModel: model,
        previousFiles: taskResult.filesModified,
        swarmProgress: this.getSwarmProgressSummary(),
      };
      // Phase 3.1: Report hollow completion to shared context engine
      this.sharedContextEngine.reportFailure(taskId, {
        action: task.description.slice(0, 200),
        error: 'Hollow completion: worker produced no meaningful output',
      });

      // Model failover for hollow completions — same pattern as quality failover
      if (this.config.enableModelFailover) {
        const capability: WorkerCapability = getTaskTypeConfig(task.type, this.config).capability ?? 'code';
        const alternative = selectAlternativeModel(this.config.workers, model, capability, this.healthTracker);
        if (alternative) {
          this.emit({
            type: 'swarm.model.failover',
            taskId,
            fromModel: model,
            toModel: alternative.model,
            reason: 'hollow-completion',
          });
          task.assignedModel = alternative.model;
          this.logDecision('failover', `Hollow failover ${taskId}: ${model} → ${alternative.model}`, 'Model produced hollow completion');
        }
      }

      const hollowRetries = this.getEffectiveRetries(task);
      const canRetry = this.taskQueue.markFailedWithoutCascade(taskId, hollowRetries);
      if (canRetry) {
        this.retries++;
      } else {
        // Retries exhausted — try shared resilience recovery (micro-decompose, degraded acceptance)
        if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
          return;
        }
        // Recovery failed — NOW trigger cascade
        this.taskQueue.triggerCascadeSkip(taskId);
      }
      this.emit({
        type: 'swarm.task.failed',
        taskId,
        error: 'Hollow completion: worker used no tools',
        attempt: task.attempts,
        maxAttempts: 1 + this.config.workerRetries,
        willRetry: canRetry,
        toolCalls: spawnResult.metrics.toolCalls,
        failoverModel: task.assignedModel !== model ? task.assignedModel : undefined,
        failureMode: 'hollow',
      });
      this.hollowStreak++;
      this.totalHollows++;
      this.logDecision('hollow-completion', `${taskId}: worker completed with 0 tool calls (streak: ${this.hollowStreak}, total hollows: ${this.totalHollows}/${this.totalDispatches})`, canRetry ? 'Marking as failed for retry' : 'Retries exhausted — hard fail');

      // B2: Hollow streak handling — only terminate if enableHollowTermination is explicitly on
      if (this.hollowStreak >= SwarmOrchestrator.HOLLOW_STREAK_THRESHOLD) {
        const uniqueModels = new Set(this.config.workers.map(w => w.model));
        const singleModel = uniqueModels.size === 1;
        const onlyModel = [...uniqueModels][0];
        const modelUnhealthy = singleModel && !this.healthTracker.getAllRecords().find(r => r.model === onlyModel)?.healthy;

        if (singleModel && modelUnhealthy) {
          if (this.config.enableHollowTermination) {
            this.logDecision('early-termination',
              `Terminating swarm: ${this.hollowStreak} consecutive hollow completions on sole model ${onlyModel}`,
              'Single-model swarm with unhealthy model — enableHollowTermination is on');
            this.skipRemainingTasks(`Single-model hollow streak (${this.hollowStreak}x on ${onlyModel})`);
          } else {
            this.logDecision('stall-mode',
              `${this.hollowStreak} consecutive hollows on sole model ${onlyModel} — entering stall mode`,
              'Will attempt model failover or simplified retry on next dispatch');
            // Reset streak to allow more attempts with adjusted strategy
            this.hollowStreak = 0;
          }
        }
      }

      // V7: Multi-model hollow ratio — warn but don't terminate unless opt-in
      const minDispatches = this.config.hollowTerminationMinDispatches ?? 8;
      const threshold = this.config.hollowTerminationRatio ?? 0.55;
      if (this.totalDispatches >= minDispatches) {
        const ratio = this.totalHollows / this.totalDispatches;
        if (ratio > threshold) {
          if (this.config.enableHollowTermination) {
            this.logDecision('early-termination',
              `Terminating swarm: hollow ratio ${(ratio * 100).toFixed(0)}% (${this.totalHollows}/${this.totalDispatches})`,
              `Exceeds threshold ${(threshold * 100).toFixed(0)}% after ${minDispatches}+ dispatches — enableHollowTermination is on`);
            this.skipRemainingTasks(`Hollow ratio ${(ratio * 100).toFixed(0)}% — models cannot execute tasks`);
          } else if (!this.hollowRatioWarned) {
            this.hollowRatioWarned = true;
            this.logDecision('stall-warning',
              `Hollow ratio ${(ratio * 100).toFixed(0)}% (${this.totalHollows}/${this.totalDispatches})`,
              'High hollow rate but continuing — tasks may still recover via resilience');
          }
        }
      }

      return;
    }

    // F4: Task had pendingCascadeSkip but produced non-hollow results.
    // Run pre-flight checks — if the output is good, accept it instead of skipping.
    if (task.pendingCascadeSkip) {
      const cachedReport = checkArtifacts(task);
      const preFlight = runPreFlightChecks(task, taskResult, this.config, cachedReport);
      if (preFlight && !preFlight.passed) {
        // Output is garbage — honor the cascade skip
        task.pendingCascadeSkip = undefined;
        task.status = 'skipped';
        this.logDecision('cascade-skip', `${taskId}: pending cascade skip honored (pre-flight failed: ${preFlight.feedback})`, '');
        this.emit({ type: 'swarm.task.skipped', taskId, reason: `cascade skip honored — output failed pre-flight: ${preFlight.feedback}` });
        return;
      }
      // Output is good — clear the flag and accept the result
      task.pendingCascadeSkip = undefined;
      task.status = 'dispatched'; // Reset so markCompleted works
      this.logDecision('cascade-skip', `${taskId}: pending cascade skip overridden — worker produced valid output`, '');
    }

    // Record model health on success (only for non-hollow completions)
    this.healthTracker.recordSuccess(model, durationMs);
    this.decreaseStagger(); // P7: Speed up on success

    // Run quality gate if enabled — skip under API pressure, skip if circuit breaker tripped,
    // and let the final attempt through without quality gate (so tasks produce *something*)
    // Foundation tasks get +1 retry to reduce cascade failure risk.
    const effectiveRetries = this.getEffectiveRetries(task);
    const recentRLCount = this.recentRateLimits.filter(t => t > Date.now() - 30_000).length;
    const isLastAttempt = task.attempts >= (effectiveRetries + 1);
    const shouldRunQualityGate = this.config.qualityGates
      && !this.qualityGateDisabledModels.has(model)
      && !isLastAttempt
      && Date.now() >= this.circuitBreakerUntil
      && recentRLCount < 2;

    // C1: Pre-compute artifact report once — shared by quality gate and pre-flight checks
    const cachedArtifactReport = checkArtifacts(task);

    if (shouldRunQualityGate) {
      // V3: Judge role handles quality gates
      const judgeModel = this.config.hierarchy?.judge?.model
        ?? this.config.qualityGateModel ?? this.config.orchestratorModel;
      const judgeConfig: QualityGateConfig = {
        model: judgeModel,
        persona: this.config.hierarchy?.judge?.persona,
      };

      this.emit({ type: 'swarm.role.action', role: 'judge', action: 'quality-gate', model: judgeModel, taskId });

      // Extract file artifacts from worker output for quality gate visibility.
      // When workers create files via write_file/edit_file, the judge needs to see
      // the actual content — not just the worker's text claims about what was created.
      const fileArtifacts = this.extractFileArtifacts(task, taskResult);

      // Foundation tasks get a relaxed quality threshold (threshold - 1, min 2)
      // to reduce the chance of cascade-skipping the entire swarm.
      const baseThreshold = this.config.qualityThreshold ?? 3;
      const qualityThreshold = task.isFoundation ? Math.max(2, baseThreshold - 1) : baseThreshold;

      const quality = await evaluateWorkerOutput(
        this.provider,
        judgeModel,
        task,
        taskResult,
        judgeConfig,
        qualityThreshold,
        (resp, purpose) => this.trackOrchestratorUsage(resp, purpose),
        fileArtifacts,
        this.config,
        cachedArtifactReport,
      );

      taskResult.qualityScore = quality.score;
      taskResult.qualityFeedback = quality.feedback;

      // F11: Foundation tasks that barely pass the relaxed threshold get concrete validation.
      // A 2/5 foundation task with truncated output will cascade-poison all dependents.
      if (quality.passed && task.isFoundation && quality.score <= baseThreshold - 1) {
        const concreteResult = runConcreteChecks(task, taskResult);
        if (!concreteResult.passed) {
          quality.passed = false;
          quality.feedback += ` [F11: foundation task barely passed (${quality.score}/${baseThreshold}) but concrete validation failed: ${concreteResult.issues.join('; ')}]`;
          this.logDecision('foundation-concrete-gate',
            `${taskId}: foundation task scored ${quality.score} (relaxed threshold ${qualityThreshold}) but concrete checks failed — rejecting`,
            concreteResult.issues.join('; '));
        }
      }

      if (!quality.passed) {
        // F7: Gate error fallback — when LLM judge fails, use concrete validation
        // If concrete checks pass, tentatively accept the result instead of rejecting.
        if (quality.gateError && (this.config.enableConcreteValidation !== false)) {
          const concreteResult = runConcreteChecks(task, taskResult);
          if (concreteResult.passed) {
            // Concrete validation passed — tentatively accept despite gate error
            this.logDecision('gate-error-fallback',
              `${taskId}: gate error but concrete checks passed — tentatively accepting`,
              quality.gateErrorMessage ?? 'unknown');
            taskResult.qualityScore = quality.score;
            taskResult.qualityFeedback = `${quality.feedback} [concrete validation passed — tentative accept]`;
            // Fall through to success path (don't return)
          } else {
            // Both gate and concrete failed — reject
            this.logDecision('gate-error-fallback',
              `${taskId}: gate error AND concrete checks failed — rejecting`,
              `Concrete issues: ${concreteResult.issues.join('; ')}`);
            // Fall through to normal rejection below
          }

          // If concrete passed, skip the rejection path
          if (concreteResult.passed) {
            this.perModelQualityRejections.delete(model);
            // Jump to success path below
          } else {
            // Proceed with normal rejection
            this.qualityRejections++;
            task.failureMode = 'quality';
            this.healthTracker.recordQualityRejection(model, quality.score);
            this.emit({ type: 'swarm.model.health', record: { model, ...this.getModelHealthSummary(model) } });
            this.hollowStreak = 0;

            task.retryContext = {
              previousFeedback: `Gate error + concrete validation failed: ${concreteResult.issues.join('; ')}`,
              previousScore: quality.score,
              attempt: task.attempts,
              previousModel: model,
              previousFiles: taskResult.filesModified,
              swarmProgress: this.getSwarmProgressSummary(),
            };

            const canRetry = this.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
            if (canRetry) {
              this.retries++;
            } else {
              // Retries exhausted — try resilience recovery before cascade-skip
              if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
                return;
              }
              // Recovery failed — NOW trigger cascade
              this.taskQueue.triggerCascadeSkip(taskId);
            }

            this.emit({
              type: 'swarm.quality.rejected',
              taskId,
              score: quality.score,
              feedback: quality.feedback,
              artifactCount: fileArtifacts.length,
              outputLength: taskResult.output.length,
              preFlightReject: false,
              filesOnDisk: checkArtifactsEnhanced(task, taskResult).files.filter(f => f.exists && f.sizeBytes > 0).length,
            });
            return;
          }
        } else if (!quality.gateError) {
          // Normal quality rejection (LLM judge rejected, no gate error)
          this.qualityRejections++;
          // P6: Tag failure mode for cascade threshold awareness
          task.failureMode = 'quality';
          // P1: Quality rejections update model health — undo premature recordSuccess
          this.healthTracker.recordQualityRejection(model, quality.score);
          this.emit({ type: 'swarm.model.health', record: { model, ...this.getModelHealthSummary(model) } });
          // V7: Quality rejection is NOT hollow — worker did work, just poorly
          this.hollowStreak = 0;

          // F7: Per-model circuit breaker → "pre-flight only mode" instead of fully disabling gates.
          // After threshold rejections, skip LLM judge but keep pre-flight mandatory.
          if (!quality.preFlightReject) {
            const modelRejections = (this.perModelQualityRejections.get(model) ?? 0) + 1;
            this.perModelQualityRejections.set(model, modelRejections);

            if (modelRejections >= SwarmOrchestrator.QUALITY_CIRCUIT_BREAKER_THRESHOLD) {
              this.qualityGateDisabledModels.add(model);
              this.logDecision('quality-circuit-breaker',
                `Switched model ${model} to pre-flight-only mode after ${modelRejections} rejections`,
                'Skipping LLM judge but keeping pre-flight checks mandatory');
            }
          }

          // V5: Attach feedback so retry prompt includes it
          task.retryContext = {
            previousFeedback: quality.feedback,
            previousScore: quality.score,
            attempt: task.attempts,
            previousModel: model,
            previousFiles: taskResult.filesModified,
            swarmProgress: this.getSwarmProgressSummary(),
          };
          // Phase 3.1: Report quality rejection to shared context engine
          this.sharedContextEngine.reportFailure(taskId, {
            action: task.description.slice(0, 200),
            error: `Quality gate rejection (score ${quality.score}): ${quality.feedback.slice(0, 300)}`,
          });

          // V5: Model failover on quality rejection — but NOT on artifact auto-fails
          // P1: Widened from score<=1 to score<threshold so failover triggers on any rejection
          if (quality.score < qualityThreshold && this.config.enableModelFailover && !quality.artifactAutoFail) {
            const capability: WorkerCapability = getTaskTypeConfig(task.type, this.config).capability ?? 'code';
            const alternative = selectAlternativeModel(this.config.workers, model, capability, this.healthTracker);
            if (alternative) {
              this.emit({
                type: 'swarm.model.failover',
                taskId,
                fromModel: model,
                toModel: alternative.model,
                reason: `quality-score-${quality.score}`,
              });
              task.assignedModel = alternative.model;
              this.logDecision('failover', `Quality failover ${taskId}: ${model} → ${alternative.model}`, `Score ${quality.score}/5`);
            }
          }

          const canRetry = this.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
          if (canRetry) {
            this.retries++;
          } else {
            // Retries exhausted — try resilience recovery before cascade-skip
            if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
              return;
            }
            // Recovery failed — NOW trigger cascade
            this.taskQueue.triggerCascadeSkip(taskId);
          }

          // M1: Only emit quality.rejected (not duplicate task.failed)
          this.emit({
            type: 'swarm.quality.rejected',
            taskId,
            score: quality.score,
            feedback: quality.feedback,
            artifactCount: fileArtifacts.length,
            outputLength: taskResult.output.length,
            preFlightReject: quality.preFlightReject,
            filesOnDisk: checkArtifactsEnhanced(task, taskResult).files.filter(f => f.exists && f.sizeBytes > 0).length,
          });
          return;
        } else {
          // gateError=true but concrete validation disabled — reject
          this.qualityRejections++;
          task.failureMode = 'quality';
          this.hollowStreak = 0;

          task.retryContext = {
            previousFeedback: quality.feedback,
            previousScore: quality.score,
            attempt: task.attempts,
            previousModel: model,
            previousFiles: taskResult.filesModified,
            swarmProgress: this.getSwarmProgressSummary(),
          };

          const canRetry = this.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
          if (canRetry) {
            this.retries++;
          } else {
            // Retries exhausted — try resilience recovery before cascade-skip
            if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
              return;
            }
            // Recovery failed — NOW trigger cascade
            this.taskQueue.triggerCascadeSkip(taskId);
          }

          this.emit({
            type: 'swarm.quality.rejected',
            taskId,
            score: quality.score,
            feedback: quality.feedback,
            artifactCount: fileArtifacts.length,
            outputLength: taskResult.output.length,
            preFlightReject: false,
            filesOnDisk: checkArtifactsEnhanced(task, taskResult).files.filter(f => f.exists && f.sizeBytes > 0).length,
          });
          return;
        }
      }

      // Quality passed — reset per-model rejection counter
      this.perModelQualityRejections.delete(model);
    }

    // F7: When quality gate was skipped (last attempt, pre-flight-only mode, API pressure),
    // still run pre-flight + concrete checks so obviously broken outputs don't slip through.
    // C1: Use cached artifact report to avoid double filesystem scan.
    if (!shouldRunQualityGate && this.config.qualityGates) {
      const preFlight = runPreFlightChecks(task, taskResult, this.config, cachedArtifactReport);
      if (preFlight && !preFlight.passed) {
        taskResult.qualityScore = preFlight.score;
        taskResult.qualityFeedback = preFlight.feedback;
        this.qualityRejections++;
        const canRetry = this.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
        if (canRetry) {
          this.retries++;
        } else {
          // Retries exhausted — try resilience recovery before cascade-skip
          this.logDecision('preflight-reject', `${taskId}: pre-flight failed: ${preFlight.feedback}`, '');
          if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
            return;
          }
          // Recovery failed — NOW trigger cascade
          this.taskQueue.triggerCascadeSkip(taskId);
        }
        this.emit({
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
      if (this.config.enableConcreteValidation !== false) {
        const concreteResult = runConcreteChecks(task, taskResult);
        if (!concreteResult.passed) {
          taskResult.qualityScore = 2;
          taskResult.qualityFeedback = `Concrete validation failed: ${concreteResult.issues.join('; ')}`;
          this.qualityRejections++;
          const canRetry = this.taskQueue.markFailedWithoutCascade(taskId, effectiveRetries);
          if (canRetry) {
            this.retries++;
          } else {
            // Retries exhausted — try resilience recovery before cascade-skip
            this.logDecision('concrete-reject', `${taskId}: concrete validation failed: ${concreteResult.issues.join('; ')}`, '');
            if (await this.tryResilienceRecovery(task, taskId, taskResult, spawnResult)) {
              return;
            }
            // Recovery failed — NOW trigger cascade
            this.taskQueue.triggerCascadeSkip(taskId);
          }
          this.emit({
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

    // Task passed — mark completed
    this.taskQueue.markCompleted(taskId, taskResult);
    this.hollowStreak = 0;
    // F25: Clear timeout counter on success
    this.taskTimeoutCounts.delete(taskId);

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
      qualityFeedback: taskResult.qualityFeedback,
      output: taskResult.output,
      closureReport: taskResult.closureReport,
      toolCalls: spawnResult.metrics.toolCalls,
    });
  }

  /**
   * Phase 4: Synthesize all completed task outputs.
   */
  private async synthesize() {
    const tasks = this.taskQueue.getAllTasks();
    const outputs = tasks
      .filter(t => t.status === 'completed')
      .map(t => taskResultToAgentOutput(t, this.config))
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
        tokensUsed: this.totalTokens + this.orchestratorTokens,
        tokensTotal: this.config.totalBudget,
        costUsed: this.totalCost + this.orchestratorCost,
        costTotal: this.config.maxCost,
      },
      orchestrator: {
        tokens: this.orchestratorTokens,
        cost: this.orchestratorCost,
        calls: this.orchestratorCalls,
        model: this.config.orchestratorModel,
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

  // ─── D3: Model Capability Probing ─────────────────────────────────────

  /**
   * D3/F23: Probe each unique model to verify it can make tool calls.
   * Models that fail the probe are marked unhealthy so they're skipped in dispatch.
   *
   * F23 fix: Uses chatWithTools() with actual tool definitions instead of
   * plain chat() which never included tools in the API request.
   */
  private async probeModelCapability(): Promise<void> {
    const uniqueModels = new Set(this.config.workers.map(w => w.model));
    this.emit({ type: 'swarm.phase.progress', phase: 'scheduling', message: `Probing ${uniqueModels.size} model(s) for tool-calling capability...` });

    // F23: Check if provider supports native tool calling
    const supportsTools = 'chatWithTools' in this.provider
      && typeof (this.provider as LLMProviderWithTools).chatWithTools === 'function';

    if (!supportsTools) {
      // Provider doesn't support chatWithTools — skip probe entirely.
      // Workers will rely on text-based tool parsing fallback.
      this.logDecision('model-probe', 'Provider does not support chatWithTools — skipping probe', '');
      return;
    }

    const providerWithTools = this.provider as LLMProviderWithTools;
    const probeTools: ToolDefinitionSchema[] = [{
      type: 'function',
      function: {
        name: 'read_file',
        description: 'Read a file from disk',
        parameters: {
          type: 'object',
          properties: { path: { type: 'string', description: 'File path' } },
          required: ['path'],
        },
      },
    }];

    // F24: Configurable probe timeout — generous default for slow models/connections
    const probeTimeout = this.config.probeTimeoutMs ?? 60_000;

    for (const model of uniqueModels) {
      try {
        const timeoutPromise = new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error(`Probe timeout (${probeTimeout}ms)`)), probeTimeout),
        );

        const response = await Promise.race([
          providerWithTools.chatWithTools(
            [
              { role: 'system', content: 'You are a test probe. Call the read_file tool with path "package.json".' },
              { role: 'user', content: 'Read package.json.' },
            ],
            { model, maxTokens: 200, temperature: 0, tools: probeTools, tool_choice: 'required' },
          ),
          timeoutPromise,
        ]);

        const hasToolCall = (response.toolCalls?.length ?? 0) > 0;

        if (!hasToolCall) {
          // F19: Directly mark unhealthy — probe failure is definitive evidence
          this.healthTracker.markUnhealthy(model);
          this.logDecision('model-probe', `Model ${model} failed probe (no tool calls)`, 'Marked unhealthy');
        } else {
          this.healthTracker.recordSuccess(model, 0);
          this.logDecision('model-probe', `Model ${model} passed probe`, '');
        }
      } catch {
        // F19: Directly mark unhealthy on probe error (includes timeout)
        this.healthTracker.markUnhealthy(model);
        this.logDecision('model-probe', `Model ${model} probe errored`, 'Marked unhealthy');
      }
    }
  }

  // ─── Circuit Breaker ────────────────────────────────────────────────

  /**
   * Record a rate limit hit and check if the circuit breaker should trip.
   */
  private recordRateLimit(): void {
    const now = Date.now();
    this.recentRateLimits.push(now);
    this.increaseStagger(); // P7: Back off on rate limits

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

  // ─── P7: Adaptive Stagger ────────────────────────────────────────────

  /** P7: Get current stagger delay (adapts based on rate limit / success signals). */
  private getStaggerMs(): number {
    return this.adaptiveStaggerMs;
  }

  /** P7: Increase stagger on rate limit (×1.5, capped at 10s). */
  private increaseStagger(): void {
    this.adaptiveStaggerMs = Math.min(this.adaptiveStaggerMs * 1.5, 10_000);
  }

  /** P7: Decrease stagger on success (×0.9, floor at 200ms). */
  private decreaseStagger(): void {
    this.adaptiveStaggerMs = Math.max(this.adaptiveStaggerMs * 0.9, 200);
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
          totalTokens: this.totalTokens + this.orchestratorTokens,
          totalCost: this.totalCost + this.orchestratorCost,
          qualityRejections: this.qualityRejections,
          retries: this.retries,
        },
        modelHealth: this.healthTracker.getAllRecords(),
        decisions: this.orchestratorDecisions,
        errors: this.errors,
        originalPrompt: this.originalPrompt,
        sharedContext: this.sharedContextState.toJSON(),
        sharedEconomics: this.sharedEconomicsState.toJSON(),
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
      tokensUsed: this.totalTokens + this.orchestratorTokens,
      tokensTotal: this.config.totalBudget,
      costUsed: this.totalCost + this.orchestratorCost,
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
      totalTokens: this.totalTokens + this.orchestratorTokens,
      totalCost: this.totalCost + this.orchestratorCost,
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

    // Artifact inventory: show what files actually exist on disk regardless of task status
    if (this.artifactInventory && this.artifactInventory.totalFiles > 0) {
      parts.push(`  Files on disk: ${this.artifactInventory.totalFiles} files (${(this.artifactInventory.totalBytes / 1024).toFixed(1)}KB)`);
      for (const f of this.artifactInventory.files.slice(0, 15)) {
        parts.push(`    ${f.path}: ${f.sizeBytes}B`);
      }
      if (this.artifactInventory.files.length > 15) {
        parts.push(`    ... and ${this.artifactInventory.files.length - 15} more`);
      }
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

  /**
   * Detect foundation tasks: tasks that are a dependency of 2+ downstream tasks.
   * These are critical single-points-of-failure — mark them for extra resilience.
   */
  private detectFoundationTasks(): void {
    const allTasks = this.taskQueue.getAllTasks();
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
        this.logDecision('scheduling',
          `Foundation task: ${task.id} (${dependentCount} dependents)`,
          'Extra retries and relaxed quality threshold applied');
      }
    }
  }

  /**
   * Extract file artifacts from a worker's output for quality gate visibility.
   * Reads actual file content from disk so the judge can verify real work,
   * not just text claims about what was created.
   */
  private extractFileArtifacts(task: SwarmTask, taskResult: import('./types.js').SwarmTaskResult): Array<{ path: string; preview: string }> {
    const artifacts: Array<{ path: string; preview: string }> = [];
    const seen = new Set<string>();

    // Collect file paths from multiple sources
    const candidatePaths: string[] = [];

    // 1. filesModified from structured closure report
    if (taskResult.filesModified) {
      candidatePaths.push(...taskResult.filesModified);
    }

    // 2. targetFiles from task definition
    if (task.targetFiles) {
      candidatePaths.push(...task.targetFiles);
    }

    // 3. Extract file paths mentioned in worker output (e.g., "Created src/foo.ts")
    const filePathPattern = /(?:created|wrote|modified|edited|updated)\s+["`']?([^\s"`',]+\.\w+)/gi;
    let match;
    while ((match = filePathPattern.exec(taskResult.output)) !== null) {
      candidatePaths.push(match[1]);
    }

    // Resolve against the target project directory, not CWD
    const baseDir = this.config.facts?.workingDirectory ?? process.cwd();

    // Read previews from disk
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

      // Limit to 10 files to keep prompt size reasonable
      if (artifacts.length >= 10) break;
    }

    return artifacts;
  }

  /**
   * Build an inventory of filesystem artifacts produced during swarm execution.
   * Scans all tasks' targetFiles and readFiles to check what actually exists on disk.
   * This reveals work done by workers even when tasks "failed" (timeout, quality gate, etc.).
   */
  private buildArtifactInventory(): ArtifactInventory {
    const allFiles = new Set<string>();
    for (const task of this.taskQueue.getAllTasks()) {
      for (const f of (task.targetFiles ?? [])) allFiles.add(f);
      for (const f of (task.readFiles ?? [])) allFiles.add(f);
    }

    const baseDir = this.config.facts?.workingDirectory ?? process.cwd();
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
  private skipRemainingTasks(reason: string): void {
    for (const task of this.taskQueue.getAllTasks()) {
      if (task.status === 'pending' || task.status === 'ready') {
        task.status = 'skipped';
        this.emit({ type: 'swarm.task.skipped', taskId: task.id, reason });
      }
    }
  }

  /**
   * F21: Mid-swarm situational assessment after each wave.
   * Evaluates success rate and budget health, triages low-priority tasks when budget is tight.
   * Also detects stalled progress and triggers mid-swarm re-planning.
   */
  private async assessAndAdapt(waveIndex: number): Promise<void> {
    const stats = this.taskQueue.getStats();
    const budgetStats = this.budgetPool.getStats();

    // 1. Calculate success rate for this swarm run
    const successRate = stats.completed / Math.max(1, stats.completed + stats.failed + stats.skipped);

    // 2. Budget efficiency: tokens spent per completed task
    const tokensPerTask = stats.completed > 0
      ? (this.totalTokens / stats.completed)
      : Infinity;

    // 3. Remaining budget vs remaining tasks
    const remainingTasks = stats.total - stats.completed - stats.failed - stats.skipped;
    const estimatedTokensNeeded = remainingTasks * tokensPerTask;
    const budgetSufficient = budgetStats.tokensRemaining > estimatedTokensNeeded * 0.5;

    // Log the assessment for observability
    this.logDecision('mid-swarm-assessment',
      `After wave ${waveIndex + 1}: ${stats.completed}/${stats.total} completed (${(successRate * 100).toFixed(0)}%), ` +
      `${remainingTasks} remaining, ${budgetStats.tokensRemaining} tokens left`,
      budgetSufficient ? 'Budget looks sufficient' : 'Budget may be insufficient for remaining tasks');

    // 4. If budget is tight, prioritize: skip low-value remaining tasks
    // Only triage if we have actual data (at least one completion to estimate from)
    if (!budgetSufficient && remainingTasks > 1 && stats.completed > 0) {
      // Prefer pausing over skipping: if workers are still running, wait for budget release
      const runningCount = stats.running ?? 0;
      if (runningCount > 0) {
        this.logDecision('budget-wait',
          'Budget tight but workers still running — waiting for budget release',
          `${runningCount} workers active, ${budgetStats.tokensRemaining} tokens remaining`);
        return;
      }

      const expendableTasks = this.findExpendableTasks();
      // Hard cap: never skip more than 20% of remaining tasks in one triage pass
      const maxSkips = Math.max(1, Math.floor(remainingTasks * 0.2));
      if (expendableTasks.length > 0) {
        let currentEstimate = estimatedTokensNeeded;
        let skipped = 0;
        for (const task of expendableTasks) {
          if (skipped >= maxSkips) break;
          // Stop trimming once we're within budget
          if (currentEstimate * 0.7 <= budgetStats.tokensRemaining) break;
          task.status = 'skipped';
          skipped++;
          this.emit({ type: 'swarm.task.skipped', taskId: task.id,
            reason: 'Budget conservation: skipping low-priority task to protect critical path' });
          this.logDecision('budget-triage',
            `Skipping ${task.id} (${task.type}, complexity ${task.complexity}) to conserve budget`,
            `${remainingTasks} tasks remain, ${budgetStats.tokensRemaining} tokens`);
          currentEstimate -= tokensPerTask;
        }
      }
    }

    // 5. Stall detection: if progress ratio is too low, trigger re-plan
    const attemptedTasks = stats.completed + stats.failed + stats.skipped;
    if (attemptedTasks >= 5) {
      const progressRatio = stats.completed / Math.max(1, attemptedTasks);
      if (progressRatio < 0.4) {
        this.logDecision('stall-detected',
          `Progress stalled: ${stats.completed}/${attemptedTasks} tasks succeeded (${(progressRatio * 100).toFixed(0)}%)`,
          'Triggering mid-swarm re-plan');
        this.emit({
          type: 'swarm.stall',
          progressRatio,
          attempted: attemptedTasks,
          completed: stats.completed,
        });
        await this.midSwarmReplan();
      }
    }
  }

  /**
   * F21: Find expendable tasks — leaf tasks (no dependents) with lowest complexity.
   * These are the safest to skip when budget is tight.
   * Only tasks with complexity <= 2 are considered expendable.
   */
  private findExpendableTasks(): SwarmTask[] {
    const allTasks = this.taskQueue.getAllTasks();

    // Build reverse dependency map: which tasks depend on each task?
    const dependentCounts = new Map<string, number>();
    for (const task of allTasks) {
      for (const depId of task.dependencies) {
        dependentCounts.set(depId, (dependentCounts.get(depId) ?? 0) + 1);
      }
    }

    // Expendable = pending/ready, never attempted, no dependents, not foundation,
    // complexity <= 2 (simple leaf tasks only), lowest complexity first
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
   * Creates simpler replacement tasks for stuck/failed work, building on what's already done.
   * Only triggers once per swarm execution to avoid infinite re-planning loops.
   */
  private async midSwarmReplan(): Promise<void> {
    if (this.hasReplanned) return;
    this.hasReplanned = true;

    const allTasks = this.taskQueue.getAllTasks();
    const completed = allTasks.filter(t => t.status === 'completed' || t.status === 'decomposed');
    const stuck = allTasks.filter(t => t.status === 'failed' || t.status === 'skipped');

    if (stuck.length === 0) return;

    const completedSummary = completed.map(t =>
      `- ${t.description} [${t.type}] → completed${t.degraded ? ' (degraded)' : ''}`,
    ).join('\n') || '(none)';
    const stuckSummary = stuck.map(t =>
      `- ${t.description} [${t.type}] → ${t.status} (${t.failureMode ?? 'unknown'})`,
    ).join('\n');
    const artifactInventory = this.buildArtifactInventory();
    const artifactSummary = artifactInventory.files.map(f => `- ${f.path} (${f.sizeBytes}B)`).join('\n') || '(none)';

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
      const response = await this.provider.chat([{ role: 'user', content: replanPrompt }]);
      this.trackOrchestratorUsage(response as any, 'mid-swarm-replan');

      const content = response.content ?? '';
      const jsonMatch = content.match(/\{[\s\S]*"subtasks"[\s\S]*\}/);
      if (!jsonMatch) {
        this.logDecision('replan-failed', 'LLM produced no parseable re-plan JSON', content.slice(0, 200));
        return;
      }

      const parsed = JSON.parse(jsonMatch[0]) as { subtasks: Array<{ description: string; type: string; complexity: number; dependencies: string[]; relevantFiles?: string[] }> };
      if (!parsed.subtasks || parsed.subtasks.length === 0) {
        this.logDecision('replan-failed', 'LLM produced empty subtask list', '');
        return;
      }

      // Add new tasks from re-plan into current wave
      const newTasks = this.taskQueue.addReplanTasks(parsed.subtasks, this.taskQueue.getCurrentWave());
      this.logDecision('replan-success',
        `Re-planned ${stuck.length} stuck tasks into ${newTasks.length} new tasks`,
        newTasks.map(t => t.description).join('; '));

      this.emit({
        type: 'swarm.replan',
        stuckCount: stuck.length,
        newTaskCount: newTasks.length,
      });

      this.emit({
        type: 'swarm.orchestrator.decision',
        decision: {
          timestamp: Date.now(),
          phase: 'replan',
          decision: `Re-planned ${stuck.length} stuck tasks into ${newTasks.length} new tasks`,
          reasoning: newTasks.map(t => `${t.id}: ${t.description}`).join('; '),
        },
      });
    } catch (error) {
      this.logDecision('replan-failed', `Re-plan LLM call failed: ${(error as Error).message}`, '');
    }
  }

  /**
   * Rescue cascade-skipped tasks that can still run.
   * After cascade-skip fires, assess whether skipped tasks can still be attempted:
   * - If all OTHER dependencies completed and the failed dep's artifacts exist on disk → un-skip
   * - If the task has no strict data dependency on the failed task (different file targets) → un-skip with warning
   */
  private rescueCascadeSkipped(lenient = false): SwarmTask[] {
    const skippedTasks = this.taskQueue.getSkippedTasks();
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
        const dep = this.taskQueue.getTask(depId);
        if (!dep) continue;
        totalDeps++;

        if (dep.status === 'completed' || dep.status === 'decomposed') {
          completedDeps++;
        } else if (dep.status === 'failed' || dep.status === 'skipped') {
          // V10: In lenient mode, use checkArtifactsEnhanced for broader detection
          const artifactReport = lenient ? checkArtifactsEnhanced(dep) : checkArtifacts(dep);
          if (artifactReport && artifactReport.files.filter(f => f.exists && f.sizeBytes > 0).length > 0) {
            failedDepsWithArtifacts++;
            failedDepDescriptions.push(`${dep.description} (failed but ${artifactReport.files.filter(f => f.exists && f.sizeBytes > 0).length} artifacts exist)`);
          } else {
            // Check if this dep's target files exist on disk (may have been created by earlier attempt)
            const targetFiles = dep.targetFiles ?? [];
            const existingFiles = targetFiles.filter(f => {
              try {
                const resolved = path.resolve(this.config.facts?.workingDirectory ?? process.cwd(), f);
                return fs.statSync(resolved).size > 0;
              } catch { return false; }
            });
            if (existingFiles.length > 0) {
              failedDepsWithArtifacts++;
              failedDepDescriptions.push(`${dep.description} (failed but ${existingFiles.length}/${targetFiles.length} target files exist)`);
            } else {
              // Check if skipped task's targets don't overlap with the failed dep's targets
              const taskTargets = new Set(task.targetFiles ?? []);
              const depTargets = new Set(dep.targetFiles ?? []);
              const hasOverlap = [...taskTargets].some(f => depTargets.has(f));
              if (!hasOverlap && taskTargets.size > 0) {
                // Different file targets — task probably doesn't need the failed dep's output
                failedDepsWithArtifacts++;
                failedDepDescriptions.push(`${dep.description} (failed, no file overlap — likely independent)`);
              } else if (lenient && dep.status === 'skipped') {
                // V10: In lenient mode, count skipped-by-skipped deps separately
                // (transitive cascade — the dep itself was a victim, not truly broken)
                skippedDepsBlockedBySkipped++;
                failedDepDescriptions.push(`${dep.description} (skipped — transitive cascade victim)`);
              } else {
                failedDepsWithoutArtifacts++;
              }
            }
          }
        }
      }

      // Rescue condition:
      // Normal: all failed deps have artifacts or are independent, AND at least some deps completed
      // Lenient: tolerate up to 1 truly-missing dep, and count transitive cascade victims as recoverable
      const effectiveWithout = failedDepsWithoutArtifacts;
      const maxMissing = lenient ? 1 : 0;
      const hasEnoughContext = lenient ? (completedDeps + failedDepsWithArtifacts + skippedDepsBlockedBySkipped > 0) : (completedDeps > 0);

      if (totalDeps > 0 && effectiveWithout <= maxMissing && hasEnoughContext) {
        const rescueContext = `Rescued from cascade-skip${lenient ? ' (lenient)' : ''}: ${completedDeps}/${totalDeps} deps completed, ` +
          `${failedDepsWithArtifacts} failed deps have artifacts${skippedDepsBlockedBySkipped > 0 ? `, ${skippedDepsBlockedBySkipped} transitive cascade victims` : ''}. ${failedDepDescriptions.join('; ')}`;
        this.taskQueue.rescueTask(task.id, rescueContext);
        rescued.push(task);
        this.logDecision('cascade-rescue',
          `${task.id}: rescued from cascade-skip${lenient ? ' (lenient)' : ''}`,
          rescueContext);
      }
    }

    return rescued;
  }

  /**
   * Final rescue pass — runs after executeWaves() finishes.
   * Uses lenient mode to rescue cascade-skipped tasks that have partial context.
   * Re-dispatches rescued tasks in a final wave.
   */
  private async finalRescuePass(): Promise<void> {
    const skipped = this.taskQueue.getSkippedTasks();
    if (skipped.length === 0) return;

    this.logDecision('final-rescue', `${skipped.length} skipped tasks — running final rescue pass`, '');
    const rescued = this.rescueCascadeSkipped(true); // lenient=true
    if (rescued.length > 0) {
      this.logDecision('final-rescue', `Rescued ${rescued.length} tasks`, rescued.map(t => t.id).join(', '));
      await this.executeWave(rescued);
    }
  }

  /**
   * Try resilience recovery strategies before hard-failing a task.
   * Called from dispatch-cap, timeout, hollow, and error paths to avoid bypassing resilience.
   *
   * Strategies (in order):
   * 1. Micro-decomposition — break complex failing tasks into subtasks
   * 2. Degraded acceptance — accept partial work if artifacts exist on disk
   *
   * Returns true if recovery succeeded (caller should return), false if hard-fail should proceed.
   */
  private async tryResilienceRecovery(
    task: SwarmTask, taskId: string,
    taskResult: SwarmTaskResult, spawnResult: SpawnResult,
  ): Promise<boolean> {
    // Strategy 1: Micro-decompose complex tasks into smaller subtasks
    // V10: Lowered threshold from >= 6 to >= 4 so moderately complex tasks can be recovered
    if ((task.complexity ?? 0) >= 4 && task.attempts >= 2 && this.budgetPool.hasCapacity()) {
      const subtasks = await this.microDecompose(task);
      if (subtasks && subtasks.length >= 2) {
        // Reset task status so replaceWithSubtasks can mark it as decomposed
        task.status = 'dispatched';
        this.taskQueue.replaceWithSubtasks(taskId, subtasks);
        this.logDecision('micro-decompose',
          `${taskId}: decomposed into ${subtasks.length} subtasks after ${task.attempts} failures`,
          subtasks.map(s => `${s.id}: ${s.description.slice(0, 60)}`).join('; '));
        this.emit({
          type: 'swarm.task.failed',
          taskId,
          error: `Micro-decomposed into ${subtasks.length} subtasks`,
          attempt: task.attempts,
          maxAttempts: this.config.maxDispatchesPerTask ?? 5,
          willRetry: false,
          toolCalls: spawnResult.metrics.toolCalls,
          failureMode: task.failureMode,
        });
        this.emit({
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
      // Micro-decompose was attempted but didn't produce usable subtasks
      if ((task.complexity ?? 0) < 4) {
        this.logDecision('resilience-skip', `${taskId}: skipped micro-decompose — complexity ${task.complexity} < 4`, '');
      }
    }

    // Strategy 2: Degraded acceptance — check if any attempt produced files on disk.
    // V10: Use checkArtifactsEnhanced for broader detection (filesModified, closureReport, output)
    const artifactReport = checkArtifactsEnhanced(task, taskResult);
    const existingArtifacts = artifactReport.files.filter(f => f.exists && f.sizeBytes > 0);
    const hasArtifacts = existingArtifacts.length > 0;
    // V10: Fix timeout detection — toolCalls=-1 means timeout (worker WAS working)
    const toolCalls = spawnResult.metrics.toolCalls ?? 0;
    const hadToolCalls = toolCalls > 0 || toolCalls === -1
      || (taskResult.filesModified && taskResult.filesModified.length > 0);

    if (hasArtifacts || hadToolCalls) {
      // Accept with degraded flag — prevents cascade-skip of dependents
      taskResult.success = true;
      taskResult.degraded = true;
      taskResult.qualityScore = 2; // Capped at low quality
      taskResult.qualityFeedback = 'Degraded acceptance: retries exhausted but filesystem artifacts exist';
      task.degraded = true;
      // Reset status so markCompleted works (markFailed may have set it to 'failed')
      task.status = 'dispatched';
      this.taskQueue.markCompleted(taskId, taskResult);
      this.hollowStreak = 0;
      this.logDecision('degraded-acceptance',
        `${taskId}: accepted as degraded — ${existingArtifacts.length} artifacts on disk, ${toolCalls} tool calls`,
        'Prevents cascade-skip of dependent tasks');
      this.emit({
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
      this.emit({
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

    // Both strategies failed — log exhaustion for traceability
    this.logDecision('resilience-exhausted',
      `${taskId}: no recovery — artifacts: ${existingArtifacts.length}, toolCalls: ${toolCalls}, filesModified: ${taskResult.filesModified?.length ?? 0}`,
      '');
    this.emit({
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

  /**
   * Micro-decompose a complex task into 2-3 smaller subtasks using the LLM.
   * Called when a complex task (complexity >= 6) fails 2+ times with the same failure mode.
   * Returns null if decomposition doesn't make sense or LLM can't produce valid subtasks.
   */
  private async microDecompose(task: SwarmTask): Promise<SwarmTask[] | null> {
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

      const response = await this.provider.chat(
        [
          { role: 'system', content: 'You are a task decomposition assistant. Return only valid JSON.' },
          { role: 'user', content: prompt },
        ],
        {
          model: this.config.orchestratorModel,
          maxTokens: 2000,
          temperature: 0.3,
        },
      );

      this.trackOrchestratorUsage(response as any, 'micro-decompose');

      // Parse response — handle markdown code blocks
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
        dependencies: [],  // Will be set by replaceWithSubtasks
        status: 'ready' as const,
        complexity: Math.min(sub.complexity ?? Math.ceil(task.complexity / 2), task.complexity - 1),
        wave: task.wave,
        targetFiles: sub.targetFiles ?? [],
        readFiles: task.readFiles,
        attempts: 0,
      }));

      return subtasks;
    } catch (error) {
      this.logDecision('micro-decompose',
        `${task.id}: micro-decomposition failed — ${(error as Error).message}`,
        'Falling through to normal failure path');
      return null;
    }
  }

  // ─── Pre-Dispatch Auto-Split ──────────────────────────────────────────────

  /**
   * Heuristic pre-filter: should this task be considered for auto-split?
   * Cheap check — no LLM call. Returns true if all conditions are met.
   */
  private shouldAutoSplit(task: SwarmTask): boolean {
    const cfg = this.config.autoSplit;
    if (cfg?.enabled === false) return false;

    const floor = cfg?.complexityFloor ?? 6;
    const splittable = cfg?.splittableTypes ?? ['implement', 'refactor', 'test'];

    // Only first attempts — retries use micro-decompose
    if (task.attempts > 0) return false;
    // Complexity check
    if ((task.complexity ?? 0) < floor) return false;
    // Type check
    if (!splittable.includes(task.type)) return false;
    // Must be on critical path (foundation task)
    if (!task.isFoundation) return false;
    // Budget capacity check
    if (!this.budgetPool.hasCapacity()) return false;

    return true;
  }

  /**
   * LLM judge call: ask the orchestrator model whether and how to split a task.
   * Returns { shouldSplit: false } or { shouldSplit: true, subtasks: [...] }.
   */
  private async judgeSplit(task: SwarmTask): Promise<{ shouldSplit: boolean; subtasks?: SwarmTask[] }> {
    const maxSubs = this.config.autoSplit?.maxSubtasks ?? 4;

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

    const response = await this.provider.chat(
      [
        { role: 'system', content: 'You are a task planning judge. Return only valid JSON.' },
        { role: 'user', content: prompt },
      ],
      {
        model: this.config.orchestratorModel,
        maxTokens: 1500,
        temperature: 0.2,
      },
    );
    this.trackOrchestratorUsage(response as any, 'auto-split-judge');

    // Parse response — reuse markdown code block stripping from microDecompose
    let jsonStr = response.content.trim();
    const codeBlockMatch = jsonStr.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (codeBlockMatch) jsonStr = codeBlockMatch[1].trim();

    const parsed = JSON.parse(jsonStr);
    if (!parsed.shouldSplit) {
      this.logDecision('auto-split', `${task.id}: judge says no split — ${parsed.reason}`, '');
      return { shouldSplit: false };
    }
    if (!parsed.subtasks || !Array.isArray(parsed.subtasks) || parsed.subtasks.length < 2) {
      return { shouldSplit: false };
    }

    // Build SwarmTask[] from judge output (same pattern as microDecompose)
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

    this.logDecision('auto-split',
      `${task.id}: split into ${subtasks.length} subtasks — ${parsed.reason}`,
      subtasks.map(s => `${s.id}: ${s.description.slice(0, 60)}`).join('; '));

    return { shouldSplit: true, subtasks };
  }

  /**
   * V7: Compute effective retry limit for a task.
   * F10: Fixup tasks get max 2 retries (3 attempts total) — one full model-failover cycle.
   * Foundation tasks get +1 retry to reduce cascade failure risk.
   */
  private getEffectiveRetries(task: SwarmTask): number {
    const isFixup = 'fixesTaskId' in task;
    if (isFixup) return 2; // Fixup tasks: 2 retries max (3 attempts total)
    return task.isFoundation ? this.config.workerRetries + 1 : this.config.workerRetries;
  }

  /**
   * F22: Build a brief summary of swarm progress for retry context.
   * Helps retrying workers understand what the swarm has already accomplished.
   */
  private getSwarmProgressSummary(): string {
    const allTasks = this.taskQueue.getAllTasks();
    const completed = allTasks.filter(t => t.status === 'completed');

    if (completed.length === 0) return '';

    const lines: string[] = [];
    for (const task of completed) {
      const score = task.result?.qualityScore ? ` (${task.result.qualityScore}/5)` : '';
      lines.push(`- ${task.id}: ${task.description.slice(0, 80)}${score}`);
    }

    // Collect files created by completed tasks
    const files = new Set<string>();
    const baseDir = this.config.facts?.workingDirectory ?? process.cwd();
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
