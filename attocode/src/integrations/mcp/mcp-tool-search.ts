/**
 * MCP Tool Search
 *
 * Provides a meta-tool for searching and dynamically loading MCP tools.
 * Enables lazy loading of tool schemas to reduce context window usage.
 *
 * Token Savings:
 * - 50 tools with full schemas: ~15,000 tokens
 * - 50 tools as summaries: ~2,500 tokens
 * - Savings: ~83% reduction in MCP tool context
 */

import type { ToolDefinition } from '../../types.js';
import type { MCPClient, MCPToolSummary } from './mcp-client.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Search result returned by the tool.
 */
export interface MCPToolSearchResult {
  /** Matching tools */
  tools: MCPToolSummary[];
  /** Total tools available (for pagination info) */
  totalAvailable: number;
  /** Whether tools were auto-loaded */
  autoLoaded: boolean;
  /** Message about what was found */
  message: string;
}

/**
 * Options for creating the search tool.
 */
export interface MCPToolSearchOptions {
  /** Auto-load found tools (default: true) */
  autoLoad?: boolean;
  /** Max results per search (default: 5) */
  defaultLimit?: number;
  /** Callback when tools are loaded */
  onToolsLoaded?: (tools: ToolDefinition[]) => void;
}

// =============================================================================
// TOOL SEARCH TOOL
// =============================================================================

/**
 * Create the mcp_tool_search tool.
 *
 * This tool allows the agent to search for MCP tools by name or description,
 * then automatically loads matching tools so they become available for use.
 *
 * @example
 * // Search for browser tools
 * mcp_tool_search({ query: "browser click" })
 *
 * // Search with regex
 * mcp_tool_search({ query: "browser_(click|hover)", regex: true })
 *
 * // Limit results
 * mcp_tool_search({ query: "screenshot", limit: 3 })
 */
export function createMCPToolSearchTool(
  mcpClient: MCPClient,
  options: MCPToolSearchOptions = {},
): ToolDefinition {
  const { autoLoad = true, defaultLimit = 5, onToolsLoaded } = options;

  return {
    name: 'mcp_tool_search',
    description: `Search for MCP tools by name or description.
Found tools are automatically loaded and become available for use.

Examples:
- "browser click" - find click-related browser tools
- "screenshot" - find screenshot tools
- "file read" - find file reading tools

Use this when you need an MCP tool but don't see it in your available tools.`,
    parameters: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search keywords (e.g., "browser click", "file read")',
        },
        regex: {
          type: 'boolean',
          description: 'Use regex matching instead of keyword search',
        },
        limit: {
          type: 'number',
          description: `Max results to return (default: ${defaultLimit})`,
        },
      },
      required: ['query'],
    },
    execute: async (args: Record<string, unknown>): Promise<MCPToolSearchResult> => {
      const query = String(args.query || '');
      const regex = Boolean(args.regex);
      const limit = typeof args.limit === 'number' ? args.limit : defaultLimit;

      // Search for matching tools
      const matches = mcpClient.searchTools(query, { limit, regex });

      // Get total count for context
      const allSummaries = mcpClient.getAllToolSummaries();
      const totalAvailable = allSummaries.length;

      // Auto-load found tools if enabled
      let loadedTools: ToolDefinition[] = [];
      if (autoLoad && matches.length > 0) {
        loadedTools = mcpClient.loadTools(matches.map((m) => m.name));

        // Notify callback if provided
        if (onToolsLoaded && loadedTools.length > 0) {
          onToolsLoaded(loadedTools);
        }
      }

      // Build result message
      let message: string;
      if (matches.length === 0) {
        message = `No tools found matching "${query}". Try different keywords.`;
      } else if (autoLoad) {
        message = `Found and loaded ${matches.length} tool(s) matching "${query}". They are now available for use.`;
      } else {
        message = `Found ${matches.length} tool(s) matching "${query}".`;
      }

      return {
        tools: matches,
        totalAvailable,
        autoLoaded: autoLoad && matches.length > 0,
        message,
      };
    },
  };
}

/**
 * Create a tool that lists all available MCP tools as summaries.
 * Useful when the agent needs to understand what tools are available.
 */
export function createMCPToolListTool(mcpClient: MCPClient): ToolDefinition {
  return {
    name: 'mcp_tool_list',
    description: `List all available MCP tools with brief descriptions.
Use this to see what tools are available before searching for specific ones.`,
    parameters: {
      type: 'object',
      properties: {
        server: {
          type: 'string',
          description: 'Filter by server name (optional)',
        },
      },
    },
    execute: async (
      args: Record<string, unknown>,
    ): Promise<{ tools: MCPToolSummary[]; count: number }> => {
      const serverFilter = args.server ? String(args.server) : undefined;

      let summaries = mcpClient.getAllToolSummaries();

      if (serverFilter) {
        summaries = summaries.filter((s) => s.serverName === serverFilter);
      }

      return {
        tools: summaries,
        count: summaries.length,
      };
    },
  };
}

/**
 * Create a tool that shows MCP context usage statistics.
 * Useful for monitoring token usage with lazy loading.
 */
export function createMCPContextStatsTool(mcpClient: MCPClient): ToolDefinition {
  return {
    name: 'mcp_context_stats',
    description: `Show MCP tool context usage statistics.
Reports token usage for tool summaries vs full definitions.`,
    parameters: {
      type: 'object',
      properties: {},
    },
    execute: async (): Promise<{
      stats: ReturnType<typeof mcpClient.getContextStats>;
      savings: string;
      recommendation: string;
    }> => {
      const stats = mcpClient.getContextStats();

      // Calculate savings
      const fullLoadTokens = stats.totalTools * 200; // Estimate: ~200 tokens per full tool
      const currentTokens = stats.summaryTokens + stats.definitionTokens;
      const savingsPercent =
        fullLoadTokens > 0 ? Math.round((1 - currentTokens / fullLoadTokens) * 100) : 0;

      // Generate recommendation
      let recommendation: string;
      if (stats.loadedCount > 20) {
        recommendation =
          'Consider using lazy loading more aggressively - many tools are fully loaded.';
      } else if (stats.loadedCount === 0) {
        recommendation =
          'All tools are summaries. Use mcp_tool_search to load specific tools when needed.';
      } else {
        recommendation = `Good balance: ${stats.loadedCount} tools loaded, ${stats.summaryCount} as summaries.`;
      }

      return {
        stats,
        savings: `${savingsPercent}% token savings vs loading all full schemas`,
        recommendation,
      };
    },
  };
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create all MCP meta-tools for dynamic tool discovery.
 */
export function createMCPMetaTools(
  mcpClient: MCPClient,
  options: MCPToolSearchOptions = {},
): ToolDefinition[] {
  return [
    createMCPToolSearchTool(mcpClient, options),
    createMCPToolListTool(mcpClient),
    createMCPContextStatsTool(mcpClient),
  ];
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Format tool summaries for display.
 */
export function formatToolSummaries(summaries: MCPToolSummary[]): string {
  if (summaries.length === 0) {
    return 'No tools available.';
  }

  const lines = ['MCP Tools:'];

  // Group by server
  const byServer = new Map<string, MCPToolSummary[]>();
  for (const s of summaries) {
    const existing = byServer.get(s.serverName) || [];
    existing.push(s);
    byServer.set(s.serverName, existing);
  }

  for (const [server, tools] of byServer) {
    lines.push(`\n  ${server}:`);
    for (const tool of tools) {
      lines.push(`    - ${tool.originalName}: ${tool.description}`);
    }
  }

  return lines.join('\n');
}

/**
 * Format context stats for display.
 */
export function formatContextStats(stats: ReturnType<MCPClient['getContextStats']>): string {
  const total = stats.summaryTokens + stats.definitionTokens;

  return `MCP Tool Context:
  Tool summaries:    ${stats.summaryCount} tools (~${stats.summaryTokens.toLocaleString()} tokens)
  Full definitions:  ${stats.loadedCount} tools (~${stats.definitionTokens.toLocaleString()} tokens)
  Total:             ${stats.totalTools} tools (~${total.toLocaleString()} tokens)`;
}
