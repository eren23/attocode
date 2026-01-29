/**
 * Agents Management Commands
 *
 * Handles all /agents sub-commands for managing agents:
 * - /agents - List all agents with enhanced formatting
 * - /agents new <name> - Create a new agent scaffold
 * - /agents info <name> - Show detailed agent information
 * - /agents edit <name> - Open agent file in $EDITOR
 */

import { exec } from 'child_process';
import { promisify } from 'util';
import type { CommandContext } from './types.js';
import {
  type AgentRegistry,
  type LoadedAgent,
  getAgentLocationDisplay,
  getAgentStats,
  createAgentScaffold,
} from '../integrations/index.js';

const execAsync = promisify(exec);

// =============================================================================
// ANSI COLOR UTILITIES
// =============================================================================

const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  white: '\x1b[37m',
};

function c(text: string, color: keyof typeof colors): string {
  return `${colors[color]}${text}${colors.reset}`;
}

// =============================================================================
// MODEL DISPLAY HELPERS
// =============================================================================

function formatModel(model: string | undefined): string {
  switch (model) {
    case 'fast':
      return c('haiku', 'cyan');
    case 'balanced':
      return c('sonnet', 'green');
    case 'quality':
      return c('opus', 'magenta');
    default:
      return c(model || 'default', 'dim');
  }
}

// =============================================================================
// ENHANCED AGENT LIST FORMATTER
// =============================================================================

/**
 * Format agents list with categorization and usage hints.
 */
export function formatEnhancedAgentList(agents: LoadedAgent[]): string {
  if (agents.length === 0) {
    return `${c('No agents loaded.', 'dim')}

${c('To add agents:', 'bold')}
  /agents new <name>      Create a new agent in .attocode/agents/

${c('Agent Locations:', 'dim')}
  ~/.attocode/agents/     User-level agents (shared across projects)
  .attocode/agents/       Project-level agents
`;
  }

  const lines: string[] = [];
  const stats = getAgentStats(agents);
  const customCount = stats.user + stats.project + stats.legacy;

  lines.push(`${c(`Agents (${agents.length} loaded: ${stats.builtin} built-in, ${customCount} custom)`, 'bold')}`);
  lines.push('');

  // Built-in agents
  const builtIn = agents.filter(a => a.source === 'builtin');
  if (builtIn.length > 0) {
    lines.push(`  ${c('BUILT-IN:', 'cyan')}`);
    lines.push(`  ${c('─'.repeat(60), 'dim')}`);

    for (const agent of builtIn) {
      const model = formatModel(agent.model);
      const desc = agent.description.split('.')[0].slice(0, 40);
      lines.push(`    ${c(agent.name.padEnd(14), 'cyan')} ${desc.padEnd(42)} ${model}`);
    }
    lines.push('');
  }

  // User-defined agents
  const userDefined = agents.filter(a => a.source === 'user' || a.source === 'project');
  if (userDefined.length > 0) {
    lines.push(`  ${c('USER-DEFINED:', 'yellow')}`);
    lines.push(`  ${c('─'.repeat(60), 'dim')}`);

    for (const agent of userDefined) {
      const model = formatModel(agent.model);
      const location = getAgentLocationDisplay(agent);
      const desc = agent.description.split('.')[0].slice(0, 35);
      lines.push(`    ${c(agent.name.padEnd(14), 'yellow')} ${desc.padEnd(37)} ${model}`);
      lines.push(`    ${c(' '.repeat(14), 'dim')} ${c(`Source: ${location}`, 'dim')}`);
    }
    lines.push('');
  }

  // Legacy agents
  const legacy = agents.filter(a => a.source === 'legacy');
  if (legacy.length > 0) {
    lines.push(`  ${c('LEGACY (.agents/):', 'dim')}`);
    lines.push(`  ${c('─'.repeat(60), 'dim')}`);

    for (const agent of legacy) {
      const model = formatModel(agent.model);
      const desc = agent.description.split('.')[0].slice(0, 40);
      lines.push(`    ${c(agent.name.padEnd(14), 'dim')} ${desc.padEnd(42)} ${model}`);
    }
    lines.push('');
  }

  // Commands
  lines.push(`  ${c('COMMANDS:', 'bold')}`);
  lines.push(`    ${c('/agents new <name>', 'cyan').padEnd(35)} Create new agent in .attocode/agents/`);
  lines.push(`    ${c('/agents info <name>', 'cyan').padEnd(35)} Show agent details`);
  lines.push(`    ${c('/agents edit <name>', 'cyan').padEnd(35)} Edit agent definition`);
  lines.push(`    ${c('/spawn <name> <task>', 'cyan').padEnd(35)} Spawn an agent with a task`);

  return lines.join('\n');
}

/**
 * Format detailed agent information.
 */
export function formatAgentInfo(agent: LoadedAgent): string {
  const lines: string[] = [];

  lines.push(`${c(`Agent: ${agent.name}`, 'bold')}`);
  lines.push(c('─'.repeat(60), 'dim'));

  lines.push(`  ${c('Description:', 'cyan').padEnd(20)} ${agent.description}`);
  lines.push(`  ${c('Source:', 'cyan').padEnd(20)} ${getAgentLocationDisplay(agent)}`);

  if (agent.filePath) {
    lines.push(`  ${c('File:', 'cyan').padEnd(20)} ${agent.filePath}`);
  }

  lines.push(`  ${c('Model:', 'cyan').padEnd(20)} ${formatModel(agent.model)}`);

  if (agent.maxIterations) {
    lines.push(`  ${c('Max Iterations:', 'cyan').padEnd(20)} ${agent.maxIterations}`);
  }

  if (agent.maxTokenBudget) {
    lines.push(`  ${c('Token Budget:', 'cyan').padEnd(20)} ${agent.maxTokenBudget.toLocaleString()}`);
  }

  if (agent.capabilities && agent.capabilities.length > 0) {
    lines.push('');
    lines.push(`  ${c('Capabilities:', 'bold')}`);
    lines.push(`    ${agent.capabilities.join(', ')}`);
  }

  if (agent.tools && agent.tools.length > 0) {
    lines.push('');
    lines.push(`  ${c('Tools Available:', 'bold')}`);
    lines.push(`    ${agent.tools.join(', ')}`);
  }

  if (agent.tags && agent.tags.length > 0) {
    lines.push('');
    lines.push(`  ${c('Tags:', 'bold')} ${agent.tags.join(', ')}`);
  }

  lines.push('');
  lines.push(`  ${c('Usage:', 'bold')}`);
  lines.push(`    /spawn ${agent.name} "<your task here>"`);

  return lines.join('\n');
}

// =============================================================================
// COMMAND HANDLERS
// =============================================================================

/**
 * Handle /agents command and sub-commands.
 */
export async function handleAgentsCommand(
  args: string[],
  ctx: CommandContext,
  agentRegistry: AgentRegistry
): Promise<void> {
  const { output } = ctx;

  if (args.length === 0) {
    // List all agents
    const agents = agentRegistry.getAllAgents();
    output.log(formatEnhancedAgentList(agents));
    return;
  }

  const subCmd = args[0].toLowerCase();

  switch (subCmd) {
    case 'new': {
      if (args.length < 2) {
        output.log(c('Usage: /agents new <name> [--model fast|balanced|quality] [--description "..."]', 'yellow'));
        return;
      }

      const name = args[1];

      // Parse optional flags
      let model: 'fast' | 'balanced' | 'quality' = 'balanced';
      let description: string | undefined;
      const capabilities: string[] = [];
      const tools: string[] = [];

      for (let i = 2; i < args.length; i++) {
        if (args[i] === '--model' && args[i + 1]) {
          const m = args[++i].toLowerCase();
          if (m === 'fast' || m === 'balanced' || m === 'quality') {
            model = m;
          }
        } else if (args[i] === '--description' && args[i + 1]) {
          description = args[++i];
        } else if (args[i] === '--capability' && args[i + 1]) {
          capabilities.push(args[++i]);
        } else if (args[i] === '--tool' && args[i + 1]) {
          tools.push(args[++i]);
        }
      }

      output.log(c(`Creating agent: ${name}...`, 'cyan'));

      const result = await createAgentScaffold(name, {
        model,
        description,
        capabilities: capabilities.length > 0 ? capabilities : undefined,
        tools: tools.length > 0 ? tools : undefined,
      });

      if (result.success) {
        output.log(c(`+ Created agent: ${result.path}`, 'green'));
        output.log('');
        output.log(c('Edit the file to customize:', 'dim'));
        output.log(c('  - Update the system prompt', 'dim'));
        output.log(c('  - Add capabilities for NL matching', 'dim'));
        output.log(c('  - Configure tools and iteration limits', 'dim'));
        output.log('');
        output.log(c(`Open in editor: /agents edit ${name}`, 'cyan'));

        // Reload agents
        await agentRegistry.loadUserAgents();
      } else {
        output.log(c(`x ${result.error}`, 'red'));
      }
      break;
    }

    case 'info': {
      if (args.length < 2) {
        output.log(c('Usage: /agents info <name>', 'yellow'));
        return;
      }

      const name = args[1];
      const agent = agentRegistry.getAgent(name);

      if (!agent) {
        output.log(c(`Agent not found: ${name}`, 'red'));
        output.log(c('Use /agents to see available agents.', 'dim'));
        return;
      }

      output.log(formatAgentInfo(agent));
      break;
    }

    case 'edit': {
      if (args.length < 2) {
        output.log(c('Usage: /agents edit <name>', 'yellow'));
        return;
      }

      const name = args[1];
      const agent = agentRegistry.getAgent(name);

      if (!agent) {
        output.log(c(`Agent not found: ${name}`, 'red'));
        return;
      }

      if (!agent.filePath) {
        output.log(c(`Cannot edit built-in agent: ${name}`, 'yellow'));
        output.log(c('Create a custom version with: /agents new ' + name + '-custom', 'dim'));
        return;
      }

      const editor = process.env.EDITOR || process.env.VISUAL || 'vim';
      output.log(c(`Opening ${agent.filePath} in ${editor}...`, 'cyan'));

      try {
        await execAsync(`${editor} "${agent.filePath}"`);
        output.log(c('+ Editor closed. Reloading agents...', 'green'));
        // Reload agents after edit
        await agentRegistry.loadUserAgents();
      } catch (error) {
        output.log(c(`Failed to open editor: ${(error as Error).message}`, 'red'));
        output.log(c(`File path: ${agent.filePath}`, 'dim'));
      }
      break;
    }

    case 'reload': {
      output.log(c('Reloading agents...', 'cyan'));
      await agentRegistry.loadUserAgents();
      const count = agentRegistry.getAllAgents().length;
      output.log(c(`+ Loaded ${count} agent(s)`, 'green'));
      break;
    }

    default:
      output.log(c(`Unknown sub-command: ${subCmd}`, 'yellow'));
      output.log(c('Usage:', 'bold'));
      output.log(c('  /agents              - List all agents', 'dim'));
      output.log(c('  /agents new <name>   - Create a new agent', 'dim'));
      output.log(c('  /agents info <name>  - Show agent details', 'dim'));
      output.log(c('  /agents edit <name>  - Open agent in $EDITOR', 'dim'));
      output.log(c('  /agents reload       - Reload all agents', 'dim'));
  }
}
