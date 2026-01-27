/**
 * Lesson 7: MCP Tools Integration
 * 
 * Convert MCP tools to agent-compatible tools.
 */

import type { MCPClient } from './mcp-client.js';
import type { MCPTool, MCPToolCallResult, MCPContent } from './types.js';

// =============================================================================
// AGENT TOOL INTERFACE
// =============================================================================

export interface AgentTool {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  execute: (input: Record<string, unknown>) => Promise<{
    success: boolean;
    output: string;
  }>;
}

// =============================================================================
// MCP TO AGENT TOOL CONVERTER
// =============================================================================

/**
 * Convert an MCP tool to an agent tool.
 */
export function mcpToolToAgentTool(
  mcpTool: MCPTool,
  client: MCPClient
): AgentTool {
  return {
    name: mcpTool.name,
    description: mcpTool.description ?? `MCP tool: ${mcpTool.name}`,
    parameters: mcpTool.inputSchema as Record<string, unknown>,
    
    execute: async (input: Record<string, unknown>) => {
      try {
        const result = await client.callTool(mcpTool.name, input);
        return {
          success: !result.isError,
          output: formatMCPContent(result.content),
        };
      } catch (error) {
        return {
          success: false,
          output: `MCP tool error: ${(error as Error).message}`,
        };
      }
    },
  };
}

/**
 * Get all tools from an MCP client as agent tools.
 */
export async function getMCPTools(client: MCPClient): Promise<AgentTool[]> {
  const mcpTools = await client.listTools();
  return mcpTools.map(tool => mcpToolToAgentTool(tool, client));
}

/**
 * Format MCP content for output.
 */
function formatMCPContent(content: MCPContent[]): string {
  return content
    .map(item => {
      switch (item.type) {
        case 'text':
          return item.text;
        case 'image':
          return `[Image: ${item.mimeType}]`;
        case 'resource':
          return item.resource.text ?? `[Resource: ${item.resource.uri}]`;
        default:
          return '[Unknown content type]';
      }
    })
    .join('\n');
}

// =============================================================================
// MCP TOOL MANAGER
// =============================================================================

/**
 * Manages tools from multiple MCP servers.
 */
export class MCPToolManager {
  private clients: Map<string, MCPClient> = new Map();
  private tools: Map<string, { client: MCPClient; tool: MCPTool }> = new Map();

  /**
   * Add an MCP client.
   */
  async addClient(name: string, client: MCPClient): Promise<void> {
    this.clients.set(name, client);
    
    // Load tools from this client
    const tools = await client.listTools();
    for (const tool of tools) {
      // Prefix tool name with client name if there's a conflict
      const toolName = this.tools.has(tool.name) 
        ? `${name}:${tool.name}` 
        : tool.name;
      
      this.tools.set(toolName, { client, tool });
    }
  }

  /**
   * Remove an MCP client.
   */
  removeClient(name: string): void {
    const client = this.clients.get(name);
    if (!client) return;

    // Remove tools from this client
    for (const [toolName, entry] of this.tools) {
      if (entry.client === client) {
        this.tools.delete(toolName);
      }
    }

    this.clients.delete(name);
  }

  /**
   * List all available tools.
   */
  listTools(): string[] {
    return Array.from(this.tools.keys());
  }

  /**
   * Get tool descriptions for the LLM.
   */
  getToolDescriptions(): Array<{
    name: string;
    description: string;
    input_schema: Record<string, unknown>;
  }> {
    return Array.from(this.tools.entries()).map(([name, { tool }]) => ({
      name,
      description: tool.description ?? `MCP tool: ${name}`,
      input_schema: tool.inputSchema as Record<string, unknown>,
    }));
  }

  /**
   * Call a tool by name.
   */
  async callTool(
    name: string,
    args: Record<string, unknown>
  ): Promise<{ success: boolean; output: string }> {
    const entry = this.tools.get(name);
    
    if (!entry) {
      return {
        success: false,
        output: `Unknown tool: ${name}. Available tools: ${this.listTools().join(', ')}`,
      };
    }

    try {
      const result = await entry.client.callTool(entry.tool.name, args);
      return {
        success: !result.isError,
        output: formatMCPContent(result.content),
      };
    } catch (error) {
      return {
        success: false,
        output: `MCP tool error: ${(error as Error).message}`,
      };
    }
  }

  /**
   * Get all tools as agent tools.
   */
  getAgentTools(): AgentTool[] {
    return Array.from(this.tools.entries()).map(([name, { client, tool }]) => ({
      name,
      description: tool.description ?? `MCP tool: ${name}`,
      parameters: tool.inputSchema as Record<string, unknown>,
      execute: async (input: Record<string, unknown>) => {
        return this.callTool(name, input);
      },
    }));
  }
}
