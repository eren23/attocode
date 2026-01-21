/**
 * Lesson 9: Complete Agent - Entry Point
 *
 * A "mini Claude Code" that demonstrates:
 * - Native tool use (no JSON parsing)
 * - Permission system
 * - Interactive REPL
 * - Context management (persistent conversations)
 *
 * Run: npx tsx 09-complete-agent/main.ts
 */

// Load .env file if present
import { config } from 'dotenv';
config();

// Import adapters to register them (they self-register on import)
import '../02-provider-abstraction/adapters/openrouter.js';
import '../02-provider-abstraction/adapters/anthropic.js';
import '../02-provider-abstraction/adapters/openai.js';
import '../02-provider-abstraction/adapters/azure.js';
import '../02-provider-abstraction/adapters/mock.js';

import { getProvider } from '../02-provider-abstraction/provider.js';
import { startREPL, runSingleTask } from './repl.js';
import { getToolsSummary } from './tools.js';
import type { LLMProviderWithTools } from '../02-provider-abstraction/types.js';
import type { PermissionMode } from '../03-tool-system/types.js';

// =============================================================================
// CLI ARGUMENT PARSING
// =============================================================================

interface CLIArgs {
  help: boolean;
  model?: string;
  permission: PermissionMode;
  task?: string;
  maxIterations: number;
}

function parseArgs(): CLIArgs {
  const args = process.argv.slice(2);
  const result: CLIArgs = {
    help: false,
    permission: 'interactive',
    maxIterations: 20,
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    if (arg === '--help' || arg === '-h') {
      result.help = true;
    } else if (arg === '--model' || arg === '-m') {
      result.model = args[++i];
    } else if (arg === '--permission' || arg === '-p') {
      const mode = args[++i] as PermissionMode;
      if (['strict', 'interactive', 'auto-safe', 'yolo'].includes(mode)) {
        result.permission = mode;
      } else {
        console.error(`Invalid permission mode: ${mode}`);
        process.exit(1);
      }
    } else if (arg === '--max-iterations' || arg === '-i') {
      result.maxIterations = parseInt(args[++i], 10);
    } else if (arg === '--task' || arg === '-t') {
      // Collect remaining args as task
      result.task = args.slice(i + 1).join(' ');
      break;
    } else if (!arg.startsWith('-')) {
      // Treat non-flag arg as task
      result.task = args.slice(i).join(' ');
      break;
    }
  }

  return result;
}

function showHelp(): void {
  console.log(`
╔════════════════════════════════════════════════════════════════╗
║  Lesson 9: Complete Agent                                      ║
╚════════════════════════════════════════════════════════════════╝

A complete coding agent with native tool use and permission system.

USAGE:
  npx tsx 09-complete-agent/main.ts [OPTIONS] [TASK]

OPTIONS:
  -h, --help              Show this help message
  -m, --model MODEL       Model to use (e.g., anthropic/claude-sonnet-4)
  -p, --permission MODE   Permission mode: strict, interactive, auto-safe, yolo
  -i, --max-iterations N  Maximum agent iterations (default: 20)
  -t, --task TASK         Run a single task (non-interactive)

PERMISSION MODES:
  strict      - Block dangerous, ask for moderate
  interactive - Ask user for moderate and dangerous (default)
  auto-safe   - Auto-approve safe and moderate
  yolo        - Auto-approve everything (testing only!)

EXAMPLES:
  # Start interactive REPL
  tsx 08-complete-agent/main.ts

  # Run a single task
  tsx 08-complete-agent/main.ts "List all TypeScript files"
  tsx 08-complete-agent/main.ts -t Create a hello.ts file

  # Use specific model
  tsx 08-complete-agent/main.ts -m openai/gpt-4o "Explain this codebase"

  # Dangerous mode (for testing)
  tsx 08-complete-agent/main.ts -p yolo "Delete all .tmp files"

AVAILABLE TOOLS:
${getToolsSummary()}

ENVIRONMENT:
  OPENROUTER_API_KEY - Required for OpenRouter provider
  ANTHROPIC_API_KEY  - Alternative: use Anthropic directly
  OPENAI_API_KEY     - Alternative: use OpenAI directly
`);
}

// =============================================================================
// MAIN
// =============================================================================

async function main(): Promise<void> {
  const args = parseArgs();

  if (args.help) {
    showHelp();
    return;
  }

  // Get provider
  console.log('🔌 Detecting LLM provider...');

  let provider: LLMProviderWithTools;
  try {
    const baseProvider = await getProvider();

    // Check if provider supports tools
    if (!('chatWithTools' in baseProvider)) {
      console.error('❌ Provider does not support native tool use.');
      console.error('   Currently only OpenRouter supports chatWithTools().');
      console.error('   Set OPENROUTER_API_KEY to use this lesson.');
      process.exit(1);
    }

    provider = baseProvider as LLMProviderWithTools;
    const actualModel = args.model || process.env.OPENROUTER_MODEL || provider.defaultModel;
    console.log(`✓ Using ${provider.name} (${actualModel})`);
  } catch (error) {
    console.error('❌ Failed to initialize provider:', (error as Error).message);
    console.error('\nMake sure you have set one of:');
    console.error('  - OPENROUTER_API_KEY (recommended)');
    console.error('  - ANTHROPIC_API_KEY');
    console.error('  - OPENAI_API_KEY');
    process.exit(1);
  }

  // Run mode
  if (args.task) {
    // Single task mode
    console.log(`\n📋 Task: ${args.task}\n`);

    const result = await runSingleTask(provider, args.task, {
      permissionMode: args.permission,
      maxIterations: args.maxIterations,
      model: args.model,
    });

    console.log('\n' + '='.repeat(60));
    console.log(result.success ? '✅ Task completed' : '⚠️ Task incomplete');
    console.log('='.repeat(60));
    console.log(result.message);

    process.exit(result.success ? 0 : 1);
  } else {
    // Interactive REPL mode
    await startREPL({
      provider,
      permissionMode: args.permission,
      maxIterations: args.maxIterations,
      model: args.model,
    });
  }
}

// =============================================================================
// RUN
// =============================================================================

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
