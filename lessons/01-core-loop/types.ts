/**
 * Lesson 1: Core Types
 * 
 * These types form the foundation of our agent system.
 * They're intentionally minimal - we'll extend them in later lessons.
 */

// =============================================================================
// MESSAGE TYPES
// =============================================================================

/**
 * A message in the conversation history.
 * This follows the standard chat format used by most LLM APIs.
 */
export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

/**
 * A tool call parsed from the LLM's response.
 * The LLM outputs JSON indicating which tool to use and with what arguments.
 */
export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
}

/**
 * Result of executing a tool.
 */
export interface ToolResult {
  success: boolean;
  output: string;
}

// =============================================================================
// LLM INTERFACE
// =============================================================================

/**
 * Minimal LLM interface.
 * Any LLM provider can implement this interface.
 * 
 * Why an interface? So we can:
 * 1. Swap providers without changing agent code
 * 2. Create mock implementations for testing
 * 3. Add features (streaming, retries) via decorators
 */
export interface LLMProvider {
  /**
   * Send messages to the LLM and get a response.
   * @param messages - Conversation history
   * @returns The assistant's response text
   */
  chat(messages: Message[]): Promise<string>;
}

// =============================================================================
// TOOL INTERFACE
// =============================================================================

/**
 * A tool that the agent can use.
 * Tools are how the agent affects the world.
 */
export interface Tool {
  /** Unique identifier for the tool */
  name: string;
  
  /** Human-readable description (shown to the LLM) */
  description: string;
  
  /** Execute the tool with given input */
  execute(input: Record<string, unknown>): Promise<ToolResult>;
}

// =============================================================================
// AGENT CONFIGURATION
// =============================================================================

/**
 * Configuration for the agent loop.
 */
export interface AgentConfig {
  /** Maximum number of iterations to prevent infinite loops */
  maxIterations: number;
  
  /** System prompt that defines agent behavior */
  systemPrompt: string;
  
  /** Available tools */
  tools: Tool[];
  
  /** LLM provider to use */
  llm: LLMProvider;
}

/**
 * Result of running the agent.
 */
export interface AgentResult {
  /** Whether the task completed successfully */
  success: boolean;
  
  /** Final message or error */
  message: string;
  
  /** Number of iterations used */
  iterations: number;
  
  /** Full conversation history */
  history: Message[];
}

// =============================================================================
// STOP REASONS
// =============================================================================

/**
 * Why the agent stopped.
 */
export type StopReason = 
  | 'completed'      // Task finished successfully
  | 'max_iterations' // Hit iteration limit
  | 'error'          // Unrecoverable error
  | 'user_cancelled'; // User interrupted
