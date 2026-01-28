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
}

/**
 * Tool call from LLM.
 */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
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
 * LLM provider interface.
 */
export interface LLMProvider {
  name?: string;
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
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
}

export interface Hook {
  /** Optional unique identifier for duplicate detection */
  id?: string;
  event: HookEvent;
  handler: (data: unknown) => void | Promise<void>;
  priority?: number;
}

export type HookEvent =
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
  servers?: Record<string, {
    command: string;
    args?: string[];
    extensions: string[];
    languageId: string;
  }>;

  /** Request timeout in ms */
  timeout?: number;
}

/**
 * Semantic cache configuration.
 * Caches LLM responses based on query similarity to avoid redundant calls.
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
 */
export interface SubagentConfig {
  /** Enable/disable subagent spawning */
  enabled?: boolean;

  /** Default timeout in ms for subagent execution (default: 120000 = 2 min) */
  defaultTimeout?: number;

  /** Default max iterations for subagents (default: 10, reduced from 30) */
  defaultMaxIterations?: number;

  /** Whether subagents inherit observability config from parent */
  inheritObservability?: boolean;
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
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Events emitted during agent execution.
 */
export type AgentEvent =
  // Core events
  | { type: 'start'; task: string; traceId: string }
  | { type: 'planning'; plan: AgentPlan }
  | { type: 'task.start'; task: PlanTask }
  | { type: 'task.complete'; task: PlanTask }
  | { type: 'llm.start'; model: string }
  | { type: 'llm.chunk'; content: string }
  | { type: 'llm.complete'; response: ChatResponse }
  | { type: 'tool.start'; tool: string; args: Record<string, unknown> }
  | { type: 'tool.complete'; tool: string; result: unknown }
  | { type: 'tool.blocked'; tool: string; reason: string }
  | { type: 'approval.required'; request: ApprovalRequest }
  | { type: 'approval.received'; response: ApprovalResponse }
  | { type: 'reflection'; attempt: number; satisfied: boolean }
  | { type: 'memory.retrieved'; count: number }
  | { type: 'memory.stored'; memoryType: string }
  | { type: 'error'; error: string }
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
  // Thread events (Lesson 24)
  | { type: 'thread.forked'; threadId: string; parentId: string }
  | { type: 'thread.switched'; fromId: string; toId: string }
  | { type: 'checkpoint.created'; checkpointId: string; label?: string }
  | { type: 'checkpoint.restored'; checkpointId: string }
  | { type: 'rollback'; steps: number }
  // Agent registry events (subagent support)
  | { type: 'agent.spawn'; agentId: string; name: string; task: string }
  | { type: 'agent.complete'; agentId: string; success: boolean }
  | { type: 'agent.error'; agentId: string; error: string }
  | { type: 'agent.registered'; name: string }
  | { type: 'agent.unregistered'; name: string }
  // Cancellation events
  | { type: 'cancellation.requested'; reason?: string }
  | { type: 'cancellation.completed'; cleanupDuration: number }
  // Semantic cache events
  | { type: 'cache.hit'; query: string; similarity: number }
  | { type: 'cache.miss'; query: string }
  | { type: 'cache.set'; query: string }
  // Compaction events
  | { type: 'compaction.auto'; tokensBefore: number; tokensAfter: number; messagesCompacted: number }
  | { type: 'compaction.warning'; currentTokens: number; threshold: number }
  // Insight events (verbose execution feedback)
  | { type: 'insight.tokens'; inputTokens: number; outputTokens: number; cacheReadTokens?: number; cacheWriteTokens?: number; cost?: number; model: string }
  | { type: 'insight.context'; currentTokens: number; maxTokens: number; messageCount: number; percentUsed: number }
  | { type: 'insight.tool'; tool: string; summary: string; durationMs: number; success: boolean }
  | { type: 'insight.routing'; model: string; reason: string; complexity?: string }
  // Mode events
  | { type: 'mode.changed'; from: string; to: string }
  // Plan mode events
  | { type: 'plan.change.queued'; tool: string; changeId?: string }
  | { type: 'plan.approved'; changeCount: number }
  | { type: 'plan.rejected' }
  | { type: 'plan.executing'; changeIndex: number; totalChanges: number }
  // Resilience events (LLM call recovery)
  | { type: 'resilience.retry'; reason: string; attempt: number; maxAttempts: number }
  | { type: 'resilience.recovered'; reason: string; attempts: number }
  | { type: 'resilience.continue'; reason: string; continuation: number; maxContinuations: number; accumulatedLength: number }
  | { type: 'resilience.completed'; reason: string; continuations: number; finalLength: number }
  | { type: 'resilience.failed'; reason: string; emptyRetries: number; continuations: number }
  // Learning store events
  | { type: 'learning.proposed'; learningId: string; description: string }
  | { type: 'learning.validated'; learningId: string }
  | { type: 'learning.applied'; learningId: string; context: string };

export type AgentEventListener = (event: AgentEvent) => void;
