/**
 * Transparency Aggregator
 *
 * Aggregates agent events into a display-ready state for the TUI.
 * Tracks routing decisions, policy decisions, and context health.
 */

import type { AgentEvent } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * A recorded decision for the history.
 */
export interface DecisionRecord {
  timestamp: number;
  type: 'routing' | 'tool' | 'context';
  summary: string;
  details?: string;
}

/**
 * Aggregated transparency state for TUI display.
 */
export interface TransparencyState {
  /** Most recent routing decision */
  lastRouting: {
    model: string;
    reason: string;
    timestamp: number;
  } | null;

  /** Most recent policy decision */
  lastPolicy: {
    tool: string;
    decision: 'allowed' | 'prompted' | 'blocked';
    reason?: string;
    timestamp: number;
  } | null;

  /** Context health status */
  contextHealth: {
    currentTokens: number;
    maxTokens: number;
    percentUsed: number;
    estimatedExchanges: number;
    lastUpdate: number;
  } | null;

  /** Active learnings being applied (if learning store is active) */
  activeLearnings: string[];

  /** Recent decision history (last N decisions) */
  decisionHistory: DecisionRecord[];

  /** Diagnostics state (AST + compilation) */
  diagnostics: {
    lastTscResult: { success: boolean; errorCount: number; duration: number } | null;
    recentSyntaxErrors: Array<{ file: string; line: number; message: string }>;
  };

  /** Count of events processed */
  eventsProcessed: number;
}

/**
 * Configuration for the aggregator.
 */
export interface TransparencyAggregatorConfig {
  /** Maximum number of decisions to keep in history */
  maxHistorySize?: number;

  /** Whether to track all events or just key decisions */
  verbose?: boolean;
}

// =============================================================================
// TRANSPARENCY AGGREGATOR
// =============================================================================

/**
 * Aggregates agent events into display-ready transparency state.
 */
export class TransparencyAggregator {
  private state: TransparencyState = {
    lastRouting: null,
    lastPolicy: null,
    contextHealth: null,
    activeLearnings: [],
    decisionHistory: [],
    diagnostics: { lastTscResult: null, recentSyntaxErrors: [] },
    eventsProcessed: 0,
  };

  private config: Required<TransparencyAggregatorConfig>;
  private listeners: Set<(state: TransparencyState) => void> = new Set();

  constructor(config: TransparencyAggregatorConfig = {}) {
    this.config = {
      maxHistorySize: config.maxHistorySize ?? 50,
      verbose: config.verbose ?? false,
    };
  }

  /**
   * Process an agent event and update state.
   */
  processEvent(event: AgentEvent): void {
    let changed = false;

    switch (event.type) {
      case 'decision.routing':
        this.state.lastRouting = {
          model: event.model,
          reason: event.reason,
          timestamp: Date.now(),
        };
        this.addToHistory({
          timestamp: Date.now(),
          type: 'routing',
          summary: `Model: ${event.model}`,
          details: event.reason,
        });
        changed = true;
        break;

      case 'decision.tool':
        this.state.lastPolicy = {
          tool: event.tool,
          decision: event.decision,
          reason: event.policyMatch,
          timestamp: Date.now(),
        };
        this.addToHistory({
          timestamp: Date.now(),
          type: 'tool',
          summary: `${event.tool}: ${event.decision}`,
          details: event.policyMatch,
        });
        changed = true;
        break;

      case 'context.health':
        this.state.contextHealth = {
          currentTokens: event.currentTokens,
          maxTokens: event.maxTokens,
          percentUsed: event.percentUsed,
          estimatedExchanges: event.estimatedExchanges,
          lastUpdate: Date.now(),
        };
        // Only add to history when significant changes occur
        if (this.config.verbose || event.percentUsed >= 70) {
          this.addToHistory({
            timestamp: Date.now(),
            type: 'context',
            summary: `Context: ${event.percentUsed}%`,
            details: `${event.estimatedExchanges} exchanges remaining`,
          });
        }
        changed = true;
        break;

      case 'learning.applied':
        if (!this.state.activeLearnings.includes(event.context)) {
          this.state.activeLearnings.push(event.context);
          // Keep only last 5 learnings
          if (this.state.activeLearnings.length > 5) {
            this.state.activeLearnings.shift();
          }
          changed = true;
        }
        break;

      // Also track insight events for routing/context
      case 'insight.routing':
        if (!this.state.lastRouting) {
          this.state.lastRouting = {
            model: event.model,
            reason: event.reason,
            timestamp: Date.now(),
          };
          changed = true;
        }
        break;

      case 'insight.context':
        if (!this.state.contextHealth) {
          this.state.contextHealth = {
            currentTokens: event.currentTokens,
            maxTokens: event.maxTokens,
            percentUsed: event.percentUsed,
            estimatedExchanges: 0,
            lastUpdate: Date.now(),
          };
          changed = true;
        }
        break;

      case 'diagnostics.tsc-check':
        this.state.diagnostics.lastTscResult = {
          success: event.errorCount === 0,
          errorCount: event.errorCount,
          duration: event.duration,
        };
        changed = true;
        break;

      case 'diagnostics.syntax-error':
        this.state.diagnostics.recentSyntaxErrors.push({
          file: event.file,
          line: event.line,
          message: event.message,
        });
        // Keep last 10
        if (this.state.diagnostics.recentSyntaxErrors.length > 10) {
          this.state.diagnostics.recentSyntaxErrors =
            this.state.diagnostics.recentSyntaxErrors.slice(-10);
        }
        changed = true;
        break;
    }

    if (changed) {
      this.state.eventsProcessed++;
      this.notifyListeners();
    }
  }

  /**
   * Add a decision to history, respecting max size.
   */
  private addToHistory(record: DecisionRecord): void {
    this.state.decisionHistory.push(record);
    if (this.state.decisionHistory.length > this.config.maxHistorySize) {
      this.state.decisionHistory.shift();
    }
  }

  /**
   * Get current state.
   */
  getState(): TransparencyState {
    return { ...this.state };
  }

  /**
   * Reset state.
   */
  reset(): void {
    this.state = {
      lastRouting: null,
      lastPolicy: null,
      contextHealth: null,
      activeLearnings: [],
      decisionHistory: [],
      diagnostics: { lastTscResult: null, recentSyntaxErrors: [] },
      eventsProcessed: 0,
    };
    this.notifyListeners();
  }

  /**
   * Subscribe to state changes.
   */
  subscribe(listener: (state: TransparencyState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notifyListeners(): void {
    const state = this.getState();
    for (const listener of this.listeners) {
      try {
        listener(state);
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
 * Create a transparency aggregator.
 */
export function createTransparencyAggregator(
  config?: TransparencyAggregatorConfig,
): TransparencyAggregator {
  return new TransparencyAggregator(config);
}

/**
 * Format transparency state for display.
 */
export function formatTransparencyState(state: TransparencyState): string {
  const lines: string[] = [];

  // Routing section
  lines.push('REASONING');
  if (state.lastRouting) {
    lines.push(`  Routing: ${state.lastRouting.model}`);
    lines.push(`    ${state.lastRouting.reason}`);
  } else {
    lines.push('  Routing: (no routing decisions yet)');
  }

  if (state.lastPolicy) {
    const icon =
      state.lastPolicy.decision === 'allowed'
        ? '+'
        : state.lastPolicy.decision === 'blocked'
          ? 'x'
          : '?';
    lines.push(`  Policy: ${icon} ${state.lastPolicy.tool} (${state.lastPolicy.decision})`);
    if (state.lastPolicy.reason) {
      lines.push(`    ${state.lastPolicy.reason}`);
    }
  }

  // Memory section
  if (state.activeLearnings.length > 0) {
    lines.push('');
    lines.push('MEMORY');
    lines.push(`  Learnings applied: ${state.activeLearnings.length}`);
    for (const learning of state.activeLearnings.slice(0, 3)) {
      lines.push(`    - ${learning.slice(0, 50)}...`);
    }
  }

  // Context section
  lines.push('');
  lines.push('CONTEXT');
  if (state.contextHealth) {
    const barLen = 20;
    const filledLen = Math.round((state.contextHealth.percentUsed / 100) * barLen);
    const bar =
      '='.repeat(Math.min(filledLen, barLen)) + '-'.repeat(Math.max(0, barLen - filledLen));
    lines.push(`  [${bar}] ${state.contextHealth.percentUsed}%`);
    lines.push(
      `  ${(state.contextHealth.currentTokens / 1000).toFixed(1)}k / ${(state.contextHealth.maxTokens / 1000).toFixed(0)}k tokens`,
    );
    lines.push(`  ~${state.contextHealth.estimatedExchanges} exchanges remaining`);
  } else {
    lines.push('  (no context data yet)');
  }

  return lines.join('\n');
}

/**
 * Get a compact one-line summary.
 */
export function getTransparencySummary(state: TransparencyState): string {
  const parts: string[] = [];

  if (state.lastRouting) {
    parts.push(`model:${state.lastRouting.model.split('-').pop()}`);
  }

  if (state.contextHealth) {
    parts.push(`ctx:${state.contextHealth.percentUsed}%`);
  }

  if (state.activeLearnings.length > 0) {
    parts.push(`L:${state.activeLearnings.length}`);
  }

  return parts.join(' | ');
}
