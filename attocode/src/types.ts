/**
 * Lesson 25: Production Agent Types
 *
 * Unified configuration types for the production-ready agent
 * that integrates all lessons into one cohesive system.
 * Now includes multi-agent, ReAct, execution policies, and thread management.
 */

// =============================================================================
// CORE TYPES (from earlier lessons)
// =============================================================================

/**
 * Message in conversation.
 */
export interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  /** For tool role messages, references the tool call this responds to */
  toolCallId?: string;
  /** Optional message metadata (compaction hints, provenance, etc.) */
  metadata?: Record<string, unknown>;
}

/**
 * Tool call from LLM.
 */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  parseError?: string;
}

/**
 * Tool execution result.
 */
export interface ToolResult {
  callId: string;
  result: unknown;
  error?: string;
}

/**
 * Tool definition.
 */
export interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  execute: (args: Record<string, unknown>) => Promise<unknown>;
  dangerLevel?: 'safe' | 'moderate' | 'dangerous';
}

/**
 * Text content block with optional cache_control marker for prompt caching.
 */
export interface TextContentBlock {
  type: 'text';
  text: string;
  cache_control?: { type: 'ephemeral' };
}

/**
 * Image content block for vision support.
 */
export interface ImageContentBlock {
  type: 'image';
  source: {
    type: 'base64' | 'url';
    media_type: string;
    data: string;
  };
}

/**
 * Content block: text or image.
 */
export type ContentBlock = TextContentBlock | ImageContentBlock;

/**
 * Message that supports both string and structured content (for prompt caching).
 */
export interface MessageWithStructuredContent {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | ContentBlock[];
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  toolCallId?: string;
  metadata?: Record<string, unknown>;
}

/**
 * LLM provider interface.
 */
export interface LLMProvider {
  name?: string;
  chat(
    messages: (Message | MessageWithStructuredContent)[],
    options?: ChatOptions,
  ): Promise<ChatResponse>;
  stream?(messages: Message[], options?: ChatOptions): AsyncIterable<StreamChunk>;
}

export interface ChatOptions {
  model?: string;
  maxTokens?: number;
  temperature?: number;
  tools?: ToolDefinition[];
}

export interface ChatResponse {
  content: string;
  toolCalls?: ToolCall[];
  usage?: TokenUsage;
  model?: string;
  stopReason?: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence';
  /** Thinking/reasoning content from models that support extended thinking (e.g., Claude) */
  thinking?: string;
}

export interface StreamChunk {
  type: 'text' | 'tool_call' | 'done' | 'error';
  content?: string;
  toolCall?: ToolCall;
  error?: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  cost?: number;
}

// =============================================================================
// PRODUCTION AGENT CONFIG
// =============================================================================

/**
 * Main configuration for ProductionAgent.
 * All features are enabled by default.
 */
export interface ProductionAgentConfig {
  /** LLM provider (required) */
  provider: LLMProvider;

  /** Available tools (required) */
  tools: ToolDefinition[];

  /** System prompt */
  systemPrompt?: string;

  /** Model to use */
  model?: string;

  /** Maximum tokens for LLM responses */
  maxTokens?: number;

  /** Temperature for LLM responses */
  temperature?: number;

  /** Hook system configuration */
  hooks?: HooksConfig | false;

  /** Plugin system configuration */
  plugins?: PluginsConfig | false;

  /** Rules/instructions configuration */
  rules?: RulesConfig | false;

  /** Memory system configuration */
  memory?: MemoryConfig | false;

  /** Planning system configuration */
  planning?: PlanningConfig | false;

  /** Reflection/self-critique configuration */
  reflection?: ReflectionConfig | false;

  /** Observability configuration */
  observability?: ObservabilityConfig | false;

  /** Model routing configuration */
  routing?: RoutingConfig | false;

  /** Sandboxing configuration */
  sandbox?: SandboxConfig | false;

  /** Human-in-the-loop configuration */
  humanInLoop?: HumanInLoopConfig | false;

  /** Multi-agent configuration (from Lesson 17) */
  multiAgent?: MultiAgentConfig | false;

  /** ReAct pattern configuration (from Lesson 18) */
  react?: ReActPatternConfig | false;

  /** Execution policy configuration (from Lesson 23) */
  executionPolicy?: ExecutionPolicyConfig | false;

  /** Unified policy engine configuration */
  policyEngine?: PolicyEngineConfig | false;

  /** Thread management configuration (from Lesson 24) */
  threads?: ThreadsConfig | false;

  /** Cancellation support configuration */
  cancellation?: CancellationConfig | false;

  /** Resource monitoring configuration */
  resources?: ResourceConfig | false;

  /** LSP (Language Server Protocol) configuration */
  lsp?: LSPAgentConfig | false;

  /** Semantic cache configuration */
  semanticCache?: SemanticCacheAgentConfig | false;

  /** Skills system configuration */
  skills?: SkillsAgentConfig | false;

  /** Codebase context configuration (intelligent code selection) */
  codebaseContext?: CodebaseContextAgentConfig | false;

  /** Interactive planning configuration (conversational + editable planning) */
  interactivePlanning?: InteractivePlanningAgentConfig | false;

  /** Recursive context configuration (RLM - Recursive Language Models) */
  recursiveContext?: RecursiveContextAgentConfig | false;

  /** Compaction configuration (context management) */
  compaction?: CompactionAgentConfig | false;

  /** Learning store configuration (cross-session learning) */
  learningStore?: LearningStoreAgentConfig | false;

  /** LLM resilience configuration (empty response retry, continuation) */
  resilience?: LLMResilienceAgentConfig | false;

  /** File change tracker configuration (undo capability) */
  fileChangeTracker?: FileChangeTrackerAgentConfig | false;

  /** Subagent configuration (timeout and iteration limits) */
  subagent?: SubagentConfig | false;

  /** Swarm mode configuration (orchestrator + workers) */
  swarm?: import('./integrations/swarm/types.js').SwarmConfig | false;

  /** Provider-level resilience (circuit breaker, fallback chain) */
  providerResilience?: ProviderResilienceConfig | false;

  /**
   * Verification criteria for completion verification.
   * When set, the agent must satisfy these criteria before completing.
   * - TUI mode: off by default
   * - Eval mode: auto-configured from FAIL_TO_PASS tests
   */
  verificationCriteria?: {
    requiredTests?: string[];
    requireFileChanges?: boolean;
    maxAttempts?: number;
  };

  /**
   * Working directory for all tool operations.
   * When set, bash commands default to this cwd, and file operations
   * resolve relative paths against this directory.
   * Falls back to process.cwd() when not set.
   */
  workingDirectory?: string;

  /** Maximum context tokens before compaction */
  maxContextTokens?: number;

  /** Maximum iterations for agent loop */
  maxIterations?: number;

  /** Request timeout in ms */
  timeout?: number;

  /**
   * Callback to resolve unknown tools on-demand.
   * Called when a tool is not found in the registered tools.
   * Useful for lazy-loading MCP tools - the resolver can load the tool
   * and return its definition, which will then be registered and executed.
   */
  toolResolver?: (toolName: string) => ToolDefinition | null;

  /**
   * MCP tool summaries to include in system prompt.
   * These are lightweight descriptions that let the model know what MCP tools
   * are available without loading full schemas.
   */
  mcpToolSummaries?: Array<{ name: string; description: string }>;

  /**
   * Unique identifier for this agent instance.
   * Used for blackboard resource claims and tracing.
   * Parent agents get an auto-generated ID; subagents receive one from spawnAgent().
   * @internal Used for subagent coordination
   */
  agentId?: string;

  /**
   * Shared blackboard for subagent coordination.
   * When provided, the agent will use this blackboard for finding sharing
   * and resource claiming. Parent agents create their own; subagents inherit
   * from their parent.
   * @internal Used for subagent spawning
   */
  blackboard?: unknown; // SharedBlackboard - using unknown to avoid circular import

  /**
   * Shared file cache for cross-agent read deduplication.
   * Created by parent agent, inherited by subagents.
   * @internal Used for subagent spawning
   */
  fileCache?: unknown; // SharedFileCache - using unknown to avoid circular import

  /**
   * Custom budget configuration for the economics system.
   * Subagents should use SUBAGENT_BUDGET for constrained execution.
   * @internal Used for subagent spawning
   */
  budget?: {
    maxTokens?: number;
    softTokenLimit?: number;
    maxCost?: number;
    maxDuration?: number;
    softDurationLimit?: number;
    targetIterations?: number;
    maxIterations?: number;
  };

  /**
   * Shared context state for cross-worker failure learning and reference pooling.
   * Created by SwarmOrchestrator, inherited by workers.
   * @internal Used for swarm worker coordination
   */
  sharedContextState?: unknown; // SharedContextState — using unknown to avoid circular import

  /**
   * Shared economics state for cross-worker doom loop aggregation.
   * Created by SwarmOrchestrator, inherited by workers.
   * @internal Used for swarm worker coordination
   */
  sharedEconomicsState?: unknown; // SharedEconomicsState — using unknown to avoid circular import
}

// =============================================================================
// FEATURE CONFIGS
// =============================================================================

/**
 * Hooks configuration (Lesson 10).
 */
export interface HooksConfig {
  /** Enable/disable hooks */
  enabled?: boolean;

  /** Built-in hooks to enable */
  builtIn?: {
    logging?: boolean;
    metrics?: boolean;
    timing?: boolean;
  };

  /** Custom hooks */
  custom?: Hook[];

  /** Optional shell hook runner configuration */
  shell?: HookShellConfig;
}

export interface Hook {
  /** Optional unique identifier for duplicate detection */
  id?: string;
  event: HookEvent;
  handler: (data: unknown) => void | Promise<void>;
  priority?: number;
}

export interface HookShellConfig {
  /** Enable shell hooks */
  enabled?: boolean;

  /** Default timeout for shell hooks in ms (default: 5000) */
  defaultTimeoutMs?: number;

  /** Environment variables allowed to pass through from process.env */
  envAllowlist?: string[];

  /** Declared shell hooks */
  commands?: ShellHookCommand[];
}

export interface ShellHookCommand {
  id?: string;
  event: HookEvent;
  command: string;
  args?: string[];
  timeoutMs?: number;
  priority?: number;
}

export type HookEvent =
  | 'run.before'
  | 'run.after'
  | 'iteration.before'
  | 'iteration.after'
  | 'completion.before'
  | 'completion.after'
  | 'recovery.before'
  | 'recovery.after'
  | 'agent.start'
  | 'agent.end'
  | 'llm.before'
  | 'llm.after'
  | 'tool.before'
  | 'tool.after'
  | 'error';

/**
 * Plugins configuration (Lesson 11).
 */
export interface PluginsConfig {
  /** Enable/disable plugins */
  enabled?: boolean;

  /** Plugins to load */
  plugins?: Plugin[];

  /** Plugin discovery paths */
  discoveryPaths?: string[];
}

export interface Plugin {
  name: string;
  version: string;
  initialize: (context: PluginContext) => Promise<void>;
  cleanup?: () => Promise<void>;
}

export interface PluginContext {
  registerHook: (hook: Hook) => void;
  registerTool: (tool: ToolDefinition) => void;
  getConfig: <T>(key: string) => T | undefined;
  log: (level: 'debug' | 'info' | 'warn' | 'error', message: string) => void;
}

/**
 * Rules configuration (Lesson 12).
 */
export interface RulesConfig {
  /** Enable/disable rules */
  enabled?: boolean;

  /** Rule sources to load */
  sources?: RuleSource[];

  /** Watch for changes */
  watch?: boolean;
}

export interface RuleSource {
  type: 'file' | 'inline';
  path?: string;
  content?: string;
  priority?: number;
}

/**
 * Memory configuration (Lesson 14).
 */
export interface MemoryConfig {
  /** Enable/disable memory */
  enabled?: boolean;

  /** Memory types to enable */
  types?: {
    episodic?: boolean;
    semantic?: boolean;
    working?: boolean;
  };

  /** Retrieval strategy */
  retrievalStrategy?: 'recency' | 'relevance' | 'importance' | 'hybrid';

  /** Maximum memories to retrieve */
  retrievalLimit?: number;

  /** Persistence path */
  persistPath?: string;

  /** Maximum episodic memory entries before eviction (default: 1000) */
  maxEpisodicEntries?: number;

  /** Maximum semantic memory entries before eviction (default: 500) */
  maxSemanticEntries?: number;
}

/**
 * Planning configuration (Lesson 15).
 */
export interface PlanningConfig {
  /** Enable/disable planning */
  enabled?: boolean;

  /** Auto-plan for complex tasks */
  autoplan?: boolean;

  /** Complexity threshold for auto-planning */
  complexityThreshold?: number;

  /** Maximum plan depth */
  maxDepth?: number;

  /** Allow re-planning on failure */
  allowReplan?: boolean;
}

/**
 * Reflection configuration (Lesson 16).
 */
export interface ReflectionConfig {
  /** Enable/disable reflection */
  enabled?: boolean;

  /** Auto-reflect after each response */
  autoReflect?: boolean;

  /** Maximum reflection attempts */
  maxAttempts?: number;

  /** Confidence threshold to accept output */
  confidenceThreshold?: number;
}

/**
 * Observability configuration (Lesson 19).
 */
export interface ObservabilityConfig {
  /** Enable/disable observability */
  enabled?: boolean;

  /** Tracing configuration */
  tracing?: {
    enabled?: boolean;
    serviceName?: string;
    exporter?: 'console' | 'otlp' | 'custom';
    customExporter?: SpanExporter;
  };

  /** Metrics configuration */
  metrics?: {
    enabled?: boolean;
    collectTokens?: boolean;
    collectCosts?: boolean;
    collectLatencies?: boolean;
  };

  /** Logging configuration */
  logging?: {
    enabled?: boolean;
    level?: 'debug' | 'info' | 'warn' | 'error';
    structured?: boolean;
  };

  /** Full trace capture configuration (from Lesson 26) */
  traceCapture?: {
    enabled?: boolean;
    outputDir?: string;
    captureMessageContent?: boolean;
    captureToolResults?: boolean;
    analyzeCacheBoundaries?: boolean;
    filePattern?: string;
  };
}

export interface SpanExporter {
  export(spans: Span[]): Promise<void>;
}

export interface Span {
  traceId: string;
  spanId: string;
  name: string;
  startTime: number;
  endTime?: number;
  attributes: Record<string, unknown>;
}

/**
 * Routing configuration (Lesson 22).
 */
export interface RoutingConfig {
  /** Enable/disable routing */
  enabled?: boolean;

  /** Available models */
  models?: ModelConfig[];

  /** Routing strategy */
  strategy?: 'cost' | 'quality' | 'latency' | 'balanced' | 'rules';

  /** Routing rules */
  rules?: RoutingRule[];

  /** Fallback chain */
  fallbackChain?: string[];

  /** Enable circuit breaker */
  circuitBreaker?: boolean;
}

export interface ModelConfig {
  id: string;
  provider: LLMProvider;
  costPer1kInput?: number;
  costPer1kOutput?: number;
  maxTokens?: number;
  capabilities?: string[];
}

export interface RoutingRule {
  condition: (context: RoutingContext) => boolean;
  model: string;
  priority?: number;
}

export interface RoutingContext {
  task: string;
  complexity?: number;
  requiredCapabilities?: string[];
  budget?: number;
}

/**
 * Unified policy profile for tool and bash behavior.
 */
export interface PolicyProfile {
  /** Tool access behavior */
  toolAccessMode?: 'all' | 'whitelist' | 'denylist';
  /** Explicitly allowed tools (for whitelist mode) */
  allowedTools?: string[];
  /** Explicitly denied tools */
  deniedTools?: string[];
  /** Bash policy mode */
  bashMode?: 'disabled' | 'read_only' | 'task_scoped' | 'full';
  /** Additional bash write protections */
  bashWriteProtection?: 'off' | 'block_file_mutation';
  /** Approval behavior overrides */
  approval?: {
    autoApprove?: string[];
    scopedApprove?: Record<string, { paths: string[] }>;
    requireApproval?: string[];
  };
}

/**
 * Policy engine configuration.
 * Provides unified and configurable enforcement across agent paths.
 */
export interface PolicyEngineConfig {
  /** Enable/disable unified policy engine */
  enabled?: boolean;
  /** Keep legacy checks as fallback while migrating */
  legacyFallback?: boolean;
  /** Named policy profiles */
  profiles?: Record<string, PolicyProfile>;
  /** Default profile for root agents */
  defaultProfile?: string;
  /** Default profile for swarm workers */
  defaultSwarmProfile?: string;
}

/**
 * Sandbox configuration (Lesson 20).
 */
export interface SandboxConfig {
  /** Enable/disable sandboxing */
  enabled?: boolean;

  /** Isolation level (legacy, use mode for OS-specific sandboxing) */
  isolation?: 'none' | 'process' | 'container';

  /** Sandbox mode - auto-detects best available sandbox */
  mode?: 'auto' | 'seatbelt' | 'docker' | 'basic' | 'none';

  /** Allowed commands for bash (used by basic sandbox) */
  allowedCommands?: string[];

  /** Blocked commands */
  blockedCommands?: string[];

  /** Resource limits */
  resourceLimits?: {
    maxCpuSeconds?: number;
    maxMemoryMB?: number;
    maxOutputBytes?: number;
    timeout?: number;
  };

  /** Allowed paths for file operations (writable) */
  allowedPaths?: string[];

  /** Readable paths (for OS-specific sandboxes) */
  readablePaths?: string[];

  /** Whether network access is allowed */
  networkAllowed?: boolean;

  /** Docker image to use (for docker mode) */
  dockerImage?: string;

  /** Legacy compatibility flag: block shell file creation patterns */
  blockFileCreationViaBash?: boolean;

  /** Optional per-agent bash policy mode */
  bashMode?: PolicyProfile['bashMode'];

  /** Optional per-agent bash write protection behavior */
  bashWriteProtection?: PolicyProfile['bashWriteProtection'];
}

/**
 * Human-in-the-loop configuration (Lesson 21).
 */
export interface HumanInLoopConfig {
  /** Enable/disable human-in-the-loop */
  enabled?: boolean;

  /** Risk threshold requiring approval */
  riskThreshold?: 'low' | 'moderate' | 'high' | 'critical';

  /** Actions that always require approval */
  alwaysApprove?: string[];

  /** Actions that never require approval */
  neverApprove?: string[];

  /** Approval timeout in ms */
  approvalTimeout?: number;

  /** Approval handler */
  approvalHandler?: ApprovalHandler;

  /** Enable audit logging */
  auditLog?: boolean;
}

export type ApprovalHandler = (request: ApprovalRequest) => Promise<ApprovalResponse>;

export interface ApprovalRequest {
  id: string;
  action: string;
  tool?: string;
  args?: Record<string, unknown>;
  risk: 'low' | 'moderate' | 'high' | 'critical';
  context: string;
}

export interface ApprovalResponse {
  approved: boolean;
  reason?: string;
  modifiedArgs?: Record<string, unknown>;
}

/**
 * Multi-agent configuration (Lesson 17).
 */
export interface MultiAgentConfig {
  /** Enable/disable multi-agent */
  enabled?: boolean;

  /** Agent roles to use */
  roles?: AgentRoleConfig[];

  /** Consensus strategy for team decisions */
  consensusStrategy?: 'voting' | 'authority' | 'unanimous' | 'first-complete';

  /** Communication mode */
  communicationMode?: 'broadcast' | 'directed';

  /** Role name that coordinates the team */
  coordinatorRole?: string;
}

export interface AgentRoleConfig {
  name: string;
  description: string;
  systemPrompt: string;
  capabilities: string[];
  authority: number;
  model?: string;
}

/**
 * ReAct pattern configuration (Lesson 18).
 */
export interface ReActPatternConfig {
  /** Enable/disable ReAct reasoning */
  enabled?: boolean;

  /** Maximum reasoning steps */
  maxSteps?: number;

  /** Stop on first valid answer */
  stopOnAnswer?: boolean;

  /** Include reasoning trace in output */
  includeReasoning?: boolean;
}

/**
 * Execution policy configuration (Lesson 23).
 */
export interface ExecutionPolicyConfig {
  /** Enable/disable execution policies */
  enabled?: boolean;

  /** Default policy for unlisted tools */
  defaultPolicy?: 'allow' | 'prompt' | 'forbidden';

  /** Per-tool policies */
  toolPolicies?: Record<string, ToolPolicyConfig>;

  /** Enable intent-aware decisions */
  intentAware?: boolean;

  /** Minimum confidence for intent-based auto-allow */
  intentConfidenceThreshold?: number;

  /** Policy preset to use */
  preset?: 'strict' | 'balanced' | 'permissive';
}

export interface ToolPolicyConfig {
  policy: 'allow' | 'prompt' | 'forbidden';
  conditions?: ToolPolicyCondition[];
  reason?: string;
}

export interface ToolPolicyCondition {
  argMatch?: Record<string, string | RegExp>;
  policy: 'allow' | 'prompt' | 'forbidden';
  reason?: string;
}

/**
 * Thread management configuration (Lesson 24).
 */
export interface ThreadsConfig {
  /** Enable/disable thread management */
  enabled?: boolean;

  /** Auto-create checkpoints at key moments */
  autoCheckpoint?: boolean;

  /** Checkpoint frequency (every N iterations) */
  checkpointFrequency?: number;

  /** Maximum checkpoints to keep */
  maxCheckpoints?: number;

  /** Enable rollback capability */
  enableRollback?: boolean;

  /** Enable forking capability */
  enableForking?: boolean;
}

/**
 * Cancellation configuration.
 * @see TimeoutConfig in config/base-types.ts for the shared timeout pattern.
 */
export interface CancellationConfig {
  /** Enable/disable cancellation support */
  enabled?: boolean;

  /** Default timeout for operations in ms (0 = no timeout) */
  defaultTimeout?: number;

  /** Grace period for cleanup after cancellation in ms */
  gracePeriod?: number;
}

/**
 * Resource monitoring configuration.
 * @see BudgetConfig in config/base-types.ts for the shared budget pattern.
 */
export interface ResourceConfig {
  /** Enable/disable resource monitoring */
  enabled?: boolean;

  /** Max memory in MB */
  maxMemoryMB?: number;

  /** Max CPU time in seconds */
  maxCpuTimeSec?: number;

  /** Max concurrent operations */
  maxConcurrentOps?: number;

  /** Warning threshold (0-1) */
  warnThreshold?: number;

  /** Critical threshold (0-1) */
  criticalThreshold?: number;
}

/**
 * LSP (Language Server Protocol) configuration.
 */
export interface LSPAgentConfig {
  /** Enable/disable LSP support */
  enabled?: boolean;

  /** Auto-detect and start servers based on file types */
  autoDetect?: boolean;

  /** Custom server configurations (language -> {command, args, extensions}) */
  servers?: Record<
    string,
    {
      command: string;
      args?: string[];
      extensions: string[];
      languageId: string;
    }
  >;

  /** Request timeout in ms */
  timeout?: number;
}

/**
 * Semantic cache configuration.
 * Caches LLM responses based on query similarity to avoid redundant calls.
 * @see BudgetConfig in config/base-types.ts for the shared budget pattern.
 */
export interface SemanticCacheAgentConfig {
  /** Enable/disable semantic caching */
  enabled?: boolean;

  /** Similarity threshold (0-1, default 0.95) - higher = more strict */
  threshold?: number;

  /** Maximum cache size (entries) */
  maxSize?: number;

  /** Time-to-live in milliseconds (0 = no expiry) */
  ttl?: number;
}

/**
 * Skills configuration.
 * Discoverable skill packages that provide specialized agent capabilities.
 */
export interface SkillsAgentConfig {
  /** Enable/disable skills system */
  enabled?: boolean;

  /** Directories to search for skills */
  directories?: string[];

  /** Whether to load built-in skills */
  loadBuiltIn?: boolean;

  /** Auto-activate skills based on triggers */
  autoActivate?: boolean;
}

/**
 * Codebase context configuration.
 * Intelligent code selection for context management within token budgets.
 */
export interface CodebaseContextAgentConfig {
  /** Enable/disable codebase context */
  enabled?: boolean;

  /** Root directory to analyze (defaults to cwd) */
  root?: string;

  /** File patterns to include (glob) */
  includePatterns?: string[];

  /** File patterns to exclude (glob) */
  excludePatterns?: string[];

  /** Maximum file size in bytes (default: 100KB) */
  maxFileSize?: number;

  /** Maximum tokens to allocate for codebase context */
  maxTokens?: number;

  /** Selection strategy: importance_first, relevance_first, breadth_first, depth_first */
  strategy?: 'importance_first' | 'relevance_first' | 'breadth_first' | 'depth_first';
}

/**
 * Interactive planning configuration.
 * Controls the conversational + editable planning feature.
 */
export interface InteractivePlanningAgentConfig {
  /** Enable/disable interactive planning */
  enabled?: boolean;

  /** Enable checkpoints for rollback (default: true) */
  enableCheckpoints?: boolean;

  /** Auto-checkpoint every N completed steps (default: 3) */
  autoCheckpointInterval?: number;

  /** Maximum number of plan steps (default: 20) */
  maxPlanSteps?: number;

  /** Require user approval before executing plan (default: true) */
  requireApproval?: boolean;
}

/**
 * Recursive context (RLM) configuration.
 * Controls the Recursive Language Models feature for large context handling.
 */
export interface RecursiveContextAgentConfig {
  /** Enable/disable recursive context */
  enabled?: boolean;

  /** Maximum recursion depth (default: 5) */
  maxRecursionDepth?: number;

  /** Maximum tokens per snippet (default: 2000) */
  maxSnippetTokens?: number;

  /** Cache navigation results (default: true) */
  cacheNavigationResults?: boolean;

  /** Enable synthesis across recursive calls (default: true) */
  enableSynthesis?: boolean;
}

/**
 * Compaction configuration.
 * Controls automatic context compaction for long sessions.
 */
export interface CompactionAgentConfig {
  /** Enable/disable compaction */
  enabled?: boolean;

  /** Token threshold to trigger compaction (e.g., 80000) */
  tokenThreshold?: number;

  /** Number of recent messages to preserve verbatim */
  preserveRecentCount?: number;

  /** Whether to preserve tool results in compaction */
  preserveToolResults?: boolean;

  /** Maximum tokens for the summary */
  summaryMaxTokens?: number;

  /** Model to use for summarization (defaults to main model) */
  summaryModel?: string;

  /** Compaction mode: auto, approval, manual */
  mode?: 'auto' | 'approval' | 'manual';
}

/**
 * Learning store configuration.
 * Controls cross-session learning from failures.
 */
export interface LearningStoreAgentConfig {
  /** Enable/disable learning store */
  enabled?: boolean;

  /** Path to SQLite database (default: .agent/learnings.db) */
  dbPath?: string;

  /** Whether to require user validation for learnings (default: true) */
  requireValidation?: boolean;

  /** Minimum confidence to auto-validate (default: 0.9) */
  autoValidateThreshold?: number;

  /** Maximum learnings to keep (default: 500) */
  maxLearnings?: number;
}

/**
 * LLM resilience configuration.
 * Controls empty response retry and max_tokens continuation behavior.
 */
export interface LLMResilienceAgentConfig {
  /** Enable/disable resilience layer */
  enabled?: boolean;

  /** Maximum retries for empty responses (default: 2) */
  maxEmptyRetries?: number;

  /** Maximum continuation attempts for max_tokens (default: 3) */
  maxContinuations?: number;

  /** Whether to auto-continue on max_tokens (default: true) */
  autoContinue?: boolean;

  /** Minimum acceptable content length (default: 1) */
  minContentLength?: number;

  /**
   * Recover when model emits "I'll do X" without calling tools.
   * Enabled by default to prevent false-complete turns.
   */
  incompleteActionRecovery?: boolean;

  /** Maximum retries for incomplete action recovery (default: 2) */
  maxIncompleteActionRetries?: number;

  /**
   * Enforce requested artifact delivery (e.g., "write *.md").
   * When enabled, completion is blocked until required write tools run.
   */
  enforceRequestedArtifacts?: boolean;

  /**
   * Auto-run bounded follow-up attempts after incomplete_action/future_intent.
   * Default: true.
   */
  incompleteActionAutoLoop?: boolean;

  /**
   * Max number of run-level auto-loop attempts for incomplete outcomes.
   * Default: 2.
   */
  maxIncompleteAutoLoops?: number;

  /**
   * Prompt style for auto-loop guidance.
   * Default: strict.
   */
  autoLoopPromptStyle?: 'strict' | 'concise';

  /**
   * Staleness threshold for task leases in ms.
   * In-progress tasks older than this may be requeued to pending at run boundaries.
   * Default: 300000 (5 minutes).
   */
  taskLeaseStaleMs?: number;
}

/**
 * File change tracker configuration.
 * Controls undo capability for file operations.
 */
export interface FileChangeTrackerAgentConfig {
  /** Enable/disable file change tracking */
  enabled?: boolean;

  /** Maximum bytes for full content storage (default: 50KB) */
  maxFullContentBytes?: number;
}

/**
 * Subagent configuration.
 * Controls timeout and iteration limits for spawned subagents.
 * @see TimeoutConfig in config/base-types.ts for the shared timeout pattern.
 */
export interface SubagentConfig {
  /** Enable/disable subagent spawning */
  enabled?: boolean;

  /** Default timeout in ms for subagent execution (default: 120000 = 2 min) */
  defaultTimeout?: number;

  /** Per-agent-type timeout overrides in ms (takes priority over defaultTimeout) */
  timeouts?: Record<string, number>;

  /** Default max iterations for subagents (default: 10, reduced from 30) */
  defaultMaxIterations?: number;

  /** Per-agent-type max iteration overrides (takes priority over defaultMaxIterations) */
  maxIterations?: Record<string, number>;

  /** Whether subagents inherit observability config from parent */
  inheritObservability?: boolean;

  /** Graceful wrapup window before hard timeout kill in ms (default: 30000) */
  wrapupWindowMs?: number;

  /** Interval for idle timeout checks in ms (default: 5000) */
  idleCheckIntervalMs?: number;
}

/**
 * Provider-level resilience configuration.
 * Controls circuit breaker and fallback chain for LLM provider calls.
 */
export interface ProviderResilienceConfig {
  /** Enable/disable provider resilience */
  enabled?: boolean;

  /** Circuit breaker configuration */
  circuitBreaker?:
    | {
        /** Number of failures before opening circuit (default: 5) */
        failureThreshold?: number;
        /** Time in ms before testing recovery (default: 30000) */
        resetTimeout?: number;
        /** Requests allowed in half-open state (default: 1) */
        halfOpenRequests?: number;
        /** Error types that trigger circuit (default: all) */
        tripOnErrors?: Array<'RATE_LIMITED' | 'SERVER_ERROR' | 'NETWORK_ERROR' | 'TIMEOUT' | 'ALL'>;
      }
    | false;

  /** Fallback provider names in priority order */
  fallbackProviders?: string[];

  /** Fallback chain configuration */
  fallbackChain?: {
    /** Cooldown time in ms for failed providers (default: 60000) */
    cooldownMs?: number;
    /** Failures before provider cooldown (default: 3) */
    failureThreshold?: number;
  };

  /** Callback when falling back between providers */
  onFallback?: (from: string, to: string, error: Error) => void;
}

/**
 * Configuration for trace collection.
 */
export interface TraceCollectorConfig {
  /** Enable trace collection */
  enabled?: boolean;

  /** Capture full message content (can be large) */
  captureMessageContent?: boolean;

  /** Capture tool results (can be large) */
  captureToolResults?: boolean;

  /** Max result size before truncation */
  maxResultSize?: number;

  /** Enable cache boundary analysis */
  analyzeCacheBoundaries?: boolean;

  /** Output directory for traces */
  outputDir?: string;

  /** JSONL file name pattern */
  filePattern?: string;

  /** Enable console output for traces */
  enableConsoleOutput?: boolean;
}

// =============================================================================
// AGENT STATE & RESULTS
// =============================================================================

/**
 * Agent execution state.
 */
export interface AgentState {
  /** Current status */
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';

  /** Conversation messages */
  messages: Message[];

  /** Current plan (if planning enabled) */
  plan?: AgentPlan;

  /** Memory context (if memory enabled) */
  memoryContext?: string[];

  /** Current iteration */
  iteration: number;

  /** Accumulated metrics */
  metrics: AgentMetrics;

  /** Trace ID for observability */
  traceId?: string;
}

export interface AgentPlan {
  goal: string;
  tasks: PlanTask[];
  currentTaskIndex: number;
}

export interface PlanTask {
  id: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  dependencies: string[];
}

export interface AgentMetrics {
  totalTokens: number;
  inputTokens: number;
  outputTokens: number;
  estimatedCost: number;
  llmCalls: number;
  toolCalls: number;
  duration: number;
  reflectionAttempts?: number;
  /** Number of successful run() completions in this session */
  successCount?: number;
  /** Number of failed run() completions in this session */
  failureCount?: number;
  /** Number of cancelled run() completions in this session */
  cancelCount?: number;
  /** Number of resilience retry attempts in this session */
  retryCount?: number;
}

export interface OpenTaskSummary {
  pending: number;
  inProgress: number;
  blocked: number;
}

export interface AgentCompletionStatus {
  success: boolean;
  reason:
    | 'completed'
    | 'resource_limit'
    | 'budget_limit'
    | 'max_iterations'
    | 'hard_context_limit'
    | 'incomplete_action'
    | 'open_tasks'
    | 'future_intent'
    | 'swarm_failure'
    | 'error'
    | 'cancelled';
  details?: string;
  openTasks?: OpenTaskSummary;
  futureIntentDetected?: boolean;
  recovery?: {
    intraRunRetries: number;
    autoLoopRuns: number;
    terminal: boolean;
    reasonChain: string[];
  };
}

/**
 * Agent run result.
 */
export interface AgentResult {
  /** Success flag */
  success: boolean;

  /** Final response */
  response: string;

  /** Error message if failed */
  error?: string;

  /** Execution metrics */
  metrics: AgentMetrics;

  /** Full message history */
  messages: Message[];

  /** Trace ID for debugging */
  traceId?: string;

  /** Plan that was executed (if planning enabled) */
  plan?: AgentPlan;

  /** Structured completion status used by UI and tracing */
  completion: AgentCompletionStatus;
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Events emitted during agent execution.
 */
export type AgentEvent =
  // Lifecycle hooks
  | { type: 'run.before'; task: string }
  | {
      type: 'run.after';
      success: boolean;
      reason: AgentCompletionStatus['reason'];
      details?: string;
    }
  | { type: 'iteration.before'; iteration: number }
  | {
      type: 'iteration.after';
      iteration: number;
      hadToolCalls: boolean;
      completionCandidate: boolean;
    }
  | { type: 'completion.before'; reason: string; attempt?: number; maxAttempts?: number }
  | {
      type: 'completion.after';
      success: boolean;
      reason: AgentCompletionStatus['reason'];
      details?: string;
    }
  | { type: 'recovery.before'; reason: string; attempt: number; maxAttempts: number }
  | { type: 'recovery.after'; reason: string; recovered: boolean; attempts: number }
  // Core events
  | { type: 'start'; task: string; traceId: string }
  | { type: 'planning'; plan: AgentPlan }
  | { type: 'task.start'; task: PlanTask }
  | { type: 'task.complete'; task: PlanTask }
  | { type: 'llm.start'; model: string; subagent?: string }
  | { type: 'llm.chunk'; content: string; subagent?: string }
  | { type: 'llm.complete'; response: ChatResponse; subagent?: string }
  | { type: 'tool.start'; tool: string; args: Record<string, unknown>; subagent?: string }
  | { type: 'tool.complete'; tool: string; result: unknown }
  | { type: 'tool.blocked'; tool: string; reason: string }
  | { type: 'approval.required'; request: ApprovalRequest }
  | { type: 'approval.received'; response: ApprovalResponse }
  | { type: 'reflection'; attempt: number; satisfied: boolean }
  | { type: 'memory.retrieved'; count: number }
  | { type: 'memory.stored'; memoryType: string }
  | { type: 'error'; error: string; subagent?: string }
  | {
      type: 'completion.blocked';
      reasons: string[];
      openTasks?: OpenTaskSummary;
      diagnostics?: {
        forceTextOnly?: boolean;
        availableTasks?: number;
        pendingWithOwner?: number;
      };
    }
  | { type: 'complete'; result: AgentResult }
  // ReAct events (Lesson 18)
  | { type: 'react.thought'; step: number; thought: string }
  | { type: 'react.action'; step: number; action: string; input: Record<string, unknown> }
  | { type: 'react.observation'; step: number; observation: string }
  | { type: 'react.answer'; answer: string }
  // Multi-agent events (Lesson 17)
  | { type: 'multiagent.spawn'; agentId: string; role: string }
  | { type: 'multiagent.complete'; agentId: string; success: boolean }
  | { type: 'consensus.start'; strategy: string }
  | { type: 'consensus.reached'; agreed: boolean; result: string }
  // Execution policy events (Lesson 23)
  | { type: 'policy.evaluated'; tool: string; policy: string; reason: string }
  | { type: 'intent.classified'; tool: string; intent: string; confidence: number }
  | { type: 'grant.created'; grantId: string; tool: string }
  | { type: 'grant.used'; grantId: string }
  | {
      type: 'policy.profile.resolved';
      profile: string;
      context: 'root' | 'subagent' | 'swarm';
      selectionSource?: 'explicit' | 'worker-capability' | 'task-type' | 'default';
      usedLegacyMappings: boolean;
      legacySources?: string[];
    }
  | { type: 'policy.legacy.fallback.used'; profile: string; sources: string[]; warnings: string[] }
  | { type: 'policy.tool.auto-allowed'; tool: string; reason: string }
  | {
      type: 'policy.tool.blocked';
      tool: string;
      profile?: string;
      phase?: 'precheck' | 'enforced';
      reason: string;
    }
  | {
      type: 'policy.bash.blocked';
      command: string;
      profile?: string;
      phase?: 'precheck' | 'enforced';
      reason: string;
    }
  // Thread events (Lesson 24)
  | { type: 'thread.forked'; threadId: string; parentId: string }
  | { type: 'thread.switched'; fromId: string; toId: string }
  | { type: 'checkpoint.created'; checkpointId: string; label?: string }
  | { type: 'checkpoint.restored'; checkpointId: string }
  | { type: 'rollback'; steps: number }
  // Agent registry events (subagent support)
  // agentId is the unique instance ID (e.g., "spawn-1704067200000-abc123")
  // agentType is the agent type name (e.g., "researcher") for display purposes
  | { type: 'agent.spawn'; agentId: string; name: string; task: string }
  | {
      type: 'agent.complete';
      agentId: string;
      agentType?: string;
      success: boolean;
      output?: string;
    }
  | { type: 'agent.error'; agentId: string; agentType?: string; error: string }
  | { type: 'agent.registered'; name: string }
  | { type: 'agent.unregistered'; name: string }
  | {
      type: 'agent.pending_plan';
      agentId: string;
      changes: Array<{ id: string; tool: string; args: Record<string, unknown>; reason: string }>;
    }
  // Cancellation events
  | { type: 'cancellation.requested'; reason?: string }
  | { type: 'cancellation.completed'; cleanupDuration: number }
  // Semantic cache events
  | { type: 'cache.hit'; query: string; similarity: number }
  | { type: 'cache.miss'; query: string }
  | { type: 'cache.set'; query: string }
  // Compaction events
  | {
      type: 'compaction.auto';
      tokensBefore: number;
      tokensAfter: number;
      messagesCompacted: number;
    }
  | { type: 'compaction.warning'; currentTokens: number; threshold: number }
  // Insight events (verbose execution feedback)
  | {
      type: 'insight.tokens';
      inputTokens: number;
      outputTokens: number;
      cacheReadTokens?: number;
      cacheWriteTokens?: number;
      cost?: number;
      model: string;
    }
  | {
      type: 'insight.context';
      currentTokens: number;
      maxTokens: number;
      messageCount: number;
      percentUsed: number;
    }
  | { type: 'insight.tool'; tool: string; summary: string; durationMs: number; success: boolean }
  | { type: 'insight.routing'; model: string; reason: string; complexity?: string }
  // Mode events
  | { type: 'mode.changed'; from: string; to: string }
  // Plan mode events
  | {
      type: 'plan.change.queued';
      tool: string;
      changeId?: string;
      summary?: string;
      subagent?: string;
    }
  | { type: 'plan.approved'; changeCount: number }
  | { type: 'plan.rejected' }
  | { type: 'plan.executing'; changeIndex: number; totalChanges: number }
  | {
      type: 'plan.change.complete';
      changeIndex: number;
      tool: string;
      result: unknown;
      error?: string;
    }
  // Resilience events (LLM call recovery)
  | { type: 'resilience.retry'; reason: string; attempt: number; maxAttempts: number }
  | { type: 'resilience.recovered'; reason: string; attempts: number }
  | {
      type: 'resilience.continue';
      reason: string;
      continuation: number;
      maxContinuations: number;
      accumulatedLength: number;
    }
  | { type: 'resilience.completed'; reason: string; continuations: number; finalLength: number }
  | { type: 'resilience.failed'; reason: string; emptyRetries: number; continuations: number }
  | { type: 'resilience.truncated_tool_call'; toolNames: string[] }
  | {
      type: 'resilience.incomplete_action_detected';
      reason: string;
      attempt: number;
      maxAttempts: number;
      requiresArtifact: boolean;
    }
  | { type: 'resilience.incomplete_action_recovered'; reason: string; attempts: number }
  | {
      type: 'resilience.incomplete_action_failed';
      reason: string;
      attempts: number;
      maxAttempts: number;
    }
  // Learning store events
  | { type: 'learning.proposed'; learningId: string; description: string }
  | { type: 'learning.validated'; learningId: string }
  | { type: 'learning.applied'; learningId: string; context: string }
  // Decision transparency events (Phase 3)
  | {
      type: 'decision.routing';
      model: string;
      reason: string;
      alternatives?: Array<{ model: string; rejected: string }>;
    }
  | {
      type: 'decision.tool';
      tool: string;
      decision: 'allowed' | 'prompted' | 'blocked';
      policyMatch?: string;
    }
  | {
      type: 'context.health';
      currentTokens: number;
      maxTokens: number;
      estimatedExchanges: number;
      percentUsed: number;
    }
  // Subagent visibility events (Phase 5)
  | { type: 'subagent.iteration'; agentId: string; iteration: number; maxIterations: number }
  | {
      type: 'subagent.phase';
      agentId: string;
      phase: 'exploring' | 'planning' | 'executing' | 'completing';
    }
  | {
      type: 'subagent.wrapup.started';
      agentId: string;
      agentType: string;
      reason: string;
      elapsedMs: number;
    }
  | { type: 'subagent.wrapup.completed'; agentId: string; agentType: string; elapsedMs: number }
  | {
      type: 'subagent.timeout.hard_kill';
      agentId: string;
      agentType: string;
      reason: string;
      elapsedMs: number;
    }
  // Parallel subagent events
  | { type: 'parallel.spawn.start'; count: number; agents: string[] }
  | {
      type: 'parallel.spawn.complete';
      count: number;
      successCount: number;
      results: Array<{ agent: string; success: boolean; tokens: number }>;
    }
  // Task system events (Claude Code-style)
  | { type: 'task.created'; task: { id: string; subject: string; status: string } }
  | { type: 'task.updated'; task: { id: string; subject: string; status: string } }
  | { type: 'task.deleted'; taskId: string }
  // Safeguard events (tool call explosion defense)
  | { type: 'safeguard.tool_call_cap'; requested: number; cap: number; droppedCount: number }
  | {
      type: 'safeguard.circuit_breaker';
      totalInBatch: number;
      failures: number;
      threshold: number;
      skipped: number;
    }
  | {
      type: 'safeguard.context_overflow_guard';
      estimatedTokens: number;
      maxTokens: number;
      toolResultsSkipped: number;
    }
  // Diagnostics events (AST + compilation visibility)
  | { type: 'diagnostics.syntax-error'; file: string; line: number; message: string }
  | {
      type: 'diagnostics.tsc-check';
      errorCount: number;
      duration: number;
      trigger: 'periodic' | 'completion' | 'manual';
    }
  // Swarm mode events (M8: use union with canonical SwarmEvent type)
  | import('./integrations/swarm/swarm-events.js').SwarmEvent;

export type AgentEventListener = (event: AgentEvent) => void;
