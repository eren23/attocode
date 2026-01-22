/**
 * Lesson 25: Agent Modes (OpenCode-inspired)
 *
 * Provides different operational modes for the agent:
 * - Build: Full access to modify files and run commands
 * - Plan: Read-only mode for exploration and planning
 * - Review: Read-only mode focused on code review
 *
 * Users can switch modes with Tab key or /mode command.
 *
 * Usage:
 *   agent.setMode('plan');
 *   const currentMode = agent.getMode();
 */

import type { ToolDefinition } from './types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Available agent modes.
 */
export type AgentMode = 'build' | 'plan' | 'review' | 'debug';

/**
 * Mode configuration.
 */
export interface ModeConfig {
  /** Display name */
  name: string;

  /** Short description */
  description: string;

  /** Available tool names in this mode */
  availableTools: string[];

  /** Additional system prompt for this mode */
  systemPromptAddition: string;

  /** Color for terminal display (ANSI code) */
  color: string;

  /** Icon for display */
  icon: string;
}

/**
 * Mode event types.
 */
export type ModeEvent =
  | { type: 'mode.changed'; from: AgentMode; to: AgentMode }
  | { type: 'mode.tool.filtered'; tool: string; mode: AgentMode };

export type ModeEventListener = (event: ModeEvent) => void;

// =============================================================================
// MODE DEFINITIONS
// =============================================================================

/**
 * Read-only tools available in restricted modes.
 */
export const READ_ONLY_TOOLS = [
  'read_file',
  'list_files',
  'list_directory',
  'search',
  'glob',
  'grep',
  'get_file_info',
  'git_status',
  'git_log',
  'git_diff',
  'lsp_definition',
  'lsp_references',
  'lsp_hover',
];

/**
 * All tools (for build mode).
 */
export const ALL_TOOLS = '*'; // Special marker for "all tools"

/**
 * Mode configurations.
 */
export const MODES: Record<AgentMode, ModeConfig> = {
  build: {
    name: 'Build',
    description: 'Full access to modify files and run commands',
    availableTools: [ALL_TOOLS],
    systemPromptAddition: `
You are in BUILD mode with full access to modify files and run commands.
- You can create, edit, and delete files
- You can run shell commands and scripts
- You can make changes to the codebase
- Proceed with caution and verify changes before committing
`,
    color: '\x1b[32m', // Green
    icon: '🔨',
  },

  plan: {
    name: 'Plan',
    description: 'Read-only mode for exploration and planning',
    availableTools: READ_ONLY_TOOLS,
    systemPromptAddition: `
You are in PLAN mode (read-only).
- You can read files and explore the codebase
- You CANNOT modify files or run destructive commands
- Focus on understanding, analysis, and planning
- Create detailed plans that can be executed in Build mode
- Use this time to gather context and propose solutions
`,
    color: '\x1b[34m', // Blue
    icon: '📋',
  },

  review: {
    name: 'Review',
    description: 'Read-only mode focused on code review',
    availableTools: READ_ONLY_TOOLS,
    systemPromptAddition: `
You are in REVIEW mode (read-only).
- You can read files and analyze code
- You CANNOT modify files
- Focus on code quality, bugs, security issues, and best practices
- Provide specific, actionable feedback
- Point out both issues and positive patterns
- Consider maintainability, readability, and performance
`,
    color: '\x1b[33m', // Yellow
    icon: '🔍',
  },

  debug: {
    name: 'Debug',
    description: 'Debugging mode with diagnostic tools',
    availableTools: [...READ_ONLY_TOOLS, 'run_tests', 'execute_code'],
    systemPromptAddition: `
You are in DEBUG mode.
- You can read files and run diagnostic commands
- You can execute tests and debug scripts
- Focus on finding and isolating bugs
- Use a systematic approach: reproduce, isolate, fix
- Consider adding logging or debugging statements
`,
    color: '\x1b[35m', // Magenta
    icon: '🐛',
  },
};

// =============================================================================
// MODE MANAGER
// =============================================================================

/**
 * Manages agent modes and tool filtering.
 */
export class ModeManager {
  private currentMode: AgentMode = 'build';
  private eventListeners: Set<ModeEventListener> = new Set();
  private allToolNames: Set<string> = new Set();

  constructor(tools: ToolDefinition[] = []) {
    // Track all available tool names
    for (const tool of tools) {
      this.allToolNames.add(tool.name);
    }
  }

  /**
   * Get the current mode.
   */
  getMode(): AgentMode {
    return this.currentMode;
  }

  /**
   * Get the current mode configuration.
   */
  getModeConfig(): ModeConfig {
    return MODES[this.currentMode];
  }

  /**
   * Set the agent mode.
   */
  setMode(mode: AgentMode): void {
    if (mode === this.currentMode) return;

    const from = this.currentMode;
    this.currentMode = mode;

    this.emit({ type: 'mode.changed', from, to: mode });
  }

  /**
   * Cycle to the next mode.
   */
  cycleMode(): AgentMode {
    const modes: AgentMode[] = ['build', 'plan', 'review', 'debug'];
    const currentIndex = modes.indexOf(this.currentMode);
    const nextIndex = (currentIndex + 1) % modes.length;
    const nextMode = modes[nextIndex];

    this.setMode(nextMode);
    return nextMode;
  }

  /**
   * Check if a tool is available in the current mode.
   */
  isToolAvailable(toolName: string): boolean {
    const config = MODES[this.currentMode];

    // Build mode has all tools
    if (config.availableTools.includes(ALL_TOOLS)) {
      return true;
    }

    return config.availableTools.includes(toolName);
  }

  /**
   * Filter tools based on current mode.
   */
  filterTools(tools: ToolDefinition[]): ToolDefinition[] {
    const config = MODES[this.currentMode];

    // Build mode has all tools
    if (config.availableTools.includes(ALL_TOOLS)) {
      return tools;
    }

    return tools.filter((tool) => {
      const available = config.availableTools.includes(tool.name);
      if (!available) {
        this.emit({ type: 'mode.tool.filtered', tool: tool.name, mode: this.currentMode });
      }
      return available;
    });
  }

  /**
   * Get the system prompt addition for the current mode.
   */
  getSystemPromptAddition(): string {
    return MODES[this.currentMode].systemPromptAddition;
  }

  /**
   * Get all available modes.
   */
  getAllModes(): AgentMode[] {
    return Object.keys(MODES) as AgentMode[];
  }

  /**
   * Get mode info for display.
   */
  getModeInfo(mode?: AgentMode): { name: string; icon: string; color: string } {
    const m = mode ?? this.currentMode;
    const config = MODES[m];
    return {
      name: config.name,
      icon: config.icon,
      color: config.color,
    };
  }

  /**
   * Format mode for terminal display.
   */
  formatModePrompt(): string {
    const config = MODES[this.currentMode];
    return `${config.color}${config.icon} ${config.name}\x1b[0m`;
  }

  /**
   * Subscribe to mode events.
   */
  subscribe(listener: ModeEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Update available tools.
   */
  updateTools(tools: ToolDefinition[]): void {
    this.allToolNames.clear();
    for (const tool of tools) {
      this.allToolNames.add(tool.name);
    }
  }

  // Internal methods

  private emit(event: ModeEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a mode manager.
 */
export function createModeManager(tools?: ToolDefinition[]): ModeManager {
  return new ModeManager(tools);
}

/**
 * Format all modes for display.
 */
export function formatModeList(): string {
  const lines: string[] = ['Available modes:'];

  for (const [key, config] of Object.entries(MODES)) {
    lines.push(`  ${config.icon} ${key.padEnd(8)} - ${config.description}`);
  }

  return lines.join('\n');
}

/**
 * Parse mode from string (case-insensitive).
 */
export function parseMode(input: string): AgentMode | null {
  const normalized = input.toLowerCase().trim();

  if (normalized in MODES) {
    return normalized as AgentMode;
  }

  // Handle aliases
  const aliases: Record<string, AgentMode> = {
    'read': 'plan',
    'readonly': 'plan',
    'read-only': 'plan',
    'explore': 'plan',
    'code-review': 'review',
    'codereview': 'review',
    'cr': 'review',
    'dev': 'build',
    'development': 'build',
    'write': 'build',
    'bug': 'debug',
    'fix': 'debug',
  };

  return aliases[normalized] || null;
}
