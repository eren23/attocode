/**
 * Trace Viewer Types
 *
 * Types for parsing, analyzing, and visualizing trace data.
 */

// =============================================================================
// PARSED TYPES
// =============================================================================

/**
 * Parsed trace event (after reading from JSONL).
 */
export interface ParsedEvent {
  /** Event type discriminator */
  type: string;
  /** Event timestamp */
  timestamp: Date;
  /** Trace ID for correlation */
  traceId: string;
  /** Raw event data */
  data: Record<string, unknown>;
}

/**
 * Parsed iteration with all contained events.
 */
export interface ParsedIteration {
  /** Iteration number */
  number: number;
  /** Start timestamp */
  startTime: Date;
  /** End timestamp */
  endTime?: Date;
  /** Duration in ms */
  durationMs?: number;
  /** LLM request/response */
  llm?: {
    requestId: string;
    model: string;
    inputTokens: number;
    outputTokens: number;
    cacheHitRate: number;
    durationMs: number;
    content: string;
    toolCalls: Array<{
      id: string;
      name: string;
      arguments: Record<string, unknown>;
    }>;
  };
  /** Thinking content if captured */
  thinking?: {
    content: string;
    estimatedTokens: number;
    summarized: boolean;
  };
  /** Tool executions in this iteration */
  tools: Array<{
    executionId: string;
    name: string;
    arguments: Record<string, unknown>;
    durationMs: number;
    status: 'success' | 'error' | 'timeout' | 'blocked';
    resultSize?: number;
    /** Tool input arguments (truncated) */
    input?: Record<string, unknown>;
    /** Preview of the output (truncated) */
    outputPreview?: string;
    /** Error message if status is error */
    errorMessage?: string;
  }>;
  /** Decisions made in this iteration */
  decisions: Array<{
    type: string;
    decision: string;
    outcome: string;
    reasoning: string;
  }>;
  /** Metrics for this iteration */
  metrics: {
    inputTokens: number;
    outputTokens: number;
    cacheHitRate: number;
    toolCallCount: number;
    cost: number;
  };
}

/**
 * Parsed task within a terminal session.
 * A terminal session can contain multiple tasks (user prompts).
 */
export interface ParsedTask {
  /** Task ID */
  taskId: string;
  /** Task number within session (1-indexed) */
  taskNumber: number;
  /** User prompt */
  prompt: string;
  /** Task start time */
  startTime: Date;
  /** Task end time */
  endTime?: Date;
  /** Duration in ms */
  durationMs?: number;
  /** Task status */
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  /** Iterations within this task */
  iterations: ParsedIteration[];
  /** Task-level metrics */
  metrics: {
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
 * Parsed session with all iterations and metadata.
 */
export interface ParsedSession {
  /** Session ID */
  sessionId: string;
  /** Trace ID */
  traceId: string;
  /** Task/prompt (for single-task sessions, or empty for terminal sessions) */
  task: string;
  /** Model used */
  model: string;
  /** Session start time */
  startTime: Date;
  /** Session end time */
  endTime?: Date;
  /** Total duration in ms */
  durationMs?: number;
  /** Session status */
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  /** Tasks within this session (for terminal sessions with multiple prompts) */
  tasks: ParsedTask[];
  /** All iterations (aggregated from all tasks, or direct if no tasks) */
  iterations: ParsedIteration[];
  /** Subagent links */
  subagentLinks: Array<{
    childSessionId: string;
    agentType: string;
    task: string;
    success?: boolean;
    tokensUsed?: number;
    durationMs?: number;
  }>;
  /** Memory retrievals */
  memoryRetrievals: Array<{
    query: string;
    memoryType: string;
    resultCount: number;
    durationMs: number;
  }>;
  /** Plan evolutions */
  planEvolutions: Array<{
    version: number;
    changeType?: string;
    progress: number;
    stepCount: number;
  }>;
  /** Errors */
  errors: Array<{
    code: string;
    message: string;
    context: string;
    recoverable: boolean;
    timestamp: Date;
  }>;
  /** Aggregated metrics */
  metrics: SessionMetrics;
}

/**
 * Session-level aggregated metrics.
 */
export interface SessionMetrics {
  /** Total iterations */
  iterations: number;
  /** Total LLM calls */
  llmCalls: number;
  /** Total tool calls */
  toolCalls: number;
  /** Unique tools used */
  uniqueTools: number;
  /** Total input tokens */
  inputTokens: number;
  /** Total output tokens */
  outputTokens: number;
  /** Total thinking tokens (if captured) */
  thinkingTokens?: number;
  /** Average cache hit rate */
  avgCacheHitRate: number;
  /** Tokens saved by cache */
  tokensSavedByCache: number;
  /** Total cost */
  totalCost: number;
  /** Cost saved by cache */
  costSavedByCache: number;
  /** Total errors */
  errors: number;
  /** Subagent spawns */
  subagentSpawns: number;
  /** Decision count */
  decisions: number;
}

// =============================================================================
// ANALYSIS TYPES
// =============================================================================

/**
 * Detected inefficiency in a session.
 */
export interface Inefficiency {
  /** Unique ID */
  id: string;
  /** Type of inefficiency */
  type:
    | 'excessive_iterations'
    | 'cache_inefficiency'
    | 'redundant_tool_calls'
    | 'error_loop'
    | 'plan_thrashing'
    | 'memory_miss'
    | 'slow_tool'
    | 'token_spike'
    | 'thinking_overhead';
  /** Severity level */
  severity: 'low' | 'medium' | 'high' | 'critical';
  /** Human-readable description */
  description: string;
  /** Evidence supporting this finding */
  evidence: string;
  /** Affected iterations */
  iterations?: number[];
  /** Suggested fix */
  suggestedFix?: string;
  /** Code locations relevant to fix */
  codeLocations?: Array<{
    file: string;
    component: string;
    relevance: 'primary' | 'secondary' | 'related';
  }>;
}

/**
 * Token flow analysis for a session.
 */
export interface TokenFlowAnalysis {
  /** Per-iteration token breakdown */
  perIteration: Array<{
    iteration: number;
    input: number;
    output: number;
    thinking?: number;
    cached: number;
    fresh: number;
  }>;
  /** Cumulative totals */
  cumulative: Array<{
    iteration: number;
    totalInput: number;
    totalOutput: number;
    totalCached: number;
  }>;
  /** Token cost breakdown */
  costBreakdown: {
    inputCost: number;
    outputCost: number;
    cachedCost: number;
    totalCost: number;
    savings: number;
  };
}

/**
 * Cache efficiency analysis.
 */
export interface CacheAnalysis {
  /** Overall hit rate */
  overallHitRate: number;
  /** Per-iteration hit rates */
  perIteration: Array<{
    iteration: number;
    hitRate: number;
    cacheRead: number;
    cacheWrite: number;
    fresh: number;
  }>;
  /** Identified cache breakpoints */
  breakpoints: Array<{
    iteration: number;
    reason: string;
    tokensAffected: number;
  }>;
  /** Recommendations */
  recommendations: string[];
}

/**
 * Cost analysis for a session.
 */
export interface CostAnalysis {
  /** Total cost */
  total: number;
  /** Per-iteration costs */
  perIteration: Array<{
    iteration: number;
    cost: number;
    breakdown: {
      input: number;
      output: number;
      cached: number;
    };
  }>;
  /** Cost by component */
  byComponent: {
    llmCalls: number;
    toolExecutions: number; // Estimated
    subagents: number;
  };
  /** Potential savings */
  potentialSavings: {
    withBetterCaching: number;
    withFewerIterations: number;
    withSmallerPrompts: number;
  };
}

// =============================================================================
// VIEW TYPES
// =============================================================================

/**
 * Timeline entry for chronological view.
 */
export interface TimelineEntry {
  /** Entry timestamp */
  timestamp: Date;
  /** Relative time from session start (ms) */
  relativeMs: number;
  /** Event type */
  type: string;
  /** Brief description */
  description: string;
  /** Duration if applicable */
  durationMs?: number;
  /** Associated iteration */
  iteration?: number;
  /** Severity/importance */
  importance: 'low' | 'normal' | 'high';
  /** Additional details */
  details?: Record<string, unknown>;
}

/**
 * Tree node for hierarchical view.
 */
export interface TreeNode {
  /** Node ID */
  id: string;
  /** Node type */
  type: 'session' | 'iteration' | 'llm' | 'tool' | 'decision' | 'subagent' | 'error';
  /** Node label */
  label: string;
  /** Duration in ms */
  durationMs?: number;
  /** Status */
  status?: 'success' | 'error' | 'pending';
  /** Children nodes */
  children: TreeNode[];
  /** Metrics for this node */
  metrics?: Record<string, number>;
}

/**
 * Summary section for quick overview.
 */
export interface SummarySection {
  /** Section title */
  title: string;
  /** Key-value items */
  items: Array<{
    label: string;
    value: string | number;
    status?: 'good' | 'warn' | 'bad';
  }>;
}

// =============================================================================
// OUTPUT TYPES
// =============================================================================

/**
 * Output format options.
 */
export type OutputFormat = 'terminal' | 'html' | 'json';

/**
 * View mode options.
 */
export type ViewMode = 'summary' | 'timeline' | 'tree' | 'tokens' | 'all';

/**
 * CLI options.
 */
export interface CLIOptions {
  /** Trace file or directory path */
  path: string;
  /** View mode */
  view: ViewMode;
  /** Output format */
  output: OutputFormat;
  /** Output file path (for html/json) */
  outFile?: string;
  /** Run analysis */
  analyze: boolean;
  /** Verbose output */
  verbose: boolean;
  /** Filter by session ID */
  sessionId?: string;
  /** Filter by date range */
  since?: Date;
  /** Filter by date range */
  until?: Date;
}

/**
 * Comparison result between two sessions.
 */
export interface SessionComparison {
  /** Baseline session ID */
  baselineId: string;
  /** Comparison session ID */
  comparisonId: string;
  /** Metric differences */
  metricDiffs: {
    iterations: number;
    tokens: number;
    cost: number;
    cacheHitRate: number;
    errors: number;
  };
  /** Percentage changes */
  percentChanges: {
    iterations: number;
    tokens: number;
    cost: number;
    cacheHitRate: number;
  };
  /** Regressions */
  regressions: string[];
  /** Improvements */
  improvements: string[];
  /** Overall assessment */
  assessment: 'improved' | 'regressed' | 'mixed' | 'similar';
}
