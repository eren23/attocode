/**
 * Message Pruning Hook
 *
 * Provides intelligent memory management for the TUI message list.
 * Prevents unbounded memory growth in long sessions by pruning older
 * messages while preserving the most recent context.
 *
 * Features:
 * - Configurable max/preserve thresholds
 * - Prunes in batches to avoid frequent re-renders
 * - Preserves error and system messages longer
 * - Returns pruning stats for transparency
 */

import { useCallback, useRef, useMemo } from 'react';

/**
 * TUI message format (matches app.tsx TUIMessage interface)
 */
export interface TUIMessage {
  id: string;
  role: string;
  content: string;
  ts: Date;
}

/**
 * Configuration for message pruning behavior.
 */
export interface MessagePruningConfig {
  /**
   * Maximum number of messages to keep before triggering pruning.
   * Default: 500
   */
  maxMessages?: number;

  /**
   * Number of most recent messages to always preserve.
   * Default: 200
   */
  preserveRecent?: number;

  /**
   * Minimum messages required before pruning is considered.
   * Prevents premature pruning in short sessions.
   * Default: 100
   */
  minBeforePrune?: number;

  /**
   * Roles that should be preserved longer (pruned last).
   * Default: ['error', 'system']
   */
  priorityRoles?: string[];

  /**
   * Callback when pruning occurs.
   */
  onPrune?: (stats: PruneStats) => void;
}

/**
 * Statistics from a pruning operation.
 */
export interface PruneStats {
  /** Messages before pruning */
  beforeCount: number;
  /** Messages after pruning */
  afterCount: number;
  /** Number of messages pruned */
  prunedCount: number;
  /** Timestamp of prune operation */
  timestamp: Date;
}

/**
 * Return type for the useMessagePruning hook.
 */
export interface UseMessagePruningResult {
  /**
   * Check if messages need pruning and return pruned array if so.
   * Returns original array reference if no pruning needed.
   */
  pruneIfNeeded: (messages: TUIMessage[]) => TUIMessage[];

  /**
   * Force prune messages to the preserve limit.
   */
  forcePrune: (messages: TUIMessage[]) => TUIMessage[];

  /**
   * Check if messages array would trigger pruning.
   */
  needsPruning: (messages: TUIMessage[]) => boolean;

  /**
   * Get the last prune stats (if any).
   */
  getLastPruneStats: () => PruneStats | null;

  /**
   * Total messages pruned this session.
   */
  totalPruned: number;
}

const DEFAULT_CONFIG: Required<MessagePruningConfig> = {
  maxMessages: 500,
  preserveRecent: 200,
  minBeforePrune: 100,
  priorityRoles: ['error', 'system'],
  onPrune: () => {},
};

/**
 * Hook for managing message pruning in the TUI.
 *
 * @example
 * ```tsx
 * const { pruneIfNeeded, needsPruning } = useMessagePruning({
 *   maxMessages: 500,
 *   preserveRecent: 200,
 *   onPrune: (stats) => console.log(`Pruned ${stats.prunedCount} messages`),
 * });
 *
 * // In your message handler:
 * const addMessage = useCallback((role, content) => {
 *   setMessages(prev => {
 *     const newMessages = [...prev, { id, role, content, ts: new Date() }];
 *     return pruneIfNeeded(newMessages);
 *   });
 * }, [pruneIfNeeded]);
 * ```
 */
export function useMessagePruning(
  config: MessagePruningConfig = {}
): UseMessagePruningResult {
  const resolvedConfig = useMemo(
    () => ({ ...DEFAULT_CONFIG, ...config }),
    [config]
  );

  const lastPruneStatsRef = useRef<PruneStats | null>(null);
  const totalPrunedRef = useRef(0);

  /**
   * Check if the messages array exceeds the max threshold.
   */
  const needsPruning = useCallback(
    (messages: TUIMessage[]): boolean => {
      return (
        messages.length >= resolvedConfig.maxMessages &&
        messages.length >= resolvedConfig.minBeforePrune
      );
    },
    [resolvedConfig.maxMessages, resolvedConfig.minBeforePrune]
  );

  /**
   * Perform the actual pruning operation.
   * Preserves priority roles (errors, system messages) when possible.
   */
  const doPrune = useCallback(
    (messages: TUIMessage[], targetCount: number): TUIMessage[] => {
      if (messages.length <= targetCount) {
        return messages;
      }

      const beforeCount = messages.length;

      // Separate priority and regular messages
      const priorityMessages: TUIMessage[] = [];
      const regularMessages: TUIMessage[] = [];

      for (const msg of messages) {
        if (resolvedConfig.priorityRoles.includes(msg.role)) {
          priorityMessages.push(msg);
        } else {
          regularMessages.push(msg);
        }
      }

      // Calculate how many of each to keep
      // Priority: keep all priority messages if they fit, otherwise keep most recent
      const maxPriority = Math.floor(targetCount * 0.3); // Max 30% can be priority
      const keptPriority = priorityMessages.slice(-maxPriority);
      const regularSlots = targetCount - keptPriority.length;
      const keptRegular = regularMessages.slice(-regularSlots);

      // Merge and sort by timestamp
      const result = [...keptPriority, ...keptRegular].sort(
        (a, b) => a.ts.getTime() - b.ts.getTime()
      );

      // Record stats
      const stats: PruneStats = {
        beforeCount,
        afterCount: result.length,
        prunedCount: beforeCount - result.length,
        timestamp: new Date(),
      };
      lastPruneStatsRef.current = stats;
      totalPrunedRef.current += stats.prunedCount;

      // Call callback
      resolvedConfig.onPrune(stats);

      return result;
    },
    [resolvedConfig]
  );

  /**
   * Prune messages if they exceed the max threshold.
   * Returns original array reference if no pruning needed.
   */
  const pruneIfNeeded = useCallback(
    (messages: TUIMessage[]): TUIMessage[] => {
      if (!needsPruning(messages)) {
        return messages;
      }
      return doPrune(messages, resolvedConfig.preserveRecent);
    },
    [needsPruning, doPrune, resolvedConfig.preserveRecent]
  );

  /**
   * Force prune to the preserve limit regardless of current count.
   */
  const forcePrune = useCallback(
    (messages: TUIMessage[]): TUIMessage[] => {
      return doPrune(messages, resolvedConfig.preserveRecent);
    },
    [doPrune, resolvedConfig.preserveRecent]
  );

  /**
   * Get the stats from the last prune operation.
   */
  const getLastPruneStats = useCallback((): PruneStats | null => {
    return lastPruneStatsRef.current;
  }, []);

  return {
    pruneIfNeeded,
    forcePrune,
    needsPruning,
    getLastPruneStats,
    get totalPruned() {
      return totalPrunedRef.current;
    },
  };
}

export default useMessagePruning;
