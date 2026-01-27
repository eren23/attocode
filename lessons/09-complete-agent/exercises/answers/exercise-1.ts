/**
 * Exercise 9: Context Tracker - REFERENCE SOLUTION
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
  maxTokens: number;
  warningThreshold: number;
}

export interface ContextStats {
  messageCount: number;
  toolCallCount: number;
  totalTokens: number;
  contextUsagePercent: number;
  toolsUsed: string[];
  elapsedMs: number;
}

// =============================================================================
// HELPER
// =============================================================================

export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

// =============================================================================
// SOLUTION: ContextTracker
// =============================================================================

export class ContextTracker {
  private config: ContextTrackerConfig;
  private messages: Message[] = [];
  private toolCalls: ToolCallRecord[] = [];
  private totalTokens: number = 0;
  private startTime: number;

  constructor(config: ContextTrackerConfig) {
    this.config = config;
    this.startTime = Date.now();
  }

  addMessage(message: Message): void {
    this.messages.push(message);
    this.totalTokens += estimateTokens(message.content);
  }

  addToolCall(toolName: string, tokens: number): void {
    this.toolCalls.push({
      toolName,
      tokens,
      timestamp: Date.now(),
    });
    this.totalTokens += tokens;
  }

  getMessages(): Message[] {
    return [...this.messages];
  }

  getStats(): ContextStats {
    // Get unique tool names
    const toolsUsed = [...new Set(this.toolCalls.map(tc => tc.toolName))];

    // Calculate usage percentage
    const contextUsagePercent = (this.totalTokens / this.config.maxTokens) * 100;

    return {
      messageCount: this.messages.length,
      toolCallCount: this.toolCalls.length,
      totalTokens: this.totalTokens,
      contextUsagePercent: Math.min(contextUsagePercent, 100), // Cap at 100%
      toolsUsed,
      elapsedMs: Date.now() - this.startTime,
    };
  }

  isNearLimit(): boolean {
    const threshold = this.config.maxTokens * this.config.warningThreshold;
    return this.totalTokens >= threshold;
  }

  getRemainingTokens(): number {
    return Math.max(0, this.config.maxTokens - this.totalTokens);
  }

  reset(): void {
    this.messages = [];
    this.toolCalls = [];
    this.totalTokens = 0;
    this.startTime = Date.now();
  }
}
