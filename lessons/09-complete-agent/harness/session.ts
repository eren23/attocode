/**
 * Session Management
 *
 * A session owns the lifecycle of an agent conversation,
 * including its context, subagents, and resources.
 */

import { ContextManager, createContextManager } from '../context/context-manager.js';
import { FilesystemContextStorage } from '../context/filesystem-context.js';
import type { LLMProviderWithTools } from '../../02-provider-abstraction/types.js';
import type { ToolRegistry } from '../../03-tool-system/registry.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Session configuration.
 */
export interface SessionConfig {
  /** Unique session identifier */
  id?: string;
  /** LLM provider to use */
  provider: LLMProviderWithTools;
  /** Tool registry */
  toolRegistry: ToolRegistry;
  /** Model override */
  model?: string;
  /** Maximum agent iterations */
  maxIterations?: number;
  /** Storage directory for persistence */
  storageDir?: string;
  /** Parent session (for subagents) */
  parentSession?: Session;
}

/**
 * Session state enumeration.
 */
export type SessionState = 'idle' | 'running' | 'paused' | 'completed' | 'error';

/**
 * Session statistics.
 */
export interface SessionStats {
  messagesCount: number;
  toolCallsCount: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCachedTokens: number;
  subagentCount: number;
  startTime: number;
  lastActivityTime: number;
}

// =============================================================================
// SESSION CLASS
// =============================================================================

/**
 * Represents an agent session with its context, state, and resources.
 *
 * A session provides:
 * - Context management (conversation history, state tracking)
 * - Subagent tracking (parent-child relationships)
 * - Resource lifecycle (cleanup when session ends)
 * - Statistics tracking
 *
 * @example
 * ```typescript
 * const session = new Session({
 *   provider,
 *   toolRegistry,
 *   storageDir: './.agent-sessions',
 * });
 *
 * await session.initialize();
 *
 * // Run agent tasks
 * await session.runTask('Read the README file');
 *
 * // Clean up
 * await session.cleanup();
 * ```
 */
export class Session {
  readonly id: string;
  readonly contextManager: ContextManager;
  readonly provider: LLMProviderWithTools;
  readonly toolRegistry: ToolRegistry;
  readonly model?: string;
  readonly maxIterations: number;
  readonly parentSession?: Session;

  private _state: SessionState = 'idle';
  private subagents: Map<string, Session> = new Map();
  private stats: SessionStats;

  constructor(config: SessionConfig) {
    this.id = config.id ?? this.generateId();
    this.provider = config.provider;
    this.toolRegistry = config.toolRegistry;
    this.model = config.model;
    this.maxIterations = config.maxIterations ?? 20;
    this.parentSession = config.parentSession;

    // Initialize context manager with storage
    const storage = config.storageDir
      ? new FilesystemContextStorage(config.storageDir)
      : undefined;

    this.contextManager = createContextManager({
      maxMessages: 100,
      maxTokens: 100000,
      storage,
    });

    // Initialize stats
    this.stats = {
      messagesCount: 0,
      toolCallsCount: 0,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      totalCachedTokens: 0,
      subagentCount: 0,
      startTime: Date.now(),
      lastActivityTime: Date.now(),
    };

    // Register with parent if this is a subagent
    if (this.parentSession) {
      this.parentSession.registerSubagent(this);
    }
  }

  // ===========================================================================
  // LIFECYCLE
  // ===========================================================================

  /**
   * Initialize the session (load existing context if available).
   */
  async initialize(): Promise<boolean> {
    const loaded = await this.contextManager.loadSession(this.id);
    this._state = 'idle';
    return loaded;
  }

  /**
   * Save session state to storage.
   */
  async save(): Promise<void> {
    await this.contextManager.saveSession();
  }

  /**
   * Clean up session resources.
   */
  async cleanup(): Promise<void> {
    // Clean up all subagents first
    for (const subagent of this.subagents.values()) {
      await subagent.cleanup();
    }
    this.subagents.clear();

    // Save final state
    await this.save();

    // Unregister from parent
    if (this.parentSession) {
      this.parentSession.unregisterSubagent(this.id);
    }

    this._state = 'completed';
  }

  // ===========================================================================
  // STATE MANAGEMENT
  // ===========================================================================

  /**
   * Get current session state.
   */
  get state(): SessionState {
    return this._state;
  }

  /**
   * Set session state.
   */
  setState(state: SessionState): void {
    this._state = state;
    this.stats.lastActivityTime = Date.now();
  }

  /**
   * Get session statistics.
   */
  getStats(): SessionStats {
    return {
      ...this.stats,
      messagesCount: this.contextManager.getMessageCount(),
      subagentCount: this.subagents.size,
    };
  }

  /**
   * Update statistics after an agent turn.
   */
  updateStats(usage: {
    inputTokens: number;
    outputTokens: number;
    cachedTokens?: number;
  }, toolCallCount: number = 0): void {
    this.stats.totalInputTokens += usage.inputTokens;
    this.stats.totalOutputTokens += usage.outputTokens;
    this.stats.totalCachedTokens += usage.cachedTokens ?? 0;
    this.stats.toolCallsCount += toolCallCount;
    this.stats.lastActivityTime = Date.now();
  }

  // ===========================================================================
  // SUBAGENT MANAGEMENT
  // ===========================================================================

  /**
   * Register a subagent with this session.
   */
  registerSubagent(subagent: Session): void {
    this.subagents.set(subagent.id, subagent);
    this.stats.subagentCount = this.subagents.size;
  }

  /**
   * Unregister a subagent.
   */
  unregisterSubagent(subagentId: string): void {
    this.subagents.delete(subagentId);
    this.stats.subagentCount = this.subagents.size;
  }

  /**
   * Get all active subagents.
   */
  getSubagents(): Session[] {
    return Array.from(this.subagents.values());
  }

  /**
   * Create a subagent session.
   */
  createSubagent(config?: Partial<SessionConfig>): Session {
    return new Session({
      provider: this.provider,
      toolRegistry: this.toolRegistry,
      model: this.model,
      maxIterations: this.maxIterations,
      ...config,
      parentSession: this,
    });
  }

  // ===========================================================================
  // CONTEXT SHORTCUTS
  // ===========================================================================

  /**
   * Add a user message to the conversation.
   */
  addUserMessage(content: string): void {
    this.contextManager.addUserMessage(content);
    this.stats.lastActivityTime = Date.now();
  }

  /**
   * Add an assistant message to the conversation.
   */
  addAssistantMessage(content: string): void {
    this.contextManager.addAssistantMessage(content);
    this.stats.lastActivityTime = Date.now();
  }

  /**
   * Get conversation history for API call.
   */
  getMessages() {
    return this.contextManager.getMessages();
  }

  /**
   * Build context summary for system prompt.
   */
  buildContextSummary(): string {
    return this.contextManager.buildContextSummary();
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  private generateId(): string {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).slice(2, 8);
    return `session-${timestamp}-${random}`;
  }

  /**
   * Check if this is a subagent session.
   */
  isSubagent(): boolean {
    return this.parentSession !== undefined;
  }

  /**
   * Get the root session (top-level parent).
   */
  getRootSession(): Session {
    let current: Session = this;
    while (current.parentSession) {
      current = current.parentSession;
    }
    return current;
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a new session.
 */
export function createSession(config: SessionConfig): Session {
  return new Session(config);
}
