/**
 * Trick E: Context Window Sliding
 *
 * Manage conversation history to fit within token limits.
 * Supports truncation, summarization, and hybrid strategies.
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Message in conversation.
 */
export interface Message {
  id: string;
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  tokens?: number;
  timestamp?: Date;
  metadata?: Record<string, unknown>;
}

/**
 * Sliding window strategy.
 */
export type SlidingStrategy = 'truncate' | 'summarize' | 'hybrid' | 'priority';

/**
 * Sliding window options.
 */
export interface SlidingOptions {
  /** Maximum tokens allowed */
  maxTokens: number;
  /** Strategy for fitting context */
  strategy: SlidingStrategy;
  /** Reserve tokens for response */
  reserveTokens?: number;
  /** Messages to always keep (by ID or index) */
  pinned?: string[] | number[];
  /** Summarization function (for summarize/hybrid) */
  summarize?: (messages: Message[]) => Promise<string>;
  /** Token counter function */
  countTokens?: (text: string) => number;
}

/**
 * Sliding result.
 */
export interface SlidingResult {
  messages: Message[];
  totalTokens: number;
  removedCount: number;
  summarized: boolean;
  summary?: string;
}

// =============================================================================
// CONTEXT WINDOW SLIDING
// =============================================================================

/**
 * Fit messages within token limit using specified strategy.
 */
export async function slideWindow(
  messages: Message[],
  options: SlidingOptions
): Promise<SlidingResult> {
  const {
    maxTokens,
    strategy,
    reserveTokens = 1000,
    pinned = [],
    countTokens = simpleTokenCount,
  } = options;

  const targetTokens = maxTokens - reserveTokens;

  // Calculate current token count
  const messagesWithTokens = messages.map((m) => ({
    ...m,
    tokens: m.tokens ?? countTokens(m.content),
  }));

  const totalTokens = messagesWithTokens.reduce((sum, m) => sum + (m.tokens || 0), 0);

  // If already within limit, return as-is
  if (totalTokens <= targetTokens) {
    return {
      messages: messagesWithTokens,
      totalTokens,
      removedCount: 0,
      summarized: false,
    };
  }

  // Apply strategy
  switch (strategy) {
    case 'truncate':
      return truncateStrategy(messagesWithTokens, targetTokens, pinned, countTokens);
    case 'summarize':
      return summarizeStrategy(messagesWithTokens, targetTokens, options);
    case 'hybrid':
      return hybridStrategy(messagesWithTokens, targetTokens, options);
    case 'priority':
      return priorityStrategy(messagesWithTokens, targetTokens, pinned, countTokens);
    default:
      return truncateStrategy(messagesWithTokens, targetTokens, pinned, countTokens);
  }
}

// =============================================================================
// STRATEGIES
// =============================================================================

/**
 * Truncate oldest messages first.
 */
function truncateStrategy(
  messages: Message[],
  targetTokens: number,
  pinned: string[] | number[],
  countTokens: (text: string) => number
): SlidingResult {
  const pinnedSet = new Set(
    pinned.map((p) => (typeof p === 'number' ? messages[p]?.id : p))
  );

  const result: Message[] = [];
  let currentTokens = 0;
  let removedCount = 0;

  // Always keep system message if present
  const systemMessage = messages.find((m) => m.role === 'system');
  if (systemMessage) {
    result.push(systemMessage);
    currentTokens += systemMessage.tokens || countTokens(systemMessage.content);
  }

  // Process from newest to oldest (keeping recent context)
  const nonSystem = messages.filter((m) => m.role !== 'system').reverse();

  for (const message of nonSystem) {
    const messageTokens = message.tokens || countTokens(message.content);

    // Always include pinned messages
    if (pinnedSet.has(message.id)) {
      result.unshift(message);
      currentTokens += messageTokens;
      continue;
    }

    // Check if adding would exceed limit
    if (currentTokens + messageTokens <= targetTokens) {
      result.unshift(message);
      currentTokens += messageTokens;
    } else {
      removedCount++;
    }
  }

  return {
    messages: result,
    totalTokens: currentTokens,
    removedCount,
    summarized: false,
  };
}

/**
 * Summarize older messages.
 */
async function summarizeStrategy(
  messages: Message[],
  targetTokens: number,
  options: SlidingOptions
): Promise<SlidingResult> {
  const { summarize, countTokens = simpleTokenCount } = options;

  if (!summarize) {
    throw new Error('Summarize function required for summarize strategy');
  }

  // Split into recent (keep) and old (summarize)
  const splitPoint = Math.floor(messages.length * 0.3); // Keep recent 30%
  const oldMessages = messages.slice(0, splitPoint);
  const recentMessages = messages.slice(splitPoint);

  // Generate summary of old messages
  const summary = await summarize(oldMessages);
  const summaryTokens = countTokens(summary);

  // Create summary message
  const summaryMessage: Message = {
    id: 'summary',
    role: 'system',
    content: `Previous conversation summary:\n${summary}`,
    tokens: summaryTokens,
  };

  // Combine summary with recent messages
  const result = [summaryMessage, ...recentMessages];
  const totalTokens = result.reduce((sum, m) => sum + (m.tokens || countTokens(m.content)), 0);

  return {
    messages: result,
    totalTokens,
    removedCount: oldMessages.length,
    summarized: true,
    summary,
  };
}

/**
 * Hybrid: truncate first, summarize if still too large.
 */
async function hybridStrategy(
  messages: Message[],
  targetTokens: number,
  options: SlidingOptions
): Promise<SlidingResult> {
  const { pinned = [], countTokens = simpleTokenCount } = options;

  // First try truncation
  const truncated = truncateStrategy(messages, targetTokens, pinned, countTokens);

  if (truncated.totalTokens <= targetTokens) {
    return truncated;
  }

  // If still too large, summarize
  return summarizeStrategy(messages, targetTokens, options);
}

/**
 * Priority-based: keep high-importance messages.
 */
function priorityStrategy(
  messages: Message[],
  targetTokens: number,
  pinned: string[] | number[],
  countTokens: (text: string) => number
): SlidingResult {
  const pinnedSet = new Set(
    pinned.map((p) => (typeof p === 'number' ? messages[p]?.id : p))
  );

  // Score messages by importance
  const scored = messages.map((m) => ({
    message: m,
    score: calculatePriority(m, pinnedSet),
  }));

  // Sort by priority (highest first)
  scored.sort((a, b) => b.score - a.score);

  // Select messages until limit reached
  const result: Message[] = [];
  let currentTokens = 0;
  let removedCount = 0;

  for (const { message } of scored) {
    const messageTokens = message.tokens || countTokens(message.content);

    if (currentTokens + messageTokens <= targetTokens) {
      result.push(message);
      currentTokens += messageTokens;
    } else {
      removedCount++;
    }
  }

  // Restore original order
  result.sort(
    (a, b) => messages.findIndex((m) => m.id === a.id) - messages.findIndex((m) => m.id === b.id)
  );

  return {
    messages: result,
    totalTokens: currentTokens,
    removedCount,
    summarized: false,
  };
}

/**
 * Calculate message priority.
 */
function calculatePriority(message: Message, pinned: Set<string>): number {
  let score = 0;

  // Pinned messages get highest priority
  if (pinned.has(message.id)) {
    score += 1000;
  }

  // System messages are important
  if (message.role === 'system') {
    score += 500;
  }

  // Recent messages are more important
  if (message.timestamp) {
    const age = Date.now() - message.timestamp.getTime();
    const ageHours = age / (1000 * 60 * 60);
    score += Math.max(0, 100 - ageHours);
  }

  // Tool results might be referenced
  if (message.role === 'tool') {
    score += 50;
  }

  // Metadata can indicate importance
  if (message.metadata?.important) {
    score += 200;
  }

  return score;
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Simple token count estimate.
 */
function simpleTokenCount(text: string): number {
  return Math.ceil(text.length / 4);
}

/**
 * Create a sliding window manager.
 */
export class ContextWindowManager {
  private options: SlidingOptions;
  private history: Message[] = [];

  constructor(options: SlidingOptions) {
    this.options = options;
  }

  /**
   * Add a message.
   */
  add(message: Message): void {
    this.history.push(message);
  }

  /**
   * Get messages that fit within context window.
   */
  async getContext(): Promise<SlidingResult> {
    return slideWindow(this.history, this.options);
  }

  /**
   * Clear history.
   */
  clear(): void {
    this.history = [];
  }

  /**
   * Get full history (unsliced).
   */
  getFullHistory(): Message[] {
    return [...this.history];
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createContextWindow(options: SlidingOptions): ContextWindowManager {
  return new ContextWindowManager(options);
}

// Usage:
// const window = createContextWindow({
//   maxTokens: 4096,
//   strategy: 'hybrid',
//   reserveTokens: 1000,
//   summarize: async (msgs) => `Summary of ${msgs.length} messages`,
// });
//
// window.add({ id: '1', role: 'user', content: 'Hello' });
// window.add({ id: '2', role: 'assistant', content: 'Hi there!' });
//
// const { messages, summarized } = await window.getContext();
