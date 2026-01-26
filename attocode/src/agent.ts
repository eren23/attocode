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
  createAgentRegistry,
  filterToolsForAgent,
  formatAgentList,
  CancellationManager,
  createCancellationManager,
  isCancellationError,
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
  type CancellationTokenType,
  type Skill,
  type ContextEngineeringConfig,
  type CodebaseContextConfig,
  type SelectionOptions,
} from './integrations/index.js';

// Lesson 26: Tracing & Evaluation integration
import { TraceCollector, createTraceCollector } from './tracing/trace-collector.js';

// Spawn agent tool for LLM-driven subagent delegation
import { createBoundSpawnAgentTool } from './tools/agent.js';

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
  private toolResolver: ((toolName: string) => ToolDefinition | null) | null = null;

  // Initialization tracking
  private initPromises: Promise<void>[] = [];
  private initComplete = false;

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
    this.economics = new ExecutionEconomicsManager({
      ...STANDARD_BUDGET,
      // Use maxIterations from config as absolute safety cap
      maxIterations: this.config.maxIterations,
      targetIterations: Math.min(20, this.config.maxIterations),
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
      (name, task) => this.spawnAgent(name, task)
    );
    this.tools.set(boundSpawnTool.name, boundSpawnTool);

    // Cancellation Support
    if (isFeatureEnabled(this.config.cancellation)) {
      this.cancellation = createCancellationManager();
      // Forward cancellation events
      this.cancellation.subscribe(event => {
        if (event.type === 'cancellation.requested') {
          this.emit({ type: 'cancellation.requested', reason: event.reason });
        }
      });
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
      // Forward cache events
      this.semanticCache.subscribe(event => {
        if (event.type === 'cache.hit') {
          this.emit({ type: 'cache.hit', query: event.query, similarity: event.similarity });
        } else if (event.type === 'cache.miss') {
          this.emit({ type: 'cache.miss', query: event.query });
        } else if (event.type === 'cache.set') {
          this.emit({ type: 'cache.set', query: event.query });
        }
      });
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
    }

    // Forward context engineering events
    this.contextEngineering.on(event => {
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

    // Lesson 26: Start trace capture session
    const traceSessionId = `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    await this.traceCollector?.startSession(traceSessionId, task, this.config.model || 'default', {});

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

      // Lesson 26: End trace capture session
      await this.traceCollector?.endSession({ success: true, output: response });

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

        // Lesson 26: End trace capture session on cancellation
        await this.traceCollector?.endSession({ success: false, failureReason: `Cancelled: ${error.message}` });

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

      this.emit({ type: 'error', error: error.message });
      this.observability?.logger?.error('Agent failed', { error: error.message });

      // Lesson 26: End trace capture session on error
      await this.traceCollector?.endSession({ success: false, failureReason: error.message });

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

      // Check iteration limit
      if (this.state.iteration >= this.config.maxIterations) {
        this.observability?.logger?.warn('Max iterations reached');
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

    // Outer loop for reflection (if enabled)
    while (reflectionAttempt < maxReflectionAttempts) {
      reflectionAttempt++;

      // Agent loop - now uses economics-based budget checking
      while (true) {
        this.state.iteration++;

        // =======================================================================
        // CANCELLATION CHECK
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
        // =======================================================================
        if (this.economics) {
          const budgetCheck = this.economics.checkBudget();

          if (!budgetCheck.canContinue) {
            // Hard limit reached
            this.observability?.logger?.warn('Budget limit reached', {
              reason: budgetCheck.reason,
              budgetType: budgetCheck.budgetType,
            });

            // Emit appropriate event
            if (budgetCheck.budgetType === 'iterations') {
              this.emit({ type: 'error', error: `Max iterations reached (${this.state.iteration})` });
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
          if (this.state.iteration >= this.config.maxIterations) {
            this.observability?.logger?.warn('Max iterations reached');
            break;
          }
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

        // Make LLM call
        const response = await this.callLLM(messages);

        // Record LLM usage for economics
        if (this.economics && response.usage) {
          this.economics.recordLLMUsage(
            response.usage.inputTokens,
            response.usage.outputTokens,
            this.config.model,
            response.usage.cost  // Use actual cost from provider when available
          );
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

        // Check for tool calls
        if (!response.toolCalls || response.toolCalls.length === 0) {
          // No tool calls, agent is done - compact tool outputs to save context
          // The model has "consumed" the tool outputs and produced a response,
          // so we can replace verbose outputs with compact summaries
          this.compactToolOutputs();
          break;
        }

        // Execute tool calls
        const toolResults = await this.executeToolCalls(response.toolCalls);

        // Record tool calls for economics/progress tracking
        for (let i = 0; i < response.toolCalls.length; i++) {
          const toolCall = response.toolCalls[i];
          const result = toolResults[i];
          this.economics?.recordToolCall(toolCall.name, toolCall.arguments, result?.result);
        }

        // Add tool results to messages (with truncation and proactive budget management)
        const MAX_TOOL_OUTPUT_CHARS = 8000; // ~2000 tokens max per tool output

        // =======================================================================
        // PROACTIVE BUDGET CHECK - compact BEFORE we overflow, not after
        // =======================================================================
        if (this.economics) {
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

        for (const result of toolResults) {
          let content = typeof result.result === 'string' ? result.result : stableStringify(result.result);

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
          };
          messages.push(toolMessage);
          this.state.messages.push(toolMessage);
        }
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

    // Combine memory and codebase context
    const combinedContext = [
      ...(memoryContext.length > 0 ? memoryContext : []),
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
    const maxTokens = this.config.maxTokens || 128000;
    this.emit({
      type: 'insight.context',
      currentTokens: estimatedTokens,
      maxTokens,
      messageCount: messages.length,
      percentUsed: Math.round((estimatedTokens / maxTokens) * 100),
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
        // EXECUTION POLICY ENFORCEMENT (Lesson 23)
        // =====================================================================
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

          // Handle forbidden policy - always block
          if (evaluation.policy === 'forbidden') {
            throw new Error(`Forbidden by policy: ${evaluation.reason}`);
          }

          // Handle prompt policy - requires approval
          if (evaluation.policy === 'prompt' && evaluation.requiresApproval) {
            // Try to get approval through safety manager's human-in-loop
            if (this.safety?.humanInLoop) {
              const approval = await this.safety.humanInLoop.requestApproval(
                toolCall,
                `Policy requires approval: ${evaluation.reason}`
              );

              if (!approval.approved) {
                throw new Error(`Denied by user: ${approval.reason || 'No reason provided'}`);
              }

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
          const validation = await this.safety.validateAndApprove(
            toolCall,
            `Executing tool: ${toolCall.name}`
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

        // Execute tool (with sandbox if available)
        let result: unknown;
        if (this.safety?.sandbox) {
          result = await this.safety.sandbox.executeWithLimits(
            () => tool.execute(toolCall.arguments)
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
   * Select relevant code synchronously using cached repo analysis.
   * Returns empty result if analysis hasn't been run yet.
   */
  private selectRelevantCodeSync(task: string, maxTokens: number): {
    chunks: Array<{ filePath: string; content: string; tokenCount: number; importance: number }>;
    totalTokens: number;
  } {
    if (!this.codebaseContext) {
      return { chunks: [], totalTokens: 0 };
    }

    const repoMap = this.codebaseContext.getRepoMap();
    if (!repoMap) {
      return { chunks: [], totalTokens: 0 };
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
      const combinedScore = chunk.importance * 0.4 + Math.min(relevance, 1) * 0.6;

      return { chunk, score: combinedScore };
    });

    // Sort by score and select within budget
    scored.sort((a, b) => b.score - a.score);

    const selected: Array<{ filePath: string; content: string; tokenCount: number; importance: number }> = [];
    let totalTokens = 0;

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
    }

    return { chunks: selected, totalTokens };
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
      return this.observability.metrics.getMetrics();
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
   * Get the trace collector (Lesson 26).
   * Returns null if trace capture is not enabled.
   */
  getTraceCollector(): TraceCollector | null {
    return this.traceCollector;
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
    let compactedCount = 0;
    let savedChars = 0;

    for (const msg of this.state.messages) {
      if (msg.role === 'tool' && msg.content && msg.content.length > COMPACT_PREVIEW_LENGTH * 2) {
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

    // Set up event forwarding
    this.multiAgent.on(event => {
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

    const result = await this.multiAgent.runWithTeam(task, {
      roles,
      consensusStrategy: this.config.multiAgent && isFeatureEnabled(this.config.multiAgent)
        ? this.config.multiAgent.consensusStrategy || 'voting'
        : 'voting',
      communicationMode: 'broadcast',
    });

    return result;
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

    // Set up event forwarding
    this.react.on(event => {
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

    const trace = await this.react.run(task);

    // Store trace in memory if available
    if (this.memory && trace.finalAnswer) {
      this.memory.storeConversation([
        { role: 'user', content: task },
        { role: 'assistant', content: trace.finalAnswer },
      ]);
    }

    return trace;
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
   */
  async spawnAgent(agentName: string, task: string): Promise<SpawnResult> {
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

    this.emit({ type: 'agent.spawn', agentId: `spawn-${Date.now()}`, name: agentName, task });
    this.observability?.logger?.info('Spawning agent', { name: agentName, task });

    const startTime = Date.now();

    try {
      // Filter tools for this agent
      const agentTools = filterToolsForAgent(agentDef, Array.from(this.tools.values()));

      // Resolve model - abstract tiers (fast/balanced/quality) should use parent's model
      // Only use agentDef.model if it's an actual model ID (contains '/')
      const resolvedModel = (agentDef.model && agentDef.model.includes('/'))
        ? agentDef.model
        : this.config.model;

      // Create a sub-agent with the agent's config
      const subAgent = new ProductionAgent({
        provider: this.provider,
        tools: agentTools,
        systemPrompt: agentDef.systemPrompt,
        model: resolvedModel,
        maxIterations: agentDef.maxIterations || 30,
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
      });

      // Forward events from subagent
      subAgent.subscribe(event => {
        // Just forward the event as-is - the agent.spawn event already logged the agent name
        this.emit(event);
      });

      // Run the task
      const result = await subAgent.run(task);

      const duration = Date.now() - startTime;
      const spawnResult: SpawnResult = {
        success: result.success,
        output: result.response || result.error || '',
        metrics: {
          tokens: result.metrics.totalTokens,
          duration,
          toolCalls: result.metrics.toolCalls,
        },
      };

      this.emit({ type: 'agent.complete', agentId: agentName, success: result.success });

      await subAgent.cleanup();

      return spawnResult;
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'agent.error', agentId: agentName, error });

      return {
        success: false,
        output: `Agent error: ${error}`,
        metrics: { tokens: 0, duration: Date.now() - startTime, toolCalls: 0 },
      };
    }
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
        const confirmed = await confirmDelegate(topSuggestion.agent, topSuggestion.reason);
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

  // =========================================================================
  // SKILLS METHODS
  // =========================================================================

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
