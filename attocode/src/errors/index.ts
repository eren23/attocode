/**
 * Centralized Error Types
 *
 * Provides typed, categorized errors for the agent system.
 * Enables better error handling, recovery strategies, and observability.
 *
 * Error Categories:
 * - TRANSIENT: Network, timeout - retryable
 * - PERMANENT: Auth, config, validation - not retryable
 * - RESOURCE: Memory, CPU limits exceeded
 * - RATE_LIMITED: API rate limits hit
 * - DEPENDENCY: External service failures
 *
 * @example
 * ```typescript
 * throw new ToolError(
 *   'File not found: config.json',
 *   ErrorCategory.PERMANENT,
 *   false,
 *   { tool: 'read_file', path: 'config.json' }
 * );
 * ```
 */

// =============================================================================
// ERROR CATEGORIES
// =============================================================================

/**
 * Categories of errors for recovery decisions.
 */
export enum ErrorCategory {
  /** Transient errors - may resolve on retry (network, timeout) */
  TRANSIENT = 'TRANSIENT',

  /** Permanent errors - will not resolve on retry (auth, invalid input) */
  PERMANENT = 'PERMANENT',

  /** Resource errors - system resource limits exceeded */
  RESOURCE = 'RESOURCE',

  /** Validation errors - invalid input or configuration */
  VALIDATION = 'VALIDATION',

  /** Rate limited - API rate limits hit, retry after delay */
  RATE_LIMITED = 'RATE_LIMITED',

  /** Dependency errors - external service failures */
  DEPENDENCY = 'DEPENDENCY',

  /** Internal errors - unexpected internal failures */
  INTERNAL = 'INTERNAL',

  /** Cancelled - operation was cancelled */
  CANCELLED = 'CANCELLED',
}

// =============================================================================
// BASE ERROR CLASS
// =============================================================================

/**
 * Base class for all agent errors.
 * Provides structured error information for handling and observability.
 */
export class AgentError extends Error {
  /** Error category for recovery decisions */
  readonly category: ErrorCategory;

  /** Whether the error may resolve on retry */
  readonly recoverable: boolean;

  /** Timestamp when error occurred */
  readonly timestamp: Date;

  /** Additional context for debugging */
  readonly context: Record<string, unknown>;

  /** Original error that caused this one (if wrapping) */
  readonly cause?: Error;

  constructor(
    message: string,
    category: ErrorCategory,
    recoverable: boolean,
    context?: Record<string, unknown>,
    cause?: Error
  ) {
    super(message);
    this.name = 'AgentError';
    this.category = category;
    this.recoverable = recoverable;
    this.timestamp = new Date();
    this.context = context ?? {};
    this.cause = cause;

    // Maintain proper stack trace in V8
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor);
    }
  }

  /**
   * Create a serializable representation of the error.
   */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      message: this.message,
      category: this.category,
      recoverable: this.recoverable,
      timestamp: this.timestamp.toISOString(),
      context: this.context,
      cause: this.cause?.message,
      stack: this.stack,
    };
  }

  /**
   * Format error for logging.
   */
  toLogString(): string {
    const parts = [
      `[${this.name}]`,
      `(${this.category})`,
      this.message,
    ];

    if (Object.keys(this.context).length > 0) {
      parts.push(`context=${JSON.stringify(this.context)}`);
    }

    return parts.join(' ');
  }
}

// =============================================================================
// SPECIALIZED ERROR CLASSES
// =============================================================================

/**
 * Error from tool execution.
 */
export class ToolError extends AgentError {
  /** Name of the tool that failed */
  readonly toolName: string;

  constructor(
    message: string,
    category: ErrorCategory,
    recoverable: boolean,
    toolName: string,
    context?: Record<string, unknown>,
    cause?: Error
  ) {
    super(message, category, recoverable, { ...context, tool: toolName }, cause);
    this.name = 'ToolError';
    this.toolName = toolName;
  }

  /**
   * Create a ToolError from a generic error.
   */
  static fromError(error: Error, toolName: string): ToolError {
    const { category, recoverable } = categorizeError(error);
    return new ToolError(
      error.message,
      category,
      recoverable,
      toolName,
      undefined,
      error
    );
  }
}

/**
 * Error from MCP server communication.
 */
export class MCPError extends AgentError {
  /** Name of the MCP server */
  readonly serverName: string;

  /** MCP method that failed (e.g., 'tools/call') */
  readonly method?: string;

  constructor(
    message: string,
    category: ErrorCategory,
    recoverable: boolean,
    serverName: string,
    context?: Record<string, unknown>,
    cause?: Error
  ) {
    super(message, category, recoverable, { ...context, server: serverName }, cause);
    this.name = 'MCPError';
    this.serverName = serverName;
    this.method = context?.method as string | undefined;
  }

  /**
   * Create error for server not found.
   */
  static serverNotFound(serverName: string): MCPError {
    return new MCPError(
      `Server not found: ${serverName}`,
      ErrorCategory.PERMANENT,
      false,
      serverName
    );
  }

  /**
   * Create error for server not connected.
   */
  static serverNotConnected(serverName: string): MCPError {
    return new MCPError(
      `Server not connected: ${serverName}`,
      ErrorCategory.DEPENDENCY,
      true, // May recover if server restarts
      serverName
    );
  }

  /**
   * Create error for request timeout.
   */
  static timeout(serverName: string, method: string): MCPError {
    return new MCPError(
      `Request timeout: ${method}`,
      ErrorCategory.TRANSIENT,
      true,
      serverName,
      { method }
    );
  }
}

/**
 * Error from file operations.
 */
export class FileOperationError extends AgentError {
  /** Path of the file operation */
  readonly path: string;

  /** Type of operation (read, write, delete, etc.) */
  readonly operation: string;

  constructor(
    message: string,
    category: ErrorCategory,
    recoverable: boolean,
    path: string,
    operation: string,
    context?: Record<string, unknown>,
    cause?: Error
  ) {
    super(message, category, recoverable, { ...context, path, operation }, cause);
    this.name = 'FileOperationError';
    this.path = path;
    this.operation = operation;
  }

  /**
   * Create error for file not found.
   */
  static notFound(path: string, operation: string): FileOperationError {
    return new FileOperationError(
      `File not found: ${path}`,
      ErrorCategory.PERMANENT,
      false,
      path,
      operation
    );
  }

  /**
   * Create error for permission denied.
   */
  static permissionDenied(path: string, operation: string): FileOperationError {
    return new FileOperationError(
      `Permission denied: ${path}`,
      ErrorCategory.PERMANENT,
      false,
      path,
      operation
    );
  }

  /**
   * Create error for file busy (may resolve on retry).
   */
  static busy(path: string, operation: string): FileOperationError {
    return new FileOperationError(
      `File busy: ${path}`,
      ErrorCategory.TRANSIENT,
      true,
      path,
      operation
    );
  }
}

/**
 * Error from LLM provider calls.
 */
export class ProviderError extends AgentError {
  /** Name of the provider */
  readonly providerName: string;

  /** HTTP status code if applicable */
  readonly statusCode?: number;

  constructor(
    message: string,
    category: ErrorCategory,
    recoverable: boolean,
    providerName: string,
    context?: Record<string, unknown>,
    cause?: Error
  ) {
    super(message, category, recoverable, { ...context, provider: providerName }, cause);
    this.name = 'ProviderError';
    this.providerName = providerName;
    this.statusCode = context?.statusCode as number | undefined;
  }

  /**
   * Create error for rate limiting.
   */
  static rateLimited(providerName: string, retryAfter?: number): ProviderError {
    return new ProviderError(
      `Rate limited by ${providerName}`,
      ErrorCategory.RATE_LIMITED,
      true,
      providerName,
      { retryAfter }
    );
  }

  /**
   * Create error for authentication failure.
   */
  static authenticationFailed(providerName: string): ProviderError {
    return new ProviderError(
      `Authentication failed for ${providerName}`,
      ErrorCategory.PERMANENT,
      false,
      providerName
    );
  }

  /**
   * Create error for server error.
   */
  static serverError(providerName: string, statusCode: number): ProviderError {
    return new ProviderError(
      `Server error from ${providerName}: ${statusCode}`,
      ErrorCategory.TRANSIENT,
      true,
      providerName,
      { statusCode }
    );
  }
}

/**
 * Error from validation failures.
 */
export class ValidationError extends AgentError {
  /** Field(s) that failed validation */
  readonly fields?: string[];

  constructor(
    message: string,
    fields?: string[],
    context?: Record<string, unknown>
  ) {
    super(message, ErrorCategory.VALIDATION, false, { ...context, fields });
    this.name = 'ValidationError';
    this.fields = fields;
  }

  /**
   * Create error from Zod validation result.
   */
  static fromZodError(error: { issues: Array<{ path: (string | number)[]; message: string }> }): ValidationError {
    const fields = error.issues.map(i => i.path.join('.'));
    const messages = error.issues.map(i => `${i.path.join('.')}: ${i.message}`);
    return new ValidationError(
      `Validation failed: ${messages.join(', ')}`,
      fields
    );
  }
}

/**
 * Error when operation is cancelled.
 */
export class CancellationError extends AgentError {
  /** Reason for cancellation */
  readonly reason: string;

  constructor(reason: string = 'Operation cancelled') {
    super(reason, ErrorCategory.CANCELLED, false, { reason });
    this.name = 'CancellationError';
    this.reason = reason;
  }
}

/**
 * Error when resources are exhausted.
 */
export class ResourceError extends AgentError {
  /** Type of resource exhausted */
  readonly resourceType: 'memory' | 'cpu' | 'time' | 'tokens' | 'concurrent';

  /** Current usage */
  readonly usage?: number;

  /** Limit that was exceeded */
  readonly limit?: number;

  constructor(
    message: string,
    resourceType: 'memory' | 'cpu' | 'time' | 'tokens' | 'concurrent',
    usage?: number,
    limit?: number
  ) {
    super(message, ErrorCategory.RESOURCE, false, { resourceType, usage, limit });
    this.name = 'ResourceError';
    this.resourceType = resourceType;
    this.usage = usage;
    this.limit = limit;
  }

  /**
   * Create error for memory limit exceeded.
   */
  static memoryExceeded(usage: number, limit: number): ResourceError {
    return new ResourceError(
      `Memory limit exceeded: ${usage}MB / ${limit}MB`,
      'memory',
      usage,
      limit
    );
  }

  /**
   * Create error for timeout.
   */
  static timeout(elapsed: number, limit: number): ResourceError {
    return new ResourceError(
      `Time limit exceeded: ${elapsed}ms / ${limit}ms`,
      'time',
      elapsed,
      limit
    );
  }

  /**
   * Create error for token limit exceeded.
   */
  static tokenLimitExceeded(used: number, limit: number): ResourceError {
    return new ResourceError(
      `Token limit exceeded: ${used} / ${limit}`,
      'tokens',
      used,
      limit
    );
  }
}

// =============================================================================
// ERROR UTILITIES
// =============================================================================

/**
 * Determine error category from a generic error.
 * Used to wrap unknown errors in typed AgentError.
 */
export function categorizeError(error: Error): {
  category: ErrorCategory;
  recoverable: boolean;
} {
  const message = error.message.toLowerCase();
  const code = (error as NodeJS.ErrnoException).code;

  // Check for transient errors (retryable)
  if (
    code === 'ETIMEDOUT' ||
    code === 'ECONNRESET' ||
    code === 'ECONNREFUSED' ||
    code === 'ENOTFOUND' ||
    message.includes('etimedout') ||
    message.includes('econnreset') ||
    message.includes('timeout') ||
    message.includes('socket hang up') ||
    message.includes('network error') ||
    message.includes('temporarily unavailable')
  ) {
    return { category: ErrorCategory.TRANSIENT, recoverable: true };
  }

  // Check for rate limiting
  if (
    message.includes('rate limit') ||
    message.includes('too many requests') ||
    message.includes('429')
  ) {
    return { category: ErrorCategory.RATE_LIMITED, recoverable: true };
  }

  // Check for authentication errors
  if (
    message.includes('unauthorized') ||
    message.includes('authentication') ||
    message.includes('forbidden') ||
    message.includes('401') ||
    message.includes('403')
  ) {
    return { category: ErrorCategory.PERMANENT, recoverable: false };
  }

  // Check for validation errors
  if (
    message.includes('invalid') ||
    message.includes('validation') ||
    message.includes('required')
  ) {
    return { category: ErrorCategory.VALIDATION, recoverable: false };
  }

  // Check for resource errors
  if (
    code === 'ENOMEM' ||
    message.includes('out of memory') ||
    message.includes('resource limit')
  ) {
    return { category: ErrorCategory.RESOURCE, recoverable: false };
  }

  // Check for cancellation
  if (message.includes('cancelled') || message.includes('aborted')) {
    return { category: ErrorCategory.CANCELLED, recoverable: false };
  }

  // Default to transient (assume retryable)
  return { category: ErrorCategory.INTERNAL, recoverable: false };
}

/**
 * Wrap an unknown error as an AgentError.
 */
export function wrapError(error: unknown, context?: Record<string, unknown>): AgentError {
  if (error instanceof AgentError) {
    return error;
  }

  const err = error instanceof Error ? error : new Error(String(error));
  const { category, recoverable } = categorizeError(err);

  return new AgentError(err.message, category, recoverable, context, err);
}

/**
 * Type guard for AgentError.
 */
export function isAgentError(error: unknown): error is AgentError {
  return error instanceof AgentError;
}

/**
 * Type guard for recoverable errors.
 */
export function isRecoverable(error: unknown): boolean {
  if (error instanceof AgentError) {
    return error.recoverable;
  }
  const { recoverable } = categorizeError(error as Error);
  return recoverable;
}

/**
 * Type guard for transient errors (should retry).
 */
export function isTransient(error: unknown): boolean {
  if (error instanceof AgentError) {
    return error.category === ErrorCategory.TRANSIENT;
  }
  const { category } = categorizeError(error as Error);
  return category === ErrorCategory.TRANSIENT;
}

/**
 * Type guard for rate limited errors (should retry with backoff).
 */
export function isRateLimited(error: unknown): boolean {
  if (error instanceof AgentError) {
    return error.category === ErrorCategory.RATE_LIMITED;
  }
  const { category } = categorizeError(error as Error);
  return category === ErrorCategory.RATE_LIMITED;
}

/**
 * Format error for display to user.
 */
export function formatError(error: unknown): string {
  if (error instanceof AgentError) {
    return `${error.name}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

/**
 * Format error for logging with full details.
 */
export function formatErrorForLog(error: unknown): string {
  if (error instanceof AgentError) {
    return error.toLogString();
  }
  if (error instanceof Error) {
    return `[Error] ${error.message}`;
  }
  return `[Unknown] ${String(error)}`;
}
