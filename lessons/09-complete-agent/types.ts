/**
 * Lesson 9: Complete Agent Types
 *
 * Extended type definitions for the complete agent loop.
 * These types tie together provider types, tool types, and add
 * agent-specific concepts like events, configuration, and state tracking.
 */

import type {
  Message,
  MessageWithContent,
  LLMProviderWithTools,
} from '../02-provider-abstraction/types.js';
import type { ToolResult, PermissionMode, DangerLevel } from '../03-tool-system/types.js';

// =============================================================================
// AGENT CONFIGURATION
// =============================================================================

/**
 * Configuration for the complete agent.
 */
export interface CompleteAgentConfig {
  /** The LLM provider with tool support */
  provider: LLMProviderWithTools;

  /** Maximum agentic iterations before stopping */
  maxIterations: number;

  /** Enable prompt caching for cost savings */
  enableCaching: boolean;

  /** Permission mode for tool execution */
  permissionMode: PermissionMode;

  /** Optional event callback for real-time updates */
  onEvent?: (event: AgentEvent) => void;

  /** Model to use (overrides provider default) */
  model?: string;
}

// =============================================================================
// AGENT EVENTS
// =============================================================================

/**
 * Events emitted during agent execution.
 * These enable real-time UI updates and logging.
 */
export type AgentEvent =
  | { type: 'thinking'; message: string }
  | { type: 'tool_call'; name: string; args: unknown }
  | { type: 'tool_result'; name: string; result: ToolResult }
  | { type: 'permission_requested'; tool: string; operation: string; level: DangerLevel }
  | { type: 'permission_granted'; tool: string }
  | { type: 'permission_denied'; tool: string; reason: string }
  | { type: 'response'; content: string }
  | { type: 'error'; error: Error }
  | { type: 'iteration'; current: number; max: number }
  | { type: 'cache_hit'; tokens: number }
  | { type: 'complete'; result: AgentResult };

// =============================================================================
// AGENT RESULT
// =============================================================================

/**
 * Result of agent execution.
 */
export interface AgentResult {
  /** Whether the task completed successfully */
  success: boolean;

  /** Final message/response from the agent */
  message: string;

  /** Total iterations used */
  iterations: number;

  /** Token usage statistics */
  usage: {
    inputTokens: number;
    outputTokens: number;
    cachedTokens?: number;
  };

  /** All tool calls made during execution */
  toolCalls: Array<{
    name: string;
    args: unknown;
    result: ToolResult;
  }>;

  /** Full conversation history */
  history: ConversationMessage[];
}

// =============================================================================
// CONVERSATION TYPES
// =============================================================================

/**
 * A message in the agent's conversation.
 * Supports both simple text and structured content.
 */
export type ConversationMessage = Message | MessageWithContent;

/**
 * Conversation state for tracking what the agent has done.
 * This helps prevent the agent from "forgetting" previous actions.
 */
export interface ConversationState {
  /** Files that have been read */
  filesRead: Set<string>;

  /** Files that have been modified */
  filesModified: Set<string>;

  /** Commands that have been executed */
  commandsExecuted: string[];

  /** Current working context/task */
  currentTask: string;
}

// =============================================================================
// REPL TYPES
// =============================================================================

/**
 * Configuration for the interactive REPL.
 */
export interface REPLConfig {
  /** Agent configuration */
  agent: CompleteAgentConfig;

  /** Welcome message to display */
  welcomeMessage?: string;

  /** Prompt string */
  prompt?: string;

  /** Enable history */
  enableHistory?: boolean;
}

/**
 * Commands available in the REPL.
 */
export type REPLCommand =
  | { type: 'quit' }
  | { type: 'clear' }
  | { type: 'help' }
  | { type: 'history' }
  | { type: 'status' }
  | { type: 'task'; input: string };

// =============================================================================
// TOOL SCHEMA CONVERSION
// =============================================================================

/**
 * OpenRouter tool definition format.
 * Used when sending tools to the LLM.
 */
export interface OpenRouterToolSchema {
  type: 'function';
  function: {
    name: string;
    description: string;
    parameters: {
      type: 'object';
      properties: Record<string, JSONSchemaProperty>;
      required?: string[];
    };
  };
}

/**
 * JSON Schema property definition.
 */
export interface JSONSchemaProperty {
  type: string;
  description?: string;
  enum?: string[];
  items?: JSONSchemaProperty;
  default?: unknown;
}

// =============================================================================
// RE-EXPORTS FOR CONVENIENCE
// =============================================================================

export type {
  Message,
  MessageWithContent,
  LLMProviderWithTools,
  ToolCallResponse,
  ChatResponseWithTools,
  ToolDefinitionSchema,
  ChatOptionsWithTools,
  CacheableContent,
} from '../02-provider-abstraction/types.js';

export type {
  ToolResult,
  ToolDefinition,
  PermissionMode,
  DangerLevel,
  PermissionRequest,
  PermissionResponse,
} from '../03-tool-system/types.js';
