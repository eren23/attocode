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
import { evaluateBashPolicy, isWriteLikeBashCommand } from './integrations/safety/bash-policy.js';

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

  /** Whether write operations require approval before execution (plan mode feature) */
  requireWriteApproval: boolean;

  /** Whether to show plan-specific prompts and UI elements */
  showPlanPrompt: boolean;
}

/**
 * Mode event types.
 */
export type ModeEvent =
  | { type: 'mode.changed'; from: AgentMode; to: AgentMode }
  | { type: 'mode.tool.filtered'; tool: string; mode: AgentMode }
  | { type: 'mode.write.intercepted'; tool: string; reason: string };

export type ModeEventListener = (event: ModeEvent) => void;

/**
 * Tools that modify the filesystem or execute side effects.
 * In plan mode with write approval, these are queued instead of executed.
 *
 * Note: spawn_agent is NOT in this list because:
 * 1. Spawning itself is a read-only operation (just creates a subagent)
 * 2. Subagents inherit the parent's mode, so they queue their own writes
 * 3. This allows research/exploration subagents to run immediately
 * 4. Only the subagent's write operations get queued (if parent is in plan mode)
 */
export const WRITE_TOOLS = [
  'write_file',
  'edit_file',
  'delete_file',
  'bash',           // Can have side effects
  'run_tests',      // Can have side effects
  'execute_code',   // Can have side effects
];

/**
 * MCP tool name patterns that indicate write operations.
 * Pattern: mcp_{server}_{action}_{target}
 *
 * These patterns catch MCP tools that modify external state:
 * - mcp_github_create_or_update_file
 * - mcp_filesystem_write
 * - mcp_notion_create_page
 * etc.
 */
const MCP_WRITE_PATTERNS = [
  // Action verbs in the middle of the name
  /^mcp_.*_(create|write|update|delete|edit|remove|push|commit|put|post|patch)_/i,
  // Action verbs at the end
  /^mcp_.*_(create|write|update|delete|edit|remove)$/i,
  // Specific patterns for common MCP servers
  /^mcp_.*_create_or_update/i,
  /^mcp_.*_add_/i,
  /^mcp_.*_set_/i,
  /^mcp_.*_insert/i,
  /^mcp_.*_modify/i,
];

/**
 * Check if a tool is a write operation.
 * Checks both static list and MCP write patterns.
 */
export function isWriteTool(toolName: string): boolean {
  // Check static list first (most common case)
  if (WRITE_TOOLS.includes(toolName)) {
    return true;
  }

  // Check MCP write patterns for mcp_ prefixed tools
  if (toolName.startsWith('mcp_')) {
    return MCP_WRITE_PATTERNS.some(pattern => pattern.test(toolName));
  }

  return false;
}

/**
 * Analyze bash command to determine if it's a write operation.
 * Returns true for commands that modify state.
 */
export function isBashWriteCommand(command: string): boolean {
  return isWriteLikeBashCommand(command);
}

/**
 * Commands known to be safe (read-only, no side effects) in plan mode.
 * Uses allowlist approach: only commands matching these patterns pass through.
 * Everything else is intercepted for approval.
 */
const SAFE_BASH_PATTERNS = [
  /^\s*ls\b/,
  /^\s*cat\b/,
  /^\s*head\b/,
  /^\s*tail\b/,
  /^\s*wc\b/,
  /^\s*find\b/,
  /^\s*grep\b/,
  /^\s*rg\b/,
  /^\s*fd\b/,
  /^\s*tree\b/,
  /^\s*pwd\b/,
  /^\s*which\b/,
  /^\s*whoami\b/,
  /^\s*env\b/,
  /^\s*echo\b/,
  /^\s*git\s+(status|log|diff|show|branch|remote|rev-parse|describe|tag)\b/,
  /^\s*node\s+(--version|-v)\b/,
  /^\s*npm\s+(list|ls|view|info|show|outdated|audit)\b/,
  /^\s*python\s+(--version|-V)\b/,
  /^\s*du\b/,
  /^\s*df\b/,
  /^\s*file\b/,
  /^\s*stat\b/,
  /^\s*uname\b/,
  /^\s*date\b/,
  /^\s*uptime\b/,
  /^\s*type\b/,
  /^\s*less\b/,
  /^\s*more\b/,
  /^\s*diff\b/,
  /^\s*jq\b/,
  /^\s*sort\b/,
  /^\s*uniq\b/,
  /^\s*cut\b/,
  /^\s*tr\b/,
];

/**
 * Dangerous patterns that override safe command matching.
 * Even if the base command is "safe", these suffixes indicate side effects.
 */
const DANGEROUS_SUFFIXES = [
  /\|\s*(rm|sudo|tee|dd|mkfs)\b/,    // Pipe to destructive tool
  />\s*\S/,                            // Output redirect
  />>\s*\S/,                           // Append redirect
  /-exec\b/,                           // find -exec
  /-delete\b/,                         // find -delete
  /\bsed\b.*-i/,                       // In-place sed edit
  /\bawk\b.*-i\s*inplace/,             // In-place awk edit
  /\bxargs\s.*\b(rm|mv|cp)\b/,         // xargs with destructive commands
];

/**
 * Check if a bash command is safe (read-only) for plan mode.
 * Uses allowlist approach: only known-safe commands pass through.
 * Returns true if the command is safe, false if it should be intercepted.
 */
export function isBashSafeCommand(command: string): boolean {
  const decision = evaluateBashPolicy(command, 'read_only', 'block_file_mutation');
  return decision.allowed;
}

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
    requireWriteApproval: false,
    showPlanPrompt: false,
  },

  plan: {
    name: 'Plan',
    description: 'Exploration mode - writes queued for approval',
    availableTools: [ALL_TOOLS], // All tools available, but writes are intercepted
    systemPromptAddition: `
You are in PLAN mode.
- You can read files, explore the codebase, and use all tools
- IMPORTANT: Write operations (file edits, bash commands with side effects) will be QUEUED for user approval
- The queued changes will be shown to the user as a "pending plan"

**CRITICAL PLAN MODE RULES - READ CAREFULLY:**

1. WRITES ARE QUEUED, NOT EXECUTED
   - When you call write_file, edit_file, or bash with write operations, the change is QUEUED
   - The file/change does NOT exist yet after queueing
   - The change will only be applied when the user runs /approve

2. ONCE QUEUED, THE TASK IS DONE
   - When you see "[PLAN MODE] Change queued for approval", the task for that file is COMPLETE
   - Do NOT try to create/modify the same file again
   - Do NOT spawn another subagent to "verify" or "retry" the same task
   - Move on to the next task or report completion

3. SUBAGENT BEHAVIOR IN PLAN MODE
   - When you spawn a subagent, it inherits plan mode
   - The subagent's writes are queued and merged into YOUR pending plan
   - When a subagent completes, its output will list what was queued
   - Do NOT spawn multiple subagents for the same file/task
   - If a subagent says it queued changes, those changes are in your plan - task is done

4. VERIFYING QUEUED CHANGES
   - You CANNOT verify if a queued file exists (it doesn't yet)
   - Use /show-plan to see all queued changes
   - Trust the confirmation message - if it says "queued", it's queued

**CRITICAL FOR RESEARCH TASKS:**
- If the user asks for analysis, research, or exploration, provide your findings VERBALLY
- Do NOT create documentation files, reports, or markdown files unless EXPLICITLY requested
- Your analysis should be returned as text output in the conversation, not written to files
- Only propose file writes when the user explicitly asks to create or modify files

BEFORE proposing changes, you MUST ask clarifying questions if:
- The scope of the task is unclear or ambiguous
- There are multiple valid approaches and you need user preference
- Requirements or constraints are not fully specified
- You need to understand priorities (speed vs quality, minimal vs comprehensive)

Focus on understanding the codebase and proposing specific changes.
Your proposed changes should include clear explanations of WHY each change is needed.
After you finish exploring, the user can approve, modify, or reject the pending plan.
`,
    color: '\x1b[34m', // Blue
    icon: '📋',
    requireWriteApproval: true,
    showPlanPrompt: true,
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
    requireWriteApproval: false,
    showPlanPrompt: false,
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
    requireWriteApproval: false,
    showPlanPrompt: false,
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

  /**
   * Check if the current mode requires write approval.
   */
  requiresWriteApproval(): boolean {
    return MODES[this.currentMode].requireWriteApproval;
  }

  /**
   * Check if the current mode should show plan prompts.
   */
  shouldShowPlanPrompt(): boolean {
    return MODES[this.currentMode].showPlanPrompt;
  }

  /**
   * Check if a tool call should be intercepted (queued) in current mode.
   * Returns true if the tool is a write operation and mode requires approval.
   *
   * @param toolName - The name of the tool
   * @param args - The tool arguments (needed to check bash commands)
   */
  shouldInterceptTool(toolName: string, args?: Record<string, unknown>): boolean {
    if (!this.requiresWriteApproval()) {
      return false;
    }

    // Check if it's a known write tool
    if (isWriteTool(toolName)) {
      // Special case: bash uses allowlist — only safe commands pass through
      if (toolName === 'bash' && args?.command) {
        return !isBashSafeCommand(String(args.command));
      }
      return true;
    }

    return false;
  }

  /**
   * Toggle between build and plan modes.
   * Useful for shift-tab or /plan command.
   */
  togglePlanMode(): AgentMode {
    if (this.currentMode === 'plan') {
      this.setMode('build');
      return 'build';
    } else {
      this.setMode('plan');
      return 'plan';
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
 * Subagent-specific plan mode prompt addition.
 *
 * This is a SHORTER version of the plan mode prompt specifically for subagents.
 * It removes parent-only sections (like "SUBAGENT BEHAVIOR" which tells the parent
 * how to manage subagents - irrelevant when you ARE the subagent).
 *
 * Key differences from parent plan mode prompt:
 * - No "SUBAGENT BEHAVIOR" section (subagents don't spawn more subagents)
 * - Focused on immediate task completion
 * - Clearer about what happens to queued writes
 */
export const SUBAGENT_PLAN_MODE_ADDITION = `
You are a SUBAGENT operating in PLAN MODE.

**YOUR TASK:**
- Complete the specific task you were given
- Your writes are queued to the PARENT's pending plan
- Once you queue a change, your task for that file is DONE

**RULES:**
1. When you see "Change queued for approval", the change is in the parent's plan - DO NOT retry
2. You CANNOT verify queued files (they don't exist yet)
3. Focus on your assigned task only - don't explore beyond scope
4. Report your findings clearly so the parent knows what you did

**READ THE BLACKBOARD:**
If context was provided from the parent or sibling agents, use it to avoid duplicate work.
`;

/**
 * Calculate task similarity using Jaccard index.
 * Returns a value between 0 and 1, where 1 means identical.
 */
export function calculateTaskSimilarity(taskA: string, taskB: string): number {
  // Normalize both tasks
  const normalize = (s: string): Set<string> => {
    const words = s
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')  // Remove punctuation
      .split(/\s+/)
      .filter(w => w.length > 2);     // Filter short words
    return new Set(words);
  };

  const wordsA = normalize(taskA);
  const wordsB = normalize(taskB);

  if (wordsA.size === 0 && wordsB.size === 0) return 1;
  if (wordsA.size === 0 || wordsB.size === 0) return 0;

  // Calculate Jaccard index: |intersection| / |union|
  const intersection = new Set([...wordsA].filter(x => wordsB.has(x)));
  const union = new Set([...wordsA, ...wordsB]);

  return intersection.size / union.size;
}

/**
 * Check if two tasks are semantically similar.
 * Uses Jaccard similarity with a default threshold of 0.75 (75%).
 */
export function areTasksSimilar(
  taskA: string,
  taskB: string,
  threshold: number = 0.75
): boolean {
  return calculateTaskSimilarity(taskA, taskB) >= threshold;
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
