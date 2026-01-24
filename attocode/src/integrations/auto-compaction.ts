/**
 * AutoCompactionManager - Monitors token usage and triggers compaction
 *
 * Implements a three-tier threshold system:
 * - OK (< 80%): Continue normally
 * - Warning (80-89%): Alert user, no automatic action
 * - Auto-Compact (90-97%): Depending on mode, auto-compact or request approval
 * - Hard Limit (>= 98%): Agent cannot continue - context too full
 */

import type { Message } from '../types.js';
import type { Compactor, CompactionResult } from './compaction.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for automatic compaction behavior.
 */
export interface AutoCompactionConfig {
  /** Compaction mode: auto (no approval), approval (asks user), manual (never auto) */
  mode: 'auto' | 'approval' | 'manual';
  /** Warning threshold as ratio (default: 0.80) */
  warningThreshold: number;
  /** Auto-compact threshold as ratio (default: 0.90) */
  autoCompactThreshold: number;
  /** Hard limit threshold as ratio (default: 0.98) */
  hardLimitThreshold: number;
  /** Number of recent user messages to preserve (default: 5) */
  preserveRecentUserMessages: number;
  /** Number of recent assistant messages to preserve (default: 5) */
  preserveRecentAssistantMessages: number;
  /** Cooldown between compactions in ms (default: 60000) */
  cooldownMs: number;
  /** Max context window tokens (default: 200000 for Claude) */
  maxContextTokens: number;
}

/**
 * Result of checking token usage and potentially compacting.
 */
export interface CompactionCheckResult {
  /** Current status after check */
  status: 'ok' | 'warning' | 'compacted' | 'needs_approval' | 'hard_limit';
  /** Current token count */
  currentTokens: number;
  /** Maximum allowed tokens */
  maxTokens: number;
  /** Ratio of current to max (0-1) */
  ratio: number;
  /** Compacted messages if compaction occurred */
  compactedMessages?: Message[];
  /** Summary generated during compaction */
  summary?: string;
}

/**
 * Events emitted by AutoCompactionManager.
 */
export type AutoCompactionEvent =
  | { type: 'autocompaction.check'; currentTokens: number; ratio: number; threshold: string }
  | { type: 'autocompaction.warning'; currentTokens: number; ratio: number }
  | { type: 'autocompaction.triggered'; mode: string; currentTokens: number }
  | { type: 'autocompaction.completed'; tokensBefore: number; tokensAfter: number; reduction: number }
  | { type: 'autocompaction.cooldown'; remainingMs: number }
  | { type: 'autocompaction.hard_limit'; currentTokens: number; ratio: number }
  | { type: 'autocompaction.needs_approval'; currentTokens: number; ratio: number };

export type AutoCompactionEventListener = (event: AutoCompactionEvent) => void;

// =============================================================================
// DEFAULT CONFIG
// =============================================================================

const DEFAULT_CONFIG: AutoCompactionConfig = {
  mode: 'auto',
  warningThreshold: 0.80,
  autoCompactThreshold: 0.90,
  hardLimitThreshold: 0.98,
  preserveRecentUserMessages: 5,
  preserveRecentAssistantMessages: 5,
  cooldownMs: 60000, // 1 minute
  maxContextTokens: 200000, // Claude's context window
};

// =============================================================================
// AUTO COMPACTION MANAGER
// =============================================================================

/**
 * Monitors token usage and triggers compaction based on thresholds.
 *
 * Three-tier threshold design:
 * - OK (< 80%): Normal operation
 * - Warning (80-89%): User alerted but no action
 * - Auto-Compact (90-97%): Automatic compaction (in auto mode) or approval request
 * - Hard Limit (>= 98%): Cannot continue - too close to context limit
 */
export class AutoCompactionManager {
  private compactor: Compactor;
  private config: AutoCompactionConfig;
  private lastCompactionTime: number = 0;
  private listeners: AutoCompactionEventListener[] = [];

  constructor(compactor: Compactor, config?: Partial<AutoCompactionConfig>) {
    this.compactor = compactor;
    this.config = { ...DEFAULT_CONFIG, ...config };

    // Validate thresholds are in correct order
    if (this.config.warningThreshold >= this.config.autoCompactThreshold) {
      throw new Error('warningThreshold must be less than autoCompactThreshold');
    }
    if (this.config.autoCompactThreshold >= this.config.hardLimitThreshold) {
      throw new Error('autoCompactThreshold must be less than hardLimitThreshold');
    }
  }

  /**
   * Check token usage and maybe perform compaction.
   *
   * @param options - Current tokens and messages
   * @returns Result indicating status and any compaction performed
   */
  async checkAndMaybeCompact(options: {
    currentTokens: number;
    messages: Message[];
  }): Promise<CompactionCheckResult> {
    const { currentTokens, messages } = options;
    const ratio = this.getTokenRatio(currentTokens);
    const maxTokens = this.config.maxContextTokens;

    // Determine which zone we're in
    const zone = this.determineZone(ratio);

    this.emit({
      type: 'autocompaction.check',
      currentTokens,
      ratio,
      threshold: zone,
    });

    // Zone: OK (< warningThreshold)
    if (zone === 'ok') {
      return {
        status: 'ok',
        currentTokens,
        maxTokens,
        ratio,
      };
    }

    // Zone: Hard Limit (>= hardLimitThreshold)
    if (zone === 'hard_limit') {
      this.emit({
        type: 'autocompaction.hard_limit',
        currentTokens,
        ratio,
      });
      return {
        status: 'hard_limit',
        currentTokens,
        maxTokens,
        ratio,
      };
    }

    // Zone: Warning (warningThreshold <= ratio < autoCompactThreshold)
    if (zone === 'warning') {
      this.emit({
        type: 'autocompaction.warning',
        currentTokens,
        ratio,
      });
      return {
        status: 'warning',
        currentTokens,
        maxTokens,
        ratio,
      };
    }

    // Zone: Auto-Compact (autoCompactThreshold <= ratio < hardLimitThreshold)
    // Check cooldown
    if (this.isInCooldown()) {
      const remaining = this.getRemainingCooldown();
      this.emit({
        type: 'autocompaction.cooldown',
        remainingMs: remaining,
      });

      // During cooldown, treat as warning
      return {
        status: 'warning',
        currentTokens,
        maxTokens,
        ratio,
      };
    }

    // Handle based on mode
    switch (this.config.mode) {
      case 'auto':
        return this.performCompaction(messages, currentTokens, maxTokens, ratio);

      case 'approval':
        this.emit({
          type: 'autocompaction.needs_approval',
          currentTokens,
          ratio,
        });
        return {
          status: 'needs_approval',
          currentTokens,
          maxTokens,
          ratio,
        };

      case 'manual':
        // In manual mode, auto-compact zone is treated as warning
        this.emit({
          type: 'autocompaction.warning',
          currentTokens,
          ratio,
        });
        return {
          status: 'warning',
          currentTokens,
          maxTokens,
          ratio,
        };

      default:
        return {
          status: 'warning',
          currentTokens,
          maxTokens,
          ratio,
        };
    }
  }

  /**
   * Get the current token ratio.
   */
  getTokenRatio(currentTokens: number): number {
    return currentTokens / this.config.maxContextTokens;
  }

  /**
   * Check if currently in cooldown period.
   */
  isInCooldown(): boolean {
    if (this.lastCompactionTime === 0) {
      return false;
    }
    return Date.now() - this.lastCompactionTime < this.config.cooldownMs;
  }

  /**
   * Get remaining cooldown time in milliseconds.
   */
  getRemainingCooldown(): number {
    if (!this.isInCooldown()) {
      return 0;
    }
    return this.config.cooldownMs - (Date.now() - this.lastCompactionTime);
  }

  /**
   * Reset cooldown (e.g., after manual compaction request).
   */
  resetCooldown(): void {
    this.lastCompactionTime = 0;
  }

  /**
   * Force compaction regardless of mode or cooldown.
   * Useful for manual compaction requests.
   */
  async forceCompact(messages: Message[]): Promise<CompactionCheckResult> {
    const currentTokens = this.compactor.estimateTokens(messages);
    const ratio = this.getTokenRatio(currentTokens);
    const maxTokens = this.config.maxContextTokens;

    return this.performCompaction(messages, currentTokens, maxTokens, ratio);
  }

  /**
   * Get current configuration.
   */
  getConfig(): AutoCompactionConfig {
    return { ...this.config };
  }

  /**
   * Update configuration.
   */
  updateConfig(updates: Partial<AutoCompactionConfig>): void {
    this.config = { ...this.config, ...updates };

    // Re-validate thresholds
    if (this.config.warningThreshold >= this.config.autoCompactThreshold) {
      throw new Error('warningThreshold must be less than autoCompactThreshold');
    }
    if (this.config.autoCompactThreshold >= this.config.hardLimitThreshold) {
      throw new Error('autoCompactThreshold must be less than hardLimitThreshold');
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: AutoCompactionEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  /**
   * Determine which zone the current ratio falls into.
   */
  private determineZone(ratio: number): 'ok' | 'warning' | 'auto_compact' | 'hard_limit' {
    if (ratio >= this.config.hardLimitThreshold) {
      return 'hard_limit';
    }
    if (ratio >= this.config.autoCompactThreshold) {
      return 'auto_compact';
    }
    if (ratio >= this.config.warningThreshold) {
      return 'warning';
    }
    return 'ok';
  }

  /**
   * Perform the actual compaction.
   */
  private async performCompaction(
    messages: Message[],
    currentTokens: number,
    maxTokens: number,
    ratio: number
  ): Promise<CompactionCheckResult> {
    this.emit({
      type: 'autocompaction.triggered',
      mode: this.config.mode,
      currentTokens,
    });

    // Configure compactor to preserve the specified number of messages
    // The compactor already handles preserving recent messages, but we can
    // update its config if needed based on our preservation settings
    const totalPreserve = this.config.preserveRecentUserMessages + this.config.preserveRecentAssistantMessages;
    const currentCompactorConfig = this.compactor.getConfig();

    // Temporarily adjust if our preserve count differs
    const needsRestore = currentCompactorConfig.preserveRecentCount !== totalPreserve;
    if (needsRestore) {
      this.compactor.updateConfig({ preserveRecentCount: totalPreserve });
    }

    let result: CompactionResult;
    try {
      result = await this.compactor.compact(messages);
    } finally {
      // Restore original config
      if (needsRestore) {
        this.compactor.updateConfig({ preserveRecentCount: currentCompactorConfig.preserveRecentCount });
      }
    }

    // Update cooldown
    this.lastCompactionTime = Date.now();

    const reduction = result.tokensBefore > 0
      ? Math.round((1 - result.tokensAfter / result.tokensBefore) * 100)
      : 0;

    this.emit({
      type: 'autocompaction.completed',
      tokensBefore: result.tokensBefore,
      tokensAfter: result.tokensAfter,
      reduction,
    });

    return {
      status: 'compacted',
      currentTokens: result.tokensAfter,
      maxTokens,
      ratio: result.tokensAfter / maxTokens,
      compactedMessages: result.preservedMessages,
      summary: result.summary,
    };
  }

  /**
   * Emit an event to all listeners.
   */
  private emit(event: AutoCompactionEvent): void {
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
// FACTORY
// =============================================================================

/**
 * Create an AutoCompactionManager.
 */
export function createAutoCompactionManager(
  compactor: Compactor,
  config?: Partial<AutoCompactionConfig>
): AutoCompactionManager {
  return new AutoCompactionManager(compactor, config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format a CompactionCheckResult for display.
 */
export function formatCompactionCheckResult(result: CompactionCheckResult): string {
  const percentUsed = Math.round(result.ratio * 100);
  const lines: string[] = [];

  switch (result.status) {
    case 'ok':
      lines.push(`Context usage: ${percentUsed}% (${result.currentTokens.toLocaleString()} / ${result.maxTokens.toLocaleString()} tokens)`);
      lines.push('Status: OK');
      break;

    case 'warning':
      lines.push(`Context usage: ${percentUsed}% (${result.currentTokens.toLocaleString()} / ${result.maxTokens.toLocaleString()} tokens)`);
      lines.push('Status: WARNING - Context usage is high');
      lines.push('Consider compacting the conversation to free up space.');
      break;

    case 'needs_approval':
      lines.push(`Context usage: ${percentUsed}% (${result.currentTokens.toLocaleString()} / ${result.maxTokens.toLocaleString()} tokens)`);
      lines.push('Status: NEEDS APPROVAL');
      lines.push('Context is nearing capacity. Approve compaction to continue.');
      break;

    case 'compacted':
      lines.push(`Context usage: ${percentUsed}% (${result.currentTokens.toLocaleString()} / ${result.maxTokens.toLocaleString()} tokens)`);
      lines.push('Status: COMPACTED');
      if (result.summary) {
        lines.push('Summary preserved: Yes');
      }
      break;

    case 'hard_limit':
      lines.push(`Context usage: ${percentUsed}% (${result.currentTokens.toLocaleString()} / ${result.maxTokens.toLocaleString()} tokens)`);
      lines.push('Status: HARD LIMIT REACHED');
      lines.push('Cannot continue - context window is too full.');
      lines.push('Manual intervention required.');
      break;
  }

  return lines.join('\n');
}

/**
 * Get suggested action based on check result.
 */
export function getSuggestedAction(result: CompactionCheckResult): string | null {
  switch (result.status) {
    case 'ok':
      return null;
    case 'warning':
      return 'Consider running /compact to free up context space';
    case 'needs_approval':
      return 'Approve context compaction to continue';
    case 'compacted':
      return null;
    case 'hard_limit':
      return 'Start a new conversation or manually clear context';
    default:
      return null;
  }
}
