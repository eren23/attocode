/**
 * Lesson 26: Tracing & Evaluation Types
 *
 * Comprehensive type definitions for:
 * - Full LLM request/response tracing
 * - KV cache boundary analysis
 * - Benchmark task definitions
 * - Evaluation results and comparison
 *
 * These types extend the observability types from Lesson 19 with
 * production-grade tracing and evaluation capabilities.
 */

import type { Span, AgentMetrics, SpanAttributeValue } from '../observability/types.js';

// =============================================================================
// LLM REQUEST/RESPONSE TRACING
// =============================================================================

/**
 * A traced message with token estimates.
 * Captures everything sent to/from the LLM for debugging and analysis.
 */
export interface TracedMessage {
  /** Message role */
  role: 'system' | 'user' | 'assistant' | 'tool';

  /** Full message content */
  content: string;

  /** Estimated token count for this message */
  estimatedTokens: number;

  /** Tool call ID (for tool messages) */
  toolCallId?: string;

  /** Tool calls made by assistant */
  toolCalls?: TracedToolCall[];

  /** Content hash for cache tracking */
  contentHash: string;
}

/**
 * A traced tool call with timing and result.
 */
export interface TracedToolCall {
  /** Unique call ID */
  id: string;

  /** Tool name */
  name: string;

  /** Arguments passed to tool */
  arguments: Record<string, unknown>;

  /** Execution duration in ms */
  durationMs?: number;

  /** Execution status */
  status?: 'pending' | 'success' | 'error';

  /** Result if completed */
  result?: unknown;

  /** Error if failed */
  error?: string;
}

/**
 * A traced tool definition.
 */
export interface TracedToolDefinition {
  /** Tool name */
  name: string;

  /** Tool description */
  description: string;

  /** JSON schema for parameters */
  parametersSchema: Record<string, unknown>;

  /** Estimated tokens for this tool definition */
  estimatedTokens: number;
}

/**
 * Token breakdown for a request.
 */
export interface TokenBreakdown {
  /** Total input tokens */
  input: number;

  /** Total output tokens */
  output: number;

  /** Total tokens */
  total: number;

  /** Per-component breakdown */
  breakdown: {
    systemPrompt: number;
    messages: number;
    toolDefinitions: number;
    toolResults: number;
  };
}

/**
 * Cache efficiency breakdown from API response.
 */
export interface CacheBreakdown {
  /** Tokens read from cache (from API response) */
  cacheReadTokens: number;

  /** Tokens written to cache */
  cacheWriteTokens: number;

  /** Fresh tokens (not cached) */
  freshTokens: number;

  /** Cache hit rate (0-1) */
  hitRate: number;

  /** Estimated cost savings from caching */
  estimatedSavings: number;

  /** Identified breakpoints where cache invalidation occurs */
  breakpoints: CacheBreakpointInfo[];
}

/**
 * Information about a cache breakpoint.
 */
export interface CacheBreakpointInfo {
  /** Position in message array */
  position: number;

  /** Type of breakpoint */
  type: 'role_change' | 'content_change' | 'tool_result' | 'dynamic_content';

  /** Description of what caused the break */
  description: string;

  /** Tokens that could not be cached after this point */
  tokensAffected: number;
}

/**
 * Full LLM request trace - captures EVERYTHING for debugging.
 */
export interface LLMRequestTrace {
  /** Unique request ID */
  requestId: string;

  /** Parent trace ID */
  traceId: string;

  /** Span ID for this request */
  spanId: string;

  /** Request timestamp */
  timestamp: number;

  /** Response duration in ms */
  durationMs?: number;

  /** Model used */
  model: string;

  /** Provider (anthropic, openai, etc.) */
  provider: string;

  /** Full request details */
  request: {
    /** All messages sent */
    messages: TracedMessage[];

    /** Tool definitions included */
    tools?: TracedToolDefinition[];

    /** Request parameters */
    parameters: {
      maxTokens?: number;
      temperature?: number;
      topP?: number;
      stopSequences?: string[];
    };
  };

  /** Full response details */
  response: {
    /** Response content */
    content: string;

    /** Tool calls in response */
    toolCalls?: TracedToolCall[];

    /** Stop reason */
    stopReason: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence';
  };

  /** Token accounting */
  tokens: TokenBreakdown;

  /** Cache efficiency */
  cache: CacheBreakdown;

  /** Actual cost from provider (e.g., OpenRouter returns this directly) */
  actualCost?: number;

  /** Error if request failed */
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  };
}

/**
 * Tool execution trace.
 */
export interface ToolExecutionTrace {
  /** Unique execution ID */
  executionId: string;

  /** Parent trace ID */
  traceId: string;

  /** Span ID */
  spanId: string;

  /** Tool name */
  toolName: string;

  /** Arguments */
  arguments: Record<string, unknown>;

  /** Start timestamp */
  startTime: number;

  /** Duration in ms */
  durationMs: number;

  /** Execution status */
  status: 'success' | 'error' | 'timeout' | 'blocked';

  /** Result (truncated for large outputs) */
  result?: {
    /** Result type */
    type: 'string' | 'object' | 'binary';

    /** Result value or summary */
    value: unknown;

    /** Whether result was truncated */
    truncated: boolean;

    /** Original size in bytes */
    originalSize?: number;
  };

  /** Error details */
  error?: {
    name: string;
    message: string;
    stack?: string;
  };

  /** Resource usage */
  resources?: {
    memoryUsed?: number;
    cpuTime?: number;
    networkCalls?: number;
  };
}

// =============================================================================
// SESSION AND ITERATION TRACES
// =============================================================================

/**
 * Trace of a complete agent iteration (one LLM call + tool executions).
 */
export interface IterationTrace {
  /** Iteration number (1-indexed) */
  iterationNumber: number;

  /** Parent trace ID */
  traceId: string;

  /** Span ID for this iteration */
  spanId: string;

  /** Start timestamp */
  startTime: number;

  /** Duration in ms */
  durationMs: number;

  /** LLM request trace */
  llmRequest: LLMRequestTrace;

  /** Tool executions in this iteration */
  toolExecutions: ToolExecutionTrace[];

  /** Iteration metrics */
  metrics: {
    inputTokens: number;
    outputTokens: number;
    cacheHitRate: number;
    toolCallCount: number;
    totalCost: number;
  };
}

/**
 * Trace of a complete agent session.
 */
export interface SessionTrace {
  /** Session ID */
  sessionId: string;

  /** Root trace ID */
  traceId: string;

  /** Task/prompt that started the session */
  task: string;

  /** Model used */
  model: string;

  /** Session start time */
  startTime: number;

  /** Session end time */
  endTime?: number;

  /** Total duration */
  durationMs?: number;

  /** Session status */
  status: 'running' | 'completed' | 'failed' | 'cancelled';

  /** All iterations */
  iterations: IterationTrace[];

  /** Aggregated metrics */
  metrics: AgentMetrics & {
    /** Average cache hit rate across iterations */
    avgCacheHitRate: number;

    /** Tokens saved by caching */
    tokensSavedByCache: number;

    /** Cost saved by caching */
    costSavedByCache: number;
  };

  /** Final result */
  result?: {
    /** Whether task completed successfully */
    success: boolean;

    /** Final output */
    output?: string;

    /** Failure reason */
    failureReason?: string;
  };

  /** Session metadata */
  metadata: Record<string, SpanAttributeValue>;
}

// =============================================================================
// JSONL EXPORT TYPES
// =============================================================================

/**
 * Base type for all JSONL entries.
 */
interface BaseJSONLEntry {
  /** Entry type discriminator */
  _type: string;

  /** Entry timestamp */
  _ts: string;

  /** Trace ID for correlation */
  traceId: string;

  // Subagent context fields (present when entry comes from a subagent)
  /** Unique ID for the subagent that generated this entry */
  subagentId?: string;
  /** Type/name of the subagent (e.g., 'researcher', 'coder') */
  subagentType?: string;
  /** Session ID of the parent agent */
  parentSessionId?: string;
  /** Parent iteration when subagent was spawned */
  spawnedAtIteration?: number;
}

/**
 * Session start entry.
 */
export interface SessionStartEntry extends BaseJSONLEntry {
  _type: 'session.start';
  sessionId: string;
  /** Task description (optional for terminal sessions that contain multiple tasks) */
  task?: string;
  model: string;
  metadata: Record<string, unknown>;
}

/**
 * Session end entry.
 */
export interface SessionEndEntry extends BaseJSONLEntry {
  _type: 'session.end';
  sessionId: string;
  status: SessionTrace['status'];
  durationMs: number;
  metrics: AgentMetrics;
}

// =============================================================================
// TASK-LEVEL TRACING (One file per terminal session)
// =============================================================================

/**
 * A task within a terminal session (one user prompt/action).
 * Terminal sessions can contain multiple tasks.
 */
export interface TaskTrace {
  /** Unique task ID */
  taskId: string;

  /** Parent session ID */
  sessionId: string;

  /** Parent trace ID */
  traceId: string;

  /** The user prompt/task */
  prompt: string;

  /** Task start time */
  startTime: number;

  /** Task end time */
  endTime?: number;

  /** Total duration */
  durationMs?: number;

  /** Task status */
  status: 'running' | 'completed' | 'failed' | 'cancelled';

  /** Task number within the session (1-indexed) */
  taskNumber: number;

  /** Iterations within this task */
  iterations: IterationTrace[];

  /** Task-level aggregated metrics */
  metrics?: {
    inputTokens: number;
    outputTokens: number;
    cacheHitRate: number;
    toolCalls: number;
    totalCost: number;
  };

  /** Task result */
  result?: {
    success: boolean;
    output?: string;
    failureReason?: string;
  };
}

/**
 * Task start entry.
 */
export interface TaskStartEntry extends BaseJSONLEntry {
  _type: 'task.start';
  taskId: string;
  sessionId: string;
  prompt: string;
  taskNumber: number;
}

/**
 * Task end entry.
 */
export interface TaskEndEntry extends BaseJSONLEntry {
  _type: 'task.end';
  taskId: string;
  sessionId: string;
  status: TaskTrace['status'];
  durationMs: number;
  metrics?: TaskTrace['metrics'];
  result?: TaskTrace['result'];
}

/**
 * LLM request entry.
 */
export interface LLMRequestEntry extends BaseJSONLEntry {
  _type: 'llm.request';
  requestId: string;
  model: string;
  messageCount: number;
  toolCount: number;
  estimatedInputTokens: number;
}

/**
 * LLM response entry.
 */
export interface LLMResponseEntry extends BaseJSONLEntry {
  _type: 'llm.response';
  requestId: string;
  durationMs: number;
  tokens: TokenBreakdown;
  cache: CacheBreakdown;
  stopReason: string;
  toolCallCount: number;
}

/**
 * Tool execution entry.
 */
export interface ToolExecutionEntry extends BaseJSONLEntry {
  _type: 'tool.execution';
  executionId: string;
  toolName: string;
  durationMs: number;
  status: ToolExecutionTrace['status'];
  resultSize?: number;
  /** Tool input arguments (truncated for large values) */
  input?: Record<string, unknown>;
  /** Preview of the result (truncated) */
  outputPreview?: string;
  /** Error message if status is error */
  errorMessage?: string;
}

/**
 * Error entry.
 */
export interface ErrorEntry extends BaseJSONLEntry {
  _type: 'error';
  errorCode: string;
  errorMessage: string;
  context: string;
  recoverable: boolean;
}

// =============================================================================
// SWARM TRACE ENTRY TYPES
// =============================================================================

/**
 * Swarm start entry - emitted when swarm execution begins.
 */
export interface SwarmStartEntry extends BaseJSONLEntry {
  _type: 'swarm.start';
  taskCount: number;
  config: { maxConcurrency: number; totalBudget: number; maxCost: number };
}

/**
 * Swarm decomposition entry - emitted after task decomposition.
 */
export interface SwarmDecompositionEntry extends BaseJSONLEntry {
  _type: 'swarm.decomposition';
  tasks: Array<{ id: string; description: string; type: string; wave: number; deps: string[] }>;
  totalWaves: number;
}

/**
 * Swarm wave entry - emitted at wave start/complete.
 */
export interface SwarmWaveEntry extends BaseJSONLEntry {
  _type: 'swarm.wave';
  phase: 'start' | 'complete';
  wave: number;
  taskCount: number;
  completed?: number;
  failed?: number;
}

/**
 * Swarm task entry - emitted for individual task lifecycle events.
 */
export interface SwarmTaskEntry extends BaseJSONLEntry {
  _type: 'swarm.task';
  phase: 'dispatched' | 'completed' | 'failed' | 'skipped';
  taskId: string;
  model?: string;
  tokensUsed?: number;
  costUsed?: number;
  qualityScore?: number;
  error?: string;
  reason?: string;
}

/**
 * Swarm quality gate entry - emitted when a task is quality-rejected.
 */
export interface SwarmQualityEntry extends BaseJSONLEntry {
  _type: 'swarm.quality';
  taskId: string;
  score: number;
  feedback: string;
}

/**
 * Swarm budget snapshot entry - sampled periodically.
 */
export interface SwarmBudgetEntry extends BaseJSONLEntry {
  _type: 'swarm.budget';
  tokensUsed: number;
  tokensTotal: number;
  costUsed: number;
  costTotal: number;
}

/**
 * Swarm verification entry - emitted during integration verification.
 */
export interface SwarmVerificationEntry extends BaseJSONLEntry {
  _type: 'swarm.verification';
  phase: 'start' | 'step' | 'complete';
  stepIndex?: number;
  description?: string;
  passed?: boolean;
  summary?: string;
}

/**
 * Swarm complete entry - emitted when swarm execution finishes.
 */
export interface SwarmCompleteEntry extends BaseJSONLEntry {
  _type: 'swarm.complete';
  stats: {
    totalTasks: number;
    completedTasks: number;
    failedTasks: number;
    totalTokens: number;
    totalCost: number;
    totalDuration: number;
  };
}

/**
 * Context compaction entry - emitted when context is compacted.
 */
export interface ContextCompactionEntry extends BaseJSONLEntry {
  _type: 'context.compacted';
  tokensBefore: number;
  tokensAfter: number;
  recoveryInjected: boolean;
}

// =============================================================================
// OBSERVABILITY VISUALIZATION ENTRY TYPES
// =============================================================================

/**
 * Codebase map entry - emitted after repository analysis completes.
 * Captures the full code map with file nodes, dependencies, and symbols.
 */
export interface CodebaseMapEntry extends BaseJSONLEntry {
  _type: 'codebase.map';
  totalFiles: number;
  totalTokens: number;
  entryPoints: string[];
  coreModules: string[];
  dependencyEdges: { file: string; imports: string[] }[];
  files?: {
    filePath: string;
    directory: string;
    fileName: string;
    tokenCount: number;
    importance: number;
    type: string;
    symbols: { name: string; kind: string; exported: boolean; line: number }[];
    inDegree: number;
    outDegree: number;
  }[];
  topChunks: {
    filePath: string;
    tokenCount: number;
    importance: number;
    type: string;
    symbols: { name: string; kind: string; exported: boolean; line: number }[];
    dependencies: string[];
  }[];
}

/**
 * Blackboard event entry - emitted on finding/claim operations.
 */
export interface BlackboardEventEntry extends BaseJSONLEntry {
  _type: 'blackboard.event';
  action: 'finding.posted' | 'finding.updated' | 'claim.acquired' | 'claim.released';
  agentId: string;
  topic?: string;
  content?: string;
  confidence?: number;
  findingType?: string;
  relatedFiles?: string[];
  resource?: string;
  claimType?: string;
}

/**
 * Budget pool entry - emitted on budget allocation/consumption/release.
 */
export interface BudgetPoolEntry extends BaseJSONLEntry {
  _type: 'budget.pool';
  action: 'allocate' | 'consume' | 'release';
  agentId: string;
  tokensAllocated?: number;
  tokensUsed?: number;
  poolRemaining: number;
  poolTotal: number;
}

/**
 * Budget check entry - records each economics budget check for debugging premature death.
 */
export interface BudgetCheckEntry extends BaseJSONLEntry {
  _type: 'budget.check';
  iteration: number;
  canContinue: boolean;
  percentUsed: number;
  budgetType?: string;
  budgetMode?: string;
  forceTextOnly: boolean;
  allowTaskContinuation: boolean;
  enforcementMode: string;
  tokenUsage: number;
  maxTokens: number;
}

/**
 * File cache event entry - emitted on cache hit/miss/set/invalidate.
 */
export interface FileCacheEventEntry extends BaseJSONLEntry {
  _type: 'filecache.event';
  action: 'hit' | 'miss' | 'set' | 'invalidate';
  filePath: string;
  agentId?: string;
  currentEntries: number;
  currentBytes: number;
}

/**
 * Context injection entry - emitted when building a subagent's context.
 */
export interface ContextInjectionEntry extends BaseJSONLEntry {
  _type: 'context.injection';
  agentId: string;
  parentAgentId: string;
  repoMapTokens: number;
  blackboardFindings: number;
  modifiedFiles: string[];
  toolCount: number;
  model: string;
}

/**
 * Union of all JSONL entry types.
 */
export type JSONLEntry =
  | SessionStartEntry
  | SessionEndEntry
  | TaskStartEntry
  | TaskEndEntry
  | LLMRequestEntry
  | LLMResponseEntry
  | ToolExecutionEntry
  | ErrorEntry
  | ThinkingEntry
  | MemoryRetrievalEntry
  | PlanEvolutionEntry
  | SubagentLinkEntry
  | DecisionEntry
  | IterationWrapperEntry
  | SwarmStartEntry
  | SwarmDecompositionEntry
  | SwarmWaveEntry
  | SwarmTaskEntry
  | SwarmQualityEntry
  | SwarmBudgetEntry
  | SwarmVerificationEntry
  | SwarmCompleteEntry
  | ContextCompactionEntry
  | CodebaseMapEntry
  | BlackboardEventEntry
  | BudgetPoolEntry
  | BudgetCheckEntry
  | FileCacheEventEntry
  | ContextInjectionEntry;

// =============================================================================
// ENHANCED TRACE TYPES (Maximum Interpretability)
// =============================================================================

/**
 * LLM thinking/reasoning block.
 * Captures the "thought process" from models that support thinking (e.g., Claude's extended thinking).
 */
export interface ThinkingBlock {
  /** Unique ID for this thinking block */
  id: string;

  /** The thinking content */
  content: string;

  /** Estimated tokens for thinking */
  estimatedTokens: number;

  /** Whether this thinking was summarized (for long thinking blocks) */
  summarized: boolean;

  /** If summarized, the original length */
  originalLength?: number;

  /** Timestamp when thinking started */
  startTime: number;

  /** Duration of thinking in ms */
  durationMs?: number;
}

/**
 * Memory retrieval trace.
 * Captures what memories/context was retrieved and how it influenced the response.
 */
export interface MemoryRetrievalTrace {
  /** Unique retrieval ID */
  retrievalId: string;

  /** Parent trace ID */
  traceId: string;

  /** Query used for retrieval */
  query: string;

  /** Type of memory being retrieved */
  memoryType: 'conversation' | 'semantic' | 'episodic' | 'procedural' | 'external';

  /** Retrieved memories with relevance scores */
  results: Array<{
    /** Memory ID */
    id: string;
    /** Memory content (may be truncated) */
    content: string;
    /** Relevance score (0-1) */
    relevance: number;
    /** Source of this memory */
    source?: string;
    /** When this memory was created */
    createdAt?: number;
  }>;

  /** Total memories considered */
  totalConsidered: number;

  /** Retrieval duration in ms */
  durationMs: number;

  /** Timestamp */
  timestamp: number;
}

/**
 * Plan evolution trace.
 * Tracks how the agent's plan changes over time.
 */
export interface PlanEvolutionTrace {
  /** Plan version (increments with each change) */
  version: number;

  /** Parent trace ID */
  traceId: string;

  /** Current plan state */
  plan: {
    /** Plan goal/objective */
    goal: string;
    /** Current steps */
    steps: Array<{
      id: string;
      description: string;
      status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';
      dependencies?: string[];
    }>;
    /** Overall progress (0-1) */
    progress: number;
  };

  /** What changed from previous version */
  change?: {
    /** Type of change */
    type: 'created' | 'step_added' | 'step_removed' | 'step_modified' | 'step_completed' | 'step_failed' | 'replanned';
    /** Reason for change */
    reason: string;
    /** Affected step IDs */
    affectedSteps?: string[];
    /** Previous state (for diffs) */
    previousState?: string;
  };

  /** Timestamp */
  timestamp: number;
}

/**
 * Subagent trace link.
 * Correlates parent and child agent traces.
 */
export interface SubagentTraceLink {
  /** Parent agent's trace ID */
  parentTraceId: string;

  /** Parent agent's session ID */
  parentSessionId: string;

  /** Child agent's trace ID */
  childTraceId: string;

  /** Child agent's session ID */
  childSessionId: string;

  /** Child agent configuration */
  childConfig: {
    /** Agent type/role */
    agentType: string;
    /** Model used */
    model: string;
    /** Task given to child */
    task: string;
    /** Tool access */
    tools?: string[];
  };

  /** Spawn context */
  spawnContext: {
    /** Why this subagent was spawned */
    reason: string;
    /** Expected outcome */
    expectedOutcome?: string;
    /** Iteration in parent when spawned */
    parentIteration: number;
  };

  /** Result summary */
  result?: {
    /** Whether child completed successfully */
    success: boolean;
    /** Brief summary of result */
    summary: string;
    /** Tokens used by child */
    tokensUsed: number;
    /** Duration of child execution */
    durationMs: number;
  };

  /** Timestamp when spawned */
  spawnedAt: number;

  /** Timestamp when completed */
  completedAt?: number;
}

/**
 * Decision trace.
 * Captures why specific decisions were made.
 */
export interface DecisionTrace {
  /** Unique decision ID */
  decisionId: string;

  /** Parent trace ID */
  traceId: string;

  /** Type of decision */
  type: 'routing' | 'tool_selection' | 'policy' | 'plan_choice' | 'model_selection' | 'retry' | 'escalation';

  /** The decision made */
  decision: string;

  /** Outcome/result of decision */
  outcome: 'allowed' | 'blocked' | 'modified' | 'deferred' | 'escalated';

  /** Reasoning behind decision */
  reasoning: string;

  /** Factors that influenced this decision */
  factors: Array<{
    name: string;
    value: string | number | boolean;
    weight?: number;
  }>;

  /** Alternatives that were considered */
  alternatives?: Array<{
    option: string;
    reason: string;
    rejected: boolean;
  }>;

  /** Confidence in decision (0-1) */
  confidence?: number;

  /** Timestamp */
  timestamp: number;
}

/**
 * Full content trace (optional, for debugging).
 * Stores complete content that would otherwise be truncated.
 */
export interface FullContentTrace {
  /** Reference ID (links to truncated version) */
  referenceId: string;

  /** Content type */
  contentType: 'prompt' | 'response' | 'tool_result' | 'thinking';

  /** Full content (may be compressed) */
  content: string;

  /** Whether content is compressed */
  compressed: boolean;

  /** Original size in bytes */
  originalSize: number;

  /** Redactions applied */
  redactions?: Array<{
    pattern: string;
    count: number;
  }>;
}

// =============================================================================
// ENHANCED JSONL ENTRY TYPES
// =============================================================================

/**
 * Thinking block entry.
 */
export interface ThinkingEntry extends BaseJSONLEntry {
  _type: 'llm.thinking';
  requestId: string;
  thinking: ThinkingBlock;
}

/**
 * Memory retrieval entry.
 */
export interface MemoryRetrievalEntry extends BaseJSONLEntry {
  _type: 'memory.retrieval';
  retrieval: MemoryRetrievalTrace;
}

/**
 * Plan evolution entry.
 */
export interface PlanEvolutionEntry extends BaseJSONLEntry {
  _type: 'plan.evolution';
  evolution: PlanEvolutionTrace;
}

/**
 * Subagent link entry.
 */
export interface SubagentLinkEntry extends BaseJSONLEntry {
  _type: 'subagent.link';
  link: SubagentTraceLink;
}

/**
 * Decision entry.
 */
export interface DecisionEntry extends BaseJSONLEntry {
  _type: 'decision';
  decision: DecisionTrace;
}

/**
 * Iteration wrapper entry - groups events within a single iteration.
 */
export interface IterationWrapperEntry extends BaseJSONLEntry {
  _type: 'iteration.wrapper';
  iterationNumber: number;
  phase: 'start' | 'end';
  metrics?: {
    inputTokens: number;
    outputTokens: number;
    cacheHitRate: number;
    toolCallCount: number;
    totalCost: number;
    thinkingTokens?: number;
  };
}

// =============================================================================
// ENHANCED TRACE CONFIGURATION
// =============================================================================

/**
 * Enhanced configuration for trace collection with maximum interpretability.
 */
export interface EnhancedTraceConfig {
  /** Base tracing enabled */
  enabled: boolean;

  /** Verbosity level */
  verbosity: 'minimal' | 'standard' | 'full' | 'debug';

  /** Capture LLM thinking/reasoning blocks */
  captureThinking: boolean;

  /** Capture memory retrieval events */
  captureMemoryRetrieval: boolean;

  /** Capture plan evolution */
  capturePlanEvolution: boolean;

  /** Capture full content (prompts, responses, results) */
  captureFullContent: boolean;

  /** Capture decision traces */
  captureDecisions: boolean;

  /** Capture subagent links */
  captureSubagentLinks: boolean;

  /** Compression settings */
  compression: {
    enabled: boolean;
    /** Compress content larger than this (bytes) */
    threshold: number;
  };

  /** Privacy settings */
  privacy: {
    enabled: boolean;
    /** Patterns to redact */
    patterns: RegExp[];
  };

  /** Output directory for traces */
  outputDir: string;

  /** JSONL file name pattern */
  filePattern: string;

  /** Max result size before truncation */
  maxResultSize: number;

  /** Enable cache boundary analysis */
  analyzeCacheBoundaries: boolean;
}

/**
 * Default enhanced trace configuration.
 */
export const DEFAULT_ENHANCED_TRACE_CONFIG: EnhancedTraceConfig = {
  enabled: true,
  verbosity: 'standard',
  captureThinking: true,
  captureMemoryRetrieval: true,
  capturePlanEvolution: true,
  captureFullContent: false,
  captureDecisions: true,
  captureSubagentLinks: true,
  compression: {
    enabled: true,
    threshold: 50000, // 50KB
  },
  privacy: {
    enabled: false,
    patterns: [],
  },
  outputDir: '.traces',
  filePattern: 'trace-{sessionId}-{timestamp}.jsonl',
  maxResultSize: 10000,
  analyzeCacheBoundaries: true,
};

// =============================================================================
// TRACE SUMMARY TYPES (for LLM analysis)
// =============================================================================

/**
 * Structured summary of a trace session for LLM analysis.
 * Designed to fit within ~4000 tokens for efficient analysis.
 */
export interface TraceSummary {
  /** Session metadata */
  meta: {
    sessionId: string;
    task: string;
    model: string;
    duration: number;
    status: 'running' | 'completed' | 'failed' | 'cancelled';
    timestamp: number;
  };

  /** Aggregated metrics */
  metrics: {
    iterations: number;
    totalTokens: number;
    inputTokens: number;
    outputTokens: number;
    thinkingTokens?: number;
    cacheHitRate: number;
    cost: number;
    costSaved: number;
    toolCalls: number;
    uniqueTools: number;
    errors: number;
  };

  /** Key decision points */
  decisionPoints: Array<{
    iteration: number;
    type: DecisionTrace['type'];
    decision: string;
    outcome: DecisionTrace['outcome'];
    brief: string;
  }>;

  /** Detected anomalies */
  anomalies: Array<{
    type: 'excessive_iterations' | 'cache_inefficiency' | 'redundant_tool_calls' | 'error_loop' | 'plan_thrashing' | 'memory_miss' | 'slow_tool' | 'token_spike';
    severity: 'low' | 'medium' | 'high' | 'critical';
    description: string;
    evidence: string;
    iteration?: number;
  }>;

  /** Tool usage patterns */
  toolPatterns: {
    /** Frequency of each tool */
    frequency: Record<string, number>;
    /** Redundant calls (same args, same result) */
    redundantCalls: Array<{
      tool: string;
      count: number;
      iterations: number[];
    }>;
    /** Slow tools */
    slowTools: Array<{
      tool: string;
      avgDuration: number;
      maxDuration: number;
    }>;
  };

  /** Per-iteration summaries */
  iterationSummaries: Array<{
    number: number;
    action: string;
    outcome: 'success' | 'partial' | 'failure';
    tokensUsed: number;
    flags: string[];
  }>;

  /** Code location mapping (for fixes) */
  codeLocations: Array<{
    component: string;
    file: string;
    relevance: 'primary' | 'secondary' | 'related';
    description: string;
  }>;
}

/**
 * Analysis result from LLM.
 */
export interface TraceAnalysisResult {
  /** Overall efficiency score (0-100) */
  efficiencyScore: number;

  /** Issues identified */
  issues: Array<{
    id: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    category: string;
    description: string;
    evidence: string;
    suggestedFix?: string;
    codeLocations?: string[];
  }>;

  /** Recommendations */
  recommendations: Array<{
    priority: number;
    recommendation: string;
    expectedImprovement: string;
    effort: 'low' | 'medium' | 'high';
  }>;

  /** Root cause analysis (if applicable) */
  rootCause?: {
    summary: string;
    chain: string[];
    ultimateCause: string;
  };

  /** Comparison notes (if comparing sessions) */
  comparison?: {
    baseline: string;
    improved: string[];
    regressed: string[];
    neutral: string[];
  };
}

// =============================================================================
// BENCHMARK TYPES
// =============================================================================

/**
 * Validation result from outcome checker.
 */
export interface ValidationResult {
  /** Whether validation passed */
  passed: boolean;

  /** Score (0-1) for partial credit */
  score: number;

  /** Human-readable message */
  message: string;

  /** Detailed output */
  details?: string;
}

/**
 * Sandbox interface for benchmark execution.
 */
export interface BenchmarkSandbox {
  /** Sandbox directory path */
  path: string;

  /** Read a file from sandbox */
  readFile(relativePath: string): Promise<string>;

  /** Check if file exists */
  exists(relativePath: string): Promise<boolean>;

  /** Run a command in sandbox (uses execFile internally for safety) */
  run(command: string, args: string[], options?: { timeout?: number }): Promise<{ stdout: string; stderr: string; exitCode: number }>;

  /** List files matching pattern */
  glob(pattern: string): Promise<string[]>;

  /** Clean up sandbox */
  cleanup(): Promise<void>;
}

/**
 * Expected outcome for a benchmark task.
 */
export type ExpectedOutcome =
  | { type: 'test_pass'; testCommand: string; testArgs?: string[]; testFile?: string }
  | { type: 'file_match'; filePath: string; pattern: RegExp | string }
  | { type: 'file_contains'; filePath: string; content: string[] }
  | { type: 'file_not_contains'; filePath: string; content: string[] }
  | { type: 'custom'; validator: (sandbox: BenchmarkSandbox) => Promise<ValidationResult> };

/**
 * A benchmark task definition.
 */
export interface BenchmarkTask {
  /** Unique task ID */
  id: string;

  /** Human-readable name */
  name: string;

  /** Task category */
  category: 'function-completion' | 'bug-fixing' | 'file-editing' | 'multi-file';

  /** Difficulty level */
  difficulty: 'easy' | 'medium' | 'hard';

  /** The prompt given to the agent */
  prompt: string;

  /** Files to set up before running */
  setupFiles?: Record<string, string>;

  /** Commands to run for setup (command and args) */
  setupCommands?: Array<{ command: string; args: string[] }>;

  /** Expected outcome definition */
  expectedOutcome: ExpectedOutcome;

  /** Maximum time allowed (ms) */
  timeout: number;

  /** Maximum iterations allowed */
  maxIterations?: number;

  /** Tags for filtering */
  tags?: string[];

  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * A suite of benchmark tasks.
 */
export interface BenchmarkSuite {
  /** Suite ID */
  id: string;

  /** Suite name */
  name: string;

  /** Suite description */
  description: string;

  /** Tasks in this suite */
  tasks: BenchmarkTask[];

  /** Suite-level setup */
  setup?: {
    files?: Record<string, string>;
    commands?: Array<{ command: string; args: string[] }>;
  };

  /** Suite metadata */
  metadata?: Record<string, unknown>;
}

// =============================================================================
// EVALUATION RESULT TYPES
// =============================================================================

/**
 * Result of running a single benchmark task.
 */
export interface TaskResult {
  /** Task ID */
  taskId: string;

  /** Run ID */
  runId: string;

  /** Whether task passed */
  passed: boolean;

  /** Score (0-1) */
  score: number;

  /** Number of iterations used */
  iterations: number;

  /** Total tokens consumed */
  totalTokens: number;

  /** Estimated cost */
  cost: number;

  /** Duration in ms */
  durationMs: number;

  /** Validation result */
  validation: ValidationResult;

  /** Session trace (if captured) */
  trace?: SessionTrace;

  /** Error if task failed */
  error?: string;

  /** Timestamp */
  timestamp: number;
}

/**
 * Aggregated results for a benchmark suite.
 */
export interface SuiteResult {
  /** Suite ID */
  suiteId: string;

  /** Run ID */
  runId: string;

  /** Model used */
  model: string;

  /** When run started */
  startTime: number;

  /** When run ended */
  endTime: number;

  /** Total duration */
  durationMs: number;

  /** Individual task results */
  taskResults: TaskResult[];

  /** Aggregated metrics */
  metrics: {
    /** Pass@1 rate (first attempt success) */
    passAt1: number;

    /** Total tasks */
    totalTasks: number;

    /** Passed tasks */
    passedTasks: number;

    /** Failed tasks */
    failedTasks: number;

    /** Average iterations per task */
    avgIterations: number;

    /** Average tokens per task */
    avgTokens: number;

    /** Average cost per task */
    avgCost: number;

    /** Total cost */
    totalCost: number;

    /** By category breakdown */
    byCategory: Record<string, { passed: number; total: number; passRate: number }>;

    /** By difficulty breakdown */
    byDifficulty: Record<string, { passed: number; total: number; passRate: number }>;
  };

  /** Configuration used */
  config: {
    model: string;
    maxIterations: number;
    timeout: number;
    parallel: boolean;
  };

  /** Run metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Comparison between two benchmark runs.
 */
export interface RunComparison {
  /** Baseline run ID */
  baselineRunId: string;

  /** Comparison run ID */
  comparisonRunId: string;

  /** Baseline metrics */
  baseline: SuiteResult['metrics'];

  /** Comparison metrics */
  comparison: SuiteResult['metrics'];

  /** Differences */
  diff: {
    passAt1: number;
    avgIterations: number;
    avgTokens: number;
    avgCost: number;
    totalCost: number;
  };

  /** Percentage changes */
  percentChange: {
    passAt1: number;
    avgIterations: number;
    avgTokens: number;
    avgCost: number;
  };

  /** Task-level regressions */
  regressions: Array<{
    taskId: string;
    baselinePassed: boolean;
    comparisonPassed: boolean;
    message: string;
  }>;

  /** Task-level improvements */
  improvements: Array<{
    taskId: string;
    baselinePassed: boolean;
    comparisonPassed: boolean;
    message: string;
  }>;
}

// =============================================================================
// CONFIGURATION TYPES
// =============================================================================

/**
 * Configuration for trace collection.
 */
export interface TraceCollectorConfig {
  /** Enable trace collection */
  enabled: boolean;

  /** Capture full message content (can be large) */
  captureMessageContent: boolean;

  /** Capture tool results (can be large) */
  captureToolResults: boolean;

  /** Max result size before truncation */
  maxResultSize: number;

  /** Enable cache boundary analysis */
  analyzeCacheBoundaries: boolean;

  /** Output directory for traces */
  outputDir: string;

  /** JSONL file name pattern */
  filePattern: string;

  /** Enable console output for traces */
  enableConsoleOutput?: boolean;
}

/**
 * Default trace collector configuration.
 */
export const DEFAULT_TRACE_CONFIG: TraceCollectorConfig = {
  enabled: true,
  captureMessageContent: true,
  captureToolResults: true,
  maxResultSize: 10000,
  analyzeCacheBoundaries: true,
  outputDir: '.traces',
  filePattern: 'trace-{sessionId}-{timestamp}.jsonl',
};

/**
 * Configuration for benchmark runner.
 */
export interface BenchmarkRunnerConfig {
  /** Model to use */
  model: string;

  /** Maximum iterations per task */
  maxIterations: number;

  /** Default timeout (ms) */
  timeout: number;

  /** Run tasks in parallel */
  parallel: boolean;

  /** Maximum parallel tasks */
  maxParallel: number;

  /** Enable tracing */
  enableTracing: boolean;

  /** Output directory for results */
  outputDir: string;

  /** Retry failed tasks */
  retryFailed: boolean;

  /** Max retries */
  maxRetries: number;
}

/**
 * Default benchmark runner configuration.
 */
export const DEFAULT_BENCHMARK_CONFIG: BenchmarkRunnerConfig = {
  model: 'claude-3-sonnet',
  maxIterations: 10,
  timeout: 120000,
  parallel: false,
  maxParallel: 4,
  enableTracing: true,
  outputDir: '.eval-results',
  retryFailed: false,
  maxRetries: 1,
};
