/**
 * TUI Command Registry
 *
 * Maps REPL commands to TUI actions with metadata for command palette.
 */

import type { CommandPaletteItem } from './types.js';

// =============================================================================
// COMMAND TYPES
// =============================================================================

export interface CommandDefinition {
  name: string;
  aliases: string[];
  description: string;
  category: CommandCategory;
  usage?: string;
  args?: CommandArgument[];
  shortcut?: string;
  action: CommandAction;
}

export interface CommandArgument {
  name: string;
  required: boolean;
  description: string;
  type: 'string' | 'number' | 'boolean';
  default?: unknown;
}

export type CommandCategory =
  | 'General'
  | 'Sessions'
  | 'Context'
  | 'MCP'
  | 'Advanced'
  | 'Subagents'
  | 'Budget'
  | 'Testing';

export type CommandAction = (ctx: CommandContext, args: string[]) => Promise<CommandResult> | CommandResult;

export interface CommandContext {
  agent: unknown;  // ProductionAgent - typed as unknown to avoid circular deps
  sessionStore: unknown;
  mcpClient: unknown;
  display: {
    log: (message: string) => void;
    error: (message: string) => void;
    success: (message: string) => void;
    info: (message: string) => void;
  };
  requestDialog: (type: string, config: unknown) => Promise<unknown>;
}

export interface CommandResult {
  success: boolean;
  message?: string;
  action?: 'quit' | 'clear' | 'refresh' | 'dialog';
  dialogConfig?: unknown;
}

// =============================================================================
// COMMAND DEFINITIONS
// =============================================================================

export const commands: CommandDefinition[] = [
  // General
  {
    name: 'help',
    aliases: ['h', '?'],
    description: 'Show help and available commands',
    category: 'General',
    shortcut: '?',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'help' } }),
  },
  {
    name: 'status',
    aliases: ['stats'],
    description: 'Show session stats and metrics',
    category: 'General',
    shortcut: 'Ctrl+S',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'status' } }),
  },
  {
    name: 'clear',
    aliases: ['cls'],
    description: 'Clear the screen',
    category: 'General',
    shortcut: 'Ctrl+L',
    action: () => ({ success: true, action: 'clear' }),
  },
  {
    name: 'reset',
    aliases: [],
    description: 'Reset agent state',
    category: 'General',
    action: async (ctx) => {
      // Implementation would call agent.reset()
      return { success: true, message: 'Agent state reset' };
    },
  },
  {
    name: 'quit',
    aliases: ['exit', 'q'],
    description: 'Exit the application',
    category: 'General',
    shortcut: 'Ctrl+C',
    action: () => ({ success: true, action: 'quit' }),
  },

  // Sessions & Context
  {
    name: 'save',
    aliases: [],
    description: 'Save current session',
    category: 'Sessions',
    action: async (ctx) => {
      return { success: true, message: 'Session saved' };
    },
  },
  {
    name: 'load',
    aliases: [],
    description: 'Load a previous session',
    category: 'Sessions',
    usage: '/load <session-id>',
    args: [{ name: 'id', required: true, description: 'Session ID to load', type: 'string' }],
    action: async (ctx, args) => {
      if (!args[0]) {
        return { success: false, message: 'Session ID required' };
      }
      return { success: true, action: 'dialog', dialogConfig: { type: 'session', sessionId: args[0] } };
    },
  },
  {
    name: 'sessions',
    aliases: [],
    description: 'List all saved sessions',
    category: 'Sessions',
    shortcut: 'Ctrl+O',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'sessions' } }),
  },
  {
    name: 'context',
    aliases: ['ctx'],
    description: 'Show context window usage',
    category: 'Context',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'context' } }),
  },
  {
    name: 'compact',
    aliases: [],
    description: 'Summarize and compress context',
    category: 'Context',
    action: async (ctx) => {
      return { success: true, message: 'Context compacted' };
    },
  },

  // MCP Integration
  {
    name: 'mcp',
    aliases: [],
    description: 'List MCP servers',
    category: 'MCP',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'mcp' } }),
  },
  {
    name: 'mcp connect',
    aliases: [],
    description: 'Connect to an MCP server',
    category: 'MCP',
    usage: '/mcp connect <server-name>',
    args: [{ name: 'name', required: true, description: 'Server name', type: 'string' }],
    action: async (ctx, args) => {
      if (!args[0]) {
        return { success: false, message: 'Server name required' };
      }
      return { success: true, message: `Connected to ${args[0]}` };
    },
  },
  {
    name: 'mcp tools',
    aliases: [],
    description: 'List available MCP tools',
    category: 'MCP',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'mcp-tools' } }),
  },
  {
    name: 'mcp search',
    aliases: [],
    description: 'Search and load MCP tools',
    category: 'MCP',
    usage: '/mcp search <query>',
    args: [{ name: 'query', required: true, description: 'Search query', type: 'string' }],
    action: async (ctx, args) => {
      const query = args.join(' ');
      if (!query) {
        return { success: false, message: 'Search query required' };
      }
      return { success: true, action: 'dialog', dialogConfig: { type: 'mcp-search', query } };
    },
  },

  // Advanced Features
  {
    name: 'react',
    aliases: [],
    description: 'Run task with ReAct reasoning pattern',
    category: 'Advanced',
    usage: '/react <task>',
    args: [{ name: 'task', required: true, description: 'Task to execute', type: 'string' }],
    action: async (ctx, args) => {
      const task = args.join(' ');
      if (!task) {
        return { success: false, message: 'Task required' };
      }
      // Would call agent.runWithReAct(task)
      return { success: true, message: `Running ReAct: ${task}` };
    },
  },
  {
    name: 'team',
    aliases: [],
    description: 'Run task with multi-agent team',
    category: 'Advanced',
    usage: '/team <task>',
    args: [{ name: 'task', required: true, description: 'Task to execute', type: 'string' }],
    action: async (ctx, args) => {
      const task = args.join(' ');
      if (!task) {
        return { success: false, message: 'Task required' };
      }
      return { success: true, message: `Running with team: ${task}` };
    },
  },
  {
    name: 'checkpoint',
    aliases: ['cp'],
    description: 'Create a conversation checkpoint',
    category: 'Advanced',
    usage: '/checkpoint [label]',
    action: async (ctx, args) => {
      const label = args.join(' ') || undefined;
      return { success: true, message: `Checkpoint created${label ? `: ${label}` : ''}` };
    },
  },
  {
    name: 'checkpoints',
    aliases: ['cps'],
    description: 'List all checkpoints',
    category: 'Advanced',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'checkpoints' } }),
  },
  {
    name: 'restore',
    aliases: [],
    description: 'Restore a checkpoint',
    category: 'Advanced',
    usage: '/restore <checkpoint-id>',
    args: [{ name: 'id', required: true, description: 'Checkpoint ID', type: 'string' }],
    action: async (ctx, args) => {
      if (!args[0]) {
        return { success: false, message: 'Checkpoint ID required' };
      }
      return { success: true, message: `Restored checkpoint: ${args[0]}` };
    },
  },
  {
    name: 'rollback',
    aliases: ['rb'],
    description: 'Rollback conversation steps',
    category: 'Advanced',
    usage: '/rollback [steps]',
    args: [{ name: 'steps', required: false, description: 'Number of steps (default: 1)', type: 'number', default: 1 }],
    action: async (ctx, args) => {
      const steps = parseInt(args[0], 10) || 1;
      return { success: true, message: `Rolled back ${steps} step(s)` };
    },
  },
  {
    name: 'fork',
    aliases: [],
    description: 'Fork the current conversation',
    category: 'Advanced',
    usage: '/fork <name>',
    args: [{ name: 'name', required: true, description: 'Fork name', type: 'string' }],
    action: async (ctx, args) => {
      const name = args.join(' ');
      if (!name) {
        return { success: false, message: 'Fork name required' };
      }
      return { success: true, message: `Forked conversation: ${name}` };
    },
  },
  {
    name: 'threads',
    aliases: [],
    description: 'List conversation threads',
    category: 'Advanced',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'threads' } }),
  },
  {
    name: 'switch',
    aliases: [],
    description: 'Switch to another thread',
    category: 'Advanced',
    usage: '/switch <thread-id>',
    args: [{ name: 'id', required: true, description: 'Thread ID', type: 'string' }],
    action: async (ctx, args) => {
      if (!args[0]) {
        return { success: false, message: 'Thread ID required' };
      }
      return { success: true, message: `Switched to thread: ${args[0]}` };
    },
  },
  {
    name: 'grants',
    aliases: [],
    description: 'Show active permission grants',
    category: 'Advanced',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'grants' } }),
  },
  {
    name: 'audit',
    aliases: [],
    description: 'Show audit log',
    category: 'Advanced',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'audit' } }),
  },

  // Subagents
  {
    name: 'agents',
    aliases: [],
    description: 'List available agents',
    category: 'Subagents',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'agents' } }),
  },
  {
    name: 'spawn',
    aliases: [],
    description: 'Spawn an agent to execute a task',
    category: 'Subagents',
    usage: '/spawn <agent> <task>',
    args: [
      { name: 'agent', required: true, description: 'Agent name', type: 'string' },
      { name: 'task', required: true, description: 'Task to execute', type: 'string' },
    ],
    action: async (ctx, args) => {
      if (args.length < 2) {
        return { success: false, message: 'Usage: /spawn <agent> <task>' };
      }
      const [agent, ...taskParts] = args;
      const task = taskParts.join(' ');
      return { success: true, message: `Spawning ${agent}: ${task}` };
    },
  },
  {
    name: 'find',
    aliases: [],
    description: 'Find agents by keyword',
    category: 'Subagents',
    usage: '/find <query>',
    args: [{ name: 'query', required: true, description: 'Search query', type: 'string' }],
    action: async (ctx, args) => {
      const query = args.join(' ');
      if (!query) {
        return { success: false, message: 'Search query required' };
      }
      return { success: true, action: 'dialog', dialogConfig: { type: 'agent-search', query } };
    },
  },
  {
    name: 'suggest',
    aliases: [],
    description: 'AI-powered agent suggestion for a task',
    category: 'Subagents',
    usage: '/suggest <task>',
    args: [{ name: 'task', required: true, description: 'Task description', type: 'string' }],
    action: async (ctx, args) => {
      const task = args.join(' ');
      if (!task) {
        return { success: false, message: 'Task description required' };
      }
      return { success: true, message: `Suggesting agents for: ${task}` };
    },
  },
  {
    name: 'auto',
    aliases: [],
    description: 'Run task with automatic agent routing',
    category: 'Subagents',
    usage: '/auto <task>',
    args: [{ name: 'task', required: true, description: 'Task to execute', type: 'string' }],
    action: async (ctx, args) => {
      const task = args.join(' ');
      if (!task) {
        return { success: false, message: 'Task required' };
      }
      return { success: true, message: `Auto-routing: ${task}` };
    },
  },

  // Budget & Economics
  {
    name: 'budget',
    aliases: [],
    description: 'Show token/cost budget usage',
    category: 'Budget',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'budget' } }),
  },
  {
    name: 'extend',
    aliases: [],
    description: 'Extend budget limits',
    category: 'Budget',
    usage: '/extend <type> <amount>',
    args: [
      { name: 'type', required: true, description: 'Budget type (tokens/cost/time)', type: 'string' },
      { name: 'amount', required: true, description: 'Amount to extend', type: 'number' },
    ],
    action: async (ctx, args) => {
      if (args.length < 2) {
        return { success: false, message: 'Usage: /extend <type> <amount>' };
      }
      return { success: true, message: `Extended ${args[0]} budget by ${args[1]}` };
    },
  },

  // Testing Features
  {
    name: 'skills',
    aliases: [],
    description: 'List loaded skills',
    category: 'Testing',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'skills' } }),
  },
  {
    name: 'sandbox',
    aliases: [],
    description: 'Show sandbox modes',
    category: 'Testing',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'sandbox' } }),
  },
  {
    name: 'shell',
    aliases: [],
    description: 'Show PTY shell info',
    category: 'Testing',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'shell' } }),
  },
  {
    name: 'lsp',
    aliases: [],
    description: 'Show LSP integration status',
    category: 'Testing',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'lsp' } }),
  },
  {
    name: 'tui',
    aliases: [],
    description: 'Show TUI features and status',
    category: 'Testing',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'tui-info' } }),
  },
  {
    name: 'model',
    aliases: [],
    description: 'Switch AI model',
    category: 'General',
    shortcut: 'Ctrl+M',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'model' } }),
  },
  {
    name: 'theme',
    aliases: [],
    description: 'Switch color theme',
    category: 'General',
    action: () => ({ success: true, action: 'dialog', dialogConfig: { type: 'theme' } }),
  },
];

// =============================================================================
// COMMAND REGISTRY
// =============================================================================

export class CommandRegistry {
  private commands: Map<string, CommandDefinition> = new Map();

  constructor(definitions: CommandDefinition[] = commands) {
    for (const cmd of definitions) {
      this.register(cmd);
    }
  }

  register(cmd: CommandDefinition): void {
    // Register primary name
    this.commands.set(cmd.name.toLowerCase(), cmd);

    // Register aliases
    for (const alias of cmd.aliases) {
      this.commands.set(alias.toLowerCase(), cmd);
    }
  }

  get(name: string): CommandDefinition | undefined {
    return this.commands.get(name.toLowerCase());
  }

  getAll(): CommandDefinition[] {
    // Return unique commands (no duplicates from aliases)
    const seen = new Set<string>();
    const result: CommandDefinition[] = [];

    for (const cmd of this.commands.values()) {
      if (!seen.has(cmd.name)) {
        seen.add(cmd.name);
        result.push(cmd);
      }
    }

    return result;
  }

  getByCategory(category: CommandCategory): CommandDefinition[] {
    return this.getAll().filter(cmd => cmd.category === category);
  }

  /**
   * Convert commands to CommandPaletteItem format for TUI.
   */
  toCommandPaletteItems(): CommandPaletteItem[] {
    return this.getAll().map(cmd => ({
      id: cmd.name,
      label: `/${cmd.name}`,
      description: cmd.description,
      shortcut: cmd.shortcut,
      category: cmd.category,
      action: () => {
        // Will be connected to actual command execution
        console.log(`Execute: /${cmd.name}`);
      },
    }));
  }

  /**
   * Parse and execute a command string.
   */
  async execute(input: string, ctx: CommandContext): Promise<CommandResult> {
    const trimmed = input.trim();

    if (!trimmed.startsWith('/')) {
      return { success: false, message: 'Commands must start with /' };
    }

    const parts = trimmed.slice(1).split(/\s+/);
    let cmdName = parts[0].toLowerCase();
    let args = parts.slice(1);

    // Handle compound commands like "mcp connect"
    if (parts.length >= 2) {
      const compound = `${parts[0]} ${parts[1]}`.toLowerCase();
      if (this.commands.has(compound)) {
        cmdName = compound;
        args = parts.slice(2);
      }
    }

    const cmd = this.get(cmdName);
    if (!cmd) {
      return { success: false, message: `Unknown command: /${cmdName}` };
    }

    try {
      return await cmd.action(ctx, args);
    } catch (error) {
      return { success: false, message: `Error: ${(error as Error).message}` };
    }
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const commandRegistry = new CommandRegistry();
export default CommandRegistry;
