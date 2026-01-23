/**
 * Lesson 2: Provider Abstraction Types
 * 
 * Extended types that support multiple LLM providers.
 */

// =============================================================================
// MESSAGE TYPES
// =============================================================================

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

// =============================================================================
// PROVIDER INTERFACE
// =============================================================================

/**
 * Options for chat requests.
 */
export interface ChatOptions {
  /** Maximum tokens to generate */
  maxTokens?: number;
  
  /** Temperature for randomness (0-1) */
  temperature?: number;
  
  /** Stop sequences */
  stopSequences?: string[];
  
  /** Model override (uses provider default if not specified) */
  model?: string;
}

/**
 * Response from chat request.
 */
export interface ChatResponse {
  /** The assistant's response text */
  content: string;
  
  /** Why the response stopped */
  stopReason: 'end_turn' | 'max_tokens' | 'stop_sequence';
  
  /** Token usage (if available) */
  usage?: {
    inputTokens: number;
    outputTokens: number;
    /** Tokens read from cache (for providers that support caching) */
    cachedTokens?: number;
    /** Actual cost from provider (when available, e.g., OpenRouter) */
    cost?: number;
  };
}

/**
 * The core LLM provider interface.
 * All providers must implement this.
 */
export interface LLMProvider {
  /** Provider name for logging/debugging */
  readonly name: string;
  
  /** Default model used by this provider */
  readonly defaultModel: string;
  
  /**
   * Send a chat request to the LLM.
   * @param messages - Conversation history
   * @param options - Optional configuration
   */
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
  
  /**
   * Check if the provider is properly configured.
   */
  isConfigured(): boolean;
}

// =============================================================================
// PROVIDER CONFIGURATION
// =============================================================================

/**
 * Configuration for Anthropic provider.
 */
export interface AnthropicConfig {
  apiKey: string;
  model?: string;
  baseUrl?: string;
}

/**
 * Configuration for OpenAI provider.
 */
export interface OpenAIConfig {
  apiKey: string;
  model?: string;
  organization?: string;
  baseUrl?: string;
}

/**
 * Configuration for Azure OpenAI provider.
 */
export interface AzureOpenAIConfig {
  apiKey: string;
  endpoint: string;
  deployment: string;
  apiVersion?: string;
}

/**
 * Configuration for OpenRouter provider.
 * OpenRouter provides access to 100+ models via a single API.
 */
export interface OpenRouterConfig {
  apiKey: string;
  model?: string;        // e.g., 'anthropic/claude-sonnet-4'
  siteUrl?: string;      // For HTTP-Referer header (analytics)
  siteName?: string;     // For X-Title header (analytics)
}

/**
 * Union of all provider configs.
 */
export type ProviderConfig =
  | { type: 'anthropic'; config: AnthropicConfig }
  | { type: 'openai'; config: OpenAIConfig }
  | { type: 'azure'; config: AzureOpenAIConfig }
  | { type: 'openrouter'; config: OpenRouterConfig }
  | { type: 'mock'; config?: undefined };

// =============================================================================
// PROVIDER ERRORS
// =============================================================================

/**
 * Base error for provider issues.
 */
export class ProviderError extends Error {
  constructor(
    message: string,
    public readonly provider: string,
    public readonly code: ProviderErrorCode,
    public readonly cause?: Error
  ) {
    super(message);
    this.name = 'ProviderError';
  }
}

export type ProviderErrorCode =
  | 'NOT_CONFIGURED'
  | 'AUTHENTICATION_FAILED'
  | 'RATE_LIMITED'
  | 'CONTEXT_LENGTH_EXCEEDED'
  | 'INVALID_REQUEST'
  | 'SERVER_ERROR'
  | 'NETWORK_ERROR'
  | 'UNKNOWN';

// =============================================================================
// NATIVE TOOL USE TYPES
// =============================================================================

/**
 * OpenAI-compatible tool definition schema.
 * This is the format expected by OpenRouter for native tool calling.
 *
 * Why this format?
 * - OpenRouter uses OpenAI's API format
 * - Native tool use is more reliable than JSON parsing from text
 * - Type safety: the LLM's tool calls are structured, not string parsing
 */
export interface ToolDefinitionSchema {
  type: 'function';
  function: {
    /** Tool name - must match what the LLM should call */
    name: string;
    /** Description shown to LLM - critical for correct tool selection */
    description: string;
    /** JSON Schema for parameters */
    parameters: Record<string, unknown>;
    /** Enable strict schema validation (OpenAI feature) */
    strict?: boolean;
  };
}

/**
 * Extended chat options that include tool definitions.
 */
export interface ChatOptionsWithTools extends ChatOptions {
  /** Tool definitions in OpenAI format */
  tools?: ToolDefinitionSchema[];

  /**
   * How the LLM should choose tools:
   * - 'auto': LLM decides whether to use tools (default)
   * - 'required': LLM must use at least one tool
   * - 'none': Disable tool use for this request
   * - { type: 'function', function: { name: 'X' } }: Force specific tool
   */
  tool_choice?: 'auto' | 'required' | 'none' | { type: 'function'; function: { name: string } };
}

/**
 * A tool call returned by the LLM.
 * This is the native response format - no JSON parsing needed!
 */
export interface ToolCallResponse {
  /** Unique ID for this tool call (used to match results) */
  id: string;
  type: 'function';
  function: {
    /** Which tool the LLM wants to call */
    name: string;
    /** Arguments as JSON string (needs JSON.parse) */
    arguments: string;
  };
}

/**
 * Extended chat response that may include tool calls.
 */
export interface ChatResponseWithTools extends ChatResponse {
  /** Tool calls requested by the LLM (if any) */
  toolCalls?: ToolCallResponse[];
}

/**
 * Message content that supports caching.
 * Used for OpenRouter's cache_control feature on Anthropic models.
 */
export interface CacheableContent {
  type: 'text';
  text: string;
  /** Mark this content for caching */
  cache_control?: { type: 'ephemeral' };
}

/**
 * Extended message that supports both string and structured content.
 * Structured content allows for cache control markers.
 */
export interface MessageWithContent {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string | CacheableContent[];
  /** For tool result messages - matches the tool call ID */
  tool_call_id?: string;
  /** For tool result messages - the name of the tool (required for Gemini) */
  name?: string;
  /** For assistant messages - tool calls made */
  tool_calls?: ToolCallResponse[];
}

/**
 * Provider interface extended with native tool use.
 * Providers that support tools implement this alongside LLMProvider.
 */
export interface LLMProviderWithTools extends LLMProvider {
  /**
   * Send a chat request with tool definitions.
   * Returns structured tool calls instead of text that needs parsing.
   */
  chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools
  ): Promise<ChatResponseWithTools>;
}
