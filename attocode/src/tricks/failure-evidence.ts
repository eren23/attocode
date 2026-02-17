/**
 * Trick S: Failure Evidence Preservation
 *
 * Preserves failed actions, error traces, and unsuccessful attempts in context
 * so the model can learn from mistakes and avoid repeating them.
 *
 * Problem: When errors are silently discarded or minimally logged, the model
 * may repeat the same mistakes. Without evidence of what failed and why,
 * the agent loops endlessly.
 *
 * Solution: Explicitly preserve failure evidence with structured metadata.
 * This includes error messages, stack traces, what was attempted, and why
 * it failed - enabling the model to learn and adapt.
 *
 * @example
 * ```typescript
 * import { createFailureTracker, formatFailureContext } from './failure-evidence';
 *
 * const tracker = createFailureTracker({
 *   maxFailures: 20,
 *   preserveStackTraces: true,
 *   categorizeErrors: true,
 * });
 *
 * // Record a failure
 * tracker.recordFailure({
 *   action: 'read_file',
 *   args: { path: '/etc/passwd' },
 *   error: 'Permission denied',
 *   category: 'permission',
 * });
 *
 * // Get context for LLM
 * const failureContext = tracker.getFailureContext();
 * ```
 */

import { logger } from '../integrations/utilities/logger.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Categories of failures for pattern detection.
 */
export type FailureCategory =
  | 'permission'     // Access/permission denied
  | 'not_found'      // File/resource not found
  | 'syntax'         // Syntax/parsing errors
  | 'type'           // Type errors
  | 'runtime'        // Runtime exceptions
  | 'network'        // Network/connection errors
  | 'timeout'        // Timeout errors
  | 'validation'     // Input validation errors
  | 'logic'          // Logic/assertion errors
  | 'resource'       // Resource exhaustion (memory, disk)
  | 'unknown';       // Uncategorized

/**
 * A recorded failure.
 */
export interface Failure {
  /** Unique ID */
  id: string;

  /** When the failure occurred */
  timestamp: string;

  /** What action/tool was attempted */
  action: string;

  /** Arguments passed to the action */
  args?: Record<string, unknown>;

  /** Error message */
  error: string;

  /** Full stack trace (if available) */
  stackTrace?: string;

  /** Error category */
  category: FailureCategory;

  /** Iteration/turn when this occurred */
  iteration?: number;

  /** What was the intent/goal */
  intent?: string;

  /** Suggested fix or workaround (from error analysis) */
  suggestion?: string;

  /** Whether this failure has been addressed */
  resolved: boolean;

  /** Number of times similar failure occurred */
  repeatCount: number;
}

/**
 * Configuration for failure tracking.
 */
export interface FailureTrackerConfig {
  /** Maximum failures to keep in memory */
  maxFailures?: number;

  /** Whether to preserve full stack traces */
  preserveStackTraces?: boolean;

  /** Whether to auto-categorize errors */
  categorizeErrors?: boolean;

  /** Whether to detect repeated failures */
  detectRepeats?: boolean;

  /** Threshold for warning about repeated failures */
  repeatWarningThreshold?: number;
}

/**
 * Failure input for recording.
 */
export interface FailureInput {
  /** What action/tool was attempted */
  action: string;

  /** Arguments passed */
  args?: Record<string, unknown>;

  /** Error message or Error object */
  error: string | Error;

  /** Error category (auto-detected if not provided) */
  category?: FailureCategory;

  /** Current iteration */
  iteration?: number;

  /** What was the goal */
  intent?: string;
}

/**
 * Pattern detected in failures.
 */
export interface FailurePattern {
  /** Pattern type */
  type: 'repeated_action' | 'repeated_error' | 'category_cluster' | 'escalating';

  /** Description of the pattern */
  description: string;

  /** Related failure IDs */
  failureIds: string[];

  /** Confidence (0-1) */
  confidence: number;

  /** Suggested action */
  suggestion: string;
}

/**
 * Events emitted by failure tracker.
 */
export type FailureEvent =
  | { type: 'failure.recorded'; failure: Failure }
  | { type: 'failure.repeated'; failure: Failure; count: number }
  | { type: 'pattern.detected'; pattern: FailurePattern }
  | { type: 'failure.resolved'; failureId: string }
  | { type: 'failure.evicted'; failure: Failure; reason: string };

export type FailureEventListener = (event: FailureEvent) => void;

// =============================================================================
// ERROR CATEGORIZATION
// =============================================================================

/**
 * Auto-categorize an error based on its message.
 */
export function categorizeError(error: string): FailureCategory {
  const lowerError = error.toLowerCase();

  // Permission errors
  if (
    lowerError.includes('permission denied') ||
    lowerError.includes('access denied') ||
    lowerError.includes('not permitted') ||
    lowerError.includes('eacces') ||
    lowerError.includes('unauthorized')
  ) {
    return 'permission';
  }

  // Not found errors
  if (
    lowerError.includes('not found') ||
    lowerError.includes('no such file') ||
    lowerError.includes('enoent') ||
    lowerError.includes('does not exist') ||
    lowerError.includes('404')
  ) {
    return 'not_found';
  }

  // Syntax errors
  if (
    lowerError.includes('syntax error') ||
    lowerError.includes('unexpected token') ||
    lowerError.includes('parse error') ||
    lowerError.includes('invalid json')
  ) {
    return 'syntax';
  }

  // Type errors
  if (
    lowerError.includes('type error') ||
    lowerError.includes('typeerror') ||
    lowerError.includes('is not a function') ||
    lowerError.includes('undefined is not') ||
    lowerError.includes('cannot read propert')
  ) {
    return 'type';
  }

  // Network errors
  if (
    lowerError.includes('network') ||
    lowerError.includes('connection') ||
    lowerError.includes('econnrefused') ||
    lowerError.includes('socket') ||
    lowerError.includes('dns') ||
    lowerError.includes('fetch failed')
  ) {
    return 'network';
  }

  // Timeout errors
  if (
    lowerError.includes('timeout') ||
    lowerError.includes('timed out') ||
    lowerError.includes('etimedout')
  ) {
    return 'timeout';
  }

  // Validation errors
  if (
    lowerError.includes('validation') ||
    lowerError.includes('invalid') ||
    lowerError.includes('required') ||
    lowerError.includes('must be')
  ) {
    return 'validation';
  }

  // Resource errors
  if (
    lowerError.includes('out of memory') ||
    lowerError.includes('disk full') ||
    lowerError.includes('enomem') ||
    lowerError.includes('enospc') ||
    lowerError.includes('quota')
  ) {
    return 'resource';
  }

  // Logic errors
  if (
    lowerError.includes('assertion') ||
    lowerError.includes('invariant') ||
    lowerError.includes('expect')
  ) {
    return 'logic';
  }

  return 'unknown';
}

/**
 * Generate a suggestion based on failure category.
 */
export function generateSuggestion(failure: Failure): string {
  switch (failure.category) {
    case 'permission':
      return `Check file/directory permissions. The action "${failure.action}" may need elevated privileges or the path may be restricted.`;

    case 'not_found':
      return `Verify the resource exists before accessing. Use list_directory or check for typos in the path.`;

    case 'syntax':
      return `Review the syntax. Check for missing brackets, quotes, or invalid characters. Validate JSON/code before submission.`;

    case 'type':
      return `Check variable types and ensure proper null/undefined handling. The value may be a different type than expected.`;

    case 'network':
      return `Check network connectivity. The service may be down, or there may be firewall/DNS issues.`;

    case 'timeout':
      return `The operation took too long. Consider breaking it into smaller operations or increasing timeout.`;

    case 'validation':
      return `Verify input matches expected format/constraints. Check required fields and value ranges.`;

    case 'resource':
      return `System resources are constrained. Consider cleanup, smaller batch sizes, or freeing memory/disk.`;

    case 'logic':
      return `An assumption was violated. Review the logic and check preconditions.`;

    default:
      return `Analyze the error message for specific guidance.`;
  }
}

// =============================================================================
// FAILURE TRACKER
// =============================================================================

/**
 * Tracks failures with pattern detection.
 */
export class FailureTracker {
  private config: Required<FailureTrackerConfig>;
  private failures: Failure[] = [];
  private actionHistory: Map<string, string[]> = new Map(); // action -> failure IDs
  private listeners: FailureEventListener[] = [];

  constructor(config: FailureTrackerConfig = {}) {
    this.config = {
      maxFailures: config.maxFailures ?? 50,
      preserveStackTraces: config.preserveStackTraces ?? true,
      categorizeErrors: config.categorizeErrors ?? true,
      detectRepeats: config.detectRepeats ?? true,
      repeatWarningThreshold: config.repeatWarningThreshold ?? 3,
    };
  }

  /**
   * Record a failure.
   */
  recordFailure(input: FailureInput): Failure {
    const errorString = input.error instanceof Error
      ? input.error.message
      : input.error;

    const stackTrace = input.error instanceof Error
      ? input.error.stack
      : undefined;

    // Auto-categorize if needed
    const category = input.category ??
      (this.config.categorizeErrors ? categorizeError(errorString) : 'unknown');

    // Check for repeats
    let repeatCount = 1;
    if (this.config.detectRepeats) {
      repeatCount = this.countSimilarFailures(input.action, errorString);
    }

    const failure: Failure = {
      id: `fail-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      timestamp: new Date().toISOString(),
      action: input.action,
      args: input.args,
      error: errorString,
      stackTrace: this.config.preserveStackTraces ? stackTrace : undefined,
      category,
      iteration: input.iteration,
      intent: input.intent,
      suggestion: '',
      resolved: false,
      repeatCount,
    };

    // Generate suggestion
    failure.suggestion = generateSuggestion(failure);

    // Store
    this.failures.push(failure);

    // Track by action
    const actionFailures = this.actionHistory.get(input.action) || [];
    actionFailures.push(failure.id);
    this.actionHistory.set(input.action, actionFailures);

    // Enforce max failures with eviction warning
    if (this.failures.length > this.config.maxFailures) {
      const evicted = this.failures.shift()!;

      // Log warning about eviction
      logger.warn(`[FailureTracker] Evicted failure due to limit (${this.config.maxFailures}): ${evicted.action} - ${evicted.error.slice(0, 50)}`);

      // Emit eviction event for observability
      this.emit({
        type: 'failure.evicted',
        failure: evicted,
        reason: `Max failures limit (${this.config.maxFailures}) exceeded`,
      });

      // Clean up action history
      for (const [_action, ids] of this.actionHistory) {
        const idx = ids.indexOf(evicted.id);
        if (idx >= 0) ids.splice(idx, 1);
      }
    }

    // Emit events
    this.emit({ type: 'failure.recorded', failure });

    if (repeatCount >= this.config.repeatWarningThreshold) {
      this.emit({ type: 'failure.repeated', failure, count: repeatCount });
    }

    // Check for patterns
    this.detectPatterns();

    return failure;
  }

  /**
   * Mark a failure as resolved.
   */
  resolveFailure(failureId: string): boolean {
    const failure = this.failures.find(f => f.id === failureId);
    if (failure) {
      failure.resolved = true;
      this.emit({ type: 'failure.resolved', failureId });
      return true;
    }
    return false;
  }

  /**
   * Get all unresolved failures.
   */
  getUnresolvedFailures(): Failure[] {
    return this.failures.filter(f => !f.resolved);
  }

  /**
   * Get failures by category.
   */
  getFailuresByCategory(category: FailureCategory): Failure[] {
    return this.failures.filter(f => f.category === category);
  }

  /**
   * Get failures by action.
   */
  getFailuresByAction(action: string): Failure[] {
    const ids = this.actionHistory.get(action) || [];
    return this.failures.filter(f => ids.includes(f.id));
  }

  /**
   * Get recent failures (last N).
   */
  getRecentFailures(count: number = 10): Failure[] {
    return this.failures.slice(-count);
  }

  /**
   * Get failure context formatted for LLM inclusion.
   */
  getFailureContext(options: {
    maxFailures?: number;
    includeResolved?: boolean;
    includeStackTraces?: boolean;
  } = {}): string {
    const {
      maxFailures = 10,
      includeResolved = false,
      includeStackTraces = false,
    } = options;

    let failures = includeResolved
      ? this.failures
      : this.failures.filter(f => !f.resolved);

    failures = failures.slice(-maxFailures);

    if (failures.length === 0) {
      return '';
    }

    return formatFailureContext(failures, { includeStackTraces });
  }

  /**
   * Check if an action has failed recently.
   */
  hasRecentFailure(action: string, withinMs: number = 60000): boolean {
    const cutoff = Date.now() - withinMs;
    return this.failures.some(
      f => f.action === action && new Date(f.timestamp).getTime() > cutoff
    );
  }

  /**
   * Get failure statistics.
   */
  getStats(): {
    total: number;
    unresolved: number;
    byCategory: Record<FailureCategory, number>;
    mostFailedActions: Array<{ action: string; count: number }>;
  } {
    const byCategory: Record<FailureCategory, number> = {
      permission: 0,
      not_found: 0,
      syntax: 0,
      type: 0,
      runtime: 0,
      network: 0,
      timeout: 0,
      validation: 0,
      logic: 0,
      resource: 0,
      unknown: 0,
    };

    for (const f of this.failures) {
      byCategory[f.category]++;
    }

    const actionCounts = new Map<string, number>();
    for (const f of this.failures) {
      actionCounts.set(f.action, (actionCounts.get(f.action) || 0) + 1);
    }

    const mostFailedActions = Array.from(actionCounts.entries())
      .map(([action, count]) => ({ action, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);

    return {
      total: this.failures.length,
      unresolved: this.failures.filter(f => !f.resolved).length,
      byCategory,
      mostFailedActions,
    };
  }

  /**
   * Clear all failures.
   */
  clear(): void {
    this.failures = [];
    this.actionHistory.clear();
  }

  /**
   * Subscribe to events.
   */
  on(listener: FailureEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // Internal methods

  private countSimilarFailures(action: string, error: string): number {
    const normalizedError = error.toLowerCase().slice(0, 50);
    return this.failures.filter(
      f => f.action === action && f.error.toLowerCase().startsWith(normalizedError)
    ).length + 1;
  }

  private detectPatterns(): void {
    // Detect repeated action failures
    for (const [action, ids] of this.actionHistory) {
      if (ids.length >= 3) {
        const recent = ids.slice(-3);
        const recentFailures = this.failures.filter(f => recent.includes(f.id));

        if (recentFailures.every(f => !f.resolved)) {
          this.emit({
            type: 'pattern.detected',
            pattern: {
              type: 'repeated_action',
              description: `Action "${action}" has failed ${ids.length} times`,
              failureIds: recent,
              confidence: Math.min(0.9, 0.3 + ids.length * 0.1),
              suggestion: `Consider an alternative approach. "${action}" is consistently failing.`,
            },
          });
        }
      }
    }

    // Detect category clusters
    const recentFailures = this.failures.slice(-10);
    const categoryCounts = new Map<FailureCategory, number>();

    for (const f of recentFailures) {
      categoryCounts.set(f.category, (categoryCounts.get(f.category) || 0) + 1);
    }

    for (const [category, count] of categoryCounts) {
      if (count >= 5) {
        this.emit({
          type: 'pattern.detected',
          pattern: {
            type: 'category_cluster',
            description: `Multiple ${category} errors (${count} of last 10)`,
            failureIds: recentFailures.filter(f => f.category === category).map(f => f.id),
            confidence: count / 10,
            suggestion: `Address the underlying ${category} issue before continuing.`,
          },
        });
      }
    }
  }

  private emit(event: FailureEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a failure tracker.
 *
 * @example
 * ```typescript
 * const tracker = createFailureTracker({
 *   maxFailures: 30,
 *   preserveStackTraces: true,
 *   detectRepeats: true,
 * });
 *
 * // Record failures during agent loop
 * try {
 *   await tool.execute(args);
 * } catch (error) {
 *   tracker.recordFailure({
 *     action: tool.name,
 *     args,
 *     error,
 *     iteration: currentIteration,
 *   });
 * }
 *
 * // Include failure context in prompts
 * const failureContext = tracker.getFailureContext();
 * if (failureContext) {
 *   messages.push({
 *     role: 'system',
 *     content: failureContext,
 *   });
 * }
 * ```
 */
export function createFailureTracker(
  config: FailureTrackerConfig = {}
): FailureTracker {
  return new FailureTracker(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format failures as context for LLM.
 */
export function formatFailureContext(
  failures: Failure[],
  options: { includeStackTraces?: boolean } = {}
): string {
  if (failures.length === 0) return '';

  const lines = [
    '[Previous Failures - Learn from these to avoid repeating mistakes]',
    '',
  ];

  for (const f of failures) {
    lines.push(`**${f.action}** (${f.category}): ${f.error}`);

    if (f.args && Object.keys(f.args).length > 0) {
      lines.push(`  Args: ${JSON.stringify(f.args)}`);
    }

    if (f.suggestion) {
      lines.push(`  → ${f.suggestion}`);
    }

    if (options.includeStackTraces && f.stackTrace) {
      const shortStack = f.stackTrace.split('\n').slice(0, 3).join('\n');
      lines.push(`  Stack: ${shortStack}`);
    }

    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Create a warning message for repeated failures.
 */
export function createRepeatWarning(
  action: string,
  count: number,
  suggestion?: string
): string {
  let warning = `⚠️ Action "${action}" has failed ${count} times.`;

  if (count >= 5) {
    warning += ' Consider a completely different approach.';
  } else if (count >= 3) {
    warning += ' Review previous errors before retrying.';
  }

  if (suggestion) {
    warning += `\n💡 Suggestion: ${suggestion}`;
  }

  return warning;
}

/**
 * Extract actionable insights from failures.
 */
export function extractInsights(failures: Failure[]): string[] {
  const insights: string[] = [];

  // Group by category
  const byCategory = new Map<FailureCategory, Failure[]>();
  for (const f of failures) {
    const group = byCategory.get(f.category) || [];
    group.push(f);
    byCategory.set(f.category, group);
  }

  // Generate insights
  if (byCategory.has('permission') && byCategory.get('permission')!.length >= 2) {
    insights.push('Multiple permission errors - check if running with sufficient privileges');
  }

  if (byCategory.has('not_found') && byCategory.get('not_found')!.length >= 2) {
    insights.push('Multiple not-found errors - verify paths and use list_directory first');
  }

  if (byCategory.has('syntax') && byCategory.get('syntax')!.length >= 2) {
    insights.push('Multiple syntax errors - validate code/JSON before execution');
  }

  if (byCategory.has('network') && byCategory.get('network')!.length >= 1) {
    insights.push('Network issues detected - check connectivity and service availability');
  }

  if (byCategory.has('timeout') && byCategory.get('timeout')!.length >= 1) {
    insights.push('Timeout detected - consider breaking operations into smaller chunks');
  }

  // Action-specific insights
  const actionCounts = new Map<string, number>();
  for (const f of failures) {
    actionCounts.set(f.action, (actionCounts.get(f.action) || 0) + 1);
  }

  for (const [action, count] of actionCounts) {
    if (count >= 3) {
      insights.push(`"${action}" failed ${count} times - try an alternative tool/approach`);
    }
  }

  return insights;
}

/**
 * Format failure stats for display.
 */
export function formatFailureStats(stats: ReturnType<FailureTracker['getStats']>): string {
  const lines = [
    `Failure Statistics:`,
    `  Total: ${stats.total} (${stats.unresolved} unresolved)`,
    '',
    '  By Category:',
  ];

  for (const [category, count] of Object.entries(stats.byCategory)) {
    if (count > 0) {
      lines.push(`    ${category}: ${count}`);
    }
  }

  if (stats.mostFailedActions.length > 0) {
    lines.push('');
    lines.push('  Most Failed Actions:');
    for (const { action, count } of stats.mostFailedActions) {
      lines.push(`    ${action}: ${count}`);
    }
  }

  return lines.join('\n');
}
