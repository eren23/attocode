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
  ToolCall,
  ToolResult,
  ToolDefinition,
  AgentState,
  AgentMetrics,
  AgentPlan,
  AgentResult,
  AgentEvent,
  AgentEventListener,
  AgentRoleConfig,
  ChatResponse,
  MultiAgentConfig,
} from './types.js';

import {
  buildConfig,
  isFeatureEnabled,
  getEnabledFeatures,
  getSubagentTimeout,
  getSubagentMaxIterations,
} from './defaults.js';

import {
  ModeManager,
  createModeManager,
  formatModeList,
  parseMode,
  isWriteTool,
  isBashWriteCommand,
  calculateTaskSimilarity,
  SUBAGENT_PLAN_MODE_ADDITION,
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
  SUBAGENT_BUDGET,
  TIMEOUT_WRAPUP_PROMPT,
  AgentRegistry,
  createAgentRegistry,
  filterToolsForAgent,
  formatAgentList,
  CancellationManager,
  createCancellationManager,
  isCancellationError,
  CancellationError,
  createTimeoutToken,
  createLinkedToken,
  createGracefulTimeout,
  race,
  ResourceManager,
  createResourceManager,
  combinedShouldContinue,
  isResourceLimitError,
  LSPManager,
  createLSPManager,
  SemanticCacheManager,
  createSemanticCacheManager,
  SkillManager,
  createSkillManager,
  formatSkillList,
  ContextEngineeringManager,
  createContextEngineering,
  stableStringify,
  CodebaseContextManager,
  createCodebaseContext,
  buildContextFromChunks,
  type ExecutionBudget,
  type AgentRole,
  type TeamTask,
  type TeamResult,
  type ReActTrace,
  type Checkpoint,
  type AgentDefinition,
  type LoadedAgent,
  type SpawnResult,
  type StructuredClosureReport,
  type CancellationTokenType,
  type Skill,
  type ContextEngineeringConfig,
  type CodebaseContextConfig,
  type SelectionOptions,
  PendingPlanManager,
  createPendingPlanManager,
  type PendingPlan,
  type ProposedChange,
  // Interactive Planning
  InteractivePlanner,
  createInteractivePlanner,
  // Recursive Context (RLM)
  RecursiveContextManager,
  createRecursiveContext,
  // Learning Store (cross-session learning)
  LearningStore,
  createLearningStore,
  // Compaction
  Compactor,
  createCompactor,
  // Auto-Compaction Manager
  AutoCompactionManager,
  createAutoCompactionManager,
  type AutoCompactionEvent,
  // File Change Tracker (undo capability)
  FileChangeTracker,
  createFileChangeTracker,
  // Capabilities Registry (unified discovery)
  CapabilitiesRegistry,
  createCapabilitiesRegistry,
  // Shared Blackboard (subagent coordination)
  SharedBlackboard,
  createSharedBlackboard,
  type BlackboardConfig,
  // Task Management
  TaskManager,
  createTaskManager,
  type SQLiteStore,
} from './integrations/index.js';

// Lesson 26: Tracing & Evaluation integration
import { TraceCollector, createTraceCollector } from './tracing/trace-collector.js';

// Model registry for context window limits
import { modelRegistry } from './costs/index.js';
import { getModelContextLength } from './integrations/openrouter-pricing.js';

// Spawn agent tools for LLM-driven subagent delegation
import {
  createBoundSpawnAgentTool,
  createBoundSpawnAgentsParallelTool,
} from './tools/agent.js';

// Task tools for Claude Code-style task management
import {
  createTaskTools,
} from './tools/tasks.js';

// =============================================================================
// PRODUCTION AGENT
// =============================================================================

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
  private blackboard: SharedBlackboard | null = null;
  private taskManager: TaskManager | null = null;
  private store: SQLiteStore | null = null;

  // Duplicate spawn prevention - tracks recently spawned tasks to prevent doom loops
  // Map<taskKey, { timestamp: number; result: string; queuedChanges: number }>
  private spawnedTasks = new Map<string, { timestamp: number; result: string; queuedChanges: number }>();
  private static readonly SPAWN_DEDUP_WINDOW_MS = 60000; // 60 seconds

  // Parent iteration tracking for total budget calculation
  private parentIterations = 0;

  // External cancellation token (for subagent timeout propagation)
  // When set, the agent will check this token in addition to its own cancellation manager
  private externalCancellationToken: CancellationTokenType | null = null;

  // Graceful wrapup support (for subagent timeout wrapup phase)
  private wrapupRequested = false;
  private wrapupReason: string | null = null;

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
      console.log(`[ProductionAgent] Initializing with features: ${features.join(', ')}`);
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
        isFeatureEnabled(this.config.humanInLoop) ? this.config.humanInLoop : false
      );
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
          console.warn('[ProductionAgent] Failed to load rules:', err);
        })
      );
    }

    // Economics System (Token Budget) - always enabled
    // Use custom budget if provided (subagents use SUBAGENT_BUDGET), otherwise STANDARD_BUDGET
    const baseBudget = this.config.budget ?? STANDARD_BUDGET;
    this.economics = new ExecutionEconomicsManager({
      ...baseBudget,
      // Use maxIterations from config as absolute safety cap
      maxIterations: this.config.maxIterations,
      targetIterations: Math.min(baseBudget.targetIterations ?? 20, this.config.maxIterations),
    });

    // Agent Registry - always enabled for subagent support
    this.agentRegistry = new AgentRegistry();
    // Load user agents asynchronously - tracked for ensureReady()
    this.initPromises.push(
      this.agentRegistry.loadUserAgents().catch(err => {
        console.warn('[ProductionAgent] Failed to load user agents:', err);
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
            console.warn('[ProductionAgent] Failed to load skills:', err);
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
      await this.traceCollector?.startSession(traceSessionId, task, this.config.model || 'default', {});
    }

    try {
      // Check for cancellation before starting
      cancellationToken?.throwIfCancellationRequested();

      // Check if planning is needed
      if (this.planning?.shouldPlan(task)) {
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
   * Execute a task directly without planning.
   */
  private async executeDirectly(task: string): Promise<void> {
    // Build messages
    const messages = this.buildMessages(task);

    // Reset economics for new task
    this.economics?.reset();

    // Reflection configuration
    const reflectionConfig = this.config.reflection;
    const reflectionEnabled = isFeatureEnabled(reflectionConfig);
    const autoReflect = reflectionEnabled && reflectionConfig.autoReflect;
    const maxReflectionAttempts = reflectionEnabled
      ? (reflectionConfig.maxAttempts || 3)
      : 1;
    const confidenceThreshold = reflectionEnabled
      ? (reflectionConfig.confidenceThreshold || 0.8)
      : 0.8;

    let reflectionAttempt = 0;
    let lastResponse = '';
    let incompleteActionRetries = 0;
    const requestedArtifact = this.extractRequestedArtifact(task);
    const executedToolNames = new Set<string>();

    // Outer loop for reflection (if enabled)
    while (reflectionAttempt < maxReflectionAttempts) {
      reflectionAttempt++;

      // Agent loop - now uses economics-based budget checking
      while (true) {
        this.state.iteration++;

        // Record iteration start for tracing
        this.traceCollector?.record({
          type: 'iteration.start',
          data: { iterationNumber: this.state.iteration },
        });

        // =======================================================================
        // CANCELLATION CHECK
        // Checks internal cancellation (ESC key) — always immediate.
        // External cancellation (parent timeout) is checked after economics
        // to allow graceful wrapup when wrapup has been requested.
        // =======================================================================
        if (this.cancellation?.isCancelled) {
          this.cancellation.token.throwIfCancellationRequested();
        }

        // =======================================================================
        // RESOURCE CHECK - system resource limits
        // =======================================================================
        if (this.resourceManager) {
          const resourceCheck = this.resourceManager.check();

          if (!resourceCheck.canContinue) {
            this.observability?.logger?.warn('Resource limit reached', {
              status: resourceCheck.status,
              message: resourceCheck.message,
            });
            this.emit({ type: 'error', error: resourceCheck.message || 'Resource limit exceeded' });
            break;
          }

          // Log warnings for elevated usage
          if (resourceCheck.status === 'warning' || resourceCheck.status === 'critical') {
            this.observability?.logger?.info(`Resource status: ${resourceCheck.status}`, {
              message: resourceCheck.message,
            });
          }
        }

        // =======================================================================
        // ECONOMICS CHECK (Token Budget) - replaces hard iteration limit
        // With recovery: try compaction before giving up on token limits
        // =======================================================================
        let forceTextOnly = false;  // Track if we should skip tool execution
        let budgetInjectedPrompt: string | undefined;

        if (this.economics) {
          const budgetCheck = this.economics.checkBudget();

          // Capture forceTextOnly and injectedPrompt for later use
          forceTextOnly = budgetCheck.forceTextOnly ?? false;
          budgetInjectedPrompt = budgetCheck.injectedPrompt;

          if (!budgetCheck.canContinue) {
            // ===================================================================
            // RECOVERY ATTEMPT: Try emergency context reduction before giving up
            // Only for token-based limits, not iteration limits
            // ===================================================================
            const isTokenLimit = budgetCheck.budgetType === 'tokens' || budgetCheck.budgetType === 'cost';
            const alreadyTriedRecovery = (this.state as { _recoveryAttempted?: boolean })._recoveryAttempted === true;

            if (isTokenLimit && !alreadyTriedRecovery) {
              this.observability?.logger?.info('Budget limit reached, attempting recovery via context reduction', {
                reason: budgetCheck.reason,
                percentUsed: budgetCheck.percentUsed,
              });

              this.emit({
                type: 'resilience.retry',
                reason: 'budget_limit_compaction',
                attempt: 1,
                maxAttempts: 1,
              });
              this.state.metrics.retryCount = (this.state.metrics.retryCount ?? 0) + 1;

              // Mark that we've attempted recovery to prevent infinite loops
              (this.state as { _recoveryAttempted?: boolean })._recoveryAttempted = true;

              const tokensBefore = this.estimateContextTokens(messages);

              // Step 1: Compact tool outputs aggressively
              this.compactToolOutputs();

              // Step 2: Emergency truncation - keep system + last N messages
              const PRESERVE_RECENT = 10;
              if (messages.length > PRESERVE_RECENT + 2) {
                const systemMessage = messages.find(m => m.role === 'system');
                const recentMessages = messages.slice(-(PRESERVE_RECENT));

                // Rebuild message array
                messages.length = 0;
                if (systemMessage) {
                  messages.push(systemMessage);
                }
                messages.push({
                  role: 'system',
                  content: `[CONTEXT REDUCED: Earlier messages were removed to stay within budget. Conversation continues from recent context.]`,
                });
                messages.push(...recentMessages);

                // Update state messages too
                this.state.messages.length = 0;
                this.state.messages.push(...messages);
              }

              const tokensAfter = this.estimateContextTokens(messages);
              const reduction = Math.round((1 - tokensAfter / tokensBefore) * 100);

              if (tokensAfter < tokensBefore * 0.8) {
                // Significant reduction achieved
                this.observability?.logger?.info('Context reduction successful, continuing execution', {
                  tokensBefore,
                  tokensAfter,
                  reduction,
                });

                this.emit({
                  type: 'resilience.recovered',
                  reason: 'budget_limit_compaction',
                  attempts: 1,
                });

                this.emit({
                  type: 'compaction.auto',
                  tokensBefore,
                  tokensAfter,
                  messagesCompacted: tokensBefore - tokensAfter,
                });

                // Continue execution instead of breaking
                continue;
              }

              this.observability?.logger?.warn('Context reduction insufficient', {
                tokensBefore,
                tokensAfter,
                reduction,
              });
            }

            // Hard limit reached and recovery failed (or not applicable)
            this.observability?.logger?.warn('Budget limit reached', {
              reason: budgetCheck.reason,
              budgetType: budgetCheck.budgetType,
            });

            // Emit appropriate event
            if (budgetCheck.budgetType === 'iterations') {
              const totalIter = this.getTotalIterations();
              const iterMsg = this.parentIterations > 0
                ? `${this.state.iteration} + ${this.parentIterations} parent = ${totalIter}`
                : `${this.state.iteration}`;
              this.emit({ type: 'error', error: `Max iterations reached (${iterMsg})` });
            } else {
              this.emit({ type: 'error', error: budgetCheck.reason || 'Budget exceeded' });
            }
            break;
          }

          // Check for soft limits and potential extension
          if (budgetCheck.isSoftLimit && budgetCheck.suggestedAction === 'request_extension') {
            this.observability?.logger?.info('Approaching budget limit', {
              reason: budgetCheck.reason,
              percentUsed: budgetCheck.percentUsed,
            });
            // Could request extension here if handler is set
          }
        } else {
          // Fallback to simple iteration check if economics not available
          // Use getTotalIterations() to account for parent iterations (subagent hierarchy)
          if (this.getTotalIterations() >= this.config.maxIterations) {
            this.observability?.logger?.warn('Max iterations reached', {
              iteration: this.state.iteration,
              parentIterations: this.parentIterations,
              total: this.getTotalIterations(),
            });
            break;
          }
        }

        // =======================================================================
        // GRACEFUL WRAPUP CHECK
        // If a wrapup has been requested (e.g., timeout approaching), convert
        // to forceTextOnly + inject wrapup prompt for structured summary.
        // Must come after economics check (which may also set forceTextOnly).
        // =======================================================================
        if (this.wrapupRequested && !forceTextOnly) {
          forceTextOnly = true;
          budgetInjectedPrompt = TIMEOUT_WRAPUP_PROMPT;
          this.wrapupRequested = false;
        }

        // =======================================================================
        // EXTERNAL CANCELLATION CHECK (deferred from above)
        // Checked after wrapup so that graceful wrapup can intercept the timeout.
        // If wrapup was already requested and converted to forceTextOnly above,
        // we skip throwing here to allow one more text-only turn for the summary.
        // =======================================================================
        if (this.externalCancellationToken?.isCancellationRequested && !forceTextOnly) {
          this.externalCancellationToken.throwIfCancellationRequested();
        }

        // =======================================================================
        // INTELLIGENT LOOP DETECTION & NUDGE INJECTION
        // Uses economics system for doom loops, exploration saturation, etc.
        // =======================================================================
        if (this.economics && budgetInjectedPrompt) {
          // Inject contextual guidance from economics system
          messages.push({
            role: 'user',
            content: budgetInjectedPrompt,
          });

          const loopState = this.economics.getLoopState();
          const phaseState = this.economics.getPhaseState();

          this.observability?.logger?.info('Loop detection - injecting guidance', {
            iteration: this.state.iteration,
            doomLoop: loopState.doomLoopDetected,
            phase: phaseState.phase,
            filesRead: phaseState.uniqueFilesRead,
            filesModified: phaseState.filesModified,
            shouldTransition: phaseState.shouldTransition,
            forceTextOnly,
          });
        }

        // =======================================================================
        // RECITATION INJECTION (Trick Q) - Combat "lost in middle" attention
        // =======================================================================
        if (this.contextEngineering) {
          if (process.env.DEBUG_LLM) {
            if (process.env.DEBUG) console.log(`[recitation] Before: ${messages.length} messages`);
          }

          const enrichedMessages = this.contextEngineering.injectRecitation(
            messages as Array<{ role: 'system' | 'user' | 'assistant' | 'tool'; content: string }>,
            {
              goal: task,
              plan: this.state.plan ? {
                description: this.state.plan.goal || task,
                tasks: this.state.plan.tasks.map(t => ({
                  id: t.id,
                  description: t.description,
                  status: t.status,
                })),
                currentTaskIndex: this.state.plan.tasks.findIndex(t => t.status === 'in_progress'),
              } : undefined,
              activeFiles: this.economics?.getProgress().filesModified
                ? [`${this.economics.getProgress().filesModified} files modified`]
                : undefined,
              recentErrors: this.contextEngineering.getFailureInsights().slice(0, 2),
            }
          );

          if (process.env.DEBUG_LLM) {
            if (process.env.DEBUG) console.log(`[recitation] After: ${enrichedMessages?.length ?? 'null/undefined'} messages`);
          }

          // Only replace if we got a DIFFERENT array back (avoid clearing same reference)
          // When no injection needed, injectRecitation returns the same array reference
          if (enrichedMessages && enrichedMessages !== messages && enrichedMessages.length > 0) {
            messages.length = 0;
            messages.push(...enrichedMessages);
          } else if (!enrichedMessages || enrichedMessages.length === 0) {
            console.warn('[executeDirectly] Recitation returned empty/null messages, keeping original');
          }
          // If enrichedMessages === messages, we don't need to do anything (same reference)

          // Update recitation frequency based on context size
          const contextTokens = messages.reduce((sum, m) => sum + (m.content?.length || 0) / 4, 0);
          this.contextEngineering.updateRecitationFrequency(contextTokens);
        }

        // =======================================================================
        // FAILURE CONTEXT INJECTION (Trick S) - Learn from mistakes
        // =======================================================================
        if (this.contextEngineering) {
          const failureContext = this.contextEngineering.getFailureContext(5);
          if (failureContext) {
            // Insert failure context before the last user message
            // (Using reverse iteration for ES2022 compatibility)
            let lastUserIdx = -1;
            for (let i = messages.length - 1; i >= 0; i--) {
              if (messages[i].role === 'user') {
                lastUserIdx = i;
                break;
              }
            }
            if (lastUserIdx > 0) {
              messages.splice(lastUserIdx, 0, {
                role: 'system',
                content: failureContext,
              });
            }
          }
        }

        // =====================================================================
        // RESILIENT LLM CALL: Empty response retries + max_tokens continuation
        // =====================================================================
        // Get resilience config
        const resilienceConfig = typeof this.config.resilience === 'object'
          ? this.config.resilience
          : {};
        const resilienceEnabled = isFeatureEnabled(this.config.resilience);
        const MAX_EMPTY_RETRIES = resilienceConfig.maxEmptyRetries ?? 2;
        const MAX_CONTINUATIONS = resilienceConfig.maxContinuations ?? 3;
        const AUTO_CONTINUE = resilienceConfig.autoContinue ?? true;
        const MIN_CONTENT_LENGTH = resilienceConfig.minContentLength ?? 1;
        const INCOMPLETE_ACTION_RECOVERY = resilienceConfig.incompleteActionRecovery ?? true;
        const MAX_INCOMPLETE_ACTION_RETRIES = resilienceConfig.maxIncompleteActionRetries ?? 2;
        const ENFORCE_REQUESTED_ARTIFACTS = resilienceConfig.enforceRequestedArtifacts ?? true;

        // =================================================================
        // PRE-FLIGHT BUDGET CHECK: Estimate if LLM call would exceed budget
        // Catches cases where we're at e.g. 120k and next call adds ~35k
        // =================================================================
        if (this.economics && !forceTextOnly) {
          const estimatedInputTokens = this.estimateContextTokens(messages);
          const estimatedOutputTokens = 4096; // Conservative output estimate
          const currentUsage = this.economics.getUsage();
          const budget = this.economics.getBudget();
          const projectedTotal = currentUsage.tokens + estimatedInputTokens + estimatedOutputTokens;

          if (projectedTotal > budget.maxTokens) {
            this.observability?.logger?.warn('Pre-flight budget check: projected overshoot', {
              currentTokens: currentUsage.tokens,
              estimatedInput: estimatedInputTokens,
              projectedTotal,
              maxTokens: budget.maxTokens,
            });

            // Inject wrap-up prompt if not already injected
            if (!budgetInjectedPrompt) {
              messages.push({
                role: 'user',
                content: '[System] BUDGET CRITICAL: This is your LAST response. Summarize findings concisely and stop. Do NOT call tools.',
              });
              this.state.messages.push({
                role: 'user',
                content: '[System] BUDGET CRITICAL: This is your LAST response. Summarize findings concisely and stop. Do NOT call tools.',
              });
            }
            forceTextOnly = true;
          }
        }

        let response = await this.callLLM(messages);
        let emptyRetries = 0;
        let continuations = 0;

        // Phase 1: Handle empty responses with retry (if resilience enabled)
        while (resilienceEnabled && emptyRetries < MAX_EMPTY_RETRIES) {
          const hasContent = response.content && response.content.length >= MIN_CONTENT_LENGTH;
          const hasToolCalls = response.toolCalls && response.toolCalls.length > 0;

          if (hasContent || hasToolCalls) {
            // Valid response received
            if (emptyRetries > 0) {
              this.emit({
                type: 'resilience.recovered',
                reason: 'empty_response',
                attempts: emptyRetries,
              });
              this.observability?.logger?.info('Recovered from empty response', {
                retries: emptyRetries,
              });
            }
            break;
          }

          // Empty response - retry with nudge
          emptyRetries++;
          this.emit({
            type: 'resilience.retry',
            reason: 'empty_response',
            attempt: emptyRetries,
            maxAttempts: MAX_EMPTY_RETRIES,
          });
          this.state.metrics.retryCount = (this.state.metrics.retryCount ?? 0) + 1;
          this.observability?.logger?.warn('Empty LLM response, retrying', {
            attempt: emptyRetries,
            maxAttempts: MAX_EMPTY_RETRIES,
          });

          // Add gentle nudge and retry
          const nudgeMessage: Message = {
            role: 'user',
            content: '[System: Your previous response was empty. Please provide a response or use a tool.]',
          };
          messages.push(nudgeMessage);
          this.state.messages.push(nudgeMessage);

          response = await this.callLLM(messages);
        }

        // Phase 2: Handle max_tokens truncation with continuation (if enabled)
        if (resilienceEnabled && AUTO_CONTINUE && response.stopReason === 'max_tokens' && !response.toolCalls?.length) {
          let accumulatedContent = response.content || '';

          while (continuations < MAX_CONTINUATIONS && response.stopReason === 'max_tokens') {
            continuations++;
            this.emit({
              type: 'resilience.continue',
              reason: 'max_tokens',
              continuation: continuations,
              maxContinuations: MAX_CONTINUATIONS,
              accumulatedLength: accumulatedContent.length,
            });
            this.observability?.logger?.info('Response truncated at max_tokens, continuing', {
              continuation: continuations,
              accumulatedLength: accumulatedContent.length,
            });

            // Add continuation request
            const continuationMessage: Message = {
              role: 'assistant',
              content: accumulatedContent,
            };
            const continueRequest: Message = {
              role: 'user',
              content: '[System: Please continue from where you left off. Do not repeat what you already said.]',
            };
            messages.push(continuationMessage, continueRequest);
            this.state.messages.push(continuationMessage, continueRequest);

            response = await this.callLLM(messages);

            // Accumulate content
            if (response.content) {
              accumulatedContent += response.content;
            }
          }

          // Update response with accumulated content
          if (continuations > 0) {
            response = { ...response, content: accumulatedContent };
            this.emit({
              type: 'resilience.completed',
              reason: 'max_tokens_continuation',
              continuations,
              finalLength: accumulatedContent.length,
            });
          }
        }

        // Phase 2b: Handle truncated tool calls (stopReason=max_tokens with tool calls present)
        // When a model hits max_tokens mid-tool-call, the JSON arguments are truncated and unparseable.
        // Instead of executing broken tool calls, strip them and ask the LLM to retry smaller.
        if (resilienceEnabled && response.stopReason === 'max_tokens' && response.toolCalls?.length) {
          this.emit({
            type: 'resilience.truncated_tool_call',
            toolNames: response.toolCalls.map(tc => tc.name),
          });
          this.observability?.logger?.warn('Tool call truncated at max_tokens', {
            toolNames: response.toolCalls.map(tc => tc.name),
            outputTokens: response.usage?.outputTokens,
          });

          // Strip truncated tool calls, inject recovery message
          const truncatedResponse = response;
          response = { ...response, toolCalls: undefined };
          const recoveryMessage: Message = {
            role: 'user',
            content: '[System: Your previous tool call was truncated because the output exceeded the token limit. ' +
              'The tool call arguments were cut off and could not be parsed. ' +
              'Please retry with a smaller approach: for write_file, break the content into smaller chunks ' +
              'or use edit_file for targeted changes instead of rewriting entire files.]',
          };
          messages.push({ role: 'assistant', content: truncatedResponse.content || '' });
          messages.push(recoveryMessage);
          this.state.messages.push({ role: 'assistant', content: truncatedResponse.content || '' });
          this.state.messages.push(recoveryMessage);

          response = await this.callLLM(messages);
        }

        // Record LLM usage for economics
        if (this.economics && response.usage) {
          this.economics.recordLLMUsage(
            response.usage.inputTokens,
            response.usage.outputTokens,
            this.config.model,
            response.usage.cost  // Use actual cost from provider when available
          );

          // =================================================================
          // POST-LLM BUDGET CHECK: Prevent tool execution if over budget
          // A single LLM call can push us over - catch it before running tools
          // =================================================================
          if (!forceTextOnly) {
            const postCheck = this.economics.checkBudget();
            if (!postCheck.canContinue) {
              this.observability?.logger?.warn('Budget exceeded after LLM call, skipping tool execution', {
                reason: postCheck.reason,
              });
              forceTextOnly = true;
            }
          }
        }

        // Add assistant message
        const assistantMessage: Message = {
          role: 'assistant',
          content: response.content,
          toolCalls: response.toolCalls,
        };
        messages.push(assistantMessage);
        this.state.messages.push(assistantMessage);
        lastResponse = response.content;

        // In plan mode: capture exploration findings as we go (not just at the end)
        // This ensures we collect context from exploration iterations before writes are queued
        if (this.modeManager.getMode() === 'plan' && response.content && response.content.length > 50) {
          const hasReadOnlyTools = response.toolCalls?.every(tc =>
            ['read_file', 'list_files', 'glob', 'grep', 'search', 'mcp_'].some(prefix =>
              tc.name.startsWith(prefix) || tc.name === prefix
            )
          );
          // Capture substantive exploration content (not just "let me read..." responses)
          if (hasReadOnlyTools && !response.content.match(/^(Let me|I'll|I will|I need to|First,)/i)) {
            this.pendingPlanManager.appendExplorationFinding(response.content.slice(0, 1000));
          }
        }

        // Check for tool calls
        // When forceTextOnly is set (max iterations reached), ignore any tool calls
        const hasToolCalls = response.toolCalls && response.toolCalls.length > 0;
        if (!hasToolCalls || forceTextOnly) {
          // Log if we're ignoring tool calls due to forceTextOnly
          if (forceTextOnly && hasToolCalls) {
            this.observability?.logger?.info('Ignoring tool calls due to forceTextOnly (max steps reached)', {
              toolCallCount: response.toolCalls?.length,
              iteration: this.state.iteration,
            });
          }

          const incompleteAction = this.detectIncompleteActionResponse(response.content || '');
          const missingRequiredArtifact = ENFORCE_REQUESTED_ARTIFACTS
            ? this.isRequestedArtifactMissing(requestedArtifact, executedToolNames)
            : false;
          const shouldRecoverIncompleteAction = resilienceEnabled
            && INCOMPLETE_ACTION_RECOVERY
            && !forceTextOnly
            && (incompleteAction || missingRequiredArtifact);

          if (shouldRecoverIncompleteAction) {
            if (incompleteActionRetries < MAX_INCOMPLETE_ACTION_RETRIES) {
              incompleteActionRetries++;
              const reason = missingRequiredArtifact && requestedArtifact
                ? `missing_requested_artifact:${requestedArtifact}`
                : 'future_intent_without_action';
              this.emit({
                type: 'resilience.incomplete_action_detected',
                reason,
                attempt: incompleteActionRetries,
                maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
                requiresArtifact: missingRequiredArtifact,
              });
              this.observability?.logger?.warn('Incomplete action detected, retrying with nudge', {
                reason,
                attempt: incompleteActionRetries,
                maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
              });

              const nudgeMessage: Message = {
                role: 'user',
                content: missingRequiredArtifact && requestedArtifact
                  ? `[System: You said you would complete the next action, but no tool call was made. The task requires creating or updating "${requestedArtifact}". Execute the required tool now, or explicitly explain why it cannot be produced.]`
                  : '[System: You described a next action but did not execute it. If work remains, call the required tool now. If the task is complete, provide a final answer with no pending action language.]',
              };
              messages.push(nudgeMessage);
              this.state.messages.push(nudgeMessage);
              continue;
            }

            const failureReason = missingRequiredArtifact && requestedArtifact
              ? `incomplete_action_missing_artifact:${requestedArtifact}`
              : 'incomplete_action_unresolved';
            this.emit({
              type: 'resilience.incomplete_action_failed',
              reason: failureReason,
              attempts: incompleteActionRetries,
              maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
            });
            throw new Error(`LLM failed to complete requested action after ${incompleteActionRetries} retries (${failureReason})`);
          }

          if (incompleteActionRetries > 0) {
            this.emit({
              type: 'resilience.incomplete_action_recovered',
              reason: 'incomplete_action',
              attempts: incompleteActionRetries,
            });
            incompleteActionRetries = 0;
          }

          // No tool calls (or forced to ignore), agent is done - compact tool outputs to save context
          // The model has "consumed" the tool outputs and produced a response,
          // so we can replace verbose outputs with compact summaries
          this.compactToolOutputs();

          // In plan mode: capture exploration summary from the final response
          // This provides context for what was learned during exploration before proposing changes
          if (this.modeManager.getMode() === 'plan' && this.pendingPlanManager.hasPendingPlan()) {
            const explorationContent = response.content || '';
            if (explorationContent.length > 0) {
              this.pendingPlanManager.setExplorationSummary(explorationContent);
            }
          }

          // Final validation: warn if response is still empty after all retries
          if (!response.content || response.content.length === 0) {
            this.observability?.logger?.error('Agent finished with empty response after all retries', {
              emptyRetries,
              continuations,
              iteration: this.state.iteration,
            });
            this.emit({
              type: 'resilience.failed',
              reason: 'empty_final_response',
              emptyRetries,
              continuations,
            });
          }

          // Record iteration end for tracing (no tool calls case)
          this.traceCollector?.record({
            type: 'iteration.end',
            data: { iterationNumber: this.state.iteration },
          });
          break;
        }

        // Execute tool calls (we know toolCalls is defined here due to the check above)
        const toolCalls = response.toolCalls!;
        const toolResults = await this.executeToolCalls(toolCalls);

        // Record tool calls for economics/progress tracking
        for (let i = 0; i < toolCalls.length; i++) {
          const toolCall = toolCalls[i];
          const result = toolResults[i];
          executedToolNames.add(toolCall.name);
          this.economics?.recordToolCall(toolCall.name, toolCall.arguments, result?.result);
        }

        // Add tool results to messages (with truncation and proactive budget management)
        const MAX_TOOL_OUTPUT_CHARS = 8000; // ~2000 tokens max per tool output

        // =======================================================================
        // PROACTIVE BUDGET CHECK - compact BEFORE we overflow, not after
        // Uses AutoCompactionManager if available for sophisticated compaction
        // =======================================================================
        const currentContextTokens = this.estimateContextTokens(messages);

        if (this.autoCompactionManager) {
          // Use the AutoCompactionManager for threshold-based compaction
          const compactionResult = await this.autoCompactionManager.checkAndMaybeCompact({
            currentTokens: currentContextTokens,
            messages: messages,
          });

          // Handle compaction result
          if (compactionResult.status === 'compacted' && compactionResult.compactedMessages) {
            // Replace messages with compacted version
            messages.length = 0;
            messages.push(...compactionResult.compactedMessages);
            this.state.messages.length = 0;
            this.state.messages.push(...compactionResult.compactedMessages);
          } else if (compactionResult.status === 'hard_limit') {
            // Hard limit reached - this is serious, emit error
            this.emit({
              type: 'error',
              error: `Context hard limit reached (${Math.round(compactionResult.ratio * 100)}% of max tokens)`,
            });
            break;
          }
        } else if (this.economics) {
          // Fallback to simple compaction
          const currentUsage = this.economics.getUsage();
          const budget = this.economics.getBudget();
          const percentUsed = (currentUsage.tokens / budget.maxTokens) * 100;

          // If we're at 70%+ of budget, proactively compact to make room
          if (percentUsed >= 70) {
            this.observability?.logger?.info('Proactive compaction triggered', {
              percentUsed: Math.round(percentUsed),
              currentTokens: currentUsage.tokens,
              maxTokens: budget.maxTokens,
            });
            this.compactToolOutputs();
          }
        }

        const toolCallNameById = new Map(toolCalls.map(tc => [tc.id, tc.name]));

        for (const result of toolResults) {
          let content = typeof result.result === 'string' ? result.result : stableStringify(result.result);
          const sourceToolName = toolCallNameById.get(result.callId);
          const isExpensiveResult = sourceToolName === 'spawn_agent' || sourceToolName === 'spawn_agents_parallel';

          // Truncate long outputs to save context
          if (content.length > MAX_TOOL_OUTPUT_CHARS) {
            content = content.slice(0, MAX_TOOL_OUTPUT_CHARS) + `\n\n... [truncated ${content.length - MAX_TOOL_OUTPUT_CHARS} chars]`;
          }

          // =======================================================================
          // ESTIMATE if adding this result would exceed budget
          // =======================================================================
          if (this.economics) {
            const estimatedNewTokens = Math.ceil(content.length / 4); // ~4 chars per token
            const currentContextTokens = this.estimateContextTokens(messages);
            const budget = this.economics.getBudget();

            // Check if adding this would push us over the hard limit
            if (currentContextTokens + estimatedNewTokens > budget.maxTokens * 0.95) {
              this.observability?.logger?.warn('Skipping tool result to stay within budget', {
                toolCallId: result.callId,
                estimatedTokens: estimatedNewTokens,
                currentContext: currentContextTokens,
                limit: budget.maxTokens,
              });

              // Add a truncated placeholder instead
              const toolMessage: Message = {
                role: 'tool',
                content: `[Result omitted to stay within token budget. Original size: ${content.length} chars]`,
                toolCallId: result.callId,
              };
              messages.push(toolMessage);
              this.state.messages.push(toolMessage);
              continue;
            }
          }

          const toolMessage: Message = {
            role: 'tool',
            content,
            toolCallId: result.callId,
            ...(isExpensiveResult
              ? {
                  metadata: {
                    preserveFromCompaction: true,
                    costToRegenerate: 'high',
                    source: sourceToolName,
                  },
                }
              : {}),
          };
          messages.push(toolMessage);
          this.state.messages.push(toolMessage);
        }

        // Emit context health after adding tool results
        const currentTokenEstimate = this.estimateContextTokens(messages);
        const contextLimit = this.getMaxContextTokens();
        const percentUsed = Math.round((currentTokenEstimate / contextLimit) * 100);
        const avgTokensPerExchange = currentTokenEstimate / Math.max(1, this.state.iteration);
        const remainingTokens = contextLimit - currentTokenEstimate;
        const estimatedExchanges = Math.floor(remainingTokens / Math.max(1, avgTokensPerExchange));

        this.emit({
          type: 'context.health',
          currentTokens: currentTokenEstimate,
          maxTokens: contextLimit,
          estimatedExchanges,
          percentUsed,
        });

        // Record iteration end for tracing (after tool execution)
        this.traceCollector?.record({
          type: 'iteration.end',
          data: { iterationNumber: this.state.iteration },
        });
      }

      // =======================================================================
      // REFLECTION (Lesson 16)
      // =======================================================================
      if (autoReflect && this.planning && reflectionAttempt < maxReflectionAttempts) {
        this.emit({ type: 'reflection', attempt: reflectionAttempt, satisfied: false });

        const reflectionResult = await this.planning.reflect(task, lastResponse, this.provider);
        this.state.metrics.reflectionAttempts = reflectionAttempt;

        if (reflectionResult.satisfied && reflectionResult.confidence >= confidenceThreshold) {
          // Output is satisfactory
          this.emit({ type: 'reflection', attempt: reflectionAttempt, satisfied: true });
          break;
        }

        // Not satisfied - add feedback and continue
        const feedbackMessage: Message = {
          role: 'user',
          content: `[Reflection feedback]\nThe previous output needs improvement:\n- Critique: ${reflectionResult.critique}\n- Suggestions: ${reflectionResult.suggestions.join(', ')}\n\nPlease improve the output.`,
        };
        messages.push(feedbackMessage);
        this.state.messages.push(feedbackMessage);

        this.observability?.logger?.info('Reflection not satisfied, retrying', {
          attempt: reflectionAttempt,
          confidence: reflectionResult.confidence,
          critique: reflectionResult.critique,
        });
      } else {
        // No reflection or already satisfied
        break;
      }
    }

    // Store conversation in memory
    this.memory?.storeConversation(this.state.messages);
    this.updateMemoryStats();
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

      try {
        // Use synchronous cache if available, otherwise skip
        const repoMap = this.codebaseContext.getRepoMap();
        if (repoMap) {
          const selection = this.selectRelevantCodeSync(task, codebaseBudget);
          if (selection.chunks.length > 0) {
            codebaseContextStr = buildContextFromChunks(selection.chunks, {
              includeFilePaths: true,
              includeSeparators: true,
              maxTotalTokens: codebaseBudget,
            });
          }
        }
      } catch {
        // Codebase analysis not ready yet - skip for this call
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
    let systemPrompt: string;

    // Combine memory, learnings, and codebase context
    const combinedContext = [
      ...(memoryContext.length > 0 ? memoryContext : []),
      ...(learningsContext ? [learningsContext] : []),
      ...(codebaseContextStr ? [`\n## Relevant Code\n${codebaseContextStr}`] : []),
    ].join('\n');

    if (this.contextEngineering) {
      // Use cache-optimized prompt builder - orders sections for KV-cache reuse:
      // static prefix -> rules -> tools -> memory/codebase -> dynamic
      systemPrompt = this.contextEngineering.buildSystemPrompt({
        rules: rulesContent + (skillsPrompt ? '\n\n' + skillsPrompt : ''),
        tools: toolDescriptions,
        memory: combinedContext.length > 0 ? combinedContext : undefined,
        dynamic: {
          mode: this.modeManager?.getMode() ?? 'default',
        },
      });
    } else {
      // Fallback: manual concatenation (original behavior)
      systemPrompt = this.config.systemPrompt;
      if (rulesContent) systemPrompt += '\n\n' + rulesContent;
      if (skillsPrompt) systemPrompt += skillsPrompt;
      if (combinedContext.length > 0) {
        systemPrompt += '\n\nRelevant context:\n' + combinedContext;
      }
      if (toolDescriptions) {
        systemPrompt += '\n\nAvailable tools:\n' + toolDescriptions;
      }
    }

    // Safety check: ensure system prompt is not empty
    if (!systemPrompt || systemPrompt.trim().length === 0) {
      console.warn('[buildMessages] Warning: Empty system prompt detected, using fallback');
      systemPrompt = this.config.systemPrompt || 'You are a helpful AI assistant.';
    }

    messages.push({ role: 'system', content: systemPrompt });

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

  /**
   * Call the LLM with routing and observability.
   */
  private async callLLM(messages: Message[]): Promise<ChatResponse> {
    const spanId = this.observability?.tracer?.startSpan('llm.call');

    this.emit({ type: 'llm.start', model: this.config.model || 'default' });

    // Emit context insight for verbose feedback
    const estimatedTokens = messages.reduce((sum, m) => {
      const content = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
      return sum + Math.ceil(content.length / 3.5); // ~3.5 chars per token estimate
    }, 0);
    // Use context window size, not output token limit
    const contextLimit = this.getMaxContextTokens();
    this.emit({
      type: 'insight.context',
      currentTokens: estimatedTokens,
      maxTokens: contextLimit,
      messageCount: messages.length,
      percentUsed: Math.round((estimatedTokens / contextLimit) * 100),
    });

    const startTime = Date.now();
    const requestId = `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    // Debug: Log message count and structure (helps diagnose API errors)
    if (process.env.DEBUG_LLM) {
      console.log(`[callLLM] Sending ${messages.length} messages:`);
      messages.forEach((m, i) => {
        console.log(`  [${i}] ${m.role}: ${m.content?.slice(0, 50)}...`);
      });
    }

    // Validate messages are not empty
    if (!messages || messages.length === 0) {
      throw new Error('No messages to send to LLM');
    }

    // Lesson 26: Record LLM request for tracing
    const model = this.config.model || 'default';
    const provider = (this.config.provider as { name?: string })?.name || 'unknown';
    this.traceCollector?.record({
      type: 'llm.request',
      data: {
        requestId,
        model,
        provider,
        messages: messages.map(m => ({
          role: m.role as 'system' | 'user' | 'assistant' | 'tool',
          content: m.content,
          toolCallId: m.toolCallId,
          toolCalls: m.toolCalls?.map(tc => ({
            id: tc.id,
            name: tc.name,
            arguments: tc.arguments,
          })),
        })),
        tools: Array.from(this.tools.values()).map(t => ({
          name: t.name,
          description: t.description,
          parametersSchema: t.parameters,
        })),
        parameters: {
          maxTokens: this.config.maxTokens,
          temperature: this.config.temperature,
        },
      },
    });

    try {
      let response: ChatResponse;
      let actualModel = model;

      // Use routing if enabled
      if (this.routing) {
        const complexity = this.routing.estimateComplexity(messages[messages.length - 1]?.content || '');
        const context = {
          task: messages[messages.length - 1]?.content || '',
          complexity,
          hasTools: this.tools.size > 0,
          hasImages: false,
          taskType: 'general',
          estimatedTokens: messages.reduce((sum, m) => sum + m.content.length / 4, 0),
        };

        const result = await this.routing.executeWithFallback(messages, context);
        response = result.response;
        actualModel = result.model;

        // Emit routing insight
        this.emit({
          type: 'insight.routing',
          model: actualModel,
          reason: actualModel !== model ? 'Routed based on complexity' : 'Default model',
          complexity: complexity <= 0.3 ? 'low' : complexity <= 0.7 ? 'medium' : 'high',
        });

        // Emit decision transparency event
        this.emit({
          type: 'decision.routing',
          model: actualModel,
          reason: actualModel !== model
            ? `Complexity ${(complexity * 100).toFixed(0)}% - using ${actualModel}`
            : 'Default model for current task',
          alternatives: actualModel !== model
            ? [{ model, rejected: 'complexity threshold exceeded' }]
            : undefined,
        });

        // Enhanced tracing: Record routing decision
        this.traceCollector?.record({
          type: 'decision',
          data: {
            type: 'routing',
            decision: `Selected model: ${actualModel}`,
            outcome: 'allowed',
            reasoning: actualModel !== model
              ? `Task complexity ${(complexity * 100).toFixed(0)}% exceeded threshold - routed to ${actualModel}`
              : `Default model ${model} suitable for task complexity ${(complexity * 100).toFixed(0)}%`,
            factors: [
              { name: 'complexity', value: complexity, weight: 0.8 },
              { name: 'hasTools', value: context.hasTools, weight: 0.1 },
              { name: 'taskType', value: context.taskType, weight: 0.1 },
            ],
            alternatives: actualModel !== model
              ? [{ option: model, reason: 'complexity threshold exceeded', rejected: true }]
              : undefined,
            confidence: 0.9,
          },
        });
      } else {
        response = await this.provider.chat(messages, {
          model: this.config.model,
          tools: Array.from(this.tools.values()),
        });
      }

      const duration = Date.now() - startTime;

      // Lesson 26: Record LLM response for tracing
      this.traceCollector?.record({
        type: 'llm.response',
        data: {
          requestId,
          content: response.content || '',
          toolCalls: response.toolCalls?.map(tc => ({
            id: tc.id,
            name: tc.name,
            arguments: tc.arguments,
          })),
          stopReason: response.stopReason === 'end_turn' ? 'end_turn'
            : response.stopReason === 'tool_use' ? 'tool_use'
            : response.stopReason === 'max_tokens' ? 'max_tokens'
            : 'stop_sequence',
          usage: {
            inputTokens: response.usage?.inputTokens || 0,
            outputTokens: response.usage?.outputTokens || 0,
            cacheReadTokens: response.usage?.cacheReadTokens,
            cacheWriteTokens: response.usage?.cacheWriteTokens,
            cost: response.usage?.cost,  // Actual cost from provider (e.g., OpenRouter)
          },
          durationMs: duration,
        },
      });

      // Enhanced tracing: Record thinking/reasoning blocks if present
      if (response.thinking) {
        this.traceCollector?.record({
          type: 'llm.thinking',
          data: {
            requestId,
            content: response.thinking,
            summarized: response.thinking.length > 10000, // Summarize if very long
            originalLength: response.thinking.length,
            durationMs: duration,
          },
        });
      }

      // Record metrics
      this.observability?.metrics?.recordLLMCall(
        response.usage?.inputTokens || 0,
        response.usage?.outputTokens || 0,
        duration,
        actualModel,
        response.usage?.cost  // Actual cost from provider (e.g., OpenRouter)
      );

      this.state.metrics.llmCalls++;
      this.state.metrics.inputTokens += response.usage?.inputTokens || 0;
      this.state.metrics.outputTokens += response.usage?.outputTokens || 0;
      this.state.metrics.totalTokens = this.state.metrics.inputTokens + this.state.metrics.outputTokens;

      this.emit({ type: 'llm.complete', response });

      // Emit token usage insight for verbose feedback
      if (response.usage) {
        this.emit({
          type: 'insight.tokens',
          inputTokens: response.usage.inputTokens,
          outputTokens: response.usage.outputTokens,
          cacheReadTokens: response.usage.cacheReadTokens,
          cacheWriteTokens: response.usage.cacheWriteTokens,
          cost: response.usage.cost,
          model: actualModel,
        });
      }

      this.observability?.tracer?.endSpan(spanId);

      return response;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      this.observability?.tracer?.recordError(error);
      this.observability?.tracer?.endSpan(spanId);
      throw error;
    }
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
   * Execute tool calls with safety checks and execution policy enforcement.
   */
  private async executeToolCalls(toolCalls: ToolCall[]): Promise<ToolResult[]> {
    const results: ToolResult[] = [];

    for (const toolCall of toolCalls) {
      const spanId = this.observability?.tracer?.startSpan(`tool.${toolCall.name}`);
      const executionId = `exec-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

      this.emit({ type: 'tool.start', tool: toolCall.name, args: toolCall.arguments });

      const startTime = Date.now();

      // Lesson 26: Record tool start for tracing
      this.traceCollector?.record({
        type: 'tool.start',
        data: {
          executionId,
          toolName: toolCall.name,
          arguments: toolCall.arguments as Record<string, unknown>,
        },
      });

      try {
        // =====================================================================
        // PLAN MODE WRITE INTERCEPTION
        // =====================================================================
        // In plan mode, intercept write operations and queue them as proposed changes
        if (this.modeManager.shouldInterceptTool(toolCall.name, toolCall.arguments as Record<string, unknown>)) {
          // Extract contextual reasoning instead of simple truncation
          const reason = this.extractChangeReasoning(toolCall, this.state.messages);

          // Start a new plan if needed
          if (!this.pendingPlanManager.hasPendingPlan()) {
            const lastUserMsg = [...this.state.messages].reverse().find(m => m.role === 'user');
            const task = typeof lastUserMsg?.content === 'string' ? lastUserMsg.content : 'Plan';
            this.pendingPlanManager.startPlan(task);
          }

          // Queue the write operation
          const change = this.pendingPlanManager.addProposedChange(
            toolCall.name,
            toolCall.arguments as Record<string, unknown>,
            reason,
            toolCall.id
          );

          // Emit event for UI
          this.emit({
            type: 'plan.change.queued',
            tool: toolCall.name,
            changeId: change?.id,
            summary: this.formatToolArgsForPlan(toolCall.name, toolCall.arguments as Record<string, unknown>),
          });

          // Return a message indicating the change was queued
          const queueMessage = `[PLAN MODE] Change queued for approval:\n` +
            `Tool: ${toolCall.name}\n` +
            `${this.formatToolArgsForPlan(toolCall.name, toolCall.arguments as Record<string, unknown>)}\n` +
            `Use /show-plan to see all pending changes, /approve to execute, /reject to discard.`;

          results.push({
            callId: toolCall.id,
            result: queueMessage,
          });

          this.observability?.tracer?.endSpan(spanId);
          continue; // Skip actual execution
        }
        // =====================================================================
        // EXECUTION POLICY ENFORCEMENT (Lesson 23)
        // =====================================================================
        let policyApprovedByUser = false;
        if (this.executionPolicy) {
          const policyContext = {
            messages: this.state.messages,
            currentMessage: this.state.messages.find(m => m.role === 'user')?.content,
            previousToolCalls: toolCalls.slice(0, toolCalls.indexOf(toolCall)),
          };

          const evaluation = this.executionPolicy.evaluate(toolCall, policyContext);

          // Emit policy event
          this.emit({
            type: 'policy.evaluated',
            tool: toolCall.name,
            policy: evaluation.policy,
            reason: evaluation.reason,
          });

          // Emit decision transparency event
          this.emit({
            type: 'decision.tool',
            tool: toolCall.name,
            decision: evaluation.policy === 'forbidden' ? 'blocked'
              : evaluation.policy === 'prompt' ? 'prompted'
              : 'allowed',
            policyMatch: evaluation.reason,
          });

          // Enhanced tracing: Record policy decision
          this.traceCollector?.record({
            type: 'decision',
            data: {
              type: 'policy',
              decision: `Tool ${toolCall.name}: ${evaluation.policy}`,
              outcome: evaluation.policy === 'forbidden' ? 'blocked'
                : evaluation.policy === 'prompt' ? 'deferred'
                : 'allowed',
              reasoning: evaluation.reason,
              factors: [
                { name: 'policy', value: evaluation.policy },
                { name: 'requiresApproval', value: evaluation.requiresApproval ?? false },
              ],
              confidence: evaluation.intent?.confidence ?? 0.8,
            },
          });

          // Handle forbidden policy - always block
          if (evaluation.policy === 'forbidden') {
            throw new Error(`Forbidden by policy: ${evaluation.reason}`);
          }

          // Handle prompt policy - requires approval
          if (evaluation.policy === 'prompt' && evaluation.requiresApproval) {
            // Try to get approval through safety manager's human-in-loop
            const humanInLoop = this.safety?.humanInLoop;
            if (humanInLoop) {
              const approval = await this.withPausedDuration(() =>
                humanInLoop.requestApproval(
                  toolCall,
                  `Policy requires approval: ${evaluation.reason}`
                )
              );

              if (!approval.approved) {
                throw new Error(`Denied by user: ${approval.reason || 'No reason provided'}`);
              }
              policyApprovedByUser = true;

              // Create a grant for future similar calls if approved
              this.executionPolicy.createGrant({
                toolName: toolCall.name,
                grantedBy: 'user',
                reason: 'Approved during execution',
                maxUsages: 5, // Allow 5 more similar calls
              });
            } else {
              // No approval handler - block by default for safety
              throw new Error(`Policy requires approval but no approval handler available: ${evaluation.reason}`);
            }
          }

          // Log intent classification if available
          if (evaluation.intent) {
            this.emit({
              type: 'intent.classified',
              tool: toolCall.name,
              intent: evaluation.intent.type,
              confidence: evaluation.intent.confidence,
            });
          }
        }

        // =====================================================================
        // SAFETY VALIDATION (Lesson 20-21)
        // =====================================================================
        if (this.safety) {
          const safety = this.safety;
          const validation = await this.withPausedDuration(() =>
            safety.validateAndApprove(
              toolCall,
              `Executing tool: ${toolCall.name}`,
              { skipHumanApproval: policyApprovedByUser }
            )
          );

          if (!validation.allowed) {
            throw new Error(`Tool call blocked: ${validation.reason}`);
          }
        }

        // Get tool definition (with lazy-loading support for MCP tools)
        let tool = this.tools.get(toolCall.name);
        const wasPreloaded = !!tool;
        if (!tool && this.toolResolver) {
          // Try to resolve and load the tool on-demand
          const resolved = this.toolResolver(toolCall.name);
          if (resolved) {
            this.addTool(resolved);
            tool = resolved;
            if (process.env.DEBUG) console.log(`  🔄 Auto-loaded MCP tool: ${toolCall.name}`);
            this.observability?.logger?.info('Tool auto-loaded', { tool: toolCall.name });
          }
        }
        if (!tool) {
          throw new Error(`Unknown tool: ${toolCall.name}`);
        }
        // Log whether tool was pre-loaded or auto-loaded (for MCP tools)
        if (process.env.DEBUG && toolCall.name.startsWith('mcp_') && wasPreloaded) {
          console.log(`  ✓ Using pre-loaded MCP tool: ${toolCall.name}`);
        }

        // =====================================================================
        // BLACKBOARD FILE COORDINATION (Parallel Subagent Support)
        // =====================================================================
        // Claim file resources before write operations to prevent conflicts
        if (this.blackboard && (toolCall.name === 'write_file' || toolCall.name === 'edit_file')) {
          const args = toolCall.arguments as Record<string, unknown>;
          const filePath = String(args.path || args.file_path || '');
          if (filePath) {
            const agentId = this.config.systemPrompt?.slice(0, 50) || 'agent';
            const claimed = this.blackboard.claim(filePath, agentId, 'write', {
              ttl: 60000, // 1 minute claim
              intent: `${toolCall.name}: ${filePath}`,
            });
            if (!claimed) {
              const existingClaim = this.blackboard.getClaim(filePath);
              throw new Error(
                `File "${filePath}" is being edited by another agent (${existingClaim?.agentId || 'unknown'}). ` +
                `Wait for the other agent to complete or choose a different file.`
              );
            }
          }
        }

        // Execute tool (with sandbox if available)
        let result: unknown;
        if (this.safety?.sandbox) {
          // CRITICAL: spawn_agent and spawn_agents_parallel need MUCH longer timeouts
          // The default 60s sandbox timeout would kill subagents prematurely
          // Subagents may run for minutes (per their own timeout config)
          const isSpawnAgent = toolCall.name === 'spawn_agent';
          const isSpawnParallel = toolCall.name === 'spawn_agents_parallel';
          const isSubagentTool = isSpawnAgent || isSpawnParallel;

          const subagentConfig = this.config.subagent;
          const hasSubagentConfig = subagentConfig !== false && subagentConfig !== undefined;
          const subagentTimeout = hasSubagentConfig
            ? (subagentConfig as { defaultTimeout?: number }).defaultTimeout ?? 600000 // 10 min default
            : 600000;

          // Use subagent timeout + buffer for spawn tools, default for others
          // For spawn_agents_parallel, multiply by number of agents (they run in parallel,
          // but the total wall-clock time should still allow the slowest agent to complete)
          const toolTimeout = isSubagentTool ? subagentTimeout + 30000 : undefined;

          result = await this.safety.sandbox.executeWithLimits(
            () => tool.execute(toolCall.arguments),
            toolTimeout
          );
        } else {
          result = await tool.execute(toolCall.arguments);
        }

        const duration = Date.now() - startTime;

        // Lesson 26: Record tool completion for tracing
        this.traceCollector?.record({
          type: 'tool.end',
          data: {
            executionId,
            status: 'success',
            result,
            durationMs: duration,
          },
        });

        // Record metrics
        this.observability?.metrics?.recordToolCall(toolCall.name, duration, true);
        this.state.metrics.toolCalls++;

        this.emit({ type: 'tool.complete', tool: toolCall.name, result });

        // Emit tool insight with result summary
        const summary = this.summarizeToolResult(toolCall.name, result);
        this.emit({
          type: 'insight.tool',
          tool: toolCall.name,
          summary,
          durationMs: duration,
          success: true,
        });

        results.push({
          callId: toolCall.id,
          result,
        });

        // Release blackboard claim after successful file write
        if (this.blackboard && (toolCall.name === 'write_file' || toolCall.name === 'edit_file')) {
          const args = toolCall.arguments as Record<string, unknown>;
          const filePath = String(args.path || args.file_path || '');
          if (filePath) {
            const agentId = this.config.systemPrompt?.slice(0, 50) || 'agent';
            this.blackboard.release(filePath, agentId);
          }
        }

        this.observability?.tracer?.endSpan(spanId);
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        const duration = Date.now() - startTime;

        // Lesson 26: Record tool error for tracing
        this.traceCollector?.record({
          type: 'tool.end',
          data: {
            executionId,
            status: error.message.includes('Blocked') || error.message.includes('Policy') ? 'blocked' : 'error',
            error,
            durationMs: duration,
          },
        });

        this.observability?.metrics?.recordToolCall(toolCall.name, duration, false);
        this.observability?.tracer?.recordError(error);
        this.observability?.tracer?.endSpan(spanId);

        // FAILURE EVIDENCE RECORDING (Trick S)
        // Track failed tool calls to prevent loops and provide context
        this.contextEngineering?.recordFailure({
          action: toolCall.name,
          args: toolCall.arguments as Record<string, unknown>,
          error,
          intent: `Execute tool ${toolCall.name}`,
        });

        results.push({
          callId: toolCall.id,
          result: `Error: ${error.message}`,
          error: error.message,
        });

        this.emit({ type: 'tool.blocked', tool: toolCall.name, reason: error.message });
      }
    }

    return results;
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
   * Create a brief summary of a tool result for insight display.
   */
  private summarizeToolResult(toolName: string, result: unknown): string {
    if (result === null || result === undefined) {
      return 'No output';
    }

    const resultStr = typeof result === 'string' ? result : JSON.stringify(result);

    // Tool-specific summaries
    if (toolName === 'list_files' || toolName === 'glob') {
      const lines = resultStr.split('\n').filter(l => l.trim());
      return `Found ${lines.length} file${lines.length !== 1 ? 's' : ''}`;
    }
    if (toolName === 'bash' || toolName === 'execute_command') {
      const lines = resultStr.split('\n').filter(l => l.trim());
      if (resultStr.includes('exit code: 0') || !resultStr.includes('exit code:')) {
        return lines.length > 1 ? `Success (${lines.length} lines)` : 'Success';
      }
      return `Failed - ${lines[0]?.slice(0, 50) || 'see output'}`;
    }
    if (toolName === 'read_file') {
      const lines = resultStr.split('\n').length;
      return `Read ${lines} line${lines !== 1 ? 's' : ''}`;
    }
    if (toolName === 'write_file' || toolName === 'edit_file') {
      return 'File updated';
    }
    if (toolName === 'search' || toolName === 'grep') {
      const matches = (resultStr.match(/\n/g) || []).length;
      return `${matches} match${matches !== 1 ? 'es' : ''}`;
    }

    // Generic summary
    if (resultStr.length <= 50) {
      return resultStr;
    }
    return `${resultStr.slice(0, 47)}...`;
  }

  /**
   * Format tool arguments for plan display.
   */
  private formatToolArgsForPlan(toolName: string, args: Record<string, unknown>): string {
    if (toolName === 'write_file') {
      const path = args.path || args.file_path;
      const content = String(args.content || '');
      const preview = content.slice(0, 100).replace(/\n/g, '\\n');
      return `File: ${path}\nContent preview: ${preview}${content.length > 100 ? '...' : ''}`;
    }
    if (toolName === 'edit_file') {
      const path = args.path || args.file_path;
      return `File: ${path}\nOld: ${String(args.old_string || args.search || '').slice(0, 50)}...\nNew: ${String(args.new_string || args.replace || '').slice(0, 50)}...`;
    }
    if (toolName === 'bash') {
      return `Command: ${String(args.command || '').slice(0, 100)}`;
    }
    if (toolName === 'delete_file') {
      return `Delete: ${args.path || args.file_path}`;
    }
    if (toolName === 'spawn_agent' || toolName === 'researcher') {
      const task = String(args.task || args.prompt || args.goal || '');
      const model = args.model ? ` (${args.model})` : '';
      const firstLine = task.split('\n')[0].slice(0, 100);
      return `${firstLine}${task.length > 100 ? '...' : ''}${model}`;
    }
    // Generic
    return `Args: ${JSON.stringify(args).slice(0, 100)}...`;
  }

  /**
   * Extract contextual reasoning for a proposed change in plan mode.
   * Looks at recent assistant messages to find relevant explanation.
   * Returns a more complete reason than simple truncation.
   */
  private extractChangeReasoning(
    toolCall: { name: string; arguments: unknown },
    messages: Message[]
  ): string {
    // Get last few assistant messages (most recent first)
    const assistantMsgs = messages
      .filter(m => m.role === 'assistant' && typeof m.content === 'string')
      .slice(-3)
      .reverse();

    if (assistantMsgs.length === 0) {
      return `Proposed change: ${toolCall.name}`;
    }

    // Use the most recent assistant message
    const lastMsg = assistantMsgs[0];
    const content = lastMsg.content as string;

    // For spawn_agent, the task itself is usually the reason
    if (toolCall.name === 'spawn_agent') {
      const args = toolCall.arguments as Record<string, unknown>;
      const task = String(args.task || args.prompt || args.goal || '');
      if (task.length > 0) {
        // Use first paragraph or 500 chars of task as reason
        const firstPara = task.split(/\n\n/)[0];
        return firstPara.length > 500 ? firstPara.slice(0, 500) + '...' : firstPara;
      }
    }

    // For file operations, look for context about the file
    if (['write_file', 'edit_file'].includes(toolCall.name)) {
      const args = toolCall.arguments as Record<string, unknown>;
      const path = String(args.path || args.file_path || '');

      // Look for mentions of this file in the assistant's explanation
      if (path && content.toLowerCase().includes(path.toLowerCase().split('/').pop() || '')) {
        // Extract the sentence(s) mentioning this file
        const sentences = content.split(/[.!?\n]+/).filter(s =>
          s.toLowerCase().includes(path.toLowerCase().split('/').pop() || '')
        );
        if (sentences.length > 0) {
          const relevant = sentences.slice(0, 2).join('. ').trim();
          return relevant.length > 500 ? relevant.slice(0, 500) + '...' : relevant;
        }
      }
    }

    // Fallback: use first 500 chars instead of 200
    // Look for the first meaningful paragraph/section
    const paragraphs = content.split(/\n\n+/).filter(p => p.trim().length > 20);
    if (paragraphs.length > 0) {
      const firstPara = paragraphs[0].trim();
      return firstPara.length > 500 ? firstPara.slice(0, 500) + '...' : firstPara;
    }

    // Ultimate fallback
    return content.length > 500 ? content.slice(0, 500) + '...' : content;
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
      console.warn(`[Checkpoint] Warning: ${warning}`);
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
      console.log(`  📦 Compacted ${compactedCount} tool outputs (saved ~${Math.round(savedChars / 4)} tokens)`);
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
   * Spawn an agent to execute a task.
   * Returns the result when the agent completes.
   *
   * @param agentName - Name of the agent to spawn (researcher, coder, etc.)
   * @param task - The task description for the agent
   * @param constraints - Optional constraints to keep the subagent focused
   */
  async spawnAgent(agentName: string, task: string, constraints?: import('./tools/agent.js').SpawnConstraints): Promise<SpawnResult> {
    if (!this.agentRegistry) {
      return {
        success: false,
        output: 'Agent registry not initialized',
        metrics: { tokens: 0, duration: 0, toolCalls: 0 },
      };
    }

    const agentDef = this.agentRegistry.getAgent(agentName);
    if (!agentDef) {
      return {
        success: false,
        output: `Agent not found: ${agentName}`,
        metrics: { tokens: 0, duration: 0, toolCalls: 0 },
      };
    }

    // DUPLICATE SPAWN PREVENTION with SEMANTIC SIMILARITY
    // First try exact string match, then check semantic similarity for similar tasks
    const SEMANTIC_SIMILARITY_THRESHOLD = 0.75; // 75% similarity = duplicate
    const taskKey = `${agentName}:${task.slice(0, 150).toLowerCase().replace(/\s+/g, ' ').trim()}`;
    const now = Date.now();

    // Clean up old entries (older than dedup window)
    for (const [key, entry] of this.spawnedTasks.entries()) {
      if (now - entry.timestamp > ProductionAgent.SPAWN_DEDUP_WINDOW_MS) {
        this.spawnedTasks.delete(key);
      }
    }

    // Check for exact match first
    let existingMatch = this.spawnedTasks.get(taskKey);
    let matchType: 'exact' | 'semantic' = 'exact';

    // If no exact match, check for semantic similarity among same agent's tasks
    if (!existingMatch) {
      for (const [key, entry] of this.spawnedTasks.entries()) {
        // Only compare tasks from the same agent type
        if (!key.startsWith(`${agentName}:`)) continue;
        if (now - entry.timestamp >= ProductionAgent.SPAWN_DEDUP_WINDOW_MS) continue;

        // Extract the task portion from the key
        const existingTask = key.slice(agentName.length + 1);
        const similarity = calculateTaskSimilarity(task, existingTask);

        if (similarity >= SEMANTIC_SIMILARITY_THRESHOLD) {
          existingMatch = entry;
          matchType = 'semantic';
          this.observability?.logger?.debug('Semantic duplicate detected', {
            agent: agentName,
            newTask: task.slice(0, 80),
            existingTask: existingTask.slice(0, 80),
            similarity: (similarity * 100).toFixed(1) + '%',
          });
          break;
        }
      }
    }

    if (existingMatch && now - existingMatch.timestamp < ProductionAgent.SPAWN_DEDUP_WINDOW_MS) {
      // Same or semantically similar task spawned within the dedup window
      this.observability?.logger?.warn('Duplicate spawn prevented', {
        agent: agentName,
        task: task.slice(0, 100),
        matchType,
        originalTimestamp: existingMatch.timestamp,
        elapsedMs: now - existingMatch.timestamp,
      });

      const duplicateMessage = `[DUPLICATE SPAWN PREVENTED${matchType === 'semantic' ? ' - SEMANTIC MATCH' : ''}]\n` +
        `This task was already spawned ${Math.round((now - existingMatch.timestamp) / 1000)}s ago.\n` +
        `${existingMatch.queuedChanges > 0
          ? `The previous spawn queued ${existingMatch.queuedChanges} change(s) to the pending plan.\n` +
            `These changes are already in your plan - do NOT spawn again.\n`
          : ''
        }Previous result summary:\n${existingMatch.result.slice(0, 500)}`;

      return {
        success: true, // Mark as success since original task completed
        output: duplicateMessage,
        metrics: { tokens: 0, duration: 0, toolCalls: 0 },
      };
    }

    // Generate a unique ID for this agent instance that will be used consistently
    // throughout the agent's lifecycle (spawn event, token events, completion events)
    const agentId = `spawn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    this.emit({ type: 'agent.spawn', agentId, name: agentName, task });
    this.observability?.logger?.info('Spawning agent', { name: agentName, task });

    const startTime = Date.now();
    const childSessionId = `subagent-${agentName}-${Date.now()}`;
    const childTraceId = `trace-${childSessionId}`;
    let workerResultId: string | undefined;

    try {
      // Filter tools for this agent
      const agentTools = filterToolsForAgent(agentDef, Array.from(this.tools.values()));

      // Resolve model - abstract tiers (fast/balanced/quality) should use parent's model
      // Only use agentDef.model if it's an actual model ID (contains '/')
      const resolvedModel = (agentDef.model && agentDef.model.includes('/'))
        ? agentDef.model
        : this.config.model;

      // Persist subagent task lifecycle in durable storage when available
      if (this.store?.hasWorkerResultsFeature()) {
        try {
          workerResultId = this.store.createWorkerResult(
            agentId,
            task.slice(0, 500),
            resolvedModel || 'default'
          );
        } catch (storeErr) {
          this.observability?.logger?.warn('Failed to create worker result record', {
            agentId,
            error: (storeErr as Error).message,
          });
        }
      }

      // Get subagent config with agent-type-specific timeouts and iteration limits
      // Uses dynamic configuration based on agent type (researcher needs more time than reviewer)
      const subagentConfig = this.config.subagent;
      const hasSubagentConfig = subagentConfig !== false && subagentConfig !== undefined;

      // Agent-type-specific timeout: researchers get 5min, reviewers get 2min, etc.
      const agentTypeTimeout = getSubagentTimeout(agentName);
      const configTimeout = hasSubagentConfig
        ? (subagentConfig as { defaultTimeout?: number }).defaultTimeout
        : undefined;
      const subagentTimeout = configTimeout ?? agentTypeTimeout;

      // Agent-type-specific iteration limit: researchers get 25, documenters get 10, etc.
      const agentTypeMaxIter = getSubagentMaxIterations(agentName);
      const configMaxIter = hasSubagentConfig
        ? (subagentConfig as { defaultMaxIterations?: number }).defaultMaxIterations
        : undefined;
      const defaultMaxIterations = agentDef.maxIterations ?? configMaxIter ?? agentTypeMaxIter;

      // BLACKBOARD CONTEXT INJECTION
      // Gather relevant context from the blackboard for the subagent
      let blackboardContext = '';
      const parentAgentId = `parent-${Date.now()}`;

      if (this.blackboard) {
        // Post parent's exploration context before spawning
        this.blackboard.post(parentAgentId, {
          topic: 'spawn.parent_context',
          content: `Parent spawning ${agentName} for task: ${task.slice(0, 200)}`,
          type: 'progress',
          confidence: 1,
          metadata: { agentName, taskPreview: task.slice(0, 100) },
        });

        // Gather recent findings that might help the subagent
        const recentFindings = this.blackboard.query({
          limit: 5,
          types: ['discovery', 'analysis', 'progress'],
          minConfidence: 0.7,
        });

        if (recentFindings.length > 0) {
          const findingsSummary = recentFindings
            .map(f => `- [${f.agentId}] ${f.topic}: ${f.content.slice(0, 150)}${f.content.length > 150 ? '...' : ''}`)
            .join('\n');
          blackboardContext = `\n\n**BLACKBOARD CONTEXT (from parent/sibling agents):**\n${findingsSummary}\n`;
        }
      }

      // Check for files already being modified in parent's pending plan
      const currentPlan = this.pendingPlanManager.getPendingPlan();
      if (currentPlan && currentPlan.proposedChanges.length > 0) {
        const pendingFiles = currentPlan.proposedChanges
          .filter((c: { tool: string }) => c.tool === 'write_file' || c.tool === 'edit_file')
          .map((c: { args: { path?: string; file_path?: string } }) => c.args.path || c.args.file_path)
          .filter(Boolean) as string[];

        if (pendingFiles.length > 0) {
          blackboardContext += `\n**FILES ALREADY IN PENDING PLAN (do not duplicate):**\n${pendingFiles.slice(0, 10).join('\n')}\n`;
        }
      }

      // CONSTRAINT INJECTION
      // Add constraints to the subagent's context if provided
      // Also always include budget awareness so subagents know their limits
      const constraintParts: string[] = [];

      // BUDGET AWARENESS: Always inject so subagent understands its limits
      const subagentBudgetTokens = constraints?.maxTokens ?? SUBAGENT_BUDGET.maxTokens ?? 100000;
      const subagentBudgetMinutes = Math.round((SUBAGENT_BUDGET.maxDuration ?? 240000) / 60000);
      constraintParts.push(
        `**RESOURCE AWARENESS (CRITICAL):**\n` +
        `- Token budget: ~${(subagentBudgetTokens / 1000).toFixed(0)}k tokens\n` +
        `- Time limit: ~${subagentBudgetMinutes} minutes\n` +
        `- You will receive warnings at 70% usage. When warned, WRAP UP immediately.\n` +
        `- Do not explore indefinitely - be focused and efficient.\n` +
        `- If approaching limits, summarize findings and return.\n` +
        `- **STRUCTURED WRAPUP:** When told to wrap up, respond with ONLY this JSON (no tool calls):\n` +
        `  {"findings":[...], "actionsTaken":[...], "failures":[...], "remainingWork":[...], "suggestedNextSteps":[...]}`
      );

      if (constraints) {
        if (constraints.focusAreas && constraints.focusAreas.length > 0) {
          constraintParts.push(`**FOCUS AREAS (limit exploration to these paths):**\n${constraints.focusAreas.map(a => `  - ${a}`).join('\n')}`);
        }

        if (constraints.excludeAreas && constraints.excludeAreas.length > 0) {
          constraintParts.push(`**EXCLUDED AREAS (do NOT explore these):**\n${constraints.excludeAreas.map(a => `  - ${a}`).join('\n')}`);
        }

        if (constraints.requiredDeliverables && constraints.requiredDeliverables.length > 0) {
          constraintParts.push(`**REQUIRED DELIVERABLES (you must produce these):**\n${constraints.requiredDeliverables.map(d => `  - ${d}`).join('\n')}`);
        }

        if (constraints.timeboxMinutes) {
          constraintParts.push(`**TIME LIMIT:** ${constraints.timeboxMinutes} minutes (soft limit - wrap up if approaching)`);
        }
      }

      const constraintContext = `\n\n**EXECUTION CONSTRAINTS:**\n${constraintParts.join('\n\n')}\n`;

      // Build subagent system prompt with subagent-specific plan mode addition
      const parentMode = this.getMode();
      const subagentSystemPrompt = parentMode === 'plan'
        ? `${agentDef.systemPrompt}\n\n${SUBAGENT_PLAN_MODE_ADDITION}${blackboardContext}${constraintContext}`
        : `${agentDef.systemPrompt}${blackboardContext}${constraintContext}`;

      // Create a sub-agent with the agent's config
      // Use SUBAGENT_BUDGET to constrain resource usage (prevents runaway token consumption)
      const subAgent = new ProductionAgent({
        provider: this.provider,
        tools: agentTools,
        // Pass toolResolver so subagent can lazy-load MCP tools
        toolResolver: this.toolResolver || undefined,
        // Pass MCP tool summaries so subagent knows what tools are available
        mcpToolSummaries: this.config.mcpToolSummaries,
        systemPrompt: subagentSystemPrompt,
        model: resolvedModel,
        maxIterations: agentDef.maxIterations || defaultMaxIterations,
        // Inherit some features but keep subagent simpler
        memory: false,
        planning: false,
        reflection: false,
        observability: this.config.observability,
        sandbox: this.config.sandbox,
        humanInLoop: this.config.humanInLoop,
        executionPolicy: this.config.executionPolicy,
        threads: false,
        // Disable hooks console output in subagents - parent handles event display
        hooks: this.config.hooks === false ? false : {
          enabled: true,
          builtIn: { logging: false, timing: false, metrics: false },
          custom: [],
        },
        // Share parent's blackboard for coordination between parallel subagents
        blackboard: this.blackboard || undefined,
        // CONSTRAINED BUDGET: Subagents get smaller budget to prevent runaway consumption
        // Uses SUBAGENT_BUDGET (100k tokens, 4 min) vs STANDARD_BUDGET (200k, 5 min)
        budget: constraints?.maxTokens
          ? { ...SUBAGENT_BUDGET, maxTokens: constraints.maxTokens }
          : SUBAGENT_BUDGET,
      });

      // CRITICAL: Subagent inherits parent's mode
      // This ensures that if parent is in plan mode:
      // - Subagent's read operations execute immediately (visible exploration)
      // - Subagent's write operations get queued in the subagent's pending plan
      // - User maintains control over what actually gets written
      if (parentMode !== 'build') {
        subAgent.setMode(parentMode);
      }

      // Pass parent's iteration count to subagent for accurate budget tracking
      // This prevents subagents from consuming excessive iterations when parent already used many
      subAgent.setParentIterations(this.getTotalIterations());

      // UNIFIED TRACING: Share parent's trace collector with subagent context
      // This ensures all subagent events are written to the same trace file as the parent,
      // tagged with subagent context for proper aggregation in /trace output
      if (this.traceCollector) {
        const subagentTraceView = this.traceCollector.createSubagentView({
          parentSessionId: this.traceCollector.getSessionId() || 'unknown',
          agentType: agentName,
          spawnedAtIteration: this.state.iteration,
        });
        subAgent.setTraceCollector(subagentTraceView);
      }

      // GRACEFUL TIMEOUT with WRAPUP PHASE
      // Instead of instant death on timeout, the subagent gets a wrapup window
      // to produce a structured summary before being killed:
      // 1. Normal operation: progress extends idle timer
      // 2. Wrapup phase: 30s before hard kill, wrapup callback fires → forceTextOnly
      // 3. Hard kill: race() throws CancellationError after wrapup window
      const IDLE_TIMEOUT = 120000; // 2 minutes without progress = timeout
      let WRAPUP_WINDOW = 30000;
      let IDLE_CHECK_INTERVAL = 5000;
      if (this.config.subagent) {
        WRAPUP_WINDOW = this.config.subagent.wrapupWindowMs ?? WRAPUP_WINDOW;
        IDLE_CHECK_INTERVAL = this.config.subagent.idleCheckIntervalMs ?? IDLE_CHECK_INTERVAL;
      }
      const progressAwareTimeout = createGracefulTimeout(
        subagentTimeout,  // Max total time (hard limit from agent type config)
        IDLE_TIMEOUT,     // Idle timeout (soft limit - no progress triggers this)
        WRAPUP_WINDOW,    // Wrapup window before hard kill
        IDLE_CHECK_INTERVAL
      );

      // Register wrapup callback — fires 30s before hard kill
      // This triggers the subagent's forceTextOnly path for a structured summary
      progressAwareTimeout.onWrapupWarning(() => {
        this.emit({
          type: 'subagent.wrapup.started',
          agentId,
          agentType: agentName,
          reason: 'Timeout approaching - graceful wrapup window opened',
          elapsedMs: Date.now() - startTime,
        });
        subAgent.requestWrapup('Timeout approaching — produce structured summary');
      });

      // Forward events from subagent with context (track for cleanup)
      // Also report progress to the timeout tracker
      const unsubSubAgent = subAgent.subscribe(event => {
        // Tag event with subagent source AND unique ID so TUI can properly attribute
        // events to the specific agent instance (critical for multiple same-type agents)
        const taggedEvent = { ...event, subagent: agentName, subagentId: agentId };
        this.emit(taggedEvent);

        // Report progress for timeout extension
        // Progress events: tool calls, LLM responses, token updates
        const progressEvents = ['tool.start', 'tool.complete', 'llm.start', 'llm.complete'];
        if (progressEvents.includes(event.type)) {
          progressAwareTimeout.reportProgress();
        }
      });

      // Link parent's cancellation with progress-aware timeout so ESC propagates to subagents
      const parentSource = this.cancellation?.getSource();
      const effectiveSource = parentSource
        ? createLinkedToken(parentSource, progressAwareTimeout)
        : progressAwareTimeout;

      // CRITICAL: Pass the cancellation token to the subagent so it can check and stop
      // gracefully when timeout fires. Without this, the subagent continues running as
      // a "zombie" even after race() returns with a timeout error.
      subAgent.setExternalCancellation(effectiveSource.token);

      // Pause parent's duration timer while subagent runs to prevent
      // the parent from timing out on wall-clock while waiting for subagent
      this.economics?.pauseDuration();

      try {
        // Run the task with cancellation propagation from parent
        const result = await race(subAgent.run(task), effectiveSource.token);

        const duration = Date.now() - startTime;

        // BEFORE cleanup - extract subagent's pending plan and merge into parent's plan
        // This ensures that when a subagent in plan mode queues writes, they bubble up to the parent
        let queuedChangeSummary = '';
        let queuedChangesCount = 0;
        if (subAgent.hasPendingPlan()) {
          const subPlan = subAgent.getPendingPlan();
          if (subPlan && subPlan.proposedChanges.length > 0) {
            queuedChangesCount = subPlan.proposedChanges.length;

            // Emit event for TUI to display
            this.emit({
              type: 'agent.pending_plan',
              agentId: agentName,
              changes: subPlan.proposedChanges,
            });

            // Build detailed summary of what was queued for the return message
            // This prevents the "doom loop" where parent doesn't know what subagent did
            const changeSummaries = subPlan.proposedChanges.map(c => {
              if (c.tool === 'write_file' || c.tool === 'edit_file') {
                const path = c.args.path || c.args.file_path || '(unknown file)';
                return `  - [${c.tool}] ${path}: ${c.reason}`;
              } else if (c.tool === 'bash') {
                const cmd = String(c.args.command || '').slice(0, 60);
                return `  - [bash] ${cmd}${String(c.args.command || '').length > 60 ? '...' : ''}: ${c.reason}`;
              }
              return `  - [${c.tool}]: ${c.reason}`;
            });

            queuedChangeSummary = `\n\n[PLAN MODE - CHANGES QUEUED TO PARENT]\n` +
              `The following ${subPlan.proposedChanges.length} change(s) have been queued in the parent's pending plan:\n` +
              changeSummaries.join('\n') + '\n' +
              `\nThese changes are now in YOUR pending plan. The task for this subagent is COMPLETE.\n` +
              `Do NOT spawn another agent for the same task - the changes are already queued.\n` +
              `Use /show-plan to see all pending changes, /approve to execute them.`;

            // Merge into parent's pending plan with subagent context
            for (const change of subPlan.proposedChanges) {
              this.pendingPlanManager.addProposedChange(
                change.tool,
                { ...change.args, _fromSubagent: agentName },
                `[${agentName}] ${change.reason}`,
                change.toolCallId
              );
            }
          }

          // Also merge exploration summary if available
          if (subPlan?.explorationSummary) {
            this.pendingPlanManager.appendExplorationFinding(
              `[${agentName}] ${subPlan.explorationSummary}`
            );
          }
        }

        // If subagent queued changes, override output with informative message
        // This is critical to prevent doom loops where parent doesn't understand what happened
        const finalOutput = queuedChangeSummary
          ? (result.response || '') + queuedChangeSummary
          : (result.response || result.error || '');

        // Parse structured closure report from agent's response (if it produced one)
        const structured = parseStructuredClosureReport(
          result.response || '',
          'completed'
        );

        const spawnResultFinal: SpawnResult = {
          success: result.success,
          output: finalOutput,
          metrics: {
            tokens: result.metrics.totalTokens,
            duration,
            toolCalls: result.metrics.toolCalls,
          },
          structured,
        };

        if (workerResultId && this.store?.hasWorkerResultsFeature()) {
          try {
            this.store.completeWorkerResult(workerResultId, {
              fullOutput: finalOutput,
              summary: finalOutput.slice(0, 500),
              artifacts: structured ? [{ type: 'structured_report', data: structured }] : undefined,
              metrics: {
                tokens: result.metrics.totalTokens,
                duration,
                toolCalls: result.metrics.toolCalls,
              },
            });
          } catch (storeErr) {
            this.observability?.logger?.warn('Failed to persist worker result', {
              agentId,
              error: (storeErr as Error).message,
            });
          }
        }

        this.emit({
          type: 'agent.complete',
          agentId,  // Use unique spawn ID for precise tracking
          agentType: agentName,  // Keep type for display purposes
          success: result.success,
          output: finalOutput.slice(0, 500),  // Include output preview
        });
        if (progressAwareTimeout.isInWrapupPhase()) {
          this.emit({
            type: 'subagent.wrapup.completed',
            agentId,
            agentType: agentName,
            elapsedMs: Date.now() - startTime,
          });
        }

        // Enhanced tracing: Record subagent completion
        this.traceCollector?.record({
          type: 'subagent.link',
          data: {
            parentSessionId: this.traceCollector.getSessionId() || 'unknown',
            childSessionId,
            childTraceId,
            childConfig: {
              agentType: agentName,
              model: resolvedModel || 'default',
              task,
              tools: agentTools.map(t => t.name),
            },
            spawnContext: {
              reason: `Delegated task: ${task.slice(0, 100)}`,
              expectedOutcome: agentDef.description,
              parentIteration: this.state.iteration,
            },
            result: {
              success: result.success,
              summary: (result.response || result.error || '').slice(0, 500),
              tokensUsed: result.metrics.totalTokens,
              durationMs: duration,
            },
          },
        });

        // Unsubscribe from subagent events before cleanup
        unsubSubAgent();
        await subAgent.cleanup();

        // Cache result for duplicate spawn prevention
        // Use the same taskKey from the dedup check above
        this.spawnedTasks.set(taskKey, {
          timestamp: Date.now(),
          result: finalOutput,
          queuedChanges: queuedChangesCount,
        });

        return spawnResultFinal;
      } catch (err) {
        // Handle cancellation (user ESC or timeout) for cleaner error messages
        if (isCancellationError(err)) {
          const duration = Date.now() - startTime;
          const isUserCancellation = parentSource?.isCancellationRequested;
          const reason = isUserCancellation
            ? 'User cancelled'
            : (err as CancellationError).reason || `Timed out after ${subagentTimeout}ms`;
          this.emit({ type: 'agent.error', agentId, agentType: agentName, error: reason });
          if (!isUserCancellation) {
            this.emit({
              type: 'subagent.timeout.hard_kill',
              agentId,
              agentType: agentName,
              reason,
              elapsedMs: Date.now() - startTime,
            });
          }

          // =======================================================================
          // PRESERVE PARTIAL RESULTS
          // Instead of discarding all work, capture whatever the subagent produced
          // before timeout. This prevents the "zombie agent" problem where tokens
          // are consumed but results are lost.
          // =======================================================================
          const subagentState = subAgent.getState();
          const subagentMetrics = subAgent.getMetrics();

          // Extract partial response from the last assistant message
          const assistantMessages = subagentState.messages.filter(m => m.role === 'assistant');
          const lastAssistantMsg = assistantMessages[assistantMessages.length - 1];
          const partialResponse = typeof lastAssistantMsg?.content === 'string'
            ? lastAssistantMsg.content
            : '';

          // Extract pending plan before cleanup (even on cancellation, preserve any queued work)
          let cancelledQueuedSummary = '';
          if (subAgent.hasPendingPlan()) {
            const subPlan = subAgent.getPendingPlan();
            if (subPlan && subPlan.proposedChanges.length > 0) {
              this.emit({
                type: 'agent.pending_plan',
                agentId: agentName,
                changes: subPlan.proposedChanges,
              });

              // Build summary of changes that were queued before cancellation
              const changeSummaries = subPlan.proposedChanges.map(c => {
                if (c.tool === 'write_file' || c.tool === 'edit_file') {
                  const path = c.args.path || c.args.file_path || '(unknown file)';
                  return `  - [${c.tool}] ${path}: ${c.reason}`;
                } else if (c.tool === 'bash') {
                  const cmd = String(c.args.command || '').slice(0, 60);
                  return `  - [bash] ${cmd}...: ${c.reason}`;
                }
                return `  - [${c.tool}]: ${c.reason}`;
              });

              cancelledQueuedSummary = `\n\n[PLAN MODE - CHANGES QUEUED BEFORE CANCELLATION]\n` +
                `${subPlan.proposedChanges.length} change(s) were queued to the parent plan:\n` +
                changeSummaries.join('\n') + '\n' +
                `These changes are preserved in your pending plan.`;

              for (const change of subPlan.proposedChanges) {
                this.pendingPlanManager.addProposedChange(
                  change.tool,
                  { ...change.args, _fromSubagent: agentName },
                  `[${agentName}] ${change.reason}`,
                  change.toolCallId
                );
              }
            }

            // Also preserve exploration summary
            if (subPlan?.explorationSummary) {
              this.pendingPlanManager.appendExplorationFinding(
                `[${agentName}] ${subPlan.explorationSummary}`
              );
            }
          }

          // Unsubscribe from subagent events and cleanup gracefully
          unsubSubAgent();
          try {
            await subAgent.cleanup();
          } catch {
            // Ignore cleanup errors on cancellation
          }

          // Build output message with partial results
          const baseOutput = isUserCancellation
            ? `Subagent '${agentName}' was cancelled by user.`
            : `Subagent '${agentName}' timed out after ${Math.round(subagentTimeout / 1000)}s.`;

          // Include partial response if we have one
          const partialResultSection = partialResponse
            ? `\n\n[PARTIAL RESULTS BEFORE TIMEOUT]\n${partialResponse.slice(0, 2000)}${partialResponse.length > 2000 ? '...(truncated)' : ''}`
            : '';

          // Enhanced tracing: Record subagent timeout with partial results
          this.traceCollector?.record({
            type: 'subagent.link',
            data: {
              parentSessionId: this.traceCollector.getSessionId() || 'unknown',
              childSessionId,
              childTraceId,
              childConfig: {
                agentType: agentName,
                model: resolvedModel || 'default',
                task,
                tools: agentTools.map(t => t.name),
              },
              spawnContext: {
                reason: `Delegated task: ${task.slice(0, 100)}`,
                expectedOutcome: agentDef.description,
                parentIteration: this.state.iteration,
              },
              result: {
                success: false,
                summary: `[TIMEOUT] ${baseOutput}\n${partialResponse.slice(0, 200)}`,
                tokensUsed: subagentMetrics.totalTokens,
                durationMs: duration,
              },
            },
          });

          // Parse structured closure report from partial response
          const exitReason = isUserCancellation ? 'cancelled' as const : 'timeout_graceful' as const;
          const structured = parseStructuredClosureReport(
            partialResponse,
            exitReason,
            task
          );

          if (workerResultId && this.store?.hasWorkerResultsFeature()) {
            try {
              this.store.failWorkerResult(workerResultId, reason);
            } catch (storeErr) {
              this.observability?.logger?.warn('Failed to mark cancelled worker result as failed', {
                agentId,
                error: (storeErr as Error).message,
              });
            }
          }

          return {
            success: false,
            output: baseOutput + partialResultSection + cancelledQueuedSummary,
            // IMPORTANT: Use actual metrics instead of zeros
            // This ensures accurate token tracking in /trace output
            metrics: {
              tokens: subagentMetrics.totalTokens,
              duration,
              toolCalls: subagentMetrics.toolCalls,
            },
            structured,
          };
        }
        throw err; // Re-throw non-cancellation errors
      } finally {
        // Resume parent's duration timer now that subagent is done
        this.economics?.resumeDuration();
        // Dispose both sources (linked source disposes its internal state, timeout source handles its timer)
        effectiveSource.dispose();
        progressAwareTimeout.dispose();
      }
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'agent.error', agentId, agentType: agentName, error });

      if (workerResultId && this.store?.hasWorkerResultsFeature()) {
        try {
          this.store.failWorkerResult(workerResultId, error);
        } catch (storeErr) {
          this.observability?.logger?.warn('Failed to mark worker result as failed', {
            agentId,
            error: (storeErr as Error).message,
          });
        }
      }

      return {
        success: false,
        output: `Agent error: ${error}`,
        metrics: { tokens: 0, duration: Date.now() - startTime, toolCalls: 0 },
      };
    }
  }

  /**
   * Spawn multiple agents in parallel to work on independent tasks.
   * Uses the shared blackboard for coordination and conflict prevention.
   *
   * Uses Promise.allSettled to handle partial failures gracefully - if one
   * agent fails or times out, others can still complete successfully.
   */
  async spawnAgentsParallel(
    tasks: Array<{ agent: string; task: string }>
  ): Promise<SpawnResult[]> {
    // Emit start event for TUI visibility
    this.emit({
      type: 'parallel.spawn.start',
      count: tasks.length,
      agents: tasks.map(t => t.agent),
    });

    // Execute all tasks in parallel using allSettled to handle partial failures
    const promises = tasks.map(({ agent, task }) => this.spawnAgent(agent, task));
    const settled = await Promise.allSettled(promises);

    // Convert settled results to SpawnResult array
    const results: SpawnResult[] = settled.map((result, i) => {
      if (result.status === 'fulfilled') {
        return result.value;
      }
      // Handle rejected promises (shouldn't happen since spawnAgent catches errors internally,
      // but this is a safety net for unexpected failures)
      const error = result.reason instanceof Error ? result.reason.message : String(result.reason);
      this.emit({
        type: 'agent.error',
        agentId: tasks[i].agent,
        error: `Unexpected parallel spawn error: ${error}`,
      });
      return {
        success: false,
        output: `Parallel spawn error: ${error}`,
        metrics: { tokens: 0, duration: 0, toolCalls: 0 },
      };
    });

    // Emit completion event
    this.emit({
      type: 'parallel.spawn.complete',
      count: tasks.length,
      successCount: results.filter(r => r.success).length,
      results: results.map((r, i) => ({
        agent: tasks[i].agent,
        success: r.success,
        tokens: r.metrics?.tokens || 0,
      })),
    });

    return results;
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
      console.warn('[ProductionAgent] Cancellation not enabled');
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
      console.warn('[ProductionAgent] LSP not enabled, cannot enable LSP file tools');
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

    // Clear blackboard (releases file claim locks)
    this.blackboard?.clear();

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
// STRUCTURED CLOSURE REPORT PARSER
// =============================================================================

/**
 * Parse a structured closure report from a subagent's text response.
 * The subagent may have produced JSON in response to a TIMEOUT_WRAPUP_PROMPT.
 *
 * @param text - The subagent's last response text
 * @param defaultExitReason - Exit reason to use (completed, timeout_graceful, cancelled, etc.)
 * @param fallbackTask - Original task description for fallback remainingWork
 * @returns Parsed StructuredClosureReport, or undefined if no JSON found and no fallback needed
 */
export function parseStructuredClosureReport(
  text: string,
  defaultExitReason: StructuredClosureReport['exitReason'],
  fallbackTask?: string,
): StructuredClosureReport | undefined {
  if (!text) {
    // No text at all — create a hard timeout fallback if we have a task
    if (fallbackTask) {
      return {
        findings: [],
        actionsTaken: [],
        failures: ['Timeout before producing structured summary'],
        remainingWork: [fallbackTask],
        exitReason: 'timeout_hard',
      };
    }
    return undefined;
  }

  try {
    // Try to extract JSON from the response
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      // Validate that it looks like a closure report (has at least one expected field)
      if (parsed.findings || parsed.actionsTaken || parsed.failures || parsed.remainingWork) {
        return {
          findings: Array.isArray(parsed.findings) ? parsed.findings : [],
          actionsTaken: Array.isArray(parsed.actionsTaken) ? parsed.actionsTaken : [],
          failures: Array.isArray(parsed.failures) ? parsed.failures : [],
          remainingWork: Array.isArray(parsed.remainingWork) ? parsed.remainingWork : [],
          exitReason: defaultExitReason,
          suggestedNextSteps: Array.isArray(parsed.suggestedNextSteps) ? parsed.suggestedNextSteps : undefined,
        };
      }
    }
  } catch {
    // JSON parse failed — fall through to fallback
  }

  // Fallback: LLM didn't produce valid JSON but we have text
  if (defaultExitReason !== 'completed') {
    return {
      findings: [text.slice(0, 500)],
      actionsTaken: [],
      failures: ['Did not produce structured JSON summary'],
      remainingWork: fallbackTask ? [fallbackTask] : [],
      exitReason: defaultExitReason === 'timeout_graceful' ? 'timeout_hard' : defaultExitReason,
    };
  }

  // For completed agents, don't force a structured report if they didn't produce one
  return undefined;
}
