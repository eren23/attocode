/**
 * Context Manager
 *
 * Manages conversation context for persistent, multi-turn interactions.
 * This solves the "first question" problem where each question starts fresh.
 */

import type { Message, MessageWithContent } from '../../02-provider-abstraction/types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Serializable conversation state.
 */
export interface ConversationState {
  /** Files that have been read in this session */
  filesRead: string[];
  /** Files that have been modified in this session */
  filesModified: string[];
  /** Commands that have been executed */
  commandsExecuted: string[];
  /** Current working task/context */
  currentTask: string;
  /** Custom metadata */
  metadata: Record<string, unknown>;
}

/**
 * A stored message with timestamp.
 */
export interface StoredMessage {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string | Array<{ type: 'text'; text: string }>;
  timestamp: number;
  /** For tool messages */
  toolCallId?: string;
  /** For assistant messages with tool calls */
  toolCalls?: Array<{
    id: string;
    type: 'function';
    function: { name: string; arguments: string };
  }>;
}

/**
 * Session metadata for persistence.
 */
export interface SessionMetadata {
  id: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
  state: ConversationState;
}

/**
 * Context manager configuration.
 */
export interface ContextManagerConfig {
  /** Maximum messages before triggering compaction */
  maxMessages?: number;
  /** Maximum estimated tokens before triggering compaction */
  maxTokens?: number;
  /** Storage backend */
  storage?: ContextStorage;
}

/**
 * Storage backend interface.
 * Implement this to customize where conversations are stored.
 */
export interface ContextStorage {
  /** Save messages for a session */
  saveMessages(sessionId: string, messages: StoredMessage[]): Promise<void>;
  /** Load messages for a session */
  loadMessages(sessionId: string): Promise<StoredMessage[]>;
  /** Save session metadata */
  saveMetadata(sessionId: string, metadata: SessionMetadata): Promise<void>;
  /** Load session metadata */
  loadMetadata(sessionId: string): Promise<SessionMetadata | null>;
  /** List all sessions */
  listSessions(): Promise<SessionMetadata[]>;
  /** Delete a session */
  deleteSession(sessionId: string): Promise<void>;
}

// =============================================================================
// CONTEXT MANAGER
// =============================================================================

/**
 * Manages conversation context with persistence and compaction.
 *
 * Key features:
 * - Persistent conversation history across questions
 * - State tracking (files read, modified, commands run)
 * - Automatic compaction when context grows too large
 * - Pluggable storage backends
 *
 * @example
 * ```typescript
 * const contextManager = new ContextManager({
 *   maxMessages: 50,
 *   storage: new FilesystemContextStorage('./sessions'),
 * });
 *
 * // Start or resume a session
 * await contextManager.loadSession('user-123');
 *
 * // Add messages as conversation progresses
 * contextManager.addMessage({ role: 'user', content: 'Hello' });
 * contextManager.addMessage({ role: 'assistant', content: 'Hi there!' });
 *
 * // Get full context for API call
 * const messages = contextManager.getMessages();
 *
 * // Persist periodically or on exit
 * await contextManager.saveSession();
 * ```
 */
export class ContextManager {
  private sessionId: string | null = null;
  private messages: StoredMessage[] = [];
  private state: ConversationState = {
    filesRead: [],
    filesModified: [],
    commandsExecuted: [],
    currentTask: '',
    metadata: {},
  };
  private config: { maxMessages: number; maxTokens: number; storage: ContextStorage | null };
  private storage: ContextStorage | null;
  private dirty = false;

  constructor(config: ContextManagerConfig = {}) {
    this.config = {
      maxMessages: config.maxMessages ?? 100,
      maxTokens: config.maxTokens ?? 100000,
      storage: config.storage ?? null,
    };
    this.storage = this.config.storage ?? null;
  }

  // ===========================================================================
  // SESSION MANAGEMENT
  // ===========================================================================

  /**
   * Start a new session.
   */
  newSession(sessionId?: string): string {
    this.sessionId = sessionId ?? this.generateSessionId();
    this.messages = [];
    this.state = {
      filesRead: [],
      filesModified: [],
      commandsExecuted: [],
      currentTask: '',
      metadata: {},
    };
    this.dirty = true;
    return this.sessionId;
  }

  /**
   * Load an existing session or create new one.
   */
  async loadSession(sessionId: string): Promise<boolean> {
    if (!this.storage) {
      this.newSession(sessionId);
      return false;
    }

    try {
      const metadata = await this.storage.loadMetadata(sessionId);
      if (!metadata) {
        this.newSession(sessionId);
        return false;
      }

      const messages = await this.storage.loadMessages(sessionId);
      this.sessionId = sessionId;
      this.messages = messages;
      this.state = metadata.state;
      this.dirty = false;
      return true;
    } catch {
      this.newSession(sessionId);
      return false;
    }
  }

  /**
   * Save current session to storage.
   */
  async saveSession(): Promise<void> {
    if (!this.storage || !this.sessionId || !this.dirty) {
      return;
    }

    const metadata: SessionMetadata = {
      id: this.sessionId,
      createdAt: this.messages[0]?.timestamp ?? Date.now(),
      updatedAt: Date.now(),
      messageCount: this.messages.length,
      state: this.state,
    };

    await this.storage.saveMessages(this.sessionId, this.messages);
    await this.storage.saveMetadata(this.sessionId, metadata);
    this.dirty = false;
  }

  /**
   * Get current session ID.
   */
  getSessionId(): string | null {
    return this.sessionId;
  }

  // ===========================================================================
  // MESSAGE MANAGEMENT
  // ===========================================================================

  /**
   * Add a message to the conversation.
   */
  addMessage(message: Message | MessageWithContent | StoredMessage): void {
    const stored: StoredMessage = {
      role: message.role as StoredMessage['role'],
      content: message.content,
      timestamp: 'timestamp' in message ? message.timestamp : Date.now(),
    };

    // Copy tool-related fields if present
    if ('tool_call_id' in message && message.tool_call_id) {
      stored.toolCallId = message.tool_call_id;
    }
    if ('tool_calls' in message && message.tool_calls) {
      stored.toolCalls = message.tool_calls;
    }

    this.messages.push(stored);
    this.dirty = true;
  }

  /**
   * Add a user message.
   */
  addUserMessage(content: string): void {
    this.addMessage({ role: 'user', content });
  }

  /**
   * Add an assistant message.
   */
  addAssistantMessage(content: string): void {
    this.addMessage({ role: 'assistant', content });
  }

  /**
   * Add a system message.
   */
  addSystemMessage(content: string): void {
    this.addMessage({ role: 'system', content });
  }

  /**
   * Get all messages for API call.
   * Converts stored messages to API format.
   */
  getMessages(): (Message | MessageWithContent)[] {
    return this.messages.map(m => {
      const msg: Record<string, unknown> = {
        role: m.role,
        content: m.content,
      };

      if (m.toolCallId) {
        msg.tool_call_id = m.toolCallId;
      }
      if (m.toolCalls) {
        msg.tool_calls = m.toolCalls;
      }

      return msg as unknown as Message | MessageWithContent;
    });
  }

  /**
   * Get message count.
   */
  getMessageCount(): number {
    return this.messages.length;
  }

  /**
   * Clear all messages (keeps session).
   */
  clearMessages(): void {
    this.messages = [];
    this.dirty = true;
  }

  // ===========================================================================
  // STATE MANAGEMENT
  // ===========================================================================

  /**
   * Get current conversation state.
   */
  getState(): ConversationState {
    return { ...this.state };
  }

  /**
   * Update conversation state.
   */
  updateState(updates: Partial<ConversationState>): void {
    this.state = { ...this.state, ...updates };
    this.dirty = true;
  }

  /**
   * Track a file read operation.
   */
  trackFileRead(path: string): void {
    if (!this.state.filesRead.includes(path)) {
      this.state.filesRead.push(path);
      this.dirty = true;
    }
  }

  /**
   * Track a file modification.
   */
  trackFileModified(path: string): void {
    if (!this.state.filesModified.includes(path)) {
      this.state.filesModified.push(path);
      this.dirty = true;
    }
  }

  /**
   * Track a command execution.
   */
  trackCommand(command: string): void {
    this.state.commandsExecuted.push(command);
    this.dirty = true;
  }

  /**
   * Set current task.
   */
  setCurrentTask(task: string): void {
    this.state.currentTask = task;
    this.dirty = true;
  }

  // ===========================================================================
  // CONTEXT INJECTION
  // ===========================================================================

  /**
   * Build a context summary to inject into system prompt.
   * This helps the LLM understand what's been done in this session.
   */
  buildContextSummary(): string {
    const parts: string[] = [];

    if (this.state.currentTask) {
      parts.push(`Current task: ${this.state.currentTask}`);
    }

    if (this.state.filesRead.length > 0) {
      parts.push(`Files read: ${this.state.filesRead.slice(-10).join(', ')}`);
    }

    if (this.state.filesModified.length > 0) {
      parts.push(`Files modified: ${this.state.filesModified.join(', ')}`);
    }

    if (this.state.commandsExecuted.length > 0) {
      const recentCommands = this.state.commandsExecuted.slice(-5);
      parts.push(`Recent commands: ${recentCommands.join(', ')}`);
    }

    return parts.length > 0 ? parts.join('\n') : '';
  }

  // ===========================================================================
  // COMPACTION
  // ===========================================================================

  /**
   * Check if compaction is needed.
   */
  needsCompaction(): boolean {
    if (this.messages.length > this.config.maxMessages) {
      return true;
    }

    const estimatedTokens = this.estimateTokens();
    if (estimatedTokens > this.config.maxTokens) {
      return true;
    }

    return false;
  }

  /**
   * Estimate token count for current messages.
   * Rough approximation: ~4 characters per token.
   */
  estimateTokens(): number {
    let totalChars = 0;

    for (const msg of this.messages) {
      if (typeof msg.content === 'string') {
        totalChars += msg.content.length;
      } else if (Array.isArray(msg.content)) {
        for (const part of msg.content) {
          totalChars += part.text.length;
        }
      }
    }

    return Math.ceil(totalChars / 4);
  }

  /**
   * Compact messages using a simple truncation strategy.
   * Keeps system messages and recent messages.
   *
   * For more advanced compaction, use the compaction strategies module.
   */
  compactSimple(keepCount: number = 20): void {
    if (this.messages.length <= keepCount) {
      return;
    }

    // Separate system messages from conversation
    const systemMessages = this.messages.filter(m => m.role === 'system');
    const conversationMessages = this.messages.filter(m => m.role !== 'system');

    // Keep only recent conversation messages
    const recentMessages = conversationMessages.slice(-keepCount);

    this.messages = [...systemMessages, ...recentMessages];
    this.dirty = true;
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  private generateSessionId(): string {
    return `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a new context manager.
 */
export function createContextManager(
  config?: ContextManagerConfig
): ContextManager {
  return new ContextManager(config);
}
