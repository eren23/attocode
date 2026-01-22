/**
 * Lesson 25: Context Compaction
 *
 * Automatically summarizes conversation history when context gets too long.
 * Preserves recent messages and important context while reducing token count.
 */

import type { LLMProvider, Message } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Compaction configuration.
 */
export interface CompactionConfig {
  /** Enable compaction (default: true) */
  enabled?: boolean;
  /** Token threshold to trigger compaction (default: 80000) */
  tokenThreshold?: number;
  /** Number of recent messages to preserve verbatim (default: 10) */
  preserveRecentCount?: number;
  /** Preserve tool results in recent context (default: true) */
  preserveToolResults?: boolean;
  /** Maximum tokens for the summary (default: 2000) */
  summaryMaxTokens?: number;
  /** Model to use for summarization (optional, uses default) */
  summaryModel?: string;
}

/**
 * Result of a compaction operation.
 */
export interface CompactionResult {
  /** The generated summary */
  summary: string;
  /** Messages preserved verbatim */
  preservedMessages: Message[];
  /** Number of messages that were compacted */
  compactedCount: number;
  /** Token count before compaction */
  tokensBefore: number;
  /** Token count after compaction */
  tokensAfter: number;
  /** Timestamp of compaction */
  compactedAt: string;
}

/**
 * Compaction events.
 */
export type CompactionEvent =
  | { type: 'compaction.check'; currentTokens: number; threshold: number }
  | { type: 'compaction.start'; messageCount: number }
  | { type: 'compaction.complete'; result: CompactionResult }
  | { type: 'compaction.error'; error: string };

export type CompactionEventListener = (event: CompactionEvent) => void;

// =============================================================================
// COMPACTOR
// =============================================================================

/**
 * Handles context compaction.
 */
export class Compactor {
  private config: Required<CompactionConfig>;
  private provider: LLMProvider;
  private listeners: CompactionEventListener[] = [];

  constructor(provider: LLMProvider, config: CompactionConfig = {}) {
    this.provider = provider;
    this.config = {
      enabled: config.enabled ?? true,
      tokenThreshold: config.tokenThreshold ?? 80000,
      preserveRecentCount: config.preserveRecentCount ?? 10,
      preserveToolResults: config.preserveToolResults ?? true,
      summaryMaxTokens: config.summaryMaxTokens ?? 2000,
      summaryModel: config.summaryModel || '',
    };
  }

  /**
   * Estimate token count for messages.
   * Uses a simple heuristic: ~4 characters per token.
   */
  estimateTokens(messages: Message[]): number {
    let totalChars = 0;
    for (const msg of messages) {
      totalChars += msg.content.length;
      if (msg.toolCalls) {
        totalChars += JSON.stringify(msg.toolCalls).length;
      }
    }
    return Math.ceil(totalChars / 4);
  }

  /**
   * Check if compaction is needed.
   */
  shouldCompact(messages: Message[], currentTokens?: number): boolean {
    if (!this.config.enabled) {
      return false;
    }

    const tokens = currentTokens ?? this.estimateTokens(messages);
    this.emit({ type: 'compaction.check', currentTokens: tokens, threshold: this.config.tokenThreshold });

    return tokens >= this.config.tokenThreshold;
  }

  /**
   * Perform compaction on messages.
   */
  async compact(messages: Message[]): Promise<CompactionResult> {
    const tokensBefore = this.estimateTokens(messages);

    // Find system message (always preserve)
    const systemMessage = messages.find(m => m.role === 'system');
    const conversationMessages = messages.filter(m => m.role !== 'system');

    // Split into messages to compact and messages to preserve
    const preserveCount = Math.min(this.config.preserveRecentCount, conversationMessages.length);
    const messagesToCompact = conversationMessages.slice(0, -preserveCount || conversationMessages.length);
    const messagesToPreserve = conversationMessages.slice(-preserveCount);

    this.emit({ type: 'compaction.start', messageCount: messagesToCompact.length });

    // If nothing to compact, return early
    if (messagesToCompact.length === 0) {
      return {
        summary: '',
        preservedMessages: messages,
        compactedCount: 0,
        tokensBefore,
        tokensAfter: tokensBefore,
        compactedAt: new Date().toISOString(),
      };
    }

    // Generate summary
    const summary = await this.generateSummary(messagesToCompact);

    // Build compacted message list
    const compactedMessages: Message[] = [];

    // Add system message if exists
    if (systemMessage) {
      compactedMessages.push(systemMessage);
    }

    // Add summary as a system context message
    if (summary) {
      compactedMessages.push({
        role: 'system',
        content: `[Conversation Summary - Compacted at ${new Date().toISOString()}]\n${summary}`,
      });
    }

    // Add preserved recent messages
    compactedMessages.push(...messagesToPreserve);

    const tokensAfter = this.estimateTokens(compactedMessages);

    const result: CompactionResult = {
      summary,
      preservedMessages: compactedMessages,
      compactedCount: messagesToCompact.length,
      tokensBefore,
      tokensAfter,
      compactedAt: new Date().toISOString(),
    };

    this.emit({ type: 'compaction.complete', result });

    return result;
  }

  /**
   * Generate a summary of messages using the LLM.
   */
  private async generateSummary(messages: Message[]): Promise<string> {
    // Format messages for summarization
    const conversationText = messages.map(m => {
      const role = m.role === 'assistant' ? 'Assistant' : m.role === 'user' ? 'User' : 'System';
      let content = m.content;

      // Truncate very long messages
      if (content.length > 2000) {
        content = content.slice(0, 2000) + '... [truncated]';
      }

      // Include tool calls
      if (m.toolCalls && m.toolCalls.length > 0) {
        const toolNames = m.toolCalls.map(tc => tc.name).join(', ');
        content += `\n[Used tools: ${toolNames}]`;
      }

      return `${role}: ${content}`;
    }).join('\n\n');

    const summaryPrompt = `Summarize this conversation concisely, preserving:
1. Key decisions and actions taken
2. Important files, paths, or code discussed
3. Current task/goal being worked on
4. Any errors or issues encountered
5. Key findings or conclusions

Keep the summary structured and under ${this.config.summaryMaxTokens} tokens.

Conversation to summarize:
---
${conversationText}
---

Summary:`;

    try {
      const response = await this.provider.chat([
        {
          role: 'system',
          content: 'You are a conversation summarizer. Create concise, structured summaries that preserve key context.',
        },
        { role: 'user', content: summaryPrompt },
      ], {
        model: this.config.summaryModel || undefined,
      });

      return response.content.trim();
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'compaction.error', error });

      // Fallback: simple extraction of key info
      return this.fallbackSummary(messages);
    }
  }

  /**
   * Fallback summary when LLM call fails.
   */
  private fallbackSummary(messages: Message[]): string {
    const lines: string[] = ['[Auto-generated summary - LLM unavailable]'];

    // Extract user requests
    const userMessages = messages.filter(m => m.role === 'user');
    if (userMessages.length > 0) {
      lines.push('User requests:');
      for (const msg of userMessages.slice(0, 5)) {
        const preview = msg.content.slice(0, 100).replace(/\n/g, ' ');
        lines.push(`- ${preview}${msg.content.length > 100 ? '...' : ''}`);
      }
    }

    // Extract tool usage
    const toolCalls = messages
      .filter(m => m.toolCalls && m.toolCalls.length > 0)
      .flatMap(m => m.toolCalls!)
      .map(tc => tc.name);

    const uniqueTools = [...new Set(toolCalls)];
    if (uniqueTools.length > 0) {
      lines.push(`Tools used: ${uniqueTools.join(', ')}`);
    }

    return lines.join('\n');
  }

  /**
   * Get current configuration.
   */
  getConfig(): Required<CompactionConfig> {
    return { ...this.config };
  }

  /**
   * Update configuration.
   */
  updateConfig(updates: Partial<CompactionConfig>): void {
    Object.assign(this.config, updates);
  }

  /**
   * Subscribe to events.
   */
  on(listener: CompactionEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Emit an event.
   */
  private emit(event: CompactionEvent): void {
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
 * Create a compactor.
 */
export function createCompactor(
  provider: LLMProvider,
  config?: CompactionConfig
): Compactor {
  return new Compactor(provider, config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format compaction result for display.
 */
export function formatCompactionResult(result: CompactionResult): string {
  const reduction = Math.round((1 - result.tokensAfter / result.tokensBefore) * 100);

  return `Context Compaction Complete:
  Messages compacted: ${result.compactedCount}
  Tokens before: ${result.tokensBefore.toLocaleString()}
  Tokens after: ${result.tokensAfter.toLocaleString()}
  Reduction: ${reduction}%`;
}

/**
 * Get context usage info.
 */
export function getContextUsage(
  messages: Message[],
  threshold: number
): { tokens: number; percent: number; shouldCompact: boolean } {
  const tokens = messages.reduce((sum, m) => sum + Math.ceil(m.content.length / 4), 0);
  const percent = Math.round((tokens / threshold) * 100);

  return {
    tokens,
    percent,
    shouldCompact: percent >= 80,
  };
}

// =============================================================================
// CONTEXT BREAKDOWN
// =============================================================================

/**
 * Tool definition for token estimation.
 */
export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema?: unknown;
}

/**
 * Context breakdown by category.
 */
export interface ContextBreakdown {
  /** Total estimated tokens */
  total: number;
  /** System prompt tokens */
  systemPrompt: number;
  /** Tool schema tokens (definitions) */
  toolSchemas: number;
  /** Number of tools */
  toolCount: number;
  /** Rules content tokens */
  rulesContent: number;
  /** Memory context tokens */
  memoryContext: number;
  /** Conversation tokens (user + assistant messages) */
  conversation: number;
  /** Number of conversation messages */
  messageCount: number;

  // === MCP-specific stats (lazy loading) ===

  /** Tokens used by MCP tool summaries (lazy mode) */
  mcpToolSummaries: number;
  /** Tokens used by fully loaded MCP tool definitions */
  mcpToolDefinitions: number;
  /** Number of MCP tools as summaries only */
  mcpSummaryCount: number;
  /** Number of fully loaded MCP tools */
  mcpLoadedCount: number;

  /** Breakdown as percentages */
  percentages: {
    systemPrompt: number;
    toolSchemas: number;
    rulesContent: number;
    memoryContext: number;
    conversation: number;
    mcpTools?: number;
  };
}

/**
 * MCP context stats for breakdown calculation.
 */
export interface MCPBreakdownStats {
  summaryTokens: number;
  definitionTokens: number;
  summaryCount: number;
  loadedCount: number;
}

/**
 * Estimate tokens for a string using ~4 chars per token heuristic.
 */
function estimateTokensForString(str: string): number {
  return Math.ceil(str.length / 4);
}

/**
 * Estimate tokens for tool schemas.
 */
function estimateToolSchemaTokens(tools: ToolDefinition[]): number {
  let total = 0;
  for (const tool of tools) {
    // Tool name + description
    total += estimateTokensForString(tool.name);
    total += estimateTokensForString(tool.description);
    // Input schema (JSON stringified)
    if (tool.inputSchema) {
      total += estimateTokensForString(JSON.stringify(tool.inputSchema));
    }
  }
  return total;
}

/**
 * Get detailed context breakdown showing where tokens are being used.
 * Supports MCP-specific stats when mcpStats is provided.
 */
export function getContextBreakdown(
  messages: Message[],
  options: {
    tools?: ToolDefinition[];
    rulesContent?: string;
    memoryContext?: string;
    /** MCP stats from MCPClient.getContextStats() */
    mcpStats?: MCPBreakdownStats;
  } = {}
): ContextBreakdown {
  const { tools = [], rulesContent = '', memoryContext = '', mcpStats } = options;

  // Extract system message
  const systemMessage = messages.find(m => m.role === 'system');
  const systemPromptTokens = systemMessage
    ? estimateTokensForString(systemMessage.content)
    : 0;

  // Tool schemas (non-MCP tools)
  const toolSchemaTokens = estimateToolSchemaTokens(tools);

  // Rules content (often embedded in system prompt, but track separately if provided)
  const rulesTokens = estimateTokensForString(rulesContent);

  // Memory context
  const memoryTokens = estimateTokensForString(memoryContext);

  // Conversation messages (excluding system)
  const conversationMessages = messages.filter(m => m.role !== 'system');
  const conversationTokens = conversationMessages.reduce((sum, m) => {
    let tokens = estimateTokensForString(m.content);
    // Include tool calls in assistant messages
    if (m.toolCalls && m.toolCalls.length > 0) {
      tokens += estimateTokensForString(JSON.stringify(m.toolCalls));
    }
    return sum + tokens;
  }, 0);

  // MCP-specific tokens
  const mcpSummaryTokens = mcpStats?.summaryTokens ?? 0;
  const mcpDefinitionTokens = mcpStats?.definitionTokens ?? 0;
  const mcpTotalTokens = mcpSummaryTokens + mcpDefinitionTokens;

  // Calculate total (include MCP tokens)
  const total = systemPromptTokens + toolSchemaTokens + rulesTokens + memoryTokens + conversationTokens + mcpTotalTokens;

  // Calculate percentages
  const safePercent = (value: number) => total > 0 ? Math.round((value / total) * 100) : 0;

  return {
    total,
    systemPrompt: systemPromptTokens,
    toolSchemas: toolSchemaTokens,
    toolCount: tools.length,
    rulesContent: rulesTokens,
    memoryContext: memoryTokens,
    conversation: conversationTokens,
    messageCount: conversationMessages.length,

    // MCP stats
    mcpToolSummaries: mcpSummaryTokens,
    mcpToolDefinitions: mcpDefinitionTokens,
    mcpSummaryCount: mcpStats?.summaryCount ?? 0,
    mcpLoadedCount: mcpStats?.loadedCount ?? 0,

    percentages: {
      systemPrompt: safePercent(systemPromptTokens),
      toolSchemas: safePercent(toolSchemaTokens),
      rulesContent: safePercent(rulesTokens),
      memoryContext: safePercent(memoryTokens),
      conversation: safePercent(conversationTokens),
      mcpTools: mcpTotalTokens > 0 ? safePercent(mcpTotalTokens) : undefined,
    },
  };
}

/**
 * Format context breakdown for display.
 */
export function formatContextBreakdown(breakdown: ContextBreakdown): string {
  const formatTokens = (tokens: number, percent: number) => {
    const bar = '█'.repeat(Math.min(20, Math.round(percent / 5))) +
                '░'.repeat(Math.max(0, 20 - Math.round(percent / 5)));
    return `[${bar}] ${tokens.toLocaleString().padStart(6)} tokens (${percent}%)`;
  };

  const lines = [
    `Context Token Breakdown (Total: ~${breakdown.total.toLocaleString()} tokens)`,
    '',
    `  System prompt:   ${formatTokens(breakdown.systemPrompt, breakdown.percentages.systemPrompt)}`,
    `  Tool schemas:    ${formatTokens(breakdown.toolSchemas, breakdown.percentages.toolSchemas)} (${breakdown.toolCount} tools)`,
    `  Rules content:   ${formatTokens(breakdown.rulesContent, breakdown.percentages.rulesContent)}`,
    `  Memory context:  ${formatTokens(breakdown.memoryContext, breakdown.percentages.memoryContext)}`,
    `  Conversation:    ${formatTokens(breakdown.conversation, breakdown.percentages.conversation)} (${breakdown.messageCount} messages)`,
  ];

  // Add MCP section if there are MCP tools
  const totalMcpTools = breakdown.mcpSummaryCount + breakdown.mcpLoadedCount;
  if (totalMcpTools > 0) {
    const mcpTotalTokens = breakdown.mcpToolSummaries + breakdown.mcpToolDefinitions;
    const mcpPercent = breakdown.percentages.mcpTools ?? 0;

    // Calculate savings estimate (full load vs current)
    const fullLoadEstimate = totalMcpTools * 200; // ~200 tokens per full tool
    const savings = fullLoadEstimate > 0
      ? Math.round((1 - mcpTotalTokens / fullLoadEstimate) * 100)
      : 0;

    lines.push('');
    lines.push('  MCP Tool Context:');
    lines.push(`    Tool summaries:   ${breakdown.mcpSummaryCount.toString().padStart(3)} tools (~${breakdown.mcpToolSummaries.toLocaleString()} tokens)`);
    lines.push(`    Full definitions: ${breakdown.mcpLoadedCount.toString().padStart(3)} tools (~${breakdown.mcpToolDefinitions.toLocaleString()} tokens)`);
    lines.push(`    Total:            ${totalMcpTools.toString().padStart(3)} tools (~${mcpTotalTokens.toLocaleString()} tokens, ${mcpPercent}%)`);

    if (savings > 0) {
      lines.push(`    Context savings:  ${savings}% (vs loading all schemas)`);
    }
  }

  return lines.join('\n');
}
