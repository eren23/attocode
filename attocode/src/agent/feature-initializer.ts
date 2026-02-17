/**
 * Feature initialization logic extracted from ProductionAgent.
 * Initializes all integration managers based on configuration.
 */

import type {
  LLMProvider,
  ToolDefinition,
  AgentEvent,
  AgentRoleConfig,
  Message,
} from '../types.js';

import type { buildConfig } from '../defaults.js';
import { isFeatureEnabled, getEnabledFeatures } from '../defaults.js';

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
  CancellationManager,
  createCancellationManager,
  ResourceManager,
  createResourceManager,
  LSPManager,
  createLSPManager,
  SemanticCacheManager,
  createSemanticCacheManager,
  SkillManager,
  createSkillManager,
  ContextEngineeringManager,
  createContextEngineering,
  CodebaseContextManager,
  createCodebaseContext,
  SwarmOrchestrator,
  createSwarmOrchestrator,
  createThrottledProvider,
  FREE_TIER_THROTTLE,
  PAID_TIER_THROTTLE,
  type SwarmConfig,
  WorkLog,
  createWorkLog,
  VerificationGate,
  createVerificationGate,
  createTypeCheckerState,
  InjectionBudgetManager,
  createInjectionBudgetManager,
  SelfImprovementProtocol,
  createSelfImprovementProtocol,
  SubagentOutputStore,
  createSubagentOutputStore,
  AutoCheckpointManager,
  createAutoCheckpointManager,
  ToolRecommendationEngine,
  createToolRecommendationEngine,
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
  SharedBlackboard,
  SharedBudgetPool,
  TaskManager,
  createTaskManager,
  createSerperSearchTool,
} from '../integrations/index.js';

import { resolvePolicyProfile } from '../integrations/safety/policy-engine.js';

import type { SharedContextState } from '../shared/shared-context-state.js';
import type { SharedEconomicsState } from '../shared/shared-economics-state.js';
import { TraceCollector, createTraceCollector } from '../tracing/trace-collector.js';
import { modelRegistry } from '../costs/index.js';
import { getModelContextLength } from '../integrations/utilities/openrouter-pricing.js';
import { createComponentLogger } from '../integrations/utilities/logger.js';

import {
  createBoundSpawnAgentTool,
  createBoundSpawnAgentsParallelTool,
  type SpawnConstraints,
} from '../tools/agent.js';

import { createTaskTools } from '../tools/tasks.js';

import { type AgentStateMachine, createAgentStateMachine } from '../core/agent-state-machine.js';

import type { SpawnResult } from '../integrations/index.js';

const log = createComponentLogger('FeatureInitializer');

// =============================================================================
// AGENT INTERNALS INTERFACE
// =============================================================================

/**
 * Interface representing the agent fields that initializeFeatures needs access to.
 * This allows the function to be standalone while still modifying agent state.
 */
export interface AgentInternals {
  // Core fields (read)
  config: ReturnType<typeof buildConfig>;
  provider: LLMProvider;
  tools: Map<string, ToolDefinition>;
  agentId: string;

  // Integration managers (read/write)
  hooks: HookManager | null;
  memory: MemoryManager | null;
  planning: PlanningManager | null;
  observability: ObservabilityManager | null;
  traceCollector: TraceCollector | null;
  safety: SafetyManager | null;
  routing: RoutingManager | null;
  multiAgent: MultiAgentManager | null;
  react: ReActManager | null;
  executionPolicy: ExecutionPolicyManager | null;
  threadManager: ThreadManager | null;
  rules: RulesManager | null;
  economics: ExecutionEconomicsManager | null;
  stateMachine: AgentStateMachine | null;
  workLog: WorkLog | null;
  verificationGate: VerificationGate | null;
  injectionBudget: InjectionBudgetManager | null;
  selfImprovement: SelfImprovementProtocol | null;
  subagentOutputStore: SubagentOutputStore | null;
  autoCheckpointManager: AutoCheckpointManager | null;
  toolRecommendation: ToolRecommendationEngine | null;
  agentRegistry: AgentRegistry | null;
  cancellation: CancellationManager | null;
  resourceManager: ResourceManager | null;
  lspManager: LSPManager | null;
  semanticCache: SemanticCacheManager | null;
  skillManager: SkillManager | null;
  contextEngineering: ContextEngineeringManager | null;
  codebaseContext: CodebaseContextManager | null;
  interactivePlanner: InteractivePlanner | null;
  recursiveContext: RecursiveContextManager | null;
  learningStore: LearningStore | null;
  compactor: Compactor | null;
  autoCompactionManager: AutoCompactionManager | null;
  modeManager: unknown;
  taskManager: TaskManager | null;
  swarmOrchestrator: SwarmOrchestrator | null;
  budgetPool: SharedBudgetPool | null;
  blackboard: SharedBlackboard | null;
  typeCheckerState: import('../integrations/safety/type-checker.js').TypeCheckerState | null;

  // Shared state (read/write)
  _sharedContextState: SharedContextState | null;
  _sharedEconomicsState: SharedEconomicsState | null;

  // Arrays (push targets)
  initPromises: Promise<void>[];
  unsubscribers: Array<() => void>;

  // Methods
  emit(event: AgentEvent): void;
  spawnAgent(agentName: string, task: string, constraints?: SpawnConstraints): Promise<SpawnResult>;
  spawnAgentsParallel(tasks: Array<{ agent: string; task: string }>): Promise<SpawnResult[]>;
}

// =============================================================================
// FEATURE INITIALIZATION
// =============================================================================

/**
 * Initialize all enabled features on an agent.
 * This is the extracted body of ProductionAgent.initializeFeatures().
 * All `this.` references are replaced with `agent.`.
 */
export function initializeFeatures(agent: AgentInternals): void {
  // Debug output only when DEBUG env var is set
  if (process.env.DEBUG) {
    const features = getEnabledFeatures(agent.config);
    log.debug('Initializing with features', { features: features.join(', ') });
  }

  // Hooks & Plugins
  if (isFeatureEnabled(agent.config.hooks) && isFeatureEnabled(agent.config.plugins)) {
    agent.hooks = new HookManager(agent.config.hooks, agent.config.plugins);
  }

  // Memory
  if (isFeatureEnabled(agent.config.memory)) {
    agent.memory = new MemoryManager(agent.config.memory);
  }

  // Planning & Reflection
  if (isFeatureEnabled(agent.config.planning) && isFeatureEnabled(agent.config.reflection)) {
    agent.planning = new PlanningManager(agent.config.planning, agent.config.reflection);
  }

  // Observability
  if (isFeatureEnabled(agent.config.observability)) {
    agent.observability = new ObservabilityManager(agent.config.observability);

    // Lesson 26: Full trace capture
    const traceCaptureConfig = agent.config.observability.traceCapture;
    if (traceCaptureConfig?.enabled) {
      agent.traceCollector = createTraceCollector({
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
  if (isFeatureEnabled(agent.config.sandbox) || isFeatureEnabled(agent.config.humanInLoop)) {
    agent.safety = new SafetyManager(
      isFeatureEnabled(agent.config.sandbox) ? agent.config.sandbox : false,
      isFeatureEnabled(agent.config.humanInLoop) ? agent.config.humanInLoop : false,
      isFeatureEnabled(agent.config.policyEngine) ? agent.config.policyEngine : false,
    );
  }

  if (isFeatureEnabled(agent.config.policyEngine)) {
    const rootPolicy = resolvePolicyProfile({
      policyEngine: agent.config.policyEngine,
      sandboxConfig: isFeatureEnabled(agent.config.sandbox) ? agent.config.sandbox : undefined,
    });
    agent.emit({
      type: 'policy.profile.resolved',
      profile: rootPolicy.profileName,
      context: 'root',
      selectionSource: rootPolicy.metadata.selectionSource,
      usedLegacyMappings: rootPolicy.metadata.usedLegacyMappings,
      legacySources: rootPolicy.metadata.legacyMappingSources,
    });
    if (rootPolicy.metadata.usedLegacyMappings) {
      agent.emit({
        type: 'policy.legacy.fallback.used',
        profile: rootPolicy.profileName,
        sources: rootPolicy.metadata.legacyMappingSources,
        warnings: rootPolicy.metadata.warnings,
      });
    }
  }

  // Routing
  if (isFeatureEnabled(agent.config.routing)) {
    agent.routing = new RoutingManager(agent.config.routing);
  }

  // Multi-Agent (Lesson 17)
  if (isFeatureEnabled(agent.config.multiAgent)) {
    const roles = (agent.config.multiAgent.roles || []).map((r: AgentRoleConfig) => ({
      name: r.name,
      description: r.description,
      systemPrompt: r.systemPrompt,
      capabilities: r.capabilities,
      authority: r.authority,
      model: r.model,
    }));
    agent.multiAgent = new MultiAgentManager(
      agent.provider,
      Array.from(agent.tools.values()),
      roles,
    );
  }

  // ReAct (Lesson 18)
  if (isFeatureEnabled(agent.config.react)) {
    agent.react = new ReActManager(agent.provider, Array.from(agent.tools.values()), {
      maxSteps: agent.config.react.maxSteps,
      stopOnAnswer: agent.config.react.stopOnAnswer,
      includeReasoning: agent.config.react.includeReasoning,
    });
  }

  // Execution Policies (Lesson 23)
  if (isFeatureEnabled(agent.config.executionPolicy)) {
    agent.executionPolicy = new ExecutionPolicyManager({
      defaultPolicy: agent.config.executionPolicy.defaultPolicy,
      toolPolicies: agent.config.executionPolicy.toolPolicies as Record<
        string,
        {
          policy: 'allow' | 'prompt' | 'forbidden';
          conditions?: {
            argMatch?: Record<string, string | RegExp>;
            policy: 'allow' | 'prompt' | 'forbidden';
            reason?: string;
          }[];
          reason?: string;
        }
      >,
      intentAware: agent.config.executionPolicy.intentAware,
      intentConfidenceThreshold: agent.config.executionPolicy.intentConfidenceThreshold,
    });
  }

  // Thread Management (Lesson 24)
  if (isFeatureEnabled(agent.config.threads)) {
    agent.threadManager = new ThreadManager();
  }

  // Rules System (Lesson 12)
  if (isFeatureEnabled(agent.config.rules)) {
    const ruleSources = agent.config.rules.sources || DEFAULT_RULE_SOURCES;
    agent.rules = new RulesManager({
      enabled: true,
      sources: ruleSources,
      watch: agent.config.rules.watch,
    });
    // Load rules asynchronously - tracked for ensureReady()
    agent.initPromises.push(
      agent.rules.loadRules().catch((err) => {
        log.warn('Failed to load rules', { error: String(err) });
      }),
    );
  }

  // Economics System (Token Budget) - always enabled
  // Use custom budget if provided (subagents use SUBAGENT_BUDGET), otherwise STANDARD_BUDGET
  const baseBudget = agent.config.budget ?? STANDARD_BUDGET;
  agent.economics = new ExecutionEconomicsManager(
    {
      ...baseBudget,
      // Use maxIterations from config as absolute safety cap
      maxIterations: agent.config.maxIterations,
      targetIterations: Math.min(baseBudget.targetIterations ?? 20, agent.config.maxIterations),
    },
    agent._sharedEconomicsState ?? undefined,
    agent.agentId,
  );

  // Enable incremental token accounting for the root agent.
  // Estimate baseline from system prompt size (~4 chars/token).
  // This activates incremental mode in recordLLMUsage() so only marginal
  // tokens per call are counted toward the budget, preventing quadratic growth.
  const systemPromptLength = agent.config.systemPrompt?.length ?? 0;
  const estimatedBaselineTokens = Math.ceil(systemPromptLength / 4);
  if (estimatedBaselineTokens > 0) {
    agent.economics.setBaseline(estimatedBaselineTokens);
  }

  // Phase 2.2: Agent State Machine - formalizes phase tracking
  // Always enabled - provides structured phase transitions with metrics
  agent.stateMachine = createAgentStateMachine();
  // Forward state machine phase transitions as subagent.phase events
  const phaseMap: Record<string, 'exploring' | 'planning' | 'executing' | 'completing'> = {
    exploring: 'exploring',
    planning: 'planning',
    acting: 'executing',
    verifying: 'completing',
  };
  const unsubStateMachine = agent.stateMachine.subscribe((event) => {
    if (event.type === 'phase.changed') {
      agent.emit({
        type: 'subagent.phase',
        agentId: agent.agentId,
        phase: phaseMap[event.transition.to] ?? 'exploring',
      });
    }
  });
  agent.unsubscribers.push(unsubStateMachine);

  // Work Log - compaction-resilient summary of agent work
  // Always enabled - minimal overhead and critical for long-running tasks
  agent.workLog = createWorkLog();

  // Verification Gate - opt-in completion verification
  if (agent.config.verificationCriteria) {
    agent.verificationGate = createVerificationGate(agent.config.verificationCriteria);
  }

  // TypeScript compilation checking — auto-detect and enable
  {
    const cwd = agent.config.workingDirectory || process.cwd();
    const tcState = createTypeCheckerState(cwd);
    agent.typeCheckerState = tcState;

    if (tcState.tsconfigDir && !agent.verificationGate) {
      agent.verificationGate = createVerificationGate({
        requireCompilation: true,
        compilationMaxAttempts: 8,
      });
    }
  }

  // Phase 2-4: Orchestration & Advanced modules (always enabled, lightweight)
  agent.injectionBudget = createInjectionBudgetManager();
  agent.selfImprovement = createSelfImprovementProtocol(
    undefined,
    agent.learningStore ?? undefined,
  );
  agent.subagentOutputStore = createSubagentOutputStore({ persistToFile: false });
  agent.autoCheckpointManager = createAutoCheckpointManager({ enabled: true });
  agent.toolRecommendation = createToolRecommendationEngine();

  // Agent Registry - always enabled for subagent support
  agent.agentRegistry = new AgentRegistry();
  // Load user agents asynchronously - tracked for ensureReady()
  agent.initPromises.push(
    agent.agentRegistry.loadUserAgents().catch((err) => {
      log.warn('Failed to load user agents', { error: String(err) });
    }),
  );

  // Register spawn_agent tool so LLM can delegate to subagents
  const boundSpawnTool = createBoundSpawnAgentTool((name, task, constraints) =>
    agent.spawnAgent(name, task, constraints),
  );
  agent.tools.set(boundSpawnTool.name, boundSpawnTool);

  // Register spawn_agents_parallel tool for parallel subagent execution
  const boundParallelSpawnTool = createBoundSpawnAgentsParallelTool((tasks) =>
    agent.spawnAgentsParallel(tasks),
  );
  agent.tools.set(boundParallelSpawnTool.name, boundParallelSpawnTool);

  // Task Manager - Claude Code-style task system for coordination
  agent.taskManager = createTaskManager();
  // Forward task events (with cleanup tracking for EventEmitter-based managers)
  const taskCreatedHandler = (data: { task: any }) => {
    agent.emit({ type: 'task.created', task: data.task });
  };
  agent.taskManager.on('task.created', taskCreatedHandler);
  agent.unsubscribers.push(() => agent.taskManager?.off('task.created', taskCreatedHandler));

  const taskUpdatedHandler = (data: { task: any }) => {
    agent.emit({ type: 'task.updated', task: data.task });
  };
  agent.taskManager.on('task.updated', taskUpdatedHandler);
  agent.unsubscribers.push(() => agent.taskManager?.off('task.updated', taskUpdatedHandler));
  // Register task tools
  const taskTools = createTaskTools(agent.taskManager);
  for (const tool of taskTools) {
    agent.tools.set(tool.name, tool);
  }

  // Built-in web search (Serper API) — gracefully handles missing API key
  const serperCustomTool = createSerperSearchTool();
  agent.tools.set('web_search', {
    name: serperCustomTool.name,
    description: serperCustomTool.description,
    parameters: serperCustomTool.inputSchema,
    execute: serperCustomTool.execute,
    dangerLevel: 'safe',
  });

  // Swarm Mode (experimental)
  if (agent.config.swarm) {
    const swarmConfig = agent.config.swarm as SwarmConfig;

    // Wrap provider with request throttle to prevent 429 rate limiting.
    // All subagents share agent.provider by reference (line 4398),
    // so wrapping here throttles ALL downstream LLM calls.
    if (swarmConfig.throttle !== false) {
      const throttleConfig =
        swarmConfig.throttle === 'paid'
          ? PAID_TIER_THROTTLE
          : swarmConfig.throttle === 'free' || swarmConfig.throttle === undefined
            ? FREE_TIER_THROTTLE
            : swarmConfig.throttle;
      agent.provider = createThrottledProvider(
        agent.provider as unknown as import('../providers/types.js').LLMProvider,
        throttleConfig,
      ) as any;
    }

    // Pass codebaseContext so the decomposer can ground tasks in actual project files
    swarmConfig.codebaseContext = agent.codebaseContext ?? undefined;

    agent.swarmOrchestrator = createSwarmOrchestrator(
      swarmConfig,
      agent.provider as unknown as import('../providers/types.js').LLMProvider,
      agent.agentRegistry,
      (name, task) => agent.spawnAgent(name, task),
      agent.blackboard ?? undefined,
    );

    // Override parent budget pool with swarm's much larger pool so spawnAgent()
    // allocates from the swarm budget (e.g. 10M tokens) instead of the parent's
    // generic pool (200K tokens). Without this, workers get 5K emergency budget.
    agent.budgetPool = agent.swarmOrchestrator.getBudgetPool().pool;

    // Phase 3.1+3.2: Set shared state so workers inherit it via buildContext()
    agent._sharedContextState = agent.swarmOrchestrator.getSharedContextState();
    agent._sharedEconomicsState = agent.swarmOrchestrator.getSharedEconomicsState();
  }

  // Cancellation Support
  if (isFeatureEnabled(agent.config.cancellation)) {
    agent.cancellation = createCancellationManager();
    // Forward cancellation events (with cleanup tracking)
    const unsubCancellation = agent.cancellation.subscribe((event) => {
      if (event.type === 'cancellation.requested') {
        agent.emit({ type: 'cancellation.requested', reason: event.reason });
      }
    });
    agent.unsubscribers.push(unsubCancellation);
  }

  // Resource Monitoring
  if (isFeatureEnabled(agent.config.resources)) {
    agent.resourceManager = createResourceManager({
      enabled: agent.config.resources.enabled,
      maxMemoryMB: agent.config.resources.maxMemoryMB,
      maxCpuTimeSec: agent.config.resources.maxCpuTimeSec,
      maxConcurrentOps: agent.config.resources.maxConcurrentOps,
      warnThreshold: agent.config.resources.warnThreshold,
      criticalThreshold: agent.config.resources.criticalThreshold,
    });
  }

  // LSP (Language Server Protocol) Support
  if (isFeatureEnabled(agent.config.lsp)) {
    agent.lspManager = createLSPManager({
      enabled: agent.config.lsp.enabled,
      autoDetect: agent.config.lsp.autoDetect,
      servers: agent.config.lsp.servers,
      timeout: agent.config.lsp.timeout,
    });
    // Auto-start is done lazily on first use to avoid startup delays
  }

  // Semantic Cache Support
  if (isFeatureEnabled(agent.config.semanticCache)) {
    agent.semanticCache = createSemanticCacheManager({
      enabled: agent.config.semanticCache.enabled,
      threshold: agent.config.semanticCache.threshold,
      maxSize: agent.config.semanticCache.maxSize,
      ttl: agent.config.semanticCache.ttl,
    });
    // Forward cache events (with cleanup tracking)
    const unsubSemanticCache = agent.semanticCache.subscribe((event) => {
      if (event.type === 'cache.hit') {
        agent.emit({ type: 'cache.hit', query: event.query, similarity: event.similarity });
      } else if (event.type === 'cache.miss') {
        agent.emit({ type: 'cache.miss', query: event.query });
      } else if (event.type === 'cache.set') {
        agent.emit({ type: 'cache.set', query: event.query });
      }
    });
    agent.unsubscribers.push(unsubSemanticCache);
  }

  // Skills Support
  if (isFeatureEnabled(agent.config.skills)) {
    agent.skillManager = createSkillManager({
      enabled: agent.config.skills.enabled,
      directories: agent.config.skills.directories,
      loadBuiltIn: agent.config.skills.loadBuiltIn,
      autoActivate: agent.config.skills.autoActivate,
    });
    // Load skills asynchronously - tracked for ensureReady()
    agent.initPromises.push(
      agent.skillManager
        .loadSkills()
        .then(() => {}) // Convert to void
        .catch((err) => {
          log.warn('Failed to load skills', { error: String(err) });
        }),
    );
  }

  // Context Engineering (Manus-inspired tricks P, Q, R, S, T)
  // Always enabled - these are performance optimizations
  agent.contextEngineering = createContextEngineering({
    enableCacheOptimization: true,
    enableRecitation: true,
    enableReversibleCompaction: true,
    enableFailureTracking: true,
    enableDiversity: false, // Off by default - can cause unexpected behavior
    staticPrefix: agent.config.systemPrompt,
    recitationFrequency: 5,
    maxFailures: 30,
    maxReferences: 50,
  });

  // Bind shared context state for cross-worker failure learning (swarm workers only)
  if (agent._sharedContextState) {
    agent.contextEngineering.setSharedState(agent._sharedContextState);
  }

  // Codebase Context - intelligent code selection for context management
  // Analyzes repo structure and selects relevant code within token budgets
  if (agent.config.codebaseContext !== false) {
    const codebaseConfig =
      typeof agent.config.codebaseContext === 'object' ? agent.config.codebaseContext : {};
    agent.codebaseContext = createCodebaseContext({
      root: codebaseConfig.root ?? process.cwd(),
      includePatterns: codebaseConfig.includePatterns,
      excludePatterns: codebaseConfig.excludePatterns,
      maxFileSize: codebaseConfig.maxFileSize ?? 100 * 1024, // 100KB
      tokensPerChar: 0.25,
      analyzeDependencies: true,
      cacheResults: true,
      cacheTTL: 5 * 60 * 1000, // 5 minutes
    });

    // Forward trace collector so codebase analysis can emit codebase.map entries.
    if (agent.traceCollector) {
      agent.codebaseContext.traceCollector = agent.traceCollector;
    }

    // Connect LSP manager to codebase context for enhanced code selection
    // This enables LSP-based relevance boosting (Phase 4.1)
    if (agent.lspManager) {
      agent.codebaseContext.setLSPManager(agent.lspManager);
    }
  }

  // Forward context engineering events (with cleanup tracking)
  const unsubContextEngineering = agent.contextEngineering.on((event) => {
    switch (event.type) {
      case 'failure.recorded':
        agent.observability?.logger?.warn('Failure recorded', {
          action: event.failure.action,
          category: event.failure.category,
        });
        break;
      case 'failure.pattern':
        agent.observability?.logger?.warn('Failure pattern detected', {
          type: event.pattern.type,
          description: event.pattern.description,
        });
        agent.emit({ type: 'error', error: `Pattern: ${event.pattern.description}` });
        break;
      case 'recitation.injected':
        agent.observability?.logger?.debug('Recitation injected', {
          iteration: event.iteration,
        });
        break;
    }
  });
  agent.unsubscribers.push(unsubContextEngineering);

  // Interactive Planning (conversational + editable planning)
  if (isFeatureEnabled(agent.config.interactivePlanning)) {
    const interactiveConfig =
      typeof agent.config.interactivePlanning === 'object' ? agent.config.interactivePlanning : {};

    agent.interactivePlanner = createInteractivePlanner({
      autoCheckpoint: interactiveConfig.enableCheckpoints ?? true,
      confirmBeforeExecute: interactiveConfig.requireApproval ?? true,
      maxCheckpoints: 20,
      autoPauseAtDecisions: true,
    });

    // Forward planner events to observability (with cleanup tracking)
    const unsubInteractivePlanner = agent.interactivePlanner.on((event) => {
      switch (event.type) {
        case 'plan.created':
          agent.observability?.logger?.info('Interactive plan created', {
            planId: event.plan.id,
            stepCount: event.plan.steps.length,
          });
          break;
        case 'step.completed':
          agent.observability?.logger?.debug('Plan step completed', {
            stepId: event.step.id,
            status: event.step.status,
          });
          break;
        case 'plan.cancelled':
          agent.observability?.logger?.info('Plan cancelled', { reason: event.reason });
          break;
        case 'checkpoint.created':
          agent.observability?.logger?.debug('Plan checkpoint created', {
            checkpointId: event.checkpoint.id,
          });
          break;
      }
    });
    agent.unsubscribers.push(unsubInteractivePlanner);
  }

  // Recursive Context (RLM - Recursive Language Models)
  // Enables on-demand context exploration for large codebases
  if (isFeatureEnabled(agent.config.recursiveContext)) {
    const recursiveConfig =
      typeof agent.config.recursiveContext === 'object' ? agent.config.recursiveContext : {};

    agent.recursiveContext = createRecursiveContext({
      maxDepth: recursiveConfig.maxRecursionDepth ?? 5,
      snippetTokens: recursiveConfig.maxSnippetTokens ?? 2000,
      synthesisTokens: 1000,
      totalBudget: 50000,
      cacheResults: recursiveConfig.cacheNavigationResults ?? true,
    });

    // Note: File system source should be registered when needed with proper glob/readFile functions
    // This is deferred to allow flexible configuration

    // Forward RLM events (with cleanup tracking)
    const unsubRecursiveContext = agent.recursiveContext.on((event) => {
      switch (event.type) {
        case 'process.started':
          agent.observability?.logger?.debug('RLM process started', {
            query: event.query,
            depth: event.depth,
          });
          break;
        case 'navigation.command':
          agent.observability?.logger?.debug('RLM navigation command', {
            command: event.command,
            depth: event.depth,
          });
          break;
        case 'process.completed':
          agent.observability?.logger?.debug('RLM process completed', {
            stats: event.stats,
          });
          break;
        case 'budget.warning':
          agent.observability?.logger?.warn('RLM budget warning', {
            remaining: event.remaining,
            total: event.total,
          });
          break;
      }
    });
    agent.unsubscribers.push(unsubRecursiveContext);
  }

  // Learning Store (cross-session learning from failures)
  // Connects to the failure tracker in contextEngineering for automatic learning extraction
  if (isFeatureEnabled(agent.config.learningStore)) {
    const learningConfig =
      typeof agent.config.learningStore === 'object' ? agent.config.learningStore : {};

    agent.learningStore = createLearningStore({
      dbPath: learningConfig.dbPath ?? '.agent/learnings.db',
      requireValidation: learningConfig.requireValidation ?? true,
      autoValidateThreshold: learningConfig.autoValidateThreshold ?? 0.9,
      maxLearnings: learningConfig.maxLearnings ?? 500,
    });

    // Connect to the failure tracker if available
    if (agent.contextEngineering) {
      const failureTracker = agent.contextEngineering.getFailureTracker();
      if (failureTracker) {
        agent.learningStore.connectFailureTracker(failureTracker);
      }
    }

    // Forward learning events to observability (with cleanup tracking)
    const unsubLearningStore = agent.learningStore.on((event) => {
      switch (event.type) {
        case 'learning.proposed':
          agent.observability?.logger?.info('Learning proposed', {
            learningId: event.learning.id,
            description: event.learning.description,
          });
          agent.emit({
            type: 'learning.proposed',
            learningId: event.learning.id,
            description: event.learning.description,
          });
          break;
        case 'learning.validated':
          agent.observability?.logger?.info('Learning validated', {
            learningId: event.learningId,
          });
          agent.emit({ type: 'learning.validated', learningId: event.learningId });
          break;
        case 'learning.applied':
          agent.observability?.logger?.debug('Learning applied', {
            learningId: event.learningId,
            context: event.context,
          });
          agent.emit({
            type: 'learning.applied',
            learningId: event.learningId,
            context: event.context,
          });
          break;
        case 'pattern.extracted':
          agent.observability?.logger?.info('Pattern extracted as learning', {
            pattern: event.pattern.description,
            learningId: event.learning.id,
          });
          break;
      }
    });
    agent.unsubscribers.push(unsubLearningStore);
  }

  // Auto-Compaction Manager (sophisticated context compaction)
  // Uses the Compactor for LLM-based summarization with threshold monitoring
  if (isFeatureEnabled(agent.config.compaction)) {
    const compactionConfig =
      typeof agent.config.compaction === 'object' ? agent.config.compaction : {};

    // Create the compactor (requires provider for LLM summarization)
    agent.compactor = createCompactor(agent.provider, {
      enabled: true,
      tokenThreshold: compactionConfig.tokenThreshold ?? 80000,
      preserveRecentCount: compactionConfig.preserveRecentCount ?? 10,
      preserveToolResults: compactionConfig.preserveToolResults ?? true,
      summaryMaxTokens: compactionConfig.summaryMaxTokens ?? 2000,
      summaryModel: compactionConfig.summaryModel,
    });

    // Create the auto-compaction manager with threshold monitoring
    // Wire reversible compaction through contextEngineering when available
    const compactHandler = agent.contextEngineering
      ? async (messages: Message[]) => {
          // Use contextEngineering's reversible compaction to preserve references
          const summarize = async (msgs: Message[]) => {
            // Use the basic compactor's summarization capability
            const result = await agent.compactor!.compact(msgs);
            return result.summary;
          };
          const contextMsgs = messages.map((m) => ({
            role: m.role as 'system' | 'user' | 'assistant' | 'tool',
            content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
          }));
          const result = await agent.contextEngineering!.compact(contextMsgs, summarize);
          const tokensBefore = agent.compactor!.estimateTokens(messages);
          const tokensAfter = agent.compactor!.estimateTokens([
            { role: 'assistant', content: result.summary },
          ]);
          return {
            summary:
              result.summary +
              (result.reconstructionPrompt ? `\n\n${result.reconstructionPrompt}` : ''),
            tokensBefore,
            tokensAfter,
            preservedMessages: [{ role: 'assistant' as const, content: result.summary }],
            references: result.references,
          };
        }
      : undefined;

    // Get model's actual context window - try OpenRouter first (real API data),
    // then fall back to hardcoded ModelRegistry, then config, then default
    const openRouterContext = getModelContextLength(agent.config.model || '');
    const registryInfo = modelRegistry.getModel(agent.config.model || '');
    const registryContext = registryInfo?.capabilities?.maxContextTokens;
    const maxContextTokens =
      agent.config.maxContextTokens ??
      openRouterContext ?? // From OpenRouter API (e.g., GLM-4.7 = 202752)
      registryContext ?? // From hardcoded registry (Claude, GPT-4o, etc.)
      200000; // Fallback to 200K

    agent.autoCompactionManager = createAutoCompactionManager(agent.compactor, {
      mode: compactionConfig.mode ?? 'auto',
      warningThreshold: 0.7, // Warn at 70% of model's context
      autoCompactThreshold: 0.8, // Compact at 80% (changed from 0.90)
      hardLimitThreshold: 0.95, // Hard limit at 95%
      preserveRecentUserMessages: Math.ceil((compactionConfig.preserveRecentCount ?? 10) / 2),
      preserveRecentAssistantMessages: Math.ceil((compactionConfig.preserveRecentCount ?? 10) / 2),
      cooldownMs: 60000, // 1 minute cooldown
      maxContextTokens, // Dynamic from model registry or config
      compactHandler, // Use reversible compaction when contextEngineering is available
    });

    // Forward compactor events to observability (with cleanup tracking)
    const unsubCompactor = agent.compactor.on((event) => {
      switch (event.type) {
        case 'compaction.start':
          agent.observability?.logger?.info('Compaction started', {
            messageCount: event.messageCount,
          });
          break;
        case 'compaction.complete':
          agent.observability?.logger?.info('Compaction complete', {
            tokensBefore: event.result.tokensBefore,
            tokensAfter: event.result.tokensAfter,
            compactedCount: event.result.compactedCount,
          });
          break;
        case 'compaction.error':
          agent.observability?.logger?.error('Compaction error', {
            error: event.error,
          });
          break;
      }
    });
    agent.unsubscribers.push(unsubCompactor);

    // Forward auto-compaction events (with cleanup tracking)
    const unsubAutoCompaction = agent.autoCompactionManager.on((event: AutoCompactionEvent) => {
      switch (event.type) {
        case 'autocompaction.warning':
          agent.observability?.logger?.warn('Context approaching limit', {
            currentTokens: event.currentTokens,
            ratio: event.ratio,
          });
          agent.emit({
            type: 'compaction.warning',
            currentTokens: event.currentTokens,
            threshold: Math.round(event.ratio * (agent.config.maxContextTokens ?? 200000)),
          });
          break;
        case 'autocompaction.triggered':
          agent.observability?.logger?.info('Auto-compaction triggered', {
            mode: event.mode,
            currentTokens: event.currentTokens,
          });
          break;
        case 'autocompaction.completed':
          agent.observability?.logger?.info('Auto-compaction completed', {
            tokensBefore: event.tokensBefore,
            tokensAfter: event.tokensAfter,
            reduction: event.reduction,
          });
          agent.emit({
            type: 'compaction.auto',
            tokensBefore: event.tokensBefore,
            tokensAfter: event.tokensAfter,
            messagesCompacted: event.tokensBefore - event.tokensAfter,
          });
          break;
        case 'autocompaction.hard_limit':
          agent.observability?.logger?.error('Context hard limit reached', {
            currentTokens: event.currentTokens,
            ratio: event.ratio,
          });
          break;
        case 'autocompaction.emergency_truncate':
          agent.observability?.logger?.warn('Emergency truncation performed', {
            reason: event.reason,
            messagesBefore: event.messagesBefore,
            messagesAfter: event.messagesAfter,
          });
          break;
      }
    });
    agent.unsubscribers.push(unsubAutoCompaction);
  }

  // Note: FileChangeTracker requires a database instance which is not
  // available at this point. Use initFileChangeTracker() to enable it
  // after the agent is constructed with a database reference.
  // This allows the feature to be optional and not require SQLite at all times.
}
