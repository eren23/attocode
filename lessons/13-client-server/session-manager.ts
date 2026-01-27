/**
 * Lesson 13: Session Manager
 *
 * Manages multiple concurrent sessions with lifecycle,
 * timeouts, and cleanup.
 */

import type {
  Session,
  SessionConfig,
  SessionStatus,
  Message,
  MessageRole,
  AgentEvent,
  AgentEventListener,
  TokenUsage,
} from './types.js';
import { generateSessionId, generateMessageId } from './types.js';

// =============================================================================
// SESSION MANAGER
// =============================================================================

/**
 * Manages multiple agent sessions.
 */
export class SessionManager {
  private sessions: Map<string, ManagedSession> = new Map();
  private listeners: Set<AgentEventListener> = new Set();
  private config: SessionManagerConfig;
  private cleanupInterval: NodeJS.Timeout | null = null;

  constructor(config: Partial<SessionManagerConfig> = {}) {
    this.config = {
      maxSessions: config.maxSessions ?? 100,
      defaultTimeout: config.defaultTimeout ?? 30 * 60 * 1000, // 30 minutes
      cleanupIntervalMs: config.cleanupIntervalMs ?? 60 * 1000, // 1 minute
    };

    this.startCleanup();
  }

  /**
   * Create a new session.
   */
  createSession(config: SessionConfig = {}): Session {
    // Check session limit
    if (this.sessions.size >= this.config.maxSessions) {
      throw new Error('Maximum session limit reached');
    }

    const session: Session = {
      id: generateSessionId(),
      config,
      status: 'active',
      createdAt: new Date(),
      lastActivityAt: new Date(),
      messageCount: 0,
      tokenUsage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 },
    };

    const managed: ManagedSession = {
      session,
      messages: [],
      subscribers: new Set(),
    };

    this.sessions.set(session.id, managed);

    return session;
  }

  /**
   * Get a session.
   */
  getSession(sessionId: string): Session | null {
    const managed = this.sessions.get(sessionId);
    if (!managed) return null;

    // Check if expired
    if (this.isExpired(managed)) {
      this.closeSession(sessionId);
      return null;
    }

    return managed.session;
  }

  /**
   * List all active sessions.
   */
  listSessions(): Session[] {
    const sessions: Session[] = [];

    for (const managed of this.sessions.values()) {
      if (!this.isExpired(managed)) {
        sessions.push(managed.session);
      }
    }

    return sessions;
  }

  /**
   * Close a session.
   */
  closeSession(sessionId: string): boolean {
    const managed = this.sessions.get(sessionId);
    if (!managed) return false;

    managed.session.status = 'closed';

    // Notify subscribers
    this.emitToSession(sessionId, {
      type: 'session.status',
      sessionId,
      status: 'closed',
    });

    // Clear subscribers
    managed.subscribers.clear();

    // Remove from map
    this.sessions.delete(sessionId);

    return true;
  }

  /**
   * Add a message to a session.
   */
  addMessage(
    sessionId: string,
    role: MessageRole,
    content: string,
    metadata?: Record<string, unknown>
  ): Message {
    const managed = this.sessions.get(sessionId);
    if (!managed) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    const message: Message = {
      id: generateMessageId(),
      sessionId,
      role,
      content,
      timestamp: new Date(),
      metadata,
    };

    managed.messages.push(message);
    managed.session.messageCount++;
    managed.session.lastActivityAt = new Date();

    // Emit event
    this.emitToSession(sessionId, {
      type: 'message.created',
      message,
    });

    return message;
  }

  /**
   * Get messages for a session.
   */
  getMessages(
    sessionId: string,
    options: { limit?: number; before?: string; after?: string } = {}
  ): Message[] {
    const managed = this.sessions.get(sessionId);
    if (!managed) return [];

    let messages = managed.messages;

    // Filter by before/after
    if (options.after) {
      const afterIndex = messages.findIndex((m) => m.id === options.after);
      if (afterIndex !== -1) {
        messages = messages.slice(afterIndex + 1);
      }
    }

    if (options.before) {
      const beforeIndex = messages.findIndex((m) => m.id === options.before);
      if (beforeIndex !== -1) {
        messages = messages.slice(0, beforeIndex);
      }
    }

    // Apply limit
    if (options.limit) {
      messages = messages.slice(-options.limit);
    }

    return messages;
  }

  /**
   * Update session status.
   */
  updateStatus(sessionId: string, status: SessionStatus): void {
    const managed = this.sessions.get(sessionId);
    if (!managed) return;

    managed.session.status = status;
    managed.session.lastActivityAt = new Date();

    this.emitToSession(sessionId, {
      type: 'session.status',
      sessionId,
      status,
    });
  }

  /**
   * Update token usage.
   */
  updateTokenUsage(sessionId: string, input: number, output: number): void {
    const managed = this.sessions.get(sessionId);
    if (!managed) return;

    managed.session.tokenUsage.inputTokens += input;
    managed.session.tokenUsage.outputTokens += output;
    managed.session.tokenUsage.totalTokens += input + output;
  }

  /**
   * Subscribe to session events.
   */
  subscribeToSession(
    sessionId: string,
    listener: AgentEventListener
  ): () => void {
    const managed = this.sessions.get(sessionId);
    if (!managed) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    managed.subscribers.add(listener);

    return () => {
      managed.subscribers.delete(listener);
    };
  }

  /**
   * Subscribe to all events.
   */
  subscribe(listener: AgentEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit event to a session's subscribers.
   */
  emitToSession(sessionId: string, event: AgentEvent): void {
    const managed = this.sessions.get(sessionId);
    if (!managed) return;

    // Notify session subscribers
    for (const listener of managed.subscribers) {
      try {
        listener(event);
      } catch (err) {
        console.error('Session event listener error:', err);
      }
    }

    // Notify global subscribers
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Global event listener error:', err);
      }
    }
  }

  /**
   * Get session statistics.
   */
  getStats(): SessionStats {
    let active = 0;
    let processing = 0;
    let idle = 0;
    let totalMessages = 0;
    let totalTokens = 0;

    for (const managed of this.sessions.values()) {
      const status = managed.session.status;
      if (status === 'active') active++;
      else if (status === 'processing') processing++;
      else if (status === 'idle') idle++;

      totalMessages += managed.session.messageCount;
      totalTokens += managed.session.tokenUsage.totalTokens;
    }

    return {
      totalSessions: this.sessions.size,
      activeSessions: active,
      processingSessions: processing,
      idleSessions: idle,
      totalMessages,
      totalTokens,
    };
  }

  /**
   * Check if session is expired.
   */
  private isExpired(managed: ManagedSession): boolean {
    const timeout = managed.session.config.timeout || this.config.defaultTimeout;
    const elapsed = Date.now() - managed.session.lastActivityAt.getTime();
    return elapsed > timeout;
  }

  /**
   * Start cleanup interval.
   */
  private startCleanup(): void {
    this.cleanupInterval = setInterval(() => {
      this.cleanupExpired();
    }, this.config.cleanupIntervalMs);
  }

  /**
   * Clean up expired sessions.
   */
  private cleanupExpired(): void {
    for (const [sessionId, managed] of this.sessions) {
      if (this.isExpired(managed)) {
        managed.session.status = 'expired';

        this.emitToSession(sessionId, {
          type: 'session.status',
          sessionId,
          status: 'expired',
        });

        this.closeSession(sessionId);
      }
    }
  }

  /**
   * Shutdown the session manager.
   */
  shutdown(): void {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
      this.cleanupInterval = null;
    }

    for (const sessionId of this.sessions.keys()) {
      this.closeSession(sessionId);
    }
  }
}

// =============================================================================
// SUPPORTING TYPES
// =============================================================================

/**
 * Session manager configuration.
 */
interface SessionManagerConfig {
  maxSessions: number;
  defaultTimeout: number;
  cleanupIntervalMs: number;
}

/**
 * Internal managed session.
 */
interface ManagedSession {
  session: Session;
  messages: Message[];
  subscribers: Set<AgentEventListener>;
}

/**
 * Session statistics.
 */
export interface SessionStats {
  totalSessions: number;
  activeSessions: number;
  processingSessions: number;
  idleSessions: number;
  totalMessages: number;
  totalTokens: number;
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createSessionManager(
  config?: Partial<SessionManagerConfig>
): SessionManager {
  return new SessionManager(config);
}
