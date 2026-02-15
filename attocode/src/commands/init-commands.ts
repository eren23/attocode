/**
 * Init Command
 *
 * Handles /init to set up the .attocode/ directory structure.
 */

import { mkdir, writeFile } from 'fs/promises';
import { existsSync } from 'fs';
import { join } from 'path';
import type { CommandContext } from './types.js';

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
// DEFAULT CONFIG
// =============================================================================

const DEFAULT_CONFIG = `{
  "model": "sonnet",
  "maxIterations": 100,
  "contextWindow": 100000,
  "autoCompact": true,
  "skillsEnabled": true,
  "agentsEnabled": true,
  "resilience": {
    "incompleteActionAutoLoop": true,
    "maxIncompleteAutoLoops": 2,
    "autoLoopPromptStyle": "strict"
  },
  "hooks": {
    "builtIn": {
      "metrics": true
    },
    "shell": {
      "enabled": false,
      "defaultTimeoutMs": 5000,
      "commands": []
    }
  }
}
`;

const DEFAULT_SWARM_YAML = `# Swarm Configuration
# Uncomment and customize sections as needed.

# philosophy: |
#   Write clean, tested code. Prefer simplicity over cleverness.
#   Always run tests after changes.

# models:
#   orchestrator: google/gemini-2.0-flash-001
#   paid_only: false

# workers:
#   - name: coder
#     model: google/gemini-2.0-flash-001
#     capabilities: [code, refactor]
#     # persona: "You are a senior TypeScript developer."
#   - name: researcher
#     model: google/gemini-2.0-flash-001
#     capabilities: [research, analysis]

# hierarchy:
#   manager:
#     model: anthropic/claude-sonnet-4
#     # persona: "You are a strict code reviewer."
#   judge:
#     model: google/gemini-2.0-flash-001
#     # persona: "You are a quality assurance expert."

# budget:
#   total_tokens: 2000000
#   max_cost: 1.00
#   max_tokens_per_worker: 20000

# quality:
#   gates: true
#   # gate_model: google/gemini-2.0-flash-001

# communication:
#   blackboard: true
#   dependency_context_max_length: 2000
#   include_file_list: true

# resilience:
#   max_concurrency: 5
#   worker_retries: 2
#   rate_limit_retries: 3
#   dispatch_stagger_ms: 500

# permissions:
#   mode: auto-safe                      # recommended for non-yolo use
#   auto_approve: [read_file, glob, grep, list_files, search]
#   scoped_approve:
#     write_file: { paths: ["src/", "tests/"] }
#     bash: { paths: ["src/", "tests/"] }
#   require_approval: [bash_dangerous]
`;

const DEFAULT_RULES = `# Project Rules

## Code Style

- Follow existing patterns in the codebase
- Use meaningful variable and function names
- Keep functions small and focused

## Testing

- Write tests for new functionality
- Run tests before committing

## Documentation

- Document public APIs
- Update README when adding features

## Safety

- Never commit secrets or credentials
- Review changes before execution
`;

// =============================================================================
// INIT COMMAND HANDLER
// =============================================================================

export interface InitOptions {
  force?: boolean;
  minimal?: boolean;
}

export interface InitResult {
  success: boolean;
  created: string[];
  skipped: string[];
  errors: string[];
}

/**
 * Initialize the .attocode/ directory structure.
 */
export async function initAttocodeDirectory(options: InitOptions = {}): Promise<InitResult> {
  const cwd = process.cwd();

  const result: InitResult = {
    success: true,
    created: [],
    skipped: [],
    errors: [],
  };

  // Directories to create
  const directories = [
    '.attocode',
    '.attocode/skills',
    '.attocode/agents',
  ];

  // Files to create with their content
  const files: Array<{ path: string; content: string }> = options.minimal ? [] : [
    { path: '.attocode/config.json', content: DEFAULT_CONFIG },
    { path: '.attocode/rules.md', content: DEFAULT_RULES },
    { path: '.attocode/swarm.yaml', content: DEFAULT_SWARM_YAML },
  ];

  // Create directories
  for (const dir of directories) {
    const fullPath = join(cwd, dir);
    try {
      if (existsSync(fullPath)) {
        result.skipped.push(dir);
      } else {
        await mkdir(fullPath, { recursive: true });
        result.created.push(dir);
      }
    } catch (error) {
      result.errors.push(`Failed to create ${dir}: ${(error as Error).message}`);
      result.success = false;
    }
  }

  // Create files
  for (const file of files) {
    const fullPath = join(cwd, file.path);
    try {
      if (existsSync(fullPath) && !options.force) {
        result.skipped.push(file.path);
      } else {
        await writeFile(fullPath, file.content, 'utf-8');
        result.created.push(file.path);
      }
    } catch (error) {
      result.errors.push(`Failed to create ${file.path}: ${(error as Error).message}`);
      result.success = false;
    }
  }

  return result;
}

/**
 * Check if .attocode/ directory exists and get its status.
 */
export async function checkAttocodeStatus(): Promise<{
  exists: boolean;
  hasConfig: boolean;
  hasSkills: boolean;
  hasAgents: boolean;
  hasRules: boolean;
}> {
  const cwd = process.cwd();

  return {
    exists: existsSync(join(cwd, '.attocode')),
    hasConfig: existsSync(join(cwd, '.attocode', 'config.json')),
    hasSkills: existsSync(join(cwd, '.attocode', 'skills')),
    hasAgents: existsSync(join(cwd, '.attocode', 'agents')),
    hasRules: existsSync(join(cwd, '.attocode', 'rules.md')),
  };
}

/**
 * Handle /init command.
 */
export async function handleInitCommand(
  args: string[],
  ctx: CommandContext
): Promise<void> {
  const { output } = ctx;

  // Check current status
  const status = await checkAttocodeStatus();

  if (status.exists && !args.includes('--force')) {
    output.log(c('.attocode/ directory already exists.', 'yellow'));
    output.log('');
    output.log(c('Current status:', 'bold'));
    output.log(`  ${status.hasConfig ? c('+', 'green') : c('o', 'dim')} config.json`);
    output.log(`  ${status.hasRules ? c('+', 'green') : c('o', 'dim')} rules.md`);
    output.log(`  ${status.hasSkills ? c('+', 'green') : c('o', 'dim')} skills/`);
    output.log(`  ${status.hasAgents ? c('+', 'green') : c('o', 'dim')} agents/`);
    output.log('');
    output.log(c('Use /init --force to recreate missing files.', 'dim'));
    return;
  }

  const options: InitOptions = {
    force: args.includes('--force'),
    minimal: args.includes('--minimal'),
  };

  output.log(c('Initializing .attocode/ directory...', 'cyan'));
  output.log('');

  const result = await initAttocodeDirectory(options);

  if (result.created.length > 0) {
    output.log(c('Created:', 'green'));
    for (const item of result.created) {
      output.log(`  ${c('+', 'green')} ${item}`);
    }
  }

  if (result.skipped.length > 0) {
    output.log(c('\nSkipped (already exists):', 'dim'));
    for (const item of result.skipped) {
      output.log(`  ${c('o', 'dim')} ${item}`);
    }
  }

  if (result.errors.length > 0) {
    output.log(c('\nErrors:', 'red'));
    for (const error of result.errors) {
      output.log(`  ${c('x', 'red')} ${error}`);
    }
  }

  if (result.success) {
    output.log('');
    output.log(c('Next steps:', 'bold'));
    output.log(`  ${c('/skills new <name>', 'cyan')}   Create a custom skill`);
    output.log(`  ${c('/agents new <name>', 'cyan')}   Create a custom agent`);
    output.log('');
    output.log(c('Edit .attocode/config.json for project settings.', 'dim'));
    output.log(c('Edit .attocode/rules.md for project-specific rules.', 'dim'));
  }
}
