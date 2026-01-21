/**
 * Lesson 13: Server
 *
 * Agent server that exposes API over HTTP/WebSocket.
 * Handles multiple clients and sessions.
 */

import type {
  ServerConfig,
  SessionConfig,
  Session,
  Message,
  HealthStatus,
  AgentEvent,
  GetMessagesOptions,
} from './types.js';
import {
  ProtocolHandler,
  createProtocolHandler,
  buildEvent,
  parseMessage,
  serializeMessage,
  SessionNotFoundError,
  RateLimitError,
} from './protocol.js';
import { SessionManager, createSessionManager, type SessionStats } from './session-manager.js';

// =============================================================================
// AGENT SERVER
// =============================================================================

/**
 * Agent server implementation.
 * In production, this would use actual HTTP/WebSocket servers.
 */
export class AgentServer {
  private config: ServerConfig;
  private sessions: SessionManager;
  private protocol: ProtocolHandler;
  private startTime: Date;
  private rateLimits: Map<string, RateLimitState> = new Map();
  private connections: Map<string, ServerConnection> = new Map();
  private running: boolean = false;

  constructor(config: ServerConfig) {
    this.config = config;
    this.sessions = createSessionManager({
      maxSessions: config.maxSessions,
      defaultTimeout: config.sessionTimeout,
    });
    this.protocol = createProtocolHandler();
    this.startTime = new Date();

    this.registerMethods();
  }

  /**
   * Start the server.
   */
  async start(): Promise<void> {
    if (this.running) return;

    console.log(`[Server] Starting on ${this.config.host || '0.0.0.0'}:${this.config.port}`);
    // In production, would start HTTP/WebSocket server here

    this.running = true;
    console.log('[Server] Ready to accept connections');
  }

  /**
   * Stop the server.
   */
  async stop(): Promise<void> {
    if (!this.running) return;

    console.log('[Server] Shutting down...');

    // Close all connections
    for (const connection of this.connections.values()) {
      await this.closeConnection(connection.id);
    }

    // Shutdown session manager
    this.sessions.shutdown();

    this.running = false;
    console.log('[Server] Stopped');
  }

  /**
   * Handle incoming connection.
   */
  async handleConnection(connectionId: string): Promise<void> {
    const connection: ServerConnection = {
      id: connectionId,
      connectedAt: new Date(),
      subscriptions: new Set(),
    };

    this.connections.set(connectionId, connection);
    console.log(`[Server] Client connected: ${connectionId}`);
  }

  /**
   * Handle incoming message.
   */
  async handleMessage(
    connectionId: string,
    rawMessage: string
  ): Promise<string | null> {
    // Check rate limit
    if (this.config.rateLimit && !this.checkRateLimit(connectionId)) {
      const errorResponse = {
        version: '1.0.0',
        type: 'response',
        payload: {
          id: 'unknown',
          success: false,
          error: { code: 'RATE_LIMITED', message: 'Rate limit exceeded' },
          timestamp: new Date(),
        },
      };
      return JSON.stringify(errorResponse);
    }

    try {
      const message = parseMessage(rawMessage);
      const response = await this.protocol.handle(message, {
        clientId: connectionId,
      });

      if (response) {
        return serializeMessage(response);
      }

      return null;
    } catch (err) {
      console.error('[Server] Message handling error:', err);
      return null;
    }
  }

  /**
   * Close a connection.
   */
  async closeConnection(connectionId: string): Promise<void> {
    const connection = this.connections.get(connectionId);
    if (!connection) return;

    // Unsubscribe from all sessions
    for (const sessionId of connection.subscriptions) {
      // Would unsubscribe in production
    }

    this.connections.delete(connectionId);
    console.log(`[Server] Client disconnected: ${connectionId}`);
  }

  /**
   * Get session manager for direct access.
   */
  getSessionManager(): SessionManager {
    return this.sessions;
  }

  /**
   * Register API methods.
   */
  private registerMethods(): void {
    // Session management
    this.protocol.register<SessionConfig | undefined, Session>(
      'session.create',
      async (params) => {
        return this.sessions.createSession(params);
      }
    );

    this.protocol.register<{ sessionId: string }, Session | null>(
      'session.get',
      async (params) => {
        const session = this.sessions.getSession(params.sessionId);
        if (!session) {
          throw new SessionNotFoundError(params.sessionId);
        }
        return session;
      }
    );

    this.protocol.register<void, Session[]>('session.list', async () => {
      return this.sessions.listSessions();
    });

    this.protocol.register<{ sessionId: string }, void>(
      'session.close',
      async (params) => {
        const closed = this.sessions.closeSession(params.sessionId);
        if (!closed) {
          throw new SessionNotFoundError(params.sessionId);
        }
      }
    );

    // Messaging
    this.protocol.register<{ sessionId: string; content: string }, Message>(
      'message.send',
      async (params) => {
        const session = this.sessions.getSession(params.sessionId);
        if (!session) {
          throw new SessionNotFoundError(params.sessionId);
        }

        // Add user message
        const userMessage = this.sessions.addMessage(
          params.sessionId,
          'user',
          params.content
        );

        // Simulate assistant response
        this.sessions.updateStatus(params.sessionId, 'processing');

        // In production, would call LLM here
        await this.simulateProcessing(params.sessionId);

        const assistantMessage = this.sessions.addMessage(
          params.sessionId,
          'assistant',
          `This is a simulated response to: "${params.content}"`
        );

        this.sessions.updateStatus(params.sessionId, 'active');

        return assistantMessage;
      }
    );

    this.protocol.register<
      { sessionId: string } & GetMessagesOptions,
      Message[]
    >('message.list', async (params) => {
      const { sessionId, ...options } = params;
      return this.sessions.getMessages(sessionId, options);
    });

    // Health
    this.protocol.register<void, HealthStatus>('health', async () => {
      const stats = this.sessions.getStats();
      const uptime = Date.now() - this.startTime.getTime();

      return {
        status: 'healthy',
        version: '1.0.0',
        uptime,
        activeSessions: stats.activeSessions,
        load: stats.processingSessions / (this.config.maxSessions || 100),
      };
    });

    // Stats
    this.protocol.register<void, SessionStats>('stats', async () => {
      return this.sessions.getStats();
    });
  }

  /**
   * Simulate processing time.
   */
  private async simulateProcessing(sessionId: string): Promise<void> {
    // Emit processing events
    const chunks = ['This', ' is', ' a', ' simulated', ' response'];

    for (const chunk of chunks) {
      await new Promise((r) => setTimeout(r, 100));
      this.sessions.emitToSession(sessionId, {
        type: 'message.delta',
        messageId: 'temp',
        delta: chunk,
      });
    }
  }

  /**
   * Check rate limit for a connection.
   */
  private checkRateLimit(connectionId: string): boolean {
    if (!this.config.rateLimit) return true;

    const now = Date.now();
    let state = this.rateLimits.get(connectionId);

    if (!state) {
      state = { count: 0, windowStart: now };
      this.rateLimits.set(connectionId, state);
    }

    // Reset window if expired
    if (now - state.windowStart > this.config.rateLimit.windowMs) {
      state.count = 0;
      state.windowStart = now;
    }

    // Check limit
    if (state.count >= this.config.rateLimit.maxRequests) {
      return false;
    }

    state.count++;
    return true;
  }
}

// =============================================================================
// SUPPORTING TYPES
// =============================================================================

/**
 * Server connection state.
 */
interface ServerConnection {
  id: string;
  connectedAt: Date;
  subscriptions: Set<string>;
}

/**
 * Rate limit state.
 */
interface RateLimitState {
  count: number;
  windowStart: number;
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createAgentServer(config: ServerConfig): AgentServer {
  return new AgentServer(config);
}
