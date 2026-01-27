/**
 * Lesson 7: MCP Types
 * 
 * Type definitions for the Model Context Protocol.
 * Based on the MCP specification.
 */

// =============================================================================
// JSON-RPC TYPES
// =============================================================================

export interface JSONRPCRequest {
  jsonrpc: '2.0';
  id: string | number;
  method: string;
  params?: unknown;
}

export interface JSONRPCResponse {
  jsonrpc: '2.0';
  id: string | number;
  result?: unknown;
  error?: JSONRPCError;
}

export interface JSONRPCError {
  code: number;
  message: string;
  data?: unknown;
}

export interface JSONRPCNotification {
  jsonrpc: '2.0';
  method: string;
  params?: unknown;
}

// =============================================================================
// MCP CAPABILITIES
// =============================================================================

export interface ServerCapabilities {
  tools?: {
    listChanged?: boolean;
  };
  resources?: {
    subscribe?: boolean;
    listChanged?: boolean;
  };
  prompts?: {
    listChanged?: boolean;
  };
  logging?: Record<string, never>;
}

export interface ClientCapabilities {
  roots?: {
    listChanged?: boolean;
  };
  sampling?: Record<string, never>;
}

// =============================================================================
// MCP TOOLS
// =============================================================================

export interface MCPTool {
  name: string;
  description?: string;
  inputSchema: MCPJSONSchema;
}

export interface MCPJSONSchema {
  type: 'object';
  properties?: Record<string, MCPPropertySchema>;
  required?: string[];
  additionalProperties?: boolean;
}

export interface MCPPropertySchema {
  type: string;
  description?: string;
  enum?: string[];
  items?: MCPPropertySchema;
  properties?: Record<string, MCPPropertySchema>;
}

export interface MCPToolCallResult {
  content: MCPContent[];
  isError?: boolean;
}

export type MCPContent =
  | { type: 'text'; text: string }
  | { type: 'image'; data: string; mimeType: string }
  | { type: 'resource'; resource: MCPResourceReference };

export interface MCPResourceReference {
  uri: string;
  mimeType?: string;
  text?: string;
}

// =============================================================================
// MCP RESOURCES
// =============================================================================

export interface MCPResource {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

export interface MCPResourceContent {
  uri: string;
  mimeType?: string;
  text?: string;
  blob?: string;
}

// =============================================================================
// MCP PROMPTS
// =============================================================================

export interface MCPPrompt {
  name: string;
  description?: string;
  arguments?: MCPPromptArgument[];
}

export interface MCPPromptArgument {
  name: string;
  description?: string;
  required?: boolean;
}

export interface MCPPromptMessage {
  role: 'user' | 'assistant';
  content: MCPContent;
}

// =============================================================================
// MCP INITIALIZATION
// =============================================================================

export interface InitializeParams {
  protocolVersion: string;
  capabilities: ClientCapabilities;
  clientInfo: {
    name: string;
    version: string;
  };
}

export interface InitializeResult {
  protocolVersion: string;
  capabilities: ServerCapabilities;
  serverInfo: {
    name: string;
    version: string;
  };
}

// =============================================================================
// MCP CLIENT EVENTS
// =============================================================================

export type MCPClientEvent =
  | { type: 'connected'; server: string }
  | { type: 'disconnected'; server: string; reason?: string }
  | { type: 'error'; error: Error }
  | { type: 'tool_called'; tool: string; arguments: unknown }
  | { type: 'tool_result'; tool: string; result: MCPToolCallResult }
  | { type: 'notification'; method: string; params: unknown };

export type MCPClientEventHandler = (event: MCPClientEvent) => void;

// =============================================================================
// TRANSPORT TYPES
// =============================================================================

export interface MCPTransport {
  send(message: JSONRPCRequest | JSONRPCNotification): Promise<void>;
  receive(): AsyncGenerator<JSONRPCResponse | JSONRPCNotification>;
  close(): Promise<void>;
}

export type TransportType = 'stdio' | 'sse' | 'websocket';

export interface TransportConfig {
  type: TransportType;
  // stdio specific
  command?: string;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  // network specific
  url?: string;
  headers?: Record<string, string>;
}
