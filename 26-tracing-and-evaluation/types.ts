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

import type { Span, AgentMetrics, SpanAttributeValue } from '../19-observability/types.js';

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
}

/**
 * Session start entry.
 */
export interface SessionStartEntry extends BaseJSONLEntry {
  _type: 'session.start';
  sessionId: string;
  task: string;
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

/**
 * Union of all JSONL entry types.
 */
export type JSONLEntry =
  | SessionStartEntry
  | SessionEndEntry
  | LLMRequestEntry
  | LLMResponseEntry
  | ToolExecutionEntry
  | ErrorEntry;

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
