/**
 * Exercise 7: MCP Tool Discovery - REFERENCE SOLUTION
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
  source?: string;
}

// =============================================================================
// HELPER
// =============================================================================

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

// =============================================================================
// SOLUTION: ToolDiscovery
// =============================================================================

export class ToolDiscovery {
  private tools: Map<string, ToolInfo> = new Map();

  registerTool(tool: ToolInfo): void {
    this.tools.set(tool.name, tool);
  }

  registerTools(tools: ToolInfo[]): void {
    for (const tool of tools) {
      this.registerTool(tool);
    }
  }

  search(query: string): ToolInfo[] {
    const queryLower = query.toLowerCase();
    const results: Array<{ tool: ToolInfo; score: number }> = [];

    for (const tool of this.tools.values()) {
      let score = 0;

      // Name exact match (highest score)
      if (tool.name.toLowerCase() === queryLower) {
        score += 100;
      }
      // Name starts with query
      else if (tool.name.toLowerCase().startsWith(queryLower)) {
        score += 50;
      }
      // Name contains query
      else if (tool.name.toLowerCase().includes(queryLower)) {
        score += 25;
      }

      // Description contains query
      if (tool.description.toLowerCase().includes(queryLower)) {
        score += 10;
      }

      // Category matches
      if (tool.category?.toLowerCase().includes(queryLower)) {
        score += 15;
      }

      if (score > 0) {
        results.push({ tool, score });
      }
    }

    // Sort by score descending
    results.sort((a, b) => b.score - a.score);

    return results.map(r => r.tool);
  }

  getByCategory(category: string): ToolInfo[] {
    const categoryLower = category.toLowerCase();
    const results: ToolInfo[] = [];

    for (const tool of this.tools.values()) {
      if (tool.category?.toLowerCase() === categoryLower) {
        results.push(tool);
      }
    }

    return results;
  }

  getAllTools(): ToolInfo[] {
    return Array.from(this.tools.values());
  }

  getToolCount(): number {
    return this.tools.size;
  }

  getSummary(tools?: ToolInfo[]): string {
    const toolsToSummarize = tools ?? this.getAllTools();

    if (toolsToSummarize.length === 0) {
      return 'No tools available.';
    }

    const header = 'Available tools:';
    const toolLines = toolsToSummarize.map(formatToolForSummary);

    return `${header}\n${toolLines.join('\n')}`;
  }
}
