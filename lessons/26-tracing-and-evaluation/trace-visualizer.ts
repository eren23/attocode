/**
 * Lesson 26: Trace Visualizer
 *
 * Formats session traces as human-readable tree views.
 * Useful for debugging and understanding agent behavior.
 *
 * @example
 * ```typescript
 * const visualizer = new TraceVisualizer();
 * console.log(visualizer.formatSession(sessionTrace));
 *
 * // Output:
 * // Session: abc123 (completed)
 * // Task: Write a fizzbuzz function
 * // Model: claude-3-sonnet
 * // Duration: 5432ms | Cost: $0.0234
 * //
 * // ✓ Iteration 1 (2100ms)
 * //    ├── LLM Request
 * //    │   ├── Messages: 3
 * //    │   ├── Tokens: 1500 in / 200 out
 * //    │   └── Cache: 78% hit rate
 * //    └── ✓ write_file (150ms)
 * ```
 */

import type {
  SessionTrace,
  IterationTrace,
  LLMRequestTrace,
  ToolExecutionTrace,
  CacheBreakdown,
  TokenBreakdown,
} from './types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Visualization options.
 */
export interface VisualizationOptions {
  /** Use colors in output */
  colors: boolean;

  /** Show token details */
  showTokens: boolean;

  /** Show cache details */
  showCache: boolean;

  /** Show tool arguments */
  showToolArgs: boolean;

  /** Show tool results (truncated) */
  showToolResults: boolean;

  /** Max result length to show */
  maxResultLength: number;

  /** Indent string */
  indent: string;

  /** Show timestamps */
  showTimestamps: boolean;
}

/**
 * Default visualization options.
 */
export const DEFAULT_VIZ_OPTIONS: VisualizationOptions = {
  colors: true,
  showTokens: true,
  showCache: true,
  showToolArgs: false,
  showToolResults: false,
  maxResultLength: 100,
  indent: '   ',
  showTimestamps: false,
};

// =============================================================================
// COLORS
// =============================================================================

const COLORS = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
};

// =============================================================================
// TRACE VISUALIZER
// =============================================================================

/**
 * Formats traces for human-readable display.
 */
export class TraceVisualizer {
  private options: VisualizationOptions;

  constructor(options: Partial<VisualizationOptions> = {}) {
    this.options = { ...DEFAULT_VIZ_OPTIONS, ...options };
  }

  /**
   * Format a complete session trace.
   */
  formatSession(trace: SessionTrace): string {
    const lines: string[] = [];

    // Header
    lines.push(this.formatHeader(trace));
    lines.push('');

    // Iterations
    for (const iteration of trace.iterations) {
      lines.push(this.formatIteration(iteration));
      lines.push('');
    }

    // Summary
    lines.push(this.formatSummary(trace));

    return lines.join('\n');
  }

  /**
   * Format session header.
   */
  formatHeader(trace: SessionTrace): string {
    const lines: string[] = [];

    const statusIcon = this.getStatusIcon(trace.status);
    const statusColor = trace.status === 'completed' ? 'green' : trace.status === 'failed' ? 'red' : 'yellow';

    lines.push(this.color('bold', `Session: ${trace.sessionId}`) + ` ${this.color(statusColor, `(${trace.status})`)}`);
    lines.push(this.color('dim', `Task: ${this.truncate(trace.task, 80)}`));
    lines.push(this.color('dim', `Model: ${trace.model}`));
    lines.push(this.color('dim', `Duration: ${this.formatDuration(trace.durationMs ?? 0)} | Cost: ${this.formatCost(trace.metrics.estimatedCost)}`));

    if (this.options.showTimestamps) {
      lines.push(this.color('dim', `Started: ${new Date(trace.startTime).toISOString()}`));
    }

    return lines.join('\n');
  }

  /**
   * Format a single iteration.
   */
  formatIteration(iteration: IterationTrace): string {
    const lines: string[] = [];

    // Iteration header
    const statusIcon = this.getIterationStatusIcon(iteration);
    const header = `${statusIcon} Iteration ${iteration.iterationNumber} (${this.formatDuration(iteration.durationMs)})`;
    lines.push(this.color('bold', header));

    const indent = this.options.indent;

    // LLM Request
    if (iteration.llmRequest) {
      lines.push(this.formatLLMRequest(iteration.llmRequest, indent));
    }

    // Tool executions
    for (let i = 0; i < iteration.toolExecutions.length; i++) {
      const tool = iteration.toolExecutions[i];
      const isLast = i === iteration.toolExecutions.length - 1;
      lines.push(this.formatToolExecution(tool, indent, isLast));
    }

    return lines.join('\n');
  }

  /**
   * Format LLM request details.
   */
  formatLLMRequest(request: LLMRequestTrace, indent: string): string {
    const lines: string[] = [];
    const prefix = '├── ';
    const childPrefix = '│   ';

    lines.push(`${indent}${prefix}${this.color('cyan', 'LLM Request')}`);

    // Messages
    lines.push(`${indent}${childPrefix}├── Messages: ${request.request.messages.length}`);

    // Tokens
    if (this.options.showTokens) {
      const tokensStr = `${request.tokens.input.toLocaleString()} in / ${request.tokens.output.toLocaleString()} out`;
      lines.push(`${indent}${childPrefix}├── Tokens: ${tokensStr}`);
    }

    // Cache
    if (this.options.showCache) {
      const cacheStr = this.formatCacheInfo(request.cache);
      lines.push(`${indent}${childPrefix}├── Cache: ${cacheStr}`);
    }

    // Stop reason
    const stopReasonColor = request.response.stopReason === 'tool_use' ? 'yellow' : 'green';
    lines.push(`${indent}${childPrefix}└── Stop: ${this.color(stopReasonColor, request.response.stopReason)}`);

    return lines.join('\n');
  }

  /**
   * Format tool execution.
   */
  formatToolExecution(tool: ToolExecutionTrace, indent: string, isLast: boolean): string {
    const lines: string[] = [];
    const prefix = isLast ? '└── ' : '├── ';
    const childPrefix = isLast ? '    ' : '│   ';

    // Tool name with status
    const statusIcon = tool.status === 'success' ? this.color('green', '✓') :
                       tool.status === 'error' ? this.color('red', '✗') :
                       tool.status === 'blocked' ? this.color('yellow', '⊘') :
                       this.color('gray', '○');

    const durationStr = this.formatDuration(tool.durationMs);
    lines.push(`${indent}${prefix}${statusIcon} ${this.color('magenta', tool.toolName)} (${durationStr})`);

    // Arguments
    if (this.options.showToolArgs && Object.keys(tool.arguments).length > 0) {
      const argsStr = this.formatObject(tool.arguments);
      lines.push(`${indent}${childPrefix}├── Args: ${argsStr}`);
    }

    // Result
    if (this.options.showToolResults && tool.result) {
      const resultStr = this.truncate(String(tool.result.value), this.options.maxResultLength);
      lines.push(`${indent}${childPrefix}└── Result: ${resultStr}`);
    }

    // Error
    if (tool.error) {
      lines.push(`${indent}${childPrefix}└── ${this.color('red', `Error: ${tool.error.message}`)}`);
    }

    return lines.join('\n');
  }

  /**
   * Format session summary.
   */
  formatSummary(trace: SessionTrace): string {
    const lines: string[] = [];
    const m = trace.metrics;

    lines.push(this.color('bold', '─'.repeat(50)));
    lines.push(this.color('bold', 'Summary'));
    lines.push(`  Iterations: ${trace.iterations.length}`);
    lines.push(`  LLM Calls: ${m.llmCalls}`);
    lines.push(`  Tool Calls: ${m.toolCalls}`);
    lines.push(`  Total Tokens: ${(m.inputTokens + m.outputTokens).toLocaleString()}`);
    lines.push(`  Avg Cache Hit: ${(m.avgCacheHitRate * 100).toFixed(1)}%`);
    lines.push(`  Cost Saved: ${this.formatCost(m.costSavedByCache)}`);
    lines.push(`  Total Cost: ${this.formatCost(m.estimatedCost)}`);

    if (trace.result) {
      const resultIcon = trace.result.success ? this.color('green', '✓') : this.color('red', '✗');
      lines.push(`  Result: ${resultIcon} ${trace.result.success ? 'Success' : trace.result.failureReason ?? 'Failed'}`);
    }

    return lines.join('\n');
  }

  /**
   * Format cache information.
   */
  formatCacheInfo(cache: CacheBreakdown): string {
    const hitRate = (cache.hitRate * 100).toFixed(0);
    const hitRateColor = cache.hitRate > 0.7 ? 'green' : cache.hitRate > 0.4 ? 'yellow' : 'red';
    return this.color(hitRateColor, `${hitRate}% hit rate`) +
           ` (${cache.cacheReadTokens.toLocaleString()} cached)`;
  }

  /**
   * Format a compact iteration list.
   */
  formatIterationList(trace: SessionTrace): string {
    const lines: string[] = [];

    for (const iter of trace.iterations) {
      const statusIcon = this.getIterationStatusIcon(iter);
      const tokens = iter.metrics.inputTokens + iter.metrics.outputTokens;
      const tools = iter.toolExecutions.map(t => t.toolName).join(', ') || 'none';

      lines.push(
        `${statusIcon} Iter ${iter.iterationNumber}: ` +
        `${tokens.toLocaleString()} tok, ` +
        `${iter.toolExecutions.length} tools (${tools}), ` +
        `${this.formatDuration(iter.durationMs)}`
      );
    }

    return lines.join('\n');
  }

  /**
   * Format token breakdown.
   */
  formatTokenBreakdown(tokens: TokenBreakdown): string {
    const lines: string[] = [];

    lines.push(`Token Breakdown:`);
    lines.push(`  System Prompt: ${tokens.breakdown.systemPrompt.toLocaleString()}`);
    lines.push(`  Messages: ${tokens.breakdown.messages.toLocaleString()}`);
    lines.push(`  Tool Definitions: ${tokens.breakdown.toolDefinitions.toLocaleString()}`);
    lines.push(`  Tool Results: ${tokens.breakdown.toolResults.toLocaleString()}`);
    lines.push(`  ─────────────`);
    lines.push(`  Input Total: ${tokens.input.toLocaleString()}`);
    lines.push(`  Output Total: ${tokens.output.toLocaleString()}`);

    return lines.join('\n');
  }

  /**
   * Format cache analysis.
   */
  formatCacheAnalysis(cache: CacheBreakdown): string {
    const lines: string[] = [];

    const hitRateColor = cache.hitRate > 0.7 ? 'green' : cache.hitRate > 0.4 ? 'yellow' : 'red';

    lines.push(`Cache Analysis:`);
    lines.push(`  Hit Rate: ${this.color(hitRateColor, `${(cache.hitRate * 100).toFixed(1)}%`)}`);
    lines.push(`  Cache Read: ${cache.cacheReadTokens.toLocaleString()} tokens`);
    lines.push(`  Cache Write: ${cache.cacheWriteTokens.toLocaleString()} tokens`);
    lines.push(`  Fresh: ${cache.freshTokens.toLocaleString()} tokens`);
    lines.push(`  Est. Savings: ${this.formatCost(cache.estimatedSavings)}`);

    if (cache.breakpoints.length > 0) {
      lines.push(`  Breakpoints:`);
      for (const bp of cache.breakpoints) {
        lines.push(`    - ${bp.type} at pos ${bp.position}: ${bp.description}`);
      }
    }

    return lines.join('\n');
  }

  // ===========================================================================
  // HELPER METHODS
  // ===========================================================================

  /**
   * Apply color if enabled.
   */
  private color(colorName: keyof typeof COLORS, text: string): string {
    if (!this.options.colors) return text;
    return `${COLORS[colorName]}${text}${COLORS.reset}`;
  }

  /**
   * Get status icon.
   */
  private getStatusIcon(status: string): string {
    switch (status) {
      case 'completed': return this.color('green', '✓');
      case 'failed': return this.color('red', '✗');
      case 'running': return this.color('yellow', '○');
      case 'cancelled': return this.color('gray', '⊘');
      default: return '○';
    }
  }

  /**
   * Get iteration status icon.
   */
  private getIterationStatusIcon(iteration: IterationTrace): string {
    const hasError = iteration.toolExecutions.some(t => t.status === 'error');
    if (hasError) return this.color('red', '✗');
    return this.color('green', '✓');
  }

  /**
   * Format duration.
   */
  private formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  }

  /**
   * Format cost.
   */
  private formatCost(cost: number): string {
    if (cost < 0.01) return `$${cost.toFixed(4)}`;
    return `$${cost.toFixed(2)}`;
  }

  /**
   * Truncate string.
   */
  private truncate(str: string, maxLen: number): string {
    if (str.length <= maxLen) return str;
    return str.substring(0, maxLen - 3) + '...';
  }

  /**
   * Format object for display.
   */
  private formatObject(obj: Record<string, unknown>): string {
    const entries = Object.entries(obj)
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
      .join(', ');
    return this.truncate(entries, 80);
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a trace visualizer.
 */
export function createTraceVisualizer(
  options: Partial<VisualizationOptions> = {}
): TraceVisualizer {
  return new TraceVisualizer(options);
}

/**
 * Quick format helper.
 */
export function formatTrace(
  trace: SessionTrace,
  options: Partial<VisualizationOptions> = {}
): string {
  return new TraceVisualizer(options).formatSession(trace);
}
