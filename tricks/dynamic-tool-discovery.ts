/**
 * Trick: Dynamic MCP Tool Discovery
 *
 * Load MCP tool summaries initially, fetch full definitions on-demand.
 * Dramatically reduces context window usage for agents with many MCP tools.
 *
 * PROBLEM:
 * MCP servers can expose 50+ tools, each consuming ~200-500 tokens for full
 * schema definitions. This quickly eats into context window limits.
 *
 * SOLUTION:
 * 1. Load lightweight summaries (~50 tokens/tool) initially
 * 2. Provide a meta-tool (mcp_tool_search) for on-demand loading
 * 3. Track which tools are fully loaded vs summary-only
 *
 * TOKEN SAVINGS:
 * - 50 tools with full schemas: ~15,000 tokens
 * - 50 tools as summaries: ~2,500 tokens
 * - Savings: ~83% reduction in MCP tool context
 */

// =============================================================================
// CONCEPTS
// =============================================================================

/**
 * Tool Summary vs Full Definition
 *
 * Summary (~50 tokens):
 * - name: "mcp_playwright_browser_click"
 * - description: "Click on element (truncated to 100 chars)..."
 * - serverName: "playwright"
 * - originalName: "browser_click"
 *
 * Full Definition (~200-500 tokens):
 * - name: "mcp_playwright_browser_click"
 * - description: Full description with usage examples
 * - parameters: Complete JSON schema with all properties, types, descriptions
 * - execute: Function reference
 */

// =============================================================================
// IMPLEMENTATION PATTERN
// =============================================================================

/**
 * Step 1: Configure MCPClient with lazy loading
 */
export const configureWithLazyLoading = `
const mcpClient = await createMCPClient({
  configPath: '.mcp.json',
  lazyLoading: true,              // Enable lazy loading
  alwaysLoadTools: [              // Tools to always have full schemas
    'browser_snapshot',
    'browser_navigate',
  ],
  summaryDescriptionLimit: 100,   // Max chars for summary descriptions
  maxToolsPerSearch: 5,           // Default results per search
});
`;

/**
 * Step 2: Add meta-tools to agent
 */
export const addMetaTools = `
import { createMCPMetaTools } from './integrations/mcp-tool-search.js';

// Create meta-tools with callback for dynamic loading
const metaTools = createMCPMetaTools(mcpClient, {
  autoLoad: true,
  defaultLimit: 5,
  onToolsLoaded: (tools) => {
    // Add newly loaded tools to agent
    for (const tool of tools) {
      agent.addTool(tool);
    }
    console.log(\`Loaded \${tools.length} tools\`);
  },
});

// Add meta-tools to agent
for (const tool of metaTools) {
  agent.addTool(tool);
}
`;

/**
 * Step 3: Use the search tool in prompts
 */
export const useInPrompts = `
// In system prompt or user message:
"If you need to interact with a browser but don't see the tool available,
use mcp_tool_search to find and load it:

Example: mcp_tool_search({ query: 'browser click' })

This will search for matching tools and automatically load them for use."
`;

/**
 * Step 4: Monitor context usage
 */
export const monitorContext = `
// Get context stats
const stats = mcpClient.getContextStats();
console.log(\`
  Tool summaries:   \${stats.summaryCount} tools (~\${stats.summaryTokens} tokens)
  Full definitions: \${stats.loadedCount} tools (~\${stats.definitionTokens} tokens)
  Total:            \${stats.totalTools} tools
\`);

// Calculate savings
const fullLoadEstimate = stats.totalTools * 200;
const currentTokens = stats.summaryTokens + stats.definitionTokens;
const savings = Math.round((1 - currentTokens / fullLoadEstimate) * 100);
console.log(\`Context savings: \${savings}%\`);
`;

// =============================================================================
// BEST PRACTICES
// =============================================================================

/**
 * Best Practices for Dynamic Tool Discovery
 *
 * 1. ALWAYS-LOAD TOOLS
 *    Keep 3-5 most commonly used tools always loaded.
 *    - Navigation/core tools the agent uses frequently
 *    - Tools that are always needed for basic functionality
 *    Example: browser_snapshot, browser_navigate for Playwright
 *
 * 2. SEARCH QUERY DESIGN
 *    Use clear, specific search queries:
 *    - Good: "browser click", "screenshot", "file read"
 *    - Bad: "do something", "help", "tool"
 *
 * 3. BATCH LOADING
 *    When you know you'll need multiple related tools:
 *    mcpClient.loadTools(['mcp_x_tool1', 'mcp_x_tool2', 'mcp_x_tool3'])
 *
 * 4. CONTEXT MONITORING
 *    Check context stats periodically, especially for long sessions:
 *    - If loadedCount > 20, consider if all loaded tools are still needed
 *    - Reset loaded tools between unrelated tasks
 *
 * 5. PROMPT GUIDANCE
 *    Include guidance in system prompt about when to search for tools:
 *    "If a tool for [task] isn't available, search for it first."
 */

// =============================================================================
// TYPES REFERENCE
// =============================================================================

/**
 * MCPToolSummary - Lightweight tool representation
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
 * MCPContextStats - Context usage statistics
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
 * MCPClientConfig - Configuration options
 */
export interface LazyLoadingConfig {
  /** Enable lazy loading of tool schemas (default: false) */
  lazyLoading?: boolean;
  /** Tools to always load fully (bypass lazy loading) */
  alwaysLoadTools?: string[];
  /** Max chars for summary descriptions (default: 100) */
  summaryDescriptionLimit?: number;
  /** Max results per search query (default: 5) */
  maxToolsPerSearch?: number;
}

// =============================================================================
// COMPLETE EXAMPLE
// =============================================================================

/**
 * Full Integration Example
 */
export const fullExample = `
import { createMCPClient, createMCPMetaTools } from './integrations/index.js';

async function setupAgent() {
  // 1. Create MCP client with lazy loading
  const mcpClient = await createMCPClient({
    configPath: '.mcp.json',
    lazyLoading: true,
    alwaysLoadTools: ['browser_snapshot', 'browser_navigate'],
    maxToolsPerSearch: 5,
  });

  // 2. Create agent
  const agent = createProductionAgent({ /* config */ });

  // 3. Add only always-loaded MCP tools initially
  const initialTools = mcpClient.getAllTools({ lazyMode: true });
  for (const tool of initialTools) {
    agent.addTool(tool);
  }

  // 4. Add meta-tools for dynamic loading
  const metaTools = createMCPMetaTools(mcpClient, {
    onToolsLoaded: (tools) => {
      for (const tool of tools) agent.addTool(tool);
    },
  });
  for (const tool of metaTools) {
    agent.addTool(tool);
  }

  // 5. Add guidance to system prompt
  agent.setSystemPrompt(\`
    You have access to MCP tools. Some tools are available immediately,
    others can be loaded on-demand.

    Available meta-tools:
    - mcp_tool_search: Search for tools by name/description
    - mcp_tool_list: List all available tools
    - mcp_context_stats: Check context usage

    If you need a tool that's not available, use mcp_tool_search first.
  \`);

  return { agent, mcpClient };
}
`;

// =============================================================================
// TROUBLESHOOTING
// =============================================================================

/**
 * Common Issues and Solutions
 *
 * ISSUE: Tool not found after search
 * CAUSE: Search query too specific or tool name mismatch
 * FIX: Use broader search terms, check mcp_tool_list for exact names
 *
 * ISSUE: High context usage despite lazy loading
 * CAUSE: Too many tools loaded over time
 * FIX: Reset agent between tasks, reduce alwaysLoadTools list
 *
 * ISSUE: Agent doesn't know to search for tools
 * CAUSE: Missing guidance in system prompt
 * FIX: Add explicit instructions about using mcp_tool_search
 *
 * ISSUE: Tool loaded but not working
 * CAUSE: Tool wasn't added to agent after loading
 * FIX: Ensure onToolsLoaded callback adds tools to agent
 */

// Usage:
// See 25-production-agent/main.ts for full integration
// Use /mcp stats in REPL to check context usage
// Use /mcp search <query> to search and load tools
