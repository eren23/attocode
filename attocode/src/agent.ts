/**
 * Lesson 25: Production Agent
 *
 * The capstone agent that composes all features from previous lessons
 * into a production-ready, modular system.
 *
 * Features integrated:
 * - Hooks & Plugins (Lessons 10-11)
 * - Rules System (Lesson 12)
 * - Memory Systems (Lesson 14)
 * - Planning & Reflection (Lessons 15-16)
 * - Multi-Agent Coordination (Lesson 17)
 * - ReAct Pattern (Lesson 18)
 * - Observability (Lesson 19)
 * - Sandboxing (Lesson 20)
 * - Human-in-the-Loop (Lesson 21)
 * - Model Routing (Lesson 22)
 * - Execution Policies (Lesson 23)
 * - Thread Management (Lesson 24)
 */

import * as path from 'node:path';

import type {
  ProductionAgentConfig,
  LLMProvider,
  Message,
  ToolDefinition,
  AgentState,
  AgentMetrics,
  AgentPlan,
  AgentResult,
  AgentEvent,
  AgentEventListener,
  AgentCompletionStatus,
  OpenTaskSummary,
} from './types.js';

import {
  buildConfig,
  isFeatureEnabled,
} from './defaults.js';

import {
  ModeManager,
  createModeManager,
  formatModeList,
  parseMode,
  type AgentMode,
} from './modes.js';

import {
  createLSPFileTools,
  type LSPFileToolsConfig,
} from './agent-tools/index.js';

import {
  HookManager,
  MemoryManager,
  PlanningManager,
  ObservabilityManager,
  SafetyManager,
  RoutingManager,
  MultiAgentManager,
  ReActManager,
  ExecutionPolicyManager,
  ThreadManager,
  RulesManager,
  ExecutionEconomicsManager,
  STANDARD_BUDGET,
  AgentRegistry,
  formatAgentList,
  CancellationManager,
  isCancellationError,
  ResourceManager,
  LSPManager,
  SemanticCacheManager,
  SkillManager,
  formatSkillList,
  ContextEngineeringManager,
  CodebaseContextManager,
  type ExecutionBudget,
  type AgentRole,
  type TeamTask,
  type TeamResult,
  type ReActTrace,
  type Checkpoint,
  type AgentDefinition,
  type LoadedAgent,
  type SpawnResult,
  type CancellationTokenType,
  type Skill,
  type CacheableContentBlock,
  SharedFileCache,
  createSharedFileCache,
  SharedBudgetPool,
  createBudgetPool,
  type ApprovalScope,
  PendingPlanManager,
  createPendingPlanManager,
  type PendingPlan,
  InteractivePlanner,
  RecursiveContextManager,
  LearningStore,
  Compactor,
  AutoCompactionManager,
  FileChangeTracker,
  createFileChangeTracker,
  CapabilitiesRegistry,
  createCapabilitiesRegistry,
  SharedBlackboard,
  createSharedBlackboard,
  TaskManager,
  type SQLiteStore,
  SwarmOrchestrator,
  type SwarmExecutionResult,
  WorkLog,
  VerificationGate,
  classifyComplexity,
  type ComplexityAssessment,
  ToolRecommendationEngine,
  InjectionBudgetManager,
  SelfImprovementProtocol,
  SubagentOutputStore,
  AutoCheckpointManager,
} from './integrations/index.js';

import type { SharedContextState } from './shared/shared-context-state.js';
import type { SharedEconomicsState } from './shared/shared-economics-state.js';
import { TraceCollector } from './tracing/trace-collector.js';
import { modelRegistry } from './costs/index.js';
import { getModelContextLength } from './integrations/utilities/openrouter-pricing.js';
import { createComponentLogger } from './integrations/utilities/logger.js';

// Spawn agent tools type for LLM-driven subagent delegation
import {
  type SpawnConstraints,
} from './tools/agent.js';

// =============================================================================
// PRODUCTION AGENT
// =============================================================================

/**
 * Tools that are safe to execute in parallel (read-only, no side effects).
 * These tools don't modify state, so running them concurrently is safe.
 */
const log = createComponentLogger('ProductionAgent');

// Tool-batching constants (canonical home: core/tool-executor.ts)
import {
  PARALLELIZABLE_TOOLS,
  CONDITIONALLY_PARALLEL_TOOLS,
  extractToolFilePath,
  groupToolCallsIntoBatches,
} from './core/index.js';
export { PARALLELIZABLE_TOOLS, CONDITIONALLY_PARALLEL_TOOLS, extractToolFilePath, groupToolCallsIntoBatches };

// Extracted core modules (Phase 2.1 — thin orchestrator delegates)
import {
  executeDirectly as coreExecuteDirectly,
  spawnAgent as coreSpawnAgent,
  spawnAgentsParallel as coreSpawnAgentsParallel,
} from './core/index.js';

// Phase 2.2: Agent State Machine
import { type AgentStateMachine } from './core/agent-state-machine.js';
import { detectIncompleteActionResponse } from './core/completion-analyzer.js';

// Feature initialization (extracted from initializeFeatures method)
import { initializeFeatures as doInitializeFeatures, type AgentInternals } from './agent/feature-initializer.js';

// Message builder (extracted from buildMessages method)
import { buildMessages as doBuildMessages, type MessageBuilderDeps } from './agent/message-builder.js';

// Session/checkpoint/file-change API (extracted from ProductionAgent methods)
import {
  trackFileChange as doTrackFileChange,
  undoLastFileChange as doUndoLastFileChange,
  undoCurrentTurn as doUndoCurrentTurn,
  reset as doReset,
  loadMessages as doLoadMessages,
  getSerializableState as doGetSerializableState,
  validateCheckpoint as doValidateCheckpoint,
  loadState as doLoadState,
  type SessionApiDeps,
} from './agent/session-api.js';

/**
 * Production-ready agent that composes all features.
 */
export class ProductionAgent {
  private config: ReturnType<typeof buildConfig>;
  private provider: LLMProvider;
  private tools: Map<string, ToolDefinition>;

  // Integration managers
  private hooks: HookManager | null = null;
  private memory: MemoryManager | null = null;
  private planning: PlanningManager | null = null;
  private observability: ObservabilityManager | null = null;
  private safety: SafetyManager | null = null;
  private routing: RoutingManager | null = null;
  private multiAgent: MultiAgentManager | null = null;
  private react: ReActManager | null = null;
  private executionPolicy: ExecutionPolicyManager | null = null;
  private threadManager: ThreadManager | null = null;
  private rules: RulesManager | null = null;
  private economics: ExecutionEconomicsManager | null = null;
  private agentRegistry: AgentRegistry | null = null;
  private cancellation: CancellationManager | null = null;
  private resourceManager: ResourceManager | null = null;
  private lspManager: LSPManager | null = null;
  private semanticCache: SemanticCacheManager | null = null;
  private skillManager: SkillManager | null = null;
  private contextEngineering: ContextEngineeringManager | null = null;
  private codebaseContext: CodebaseContextManager | null = null;
  private codebaseAnalysisTriggered = false;
  private traceCollector: TraceCollector | null = null;
  private modeManager: ModeManager;
  private pendingPlanManager: PendingPlanManager;
  private interactivePlanner: InteractivePlanner | null = null;
  private recursiveContext: RecursiveContextManager | null = null;
  private learningStore: LearningStore | null = null;
  private compactor: Compactor | null = null;
  private autoCompactionManager: AutoCompactionManager | null = null;
  private fileChangeTracker: FileChangeTracker | null = null;
  private capabilitiesRegistry: CapabilitiesRegistry | null = null;
  private toolResolver: ((toolName: string) => ToolDefinition | null) | null = null;
  private agentId!: string;
  private blackboard: SharedBlackboard | null = null;
  private fileCache: SharedFileCache | null = null;
  private _sharedContextState: SharedContextState | null = null;
  private _sharedEconomicsState: SharedEconomicsState | null = null;
  private budgetPool: SharedBudgetPool | null = null;
  private taskManager: TaskManager | null = null;
  private store: SQLiteStore | null = null;
  private swarmOrchestrator: SwarmOrchestrator | null = null;
  private workLog: WorkLog | null = null;
  private verificationGate: VerificationGate | null = null;

  // Phase 2-4 integration modules
  private injectionBudget: InjectionBudgetManager | null = null;
  private selfImprovement: SelfImprovementProtocol | null = null;
  private subagentOutputStore: SubagentOutputStore | null = null;
  private autoCheckpointManager: AutoCheckpointManager | null = null;
  private toolRecommendation: ToolRecommendationEngine | null = null;
  private stateMachine: AgentStateMachine | null = null;
  private lastComplexityAssessment: ComplexityAssessment | null = null;
  private lastSystemPromptLength = 0;

  // Duplicate spawn prevention - tracks recently spawned tasks to prevent doom loops
  // Map<taskKey, { timestamp: number; result: string; queuedChanges: number }>
  private spawnedTasks = new Map<string, { timestamp: number; result: string; queuedChanges: number }>();
  // SPAWN_DEDUP_WINDOW_MS moved to core/subagent-spawner.ts

  // Parent iteration tracking for total budget calculation
  private parentIterations = 0;

  // External cancellation token (for subagent timeout propagation)
  // When set, the agent will check this token in addition to its own cancellation manager
  private externalCancellationToken: CancellationTokenType | null = null;

  // Graceful wrapup support (for subagent timeout wrapup phase)
  private wrapupRequested = false;
  private wrapupReason: string | null = null;

  // Cacheable system prompt blocks for prompt caching (Improvement P1)
  // When set, callLLM() will inject these as structured content with cache_control markers
  private cacheableSystemBlocks: CacheableContentBlock[] | null = null;

  // Pre-compaction agentic turn: when true, the agent gets one more LLM turn
  // to summarize its state before compaction clears the context.
  private compactionPending = false;

  // Initialization tracking
  private initPromises: Promise<void>[] = [];
  private initComplete = false;

  // Event listener cleanup tracking (prevents memory leaks in long sessions)
  private unsubscribers: Array<() => void> = [];

  // State
  private state: AgentState = {
    status: 'idle',
    messages: [],
    plan: undefined,
    memoryContext: [],
    metrics: {
      totalTokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      estimatedCost: 0,
      llmCalls: 0,
      toolCalls: 0,
      duration: 0,
      successCount: 0,
      failureCount: 0,
      cancelCount: 0,
      retryCount: 0,
    },
    iteration: 0,
  };

  constructor(userConfig: Partial<ProductionAgentConfig> & { provider: LLMProvider }) {
    // Build complete config with defaults
    this.config = buildConfig(userConfig);
    this.provider = userConfig.provider;

    // Set unique agent ID (passed from spawnAgent for subagents, auto-generated for parents)
    this.agentId = userConfig.agentId || `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    // Initialize tool registry
    this.tools = new Map();
    for (const tool of this.config.tools) {
      this.tools.set(tool.name, tool);
    }

    // Store tool resolver for lazy-loading unknown tools (e.g., MCP tools)
    this.toolResolver = userConfig.toolResolver || null;

    // Initialize mode manager (always enabled)
    this.modeManager = createModeManager(this.config.tools);

    // Initialize pending plan manager for plan mode write interception
    this.pendingPlanManager = createPendingPlanManager();

    // Shared Blackboard - enables coordination between parallel subagents
    // Subagents inherit parent's blackboard; parent agents create their own
    if (userConfig.blackboard) {
      this.blackboard = userConfig.blackboard as SharedBlackboard;
    } else if (this.config.subagent !== false) {
      this.blackboard = createSharedBlackboard({
        maxFindings: 500,
        defaultClaimTTL: 120000, // 2 minutes for file claims
        deduplicateFindings: true,
      });
    }

    // Shared File Cache - eliminates redundant file reads across parent and subagents
    // Subagents inherit parent's cache; parent agents create their own
    if ((userConfig as Record<string, unknown>).fileCache) {
      this.fileCache = (userConfig as Record<string, unknown>).fileCache as SharedFileCache;
    } else if (this.config.subagent !== false) {
      this.fileCache = createSharedFileCache({
        maxCacheBytes: 5 * 1024 * 1024, // 5MB
        ttlMs: 5 * 60 * 1000, // 5 minutes
      });
    }

    // Shared Budget Pool - pools token budget across parent and subagents
    // Only parent agents create the pool; subagents don't need their own
    // The pool is used in spawnAgent() to allocate budgets from the parent's total
    if (this.config.subagent !== false) {
      // Use actual configured budget (custom or default), not always STANDARD_BUDGET
      const baseBudget = this.config.budget ?? STANDARD_BUDGET;
      const parentBudgetTokens = baseBudget.maxTokens ?? STANDARD_BUDGET.maxTokens ?? 200000;
      this.budgetPool = createBudgetPool(parentBudgetTokens, 0.25, 100000);
    }

    // Shared state for swarm workers (passed from orchestrator via config)
    this._sharedContextState = (userConfig as any).sharedContextState ?? null;
    this._sharedEconomicsState = (userConfig as any).sharedEconomicsState ?? null;

    // Initialize enabled features
    this.initializeFeatures();
  }

  /**
   * Initialize all enabled features.
   * Delegates to the extracted feature-initializer module.
   */
  private initializeFeatures(): void {
    doInitializeFeatures(this as unknown as AgentInternals);
  }

  /**
   * Initialize the file change tracker with a database instance.
   * Call this if you want undo capability for file operations.
   *
   * @param db - SQLite database instance from better-sqlite3
   * @param sessionId - Session ID for tracking changes
   */
  initFileChangeTracker(db: import('better-sqlite3').Database, sessionId: string): void {
    if (!isFeatureEnabled(this.config.fileChangeTracker)) {
      return;
    }

    const trackerConfig = typeof this.config.fileChangeTracker === 'object'
      ? this.config.fileChangeTracker
      : {};

    this.fileChangeTracker = createFileChangeTracker(db, sessionId, {
      enabled: true,
      maxFullContentBytes: trackerConfig.maxFullContentBytes ?? 50 * 1024,
    });

    this.observability?.logger?.info('File change tracker initialized', {
      sessionId,
      maxFullContentBytes: trackerConfig.maxFullContentBytes ?? 50 * 1024,
    });
  }

  /**
   * Ensure all async initialization is complete before running.
   * Call this at the start of run() to prevent race conditions.
   */
  async ensureReady(): Promise<void> {
    if (this.initComplete) {
      return;
    }

    if (this.initPromises.length > 0) {
      await Promise.all(this.initPromises);
    }

    this.initComplete = true;
  }

  /**
   * Run the agent on a task.
   */
  async run(task: string): Promise<AgentResult> {
    // Ensure all integrations are ready before running
    await this.ensureReady();
    this.reconcileStaleTasks('run_start');

    const startTime = Date.now();

    // Create cancellation context if enabled
    const cancellationConfig = isFeatureEnabled(this.config.cancellation) ? this.config.cancellation : null;
    const cancellationToken = this.cancellation?.createContext(
      cancellationConfig?.defaultTimeout || undefined
    );

    // Start tracing
    const traceId = this.observability?.tracer?.startTrace('agent.run') || `trace-${Date.now()}`;
    this.emit({ type: 'start', task, traceId });
    this.emit({ type: 'run.before', task });
    this.observability?.logger?.info('Agent started', { task });

    // Lesson 26: Start trace capture
    // If session is already active (managed by REPL), start a task within it.
    // Otherwise, start a new session for backward compatibility (single-task mode).
    const taskId = `task-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    if (this.traceCollector?.isSessionActive()) {
      // Session managed by REPL - just start a task
      await this.traceCollector.startTask(taskId, task);
    } else {
      // Single-task mode (backward compatibility) - start session with task
      const traceSessionId = `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const sessionMetadata: Record<string, unknown> = {};
      if (this.swarmOrchestrator) {
        sessionMetadata.swarm = true;
      }
      await this.traceCollector?.startSession(traceSessionId, task, this.config.model || 'default', sessionMetadata);
    }

    try {
      let runSuccess = true;
      let runFailureReason: string | undefined;
      let completion: AgentCompletionStatus = {
        success: true,
        reason: 'completed',
      };

      // Check for cancellation before starting
      cancellationToken?.throwIfCancellationRequested();

      // Classify task complexity for scaling guidance
      this.lastComplexityAssessment = classifyComplexity(task, {
        hasActivePlan: !!this.state.plan,
      });

      // Check if swarm mode should handle this task
      if (this.swarmOrchestrator) {
        const swarmResult = await this.runSwarm(task);
        if (!swarmResult.success) {
          runSuccess = false;
          runFailureReason = swarmResult.summary || 'Swarm reported unsuccessful execution';
          completion = {
            success: false,
            reason: 'swarm_failure',
            details: runFailureReason,
          };
        }
        // Guard against summaries that still indicate pending work.
        if (detectIncompleteActionResponse(swarmResult.summary || '')) {
          this.emit({ type: 'completion.before', reason: 'future_intent' });
          runSuccess = false;
          runFailureReason = 'Swarm summary indicates pending, unexecuted work';
          completion = {
            success: false,
            reason: 'future_intent',
            details: runFailureReason,
            futureIntentDetected: true,
          };
        }
        // Store swarm summary as an assistant message for the response
        this.state.messages.push({ role: 'assistant', content: swarmResult.summary });
      } else if (this.planning?.shouldPlan(task)) {
        // Check if planning is needed
        await this.createAndExecutePlan(task);
      } else {
        const directResult = await this.executeDirectly(task);
        if (!directResult.success) {
          runSuccess = false;
          runFailureReason = directResult.failureReason || directResult.terminationReason;
        }
        completion = {
          success: directResult.success,
          reason: directResult.terminationReason,
          ...(directResult.failureReason ? { details: directResult.failureReason } : {}),
          ...(directResult.openTasks ? { openTasks: directResult.openTasks } : {}),
        };
      }

      // Get final response - find the LAST assistant message (not just check if last message is assistant)
      const assistantMessages = this.state.messages.filter(m => m.role === 'assistant');
      const lastAssistantMessage = assistantMessages[assistantMessages.length - 1];
      const response = typeof lastAssistantMessage?.content === 'string'
        ? lastAssistantMessage.content
        : '';

      // Final guardrail: never mark a run successful if the final answer is "I'll do X".
      if (runSuccess && detectIncompleteActionResponse(response)) {
        this.emit({ type: 'completion.before', reason: 'future_intent' });
        runSuccess = false;
        runFailureReason = 'Final response indicates pending, unexecuted work';
        completion = {
          success: false,
          reason: 'future_intent',
          details: runFailureReason,
          futureIntentDetected: true,
        };
      }

      if (runSuccess && completion.reason === 'completed') {
        this.reconcileStaleTasks('run_end');
        const openTasks = this.getOpenTasksSummary();
        if (openTasks && (openTasks.inProgress > 0 || openTasks.pending > 0)) {
          this.emit({ type: 'completion.before', reason: 'open_tasks' });
          runSuccess = false;
          runFailureReason = `Open tasks remain: ${openTasks.pending} pending, ${openTasks.inProgress} in_progress`;
          completion = {
            success: false,
            reason: 'open_tasks',
            details: runFailureReason,
            openTasks,
          };
          this.emit({
            type: 'completion.blocked',
            reasons: [
              runFailureReason,
              openTasks.blocked > 0 ? `${openTasks.blocked} pending tasks are blocked` : '',
            ].filter(Boolean),
            openTasks,
            diagnostics: {
              forceTextOnly: false,
              availableTasks: this.taskManager?.getAvailableTasks().length ?? 0,
              pendingWithOwner: 0,
            },
          });
        }
      }

      // Finalize
      const duration = Date.now() - startTime;
      this.state.metrics.duration = duration;
      if (runSuccess) {
        this.state.metrics.successCount = (this.state.metrics.successCount ?? 0) + 1;
      } else {
        this.state.metrics.failureCount = (this.state.metrics.failureCount ?? 0) + 1;
      }

      await this.observability?.tracer?.endTrace();

      const result: AgentResult = {
        success: runSuccess,
        response,
        ...(runSuccess ? {} : { error: runFailureReason ?? 'Task failed' }),
        metrics: this.getMetrics(),
        messages: this.state.messages,
        traceId,
        plan: this.state.plan,
        completion,
      };
      result.completion.recovery = {
        intraRunRetries: this.state.metrics.retryCount ?? 0,
        autoLoopRuns: 0,
        terminal: !runSuccess,
        reasonChain: [completion.reason],
      };

      this.emit({ type: 'complete', result });
      this.emit({
        type: 'completion.after',
        success: runSuccess,
        reason: completion.reason,
        ...(completion.details ? { details: completion.details } : {}),
      });
      this.emit({
        type: 'run.after',
        success: runSuccess,
        reason: completion.reason,
        ...(completion.details ? { details: completion.details } : {}),
      });
      this.observability?.logger?.info('Agent completed', {
        duration,
        success: runSuccess,
        ...(runFailureReason ? { failureReason: runFailureReason } : {}),
      });

      // Lesson 26: End trace capture
      // If task is active (REPL mode), end the task. Otherwise end the session (single-task mode).
      if (this.traceCollector?.isTaskActive()) {
        await this.traceCollector.endTask(
          runSuccess
            ? { success: true, output: response }
            : { success: false, failureReason: runFailureReason ?? 'Task failed', output: response },
        );
      } else if (this.traceCollector?.isSessionActive()) {
        await this.traceCollector.endSession(
          runSuccess
            ? { success: true, output: response }
            : { success: false, failureReason: runFailureReason ?? 'Task failed', output: response },
        );
      }

      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));

      // Handle cancellation specially
      if (isCancellationError(err)) {
        const cleanupStart = Date.now();
        this.cancellation?.disposeContext();
        const cleanupDuration = Date.now() - cleanupStart;

        this.emit({ type: 'cancellation.completed', cleanupDuration });
        this.observability?.logger?.info('Agent cancelled', { reason: error.message, cleanupDuration });
        this.state.metrics.cancelCount = (this.state.metrics.cancelCount ?? 0) + 1;

        // Lesson 26: End trace capture on cancellation
        if (this.traceCollector?.isTaskActive()) {
          await this.traceCollector.endTask({ success: false, failureReason: `Cancelled: ${error.message}` });
        } else if (this.traceCollector?.isSessionActive()) {
          await this.traceCollector.endSession({ success: false, failureReason: `Cancelled: ${error.message}` });
        }

        this.emit({
          type: 'completion.after',
          success: false,
          reason: 'cancelled',
          details: `Cancelled: ${error.message}`,
        });
        this.emit({
          type: 'run.after',
          success: false,
          reason: 'cancelled',
          details: `Cancelled: ${error.message}`,
        });

        return {
          success: false,
          response: '',
          error: `Cancelled: ${error.message}`,
          metrics: this.getMetrics(),
          messages: this.state.messages,
          traceId,
          completion: {
            success: false,
            reason: 'cancelled',
            details: `Cancelled: ${error.message}`,
          },
        };
      }

      this.observability?.tracer?.recordError(error);
      await this.observability?.tracer?.endTrace();
      this.state.metrics.failureCount = (this.state.metrics.failureCount ?? 0) + 1;

      this.emit({ type: 'error', error: error.message });
      this.observability?.logger?.error('Agent failed', { error: error.message });
      const completionReason = error.message.includes('failed to complete requested action')
        ? 'incomplete_action' as const
        : 'error' as const;

      // Lesson 26: End trace capture on error
      if (this.traceCollector?.isTaskActive()) {
        await this.traceCollector.endTask({ success: false, failureReason: error.message });
      } else if (this.traceCollector?.isSessionActive()) {
        await this.traceCollector.endSession({ success: false, failureReason: error.message });
      }

      const errorResult = {
        success: false,
        response: '',
        error: error.message,
        metrics: this.getMetrics(),
        messages: this.state.messages,
        traceId,
        completion: {
          success: false,
          reason: completionReason,
          details: error.message,
        },
      };
      this.emit({
        type: 'run.after',
        success: false,
        reason: completionReason,
        details: error.message,
      });
      return errorResult;
    } finally {
      // Dispose cancellation context on completion
      this.cancellation?.disposeContext();
    }
  }

  /**
   * Create and execute a plan for complex tasks.
   */
  private async createAndExecutePlan(task: string): Promise<void> {
    this.observability?.logger?.info('Creating plan for complex task');

    const plan = await this.planning!.createPlan(task, this.provider);
    this.state.plan = plan;

    this.emit({ type: 'planning', plan });

    // Execute each task in the plan
    while (!this.planning!.isPlanComplete()) {
      const currentTask = this.planning!.getNextTask();
      if (!currentTask) break;

      this.planning!.startTask(currentTask.id);
      this.emit({ type: 'task.start', task: currentTask });

      try {
        await this.executeDirectly(currentTask.description);
        this.planning!.completeTask(currentTask.id);
        this.emit({ type: 'task.complete', task: currentTask });
      } catch (_err) {
        this.planning!.failTask(currentTask.id);
        this.observability?.logger?.warn('Plan task failed', { taskId: currentTask.id });
        // Continue with other tasks if possible
      }

      // Check iteration limit (using total iterations to account for parent)
      if (this.getTotalIterations() >= this.config.maxIterations) {
        this.observability?.logger?.warn('Max iterations reached', {
          iteration: this.state.iteration,
          parentIterations: this.parentIterations,
          total: this.getTotalIterations(),
        });
        break;
      }
    }
  }

  /**
   * Run a task in swarm mode using the SwarmOrchestrator.
   */
  private async runSwarm(task: string): Promise<SwarmExecutionResult> {
    if (!this.swarmOrchestrator) {
      throw new Error('Swarm orchestrator not initialized');
    }

    this.observability?.logger?.info('Starting swarm execution', { task: task.slice(0, 100) });
    this.observability?.logger?.info('Starting swarm mode — decomposing task into subtasks...');

    // Forward swarm events to the main agent event system
    const unsubSwarm = this.swarmOrchestrator.subscribe(event => {
      // Forward as a generic agent event for TUI display
      this.emit(event as unknown as import('./types.js').AgentEvent);
    });

    // Bridge events to filesystem for live dashboard
    const { SwarmEventBridge } = await import('./integrations/swarm/swarm-event-bridge.js');
    const bridge = new SwarmEventBridge({ outputDir: '.agent/swarm-live' });
    const unsubBridge = bridge.attach(this.swarmOrchestrator);

    const writeCodeMapSnapshot = (): void => {
      if (!this.codebaseContext) {
        return;
      }
      const repoMap = this.codebaseContext.getRepoMap();
      if (!repoMap) {
        return;
      }

      // Build dependency edges from the dependency graph
      const depEdges: { file: string; imports: string[] }[] = [];
      for (const [file, deps] of repoMap.dependencyGraph) {
        depEdges.push({ file, imports: Array.from(deps) });
      }

      // Build top chunks sorted by importance
      const chunks = Array.from(repoMap.chunks.values());
      const topChunks = chunks
        .sort((a, b) => b.importance - a.importance)
        .slice(0, 100)
        .map(c => ({
          filePath: c.filePath,
          tokenCount: c.tokenCount,
          importance: c.importance,
          type: c.type,
          symbols: c.symbolDetails,
        }));
      const files = chunks.map((chunk) => ({
        filePath: chunk.filePath,
        directory: path.dirname(chunk.filePath) === '.' ? '' : path.dirname(chunk.filePath),
        fileName: path.basename(chunk.filePath),
        tokenCount: chunk.tokenCount,
        importance: chunk.importance,
        type: chunk.type,
        symbols: chunk.symbolDetails,
        inDegree: repoMap.reverseDependencyGraph.get(chunk.filePath)?.size ?? 0,
        outDegree: repoMap.dependencyGraph.get(chunk.filePath)?.size ?? 0,
      }));

      bridge.writeCodeMapSnapshot({
        totalFiles: repoMap.chunks.size,
        totalTokens: repoMap.totalTokens,
        entryPoints: repoMap.entryPoints,
        coreModules: repoMap.coreModules,
        dependencyEdges: depEdges,
        files,
        topChunks,
      });
    };
    let codeMapRefreshInFlight = false;
    let codeMapRefreshTimer: ReturnType<typeof setTimeout> | null = null;
    const refreshAndWriteCodeMapSnapshot = async (): Promise<void> => {
      if (!this.codebaseContext || codeMapRefreshInFlight) {
        return;
      }
      codeMapRefreshInFlight = true;
      try {
        // Re-analyze from disk so snapshots include newly created files during swarm execution.
        this.codebaseContext.clearCache();
        await this.codebaseContext.analyze();
        writeCodeMapSnapshot();
      } catch {
        // Best effort
      } finally {
        codeMapRefreshInFlight = false;
      }
    };

    // Write observability snapshots to swarm-live/ on relevant events
    const unsubSnapshots = this.swarmOrchestrator.subscribe(event => {
      // Write codemap snapshot when tasks are loaded.
      if (event.type === 'swarm.tasks.loaded' && this.codebaseContext) {
        try {
          writeCodeMapSnapshot();
        } catch {
          // Best effort — don't crash the swarm
        }
      }
      // Refresh codemap after each completed wave to avoid stale 0-file snapshots.
      if (event.type === 'swarm.wave.complete' && this.codebaseContext) {
        void refreshAndWriteCodeMapSnapshot();
      }
      if (event.type === 'swarm.task.completed' && this.codebaseContext) {
        if (codeMapRefreshTimer) {
          clearTimeout(codeMapRefreshTimer);
        }
        codeMapRefreshTimer = setTimeout(() => {
          void refreshAndWriteCodeMapSnapshot();
        }, 1200);
      }

      // Write blackboard.json on wave completion or task completion
      if ((event.type === 'swarm.wave.complete' || event.type === 'swarm.task.completed') && this.blackboard) {
        try {
          const findings = this.blackboard.getAllFindings();
          bridge.writeBlackboardSnapshot({
            findings: findings.map(f => ({
              id: f.id ?? '',
              topic: f.topic ?? '',
              type: f.type ?? '',
              agentId: f.agentId ?? '',
              confidence: f.confidence ?? 0,
              content: (f.content ?? '').slice(0, 500),
            })),
            claims: [],
            updatedAt: new Date().toISOString(),
          });
        } catch {
          // Best effort
        }
      }

      // Write budget-pool.json on budget updates
      if (event.type === 'swarm.budget.update' && this.budgetPool) {
        try {
          const stats = this.budgetPool.getStats();
          bridge.writeBudgetPoolSnapshot({
            poolTotal: stats.totalTokens,
            poolUsed: stats.tokensUsed,
            poolRemaining: stats.tokensRemaining,
            allocations: [],
            updatedAt: new Date().toISOString(),
          });
        } catch {
          // Best effort
        }
      }
    });

    // Bridge swarm events into JSONL trace pipeline
    const traceCollector = this.traceCollector;
    let unsubTrace: (() => void) | undefined;
    if (traceCollector) {
      unsubTrace = this.swarmOrchestrator.subscribe(event => {
        switch (event.type) {
          case 'swarm.start':
            traceCollector.record({
              type: 'swarm.start',
              data: { taskCount: event.taskCount, config: event.config },
            });
            break;
          case 'swarm.tasks.loaded':
            traceCollector.record({
              type: 'swarm.decomposition',
              data: {
                tasks: event.tasks.map(t => ({
                  id: t.id,
                  description: t.description.slice(0, 200),
                  type: t.type,
                  wave: t.wave,
                  deps: t.dependencies,
                })),
                totalWaves: Math.max(...event.tasks.map(t => t.wave), 0) + 1,
              },
            });
            break;
          case 'swarm.wave.start':
            traceCollector.record({
              type: 'swarm.wave',
              data: { phase: 'start', wave: event.wave, taskCount: event.taskCount },
            });
            break;
          case 'swarm.wave.complete':
            traceCollector.record({
              type: 'swarm.wave',
              data: {
                phase: 'complete',
                wave: event.wave,
                taskCount: event.completed + event.failed + (event.skipped ?? 0),
                completed: event.completed,
                failed: event.failed,
              },
            });
            break;
          case 'swarm.task.dispatched':
            traceCollector.record({
              type: 'swarm.task',
              data: { phase: 'dispatched', taskId: event.taskId, model: event.model },
            });
            break;
          case 'swarm.task.completed':
            traceCollector.record({
              type: 'swarm.task',
              data: {
                phase: 'completed',
                taskId: event.taskId,
                tokensUsed: event.tokensUsed,
                costUsed: event.costUsed,
                qualityScore: event.qualityScore,
              },
            });
            break;
          case 'swarm.task.failed':
            traceCollector.record({
              type: 'swarm.task',
              data: { phase: 'failed', taskId: event.taskId, error: event.error },
            });
            break;
          case 'swarm.task.skipped':
            traceCollector.record({
              type: 'swarm.task',
              data: { phase: 'skipped', taskId: event.taskId, reason: event.reason },
            });
            break;
          case 'swarm.quality.rejected':
            traceCollector.record({
              type: 'swarm.quality',
              data: { taskId: event.taskId, score: event.score, feedback: event.feedback },
            });
            break;
          case 'swarm.budget.update':
            traceCollector.record({
              type: 'swarm.budget',
              data: {
                tokensUsed: event.tokensUsed,
                tokensTotal: event.tokensTotal,
                costUsed: event.costUsed,
                costTotal: event.costTotal,
              },
            });
            break;
          case 'swarm.verify.start':
            traceCollector.record({
              type: 'swarm.verification',
              data: { phase: 'start', description: `${event.stepCount} verification steps` },
            });
            break;
          case 'swarm.verify.step':
            traceCollector.record({
              type: 'swarm.verification',
              data: {
                phase: 'step',
                stepIndex: event.stepIndex,
                description: event.description,
                passed: event.passed,
              },
            });
            break;
          case 'swarm.verify.complete':
            traceCollector.record({
              type: 'swarm.verification',
              data: {
                phase: 'complete',
                passed: event.result.passed,
                summary: event.result.summary,
              },
            });
            break;
          case 'swarm.orchestrator.llm':
            traceCollector.record({
              type: 'swarm.orchestrator.llm',
              data: { model: event.model, purpose: event.purpose, tokens: event.tokens, cost: event.cost },
            });
            break;
          case 'swarm.wave.allFailed':
            traceCollector.record({
              type: 'swarm.wave.allFailed',
              data: { wave: event.wave },
            });
            break;
          case 'swarm.phase.progress':
            traceCollector.record({
              type: 'swarm.phase.progress',
              data: { phase: event.phase, message: event.message },
            });
            break;
          case 'swarm.complete':
            traceCollector.record({
              type: 'swarm.complete',
              data: {
                stats: {
                  totalTasks: event.stats.totalTasks,
                  completedTasks: event.stats.completedTasks,
                  failedTasks: event.stats.failedTasks,
                  totalTokens: event.stats.totalTokens,
                  totalCost: event.stats.totalCost,
                  totalDuration: event.stats.totalDurationMs,
                },
              },
            });
            break;
        }
      });
    }

    try {
      // Ensure codebase context is analyzed before decomposition so repo map is available
      if (this.codebaseContext && !this.codebaseContext.getRepoMap()) {
        try {
          await this.codebaseContext.analyze();
        } catch {
          // non-fatal — decomposer will work without codebase context
        }
      }

      // Write codemap snapshot immediately so dashboard can render even if decomposition fails.
      try {
        writeCodeMapSnapshot();
      } catch {
        // Best effort
      }

      const result = await this.swarmOrchestrator.execute(task);

      // Populate task DAG for dashboard after execution
      bridge.setTasks(result.tasks);

      this.observability?.logger?.info('Swarm execution complete', {
        success: result.success,
        tasks: result.stats.totalTasks,
        completed: result.stats.completedTasks,
        tokens: result.stats.totalTokens,
        cost: result.stats.totalCost,
      });

      return result;
    } finally {
      if (codeMapRefreshTimer) {
        clearTimeout(codeMapRefreshTimer);
      }
      unsubTrace?.();
      unsubSnapshots();
      unsubBridge();
      bridge.close();
      unsubSwarm();
    }
  }

  /**
   * Execute a task directly without planning (delegates to core/execution-loop).
   */
  private async executeDirectly(task: string): Promise<Awaited<ReturnType<typeof coreExecuteDirectly>>> {
    const messages = await this.buildMessages(task);
    const ctx = this.buildContext();
    const mutators = this.buildMutators();
    return coreExecuteDirectly(task, messages, ctx, mutators);
  }

  /**
   * Build messages for LLM call.
   *
   * Uses cache-aware system prompt building (Trick P) when contextEngineering
   * is available, ensuring static content is ordered for optimal KV-cache reuse.
   */
  private async buildMessages(task: string): Promise<Message[]> {
    return doBuildMessages(this as unknown as MessageBuilderDeps, task);
  }

  // ===========================================================================
  // CONTEXT BUILDERS — Bridge private fields to extracted core modules
  // ===========================================================================

  private buildContext(): import('./core/types.js').AgentContext {
    return {
      config: this.config, agentId: this.agentId, provider: this.provider,
      tools: this.tools, state: this.state,
      modeManager: this.modeManager, pendingPlanManager: this.pendingPlanManager,
      hooks: this.hooks, economics: this.economics, cancellation: this.cancellation,
      resourceManager: this.resourceManager, safety: this.safety,
      observability: this.observability, contextEngineering: this.contextEngineering,
      traceCollector: this.traceCollector, executionPolicy: this.executionPolicy,
      routing: this.routing, planning: this.planning, memory: this.memory,
      react: this.react, blackboard: this.blackboard, fileCache: this.fileCache,
      budgetPool: this.budgetPool, taskManager: this.taskManager, store: this.store,
      codebaseContext: this.codebaseContext, learningStore: this.learningStore,
      compactor: this.compactor, autoCompactionManager: this.autoCompactionManager,
      workLog: this.workLog, verificationGate: this.verificationGate,
      agentRegistry: this.agentRegistry, toolRecommendation: this.toolRecommendation,
      selfImprovement: this.selfImprovement, subagentOutputStore: this.subagentOutputStore,
      autoCheckpointManager: this.autoCheckpointManager, injectionBudget: this.injectionBudget,
      skillManager: this.skillManager, semanticCache: this.semanticCache,
      lspManager: this.lspManager, threadManager: this.threadManager,
      interactivePlanner: this.interactivePlanner, recursiveContext: this.recursiveContext,
      fileChangeTracker: this.fileChangeTracker, capabilitiesRegistry: this.capabilitiesRegistry,
      rules: this.rules, stateMachine: this.stateMachine,
      lastComplexityAssessment: this.lastComplexityAssessment,
      cacheableSystemBlocks: this.cacheableSystemBlocks,
      parentIterations: this.parentIterations,
      externalCancellationToken: this.externalCancellationToken,
      wrapupRequested: this.wrapupRequested, wrapupReason: this.wrapupReason,
      compactionPending: this.compactionPending,
      sharedContextState: this._sharedContextState,
      sharedEconomicsState: this._sharedEconomicsState,
      spawnedTasks: this.spawnedTasks, toolResolver: this.toolResolver,
      emit: (event) => this.emit(event),
      addTool: (tool) => this.addTool(tool),
      getMaxContextTokens: () => this.getMaxContextTokens(),
      getTotalIterations: () => this.getTotalIterations(),
    };
  }

  private buildMutators(): import('./core/types.js').AgentContextMutators {
    return {
      setBudgetPool: (pool) => { this.budgetPool = pool; },
      setCacheableSystemBlocks: (blocks) => { this.cacheableSystemBlocks = blocks; },
      setCompactionPending: (pending) => { this.compactionPending = pending; },
      setWrapupRequested: (requested) => { this.wrapupRequested = requested; },
      setLastComplexityAssessment: (a) => { this.lastComplexityAssessment = a; },
      setExternalCancellationToken: (t) => { this.externalCancellationToken = t; },
    };
  }

  private createSubAgentFactory(): import('./core/types.js').SubAgentFactory {
    return (config) => new ProductionAgent(config) as unknown as import('./core/types.js').SubAgentInstance;
  }

  /**
   * Execute an async callback while excluding wall-clock wait time from duration budgeting.
   * Used for external waits such as approval dialogs and delegation confirmation.
   */
  private async withPausedDuration<T>(fn: () => Promise<T>): Promise<T> {
    this.economics?.pauseDuration();
    try {
      return await fn();
    } finally {
      this.economics?.resumeDuration();
    }
  }

  /**
   * Get recently modified file paths from the file change tracker.
   * Returns paths of files modified in this session (not undone).
   */
  private getRecentlyModifiedFiles(limit: number = 5): string[] {
    if (!this.fileChangeTracker) return [];

    try {
      const changes = this.fileChangeTracker.getChanges();
      const recentFiles = new Set<string>();

      // Iterate in reverse to get most recent first
      for (let i = changes.length - 1; i >= 0 && recentFiles.size < limit; i--) {
        const change = changes[i];
        if (!change.isUndone) {
          recentFiles.add(change.filePath);
        }
      }

      return Array.from(recentFiles);
    } catch {
      return [];
    }
  }

  /**
   * Select relevant code synchronously using cached repo analysis.
   * Uses LSP-enhanced selection when available to boost related files.
   * Returns empty result if analysis hasn't been run yet.
   */
  private selectRelevantCodeSync(task: string, maxTokens: number): {
    chunks: Array<{ filePath: string; content: string; tokenCount: number; importance: number }>;
    totalTokens: number;
    lspBoostedFiles?: string[];
  } {
    if (!this.codebaseContext) {
      return { chunks: [], totalTokens: 0 };
    }

    const repoMap = this.codebaseContext.getRepoMap();
    if (!repoMap) {
      return { chunks: [], totalTokens: 0 };
    }

    // Get recently modified files for LSP-enhanced selection
    const recentFiles = this.getRecentlyModifiedFiles();
    const priorityFileSet = new Set(recentFiles);

    // LSP-related files (files that reference or are referenced by recent files)
    const lspRelatedFiles = new Set<string>();
    if (this.codebaseContext.hasActiveLSP() && recentFiles.length > 0) {
      // Use dependency graph as a synchronous proxy for LSP relationships
      for (const file of recentFiles) {
        // Files that this file depends on
        const deps = repoMap.dependencyGraph.get(file);
        if (deps) {
          for (const dep of deps) {
            lspRelatedFiles.add(dep);
          }
        }
        // Files that depend on this file
        const reverseDeps = repoMap.reverseDependencyGraph.get(file);
        if (reverseDeps) {
          for (const dep of reverseDeps) {
            lspRelatedFiles.add(dep);
          }
        }
      }
    }

    // Get all chunks and score by relevance
    const allChunks = Array.from(repoMap.chunks.values());
    const taskLower = task.toLowerCase();
    const taskWords = taskLower.split(/\s+/).filter((w) => w.length > 2);

    // Score chunks by task relevance
    const scored = allChunks.map((chunk) => {
      let relevance = 0;

      // Check file path
      const pathLower = chunk.filePath.toLowerCase();
      for (const word of taskWords) {
        if (pathLower.includes(word)) relevance += 0.3;
      }

      // Check symbols
      for (const symbol of chunk.symbols) {
        const symbolLower = symbol.toLowerCase();
        for (const word of taskWords) {
          if (symbolLower.includes(word) || word.includes(symbolLower)) {
            relevance += 0.2;
          }
        }
      }

      // Combine with base importance
      let combinedScore = chunk.importance * 0.4 + Math.min(relevance, 1) * 0.6;

      // Boost recently modified files (highest priority)
      if (priorityFileSet.has(chunk.filePath)) {
        combinedScore = Math.min(1.0, combinedScore + 0.4);
      }
      // Boost LSP-related files (files connected to recent edits)
      else if (lspRelatedFiles.has(chunk.filePath)) {
        combinedScore = Math.min(1.0, combinedScore + 0.25);
      }

      return { chunk, score: combinedScore };
    });

    // Sort by score and select within budget
    scored.sort((a, b) => b.score - a.score);

    const selected: Array<{ filePath: string; content: string; tokenCount: number; importance: number }> = [];
    let totalTokens = 0;
    const boostedFiles: string[] = [];

    for (const { chunk, score } of scored) {
      if (score < 0.1) continue; // Skip very low relevance
      if (totalTokens + chunk.tokenCount > maxTokens) continue;

      selected.push({
        filePath: chunk.filePath,
        content: chunk.content,
        tokenCount: chunk.tokenCount,
        importance: score,
      });
      totalTokens += chunk.tokenCount;

      // Track which files were boosted by LSP/dependency relationships
      if (lspRelatedFiles.has(chunk.filePath)) {
        boostedFiles.push(chunk.filePath);
      }
    }

    return {
      chunks: selected,
      totalTokens,
      lspBoostedFiles: boostedFiles.length > 0 ? boostedFiles : undefined,
    };
  }

  /**
   * Analyze the codebase (async). Call this once at startup for optimal performance.
   */
  async analyzeCodebase(root?: string): Promise<void> {
    if (this.codebaseContext) {
      await this.codebaseContext.analyze(root);
    }
  }

  /**
   * Emit an event.
   */
  private emit(event: AgentEvent): void {
    this.hooks?.emit(event);
  }


  /**
   * Update memory statistics.
   * Memory stats are retrieved via memory manager, not stored in state.
   */
  private updateMemoryStats(): void {
    // Memory stats are accessed via getMetrics() when needed
    // This method exists for hook/extension points
    this.memory?.getStats();
  }

  /**
   * Get current metrics.
   */
  getMetrics(): AgentResult['metrics'] {
    if (this.observability?.metrics) {
      const observed = this.observability.metrics.getMetrics();
      return {
        ...observed,
        successCount: this.state.metrics.successCount ?? 0,
        failureCount: this.state.metrics.failureCount ?? 0,
        cancelCount: this.state.metrics.cancelCount ?? 0,
        retryCount: this.state.metrics.retryCount ?? 0,
      };
    }
    return this.state.metrics;
  }

  getResilienceConfig(): ProductionAgentConfig['resilience'] {
    return this.config.resilience;
  }

  /**
   * Get current state.
   */
  getState(): AgentState {
    return { ...this.state };
  }

  /**
   * Get shared state stats for TUI visibility.
   * Returns null when not in a swarm context.
   */
  getSharedStats(): { context: { failures: number; references: number }; economics: { fingerprints: number; globalLoops: string[] } } | null {
    if (!this._sharedContextState) return null;
    return {
      context: this._sharedContextState.getStats(),
      economics: this._sharedEconomicsState?.getStats() ?? { fingerprints: 0, globalLoops: [] },
    };
  }

  /**
   * Get the maximum context tokens for this agent's model.
   * Priority: user config > OpenRouter API > hardcoded ModelRegistry > 200K default
   */
  getMaxContextTokens(): number {
    if (this.config.maxContextTokens) {
      return this.config.maxContextTokens;
    }
    // Try OpenRouter API cache (has real data for GLM-4.7, etc.)
    const openRouterContext = getModelContextLength(this.config.model || '');
    if (openRouterContext) {
      return openRouterContext;
    }
    // Fall back to hardcoded registry
    const registryInfo = modelRegistry.getModel(this.config.model || '');
    if (registryInfo?.capabilities?.maxContextTokens) {
      return registryInfo.capabilities.maxContextTokens;
    }
    // Default
    return 200000;
  }

  /**
   * Estimate tokens used by the system prompt (codebase context, tools, rules).
   * Used by TUI to display accurate context % that includes system overhead.
   */
  getSystemPromptTokenEstimate(): number {
    if (this.lastSystemPromptLength > 0) {
      return Math.ceil(this.lastSystemPromptLength / 3.2);
    }
    return 0;
  }

  /**
   * Get the trace collector (Lesson 26).
   * Returns null if trace capture is not enabled.
   */
  getTraceCollector(): TraceCollector | null {
    return this.traceCollector;
  }

  /**
   * Set a trace collector for this agent.
   * Used for subagents to share the parent's trace collector (with subagent context).
   */
  setTraceCollector(collector: TraceCollector): void {
    this.traceCollector = collector;
    if (this.codebaseContext) {
      this.codebaseContext.traceCollector = collector;
    }
  }

  /**
   * Get the learning store for cross-session learning.
   * Returns null if learning store is not enabled.
   */
  getLearningStore(): LearningStore | null {
    return this.learningStore;
  }

  /**
   * Get the auto-compaction manager.
   * Returns null if compaction is not enabled.
   */
  getAutoCompactionManager(): AutoCompactionManager | null {
    return this.autoCompactionManager;
  }

  /**
   * Get the file change tracker for undo capability.
   * Returns null if file change tracking is not enabled.
   */
  getFileChangeTracker(): FileChangeTracker | null {
    return this.fileChangeTracker;
  }

  /**
   * Record a file change for potential undo.
   * No-op if file change tracking is not enabled.
   *
   * @param params - Change details
   * @returns Change ID if tracked, -1 otherwise
   */
  async trackFileChange(params: {
    filePath: string;
    operation: 'create' | 'write' | 'edit' | 'delete';
    contentBefore?: string;
    contentAfter?: string;
    toolCallId?: string;
  }): Promise<number> {
    return doTrackFileChange(this as unknown as SessionApiDeps, params);
  }

  /**
   * Undo the last change to a specific file.
   * Returns null if file change tracking is not enabled.
   */
  async undoLastFileChange(filePath: string): Promise<import('./integrations/index.js').UndoResult | null> {
    return doUndoLastFileChange(this as unknown as SessionApiDeps, filePath);
  }

  /**
   * Undo all changes in the current turn.
   * Returns null if file change tracking is not enabled.
   */
  async undoCurrentTurn(): Promise<import('./integrations/index.js').UndoResult[] | null> {
    return doUndoCurrentTurn(this as unknown as SessionApiDeps);
  }

  /**
   * Subscribe to events.
   */
  subscribe(listener: AgentEventListener): () => void {
    if (this.hooks) {
      return this.hooks.subscribe(listener);
    }
    return () => {};
  }

  /**
   * Reset agent state.
   */
  reset(): void {
    doReset(this as unknown as SessionApiDeps);
  }

  /**
   * Load messages from a previous session.
   * @deprecated Use loadState() for full state restoration
   */
  loadMessages(messages: Message[]): void {
    doLoadMessages(this as unknown as SessionApiDeps, messages);
  }

  /**
   * Serializable state for checkpoints (excludes non-serializable fields).
   */
  getSerializableState(): {
    messages: Message[];
    iteration: number;
    metrics: AgentMetrics;
    plan?: AgentPlan;
    memoryContext?: string[];
  } {
    return doGetSerializableState(this as unknown as SessionApiDeps);
  }

  /**
   * Validate checkpoint data before loading.
   * Returns validation result with errors and warnings.
   */
  private validateCheckpoint(data: unknown): {
    valid: boolean;
    errors: string[];
    warnings: string[];
    sanitized: {
      messages: Message[];
      iteration: number;
      metrics?: Partial<AgentMetrics>;
      plan?: AgentPlan;
      memoryContext?: string[];
    } | null;
  } {
    return doValidateCheckpoint(data);
  }

  /**
   * Load full state from a checkpoint.
   * Restores messages, iteration, metrics, plan, and memory context.
   * Validates checkpoint data before loading to prevent corrupted state.
   */
  loadState(savedState: {
    messages: Message[];
    iteration?: number;
    metrics?: Partial<AgentMetrics>;
    plan?: AgentPlan;
    memoryContext?: string[];
  }): void {
    doLoadState(this as unknown as SessionApiDeps, savedState);
  }

  /**
   * Add a tool dynamically.
   */
  addTool(tool: ToolDefinition): void {
    this.tools.set(tool.name, tool);
    this.observability?.logger?.debug('Tool added', { tool: tool.name });
  }

  /**
   * Remove a tool.
   */
  removeTool(name: string): void {
    this.tools.delete(name);
    this.observability?.logger?.debug('Tool removed', { tool: name });
  }

  /**
   * Compact tool outputs to save context.
   * Called after model produces a response - replaces verbose tool outputs
   * with compact summaries since the model has already "consumed" them.
   */
  private compactToolOutputs(): void {
    const COMPACT_PREVIEW_LENGTH = 200; // Keep first 200 chars as preview
    const MAX_PRESERVED_EXPENSIVE_RESULTS = 6;
    let compactedCount = 0;
    let savedChars = 0;
    const preservedExpensiveIndexes = this.state.messages
      .map((msg, index) => ({ msg, index }))
      .filter(({ msg }) =>
        msg.role === 'tool' && msg.metadata?.preserveFromCompaction === true
      )
      .map(({ index }) => index);
    const preserveSet = new Set(
      preservedExpensiveIndexes.slice(-MAX_PRESERVED_EXPENSIVE_RESULTS)
    );

    for (let i = 0; i < this.state.messages.length; i++) {
      const msg = this.state.messages[i];
      if (msg.role === 'tool' && msg.content && msg.content.length > COMPACT_PREVIEW_LENGTH * 2) {
        if (msg.metadata?.preserveFromCompaction === true && preserveSet.has(i)) {
          continue;
        }
        const originalLength = msg.content.length;
        const preview = msg.content.slice(0, COMPACT_PREVIEW_LENGTH).replace(/\n/g, ' ');
        msg.content = `[${preview}...] (${originalLength} chars, compacted)`;
        savedChars += originalLength - msg.content.length;
        compactedCount++;
      }
    }

    if (compactedCount > 0 && process.env.DEBUG) {
      log.debug('Compacted tool outputs', { compactedCount, savedTokens: Math.round(savedChars / 4) });
    }
  }

  /**
   * Estimate total tokens in a message array.
   * Uses ~4 chars per token heuristic for fast estimation.
   */
  private estimateContextTokens(messages: Message[]): number {
    let totalChars = 0;
    for (const msg of messages) {
      if (msg.content) {
        totalChars += msg.content.length;
      }
      // Account for tool calls in assistant messages
      if (msg.toolCalls) {
        for (const tc of msg.toolCalls) {
          totalChars += tc.name.length;
          totalChars += JSON.stringify(tc.arguments).length;
        }
      }
    }
    return Math.ceil(totalChars / 4); // ~4 chars per token
  }

  /**
   * Extract a requested markdown artifact filename from a task prompt.
   * Returns null when no explicit artifact requirement is detected.
   */
  private extractRequestedArtifact(task: string): string | null {
    const markdownArtifactMatch = task.match(/(?:write|save|create)[^.\n]{0,120}\b([A-Za-z0-9._/-]+\.md)\b/i);
    return markdownArtifactMatch?.[1] ?? null;
  }

  /**
   * Check whether a requested artifact appears to be missing based on executed tools.
   */
  private isRequestedArtifactMissing(
    requestedArtifact: string | null,
    executedToolNames: Set<string>
  ): boolean {
    if (!requestedArtifact) {
      return false;
    }

    const artifactWriteTools = ['write_file', 'edit_file', 'apply_patch', 'append_file'];
    return !artifactWriteTools.some(toolName => executedToolNames.has(toolName));
  }

  private getOpenTasksSummary(): OpenTaskSummary | undefined {
    if (!this.taskManager) {
      return undefined;
    }
    const tasks = this.taskManager.list();
    const pending = tasks.filter(t => t.status === 'pending').length;
    const inProgress = tasks.filter(t => t.status === 'in_progress').length;
    const blocked = tasks.filter(t => t.status === 'pending' && this.taskManager?.isBlocked(t.id)).length;
    return { pending, inProgress, blocked };
  }

  private reconcileStaleTasks(reason: string): void {
    if (!this.taskManager) return;
    const staleAfterMs = typeof this.config.resilience === 'object'
      ? (this.config.resilience.taskLeaseStaleMs ?? 5 * 60 * 1000)
      : 5 * 60 * 1000;
    const recovered = this.taskManager.reconcileStaleInProgress({
      staleAfterMs,
      reason,
    });
    if (recovered.reconciled > 0) {
      this.observability?.logger?.info('Recovered stale task leases', {
        reason,
        recovered: recovered.reconciled,
      });
    }
  }

  /**
   * Get audit log (if human-in-loop is enabled).
   */
  getAuditLog(): unknown[] {
    return this.safety?.humanInLoop?.getAuditLog() || [];
  }

  // =========================================================================
  // MULTI-AGENT METHODS (Lesson 17)
  // =========================================================================

  /**
   * Run a task with a multi-agent team.
   * Requires multiAgent to be enabled in config.
   */
  async runWithTeam(task: TeamTask, roles: AgentRole[]): Promise<TeamResult> {
    if (!this.multiAgent) {
      throw new Error('Multi-agent not enabled. Enable it in config to use runWithTeam()');
    }

    this.observability?.logger?.info('Running with team', { task: task.goal, roles: roles.map(r => r.name) });

    // Register roles if not already registered
    for (const role of roles) {
      this.multiAgent.registerRole(role);
    }

    // Set up event forwarding (unsubscribe after operation to prevent memory leaks)
    const unsubMultiAgent = this.multiAgent.on(event => {
      switch (event.type) {
        case 'agent.spawn':
          this.emit({ type: 'multiagent.spawn', agentId: event.agentId, role: event.role });
          break;
        case 'agent.complete':
          this.emit({ type: 'multiagent.complete', agentId: event.agentId, success: event.result.success });
          break;
        case 'consensus.start':
          this.emit({ type: 'consensus.start', strategy: event.strategy });
          break;
        case 'consensus.reached':
          this.emit({ type: 'consensus.reached', agreed: event.decision.agreed, result: event.decision.result });
          break;
      }
    });

    try {
      const result = await this.multiAgent.runWithTeam(task, {
        roles,
        consensusStrategy: this.config.multiAgent && isFeatureEnabled(this.config.multiAgent)
          ? this.config.multiAgent.consensusStrategy || 'voting'
          : 'voting',
        communicationMode: 'broadcast',
      });

      return result;
    } finally {
      unsubMultiAgent();
    }
  }

  /**
   * Add a role to the multi-agent manager.
   */
  addRole(role: AgentRole): void {
    if (!this.multiAgent) {
      throw new Error('Multi-agent not enabled');
    }
    this.multiAgent.registerRole(role);
  }

  // =========================================================================
  // REACT METHODS (Lesson 18)
  // =========================================================================

  /**
   * Run a task using the ReAct (Reasoning + Acting) pattern.
   * Provides explicit reasoning traces.
   */
  async runWithReAct(task: string): Promise<ReActTrace> {
    if (!this.react) {
      throw new Error('ReAct not enabled. Enable it in config to use runWithReAct()');
    }

    this.observability?.logger?.info('Running with ReAct', { task });

    // Set up event forwarding (unsubscribe after operation to prevent memory leaks)
    const unsubReact = this.react.on(event => {
      switch (event.type) {
        case 'react.thought':
          this.emit({ type: 'react.thought', step: event.step, thought: event.thought });
          break;
        case 'react.action':
          this.emit({ type: 'react.action', step: event.step, action: event.action.tool, input: event.action.input });
          break;
        case 'react.observation':
          this.emit({ type: 'react.observation', step: event.step, observation: event.observation });
          break;
        case 'react.answer':
          this.emit({ type: 'react.answer', answer: event.answer });
          break;
      }
    });

    try {
      const trace = await this.react.run(task);

      // Store trace in memory if available
      if (this.memory && trace.finalAnswer) {
        this.memory.storeConversation([
          { role: 'user', content: task },
          { role: 'assistant', content: trace.finalAnswer },
        ]);
      }

      return trace;
    } finally {
      unsubReact();
    }
  }

  /**
   * Get the ReAct trace formatted as a string.
   */
  formatReActTrace(trace: ReActTrace): string {
    if (!this.react) {
      throw new Error('ReAct not enabled');
    }
    return this.react.formatTrace(trace);
  }

  // =========================================================================
  // EXECUTION POLICY METHODS (Lesson 23)
  // =========================================================================

  /**
   * Create a permission grant for a tool.
   * Allows temporary, scoped permissions.
   */
  createPermissionGrant(options: {
    toolName: string;
    argPattern?: Record<string, unknown>;
    grantedBy?: 'user' | 'system' | 'inferred';
    expiresAt?: Date;
    maxUsages?: number;
    reason?: string;
  }): string {
    if (!this.executionPolicy) {
      throw new Error('Execution policies not enabled');
    }
    const grant = this.executionPolicy.createGrant({
      toolName: options.toolName,
      argPattern: options.argPattern,
      grantedBy: options.grantedBy || 'user',
      expiresAt: options.expiresAt,
      maxUsages: options.maxUsages,
      reason: options.reason,
    });
    this.emit({ type: 'grant.created', grantId: grant.id, tool: options.toolName });
    return grant.id;
  }

  /**
   * Revoke a permission grant.
   */
  revokePermissionGrant(grantId: string): boolean {
    if (!this.executionPolicy) {
      throw new Error('Execution policies not enabled');
    }
    return this.executionPolicy.revokeGrant(grantId);
  }

  /**
   * Get active permission grants.
   */
  getActiveGrants(): unknown[] {
    if (!this.executionPolicy) {
      return [];
    }
    return this.executionPolicy.getActiveGrants();
  }

  // =========================================================================
  // ECONOMICS METHODS (Token Budget)
  // =========================================================================

  /**
   * Get current budget usage.
   */
  getBudgetUsage(): {
    tokens: number;
    cost: number;
    duration: number;
    iterations: number;
    percentUsed: number;
  } | null {
    if (!this.economics) return null;

    const usage = this.economics.getUsage();
    const budget = this.economics.getBudget();

    return {
      tokens: usage.tokens,
      cost: usage.cost,
      duration: usage.duration,
      iterations: usage.iterations,
      percentUsed: Math.max(
        (usage.tokens / budget.maxTokens) * 100,
        (usage.cost / budget.maxCost) * 100,
        (usage.duration / budget.maxDuration) * 100
      ),
    };
  }

  /**
   * Get current budget limits.
   */
  getBudgetLimits(): {
    maxTokens: number;
    maxCost: number;
    maxDuration: number;
    maxIterations: number;
  } | null {
    if (!this.economics) return null;
    const budget = this.economics.getBudget();
    return {
      maxTokens: budget.maxTokens,
      maxCost: budget.maxCost,
      maxDuration: budget.maxDuration,
      maxIterations: budget.maxIterations,
    };
  }

  /**
   * Get progress tracking info.
   */
  getProgress(): {
    filesRead: number;
    filesModified: number;
    commandsRun: number;
    isStuck: boolean;
  } | null {
    if (!this.economics) return null;
    return this.economics.getProgress();
  }

  /**
   * Get actual file paths modified during this agent's session.
   */
  getModifiedFilePaths(): string[] {
    return this.economics?.getModifiedFilePaths() ?? [];
  }

  /**
   * Extend the budget limits.
   */
  extendBudget(extension: Partial<ExecutionBudget>): void {
    if (this.economics) {
      this.economics.extendBudget(extension);
    }
  }

  // =========================================================================
  // THREAD MANAGEMENT METHODS (Lesson 24)
  // =========================================================================

  /**
   * Create a checkpoint of the current state.
   * Useful before risky operations.
   */
  createCheckpoint(label?: string): Checkpoint {
    if (!this.threadManager) {
      throw new Error('Thread management not enabled. Enable it in config to use createCheckpoint()');
    }

    // CRITICAL: Sync current state.messages to threadManager before checkpoint
    // The run() method adds messages directly to this.state.messages but doesn't sync
    // to threadManager, so thread.messages would be empty without this sync
    const thread = this.threadManager.getActiveThread();
    thread.messages = [...this.state.messages];

    const checkpoint = this.threadManager.createCheckpoint({
      label,
      agentState: this.state,
    });

    this.emit({ type: 'checkpoint.created', checkpointId: checkpoint.id, label });
    this.observability?.logger?.info('Checkpoint created', { checkpointId: checkpoint.id, label });

    return checkpoint;
  }

  /**
   * Restore from a checkpoint.
   */
  restoreCheckpoint(checkpointId: string): boolean {
    if (!this.threadManager) {
      throw new Error('Thread management not enabled');
    }

    const state = this.threadManager.restoreCheckpoint(checkpointId);
    if (!state) {
      return false;
    }

    // Restore agent state
    this.state.messages = state.messages;
    this.state.metrics = state.metrics;
    this.state.iteration = state.iteration;

    this.emit({ type: 'checkpoint.restored', checkpointId });
    this.observability?.logger?.info('Checkpoint restored', { checkpointId });

    return true;
  }

  /**
   * Rollback the conversation by N messages.
   */
  rollback(steps: number): boolean {
    if (!this.threadManager) {
      throw new Error('Thread management not enabled');
    }

    // Sync state.messages to threadManager before rollback (messages may have been added directly)
    const thread = this.threadManager.getActiveThread();
    thread.messages = [...this.state.messages];

    const success = this.threadManager.rollback(steps);
    if (success) {
      // Sync back to state
      this.state.messages = this.threadManager.getMessages();
      this.emit({ type: 'rollback', steps });
      this.observability?.logger?.info('Rolled back', { steps });
    }

    return success;
  }

  /**
   * Fork the current conversation into a new branch.
   * Useful for exploring alternatives.
   */
  fork(name: string): string {
    if (!this.threadManager) {
      throw new Error('Thread management not enabled');
    }

    const thread = this.threadManager.fork({ name });
    this.emit({ type: 'thread.forked', threadId: thread.id, parentId: thread.parentId || 'main' });
    this.observability?.logger?.info('Thread forked', { threadId: thread.id, name });

    return thread.id;
  }

  /**
   * Switch to a different thread.
   */
  switchThread(threadId: string): boolean {
    if (!this.threadManager) {
      throw new Error('Thread management not enabled');
    }

    const fromId = this.threadManager.getActiveThread().id;
    const success = this.threadManager.switchThread(threadId);

    if (success) {
      this.state.messages = this.threadManager.getMessages();
      this.emit({ type: 'thread.switched', fromId, toId: threadId });
    }

    return success;
  }

  /**
   * Get all threads.
   */
  getAllThreads(): unknown[] {
    if (!this.threadManager) {
      return [];
    }
    return this.threadManager.getAllThreads();
  }

  /**
   * Get checkpoints for the current thread.
   */
  getCheckpoints(): Checkpoint[] {
    if (!this.threadManager) {
      return [];
    }
    return this.threadManager.getThreadCheckpoints();
  }

  /**
   * Automatically create checkpoint if enabled in config.
   * Safe to call after each Q&A cycle - handles all checks internally.
   * @param force - If true, bypasses frequency check and always creates checkpoint
   * @returns The created checkpoint, or null if conditions not met
   */
  autoCheckpoint(force = false): Checkpoint | null {
    // Check if thread management is enabled
    if (!this.threadManager) {
      return null;
    }

    // Check if auto-checkpoint is enabled
    const threadsConfig = this.config.threads;
    if (!threadsConfig || typeof threadsConfig === 'boolean' || !threadsConfig.autoCheckpoint) {
      return null;
    }

    // Check frequency (every N iterations, default 5) - unless forced
    if (!force) {
      const frequency = threadsConfig.checkpointFrequency || 5;
      if (this.state.iteration % frequency !== 0) {
        return null;
      }
    }

    // Create the checkpoint
    const label = `auto-iter-${this.state.iteration}`;

    // Supplementary: also save to AutoCheckpointManager (file-based)
    if (this.autoCheckpointManager) {
      try {
        this.autoCheckpointManager.save({
          label,
          sessionId: this.agentId,
          iteration: this.state.iteration,
        });
      } catch {
        // Non-critical — don't fail the main checkpoint path
      }
    }

    return this.createCheckpoint(label);
  }

  // =========================================================================
  // AGENT REGISTRY METHODS (Subagent Support)
  // =========================================================================

  /**
   * Get all registered agents (built-in + user-defined).
   */
  getAgents(): LoadedAgent[] {
    if (!this.agentRegistry) {
      return [];
    }
    return this.agentRegistry.getAllAgents();
  }

  /**
   * Get a specific agent by name.
   */
  getAgent(name: string): LoadedAgent | undefined {
    return this.agentRegistry?.getAgent(name);
  }

  /**
   * Find agents matching a natural language query.
   * Use this for NL-based agent selection.
   */
  findAgentsForTask(query: string, limit: number = 3): LoadedAgent[] {
    if (!this.agentRegistry) {
      return [];
    }
    return this.agentRegistry.findMatchingAgents(query, limit);
  }

  /**
   * Register a custom agent at runtime.
   */
  registerAgent(definition: AgentDefinition): void {
    if (!this.agentRegistry) {
      throw new Error('Agent registry not initialized');
    }
    this.agentRegistry.registerAgent(definition);
    this.emit({ type: 'agent.registered', name: definition.name });
    this.observability?.logger?.info('Agent registered', { name: definition.name });
  }

  /**
   * Unregister an agent.
   */
  unregisterAgent(name: string): boolean {
    if (!this.agentRegistry) {
      return false;
    }
    const success = this.agentRegistry.unregisterAgent(name);
    if (success) {
      this.emit({ type: 'agent.unregistered', name });
    }
    return success;
  }

  /**
   * Spawn a subagent (delegates to core/subagent-spawner).
   */
  async spawnAgent(agentName: string, task: string, constraints?: SpawnConstraints): Promise<SpawnResult> {
    return coreSpawnAgent(agentName, task, this.buildContext(), this.createSubAgentFactory(), constraints);
  }


  /**
   * Spawn multiple subagents in parallel (delegates to core/subagent-spawner).
   */
  async spawnAgentsParallel(tasks: Array<{ agent: string; task: string }>): Promise<SpawnResult[]> {
    return coreSpawnAgentsParallel(tasks, this.buildContext(), this.buildMutators(), this.createSubAgentFactory());
  }

  /**
   * Get a formatted list of available agents.
   */
  formatAgentList(): string {
    if (!this.agentRegistry) {
      return 'No agents available';
    }
    return formatAgentList(this.agentRegistry.getAllAgents());
  }

  // =========================================================================
  // NL ROUTING METHODS (Intelligent Agent Selection)
  // =========================================================================

  /**
   * Use LLM to suggest the best agent(s) for a given task.
   * Returns ranked suggestions with confidence scores.
   */
  async suggestAgentForTask(task: string): Promise<{
    suggestions: Array<{
      agent: LoadedAgent;
      confidence: number;
      reason: string;
    }>;
    shouldDelegate: boolean;
    delegateAgent?: string;
  }> {
    if (!this.agentRegistry) {
      return { suggestions: [], shouldDelegate: false };
    }

    // First, get keyword-based matches
    const keywordMatches = this.agentRegistry.findMatchingAgents(task, 5);

    // If no LLM provider, fall back to keyword matching
    if (!this.provider) {
      return {
        suggestions: keywordMatches.map((agent, i) => ({
          agent,
          confidence: 0.9 - i * 0.15,
          reason: `Keyword match: ${agent.capabilities?.slice(0, 3).join(', ') || agent.description.split('.')[0]}`,
        })),
        shouldDelegate: keywordMatches.length > 0,
        delegateAgent: keywordMatches[0]?.name,
      };
    }

    // Build agent descriptions for LLM
    const agents = this.agentRegistry.getAllAgents();
    const agentDescriptions = agents.map(a =>
      `- ${a.name}: ${a.description}${a.capabilities?.length ? ` (can: ${a.capabilities.join(', ')})` : ''}`
    ).join('\n');

    // Ask LLM to classify the task
    const classificationPrompt = `You are a task routing assistant. Given a user task, determine which specialized agent (if any) should handle it.

Available agents:
${agentDescriptions}

User task: "${task}"

Respond in JSON format:
{
  "analysis": "Brief analysis of what the task requires",
  "bestAgent": "agent name or null if main agent should handle it",
  "confidence": 0.0 to 1.0,
  "reason": "Why this agent is best suited",
  "alternatives": ["other suitable agents in order of preference"]
}

If the task is a simple question or doesn't need specialized handling, set bestAgent to null.`;

    try {
      const response = await this.provider.chat([
        { role: 'system', content: 'You are a task routing classifier. Always respond with valid JSON.' },
        { role: 'user', content: classificationPrompt },
      ], {
        model: this.config.model,
      });

      // Parse the JSON response
      const jsonMatch = response.content.match(/\{[\s\S]*\}/);
      if (!jsonMatch) {
        // Fallback to keyword matching
        return {
          suggestions: keywordMatches.map((agent, i) => ({
            agent,
            confidence: 0.7 - i * 0.1,
            reason: 'Keyword-based match',
          })),
          shouldDelegate: false,
        };
      }

      const classification = JSON.parse(jsonMatch[0]) as {
        analysis: string;
        bestAgent: string | null;
        confidence: number;
        reason: string;
        alternatives: string[];
      };

      // Build suggestions
      const suggestions: Array<{ agent: LoadedAgent; confidence: number; reason: string }> = [];

      if (classification.bestAgent) {
        const bestAgent = this.agentRegistry.getAgent(classification.bestAgent);
        if (bestAgent) {
          suggestions.push({
            agent: bestAgent,
            confidence: classification.confidence,
            reason: classification.reason,
          });
        }
      }

      // Add alternatives
      for (let i = 0; i < (classification.alternatives || []).length; i++) {
        const altName = classification.alternatives[i];
        const altAgent = this.agentRegistry.getAgent(altName);
        if (altAgent && !suggestions.find(s => s.agent.name === altName)) {
          suggestions.push({
            agent: altAgent,
            confidence: Math.max(0.3, classification.confidence - 0.2 - i * 0.1),
            reason: 'Alternative option',
          });
        }
      }

      // Determine if we should delegate
      const shouldDelegate = classification.confidence >= 0.7 && classification.bestAgent !== null;

      return {
        suggestions,
        shouldDelegate,
        delegateAgent: shouldDelegate ? classification.bestAgent || undefined : undefined,
      };
    } catch (error) {
      // On error, fall back to keyword matching
      this.observability?.logger?.warn('Agent suggestion LLM call failed', { error });
      return {
        suggestions: keywordMatches.map((agent, i) => ({
          agent,
          confidence: 0.6 - i * 0.1,
          reason: 'Keyword-based fallback',
        })),
        shouldDelegate: false,
      };
    }
  }

  /**
   * Run a task with automatic agent routing.
   * If a specialized agent is highly suited, delegates to it.
   * Otherwise runs with the main agent.
   */
  async runWithAutoRouting(
    task: string,
    options: {
      confidenceThreshold?: number;
      confirmDelegate?: (agent: LoadedAgent, reason: string) => Promise<boolean>;
    } = {}
  ): Promise<AgentResult | SpawnResult> {
    const { confidenceThreshold = 0.8, confirmDelegate } = options;

    // Get agent suggestions
    const { suggestions, shouldDelegate, delegateAgent } = await this.suggestAgentForTask(task);

    // Check if we should delegate
    if (shouldDelegate && delegateAgent) {
      const topSuggestion = suggestions[0];

      // If confirmation callback provided, ask user
      if (confirmDelegate && topSuggestion) {
        const confirmed = await this.withPausedDuration(() =>
          confirmDelegate(topSuggestion.agent, topSuggestion.reason)
        );
        if (!confirmed) {
          // User declined, run with main agent
          return this.run(task);
        }
      }

      // Only auto-delegate if confidence exceeds threshold
      if (topSuggestion && topSuggestion.confidence >= confidenceThreshold) {
        this.emit({
          type: 'agent.spawn',
          agentId: `auto-${Date.now()}`,
          name: delegateAgent,
          task,
        });

        return this.spawnAgent(delegateAgent, task);
      }
    }

    // Run with main agent
    return this.run(task);
  }

  // =========================================================================
  // CANCELLATION METHODS
  // =========================================================================

  /**
   * Request cancellation of the current operation.
   * The agent will attempt to stop gracefully.
   */
  cancel(reason?: string): void {
    if (!this.cancellation) {
      log.warn('Cancellation not enabled');
      return;
    }

    this.cancellation.cancel(reason);
    this.state.status = 'paused';
    this.observability?.logger?.info('Cancellation requested', { reason });
  }

  /**
   * Check if cancellation has been requested.
   */
  isCancelled(): boolean {
    return this.cancellation?.isCancelled ?? false;
  }

  // =========================================================================
  // RESOURCE MONITORING METHODS
  // =========================================================================

  /**
   * Get current resource usage.
   */
  getResourceUsage() {
    return this.resourceManager?.getUsage() || null;
  }

  /**
   * Get formatted resource status string.
   */
  getResourceStatus(): string | null {
    return this.resourceManager?.getStatusString() || null;
  }

  /**
   * Reset CPU time counter for the resource manager.
   * Call this when starting a new prompt to allow per-prompt time limits
   * instead of session-wide limits.
   */
  resetResourceTimer(): void {
    this.resourceManager?.resetCpuTime();
  }

  // =========================================================================
  // LSP (LANGUAGE SERVER) METHODS
  // =========================================================================

  /**
   * Start LSP servers for the workspace.
   * Auto-detects languages based on project files.
   */
  async startLSP(workspaceRoot?: string): Promise<string[]> {
    if (!this.lspManager) return [];
    return this.lspManager.autoStart(workspaceRoot);
  }

  /**
   * Get code definition location.
   */
  async getLSPDefinition(file: string, line: number, col: number) {
    return this.lspManager?.getDefinition(file, line, col) || null;
  }

  /**
   * Get code completions.
   */
  async getLSPCompletions(file: string, line: number, col: number) {
    return this.lspManager?.getCompletions(file, line, col) || [];
  }

  /**
   * Get hover documentation.
   */
  async getLSPHover(file: string, line: number, col: number) {
    return this.lspManager?.getHover(file, line, col) || null;
  }

  /**
   * Get all references to a symbol.
   */
  async getLSPReferences(file: string, line: number, col: number) {
    return this.lspManager?.getReferences(file, line, col) || [];
  }

  /**
   * Get active LSP servers.
   */
  getActiveLSPServers(): string[] {
    return this.lspManager?.getActiveServers() || [];
  }

  /**
   * Get LSP diagnostics for a file.
   */
  getLSPDiagnostics(file: string) {
    return this.lspManager?.getDiagnostics(file) || [];
  }

  /**
   * Get the LSP manager instance (for advanced use).
   */
  getLSPManager(): LSPManager | null {
    return this.lspManager;
  }

  /**
   * Get LSP-aware file tools.
   * These tools provide diagnostic feedback after edit/write operations.
   * Returns the tools if LSP is enabled, empty array otherwise.
   */
  getLSPFileTools(options?: Partial<Omit<LSPFileToolsConfig, 'lspManager'>>): ToolDefinition[] {
    if (!this.lspManager) {
      return [];
    }

    return createLSPFileTools({
      lspManager: this.lspManager,
      diagnosticDelay: options?.diagnosticDelay ?? 500,
      includeWarnings: options?.includeWarnings ?? true,
    });
  }

  /**
   * Replace standard file tools with LSP-aware versions.
   * Call this after enabling LSP to get diagnostic feedback on edits.
   */
  enableLSPFileTools(options?: Partial<Omit<LSPFileToolsConfig, 'lspManager'>>): void {
    if (!this.lspManager) {
      log.warn('LSP not enabled, cannot enable LSP file tools');
      return;
    }

    const lspTools = this.getLSPFileTools(options);
    for (const tool of lspTools) {
      this.tools.set(tool.name, tool);
    }

    this.observability?.logger?.info('LSP file tools enabled', {
      tools: lspTools.map(t => t.name),
    });
  }

  // =========================================================================
  // SEMANTIC CACHE METHODS
  // =========================================================================

  /**
   * Check if a cached response exists for a similar query.
   */
  async getCachedResponse(query: string): Promise<{ response: string; similarity: number } | null> {
    const hit = await this.semanticCache?.get(query);
    if (hit) {
      return { response: hit.entry.response, similarity: hit.similarity };
    }
    return null;
  }

  /**
   * Cache an LLM response for a query.
   */
  async cacheResponse(query: string, response: string, metadata?: Record<string, unknown>): Promise<string | null> {
    return await this.semanticCache?.set(query, response, metadata) || null;
  }

  /**
   * Check if a similar query exists in cache (without retrieving).
   */
  async hasCachedQuery(query: string): Promise<boolean> {
    return await this.semanticCache?.has(query) || false;
  }

  /**
   * Get cache statistics.
   */
  getCacheStats() {
    return this.semanticCache?.getStats() || { size: 0, totalHits: 0, avgHits: 0, hitRate: 0, totalQueries: 0 };
  }

  /**
   * Clear the semantic cache.
   */
  clearCache(): void {
    this.semanticCache?.clear();
  }

  // =========================================================================
  // MODE MANAGEMENT METHODS
  // =========================================================================

  /**
   * Get the current agent mode.
   */
  getMode(): AgentMode {
    return this.modeManager.getMode();
  }

  /**
   * Set the agent mode.
   */
  setMode(mode: AgentMode | string): void {
    const parsed = typeof mode === 'string' ? parseMode(mode) : mode;
    if (parsed) {
      this.modeManager.setMode(parsed);
      this.emit({ type: 'mode.changed' as any, from: this.getMode(), to: parsed });
    }
  }

  /**
   * Set the parent's iteration count for total budget tracking.
   * When this agent is a subagent, the parent passes its iteration count
   * so the subagent can account for total iterations across the hierarchy.
   */
  setParentIterations(count: number): void {
    this.parentIterations = count;
  }

  /**
   * Set an approval scope for this agent (used by parent when spawning subagents).
   * Enables pre-approved operations within a defined scope, reducing approval prompts.
   */
  setApprovalScope(scope: ApprovalScope): void {
    if (this.safety?.humanInLoop) {
      this.safety.humanInLoop.setApprovalScope(scope);
    }
  }

  /**
   * Set an external cancellation token for this agent.
   * Used when spawning subagents to propagate parent timeout/cancellation.
   * The agent will check this token in its main loop and stop gracefully
   * when cancellation is requested, preserving partial results.
   */
  setExternalCancellation(token: CancellationTokenType): void {
    this.externalCancellationToken = token;
  }

  /**
   * Set a SQLite store instance for durable persistence features.
   */
  setStore(store: SQLiteStore): void {
    this.store = store;
  }

  /**
   * Check if external cancellation has been requested.
   * Returns true if the external token signals cancellation.
   */
  isExternallyCancelled(): boolean {
    return this.externalCancellationToken?.isCancellationRequested ?? false;
  }

  /**
   * Request a graceful wrapup of the agent's current work.
   * On the next main loop iteration, the agent will produce a structured summary
   * instead of making more tool calls.
   */
  requestWrapup(reason?: string): void {
    this.wrapupRequested = true;
    this.wrapupReason = reason || 'Timeout approaching';
  }

  /**
   * Get total iterations (this agent + parent).
   * Used for accurate budget tracking across subagent hierarchies.
   */
  getTotalIterations(): number {
    return this.state.iteration + this.parentIterations;
  }

  /**
   * Cycle to the next mode (for Tab key).
   */
  cycleMode(): AgentMode {
    return this.modeManager.cycleMode();
  }

  /**
   * Get all registered tools.
   */
  getTools(): ToolDefinition[] {
    return Array.from(this.tools.values());
  }

  /**
   * Get available tools filtered by current mode.
   */
  getModeFilteredTools(): ToolDefinition[] {
    return this.modeManager.filterTools(Array.from(this.tools.values()));
  }

  /**
   * Get mode info for display.
   */
  getModeInfo() {
    return this.modeManager.getModeInfo();
  }

  /**
   * Format mode for terminal prompt.
   */
  formatModePrompt(): string {
    return this.modeManager.formatModePrompt();
  }

  /**
   * Get list of all available modes.
   */
  getAvailableModes(): string {
    return formatModeList();
  }

  /**
   * Get system prompt with mode-specific additions.
   */
  getSystemPromptWithMode(): string {
    const base = this.config.systemPrompt;
    const modeAddition = this.modeManager.getSystemPromptAddition();
    return `${base}\n\n${modeAddition}`;
  }

  /**
   * Toggle between build and plan modes.
   */
  togglePlanMode(): AgentMode {
    return this.modeManager.togglePlanMode();
  }

  // =========================================================================
  // PENDING PLAN METHODS (Plan Mode)
  // =========================================================================

  /**
   * Get the current pending plan.
   */
  getPendingPlan(): PendingPlan | null {
    return this.pendingPlanManager.getPendingPlan();
  }

  /**
   * Check if there's a pending plan awaiting approval.
   */
  hasPendingPlan(): boolean {
    return this.pendingPlanManager.hasPendingPlan();
  }

  /**
   * Get formatted plan for display.
   */
  formatPendingPlan(): string {
    return this.pendingPlanManager.formatPlan();
  }

  /**
   * Approve the pending plan and execute the changes.
   * @param count - If provided, only approve first N changes
   * @returns Result of executing the approved changes, including tool outputs
   */
  async approvePlan(count?: number): Promise<{
    success: boolean;
    executed: number;
    errors: string[];
    results: Array<{ tool: string; output: unknown }>;
  }> {
    const result = this.pendingPlanManager.approve(count);

    if (result.changes.length === 0) {
      return { success: true, executed: 0, errors: [], results: [] };
    }

    // Switch to build mode for execution
    const previousMode = this.getMode();
    this.setMode('build');

    this.emit({ type: 'plan.approved', changeCount: result.changes.length });

    const errors: string[] = [];
    const results: Array<{ tool: string; output: unknown }> = [];
    let executed = 0;

    // Execute each change and CAPTURE results
    for (let i = 0; i < result.changes.length; i++) {
      const change = result.changes[i];
      this.emit({ type: 'plan.executing', changeIndex: i, totalChanges: result.changes.length });

      try {
        const tool = this.tools.get(change.tool);
        if (!tool) {
          errors.push(`Unknown tool: ${change.tool}`);
          this.emit({
            type: 'plan.change.complete',
            changeIndex: i,
            tool: change.tool,
            result: null,
            error: `Unknown tool: ${change.tool}`,
          });
          continue;
        }

        // CRITICAL: Capture tool result instead of discarding it
        const toolResult = await tool.execute(change.args);
        results.push({ tool: change.tool, output: toolResult });
        executed++;

        // Emit result for TUI display
        this.emit({
          type: 'plan.change.complete',
          changeIndex: i,
          tool: change.tool,
          result: toolResult,
        });
      } catch (err) {
        const error = err instanceof Error ? err.message : String(err);
        errors.push(`${change.tool}: ${error}`);
        this.emit({
          type: 'plan.change.complete',
          changeIndex: i,
          tool: change.tool,
          result: null,
          error,
        });
      }
    }

    // Restore previous mode if it wasn't build
    if (previousMode !== 'build' && previousMode !== 'plan') {
      this.setMode(previousMode);
    }

    return {
      success: errors.length === 0,
      executed,
      errors,
      results,
    };
  }

  /**
   * Reject the pending plan and discard all proposed changes.
   */
  rejectPlan(): void {
    this.pendingPlanManager.reject();
    this.emit({ type: 'plan.rejected' });
  }

  /**
   * Clear the pending plan without emitting rejection event.
   */
  clearPlan(): void {
    this.pendingPlanManager.clear();
  }

  /**
   * Get the number of pending changes.
   */
  getPendingChangeCount(): number {
    return this.pendingPlanManager.getChangeCount();
  }

  // =========================================================================
  // SKILLS METHODS
  // =========================================================================

  /**
   * Get the skill manager instance for advanced operations.
   */
  getSkillManager(): SkillManager | null {
    return this.skillManager;
  }

  /**
   * Get the agent registry instance for advanced operations.
   */
  getAgentRegistry(): AgentRegistry | null {
    return this.agentRegistry;
  }

  /**
   * Get the task manager instance for task tracking.
   */
  getTaskManager(): TaskManager | null {
    return this.taskManager;
  }

  /**
   * Get all loaded skills.
   */
  getSkills(): Skill[] {
    return this.skillManager?.getAllSkills() || [];
  }

  /**
   * Get a specific skill by name.
   */
  getSkill(name: string): Skill | undefined {
    return this.skillManager?.getSkill(name);
  }

  /**
   * Activate a skill by name.
   */
  activateSkill(name: string): boolean {
    if (!this.skillManager) return false;
    return this.skillManager.activateSkill(name);
  }

  /**
   * Deactivate a skill by name.
   */
  deactivateSkill(name: string): boolean {
    if (!this.skillManager) return false;
    return this.skillManager.deactivateSkill(name);
  }

  /**
   * Get currently active skills.
   */
  getActiveSkills(): Skill[] {
    return this.skillManager?.getActiveSkills() || [];
  }

  /**
   * Check if a skill is active.
   */
  isSkillActive(name: string): boolean {
    return this.skillManager?.isSkillActive(name) || false;
  }

  /**
   * Find skills matching a query (for auto-activation).
   */
  findMatchingSkills(query: string): Skill[] {
    return this.skillManager?.findMatchingSkills(query) || [];
  }

  /**
   * Get the capabilities registry for unified discovery.
   * Lazily creates and populates the registry on first access.
   */
  getCapabilitiesRegistry(): CapabilitiesRegistry {
    if (!this.capabilitiesRegistry) {
      this.capabilitiesRegistry = createCapabilitiesRegistry();

      // Register sources
      this.capabilitiesRegistry.registerToolRegistry({
        getTools: () => this.getTools(),
      });

      if (this.skillManager) {
        this.capabilitiesRegistry.registerSkillManager(this.skillManager);
      }

      if (this.agentRegistry) {
        this.capabilitiesRegistry.registerAgentRegistry(this.agentRegistry);
      }

      // MCP client is registered externally if available
    }

    return this.capabilitiesRegistry;
  }

  /**
   * Register an MCP client with the capabilities registry.
   */
  registerMCPClient(client: { getAllTools(): ToolDefinition[]; isToolLoaded(name: string): boolean }): void {
    const registry = this.getCapabilitiesRegistry();
    registry.registerMCPClient(client as any);
  }

  /**
   * Get formatted list of available skills.
   */
  formatSkillList(): string {
    if (!this.skillManager) return 'Skills not enabled';
    return formatSkillList(this.skillManager.getAllSkills());
  }

  /**
   * Cleanup resources.
   */
  async cleanup(): Promise<void> {
    // Unsubscribe all event listeners (prevents memory leaks in long sessions)
    for (const unsub of this.unsubscribers) {
      try {
        unsub();
      } catch {
        // Ignore unsubscribe errors during cleanup
      }
    }
    this.unsubscribers = [];

    // Flush trace collector before cleanup
    await this.traceCollector?.flush();

    // Per-agent blackboard cleanup: release only this agent's claims and subscriptions
    // so parallel siblings don't lose their data. Only root agent clears everything.
    if (this.blackboard) {
      if (this.parentIterations > 0 && this.agentId) {
        // Subagent: release only our claims and subscriptions
        this.blackboard.releaseAll(this.agentId);
        this.blackboard.unsubscribeAgent(this.agentId);
      } else {
        // Root agent: full clear
        this.blackboard.clear();
      }
    }

    // Wait for any pending init before cleanup
    if (this.initPromises.length > 0) {
      try {
        await Promise.all(this.initPromises);
      } catch {
        // Ignore init errors during cleanup
      }
    }

    this.cancellation?.cleanup();
    this.resourceManager?.cleanup();
    await this.lspManager?.cleanup();
    this.semanticCache?.cleanup();
    this.skillManager?.cleanup();
    await this.hooks?.cleanup();
    this.rules?.cleanup();
    this.agentRegistry?.cleanup();
    this.observability?.logger?.info('Agent cleanup complete');
  }
}

// =============================================================================
// Re-exports for backward compatibility
export { parseStructuredClosureReport } from './core/index.js';
