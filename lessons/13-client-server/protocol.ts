/**
 * Lesson 13: Protocol
 *
 * Message protocol for client/server communication.
 * Supports JSON-RPC style request/response and events.
 */

import type {
  ProtocolMessage,
  APIRequest,
  APIResponse,
  APIError,
  ErrorCode,
  AgentEvent,
} from './types.js';
import { generateId } from './types.js';

// =============================================================================
// PROTOCOL VERSION
// =============================================================================

export const PROTOCOL_VERSION = '1.0.0';

// =============================================================================
// MESSAGE BUILDERS
// =============================================================================

/**
 * Build a request message.
 */
export function buildRequest<T>(method: string, params: T): ProtocolMessage {
  const request: APIRequest<T> = {
    id: generateId(),
    method,
    params,
    timestamp: new Date(),
  };

  return {
    version: PROTOCOL_VERSION,
    type: 'request',
    payload: request,
  };
}

/**
 * Build a success response.
 */
export function buildSuccessResponse<T>(
  requestId: string,
  data: T
): ProtocolMessage {
  const response: APIResponse<T> = {
    id: requestId,
    success: true,
    data,
    timestamp: new Date(),
  };

  return {
    version: PROTOCOL_VERSION,
    type: 'response',
    payload: response,
  };
}

/**
 * Build an error response.
 */
export function buildErrorResponse(
  requestId: string,
  code: ErrorCode,
  message: string,
  details?: Record<string, unknown>
): ProtocolMessage {
  const response: APIResponse = {
    id: requestId,
    success: false,
    error: { code, message, details },
    timestamp: new Date(),
  };

  return {
    version: PROTOCOL_VERSION,
    type: 'response',
    payload: response,
  };
}

/**
 * Build an event message.
 */
export function buildEvent(event: AgentEvent): ProtocolMessage {
  return {
    version: PROTOCOL_VERSION,
    type: 'event',
    payload: event,
  };
}

/**
 * Build a ping message.
 */
export function buildPing(): ProtocolMessage {
  return {
    version: PROTOCOL_VERSION,
    type: 'ping',
    payload: Date.now(),
  };
}

/**
 * Build a pong message.
 */
export function buildPong(timestamp: number): ProtocolMessage {
  return {
    version: PROTOCOL_VERSION,
    type: 'pong',
    payload: { sent: timestamp, received: Date.now() },
  };
}

// =============================================================================
// MESSAGE PARSING
// =============================================================================

/**
 * Parse a protocol message from JSON.
 */
export function parseMessage(json: string): ProtocolMessage {
  try {
    const parsed = JSON.parse(json);

    if (!parsed.version || !parsed.type) {
      throw new Error('Invalid protocol message format');
    }

    return parsed as ProtocolMessage;
  } catch (err) {
    throw new Error(
      `Failed to parse protocol message: ${err instanceof Error ? err.message : String(err)}`
    );
  }
}

/**
 * Serialize a protocol message to JSON.
 */
export function serializeMessage(message: ProtocolMessage): string {
  return JSON.stringify(message);
}

/**
 * Extract request from message.
 */
export function extractRequest<T = unknown>(
  message: ProtocolMessage
): APIRequest<T> | null {
  if (message.type !== 'request') return null;
  return message.payload as APIRequest<T>;
}

/**
 * Extract response from message.
 */
export function extractResponse<T = unknown>(
  message: ProtocolMessage
): APIResponse<T> | null {
  if (message.type !== 'response') return null;
  return message.payload as APIResponse<T>;
}

/**
 * Extract event from message.
 */
export function extractEvent(message: ProtocolMessage): AgentEvent | null {
  if (message.type !== 'event') return null;
  return message.payload as AgentEvent;
}

// =============================================================================
// PROTOCOL HANDLER
// =============================================================================

/**
 * Method handler function type.
 */
export type MethodHandler<P = unknown, R = unknown> = (
  params: P,
  context: HandlerContext
) => Promise<R>;

/**
 * Handler context.
 */
export interface HandlerContext {
  requestId: string;
  clientId?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Protocol handler for routing requests to methods.
 */
export class ProtocolHandler {
  private methods: Map<string, MethodHandler> = new Map();

  /**
   * Register a method handler.
   */
  register<P, R>(method: string, handler: MethodHandler<P, R>): void {
    this.methods.set(method, handler as MethodHandler);
  }

  /**
   * Handle an incoming message.
   */
  async handle(
    message: ProtocolMessage,
    context?: Partial<HandlerContext>
  ): Promise<ProtocolMessage | null> {
    // Handle pings
    if (message.type === 'ping') {
      return buildPong(message.payload as number);
    }

    // Only process requests
    if (message.type !== 'request') {
      return null;
    }

    const request = message.payload as APIRequest;
    const handler = this.methods.get(request.method);

    if (!handler) {
      return buildErrorResponse(
        request.id,
        'INVALID_REQUEST',
        `Unknown method: ${request.method}`
      );
    }

    const handlerContext: HandlerContext = {
      requestId: request.id,
      ...context,
    };

    try {
      const result = await handler(request.params, handlerContext);
      return buildSuccessResponse(request.id, result);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);

      // Check for specific error types
      if (err instanceof SessionNotFoundError) {
        return buildErrorResponse(request.id, 'SESSION_NOT_FOUND', message);
      }
      if (err instanceof RateLimitError) {
        return buildErrorResponse(request.id, 'RATE_LIMITED', message);
      }

      return buildErrorResponse(request.id, 'SERVER_ERROR', message);
    }
  }

  /**
   * List registered methods.
   */
  getMethods(): string[] {
    return Array.from(this.methods.keys());
  }
}

// =============================================================================
// CUSTOM ERRORS
// =============================================================================

export class SessionNotFoundError extends Error {
  constructor(sessionId: string) {
    super(`Session not found: ${sessionId}`);
    this.name = 'SessionNotFoundError';
  }
}

export class RateLimitError extends Error {
  constructor(message: string = 'Rate limit exceeded') {
    super(message);
    this.name = 'RateLimitError';
  }
}

export class SessionExpiredError extends Error {
  constructor(sessionId: string) {
    super(`Session expired: ${sessionId}`);
    this.name = 'SessionExpiredError';
  }
}

// =============================================================================
// REQUEST QUEUE
// =============================================================================

/**
 * Pending request tracker.
 */
interface PendingRequest<T = unknown> {
  resolve: (value: T) => void;
  reject: (error: Error) => void;
  timeout: NodeJS.Timeout;
}

/**
 * Manages pending requests with timeout.
 */
export class RequestQueue {
  private pending: Map<string, PendingRequest> = new Map();
  private defaultTimeout: number;

  constructor(defaultTimeout: number = 30000) {
    this.defaultTimeout = defaultTimeout;
  }

  /**
   * Add a pending request.
   */
  add<T>(requestId: string, timeout?: number): Promise<T> {
    return new Promise((resolve, reject) => {
      const timeoutMs = timeout || this.defaultTimeout;

      const timeoutHandle = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`Request ${requestId} timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      this.pending.set(requestId, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timeout: timeoutHandle,
      });
    });
  }

  /**
   * Resolve a pending request.
   */
  resolve(requestId: string, result: unknown): boolean {
    const pending = this.pending.get(requestId);
    if (!pending) return false;

    clearTimeout(pending.timeout);
    this.pending.delete(requestId);
    pending.resolve(result);
    return true;
  }

  /**
   * Reject a pending request.
   */
  reject(requestId: string, error: Error): boolean {
    const pending = this.pending.get(requestId);
    if (!pending) return false;

    clearTimeout(pending.timeout);
    this.pending.delete(requestId);
    pending.reject(error);
    return true;
  }

  /**
   * Cancel all pending requests.
   */
  cancelAll(reason: string): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timeout);
      pending.reject(new Error(reason));
    }
    this.pending.clear();
  }

  /**
   * Get pending request count.
   */
  get size(): number {
    return this.pending.size;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createProtocolHandler(): ProtocolHandler {
  return new ProtocolHandler();
}

export function createRequestQueue(timeout?: number): RequestQueue {
  return new RequestQueue(timeout);
}
