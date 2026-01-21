/**
 * Lesson 7: MCP Client
 * 
 * Client for connecting to MCP servers.
 */

import { spawn, ChildProcess } from 'node:child_process';
import { createInterface, Interface } from 'node:readline';
import type {
  JSONRPCRequest,
  JSONRPCResponse,
  MCPTool,
  MCPResource,
  MCPPrompt,
  MCPToolCallResult,
  MCPResourceContent,
  MCPPromptMessage,
  InitializeResult,
  MCPClientEvent,
  MCPClientEventHandler,
  TransportConfig,
  ServerCapabilities,
} from './types.js';

// =============================================================================
// MCP CLIENT
// =============================================================================

export class MCPClient {
  private process: ChildProcess | null = null;
  private readline: Interface | null = null;
  private requestId = 0;
  private pendingRequests: Map<number, {
    resolve: (value: unknown) => void;
    reject: (error: Error) => void;
  }> = new Map();
  private eventHandlers: Set<MCPClientEventHandler> = new Set();
  private serverInfo: InitializeResult | null = null;
  private connected = false;

  /**
   * Connect to an MCP server via stdio.
   */
  async connect(config: TransportConfig): Promise<InitializeResult> {
    if (this.connected) {
      throw new Error('Already connected');
    }

    if (config.type !== 'stdio') {
      throw new Error(`Transport type "${config.type}" not yet supported`);
    }

    if (!config.command) {
      throw new Error('Command is required for stdio transport');
    }

    // Spawn the server process
    this.process = spawn(config.command, config.args ?? [], {
      cwd: config.cwd,
      env: { ...process.env, ...config.env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    // Set up readline for reading responses
    this.readline = createInterface({
      input: this.process.stdout!,
      crlfDelay: Infinity,
    });

    // Handle incoming messages
    this.readline.on('line', (line) => {
      this.handleMessage(line);
    });

    // Handle process errors
    this.process.on('error', (error) => {
      this.emit({ type: 'error', error });
    });

    this.process.on('exit', (code) => {
      this.connected = false;
      this.emit({ 
        type: 'disconnected', 
        server: config.command!, 
        reason: `Process exited with code ${code}` 
      });
    });

    // Initialize the connection
    this.connected = true;
    
    const result = await this.request<InitializeResult>('initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {
        roots: { listChanged: true },
      },
      clientInfo: {
        name: 'first-principles-agent',
        version: '1.0.0',
      },
    });

    this.serverInfo = result;
    
    // Send initialized notification
    await this.notify('notifications/initialized', {});

    this.emit({ type: 'connected', server: config.command });
    return result;
  }

  /**
   * Disconnect from the server.
   */
  async disconnect(): Promise<void> {
    if (!this.connected) return;

    this.readline?.close();
    this.process?.kill();
    this.connected = false;
    this.process = null;
    this.readline = null;
  }

  /**
   * List available tools.
   */
  async listTools(): Promise<MCPTool[]> {
    const result = await this.request<{ tools: MCPTool[] }>('tools/list', {});
    return result.tools;
  }

  /**
   * Call a tool.
   */
  async callTool(name: string, args: Record<string, unknown>): Promise<MCPToolCallResult> {
    this.emit({ type: 'tool_called', tool: name, arguments: args });
    
    const result = await this.request<MCPToolCallResult>('tools/call', {
      name,
      arguments: args,
    });

    this.emit({ type: 'tool_result', tool: name, result });
    return result;
  }

  /**
   * List available resources.
   */
  async listResources(): Promise<MCPResource[]> {
    const result = await this.request<{ resources: MCPResource[] }>('resources/list', {});
    return result.resources;
  }

  /**
   * Read a resource.
   */
  async readResource(uri: string): Promise<MCPResourceContent[]> {
    const result = await this.request<{ contents: MCPResourceContent[] }>('resources/read', {
      uri,
    });
    return result.contents;
  }

  /**
   * List available prompts.
   */
  async listPrompts(): Promise<MCPPrompt[]> {
    const result = await this.request<{ prompts: MCPPrompt[] }>('prompts/list', {});
    return result.prompts;
  }

  /**
   * Get a prompt.
   */
  async getPrompt(name: string, args?: Record<string, string>): Promise<{
    description?: string;
    messages: MCPPromptMessage[];
  }> {
    return this.request('prompts/get', { name, arguments: args });
  }

  /**
   * Get server capabilities.
   */
  getCapabilities(): ServerCapabilities | null {
    return this.serverInfo?.capabilities ?? null;
  }

  /**
   * Check if connected.
   */
  isConnected(): boolean {
    return this.connected;
  }

  /**
   * Add event handler.
   */
  on(handler: MCPClientEventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  // =============================================================================
  // PRIVATE METHODS
  // =============================================================================

  private async request<T>(method: string, params: unknown): Promise<T> {
    if (!this.connected || !this.process) {
      throw new Error('Not connected');
    }

    const id = ++this.requestId;
    const request: JSONRPCRequest = {
      jsonrpc: '2.0',
      id,
      method,
      params,
    };

    return new Promise<T>((resolve, reject) => {
      this.pendingRequests.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
      });

      this.process!.stdin!.write(JSON.stringify(request) + '\n');
    });
  }

  private async notify(method: string, params: unknown): Promise<void> {
    if (!this.connected || !this.process) {
      throw new Error('Not connected');
    }

    const notification = {
      jsonrpc: '2.0',
      method,
      params,
    };

    this.process.stdin!.write(JSON.stringify(notification) + '\n');
  }

  private handleMessage(line: string): void {
    try {
      const message = JSON.parse(line) as JSONRPCResponse;
      
      if ('id' in message && message.id !== undefined) {
        // Response to a request
        const pending = this.pendingRequests.get(message.id as number);
        if (pending) {
          this.pendingRequests.delete(message.id as number);
          
          if (message.error) {
            pending.reject(new Error(message.error.message));
          } else {
            pending.resolve(message.result);
          }
        }
      } else if ('method' in message) {
        // Notification from server
        this.emit({
          type: 'notification',
          method: (message as unknown as { method: string }).method,
          params: (message as unknown as { params: unknown }).params,
        });
      }
    } catch (error) {
      // Ignore parse errors (might be debug output)
    }
  }

  private emit(event: MCPClientEvent): void {
    for (const handler of this.eventHandlers) {
      try {
        handler(event);
      } catch {
        // Ignore handler errors
      }
    }
  }
}
