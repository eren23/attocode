/**
 * Lesson 3: Tool System Types
 * 
 * Type definitions for the tool registry and permission system.
 */

import { z } from 'zod';

// =============================================================================
// TOOL DEFINITION TYPES
// =============================================================================

/**
 * Schema for a tool parameter.
 * Uses Zod for runtime validation.
 */
export type ParameterSchema = z.ZodTypeAny;

/**
 * Retry configuration for a tool.
 * @see RetryConfig in config/base-types.ts for the shared base pattern.
 */
export interface ToolRetryConfig {
  /** Maximum retry attempts (including initial). Set to 1 to disable retry. */
  maxAttempts?: number;
  /** Base delay between retries in ms */
  baseDelayMs?: number;
  /** Error patterns that trigger retry */
  retryableErrors?: string[];
}

/**
 * Tool definition that includes schema and metadata.
 */
export interface ToolDefinition<TInput extends z.ZodTypeAny = z.ZodTypeAny> {
  /** Unique identifier */
  name: string;

  /** Human-readable description (shown to LLM) */
  description: string;

  /** Input parameter schema */
  parameters: TInput;

  /** Default danger level for permission checking */
  dangerLevel: DangerLevel;

  /**
   * Optional callback to dynamically determine danger level based on input.
   * If provided, this takes precedence over the static dangerLevel.
   * Useful for tools like bash where 'ls' is safe but 'rm -rf' is dangerous.
   */
  getDangerLevel?: (input: z.infer<TInput>) => DangerLevel;

  /** Execute the tool */
  execute: (input: z.infer<TInput>) => Promise<ToolResult>;

  /** Retry configuration for transient failures */
  retryConfig?: ToolRetryConfig;
}

/**
 * Result of tool execution.
 */
export interface ToolResult {
  success: boolean;
  output: string;
  metadata?: Record<string, unknown>;
}

// =============================================================================
// PERMISSION TYPES
// =============================================================================

/**
 * Danger levels for tools and operations.
 */
export type DangerLevel = 
  | 'safe'      // Reading, listing - auto-approve
  | 'moderate'  // Writing files - may need confirmation
  | 'dangerous' // Destructive commands - require confirmation
  | 'critical'; // System commands - may be blocked entirely

/**
 * Permission modes.
 */
export type PermissionMode = 
  | 'strict'      // Block dangerous, ask for moderate
  | 'interactive' // Ask user for moderate and dangerous
  | 'auto-safe'   // Auto-approve safe and moderate
  | 'yolo';       // Auto-approve everything (testing only)

/**
 * Request for permission to perform an operation.
 */
export interface PermissionRequest {
  tool: string;
  operation: string;
  target: string;
  dangerLevel: DangerLevel;
  context?: string;
}

/**
 * Response to a permission request.
 */
export interface PermissionResponse {
  granted: boolean;
  reason?: string;
  remember?: boolean; // Remember this decision for similar operations
}

/**
 * Interface for permission checkers.
 */
export interface PermissionChecker {
  check(request: PermissionRequest): Promise<PermissionResponse>;
}

// =============================================================================
// JSON SCHEMA GENERATION
// =============================================================================

/**
 * JSON Schema representation for LLM tool descriptions.
 */
export interface JSONSchema {
  type: 'object';
  properties: Record<string, JSONSchemaProperty>;
  required?: string[];
}

export interface JSONSchemaProperty {
  type: string;
  description?: string;
  enum?: string[];
  items?: JSONSchemaProperty;
  properties?: Record<string, JSONSchemaProperty>;
}

/**
 * Tool description in format suitable for LLM APIs.
 */
export interface ToolDescription {
  name: string;
  description: string;
  input_schema: JSONSchema;
}

// =============================================================================
// REGISTRY TYPES
// =============================================================================

/**
 * Options for tool execution.
 */
export interface ExecuteOptions {
  /** Permission mode to use */
  permissionMode?: PermissionMode;
  
  /** Working directory for file operations */
  cwd?: string;
  
  /** Timeout in milliseconds */
  timeout?: number;
}

/**
 * Events emitted during tool execution.
 */
export type ToolEvent = 
  | { type: 'start'; tool: string; input: unknown }
  | { type: 'permission_requested'; request: PermissionRequest }
  | { type: 'permission_granted'; request: PermissionRequest }
  | { type: 'permission_denied'; request: PermissionRequest; reason: string }
  | { type: 'executing'; tool: string }
  | { type: 'complete'; tool: string; result: ToolResult }
  | { type: 'error'; tool: string; error: Error };

/**
 * Listener for tool events.
 */
export type ToolEventListener = (event: ToolEvent) => void;

// =============================================================================
// DANGEROUS PATTERNS
// =============================================================================

/**
 * Patterns that indicate dangerous operations.
 */
export interface DangerPattern {
  pattern: RegExp;
  level: DangerLevel;
  description: string;
}

/**
 * Default dangerous patterns for bash commands.
 */
export const DANGEROUS_PATTERNS: DangerPattern[] = [
  // Critical - system operations
  { pattern: /\bsudo\b/, level: 'critical', description: 'Superuser command' },
  { pattern: /\bsu\b/, level: 'critical', description: 'Switch user' },
  { pattern: /\bchmod\s+[0-7]*7/, level: 'critical', description: 'World-writable permission' },
  { pattern: /\bchown\b/, level: 'critical', description: 'Change ownership' },
  
  // Dangerous - destructive operations
  { pattern: /\brm\s+(-[rf]+\s+)*\//, level: 'dangerous', description: 'Remove from root' },
  { pattern: /\brm\s+-rf\b/, level: 'dangerous', description: 'Recursive force delete' },
  { pattern: />\s*\/dev\/(?!null)/, level: 'dangerous', description: 'Write to device (excludes /dev/null)' },
  { pattern: /\bdd\b.*if=/, level: 'dangerous', description: 'Low-level disk operation' },
  { pattern: /\bmkfs\b/, level: 'dangerous', description: 'Format filesystem' },
  { pattern: /\bkill\s+-9\b/, level: 'dangerous', description: 'Force kill process' },
  
  // Moderate - network and potentially harmful
  { pattern: /\bcurl\b.*\|\s*(ba)?sh/, level: 'dangerous', description: 'Pipe URL to shell' },
  { pattern: /\bwget\b.*\|\s*(ba)?sh/, level: 'dangerous', description: 'Pipe URL to shell' },
  { pattern: /\bnpm\s+install\s+-g\b/, level: 'moderate', description: 'Global npm install' },
  { pattern: /\bpip\s+install\b/, level: 'moderate', description: 'Python package install' },
];
