/**
 * Tool Recommendation Engine
 *
 * Heuristic-based tool recommendation for subagents and swarm workers.
 * Maps task types to tool categories and analyzes task descriptions
 * for tool-relevant keywords.
 *
 * Key features:
 * - Static task-type → tool-category mappings (no LLM call needed)
 * - Keyword analysis for MCP tool preloading
 * - Tool filtering for subagent specialization
 * - Custom task types fall back to a known type's tools based on capability
 */

import type { WorkerCapability } from '../swarm/types.js';

// =============================================================================
// TYPES
// =============================================================================

export interface ToolRecommendation {
  toolName: string;
  relevanceScore: number; // 0-1
  reason: string;
  source: 'builtin' | 'mcp';
}

export interface ToolRecommendationConfig {
  /** Maximum tools to recommend per agent (default: 15) */
  maxToolsPerAgent?: number;
  /** Enable MCP tool preloading for known patterns (default: true) */
  enablePreloading?: boolean;
  /** Task-type to tool mapping overrides */
  taskToolOverrides?: Record<string, string[]>;
}

export interface ToolCategory {
  name: string;
  tools: string[];
  relevance: number; // 0-1 base relevance for this category
}

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * Static mapping from subtask types to tool categories.
 * Core heuristic: task type determines which tools are most useful.
 */
const TASK_TYPE_TOOL_MAP: Record<string, ToolCategory[]> = {
  research: [
    {
      name: 'file_reading',
      tools: [
        'read_file',
        'glob',
        'grep',
        'list_files',
        'search_files',
        'search_code',
        'get_file_info',
      ],
      relevance: 1.0,
    },
    { name: 'web', tools: ['web_search'], relevance: 0.8 },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 0.6 },
    { name: 'bash_readonly', tools: ['bash'], relevance: 0.5 },
    { name: 'task_coordination', tools: ['task_get', 'task_list'], relevance: 0.3 },
  ],
  analysis: [
    {
      name: 'file_reading',
      tools: ['read_file', 'glob', 'grep', 'list_files', 'search_files', 'search_code'],
      relevance: 1.0,
    },
    { name: 'bash_readonly', tools: ['bash'], relevance: 0.6 },
    { name: 'web', tools: ['web_search'], relevance: 0.5 },
  ],
  design: [
    { name: 'file_reading', tools: ['read_file', 'glob', 'grep', 'list_files'], relevance: 0.9 },
    { name: 'file_writing', tools: ['write_file'], relevance: 0.4 },
  ],
  implement: [
    { name: 'file_reading', tools: ['read_file', 'glob', 'grep', 'list_files'], relevance: 0.8 },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 1.0 },
    { name: 'execution', tools: ['bash'], relevance: 0.7 },
    {
      name: 'task_coordination',
      tools: ['task_create', 'task_update', 'task_get', 'task_list'],
      relevance: 0.3,
    },
  ],
  test: [
    { name: 'execution', tools: ['bash'], relevance: 1.0 },
    { name: 'file_reading', tools: ['read_file', 'glob', 'grep'], relevance: 0.7 },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 0.5 },
  ],
  refactor: [
    {
      name: 'file_reading',
      tools: ['read_file', 'glob', 'grep', 'list_files', 'search_code'],
      relevance: 0.9,
    },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 1.0 },
    { name: 'execution', tools: ['bash'], relevance: 0.5 },
  ],
  review: [
    {
      name: 'file_reading',
      tools: ['read_file', 'glob', 'grep', 'list_files', 'search_files'],
      relevance: 1.0,
    },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 0.4 },
    { name: 'bash_readonly', tools: ['bash'], relevance: 0.3 },
  ],
  document: [
    { name: 'file_reading', tools: ['read_file', 'glob', 'grep'], relevance: 0.8 },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 1.0 },
  ],
  integrate: [
    { name: 'file_reading', tools: ['read_file', 'glob', 'grep'], relevance: 0.8 },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 0.9 },
    { name: 'execution', tools: ['bash'], relevance: 0.8 },
  ],
  deploy: [
    { name: 'execution', tools: ['bash'], relevance: 1.0 },
    { name: 'file_reading', tools: ['read_file', 'glob'], relevance: 0.5 },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 0.4 },
  ],
  merge: [
    { name: 'file_reading', tools: ['read_file', 'glob', 'grep'], relevance: 0.9 },
    { name: 'file_writing', tools: ['write_file', 'edit_file'], relevance: 1.0 },
    { name: 'execution', tools: ['bash'], relevance: 0.5 },
    { name: 'task_coordination', tools: ['task_get', 'task_list'], relevance: 0.3 },
  ],
};

/**
 * Map a WorkerCapability to the closest built-in task type for tool recommendations.
 * Used as a fallback when a custom task type isn't in TASK_TYPE_TOOL_MAP.
 */
const CAPABILITY_TO_TOOL_MAP_KEY: Record<WorkerCapability, string> = {
  code: 'implement',
  research: 'research',
  review: 'review',
  test: 'test',
  document: 'document',
  write: 'merge',
};

/**
 * Keyword patterns that suggest specific MCP tools.
 */
const MCP_KEYWORD_PATTERNS: Array<{
  keywords: string[];
  mcpPrefix: string;
  description: string;
}> = [
  {
    keywords: ['browser', 'screenshot', 'click', 'navigate', 'page', 'web page', 'UI test'],
    mcpPrefix: 'mcp_playwright',
    description: 'Playwright browser automation',
  },
  {
    keywords: ['database', 'sql', 'query', 'table', 'schema'],
    mcpPrefix: 'mcp_sqlite',
    description: 'SQLite database operations',
  },
  {
    keywords: ['documentation', 'library docs', 'api docs', 'npm package'],
    mcpPrefix: 'mcp_context7',
    description: 'Context7 documentation lookup',
  },
  {
    keywords: ['web search', 'google', 'search online', 'look up'],
    mcpPrefix: 'mcp_serper',
    description: 'Web search via Serper',
  },
  {
    keywords: ['github', 'pull request', 'issue', 'repository'],
    mcpPrefix: 'mcp_github',
    description: 'GitHub API operations',
  },
];

// =============================================================================
// ENGINE
// =============================================================================

export class ToolRecommendationEngine {
  private config: Required<ToolRecommendationConfig>;

  constructor(config?: ToolRecommendationConfig) {
    this.config = {
      maxToolsPerAgent: config?.maxToolsPerAgent ?? 15,
      enablePreloading: config?.enablePreloading ?? true,
      taskToolOverrides: config?.taskToolOverrides ?? {},
    };
  }

  /**
   * Recommend tools for a task based on type and description.
   * Custom task types not in TASK_TYPE_TOOL_MAP fall back to a known type
   * based on the custom type's capability (via TaskTypeConfig).
   */
  recommendTools(
    taskDescription: string,
    taskType: string,
    availableToolNames: string[],
    capability?: WorkerCapability,
  ): ToolRecommendation[] {
    const recommendations: Map<string, ToolRecommendation> = new Map();
    const availableSet = new Set(availableToolNames);

    // Phase 1: Task-type based recommendations
    // For custom types not in the map, fall back to a known type via capability
    let categories: ToolCategory[];
    if (this.config.taskToolOverrides[taskType]) {
      categories = [
        { name: 'override', tools: this.config.taskToolOverrides[taskType], relevance: 1.0 },
      ];
    } else if (TASK_TYPE_TOOL_MAP[taskType]) {
      categories = TASK_TYPE_TOOL_MAP[taskType];
    } else {
      // Custom type fallback: use capability to find closest built-in tool map
      const fallbackType = capability
        ? (CAPABILITY_TO_TOOL_MAP_KEY[capability] ?? 'implement')
        : 'implement';
      categories = TASK_TYPE_TOOL_MAP[fallbackType] ?? [];
    }

    for (const category of categories) {
      for (const toolName of category.tools) {
        if (availableSet.has(toolName) && !recommendations.has(toolName)) {
          recommendations.set(toolName, {
            toolName,
            relevanceScore: category.relevance,
            reason: `${category.name} tool for ${taskType} tasks`,
            source: 'builtin',
          });
        }
      }
    }

    // Phase 2: Keyword-based MCP tool recommendations
    const taskLower = taskDescription.toLowerCase();
    for (const pattern of MCP_KEYWORD_PATTERNS) {
      const matchCount = pattern.keywords.filter((kw) => taskLower.includes(kw)).length;
      if (matchCount > 0) {
        // Find available MCP tools matching the prefix
        for (const toolName of availableToolNames) {
          if (toolName.startsWith(pattern.mcpPrefix) && !recommendations.has(toolName)) {
            const relevance = Math.min(0.5 + matchCount * 0.15, 1.0);
            recommendations.set(toolName, {
              toolName,
              relevanceScore: relevance,
              reason: `${pattern.description} (matched: ${matchCount} keywords)`,
              source: 'mcp',
            });
          }
        }
      }
    }

    // Phase 3: Always include spawn_agent for complex tasks
    if (availableSet.has('spawn_agent') && !recommendations.has('spawn_agent')) {
      recommendations.set('spawn_agent', {
        toolName: 'spawn_agent',
        relevanceScore: 0.3,
        reason: 'Available for delegation',
        source: 'builtin',
      });
    }

    // Sort by relevance and limit
    return [...recommendations.values()]
      .sort((a, b) => b.relevanceScore - a.relevanceScore)
      .slice(0, this.config.maxToolsPerAgent);
  }

  /**
   * Get MCP tool prefixes that should be preloaded for a task type.
   */
  getMCPPreloadPrefixes(taskDescription: string): string[] {
    if (!this.config.enablePreloading) return [];

    const taskLower = taskDescription.toLowerCase();
    const prefixes: string[] = [];

    for (const pattern of MCP_KEYWORD_PATTERNS) {
      const matches = pattern.keywords.filter((kw) => taskLower.includes(kw));
      if (matches.length > 0) {
        prefixes.push(pattern.mcpPrefix);
      }
    }

    return prefixes;
  }

  /**
   * Filter tools for an agent based on task type.
   * Returns tool names that should be available to the agent.
   */
  getToolFilterForTaskType(taskType: string, availableToolNames: string[]): string[] {
    const recommendations = this.recommendTools('', taskType, availableToolNames);
    return recommendations.map((r) => r.toolName);
  }

  /**
   * Infer a SubtaskType from an agent name.
   */
  static inferTaskType(agentName: string): string {
    const nameToType: Record<string, string> = {
      researcher: 'research',
      coder: 'implement',
      reviewer: 'review',
      architect: 'design',
      debugger: 'analysis',
      tester: 'test',
      documenter: 'document',
      synthesizer: 'merge',
      writer: 'document',
      merger: 'merge',
    };

    const lower = agentName.toLowerCase();
    if (nameToType[lower]) {
      return nameToType[lower];
    }

    // Dynamic swarm names like "swarm-coder-task-1" should resolve by role token.
    const tokens = lower.split(/[^a-z0-9]+/).filter(Boolean);
    for (const token of tokens) {
      if (nameToType[token]) {
        return nameToType[token];
      }
    }

    // For swarm workers, default to implementation rather than research so
    // write-capable profiles are selected unless explicitly constrained.
    if (lower.startsWith('swarm-')) {
      return 'implement';
    }

    return 'research';
  }
}

/**
 * Create a tool recommendation engine with optional config.
 */
export function createToolRecommendationEngine(
  config?: ToolRecommendationConfig,
): ToolRecommendationEngine {
  return new ToolRecommendationEngine(config);
}
