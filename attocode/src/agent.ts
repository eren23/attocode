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
  AgentRoleConfig,
  MultiAgentConfig,
} from './types.js';

import {
  buildConfig,
  isFeatureEnabled,
  getEnabledFeatures,
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
  DEFAULT_RULE_SOURCES,
  ExecutionEconomicsManager,
  STANDARD_BUDGET,
  AgentRegistry,
  formatAgentList,
  CancellationManager,
  createCancellationManager,
  isCancellationError,
  ResourceManager,
  createResourceManager,
  LSPManager,
  createLSPManager,
  SemanticCacheManager,
  createSemanticCacheManager,
  SkillManager,
  createSkillManager,
  formatSkillList,
  ContextEngineeringManager,
  createContextEngineering,
  CodebaseContextManager,
  createCodebaseContext,
  buildContextFromChunks,
  generateLightweightRepoMap,
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
  createInteractivePlanner,
  RecursiveContextManager,
  createRecursiveContext,
  LearningStore,
  createLearningStore,
  Compactor,
  createCompactor,
  AutoCompactionManager,
  createAutoCompactionManager,
  type AutoCompactionEvent,
  FileChangeTracker,
  createFileChangeTracker,
  CapabilitiesRegistry,
  createCapabilitiesRegistry,
  SharedBlackboard,
  createSharedBlackboard,
  TaskManager,
  createTaskManager,
  type SQLiteStore,
  SwarmOrchestrator,
  createSwarmOrchestrator,
  createThrottledProvider,
  FREE_TIER_THROTTLE,
  PAID_TIER_THROTTLE,
  type SwarmConfig,
  type SwarmExecutionResult,
  WorkLog,
  createWorkLog,
  VerificationGate,
  createVerificationGate,
  classifyComplexity,
  getScalingGuidance,
  type ComplexityAssessment,
  ToolRecommendationEngine,
  createToolRecommendationEngine,
  InjectionBudgetManager,
  createInjectionBudgetManager,
  getThinkingSystemPrompt,
  SelfImprovementProtocol,
  createSelfImprovementProtocol,
  SubagentOutputStore,
  createSubagentOutputStore,
  createSerperSearchTool,
  getEnvironmentFacts,
  formatFactsBlock,
  AutoCheckpointManager,
  createAutoCheckpointManager,
} from './integrations/index.js';
import {
  resolvePolicyProfile,
} from './integrations/policy-engine.js';

import type { SharedContextState } from './shared/shared-context-state.js';
import type { SharedEconomicsState } from './shared/shared-economics-state.js';
import { TraceCollector, createTraceCollector } from './tracing/trace-collector.js';
import { modelRegistry } from './costs/index.js';
import { getModelContextLength } from './integrations/openrouter-pricing.js';
import { createComponentLogger } from './integrations/logger.js';

// Spawn agent tools for LLM-driven subagent delegation
import {
  createBoundSpawnAgentTool,
  createBoundSpawnAgentsParallelTool,
  type SpawnConstraints,
} from './tools/agent.js';

// Task tools for Claude Code-style task management
import {
  createTaskTools,
} from './tools/tasks.js';

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
import { type AgentStateMachine, createAgentStateMachine } from './core/agent-state-machine.js';

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
   */
  private initializeFeatures(): void {
    // Debug output only when DEBUG env var is set
    if (process.env.DEBUG) {
      const features = getEnabledFeatures(this.config);
      log.debug('Initializing with features', { features: features.join(', ') });
    }

    // Hooks & Plugins
    if (isFeatureEnabled(this.config.hooks) && isFeatureEnabled(this.config.plugins)) {
      this.hooks = new HookManager(this.config.hooks, this.config.plugins);
    }

    // Memory
    if (isFeatureEnabled(this.config.memory)) {
      this.memory = new MemoryManager(this.config.memory);
    }

    // Planning & Reflection
    if (isFeatureEnabled(this.config.planning) && isFeatureEnabled(this.config.reflection)) {
      this.planning = new PlanningManager(this.config.planning, this.config.reflection);
    }

    // Observability
    if (isFeatureEnabled(this.config.observability)) {
      this.observability = new ObservabilityManager(this.config.observability);

      // Lesson 26: Full trace capture
      const traceCaptureConfig = this.config.observability.traceCapture;
      if (traceCaptureConfig?.enabled) {
        this.traceCollector = createTraceCollector({
          enabled: true,
          outputDir: traceCaptureConfig.outputDir ?? '.traces',
          captureMessageContent: traceCaptureConfig.captureMessageContent ?? true,
          captureToolResults: traceCaptureConfig.captureToolResults ?? true,
          analyzeCacheBoundaries: traceCaptureConfig.analyzeCacheBoundaries ?? true,
          filePattern: traceCaptureConfig.filePattern ?? 'trace-{sessionId}-{timestamp}.jsonl',
          enableConsoleOutput: false,
        });
      }
    }

    // Safety (Sandbox + Human-in-Loop)
    if (isFeatureEnabled(this.config.sandbox) || isFeatureEnabled(this.config.humanInLoop)) {
      this.safety = new SafetyManager(
        isFeatureEnabled(this.config.sandbox) ? this.config.sandbox : false,
        isFeatureEnabled(this.config.humanInLoop) ? this.config.humanInLoop : false,
        isFeatureEnabled(this.config.policyEngine) ? this.config.policyEngine : false,
      );
    }

    if (isFeatureEnabled(this.config.policyEngine)) {
      const rootPolicy = resolvePolicyProfile({
        policyEngine: this.config.policyEngine,
        sandboxConfig: isFeatureEnabled(this.config.sandbox) ? this.config.sandbox : undefined,
      });
      this.emit({
        type: 'policy.profile.resolved',
        profile: rootPolicy.profileName,
        context: 'root',
        selectionSource: rootPolicy.metadata.selectionSource,
        usedLegacyMappings: rootPolicy.metadata.usedLegacyMappings,
        legacySources: rootPolicy.metadata.legacyMappingSources,
      });
      if (rootPolicy.metadata.usedLegacyMappings) {
        this.emit({
          type: 'policy.legacy.fallback.used',
          profile: rootPolicy.profileName,
          sources: rootPolicy.metadata.legacyMappingSources,
          warnings: rootPolicy.metadata.warnings,
        });
      }
    }

    // Routing
    if (isFeatureEnabled(this.config.routing)) {
      this.routing = new RoutingManager(this.config.routing);
    }

    // Multi-Agent (Lesson 17)
    if (isFeatureEnabled(this.config.multiAgent)) {
      const roles = (this.config.multiAgent.roles || []).map((r: AgentRoleConfig) => ({
        name: r.name,
        description: r.description,
        systemPrompt: r.systemPrompt,
        capabilities: r.capabilities,
        authority: r.authority,
        model: r.model,
      }));
      this.multiAgent = new MultiAgentManager(this.provider, Array.from(this.tools.values()), roles);
    }

    // ReAct (Lesson 18)
    if (isFeatureEnabled(this.config.react)) {
      this.react = new ReActManager(this.provider, Array.from(this.tools.values()), {
        maxSteps: this.config.react.maxSteps,
        stopOnAnswer: this.config.react.stopOnAnswer,
        includeReasoning: this.config.react.includeReasoning,
      });
    }

    // Execution Policies (Lesson 23)
    if (isFeatureEnabled(this.config.executionPolicy)) {
      this.executionPolicy = new ExecutionPolicyManager({
        defaultPolicy: this.config.executionPolicy.defaultPolicy,
        toolPolicies: this.config.executionPolicy.toolPolicies as Record<string, { policy: 'allow' | 'prompt' | 'forbidden'; conditions?: { argMatch?: Record<string, string | RegExp>; policy: 'allow' | 'prompt' | 'forbidden'; reason?: string }[]; reason?: string }>,
        intentAware: this.config.executionPolicy.intentAware,
        intentConfidenceThreshold: this.config.executionPolicy.intentConfidenceThreshold,
      });
    }

    // Thread Management (Lesson 24)
    if (isFeatureEnabled(this.config.threads)) {
      this.threadManager = new ThreadManager();
    }

    // Rules System (Lesson 12)
    if (isFeatureEnabled(this.config.rules)) {
      const ruleSources = this.config.rules.sources || DEFAULT_RULE_SOURCES;
      this.rules = new RulesManager({
        enabled: true,
        sources: ruleSources,
        watch: this.config.rules.watch,
      });
      // Load rules asynchronously - tracked for ensureReady()
      this.initPromises.push(
        this.rules.loadRules().catch(err => {
          log.warn('Failed to load rules', { error: String(err) });
        })
      );
    }

    // Economics System (Token Budget) - always enabled
    // Use custom budget if provided (subagents use SUBAGENT_BUDGET), otherwise STANDARD_BUDGET
    const baseBudget = this.config.budget ?? STANDARD_BUDGET;
    this.economics = new ExecutionEconomicsManager(
      {
        ...baseBudget,
        // Use maxIterations from config as absolute safety cap
        maxIterations: this.config.maxIterations,
        targetIterations: Math.min(baseBudget.targetIterations ?? 20, this.config.maxIterations),
      },
      this._sharedEconomicsState ?? undefined,
      this.agentId,
    );

    // Phase 2.2: Agent State Machine - formalizes phase tracking
    // Always enabled - provides structured phase transitions with metrics
    this.stateMachine = createAgentStateMachine();
    // Forward state machine phase transitions as subagent.phase events
    const phaseMap: Record<string, 'exploring' | 'planning' | 'executing' | 'completing'> = {
      exploring: 'exploring', planning: 'planning', acting: 'executing', verifying: 'completing',
    };
    const unsubStateMachine = this.stateMachine.subscribe(event => {
      if (event.type === 'phase.changed') {
        this.emit({
          type: 'subagent.phase',
          agentId: this.agentId,
          phase: phaseMap[event.transition.to] ?? 'exploring',
        });
      }
    });
    this.unsubscribers.push(unsubStateMachine);

    // Work Log - compaction-resilient summary of agent work
    // Always enabled - minimal overhead and critical for long-running tasks
    this.workLog = createWorkLog();

    // Verification Gate - opt-in completion verification
    if (this.config.verificationCriteria) {
      this.verificationGate = createVerificationGate(this.config.verificationCriteria);
    }

    // Phase 2-4: Orchestration & Advanced modules (always enabled, lightweight)
    this.injectionBudget = createInjectionBudgetManager();
    this.selfImprovement = createSelfImprovementProtocol(undefined, this.learningStore ?? undefined);
    this.subagentOutputStore = createSubagentOutputStore({ persistToFile: false });
    this.autoCheckpointManager = createAutoCheckpointManager({ enabled: true });
    this.toolRecommendation = createToolRecommendationEngine();

    // Agent Registry - always enabled for subagent support
    this.agentRegistry = new AgentRegistry();
    // Load user agents asynchronously - tracked for ensureReady()
    this.initPromises.push(
      this.agentRegistry.loadUserAgents().catch(err => {
        log.warn('Failed to load user agents', { error: String(err) });
      })
    );

    // Register spawn_agent tool so LLM can delegate to subagents
    const boundSpawnTool = createBoundSpawnAgentTool(
      (name, task, constraints) => this.spawnAgent(name, task, constraints)
    );
    this.tools.set(boundSpawnTool.name, boundSpawnTool);

    // Register spawn_agents_parallel tool for parallel subagent execution
    const boundParallelSpawnTool = createBoundSpawnAgentsParallelTool(
      (tasks) => this.spawnAgentsParallel(tasks)
    );
    this.tools.set(boundParallelSpawnTool.name, boundParallelSpawnTool);

    // Task Manager - Claude Code-style task system for coordination
    this.taskManager = createTaskManager();
    // Forward task events (with cleanup tracking for EventEmitter-based managers)
    const taskCreatedHandler = (data: { task: any }) => {
      this.emit({ type: 'task.created', task: data.task });
    };
    this.taskManager.on('task.created', taskCreatedHandler);
    this.unsubscribers.push(() => this.taskManager?.off('task.created', taskCreatedHandler));

    const taskUpdatedHandler = (data: { task: any }) => {
      this.emit({ type: 'task.updated', task: data.task });
    };
    this.taskManager.on('task.updated', taskUpdatedHandler);
    this.unsubscribers.push(() => this.taskManager?.off('task.updated', taskUpdatedHandler));
    // Register task tools
    const taskTools = createTaskTools(this.taskManager);
    for (const tool of taskTools) {
      this.tools.set(tool.name, tool);
    }

    // Built-in web search (Serper API) — gracefully handles missing API key
    const serperCustomTool = createSerperSearchTool();
    this.tools.set('web_search', {
      name: serperCustomTool.name,
      description: serperCustomTool.description,
      parameters: serperCustomTool.inputSchema,
      execute: serperCustomTool.execute,
      dangerLevel: 'safe',
    });

    // Swarm Mode (experimental)
    if (this.config.swarm) {
      const swarmConfig = this.config.swarm as SwarmConfig;

      // Wrap provider with request throttle to prevent 429 rate limiting.
      // All subagents share this.provider by reference (line 4398),
      // so wrapping here throttles ALL downstream LLM calls.
      if (swarmConfig.throttle !== false) {
        const throttleConfig = swarmConfig.throttle === 'paid'
          ? PAID_TIER_THROTTLE
          : swarmConfig.throttle === 'free' || swarmConfig.throttle === undefined
            ? FREE_TIER_THROTTLE
            : swarmConfig.throttle;
        this.provider = createThrottledProvider(
          this.provider as unknown as import('./providers/types.js').LLMProvider,
          throttleConfig,
        ) as any;
      }

      this.swarmOrchestrator = createSwarmOrchestrator(
        swarmConfig,
        this.provider as unknown as import('./providers/types.js').LLMProvider,
        this.agentRegistry,
        (name, task) => this.spawnAgent(name, task),
        this.blackboard ?? undefined,
      );

      // Override parent budget pool with swarm's much larger pool so spawnAgent()
      // allocates from the swarm budget (e.g. 10M tokens) instead of the parent's
      // generic pool (200K tokens). Without this, workers get 5K emergency budget.
      this.budgetPool = this.swarmOrchestrator.getBudgetPool().pool;

      // Phase 3.1+3.2: Set shared state so workers inherit it via buildContext()
      this._sharedContextState = this.swarmOrchestrator.getSharedContextState();
      this._sharedEconomicsState = this.swarmOrchestrator.getSharedEconomicsState();
    }

    // Cancellation Support
    if (isFeatureEnabled(this.config.cancellation)) {
      this.cancellation = createCancellationManager();
      // Forward cancellation events (with cleanup tracking)
      const unsubCancellation = this.cancellation.subscribe(event => {
        if (event.type === 'cancellation.requested') {
          this.emit({ type: 'cancellation.requested', reason: event.reason });
        }
      });
      this.unsubscribers.push(unsubCancellation);
    }

    // Resource Monitoring
    if (isFeatureEnabled(this.config.resources)) {
      this.resourceManager = createResourceManager({
        enabled: this.config.resources.enabled,
        maxMemoryMB: this.config.resources.maxMemoryMB,
        maxCpuTimeSec: this.config.resources.maxCpuTimeSec,
        maxConcurrentOps: this.config.resources.maxConcurrentOps,
        warnThreshold: this.config.resources.warnThreshold,
        criticalThreshold: this.config.resources.criticalThreshold,
      });
    }

    // LSP (Language Server Protocol) Support
    if (isFeatureEnabled(this.config.lsp)) {
      this.lspManager = createLSPManager({
        enabled: this.config.lsp.enabled,
        autoDetect: this.config.lsp.autoDetect,
        servers: this.config.lsp.servers,
        timeout: this.config.lsp.timeout,
      });
      // Auto-start is done lazily on first use to avoid startup delays
    }

    // Semantic Cache Support
    if (isFeatureEnabled(this.config.semanticCache)) {
      this.semanticCache = createSemanticCacheManager({
        enabled: this.config.semanticCache.enabled,
        threshold: this.config.semanticCache.threshold,
        maxSize: this.config.semanticCache.maxSize,
        ttl: this.config.semanticCache.ttl,
      });
      // Forward cache events (with cleanup tracking)
      const unsubSemanticCache = this.semanticCache.subscribe(event => {
        if (event.type === 'cache.hit') {
          this.emit({ type: 'cache.hit', query: event.query, similarity: event.similarity });
        } else if (event.type === 'cache.miss') {
          this.emit({ type: 'cache.miss', query: event.query });
        } else if (event.type === 'cache.set') {
          this.emit({ type: 'cache.set', query: event.query });
        }
      });
      this.unsubscribers.push(unsubSemanticCache);
    }

    // Skills Support
    if (isFeatureEnabled(this.config.skills)) {
      this.skillManager = createSkillManager({
        enabled: this.config.skills.enabled,
        directories: this.config.skills.directories,
        loadBuiltIn: this.config.skills.loadBuiltIn,
        autoActivate: this.config.skills.autoActivate,
      });
      // Load skills asynchronously - tracked for ensureReady()
      this.initPromises.push(
        this.skillManager.loadSkills()
          .then(() => {}) // Convert to void
          .catch(err => {
            log.warn('Failed to load skills', { error: String(err) });
          })
      );
    }

    // Context Engineering (Manus-inspired tricks P, Q, R, S, T)
    // Always enabled - these are performance optimizations
    this.contextEngineering = createContextEngineering({
      enableCacheOptimization: true,
      enableRecitation: true,
      enableReversibleCompaction: true,
      enableFailureTracking: true,
      enableDiversity: false, // Off by default - can cause unexpected behavior
      staticPrefix: this.config.systemPrompt,
      recitationFrequency: 5,
      maxFailures: 30,
      maxReferences: 50,
    });

    // Bind shared context state for cross-worker failure learning (swarm workers only)
    if (this._sharedContextState) {
      this.contextEngineering.setSharedState(this._sharedContextState);
    }

    // Codebase Context - intelligent code selection for context management
    // Analyzes repo structure and selects relevant code within token budgets
    if (this.config.codebaseContext !== false) {
      const codebaseConfig = typeof this.config.codebaseContext === 'object'
        ? this.config.codebaseContext
        : {};
      this.codebaseContext = createCodebaseContext({
        root: codebaseConfig.root ?? process.cwd(),
        includePatterns: codebaseConfig.includePatterns,
        excludePatterns: codebaseConfig.excludePatterns,
        maxFileSize: codebaseConfig.maxFileSize ?? 100 * 1024, // 100KB
        tokensPerChar: 0.25,
        analyzeDependencies: true,
        cacheResults: true,
        cacheTTL: 5 * 60 * 1000, // 5 minutes
      });

      // Connect LSP manager to codebase context for enhanced code selection
      // This enables LSP-based relevance boosting (Phase 4.1)
      if (this.lspManager) {
        this.codebaseContext.setLSPManager(this.lspManager);
      }
    }

    // Forward context engineering events (with cleanup tracking)
    const unsubContextEngineering = this.contextEngineering.on(event => {
      switch (event.type) {
        case 'failure.recorded':
          this.observability?.logger?.warn('Failure recorded', {
            action: event.failure.action,
            category: event.failure.category,
          });
          break;
        case 'failure.pattern':
          this.observability?.logger?.warn('Failure pattern detected', {
            type: event.pattern.type,
            description: event.pattern.description,
          });
          this.emit({ type: 'error', error: `Pattern: ${event.pattern.description}` });
          break;
        case 'recitation.injected':
          this.observability?.logger?.debug('Recitation injected', {
            iteration: event.iteration,
          });
          break;
      }
    });
    this.unsubscribers.push(unsubContextEngineering);

    // Interactive Planning (conversational + editable planning)
    if (isFeatureEnabled(this.config.interactivePlanning)) {
      const interactiveConfig = typeof this.config.interactivePlanning === 'object'
        ? this.config.interactivePlanning
        : {};

      this.interactivePlanner = createInteractivePlanner({
        autoCheckpoint: interactiveConfig.enableCheckpoints ?? true,
        confirmBeforeExecute: interactiveConfig.requireApproval ?? true,
        maxCheckpoints: 20,
        autoPauseAtDecisions: true,
      });

      // Forward planner events to observability (with cleanup tracking)
      const unsubInteractivePlanner = this.interactivePlanner.on(event => {
        switch (event.type) {
          case 'plan.created':
            this.observability?.logger?.info('Interactive plan created', {
              planId: event.plan.id,
              stepCount: event.plan.steps.length,
            });
            break;
          case 'step.completed':
            this.observability?.logger?.debug('Plan step completed', {
              stepId: event.step.id,
              status: event.step.status,
            });
            break;
          case 'plan.cancelled':
            this.observability?.logger?.info('Plan cancelled', { reason: event.reason });
            break;
          case 'checkpoint.created':
            this.observability?.logger?.debug('Plan checkpoint created', {
              checkpointId: event.checkpoint.id,
            });
            break;
        }
      });
      this.unsubscribers.push(unsubInteractivePlanner);
    }

    // Recursive Context (RLM - Recursive Language Models)
    // Enables on-demand context exploration for large codebases
    if (isFeatureEnabled(this.config.recursiveContext)) {
      const recursiveConfig = typeof this.config.recursiveContext === 'object'
        ? this.config.recursiveContext
        : {};

      this.recursiveContext = createRecursiveContext({
        maxDepth: recursiveConfig.maxRecursionDepth ?? 5,
        snippetTokens: recursiveConfig.maxSnippetTokens ?? 2000,
        synthesisTokens: 1000,
        totalBudget: 50000,
        cacheResults: recursiveConfig.cacheNavigationResults ?? true,
      });

      // Note: File system source should be registered when needed with proper glob/readFile functions
      // This is deferred to allow flexible configuration

      // Forward RLM events (with cleanup tracking)
      const unsubRecursiveContext = this.recursiveContext.on(event => {
        switch (event.type) {
          case 'process.started':
            this.observability?.logger?.debug('RLM process started', {
              query: event.query,
              depth: event.depth,
            });
            break;
          case 'navigation.command':
            this.observability?.logger?.debug('RLM navigation command', {
              command: event.command,
              depth: event.depth,
            });
            break;
          case 'process.completed':
            this.observability?.logger?.debug('RLM process completed', {
              stats: event.stats,
            });
            break;
          case 'budget.warning':
            this.observability?.logger?.warn('RLM budget warning', {
              remaining: event.remaining,
              total: event.total,
            });
            break;
        }
      });
      this.unsubscribers.push(unsubRecursiveContext);
    }

    // Learning Store (cross-session learning from failures)
    // Connects to the failure tracker in contextEngineering for automatic learning extraction
    if (isFeatureEnabled(this.config.learningStore)) {
      const learningConfig = typeof this.config.learningStore === 'object'
        ? this.config.learningStore
        : {};

      this.learningStore = createLearningStore({
        dbPath: learningConfig.dbPath ?? '.agent/learnings.db',
        requireValidation: learningConfig.requireValidation ?? true,
        autoValidateThreshold: learningConfig.autoValidateThreshold ?? 0.9,
        maxLearnings: learningConfig.maxLearnings ?? 500,
      });

      // Connect to the failure tracker if available
      if (this.contextEngineering) {
        const failureTracker = this.contextEngineering.getFailureTracker();
        if (failureTracker) {
          this.learningStore.connectFailureTracker(failureTracker);
        }
      }

      // Forward learning events to observability (with cleanup tracking)
      const unsubLearningStore = this.learningStore.on(event => {
        switch (event.type) {
          case 'learning.proposed':
            this.observability?.logger?.info('Learning proposed', {
              learningId: event.learning.id,
              description: event.learning.description,
            });
            this.emit({
              type: 'learning.proposed',
              learningId: event.learning.id,
              description: event.learning.description,
            });
            break;
          case 'learning.validated':
            this.observability?.logger?.info('Learning validated', {
              learningId: event.learningId,
            });
            this.emit({ type: 'learning.validated', learningId: event.learningId });
            break;
          case 'learning.applied':
            this.observability?.logger?.debug('Learning applied', {
              learningId: event.learningId,
              context: event.context,
            });
            this.emit({
              type: 'learning.applied',
              learningId: event.learningId,
              context: event.context,
            });
            break;
          case 'pattern.extracted':
            this.observability?.logger?.info('Pattern extracted as learning', {
              pattern: event.pattern.description,
              learningId: event.learning.id,
            });
            break;
        }
      });
      this.unsubscribers.push(unsubLearningStore);
    }

    // Auto-Compaction Manager (sophisticated context compaction)
    // Uses the Compactor for LLM-based summarization with threshold monitoring
    if (isFeatureEnabled(this.config.compaction)) {
      const compactionConfig = typeof this.config.compaction === 'object'
        ? this.config.compaction
        : {};

      // Create the compactor (requires provider for LLM summarization)
      this.compactor = createCompactor(this.provider, {
        enabled: true,
        tokenThreshold: compactionConfig.tokenThreshold ?? 80000,
        preserveRecentCount: compactionConfig.preserveRecentCount ?? 10,
        preserveToolResults: compactionConfig.preserveToolResults ?? true,
        summaryMaxTokens: compactionConfig.summaryMaxTokens ?? 2000,
        summaryModel: compactionConfig.summaryModel,
      });

      // Create the auto-compaction manager with threshold monitoring
      // Wire reversible compaction through contextEngineering when available
      const compactHandler = this.contextEngineering
        ? async (messages: Message[]) => {
            // Use contextEngineering's reversible compaction to preserve references
            const summarize = async (msgs: Message[]) => {
              // Use the basic compactor's summarization capability
              const result = await this.compactor!.compact(msgs);
              return result.summary;
            };
            const contextMsgs = messages.map(m => ({
              role: m.role as 'system' | 'user' | 'assistant' | 'tool',
              content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
            }));
            const result = await this.contextEngineering!.compact(contextMsgs, summarize);
            const tokensBefore = this.compactor!.estimateTokens(messages);
            const tokensAfter = this.compactor!.estimateTokens([{ role: 'assistant', content: result.summary }]);
            return {
              summary: result.summary + (result.reconstructionPrompt ? `\n\n${result.reconstructionPrompt}` : ''),
              tokensBefore,
              tokensAfter,
              preservedMessages: [{ role: 'assistant' as const, content: result.summary }],
              references: result.references,
            };
          }
        : undefined;

      // Get model's actual context window - try OpenRouter first (real API data),
      // then fall back to hardcoded ModelRegistry, then config, then default
      const openRouterContext = getModelContextLength(this.config.model || '');
      const registryInfo = modelRegistry.getModel(this.config.model || '');
      const registryContext = registryInfo?.capabilities?.maxContextTokens;
      const maxContextTokens = this.config.maxContextTokens
        ?? openRouterContext   // From OpenRouter API (e.g., GLM-4.7 = 202752)
        ?? registryContext     // From hardcoded registry (Claude, GPT-4o, etc.)
        ?? 200000;             // Fallback to 200K

      this.autoCompactionManager = createAutoCompactionManager(this.compactor, {
        mode: compactionConfig.mode ?? 'auto',
        warningThreshold: 0.70,       // Warn at 70% of model's context
        autoCompactThreshold: 0.80,   // Compact at 80% (changed from 0.90)
        hardLimitThreshold: 0.95,     // Hard limit at 95%
        preserveRecentUserMessages: Math.ceil((compactionConfig.preserveRecentCount ?? 10) / 2),
        preserveRecentAssistantMessages: Math.ceil((compactionConfig.preserveRecentCount ?? 10) / 2),
        cooldownMs: 60000, // 1 minute cooldown
        maxContextTokens,  // Dynamic from model registry or config
        compactHandler, // Use reversible compaction when contextEngineering is available
      });

      // Forward compactor events to observability (with cleanup tracking)
      const unsubCompactor = this.compactor.on(event => {
        switch (event.type) {
          case 'compaction.start':
            this.observability?.logger?.info('Compaction started', {
              messageCount: event.messageCount,
            });
            break;
          case 'compaction.complete':
            this.observability?.logger?.info('Compaction complete', {
              tokensBefore: event.result.tokensBefore,
              tokensAfter: event.result.tokensAfter,
              compactedCount: event.result.compactedCount,
            });
            break;
          case 'compaction.error':
            this.observability?.logger?.error('Compaction error', {
              error: event.error,
            });
            break;
        }
      });
      this.unsubscribers.push(unsubCompactor);

      // Forward auto-compaction events (with cleanup tracking)
      const unsubAutoCompaction = this.autoCompactionManager.on((event: AutoCompactionEvent) => {
        switch (event.type) {
          case 'autocompaction.warning':
            this.observability?.logger?.warn('Context approaching limit', {
              currentTokens: event.currentTokens,
              ratio: event.ratio,
            });
            this.emit({
              type: 'compaction.warning',
              currentTokens: event.currentTokens,
              threshold: Math.round(event.ratio * (this.config.maxContextTokens ?? 200000)),
            });
            break;
          case 'autocompaction.triggered':
            this.observability?.logger?.info('Auto-compaction triggered', {
              mode: event.mode,
              currentTokens: event.currentTokens,
            });
            break;
          case 'autocompaction.completed':
            this.observability?.logger?.info('Auto-compaction completed', {
              tokensBefore: event.tokensBefore,
              tokensAfter: event.tokensAfter,
              reduction: event.reduction,
            });
            this.emit({
              type: 'compaction.auto',
              tokensBefore: event.tokensBefore,
              tokensAfter: event.tokensAfter,
              messagesCompacted: event.tokensBefore - event.tokensAfter,
            });
            break;
          case 'autocompaction.hard_limit':
            this.observability?.logger?.error('Context hard limit reached', {
              currentTokens: event.currentTokens,
              ratio: event.ratio,
            });
            break;
          case 'autocompaction.emergency_truncate':
            this.observability?.logger?.warn('Emergency truncation performed', {
              reason: event.reason,
              messagesBefore: event.messagesBefore,
              messagesAfter: event.messagesAfter,
            });
            break;
        }
      });
      this.unsubscribers.push(unsubAutoCompaction);
    }

    // Note: FileChangeTracker requires a database instance which is not
    // available at this point. Use initFileChangeTracker() to enable it
    // after the agent is constructed with a database reference.
    // This allows the feature to be optional and not require SQLite at all times.
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

    const startTime = Date.now();

    // Create cancellation context if enabled
    const cancellationConfig = isFeatureEnabled(this.config.cancellation) ? this.config.cancellation : null;
    const cancellationToken = this.cancellation?.createContext(
      cancellationConfig?.defaultTimeout || undefined
    );

    // Start tracing
    const traceId = this.observability?.tracer?.startTrace('agent.run') || `trace-${Date.now()}`;
    this.emit({ type: 'start', task, traceId });
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
      // Check for cancellation before starting
      cancellationToken?.throwIfCancellationRequested();

      // Classify task complexity for scaling guidance
      this.lastComplexityAssessment = classifyComplexity(task, {
        hasActivePlan: !!this.state.plan,
      });

      // Check if swarm mode should handle this task
      if (this.swarmOrchestrator) {
        const swarmResult = await this.runSwarm(task);
        // Store swarm summary as an assistant message for the response
        this.state.messages.push({ role: 'assistant', content: swarmResult.summary });
      } else if (this.planning?.shouldPlan(task)) {
        // Check if planning is needed
        await this.createAndExecutePlan(task);
      } else {
        await this.executeDirectly(task);
      }

      // Get final response - find the LAST assistant message (not just check if last message is assistant)
      const assistantMessages = this.state.messages.filter(m => m.role === 'assistant');
      const lastAssistantMessage = assistantMessages[assistantMessages.length - 1];
      const response = typeof lastAssistantMessage?.content === 'string'
        ? lastAssistantMessage.content
        : '';

      // Finalize
      const duration = Date.now() - startTime;
      this.state.metrics.duration = duration;
      this.state.metrics.successCount = (this.state.metrics.successCount ?? 0) + 1;

      await this.observability?.tracer?.endTrace();

      const result: AgentResult = {
        success: true,
        response,
        metrics: this.getMetrics(),
        messages: this.state.messages,
        traceId,
        plan: this.state.plan,
      };

      this.emit({ type: 'complete', result });
      this.observability?.logger?.info('Agent completed', { duration, success: true });

      // Lesson 26: End trace capture
      // If task is active (REPL mode), end the task. Otherwise end the session (single-task mode).
      if (this.traceCollector?.isTaskActive()) {
        await this.traceCollector.endTask({ success: true, output: response });
      } else if (this.traceCollector?.isSessionActive()) {
        await this.traceCollector.endSession({ success: true, output: response });
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

        return {
          success: false,
          response: '',
          error: `Cancelled: ${error.message}`,
          metrics: this.getMetrics(),
          messages: this.state.messages,
          traceId,
        };
      }

      this.observability?.tracer?.recordError(error);
      await this.observability?.tracer?.endTrace();
      this.state.metrics.failureCount = (this.state.metrics.failureCount ?? 0) + 1;

      this.emit({ type: 'error', error: error.message });
      this.observability?.logger?.error('Agent failed', { error: error.message });

      // Lesson 26: End trace capture on error
      if (this.traceCollector?.isTaskActive()) {
        await this.traceCollector.endTask({ success: false, failureReason: error.message });
      } else if (this.traceCollector?.isSessionActive()) {
        await this.traceCollector.endSession({ success: false, failureReason: error.message });
      }

      return {
        success: false,
        response: '',
        error: error.message,
        metrics: this.getMetrics(),
        messages: this.state.messages,
        traceId,
      };
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
      } catch (err) {
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
      unsubTrace?.();
      unsubBridge();
      bridge.close();
      unsubSwarm();
    }
  }

  /**
   * Execute a task directly without planning (delegates to core/execution-loop).
   */
  private async executeDirectly(task: string): Promise<void> {
    const messages = this.buildMessages(task);
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
  private buildMessages(task: string): Message[] {
    const messages: Message[] = [];

    // Gather all context components
    const rulesContent = this.rules?.getRulesContent() ?? '';
    const skillsPrompt = this.skillManager?.getActiveSkillsPrompt() ?? '';
    const memoryContext = this.memory?.getContextStrings(task) ?? [];

    // Get relevant learnings from past sessions
    const learningsContext = this.learningStore?.getLearningContext({
      query: task,
      maxLearnings: 5,
    }) ?? '';

    // Budget-aware codebase context selection
    let codebaseContextStr = '';
    if (this.codebaseContext) {
      // Calculate available budget for codebase context
      // Reserve tokens for: rules (~2000), tools (~2500), memory (~1000), conversation (~5000)
      const reservedTokens = 10500;
      const maxContextTokens = (this.config.maxContextTokens ?? 80000) - reservedTokens;
      const codebaseBudget = Math.min(maxContextTokens * 0.3, 15000); // Up to 30% or 15K tokens

      const repoMap = this.codebaseContext.getRepoMap();

      // Lazy: trigger analysis on first system prompt build, ready by next turn
      if (!repoMap && !this.codebaseAnalysisTriggered) {
        this.codebaseAnalysisTriggered = true;
        this.codebaseContext.analyze().catch(() => { /* non-fatal */ });
      }

      if (repoMap) {
        try {
          const selection = this.selectRelevantCodeSync(task, codebaseBudget);
          if (selection.chunks.length > 0) {
            codebaseContextStr = buildContextFromChunks(selection.chunks, {
              includeFilePaths: true,
              includeSeparators: true,
              maxTotalTokens: codebaseBudget,
            });
          } else {
            // Fallback: lightweight repo map when task-specific selection finds nothing
            codebaseContextStr = generateLightweightRepoMap(repoMap, codebaseBudget);
          }
        } catch {
          // Selection error — skip
        }
      }
    }

    // Build tool descriptions
    let toolDescriptions = '';
    if (this.tools.size > 0) {
      const toolLines: string[] = [];
      for (const tool of this.tools.values()) {
        toolLines.push(`- ${tool.name}: ${tool.description}`);
      }
      toolDescriptions = toolLines.join('\n');
    }

    // Add MCP tool summaries
    if (this.config.mcpToolSummaries && this.config.mcpToolSummaries.length > 0) {
      const mcpLines = this.config.mcpToolSummaries.map(
        s => `- ${s.name}: ${s.description}`
      );
      if (toolDescriptions) {
        toolDescriptions += '\n\nMCP tools (call directly, they auto-load):\n' + mcpLines.join('\n');
      } else {
        toolDescriptions = 'MCP tools (call directly, they auto-load):\n' + mcpLines.join('\n');
      }
    }

    // Build system prompt using cache-aware builder if available (Trick P)
    // Combine memory, learnings, codebase context, and environment facts
    const combinedContextParts = [
      // Environment facts — temporal/platform grounding (prevents stale date hallucinations)
      formatFactsBlock(getEnvironmentFacts()),
      ...(memoryContext.length > 0 ? memoryContext : []),
      ...(learningsContext ? [learningsContext] : []),
      ...(codebaseContextStr ? [`\n## Relevant Code\n${codebaseContextStr}`] : []),
    ];

    // Inject thinking directives and scaling guidance for non-simple tasks
    if (this.lastComplexityAssessment) {
      const thinkingPrompt = getThinkingSystemPrompt(this.lastComplexityAssessment.tier);
      if (thinkingPrompt) {
        combinedContextParts.push(thinkingPrompt);
      }
      if (this.lastComplexityAssessment.tier !== 'simple') {
        combinedContextParts.push(getScalingGuidance(this.lastComplexityAssessment));
      }
    }

    const combinedContext = combinedContextParts.join('\n');

    const promptOptions = {
      rules: rulesContent + (skillsPrompt ? '\n\n' + skillsPrompt : ''),
      tools: toolDescriptions,
      memory: combinedContext.length > 0 ? combinedContext : undefined,
      dynamic: {
        mode: this.modeManager?.getMode() ?? 'default',
      },
    };

    if (this.contextEngineering) {
      // Build cache-aware system prompt with cache_control markers (Improvement P1).
      // Store structured blocks for callLLM() to inject as MessageWithContent.
      // The string version is still used for token estimation and debugging.
      const cacheableBlocks = this.contextEngineering.buildCacheableSystemPrompt(promptOptions);

      // Safety check: ensure we have content (empty array = no cache context configured)
      if (cacheableBlocks.length === 0 || cacheableBlocks.every(b => b.text.trim().length === 0)) {
        this.cacheableSystemBlocks = null;
        messages.push({ role: 'system', content: this.config.systemPrompt || 'You are a helpful AI assistant.' });
      } else {
        // Store cacheable blocks for provider injection
        this.cacheableSystemBlocks = cacheableBlocks;
        // Push a regular string Message for backward compatibility (token estimation, etc.)
        const flatPrompt = cacheableBlocks.map(b => b.text).join('');
        messages.push({ role: 'system', content: flatPrompt });
      }
    } else {
      // Fallback: manual concatenation (original behavior) — no cache markers
      this.cacheableSystemBlocks = null;
      let systemPrompt = this.config.systemPrompt;
      if (rulesContent) systemPrompt += '\n\n' + rulesContent;
      if (skillsPrompt) systemPrompt += skillsPrompt;
      if (combinedContext.length > 0) {
        systemPrompt += '\n\nRelevant context:\n' + combinedContext;
      }
      if (toolDescriptions) {
        systemPrompt += '\n\nAvailable tools:\n' + toolDescriptions;
      }

      // Safety check: ensure system prompt is not empty
      if (!systemPrompt || systemPrompt.trim().length === 0) {
        log.warn('Empty system prompt detected, using fallback');
        systemPrompt = this.config.systemPrompt || 'You are a helpful AI assistant.';
      }

      messages.push({ role: 'system', content: systemPrompt });
    }

    // Add existing conversation
    for (const msg of this.state.messages) {
      if (msg.role !== 'system') {
        messages.push(msg);
      }
    }

    // Add current task
    messages.push({ role: 'user', content: task });

    return messages;
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

  /**
   * Get current state.
   */
  getState(): AgentState {
    return { ...this.state };
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
    if (!this.fileChangeTracker) {
      return -1;
    }

    return this.fileChangeTracker.recordChange({
      filePath: params.filePath,
      operation: params.operation,
      contentBefore: params.contentBefore,
      contentAfter: params.contentAfter,
      turnNumber: this.state.iteration,
      toolCallId: params.toolCallId,
    });
  }

  /**
   * Undo the last change to a specific file.
   * Returns null if file change tracking is not enabled.
   */
  async undoLastFileChange(filePath: string): Promise<import('./integrations/index.js').UndoResult | null> {
    if (!this.fileChangeTracker) {
      return null;
    }
    return this.fileChangeTracker.undoLastChange(filePath);
  }

  /**
   * Undo all changes in the current turn.
   * Returns null if file change tracking is not enabled.
   */
  async undoCurrentTurn(): Promise<import('./integrations/index.js').UndoResult[] | null> {
    if (!this.fileChangeTracker) {
      return null;
    }
    return this.fileChangeTracker.undoTurn(this.state.iteration);
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
    this.state = {
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

    this.memory?.clear();
    this.observability?.metrics?.reset();
    this.planning?.clearPlan();

    this.observability?.logger?.info('Agent state reset');
  }

  /**
   * Load messages from a previous session.
   * @deprecated Use loadState() for full state restoration
   */
  loadMessages(messages: Message[]): void {
    this.state.messages = [...messages];

    // Sync to threadManager if enabled
    if (this.threadManager) {
      const thread = this.threadManager.getActiveThread();
      thread.messages = [...messages];
    }

    this.observability?.logger?.info('Messages loaded', { count: messages.length });
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
    return {
      messages: this.state.messages,
      iteration: this.state.iteration,
      metrics: { ...this.state.metrics },
      plan: this.state.plan ? { ...this.state.plan } : undefined,
      memoryContext: this.state.memoryContext ? [...this.state.memoryContext] : undefined,
    };
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
    const errors: string[] = [];
    const warnings: string[] = [];

    // Check if data is an object
    if (!data || typeof data !== 'object') {
      errors.push('Checkpoint data must be an object');
      return { valid: false, errors, warnings, sanitized: null };
    }

    const checkpoint = data as Record<string, unknown>;

    // Validate messages array (required)
    if (!checkpoint.messages) {
      errors.push('Checkpoint missing required "messages" field');
    } else if (!Array.isArray(checkpoint.messages)) {
      errors.push('Checkpoint "messages" must be an array');
    } else {
      // Validate each message has required fields
      for (let i = 0; i < checkpoint.messages.length; i++) {
        const msg = checkpoint.messages[i] as Record<string, unknown>;
        if (!msg || typeof msg !== 'object') {
          errors.push(`Message at index ${i} is not an object`);
          continue;
        }
        if (!msg.role || typeof msg.role !== 'string') {
          errors.push(`Message at index ${i} missing valid "role" field`);
        }
        if (msg.content !== undefined && msg.content !== null && typeof msg.content !== 'string') {
          // Content can be undefined for tool call messages
          warnings.push(`Message at index ${i} has non-string content (type: ${typeof msg.content})`);
        }
      }
    }

    // Validate iteration (optional but should be non-negative number)
    if (checkpoint.iteration !== undefined) {
      if (typeof checkpoint.iteration !== 'number' || checkpoint.iteration < 0) {
        warnings.push(`Invalid iteration value: ${checkpoint.iteration}, will use default`);
      }
    }

    // Validate metrics (optional)
    if (checkpoint.metrics !== undefined && checkpoint.metrics !== null) {
      if (typeof checkpoint.metrics !== 'object') {
        warnings.push('Metrics field is not an object, will be ignored');
      }
    }

    // Validate memoryContext (optional)
    if (checkpoint.memoryContext !== undefined && checkpoint.memoryContext !== null) {
      if (!Array.isArray(checkpoint.memoryContext)) {
        warnings.push('memoryContext is not an array, will be ignored');
      }
    }

    // If we have critical errors, fail validation
    if (errors.length > 0) {
      return { valid: false, errors, warnings, sanitized: null };
    }

    // Build sanitized checkpoint
    const messages = (checkpoint.messages as Message[]).filter(
      (msg): msg is Message => msg && typeof msg === 'object' && typeof msg.role === 'string'
    );

    const sanitized = {
      messages,
      iteration: typeof checkpoint.iteration === 'number' && checkpoint.iteration >= 0
        ? checkpoint.iteration
        : Math.floor(messages.length / 2),
      metrics: typeof checkpoint.metrics === 'object' && checkpoint.metrics !== null
        ? checkpoint.metrics as Partial<AgentMetrics>
        : undefined,
      plan: checkpoint.plan as AgentPlan | undefined,
      memoryContext: Array.isArray(checkpoint.memoryContext)
        ? checkpoint.memoryContext as string[]
        : undefined,
    };

    return { valid: true, errors, warnings, sanitized };
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
    // Validate checkpoint data
    const validation = this.validateCheckpoint(savedState);

    // Log warnings
    for (const warning of validation.warnings) {
      log.warn('Checkpoint validation warning', { warning });
      this.observability?.logger?.warn('Checkpoint validation warning', { warning });
    }

    // Fail on validation errors
    if (!validation.valid || !validation.sanitized) {
      const errorMsg = `Invalid checkpoint: ${validation.errors.join('; ')}`;
      this.observability?.logger?.error('Checkpoint validation failed', { errors: validation.errors });
      throw new Error(errorMsg);
    }

    // Use sanitized data
    const sanitized = validation.sanitized;

    // Restore messages
    this.state.messages = [...sanitized.messages];

    // Restore iteration (already validated/defaulted in sanitized)
    this.state.iteration = sanitized.iteration;

    // Restore metrics (merge with defaults)
    if (sanitized.metrics) {
      this.state.metrics = {
        totalTokens: sanitized.metrics.totalTokens ?? 0,
        inputTokens: sanitized.metrics.inputTokens ?? 0,
        outputTokens: sanitized.metrics.outputTokens ?? 0,
        estimatedCost: sanitized.metrics.estimatedCost ?? 0,
        llmCalls: sanitized.metrics.llmCalls ?? 0,
        toolCalls: sanitized.metrics.toolCalls ?? 0,
        duration: sanitized.metrics.duration ?? 0,
        reflectionAttempts: sanitized.metrics.reflectionAttempts,
        successCount: sanitized.metrics.successCount ?? 0,
        failureCount: sanitized.metrics.failureCount ?? 0,
        cancelCount: sanitized.metrics.cancelCount ?? 0,
        retryCount: sanitized.metrics.retryCount ?? 0,
      };
    }

    // Restore plan if present
    if (sanitized.plan) {
      this.state.plan = { ...sanitized.plan };
      // Sync with planning manager if enabled
      if (this.planning) {
        this.planning.loadPlan(sanitized.plan);
      }
    }

    // Restore memory context if present
    if (sanitized.memoryContext) {
      this.state.memoryContext = [...sanitized.memoryContext];
    }

    // Sync to threadManager if enabled
    if (this.threadManager) {
      const thread = this.threadManager.getActiveThread();
      thread.messages = [...sanitized.messages];
    }

    this.observability?.logger?.info('State loaded', {
      messageCount: sanitized.messages.length,
      iteration: this.state.iteration,
      hasPlan: !!sanitized.plan,
      hasMemoryContext: !!sanitized.memoryContext,
    });
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

  /**
   * Detect "future-intent" responses that imply the model has not completed work.
   */
  private detectIncompleteActionResponse(content: string): boolean {
    const trimmed = content.trim();
    if (!trimmed) {
      return false;
    }

    const lower = trimmed.toLowerCase();
    const futureIntentPatterns: RegExp[] = [
      /^(now|next|then)\s+(i\s+will|i'll|let me)\b/,
      /^i\s+(will|am going to|can)\b/,
      /^(let me|i'll|i will)\s+(create|write|save|do|make|generate|start)\b/,
      /^(now|next|then)\s+i(?:'ll| will)\b/,
    ];
    const completionSignals = /\b(done|completed|finished|here is|created|saved|wrote)\b/;

    return futureIntentPatterns.some(pattern => pattern.test(lower)) && !completionSignals.test(lower);
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
// FACTORY
// =============================================================================

/**
 * Create a production agent with the given configuration.
 */
export function createProductionAgent(
  config: Partial<ProductionAgentConfig> & { provider: LLMProvider }
): ProductionAgent {
  return new ProductionAgent(config);
}

// =============================================================================
// BUILDER PATTERN
// =============================================================================

/**
 * Builder for creating customized production agents.
 */
export class ProductionAgentBuilder {
  private config: Partial<ProductionAgentConfig> = {};

  /**
   * Set the LLM provider.
   */
  provider(provider: LLMProvider): this {
    this.config.provider = provider;
    return this;
  }

  /**
   * Set the model.
   */
  model(model: string): this {
    this.config.model = model;
    return this;
  }

  /**
   * Set the system prompt.
   */
  systemPrompt(prompt: string): this {
    this.config.systemPrompt = prompt;
    return this;
  }

  /**
   * Add tools.
   */
  tools(tools: ToolDefinition[]): this {
    this.config.tools = tools;
    return this;
  }

  /**
   * Configure hooks.
   */
  hooks(config: ProductionAgentConfig['hooks']): this {
    this.config.hooks = config;
    return this;
  }

  /**
   * Configure plugins.
   */
  plugins(config: ProductionAgentConfig['plugins']): this {
    this.config.plugins = config;
    return this;
  }

  /**
   * Configure memory.
   */
  memory(config: ProductionAgentConfig['memory']): this {
    this.config.memory = config;
    return this;
  }

  /**
   * Configure planning.
   */
  planning(config: ProductionAgentConfig['planning']): this {
    this.config.planning = config;
    return this;
  }

  /**
   * Configure reflection.
   */
  reflection(config: ProductionAgentConfig['reflection']): this {
    this.config.reflection = config;
    return this;
  }

  /**
   * Configure observability.
   */
  observability(config: ProductionAgentConfig['observability']): this {
    this.config.observability = config;
    return this;
  }

  /**
   * Configure sandbox.
   */
  sandbox(config: ProductionAgentConfig['sandbox']): this {
    this.config.sandbox = config;
    return this;
  }

  /**
   * Configure human-in-the-loop.
   */
  humanInLoop(config: ProductionAgentConfig['humanInLoop']): this {
    this.config.humanInLoop = config;
    return this;
  }

  /**
   * Configure routing.
   */
  routing(config: ProductionAgentConfig['routing']): this {
    this.config.routing = config;
    return this;
  }

  /**
   * Configure multi-agent coordination (Lesson 17).
   */
  multiAgent(config: ProductionAgentConfig['multiAgent']): this {
    this.config.multiAgent = config;
    return this;
  }

  /**
   * Add a role to multi-agent config.
   */
  addRole(role: AgentRoleConfig): this {
    // Handle undefined, false, or disabled config
    if (!this.config.multiAgent) {
      this.config.multiAgent = { enabled: true, roles: [] };
    }
    // Ensure roles array exists
    const multiAgentConfig = this.config.multiAgent as MultiAgentConfig;
    if (!multiAgentConfig.roles) {
      multiAgentConfig.roles = [];
    }
    multiAgentConfig.roles.push(role);
    return this;
  }

  /**
   * Configure ReAct pattern (Lesson 18).
   */
  react(config: ProductionAgentConfig['react']): this {
    this.config.react = config;
    return this;
  }

  /**
   * Configure execution policies (Lesson 23).
   */
  executionPolicy(config: ProductionAgentConfig['executionPolicy']): this {
    this.config.executionPolicy = config;
    return this;
  }

  /**
   * Configure thread management (Lesson 24).
   */
  threads(config: ProductionAgentConfig['threads']): this {
    this.config.threads = config;
    return this;
  }

  /**
   * Configure skills system.
   */
  skills(config: ProductionAgentConfig['skills']): this {
    this.config.skills = config;
    return this;
  }

  /**
   * Set max iterations.
   */
  maxIterations(max: number): this {
    this.config.maxIterations = max;
    return this;
  }

  /**
   * Set timeout.
   */
  timeout(ms: number): this {
    this.config.timeout = ms;
    return this;
  }

  /**
   * Disable a feature.
   */
  disable(feature: keyof Omit<ProductionAgentConfig, 'provider' | 'tools' | 'systemPrompt' | 'model' | 'maxIterations' | 'timeout'>): this {
    (this.config as Record<string, unknown>)[feature] = false;
    return this;
  }

  /**
   * Build the agent.
   */
  build(): ProductionAgent {
    if (!this.config.provider) {
      throw new Error('Provider is required');
    }
    return new ProductionAgent(this.config as Partial<ProductionAgentConfig> & { provider: LLMProvider });
  }
}

/**
 * Start building a production agent.
 */
export function buildAgent(): ProductionAgentBuilder {
  return new ProductionAgentBuilder();
}

// =============================================================================
// Re-export from core for backward compatibility
export { parseStructuredClosureReport } from './core/index.js';
