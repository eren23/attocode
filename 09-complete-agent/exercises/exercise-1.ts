/**
 * Exercise 9: Context Tracker
 *
 * Implement a context tracker for monitoring agent execution.
 */

// =============================================================================
// TYPES
// =============================================================================

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ToolCallRecord {
  toolName: string;
  tokens: number;
  timestamp: number;
}

export interface ContextTrackerConfig {
  /** Maximum tokens allowed in context */
  maxTokens: number;
  /** Threshold (0-1) at which to warn about context usage */
  warningThreshold: number;
}

export interface ContextStats {
  /** Number of messages in history */
  messageCount: number;
  /** Number of tool calls made */
  toolCallCount: number;
  /** Total tokens used */
  totalTokens: number;
  /** Percentage of context used (0-100) */
  contextUsagePercent: number;
  /** List of tools called */
  toolsUsed: string[];
  /** Time since first message (ms) */
  elapsedMs: number;
}

// =============================================================================
// HELPER: Estimate token count
// =============================================================================

export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

// =============================================================================
// TODO: Implement ContextTracker
// =============================================================================

/**
 * Tracks agent context usage and provides monitoring capabilities.
 *
 * TODO: Implement this class with the following:
 *
 * 1. Constructor:
 *    - Store config
 *    - Initialize tracking state
 *    - Record start time
 *
 * 2. addMessage(message):
 *    - Add to message history
 *    - Update token count
 *
 * 3. addToolCall(toolName, tokens):
 *    - Record tool call with timestamp
 *    - Update token count
 *
 * 4. getMessages():
 *    - Return copy of message history
 *
 * 5. getStats():
 *    - Return current statistics
 *    - Include all fields in ContextStats
 *
 * 6. isNearLimit():
 *    - Return true if usage >= warningThreshold * maxTokens
 *
 * 7. reset():
 *    - Clear all history and stats
 *    - Reset start time
 */
export class ContextTracker {
  // TODO: Add private fields
  // private config: ContextTrackerConfig;
  // private messages: Message[] = [];
  // private toolCalls: ToolCallRecord[] = [];
  // private totalTokens: number = 0;
  // private startTime: number;

  constructor(_config: ContextTrackerConfig) {
    // TODO: Initialize tracker
    throw new Error('TODO: Implement constructor');
  }

  /**
   * Add a message to the context.
   */
  addMessage(_message: Message): void {
    // TODO: Add message and update token count
    throw new Error('TODO: Implement addMessage');
  }

  /**
   * Record a tool call.
   */
  addToolCall(_toolName: string, _tokens: number): void {
    // TODO: Record tool call with timestamp
    throw new Error('TODO: Implement addToolCall');
  }

  /**
   * Get all messages in the context.
   */
  getMessages(): Message[] {
    // TODO: Return copy of messages
    throw new Error('TODO: Implement getMessages');
  }

  /**
   * Get current context statistics.
   */
  getStats(): ContextStats {
    // TODO: Calculate and return all stats
    throw new Error('TODO: Implement getStats');
  }

  /**
   * Check if context usage is approaching the limit.
   */
  isNearLimit(): boolean {
    // TODO: Check against warning threshold
    throw new Error('TODO: Implement isNearLimit');
  }

  /**
   * Get remaining token capacity.
   */
  getRemainingTokens(): number {
    // TODO: Calculate remaining
    throw new Error('TODO: Implement getRemainingTokens');
  }

  /**
   * Reset the tracker to initial state.
   */
  reset(): void {
    // TODO: Clear all state and restart timer
    throw new Error('TODO: Implement reset');
  }
}
