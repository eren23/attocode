/**
 * Exercise 7: MCP Tool Discovery
 *
 * Implement a tool discovery system for searching and summarizing MCP tools.
 */

// =============================================================================
// TYPES
// =============================================================================

export interface ToolParameter {
  name: string;
  type: string;
  description?: string;
  required?: boolean;
}

export interface ToolInfo {
  name: string;
  description: string;
  category?: string;
  parameters?: ToolParameter[];
  source?: string; // Which MCP server provided this tool
}

// =============================================================================
// TODO: Implement ToolDiscovery
// =============================================================================

/**
 * A system for discovering and searching MCP tools.
 *
 * TODO: Implement this class with the following:
 *
 * 1. registerTool(tool):
 *    - Store tool by name
 *    - Handle duplicates (update existing)
 *
 * 2. search(query):
 *    - Search by name (partial match, case-insensitive)
 *    - Search by description keywords
 *    - Return matching tools sorted by relevance
 *
 * 3. getSummary(tools?):
 *    - If tools provided, summarize those
 *    - Otherwise summarize all registered tools
 *    - Format suitable for LLM system prompts
 *
 * 4. getByCategory(category):
 *    - Return tools matching category
 *    - Case-insensitive comparison
 *
 * 5. getAllTools():
 *    - Return all registered tools
 */
export class ToolDiscovery {
  // TODO: Add private storage
  // private tools: Map<string, ToolInfo> = new Map();

  /**
   * Register a tool for discovery.
   */
  registerTool(_tool: ToolInfo): void {
    // TODO: Implement
    throw new Error('TODO: Implement registerTool');
  }

  /**
   * Register multiple tools at once.
   */
  registerTools(tools: ToolInfo[]): void {
    for (const tool of tools) {
      this.registerTool(tool);
    }
  }

  /**
   * Search tools by name or description.
   */
  search(_query: string): ToolInfo[] {
    // TODO: Implement search
    // 1. Convert query to lowercase
    // 2. Search tool names (partial match)
    // 3. Search descriptions (keyword match)
    // 4. Score and sort by relevance
    // 5. Return matching tools
    throw new Error('TODO: Implement search');
  }

  /**
   * Get tools by category.
   */
  getByCategory(_category: string): ToolInfo[] {
    // TODO: Implement category filter
    throw new Error('TODO: Implement getByCategory');
  }

  /**
   * Get all registered tools.
   */
  getAllTools(): ToolInfo[] {
    // TODO: Return all tools
    throw new Error('TODO: Implement getAllTools');
  }

  /**
   * Get count of registered tools.
   */
  getToolCount(): number {
    // TODO: Return count
    throw new Error('TODO: Implement getToolCount');
  }

  /**
   * Generate a summary of tools for LLM context.
   */
  getSummary(tools?: ToolInfo[]): string {
    // TODO: Implement summary generation
    // Format example:
    // Available tools:
    // - read_file: Read contents of a file
    //   Parameters: path (string, required)
    // - write_file: Write content to a file
    //   Parameters: path (string), content (string)
    throw new Error('TODO: Implement getSummary');
  }
}

// =============================================================================
// HELPER: Format tool for summary
// =============================================================================

/**
 * Format a single tool for the summary.
 * You can use this helper in getSummary.
 */
export function formatToolForSummary(tool: ToolInfo): string {
  let result = `- ${tool.name}: ${tool.description}`;

  if (tool.parameters && tool.parameters.length > 0) {
    const params = tool.parameters.map(p => {
      let param = `${p.name} (${p.type}`;
      if (p.required) param += ', required';
      param += ')';
      return param;
    });
    result += `\n  Parameters: ${params.join(', ')}`;
  }

  return result;
}
