/**
 * Lesson 25: MCP Client
 *
 * Connects to Model Context Protocol (MCP) servers to extend agent capabilities.
 * Supports stdio-based servers (spawned as child processes).
 */

import { spawn, type ChildProcess } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface, type Interface as ReadlineInterface } from 'node:readline';
import type { ToolDefinition } from '../types.js';
import { withRetry, MCP_RETRY_CONFIG } from './retry.js';
import { MCPError, isRecoverable } from '../errors/index.js';
import type { DeadLetterQueue } from './dead-letter-queue.js';
import { validateAllTools, formatValidationSummary } from './mcp-tool-validator.js';
import { logger } from './logger.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * MCP server configuration.
 */
export interface MCPServerConfig {
  /** Command to run */
  command: string;
  /** Command arguments */
  args?: string[];
  /** Environment variables */
  env?: Record<string, string>;
  /** Working directory */
  cwd?: string;
}

/**
 * Lightweight tool summary - always in context (low token cost).
 * ~50 tokens per tool vs ~200-500 tokens for full definitions.
 */
export interface MCPToolSummary {
  /** Full tool name (e.g., "mcp_playwright_browser_click") */
  name: string;
  /** Truncated description */
  description: string;
  /** Server name (e.g., "playwright") */
  serverName: string;
  /** Original MCP tool name (e.g., "browser_click") */
  originalName: string;
}

/**
 * MCP config file structure.
 */
export interface MCPConfigFile {
  servers: Record<string, MCPServerConfig>;
}

/**
 * MCP tool definition from server.
 */
interface MCPToolDefinition {
  name: string;
  description?: string;
  inputSchema?: {
    type: string;
    properties?: Record<string, unknown>;
    required?: string[];
  };
}

/**
 * MCP server connection state.
 */
interface MCPConnection {
  name: string;
  config: MCPServerConfig;
  process: ChildProcess | null;
  readline: ReadlineInterface | null;
  tools: MCPToolDefinition[];
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  error?: string;
  pendingRequests: Map<number, {
    resolve: (result: unknown) => void;
    reject: (error: Error) => void;
  }>;
  nextRequestId: number;
  /** Set of tools that have been fully loaded (lazy loading mode) */
  loadedTools: Set<string>;
}

/**
 * MCP client configuration.
 */
export interface MCPClientConfig {
  /** Config file path (default: .mcp.json in cwd) */
  configPath?: string;
  /**
   * Multiple config paths loaded in order (later overrides earlier).
   * Example: ['/path/to/global.mcp.json', './.mcp.json']
   * If provided, takes precedence over configPath.
   */
  configPaths?: string[];
  /** Timeout for requests in ms (default: 30000) */
  requestTimeout?: number;
  /** Auto-connect on load (default: true) */
  autoConnect?: boolean;

  // === Lazy Loading Options ===

  /** Enable lazy loading of tool schemas (default: false) */
  lazyLoading?: boolean;
  /** Tools to always load fully (bypass lazy loading) */
  alwaysLoadTools?: string[];
  /** Max chars for summary descriptions (default: 100) */
  summaryDescriptionLimit?: number;
  /** Max results per search query (default: 5) */
  maxToolsPerSearch?: number;
}

/**
 * Context statistics for MCP tools.
 */
export interface MCPContextStats {
  /** Estimated tokens for tool summaries */
  summaryTokens: number;
  /** Estimated tokens for loaded full definitions */
  definitionTokens: number;
  /** Number of tools as summaries only */
  summaryCount: number;
  /** Number of fully loaded tools */
  loadedCount: number;
  /** Total tools available */
  totalTools: number;
}

/**
 * Server info for display.
 */
export interface MCPServerInfo {
  name: string;
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  toolCount: number;
  error?: string;
}

/**
 * MCP events.
 */
export type MCPEvent =
  | { type: 'server.connecting'; name: string }
  | { type: 'server.connected'; name: string; toolCount: number }
  | { type: 'server.disconnected'; name: string }
  | { type: 'server.error'; name: string; error: string }
  | { type: 'tool.call'; server: string; tool: string }
  | { type: 'tool.result'; server: string; tool: string; success: boolean }
  | { type: 'tool.dynamicLoad'; name: string; serverName: string }
  | { type: 'tool.search'; query: string; resultCount: number };

export type MCPEventListener = (event: MCPEvent) => void;

// =============================================================================
// MCP CLIENT
// =============================================================================

/**
 * MCP Client manages connections to MCP servers.
 */
export class MCPClient {
  private config: Required<MCPClientConfig>;
  private servers: Map<string, MCPConnection> = new Map();
  private listeners: MCPEventListener[] = [];
  private dlq: DeadLetterQueue | null = null;
  private sessionId?: string;

  constructor(config: MCPClientConfig = {}) {
    this.config = {
      configPath: config.configPath || '.mcp.json',
      configPaths: config.configPaths ?? [],
      requestTimeout: config.requestTimeout ?? 30000,
      autoConnect: config.autoConnect ?? true,
      lazyLoading: config.lazyLoading ?? false,
      alwaysLoadTools: config.alwaysLoadTools ?? [],
      summaryDescriptionLimit: config.summaryDescriptionLimit ?? 100,
      maxToolsPerSearch: config.maxToolsPerSearch ?? 5,
    };
  }

  /**
   * Load servers from config file.
   */
  async loadFromConfig(configPath?: string): Promise<void> {
    const path = configPath || this.config.configPath;

    if (!existsSync(path)) {
      return; // No config file, silently skip
    }

    try {
      const content = await readFile(path, 'utf-8');
      const mcpConfig: MCPConfigFile = JSON.parse(content);

      for (const [name, serverConfig] of Object.entries(mcpConfig.servers)) {
        // Expand environment variables in config
        const expandedConfig = this.expandEnvVars(serverConfig);
        this.registerServer(name, expandedConfig);

        if (this.config.autoConnect) {
          await this.connectServer(name).catch(err => {
            logger.warn('Failed to connect to MCP server', { server: name, error: String(err.message) });
          });
        }
      }
    } catch (err) {
      logger.warn('Failed to load MCP config', { path, error: String(err) });
    }
  }

  /**
   * Load servers from multiple config files (hierarchical).
   * Later configs override earlier ones for the same server name.
   * Servers from all configs are merged together.
   */
  async loadFromHierarchicalConfigs(configPaths: string[]): Promise<void> {
    const mergedServers: Record<string, MCPServerConfig> = {};

    // Load and merge all configs
    for (const configPath of configPaths) {
      if (!existsSync(configPath)) {
        continue;
      }

      try {
        const content = await readFile(configPath, 'utf-8');
        const mcpConfig: MCPConfigFile = JSON.parse(content);

        // Merge servers (later overrides earlier)
        for (const [name, serverConfig] of Object.entries(mcpConfig.servers)) {
          mergedServers[name] = this.expandEnvVars(serverConfig);
        }
      } catch (err) {
        logger.warn('Failed to load MCP config', { configPath, error: String(err) });
      }
    }

    // Register all merged servers
    for (const [name, config] of Object.entries(mergedServers)) {
      this.registerServer(name, config);

      if (this.config.autoConnect) {
        await this.connectServer(name).catch(err => {
          logger.warn('Failed to connect to MCP server', { server: name, error: String(err.message) });
        });
      }
    }
  }

  /**
   * Expand environment variables in config.
   */
  private expandEnvVars(config: MCPServerConfig): MCPServerConfig {
    const expand = (str: string): string => {
      return str.replace(/\$\{(\w+)\}/g, (_, name) => process.env[name] || '');
    };

    return {
      command: expand(config.command),
      args: config.args?.map(expand),
      env: config.env
        ? Object.fromEntries(
            Object.entries(config.env).map(([k, v]) => [k, expand(v)])
          )
        : undefined,
      cwd: config.cwd ? expand(config.cwd) : undefined,
    };
  }

  /**
   * Register a server (without connecting).
   */
  registerServer(name: string, config: MCPServerConfig): void {
    this.servers.set(name, {
      name,
      config,
      process: null,
      readline: null,
      tools: [],
      status: 'disconnected',
      pendingRequests: new Map(),
      nextRequestId: 1,
      loadedTools: new Set(),
    });
  }

  /**
   * Connect to a registered server.
   */
  async connectServer(name: string): Promise<void> {
    const server = this.servers.get(name);
    if (!server) {
      throw MCPError.serverNotFound(name);
    }

    if (server.status === 'connected') {
      return; // Already connected
    }

    server.status = 'connecting';
    this.emit({ type: 'server.connecting', name });

    try {
      // Spawn the server process
      const proc = spawn(server.config.command, server.config.args || [], {
        env: { ...process.env, ...server.config.env },
        cwd: server.config.cwd,
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      server.process = proc;

      // Set up readline for stdout
      server.readline = createInterface({
        input: proc.stdout!,
        crlfDelay: Infinity,
      });

      // Handle incoming messages
      server.readline.on('line', (line) => {
        this.handleServerMessage(server, line);
      });

      // Handle errors
      proc.stderr?.on('data', (data) => {
        logger.error('MCP server stderr output', { server: name, output: data.toString() });
      });

      proc.on('error', (err) => {
        server.status = 'error';
        server.error = err.message;

        // CRITICAL: Reject ALL pending requests before clearing
        const errorMsg = new Error(`MCP server "${name}" process error: ${err.message}`);
        for (const [_id, pending] of server.pendingRequests) {
          pending.reject(errorMsg);
        }
        server.pendingRequests.clear();

        this.emit({ type: 'server.error', name, error: err.message });
      });

      proc.on('exit', (code, signal) => {
        // CRITICAL: Reject ALL pending requests before clearing
        // This prevents orphaned promises that never resolve
        const exitError = new Error(
          `MCP server "${name}" exited unexpectedly (code: ${code}, signal: ${signal})`
        );
        for (const [_id, pending] of server.pendingRequests) {
          pending.reject(exitError);
        }
        server.pendingRequests.clear();

        server.status = 'disconnected';
        server.process = null;
        server.readline = null;
        this.emit({ type: 'server.disconnected', name });
      });

      // Initialize the connection
      await this.initializeServer(server);

      server.status = 'connected';
      this.emit({ type: 'server.connected', name, toolCount: server.tools.length });
    } catch (err) {
      server.status = 'error';
      server.error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'server.error', name, error: server.error });
      throw err;
    }
  }

  /**
   * Initialize MCP protocol with server.
   */
  private async initializeServer(server: MCPConnection): Promise<void> {
    // Send initialize request
    const initResult = await this.sendRequest(server, 'initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: {
        name: 'first-principles-agent',
        version: '1.0.0',
      },
    });

    // Send initialized notification
    this.sendNotification(server, 'notifications/initialized', {});

    // List available tools
    const toolsResult = await this.sendRequest(server, 'tools/list', {}) as { tools: MCPToolDefinition[] };
    server.tools = toolsResult.tools || [];
  }

  /**
   * Send a JSON-RPC request and wait for response.
   */
  private sendRequest(server: MCPConnection, method: string, params: unknown): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const id = server.nextRequestId++;

      const request = {
        jsonrpc: '2.0',
        id,
        method,
        params,
      };

      server.pendingRequests.set(id, { resolve, reject });

      // Set timeout
      const timeout = setTimeout(() => {
        server.pendingRequests.delete(id);
        reject(MCPError.timeout(server.name, method));
      }, this.config.requestTimeout);

      // Store timeout to clear later
      const originalResolve = resolve;
      server.pendingRequests.set(id, {
        resolve: (result) => {
          clearTimeout(timeout);
          originalResolve(result);
        },
        reject: (error) => {
          clearTimeout(timeout);
          reject(error);
        },
      });

      // Send request
      server.process?.stdin?.write(JSON.stringify(request) + '\n');
    });
  }

  /**
   * Send a JSON-RPC notification (no response expected).
   */
  private sendNotification(server: MCPConnection, method: string, params: unknown): void {
    const notification = {
      jsonrpc: '2.0',
      method,
      params,
    };

    server.process?.stdin?.write(JSON.stringify(notification) + '\n');
  }

  /**
   * Handle incoming message from server.
   */
  private handleServerMessage(server: MCPConnection, line: string): void {
    let message: { id?: number; result?: unknown; error?: { message?: string } };

    try {
      message = JSON.parse(line);
    } catch (parseError) {
      // Log malformed JSON instead of silently ignoring
      // This helps diagnose protocol desync issues
      const preview = line.length > 100 ? line.substring(0, 100) + '...' : line;
      logger.error('Malformed JSON-RPC message from MCP server', { server: server.name, preview });
      this.emit({ type: 'server.error', name: server.name, error: 'Protocol error: malformed JSON' });
      return; // Don't crash, just skip this malformed message
    }

    // Handle response
    if (message.id !== undefined) {
      const pending = server.pendingRequests.get(message.id);
      if (pending) {
        server.pendingRequests.delete(message.id);
        if (message.error) {
          pending.reject(new Error(message.error.message || 'Unknown error'));
        } else {
          pending.resolve(message.result);
        }
      }
    }

    // Handle notifications from server (if any)
    // MCP servers can send notifications for things like resource updates
  }

  /**
   * Disconnect from a server.
   */
  async disconnectServer(name: string): Promise<void> {
    const server = this.servers.get(name);
    if (!server) {
      return;
    }

    if (server.process) {
      server.process.kill();
      server.process = null;
    }

    if (server.readline) {
      server.readline.close();
      server.readline = null;
    }

    server.status = 'disconnected';
    server.tools = [];
    this.emit({ type: 'server.disconnected', name });
  }

  /**
   * Call a tool on a specific server.
   * Includes automatic retry for transient failures (timeouts, connection resets).
   */
  async callTool(serverName: string, toolName: string, args: unknown): Promise<unknown> {
    const server = this.servers.get(serverName);
    if (!server) {
      throw MCPError.serverNotFound(serverName);
    }

    if (server.status !== 'connected') {
      throw MCPError.serverNotConnected(serverName);
    }

    this.emit({ type: 'tool.call', server: serverName, tool: toolName });

    try {
      // Wrap the request with retry logic for transient failures
      const result = await withRetry(
        async () => {
          return await this.sendRequest(server, 'tools/call', {
            name: toolName,
            arguments: args,
          }) as { content: Array<{ type: string; text?: string }> };
        },
        {
          maxAttempts: 2, // Initial + 1 retry
          ...MCP_RETRY_CONFIG,
          onRetry: (attempt, error, delay) => {
            this.emit({
              type: 'tool.call',
              server: serverName,
              tool: toolName,
              // @ts-expect-error Extended event with retry info
              retry: { attempt, error: error.message, delayMs: delay },
            });
          },
        }
      );

      this.emit({ type: 'tool.result', server: serverName, tool: toolName, success: true });

      // Extract text content from result
      const textContent = result.content
        ?.filter(c => c.type === 'text')
        .map(c => c.text)
        .join('\n');

      return textContent || result;
    } catch (err) {
      this.emit({ type: 'tool.result', server: serverName, tool: toolName, success: false });

      // Write to DLQ if the error is not recoverable (permanent failure)
      if (this.dlq?.isAvailable() && !isRecoverable(err)) {
        try {
          this.dlq.add({
            operation: `mcp:${serverName}:${toolName}`,
            args,
            error: err as Error,
            sessionId: this.sessionId,
          });
        } catch {
          // Don't let DLQ errors affect MCP execution
        }
      }

      throw err;
    }
  }

  /**
   * List all servers and their status.
   */
  listServers(): MCPServerInfo[] {
    return Array.from(this.servers.values()).map(s => ({
      name: s.name,
      status: s.status,
      toolCount: s.tools.length,
      error: s.error,
    }));
  }

  /**
   * Get tools from a specific server.
   */
  getServerTools(serverName: string): MCPToolDefinition[] {
    const server = this.servers.get(serverName);
    return server?.tools || [];
  }

  // ===========================================================================
  // LAZY LOADING METHODS
  // ===========================================================================

  /**
   * Get lightweight summaries for all tools (low token cost).
   * Use this for initial context, then load full definitions on-demand.
   */
  getAllToolSummaries(): MCPToolSummary[] {
    const summaries: MCPToolSummary[] = [];
    const descLimit = this.config.summaryDescriptionLimit;

    for (const server of this.servers.values()) {
      if (server.status !== 'connected') continue;

      for (const tool of server.tools) {
        const fullName = `mcp_${server.name}_${tool.name}`;
        const desc = tool.description || `MCP tool: ${tool.name}`;

        summaries.push({
          name: fullName,
          description: desc.length > descLimit ? desc.slice(0, descLimit) + '...' : desc,
          serverName: server.name,
          originalName: tool.name,
        });
      }
    }

    return summaries;
  }

  /**
   * Search tools by name or description with BM25-style scoring.
   * Returns matching tool summaries sorted by relevance.
   */
  searchTools(
    query: string,
    options: { limit?: number; regex?: boolean } = {}
  ): MCPToolSummary[] {
    const { limit = this.config.maxToolsPerSearch, regex = false } = options;
    const summaries = this.getAllToolSummaries();

    if (!query.trim()) {
      return summaries.slice(0, limit);
    }

    // Normalize query
    const queryLower = query.toLowerCase();
    const queryTerms = queryLower.split(/\s+/).filter(t => t.length > 0);

    // Score each tool
    const scored = summaries.map(summary => {
      let score = 0;
      const nameLower = summary.name.toLowerCase();
      const descLower = summary.description.toLowerCase();
      const originalLower = summary.originalName.toLowerCase();

      if (regex) {
        try {
          const re = new RegExp(query, 'i');
          if (re.test(summary.name)) score += 10;
          if (re.test(summary.description)) score += 5;
          if (re.test(summary.originalName)) score += 8;
        } catch {
          // Invalid regex, fall back to substring matching
        }
      }

      // BM25-style term frequency scoring
      for (const term of queryTerms) {
        // Exact match bonuses
        if (originalLower === term) score += 20;
        if (nameLower.includes(term)) score += 10;
        if (originalLower.includes(term)) score += 8;
        if (descLower.includes(term)) score += 3;

        // Partial match (prefix)
        if (originalLower.startsWith(term)) score += 5;
      }

      // Boost if all terms appear
      const allTermsInName = queryTerms.every(t => nameLower.includes(t));
      const allTermsInDesc = queryTerms.every(t => descLower.includes(t));
      if (allTermsInName) score += 15;
      if (allTermsInDesc) score += 5;

      return { summary, score };
    });

    // Filter and sort by score
    const results = scored
      .filter(s => s.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map(s => s.summary);

    this.emit({ type: 'tool.search', query, resultCount: results.length });

    return results;
  }

  /**
   * Get full tool definition for a specific tool.
   * Marks the tool as loaded for context tracking.
   */
  getFullToolDefinition(toolName: string): ToolDefinition | null {
    // Parse tool name: mcp_{serverName}_{originalToolName}
    const match = toolName.match(/^mcp_([^_]+)_(.+)$/);
    if (!match) return null;

    const [, serverName, originalName] = match;
    const server = this.servers.get(serverName);
    if (!server || server.status !== 'connected') return null;

    const mcpTool = server.tools.find(t => t.name === originalName);
    if (!mcpTool) return null;

    // Mark as loaded
    server.loadedTools.add(originalName);
    this.emit({ type: 'tool.dynamicLoad', name: toolName, serverName });

    return {
      name: toolName,
      description: mcpTool.description || `MCP tool: ${mcpTool.name} (from ${serverName})`,
      parameters: mcpTool.inputSchema as Record<string, unknown> || { type: 'object', properties: {} },
      execute: async (args: Record<string, unknown>) => {
        return this.callTool(serverName, originalName, args);
      },
    };
  }

  /**
   * Batch load multiple tools by name.
   * Returns array of loaded ToolDefinitions.
   */
  loadTools(toolNames: string[]): ToolDefinition[] {
    const loaded: ToolDefinition[] = [];

    for (const name of toolNames) {
      const tool = this.getFullToolDefinition(name);
      if (tool) {
        loaded.push(tool);
      }
    }

    return loaded;
  }

  /**
   * Get context statistics for MCP tools.
   * Useful for monitoring token usage with lazy loading.
   */
  getContextStats(): MCPContextStats {
    let summaryCount = 0;
    let loadedCount = 0;
    let summaryTokens = 0;
    let definitionTokens = 0;

    for (const server of this.servers.values()) {
      if (server.status !== 'connected') continue;

      for (const tool of server.tools) {
        const isLoaded = server.loadedTools.has(tool.name);

        if (isLoaded) {
          loadedCount++;
          // Full definition tokens: name + description + schema
          const schemaStr = tool.inputSchema ? JSON.stringify(tool.inputSchema) : '{}';
          const defChars = (tool.name.length) +
                          (tool.description?.length || 0) +
                          schemaStr.length;
          definitionTokens += Math.ceil(defChars / 4); // ~4 chars per token
        } else {
          summaryCount++;
          // Summary tokens: name + truncated description
          const descLen = Math.min(
            tool.description?.length || 0,
            this.config.summaryDescriptionLimit
          );
          const sumChars = tool.name.length + descLen + server.name.length;
          summaryTokens += Math.ceil(sumChars / 4);
        }
      }
    }

    return {
      summaryTokens,
      definitionTokens,
      summaryCount,
      loadedCount,
      totalTools: summaryCount + loadedCount,
    };
  }

  /**
   * Check if a tool is fully loaded (has schema in context).
   */
  isToolLoaded(toolName: string): boolean {
    const match = toolName.match(/^mcp_([^_]+)_(.+)$/);
    if (!match) return false;

    const [, serverName, originalName] = match;
    const server = this.servers.get(serverName);
    return server?.loadedTools.has(originalName) ?? false;
  }

  /**
   * Get all tools with lazy loading support.
   * When lazyMode is true, only returns always-loaded tools + previously loaded tools.
   * When lazyMode is false (default), returns all tools with full definitions.
   */
  getAllTools(options: { lazyMode?: boolean } = {}): ToolDefinition[] {
    const { lazyMode = this.config.lazyLoading } = options;

    if (!lazyMode) {
      // Original behavior: return all tools with full definitions
      const tools: ToolDefinition[] = [];

      for (const server of this.servers.values()) {
        if (server.status !== 'connected') continue;

        for (const tool of server.tools) {
          tools.push({
            name: `mcp_${server.name}_${tool.name}`,
            description: tool.description || `MCP tool: ${tool.name} (from ${server.name})`,
            parameters: tool.inputSchema as Record<string, unknown> || { type: 'object', properties: {} },
            execute: async (args: Record<string, unknown>) => {
              return this.callTool(server.name, tool.name, args);
            },
          });
        }
      }

      // Validate tool descriptions (non-invasive: logs warnings, doesn't reject tools)
      if (tools.length > 0) {
        try {
          const results = validateAllTools(tools);
          const poor = results.filter(r => r.score < 50);
          if (poor.length > 0) {
            logger.warn('MCP tool quality issues detected', { poorCount: poor.length, totalCount: tools.length, summary: formatValidationSummary(poor) });
          }
        } catch {
          // Validation is optional — don't fail if module has issues
        }
      }

      return tools;
    }

    // Lazy mode: only return always-loaded tools + previously loaded tools
    const tools: ToolDefinition[] = [];

    for (const server of this.servers.values()) {
      if (server.status !== 'connected') continue;

      for (const tool of server.tools) {
        const fullName = `mcp_${server.name}_${tool.name}`;
        const isAlwaysLoaded = this.config.alwaysLoadTools.some(
          pattern => fullName.includes(pattern) || tool.name.includes(pattern)
        );
        const isPreviouslyLoaded = server.loadedTools.has(tool.name);

        if (isAlwaysLoaded || isPreviouslyLoaded) {
          // Mark as loaded
          server.loadedTools.add(tool.name);

          tools.push({
            name: fullName,
            description: tool.description || `MCP tool: ${tool.name} (from ${server.name})`,
            parameters: tool.inputSchema as Record<string, unknown> || { type: 'object', properties: {} },
            execute: async (args: Record<string, unknown>) => {
              return this.callTool(server.name, tool.name, args);
            },
          });
        }
      }
    }

    return tools;
  }

  /**
   * Check if a server is connected.
   */
  isConnected(serverName: string): boolean {
    const server = this.servers.get(serverName);
    return server?.status === 'connected';
  }

  /**
   * Subscribe to events.
   */
  on(listener: MCPEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Set the dead letter queue for failed operation tracking.
   * When set, permanent failures will be logged to the DLQ for later retry.
   */
  setDeadLetterQueue(dlq: DeadLetterQueue | null, sessionId?: string): void {
    this.dlq = dlq;
    this.sessionId = sessionId;
  }

  /**
   * Emit an event.
   */
  private emit(event: MCPEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Cleanup - disconnect all servers.
   */
  async cleanup(): Promise<void> {
    for (const name of this.servers.keys()) {
      await this.disconnectServer(name);
    }
    this.servers.clear();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create and initialize an MCP client.
 */
export async function createMCPClient(config?: MCPClientConfig): Promise<MCPClient> {
  const client = new MCPClient(config);

  // Use hierarchical loading if configPaths provided, otherwise single config
  if (config?.configPaths && config.configPaths.length > 0) {
    await client.loadFromHierarchicalConfigs(config.configPaths);
  } else {
    await client.loadFromConfig();
  }

  return client;
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format server list for display.
 */
export function formatServerList(servers: MCPServerInfo[]): string {
  if (servers.length === 0) {
    return 'No MCP servers configured.';
  }

  const lines: string[] = ['MCP Servers:'];

  for (const server of servers) {
    const statusIcon = server.status === 'connected' ? '✓' : server.status === 'error' ? '✗' : '○';
    const statusColor = server.status === 'connected' ? 'green' : server.status === 'error' ? 'red' : 'dim';
    lines.push(`  ${statusIcon} ${server.name} (${server.status}) - ${server.toolCount} tools`);
    if (server.error) {
      lines.push(`      Error: ${server.error}`);
    }
  }

  return lines.join('\n');
}

/**
 * Create a sample .mcp.json config file content.
 */
export function getSampleMCPConfig(): string {
  return JSON.stringify({
    servers: {
      filesystem: {
        command: 'npx',
        args: ['-y', '@anthropic/mcp-server-filesystem', '/path/to/allowed/dir'],
      },
      sqlite: {
        command: 'npx',
        args: ['-y', '@anthropic/mcp-server-sqlite', '~/database.db'],
      },
      github: {
        command: 'npx',
        args: ['-y', '@anthropic/mcp-server-github'],
        env: {
          GITHUB_TOKEN: '${GITHUB_TOKEN}',
        },
      },
    },
  }, null, 2);
}
