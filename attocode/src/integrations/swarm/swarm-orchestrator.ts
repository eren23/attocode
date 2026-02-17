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
 *
 * Phase 3a: Heavy logic extracted into:
 * - swarm-lifecycle.ts   — Decomposition, planning, verification, resume, synthesis, helpers
 * - swarm-execution.ts   — Wave dispatch loop, task completion handling
 * - swarm-recovery.ts    — Error recovery, resilience, circuit breaker, adaptive stagger
 */

import type { LLMProvider, LLMProviderWithTools, ToolDefinitionSchema } from '../../providers/types.js';
import type { AgentRegistry } from '../agents/agent-registry.js';
import type { SharedBlackboard } from '../agents/shared-blackboard.js';
import { createSmartDecomposer, parseDecompositionResponse, validateDecomposition, type LLMDecomposeFunction, type SmartDecompositionResult } from '../tasks/smart-decomposer.js';
import { createResultSynthesizer } from '../agents/result-synthesizer.js';
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
  OrchestratorDecision,
  ArtifactInventory,
} from './types.js';
import { DEFAULT_SWARM_CONFIG } from './types.js';
import { SwarmTaskQueue, createSwarmTaskQueue } from './task-queue.js';
import { createSwarmBudgetPool, type SwarmBudgetPool } from './swarm-budget.js';
import { SwarmWorkerPool, createSwarmWorkerPool, type SpawnAgentFn } from './worker-pool.js';
import { ModelHealthTracker, selectAlternativeModel } from './model-selector.js';
import { SwarmStateStore } from './swarm-state-store.js';
import type { SwarmEvent } from './swarm-events.js';
import { createSharedContextState, type SharedContextState } from '../../shared/shared-context-state.js';
import { createSharedEconomicsState, type SharedEconomicsState } from '../../shared/shared-economics-state.js';
import { createSharedContextEngine, type SharedContextEngine } from '../../shared/context-engine.js';
import { calculateCost } from '../utilities/openrouter-pricing.js';

// ─── Extracted Module Imports ───────────────────────────────────────────

import {
  decomposeTask,
  planExecution,
  verifyIntegration,
  handleVerificationFailure,
  resumeExecution,
  synthesizeOutputs,
  saveCheckpoint,
  buildStats,
  buildSummary,
  buildErrorResult,
  detectFoundationTasks,
  buildArtifactInventory,
  skipRemainingTasks,
} from './swarm-lifecycle.js';

import {
  executeWaves as executeWavesImpl,
  executeWave as executeWaveImpl,
} from './swarm-execution.js';

import {
  type SwarmRecoveryState,
  finalRescuePass,
  midSwarmReplan,
} from './swarm-recovery.js';

// ─── Helpers (extracted to break circular dependency) ─────────────────────

import {
  repoLooksUnscaffolded,
  type SwarmEventListener,
} from './swarm-helpers.js';

// Re-export for backward compatibility
export { isHollowCompletion, FAILURE_INDICATORS, hasFutureIntentLanguage, BOILERPLATE_INDICATORS, repoLooksUnscaffolded, type SwarmEventListener } from './swarm-helpers.js';

// ─── OrchestratorInternals Interface ────────────────────────────────────

/**
 * The internal orchestrator state that extracted functions need access to.
 * Implemented by SwarmOrchestrator and exposed via getInternals().
 */
export interface OrchestratorInternals {
  config: SwarmConfig;
  provider: LLMProvider;
  blackboard?: SharedBlackboard;

  sharedContextState: SharedContextState;
  sharedEconomicsState: SharedEconomicsState;
  sharedContextEngine: SharedContextEngine;

  taskQueue: SwarmTaskQueue;
  budgetPool: SwarmBudgetPool;
  workerPool: SwarmWorkerPool;
  decomposer: ReturnType<typeof createSmartDecomposer>;
  synthesizer: ReturnType<typeof createResultSynthesizer>;

  listeners: SwarmEventListener[];
  errors: SwarmError[];
  cancelled: boolean;

  currentPhase: SwarmStatus['phase'];

  // Stats
  totalTokens: number;
  totalCost: number;
  qualityRejections: number;
  retries: number;
  startTime: number;
  modelUsage: Map<string, { tasks: number; tokens: number; cost: number }>;

  orchestratorTokens: number;
  orchestratorCost: number;
  orchestratorCalls: number;

  // V2
  plan?: SwarmPlan;
  waveReviews: WaveReviewResult[];
  verificationResult?: VerificationResult;
  artifactInventory?: ArtifactInventory;
  orchestratorDecisions: OrchestratorDecision[];
  healthTracker: ModelHealthTracker;
  stateStore?: SwarmStateStore;
  spawnAgentFn: SpawnAgentFn;

  // Hollow tracking
  hollowStreak: number;
  totalDispatches: number;
  totalHollows: number;

  // State
  originalPrompt: string;
  hasReplanned: boolean;

  // Helpers bound from the orchestrator
  emit: (event: SwarmEvent) => void;
  trackOrchestratorUsage: (response: any, purpose: string) => void;
  logDecision: (phase: string, decision: string, reasoning: string) => void;

  // Methods delegated back to orchestrator (for cross-cutting calls)
  executeWaves: () => Promise<void>;
  executeWave: (tasks: SwarmTask[]) => Promise<void>;
  finalRescuePass: () => Promise<void>;
}

// ─── Orchestrator ──────────────────────────────────────────────────────

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

  // Hollow completion streak: early termination when single-model swarm produces only hollows
  private hollowStreak = 0;

  // V7: Global dispatch + hollow ratio tracking for multi-model termination
  private totalDispatches = 0;
  private totalHollows = 0;

  // Original prompt for re-planning on resume
  private originalPrompt = '';

  // Mid-swarm re-planning: only once per swarm execution
  private hasReplanned = false;

  // Recovery state (circuit breaker, stagger, quality gate breaker, etc.)
  private recoveryState: SwarmRecoveryState;

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

    // Initialize recovery state
    const initialStagger = this.config.dispatchStaggerMs ?? 500;
    this.recoveryState = {
      recentRateLimits: [],
      circuitBreakerUntil: 0,
      perModelQualityRejections: new Map(),
      qualityGateDisabledModels: new Set(),
      adaptiveStaggerMs: initialStagger,
      taskTimeoutCounts: new Map(),
      hollowRatioWarned: false,
    };

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
    const llmDecompose: LLMDecomposeFunction = async (task, context) => {
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

      // Build codebase context section from repo map if available
      let codebaseSection = '';
      if (context.repoMap) {
        const map = context.repoMap;
        const topFiles = Array.from(map.chunks.values())
          .sort((a, b) => b.importance - a.importance)
          .slice(0, 30)
          .map(c => `  - ${c.filePath} (${c.type}, ${c.tokenCount} tokens, importance: ${c.importance.toFixed(2)})`);

        codebaseSection = `

CODEBASE STRUCTURE (${map.chunks.size} files, ${map.totalTokens} total tokens):
Entry points: ${map.entryPoints.slice(0, 5).join(', ')}
Core modules: ${map.coreModules.slice(0, 5).join(', ')}
Key files:
${topFiles.join('\n')}

CRITICAL: Your subtasks MUST reference actual files from this codebase.
Do NOT invent new project scaffolding or create files that don't relate to the existing codebase.
Decompose the work based on what ALREADY EXISTS in the project.`;
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
}${customTypeSection}${codebaseSection}

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

        // Retry with explicit JSON instruction
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
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        if (process.env.DEBUG) {
          console.error(`[SwarmOrchestrator] Listener error on ${event.type}: ${msg}`);
        }
      }
    }
  }

  /**
   * Track token usage from an orchestrator LLM call.
   */
  private trackOrchestratorUsage(response: { usage?: { total_tokens?: number; prompt_tokens?: number; completion_tokens?: number; inputTokens?: number; outputTokens?: number; cost?: number } }, purpose: string): void {
    if (!response.usage) return;
    const input = response.usage.prompt_tokens ?? response.usage.inputTokens ?? 0;
    const output = response.usage.completion_tokens ?? response.usage.outputTokens ?? 0;
    const tokens = response.usage.total_tokens ?? (input + output);
    const cost = response.usage.cost ?? calculateCost(this.config.orchestratorModel, input, output);
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
   * Build the OrchestratorInternals interface for extracted functions.
   */
  private getInternals(): OrchestratorInternals {
    return {
      config: this.config,
      provider: this.provider,
      blackboard: this.blackboard,
      sharedContextState: this.sharedContextState,
      sharedEconomicsState: this.sharedEconomicsState,
      sharedContextEngine: this.sharedContextEngine,
      taskQueue: this.taskQueue,
      budgetPool: this.budgetPool,
      workerPool: this.workerPool,
      decomposer: this._decomposer,
      synthesizer: this.synthesizer,
      listeners: this.listeners,
      errors: this.errors,
      cancelled: this.cancelled,
      currentPhase: this.currentPhase,
      totalTokens: this.totalTokens,
      totalCost: this.totalCost,
      qualityRejections: this.qualityRejections,
      retries: this.retries,
      startTime: this.startTime,
      modelUsage: this.modelUsage,
      orchestratorTokens: this.orchestratorTokens,
      orchestratorCost: this.orchestratorCost,
      orchestratorCalls: this.orchestratorCalls,
      plan: this.plan,
      waveReviews: this.waveReviews,
      verificationResult: this.verificationResult,
      artifactInventory: this.artifactInventory,
      orchestratorDecisions: this.orchestratorDecisions,
      healthTracker: this.healthTracker,
      stateStore: this.stateStore,
      spawnAgentFn: this.spawnAgentFn,
      hollowStreak: this.hollowStreak,
      totalDispatches: this.totalDispatches,
      totalHollows: this.totalHollows,
      originalPrompt: this.originalPrompt,
      hasReplanned: this.hasReplanned,
      emit: (event: SwarmEvent) => this.emit(event),
      trackOrchestratorUsage: (response: any, purpose: string) => this.trackOrchestratorUsage(response, purpose),
      logDecision: (phase: string, decision: string, reasoning: string) => this.logDecision(phase, decision, reasoning),
      executeWaves: () => this.executeWavesDelegate(),
      executeWave: (tasks: SwarmTask[]) => this.executeWaveDelegate(tasks),
      finalRescuePass: () => this.finalRescuePassDelegate(),
    };
  }

  /**
   * Sync mutable state back from internals after an extracted function call.
   * The internals object holds references to mutable objects (arrays, maps),
   * but primitive values need syncing back.
   */
  private syncFromInternals(ctx: OrchestratorInternals): void {
    this.cancelled = ctx.cancelled;
    this.currentPhase = ctx.currentPhase;
    this.totalTokens = ctx.totalTokens;
    this.totalCost = ctx.totalCost;
    this.qualityRejections = ctx.qualityRejections;
    this.retries = ctx.retries;
    this.orchestratorTokens = ctx.orchestratorTokens;
    this.orchestratorCost = ctx.orchestratorCost;
    this.orchestratorCalls = ctx.orchestratorCalls;
    this.plan = ctx.plan;
    this.verificationResult = ctx.verificationResult;
    this.artifactInventory = ctx.artifactInventory;
    this.hollowStreak = ctx.hollowStreak;
    this.totalDispatches = ctx.totalDispatches;
    this.totalHollows = ctx.totalHollows;
    this.originalPrompt = ctx.originalPrompt;
    this.hasReplanned = ctx.hasReplanned;
  }

  /**
   * Execute the full swarm pipeline for a task.
   */
  async execute(task: string): Promise<SwarmExecutionResult> {
    this.startTime = Date.now();
    this.originalPrompt = task;

    try {
      const ctx = this.getInternals();

      // V2: Check for resume
      if (this.config.resumeSessionId && this.stateStore) {
        const resumeResult = await resumeExecution(
          ctx, task,
          () => midSwarmReplan(ctx),
        );
        this.syncFromInternals(ctx);
        if (resumeResult) return resumeResult;
        // null means no checkpoint found, fall through to normal execute
      }

      // Phase 1: Decompose
      this.currentPhase = 'decomposing';
      ctx.currentPhase = 'decomposing';
      this.emit({ type: 'swarm.phase.progress', phase: 'decomposing', message: 'Decomposing task into subtasks...' });
      const decomposeOutcome = await decomposeTask(ctx, task);
      this.syncFromInternals(ctx);
      if (!decomposeOutcome.result) {
        this.currentPhase = 'failed';
        return buildErrorResult(ctx, `Decomposition failed: ${decomposeOutcome.failureReason}`);
      }
      let decomposition = decomposeOutcome.result;

      // If repository is mostly empty, force a scaffold-first dependency chain
      if (repoLooksUnscaffolded(this.config.facts?.workingDirectory ?? process.cwd())) {
        const scaffoldTask = decomposition.subtasks.find(st =>
          /\b(scaffold|bootstrap|initialize|setup|set up|project scaffold)\b/i.test(st.description)
        );
        if (scaffoldTask) {
          for (const subtask of decomposition.subtasks) {
            if (subtask.id === scaffoldTask.id) continue;
            if (!subtask.dependencies.includes(scaffoldTask.id)) {
              subtask.dependencies.push(scaffoldTask.id);
            }
          }
          this.logDecision(
            'scaffold-first',
            `Repo appears unscaffolded; enforcing scaffold task ${scaffoldTask.id} as prerequisite`,
            ''
          );
        }
      }

      // F5: Validate decomposition
      const validation = validateDecomposition(decomposition);
      if (validation.warnings.length > 0) {
        this.logDecision('decomposition-validation',
          `Warnings: ${validation.warnings.join('; ')}`, '');
      }
      if (!validation.valid) {
        this.logDecision('decomposition-validation',
          `Invalid decomposition: ${validation.issues.join('; ')}`, 'Retrying...');
        const retryOutcome = await decomposeTask(
          ctx,
          `${task}\n\nIMPORTANT: Previous decomposition was invalid: ${validation.issues.join('. ')}. Fix these issues.`,
        );
        this.syncFromInternals(ctx);
        if (!retryOutcome.result) {
          this.currentPhase = 'failed';
          return buildErrorResult(ctx, `Decomposition validation failed: ${validation.issues.join('; ')}`);
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
      ctx.currentPhase = 'scheduling';
      this.emit({ type: 'swarm.phase.progress', phase: 'scheduling', message: `Scheduling ${decomposition.subtasks.length} subtasks into waves...` });
      this.taskQueue.loadFromDecomposition(decomposition, this.config);

      // F3: Dynamic orchestrator reserve scaling
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

      // Foundation task detection
      detectFoundationTasks(ctx);

      // D3/F1: Probe model capability before dispatch
      if (this.config.probeModels !== false) {
        await this.probeModelCapability();

        const probeStrategy = this.config.probeFailureStrategy
          ?? (this.config.ignoreProbeFailures ? 'warn-and-try' : 'warn-and-try');
        const uniqueModels = [...new Set(this.config.workers.map(w => w.model))];
        const healthyModels = this.healthTracker.getHealthy(uniqueModels);

        if (healthyModels.length === 0 && uniqueModels.length > 0) {
          if (probeStrategy === 'abort') {
            const reason = `All ${uniqueModels.length} worker model(s) failed capability probes — no model can make tool calls. Aborting swarm to prevent budget waste. Fix model configuration and retry.`;
            this.logDecision('probe-abort', reason, `Models tested: ${uniqueModels.join(', ')}`);
            this.emit({ type: 'swarm.abort', reason });
            skipRemainingTasks(ctx, reason);
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
            this.logDecision('probe-warning',
              `All ${uniqueModels.length} model(s) failed probe — continuing anyway (strategy: warn-and-try)`,
              'Will abort after first real task failure if model cannot use tools');
            for (const model of uniqueModels) {
              this.healthTracker.recordSuccess(model, 0);
            }
          }
        }
      }

      // Emit skip events when tasks are cascade-skipped
      this.taskQueue.setOnCascadeSkip((skippedTaskId, reason) => {
        this.emit({ type: 'swarm.task.skipped', taskId: skippedTaskId, reason });
      });

      const stats = this.taskQueue.getStats();
      this.emit({ type: 'swarm.phase.progress', phase: 'scheduling', message: `Scheduled ${stats.total} tasks in ${this.taskQueue.getTotalWaves()} waves` });

      // V2: Phase 2.5: Plan execution
      let planPromise: Promise<void> | undefined;
      if (this.config.enablePlanning) {
        this.currentPhase = 'planning';
        ctx.currentPhase = 'planning';
        this.emit({ type: 'swarm.phase.progress', phase: 'planning', message: 'Creating acceptance criteria...' });
        planPromise = planExecution(ctx, task, decomposition).then(() => {
          this.syncFromInternals(ctx);
        }).catch(err => {
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

      // Emit tasks AFTER swarm.start
      this.emit({
        type: 'swarm.tasks.loaded',
        tasks: this.taskQueue.getAllTasks(),
      });

      // Phase 3: Execute waves
      this.currentPhase = 'executing';
      ctx.currentPhase = 'executing';
      await this.executeWavesDelegate();
      this.syncFromInternals(ctx);

      // V10: Final rescue pass
      if (!this.cancelled) {
        await this.finalRescuePassDelegate();
        this.syncFromInternals(ctx);
      }

      // Ensure planning completed
      if (planPromise) await planPromise;

      // Post-wave artifact audit
      this.artifactInventory = buildArtifactInventory(ctx);

      // V2: Phase 3.5: Verify integration
      if (this.config.enableVerification && this.plan?.integrationTestPlan) {
        this.currentPhase = 'verifying';
        ctx.currentPhase = 'verifying';
        const verification = await verifyIntegration(ctx, this.plan.integrationTestPlan);
        this.syncFromInternals(ctx);

        if (!verification.passed) {
          await handleVerificationFailure(ctx, verification, task);
          this.syncFromInternals(ctx);
        }
      }

      // Phase 4: Synthesize results
      this.currentPhase = 'synthesizing';
      ctx.currentPhase = 'synthesizing';
      const synthesisResult = await synthesizeOutputs(ctx);
      this.syncFromInternals(ctx);

      this.currentPhase = 'completed';
      ctx.currentPhase = 'completed';
      const executionStats = buildStats(ctx);

      // V2: Final checkpoint
      saveCheckpoint(ctx, 'final');

      const hasArtifacts = (this.artifactInventory?.totalFiles ?? 0) > 0;
      this.emit({ type: 'swarm.complete', stats: executionStats, errors: this.errors, artifactInventory: this.artifactInventory });

      // Success requires completing at least 70% of tasks
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
        artifactInventory: this.artifactInventory,
        summary: buildSummary(ctx, executionStats),
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
      const ctx = this.getInternals();
      return buildErrorResult(ctx, message);
    } finally {
      this.workerPool.cleanup();
    }
  }

  /**
   * Get live status for TUI.
   */
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
   */
  async cancel(): Promise<void> {
    this.cancelled = true;
    this.currentPhase = 'failed';
    await this.workerPool.cancelAll();
  }

  // ─── D3: Model Capability Probing ─────────────────────────────────────

  private async probeModelCapability(): Promise<void> {
    const uniqueModels = new Set(this.config.workers.map(w => w.model));
    this.emit({ type: 'swarm.phase.progress', phase: 'scheduling', message: `Probing ${uniqueModels.size} model(s) for tool-calling capability...` });

    const supportsTools = 'chatWithTools' in this.provider
      && typeof (this.provider as LLMProviderWithTools).chatWithTools === 'function';

    if (!supportsTools) {
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
          this.healthTracker.markUnhealthy(model);
          this.logDecision('model-probe', `Model ${model} failed probe (no tool calls)`, 'Marked unhealthy');
        } else {
          this.healthTracker.recordSuccess(model, 0);
          this.logDecision('model-probe', `Model ${model} passed probe`, '');
        }
      } catch {
        this.healthTracker.markUnhealthy(model);
        this.logDecision('model-probe', `Model ${model} probe errored`, 'Marked unhealthy');
      }
    }
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

  // ─── Delegation Methods ───────────────────────────────────────────────

  /**
   * Delegate to executeWaves in swarm-execution.ts.
   */
  private async executeWavesDelegate(): Promise<void> {
    const ctx = this.getInternals();
    await executeWavesImpl(ctx, this.recoveryState, () => this.getStatus());
    this.syncFromInternals(ctx);
  }

  /**
   * Delegate to executeWave in swarm-execution.ts.
   */
  private async executeWaveDelegate(tasks: SwarmTask[]): Promise<void> {
    const ctx = this.getInternals();
    await executeWaveImpl(ctx, this.recoveryState, tasks, () => this.getStatus());
    this.syncFromInternals(ctx);
  }

  /**
   * Delegate to finalRescuePass in swarm-recovery.ts.
   */
  private async finalRescuePassDelegate(): Promise<void> {
    const ctx = this.getInternals();
    await finalRescuePass(ctx, (tasks) => this.executeWaveDelegate(tasks));
    this.syncFromInternals(ctx);
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
