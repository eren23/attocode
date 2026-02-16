/**
 * CLI Argument Parsing and Help
 *
 * Handles command-line argument parsing and help text display.
 */

import type { PermissionMode } from './tools/types.js';
import { logger } from './integrations/logger.js';

// ANSI color codes for terminal output
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

export const VERSION = '1.0.0';

/**
 * CLI arguments structure.
 */
export interface CLIArgs {
  help: boolean;
  model?: string;
  permission: PermissionMode;
  task?: string;
  maxIterations: number;
  trace: boolean;
  tui: boolean | 'auto';
  theme?: 'dark' | 'light' | 'auto';
  version: boolean;
  debug: boolean;
  init: boolean;
  /** Swarm mode: true for defaults, string for config file path */
  swarm?: boolean | string;
  /** Resume a swarm session by ID */
  swarmResume?: string;
  /** Use only paid models in swarm mode (no free tier) */
  paidOnly?: boolean;
}

/**
 * Parse command-line arguments.
 */
export function parseArgs(): CLIArgs {
  const args = process.argv.slice(2);
  const result: CLIArgs = {
    help: false,
    permission: 'interactive',
    maxIterations: 50,
    trace: false,
    tui: 'auto',
    version: false,
    debug: false,
    init: false,
  };

  // Check for init command first
  if (args[0] === 'init') {
    result.init = true;
    return result;
  }

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--help' || arg === '-h') {
      result.help = true;
    } else if (arg === '--version' || arg === '-v') {
      result.version = true;
    } else if (arg === '--trace') {
      result.trace = true;
    } else if (arg === '--debug') {
      result.debug = true;
    } else if (arg === '--tui') {
      result.tui = true;
    } else if (arg === '--legacy' || arg === '--no-tui') {
      result.tui = false;
    } else if (arg === '--theme') {
      result.theme = args[++i] as 'dark' | 'light' | 'auto';
    } else if (arg === '--model' || arg === '-m') {
      result.model = args[++i];
    } else if (arg === '--permission' || arg === '-p') {
      result.permission = args[++i] as PermissionMode;
    } else if (arg === '--yolo') {
      result.permission = 'yolo';
    } else if (arg === '--max-iterations' || arg === '-i') {
      result.maxIterations = parseInt(args[++i], 10);
    } else if (arg === '--swarm') {
      // --swarm or --swarm path/to/config.yaml
      const next = args[i + 1];
      if (next && !next.startsWith('-') && (next.endsWith('.yaml') || next.endsWith('.yml') || next.endsWith('.json'))) {
        result.swarm = args[++i];
      } else {
        result.swarm = true;
      }
    } else if (arg === '--swarm-resume') {
      const nextArg = args[i + 1];
      if (nextArg && !nextArg.startsWith('--')) {
        result.swarmResume = nextArg;
        i++;
      } else {
        result.swarmResume = 'latest';
      }
      // Implicitly enable swarm mode
      if (!result.swarm) result.swarm = true;
    } else if (arg === '--resume') {
      // Shorthand for --swarm-resume
      const nextArg = args[i + 1];
      if (nextArg && !nextArg.startsWith('--')) {
        result.swarmResume = nextArg;
        i++;
      } else {
        result.swarmResume = 'latest';
      }
      if (!result.swarm) result.swarm = true;
    } else if (arg === '--paid-only') {
      result.paidOnly = true;
    } else if (arg === '--task' || arg === '-t') {
      result.task = args.slice(i + 1).join(' ');
      break;
    } else if (!arg.startsWith('-')) {
      result.task = args.slice(i).join(' ');
      break;
    }
  }

  return result;
}

/**
 * Display help text.
 */
export function showHelp(): void {
  logger.info(`
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('                    ATTOCODE - PRODUCTION CODING AGENT', 'bold')}
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}

A fully-featured AI coding agent with:
  • Memory, Planning, Reflection     • Multi-Agent Coordination
  • ReAct Reasoning                  • Sandboxed Execution
  • Thread Management & Checkpoints  • Session Persistence
  • MCP Integration                  • Context Compaction

${c('USAGE:', 'bold')}
  attocode [COMMAND] [OPTIONS] [TASK]

${c('COMMANDS:', 'bold')}
  init                    Interactive setup (API key, model, etc.)

${c('OPTIONS:', 'bold')}
  -h, --help              Show this help
  -v, --version           Show version (${VERSION})
  -m, --model MODEL       Model to use (e.g., anthropic/claude-sonnet-4)
  -p, --permission MODE   Permission mode:
                            strict      - Ask for everything
                            interactive - Ask for dangerous ops (default)
                            auto-safe   - Auto-approve safe ops
                            yolo        - Auto-approve everything
  --yolo                  Shorthand for --permission yolo
  -i, --max-iterations N  Max agent iterations (default: 50)
  -t, --task TASK         Run single task non-interactively
  --swarm [CONFIG]        Swarm mode: orchestrator + worker models
                            Without arg: auto-detect worker models
                            With path: load .attocode/swarm.yaml
  --swarm-resume [ID]     Resume a swarm session (omit ID for latest)
  --resume [ID]           Shorthand for --swarm-resume
  --paid-only             Use only paid models in swarm (no free tier)

${c('INTERFACE OPTIONS:', 'bold')}
  --tui                   Force TUI mode (rich Ink-based interface)
  --legacy, --no-tui      Force legacy readline mode
  --theme THEME           Color theme: dark, light, auto (default: auto)
  --trace                 Enable JSONL trace capture (saved to .traces/)
  --debug                 Enable verbose debug logging for persistence

${c('EXAMPLES:', 'bold')}
  ${c('# First-time setup', 'dim')}
  attocode init

  ${c('# Interactive mode (auto-detects TUI)', 'dim')}
  attocode

  ${c('# Single task execution', 'dim')}
  attocode "List all TypeScript files"

  ${c('# With specific model', 'dim')}
  attocode -m anthropic/claude-sonnet-4 "Explain this code"

  ${c('# Swarm mode (orchestrator + worker models)', 'dim')}
  attocode --swarm "Build a recursive descent parser"

  ${c('# Swarm with approval for dangerous ops only', 'dim')}
  attocode --swarm --permission auto-safe "Implement login"

  ${c('# Swarm with custom config and paid models only', 'dim')}
  attocode --swarm .attocode/swarm.yaml --paid-only "Refactor auth module"

  ${c('# Force legacy mode with tracing', 'dim')}
  attocode --legacy --trace

${c('KEY REPL COMMANDS:', 'bold')}
  /help        Show all commands         /status      Show metrics
  /checkpoint  Create checkpoint         /restore     Restore checkpoint
  /react       ReAct reasoning mode      /team        Multi-agent mode
  /agents      List subagents            /spawn       Spawn subagent
  /mcp         MCP server management     /compact     Compress context
  /sessions    List saved sessions       /resume      Resume last session

  ${c('Run /help in REPL for complete command list', 'dim')}

${c('ENVIRONMENT VARIABLES:', 'bold')}
  OPENROUTER_API_KEY    OpenRouter API key (recommended - multi-model)
  ANTHROPIC_API_KEY     Anthropic direct API key
  OPENAI_API_KEY        OpenAI direct API key

${c('FILES & DIRECTORIES:', 'bold')}
  .agent/sessions/      Session data (JSONL + SQLite)
  .traces/              Trace files (when --trace enabled)
  .mcp.json             MCP server configuration

${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
`);
}

/**
 * Determine whether to use TUI mode based on CLI args and environment.
 */
export function shouldUseTUI(args: CLIArgs): boolean {
  if (args.tui === true) return true;
  if (args.tui === false) return false;
  // Auto-detect: use TUI when TTY and interactive
  return process.stdin.isTTY && process.stdout.isTTY && !args.task;
}
