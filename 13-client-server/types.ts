/**
 * Lesson 13: Client/Server Types
 *
 * Types for agent client/server architecture,
 * enabling separation of UI from agent logic.
 */

// =============================================================================
// SESSION TYPES
// =============================================================================

/**
 * Session configuration.
 */
export interface SessionConfig {
  /** Model to use */
  model?: string;

  /** System prompt override */
  systemPrompt?: string;

  /** Maximum tokens per response */
  maxTokens?: number;

  /** Temperature for generation */
  temperature?: number;

  /** Available tools */
  tools?: string[];

  /** Session timeout in ms */
  timeout?: number;

  /** Session metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Session state.
 */
export interface Session {
  /** Unique session ID */
  id: string;

  /** Session configuration */
  config: SessionConfig;

  /** Session status */
  status: SessionStatus;

  /** Creation timestamp */
  createdAt: Date;

  /** Last activity timestamp */
  lastActivityAt: Date;

  /** Message count */
  messageCount: number;

  /** Token usage */
  tokenUsage: TokenUsage;
}

/**
 * Session status.
 */
export type SessionStatus =
  | 'active'
  | 'idle'
  | 'processing'
  | 'expired'
  | 'closed';

/**
 * Token usage tracking.
 */
export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

// =============================================================================
// MESSAGE TYPES
// =============================================================================

/**
 * Message in a conversation.
 */
export interface Message {
  /** Unique message ID */
  id: string;

  /** Session ID */
  sessionId: string;

  /** Message role */
  role: MessageRole;

  /** Message content */
  content: string;

  /** Tool calls (for assistant messages) */
  toolCalls?: ToolCall[];

  /** Tool result (for tool messages) */
  toolResult?: ToolResult;

  /** Timestamp */
  timestamp: Date;

  /** Token count */
  tokens?: number;

  /** Message metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Message role.
 */
export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

/**
 * Tool call.
 */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

/**
 * Tool result.
 */
export interface ToolResult {
  callId: string;
  result: unknown;
  error?: string;
}

// =============================================================================
// API TYPES
// =============================================================================

/**
 * Server API interface.
 */
export interface AgentServerAPI {
  // Session management
  createSession(config?: SessionConfig): Promise<Session>;
  getSession(sessionId: string): Promise<Session | null>;
  listSessions(): Promise<Session[]>;
  closeSession(sessionId: string): Promise<void>;

  // Messaging
  sendMessage(sessionId: string, content: string): Promise<Message>;
  getMessages(sessionId: string, options?: GetMessagesOptions): Promise<Message[]>;

  // Streaming
  streamMessage(sessionId: string, content: string): AsyncIterable<StreamChunk>;

  // Events
  subscribe(sessionId: string): AsyncIterable<AgentEvent>;

  // Control
  cancel(sessionId: string): Promise<void>;

  // Health
  health(): Promise<HealthStatus>;
}

/**
 * Options for getting messages.
 */
export interface GetMessagesOptions {
  limit?: number;
  before?: string;
  after?: string;
}

/**
 * Streaming response chunk.
 */
export interface StreamChunk {
  type: 'text' | 'tool_call' | 'done' | 'error';
  content?: string;
  toolCall?: ToolCall;
  error?: string;
  messageId?: string;
}

/**
 * Server health status.
 */
export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  uptime: number;
  activeSessions: number;
  load: number;
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Agent events for real-time updates.
 */
export type AgentEvent =
  | { type: 'message.created'; message: Message }
  | { type: 'message.delta'; messageId: string; delta: string }
  | { type: 'message.completed'; message: Message }
  | { type: 'tool.called'; sessionId: string; toolCall: ToolCall }
  | { type: 'tool.completed'; sessionId: string; result: ToolResult }
  | { type: 'session.status'; sessionId: string; status: SessionStatus }
  | { type: 'error'; sessionId: string; error: string };

export type AgentEventListener = (event: AgentEvent) => void;

// =============================================================================
// REQUEST/RESPONSE TYPES
// =============================================================================

/**
 * API request wrapper.
 */
export interface APIRequest<T = unknown> {
  /** Request ID for correlation */
  id: string;

  /** Request method */
  method: string;

  /** Request parameters */
  params: T;

  /** Request timestamp */
  timestamp: Date;
}

/**
 * API response wrapper.
 */
export interface APIResponse<T = unknown> {
  /** Request ID for correlation */
  id: string;

  /** Success flag */
  success: boolean;

  /** Response data */
  data?: T;

  /** Error details */
  error?: APIError;

  /** Response timestamp */
  timestamp: Date;
}

/**
 * API error.
 */
export interface APIError {
  code: ErrorCode;
  message: string;
  details?: Record<string, unknown>;
}

/**
 * Error codes.
 */
export type ErrorCode =
  | 'INVALID_REQUEST'
  | 'SESSION_NOT_FOUND'
  | 'SESSION_EXPIRED'
  | 'RATE_LIMITED'
  | 'SERVER_ERROR'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'UNAUTHORIZED';

// =============================================================================
// PROTOCOL TYPES
// =============================================================================

/**
 * Protocol message format.
 */
export interface ProtocolMessage {
  /** Protocol version */
  version: string;

  /** Message type */
  type: 'request' | 'response' | 'event' | 'ping' | 'pong';

  /** Payload */
  payload: unknown;
}

/**
 * Connection state.
 */
export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting';

// =============================================================================
// CLIENT CONFIG
// =============================================================================

/**
 * Client configuration.
 */
export interface ClientConfig {
  /** Server URL */
  serverUrl: string;

  /** API key for authentication */
  apiKey?: string;

  /** Request timeout */
  timeout?: number;

  /** Auto-reconnect on disconnect */
  autoReconnect?: boolean;

  /** Reconnect delay */
  reconnectDelay?: number;

  /** Maximum reconnect attempts */
  maxReconnectAttempts?: number;
}

// =============================================================================
// SERVER CONFIG
// =============================================================================

/**
 * Server configuration.
 */
export interface ServerConfig {
  /** Port to listen on */
  port: number;

  /** Host to bind to */
  host?: string;

  /** Enable CORS */
  cors?: boolean;

  /** API key validation */
  apiKeyValidator?: (key: string) => boolean;

  /** Session timeout */
  sessionTimeout?: number;

  /** Maximum sessions */
  maxSessions?: number;

  /** Rate limiting */
  rateLimit?: RateLimitConfig;
}

/**
 * Rate limit configuration.
 */
export interface RateLimitConfig {
  /** Requests per window */
  maxRequests: number;

  /** Window size in ms */
  windowMs: number;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Generate unique ID.
 */
export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Generate session ID.
 */
export function generateSessionId(): string {
  return `session-${generateId()}`;
}

/**
 * Generate message ID.
 */
export function generateMessageId(): string {
  return `msg-${generateId()}`;
}
