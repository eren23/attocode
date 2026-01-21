/**
 * Lesson 13: Client
 *
 * Client SDK for connecting to agent servers.
 * Supports request/response and event streaming.
 */

import type {
  ClientConfig,
  Session,
  SessionConfig,
  Message,
  HealthStatus,
  AgentEvent,
  AgentEventListener,
  ConnectionState,
  GetMessagesOptions,
  StreamChunk,
} from './types.js';
import {
  buildRequest,
  parseMessage,
  serializeMessage,
  extractResponse,
  extractEvent,
  RequestQueue,
  createRequestQueue,
} from './protocol.js';
import type { SessionStats } from './session-manager.js';

// =============================================================================
// AGENT CLIENT
// =============================================================================

/**
 * Client for connecting to agent servers.
 */
export class AgentClient {
  private config: ClientConfig;
  private state: ConnectionState = 'disconnected';
  private requestQueue: RequestQueue;
  private eventListeners: Set<AgentEventListener> = new Set();
  private reconnectAttempts: number = 0;
  private serverSimulator?: ServerSimulator;

  constructor(config: ClientConfig) {
    this.config = {
      timeout: 30000,
      autoReconnect: true,
      reconnectDelay: 1000,
      maxReconnectAttempts: 5,
      ...config,
    };
    this.requestQueue = createRequestQueue(this.config.timeout);
  }

  /**
   * Connect to the server.
   */
  async connect(): Promise<void> {
    if (this.state === 'connected') return;

    this.state = 'connecting';

    try {
      // In production, would establish WebSocket connection
      // For demo, we'll use a simulated server
      this.serverSimulator = new ServerSimulator();
      await this.serverSimulator.start();

      this.state = 'connected';
      this.reconnectAttempts = 0;

      console.log(`[Client] Connected to ${this.config.serverUrl}`);
    } catch (err) {
      this.state = 'disconnected';
      throw new Error(`Connection failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  /**
   * Disconnect from the server.
   */
  async disconnect(): Promise<void> {
    if (this.state === 'disconnected') return;

    this.requestQueue.cancelAll('Client disconnected');

    if (this.serverSimulator) {
      await this.serverSimulator.stop();
    }

    this.state = 'disconnected';
    console.log('[Client] Disconnected');
  }

  /**
   * Get connection state.
   */
  getState(): ConnectionState {
    return this.state;
  }

  // ===========================================================================
  // SESSION METHODS
  // ===========================================================================

  /**
   * Create a new session.
   */
  async createSession(config?: SessionConfig): Promise<Session> {
    return this.request<Session>('session.create', config);
  }

  /**
   * Get a session.
   */
  async getSession(sessionId: string): Promise<Session | null> {
    try {
      return await this.request<Session>('session.get', { sessionId });
    } catch (err) {
      if (err instanceof Error && err.message.toLowerCase().includes('session not found')) {
        return null;
      }
      throw err;
    }
  }

  /**
   * List all sessions.
   */
  async listSessions(): Promise<Session[]> {
    return this.request<Session[]>('session.list', {});
  }

  /**
   * Close a session.
   */
  async closeSession(sessionId: string): Promise<void> {
    await this.request<void>('session.close', { sessionId });
  }

  // ===========================================================================
  // MESSAGE METHODS
  // ===========================================================================

  /**
   * Send a message and get response.
   */
  async sendMessage(sessionId: string, content: string): Promise<Message> {
    return this.request<Message>('message.send', { sessionId, content });
  }

  /**
   * Get messages for a session.
   */
  async getMessages(
    sessionId: string,
    options?: GetMessagesOptions
  ): Promise<Message[]> {
    return this.request<Message[]>('message.list', { sessionId, ...options });
  }

  /**
   * Stream a message response.
   */
  async *streamMessage(
    sessionId: string,
    content: string
  ): AsyncIterable<StreamChunk> {
    // In production, would use server-sent events or WebSocket streaming
    // For demo, simulate streaming

    yield { type: 'text', content: 'This ' };
    await new Promise((r) => setTimeout(r, 100));

    yield { type: 'text', content: 'is ' };
    await new Promise((r) => setTimeout(r, 100));

    yield { type: 'text', content: 'a ' };
    await new Promise((r) => setTimeout(r, 100));

    yield { type: 'text', content: 'streamed ' };
    await new Promise((r) => setTimeout(r, 100));

    yield { type: 'text', content: 'response.' };
    await new Promise((r) => setTimeout(r, 100));

    yield { type: 'done', messageId: 'msg-simulated' };
  }

  // ===========================================================================
  // EVENT METHODS
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  subscribe(listener: AgentEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Subscribe to session events.
   */
  async *subscribeToSession(sessionId: string): AsyncIterable<AgentEvent> {
    // In production, would subscribe via WebSocket
    // For demo, simulate some events

    yield {
      type: 'session.status',
      sessionId,
      status: 'active',
    };

    await new Promise((r) => setTimeout(r, 1000));

    yield {
      type: 'session.status',
      sessionId,
      status: 'idle',
    };
  }

  // ===========================================================================
  // CONTROL METHODS
  // ===========================================================================

  /**
   * Cancel ongoing operation.
   */
  async cancel(sessionId: string): Promise<void> {
    // In production, would send cancel request
    console.log(`[Client] Cancel requested for session: ${sessionId}`);
  }

  // ===========================================================================
  // HEALTH METHODS
  // ===========================================================================

  /**
   * Check server health.
   */
  async health(): Promise<HealthStatus> {
    return this.request<HealthStatus>('health', {});
  }

  /**
   * Get server stats.
   */
  async stats(): Promise<SessionStats> {
    return this.request<SessionStats>('stats', {});
  }

  // ===========================================================================
  // INTERNAL METHODS
  // ===========================================================================

  /**
   * Send a request and wait for response.
   */
  private async request<T>(method: string, params: unknown): Promise<T> {
    if (this.state !== 'connected') {
      throw new Error('Not connected');
    }

    const message = buildRequest(method, params);
    const requestId = (message.payload as { id: string }).id;

    // Add to pending queue
    const responsePromise = this.requestQueue.add<T>(requestId);

    // Send request (via simulated server)
    if (this.serverSimulator) {
      const responseStr = await this.serverSimulator.handleRequest(
        serializeMessage(message)
      );

      if (responseStr) {
        const responseMessage = parseMessage(responseStr);
        const response = extractResponse<T>(responseMessage);

        if (response) {
          if (response.success) {
            this.requestQueue.resolve(requestId, response.data);
          } else {
            this.requestQueue.reject(
              requestId,
              new Error(response.error?.message || 'Request failed')
            );
          }
        }
      }
    }

    return responsePromise;
  }

  /**
   * Handle reconnection.
   */
  private async reconnect(): Promise<void> {
    if (!this.config.autoReconnect) return;

    if (this.reconnectAttempts >= (this.config.maxReconnectAttempts || 5)) {
      console.error('[Client] Max reconnect attempts reached');
      return;
    }

    this.state = 'reconnecting';
    this.reconnectAttempts++;

    const delay = this.config.reconnectDelay || 1000;
    await new Promise((r) => setTimeout(r, delay * this.reconnectAttempts));

    try {
      await this.connect();
    } catch (err) {
      console.error('[Client] Reconnect failed:', err);
      await this.reconnect();
    }
  }

  /**
   * Emit event to listeners.
   */
  private emitEvent(event: AgentEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Event listener error:', err);
      }
    }
  }
}

// =============================================================================
// SERVER SIMULATOR
// =============================================================================

/**
 * Simulates server for demo purposes.
 */
class ServerSimulator {
  private server: import('./server.js').AgentServer | null = null;

  async start(): Promise<void> {
    const { createAgentServer } = await import('./server.js');
    this.server = createAgentServer({
      port: 3000,
      host: 'localhost',
      maxSessions: 100,
      sessionTimeout: 30 * 60 * 1000,
    });
    await this.server.start();
  }

  async stop(): Promise<void> {
    if (this.server) {
      await this.server.stop();
    }
  }

  async handleRequest(rawMessage: string): Promise<string | null> {
    if (!this.server) return null;
    return this.server.handleMessage('client-1', rawMessage);
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createAgentClient(config: ClientConfig): AgentClient {
  return new AgentClient(config);
}
