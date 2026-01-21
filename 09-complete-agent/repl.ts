/**
 * Lesson 9: Interactive REPL with Persistent Sessions
 *
 * A command-line interface for interacting with the agent.
 * Features:
 * - Real-time feedback on tool execution
 * - Persistent conversation history across prompts
 * - Session save/load for resuming conversations
 * - Cache hit statistics
 * - Subagent spawning commands
 */

import * as readline from 'node:readline/promises';
import { stdin, stdout } from 'node:process';
import { runAgentWithContext } from './agent.js';
import { createStandardRegistry, getToolsSummary } from './tools.js';
import { createContextManager } from './context/context-manager.js';
import { FilesystemContextStorage } from './context/filesystem-context.js';
import { CacheAwareProvider, type CacheStatistics } from '../08-cache-hitting/cache-provider.js';
import type { CompleteAgentConfig, AgentEvent, AgentResult, PermissionMode } from './types.js';
import type { LLMProviderWithTools } from '../02-provider-abstraction/types.js';

// =============================================================================
// COLORS (simple ANSI codes, no chalk dependency needed)
// =============================================================================

const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  red: '\x1b[31m',
};

function colorize(text: string, color: keyof typeof colors): string {
  return `${colors[color]}${text}${colors.reset}`;
}

// =============================================================================
// REPL CONFIGURATION
// =============================================================================

export interface REPLOptions {
  provider: LLMProviderWithTools;
  permissionMode?: PermissionMode;
  maxIterations?: number;
  model?: string;
  showTokenUsage?: boolean;
  /** Directory to store session data */
  storageDir?: string;
  /** Session ID to load on startup */
  sessionId?: string;
}

// =============================================================================
// SESSION STATISTICS
// =============================================================================

interface SessionStats {
  totalTasks: number;
  successfulTasks: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCachedTokens: number;
  toolCallsCount: number;
}

function createStats(): SessionStats {
  return {
    totalTasks: 0,
    successfulTasks: 0,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    totalCachedTokens: 0,
    toolCallsCount: 0,
  };
}

function updateStats(stats: SessionStats, result: AgentResult): void {
  stats.totalTasks++;
  if (result.success) {
    stats.successfulTasks++;
  }
  if (result.usage) {
    stats.totalInputTokens += result.usage.inputTokens;
    stats.totalOutputTokens += result.usage.outputTokens;
    stats.totalCachedTokens += result.usage.cachedTokens ?? 0;
  }
  stats.toolCallsCount += result.toolCalls?.length ?? 0;
}

function formatCacheStats(stats: SessionStats): string {
  const totalInputTokens = stats.totalInputTokens;
  const cachedTokens = stats.totalCachedTokens;
  const hitRate = totalInputTokens > 0
    ? ((cachedTokens / totalInputTokens) * 100).toFixed(1)
    : '0.0';

  return `Cache: ${cachedTokens.toLocaleString()} cached / ${totalInputTokens.toLocaleString()} input (${hitRate}% hit rate)`;
}

// =============================================================================
// EVENT DISPLAY
// =============================================================================

/**
 * Create an event handler that displays agent activity in real-time.
 */
function createEventDisplay(showTokenUsage: boolean) {
  return (event: AgentEvent): void => {
    switch (event.type) {
      case 'thinking':
        console.log(colorize(`\n💭 ${event.message}`, 'dim'));
        break;

      case 'iteration':
        console.log(colorize(`\n[Iteration ${event.current}/${event.max}]`, 'dim'));
        break;

      case 'tool_call':
        console.log(colorize(`\n🔧 Tool: ${event.name}`, 'cyan'));
        console.log(colorize(`   Args: ${JSON.stringify(event.args, null, 2).split('\n').join('\n   ')}`, 'dim'));
        break;

      case 'tool_result':
        const status = event.result.success
          ? colorize('✓', 'green')
          : colorize('✗', 'red');
        console.log(`   ${status} ${truncate(event.result.output, 200)}`);
        break;

      case 'permission_requested':
        console.log(colorize(`\n⚠️  Permission requested: ${event.tool} (${event.level})`, 'yellow'));
        break;

      case 'permission_denied':
        console.log(colorize(`   ❌ Denied: ${event.reason}`, 'red'));
        break;

      case 'cache_hit':
        console.log(colorize(`   💾 Cache hit: ${event.tokens.toLocaleString()} tokens from cache`, 'blue'));
        break;

      case 'error':
        console.log(colorize(`\n❌ Error: ${event.error.message}`, 'red'));
        break;

      case 'complete':
        if (showTokenUsage && event.result.usage) {
          const cached = event.result.usage.cachedTokens ?? 0;
          const cacheInfo = cached > 0 ? ` (${cached} cached)` : '';
          console.log(colorize(
            `\n📊 Tokens: ${event.result.usage.inputTokens} in${cacheInfo} / ${event.result.usage.outputTokens} out`,
            'dim'
          ));
        }
        break;
    }
  };
}

/**
 * Truncate long output for display.
 */
function truncate(text: string, maxLength: number): string {
  const firstLine = text.split('\n')[0];
  if (firstLine.length <= maxLength) {
    return firstLine + (text.includes('\n') ? ' ...' : '');
  }
  return firstLine.slice(0, maxLength) + '...';
}

// =============================================================================
// REPL COMMANDS
// =============================================================================

function showHelp(): void {
  console.log(`
${colorize('Commands:', 'bold')}
  ${colorize('/help', 'cyan')}       - Show this help message
  ${colorize('/tools', 'cyan')}      - List available tools
  ${colorize('/status', 'cyan')}     - Show session statistics and cache info
  ${colorize('/clear', 'cyan')}      - Clear screen (keeps history)
  ${colorize('/new', 'cyan')}        - Start new conversation (clears history)
  ${colorize('/save', 'cyan')}       - Save current session
  ${colorize('/load <id>', 'cyan')}  - Load a saved session
  ${colorize('/sessions', 'cyan')}   - List available sessions
  ${colorize('/context', 'cyan')}    - Show context summary (files read, etc.)
  ${colorize('/quit', 'cyan')}       - Exit the REPL

${colorize('Tips:', 'bold')}
  • Conversation persists across prompts - the agent remembers context
  • Use /save to preserve your session for later
  • Use /status to see cache hit statistics
`);
}

function showTools(): void {
  console.log(`
${colorize('Available Tools:', 'bold')}
${getToolsSummary()}

${colorize('Legend:', 'dim')} ⚠️ = requires permission
`);
}

// =============================================================================
// MAIN REPL LOOP
// =============================================================================

/**
 * Start the interactive REPL with persistent sessions.
 *
 * @example
 * ```typescript
 * import { OpenRouterProvider } from '../02-provider-abstraction/adapters/openrouter.js';
 *
 * const provider = new OpenRouterProvider();
 * await startREPL({
 *   provider,
 *   permissionMode: 'interactive',
 *   storageDir: './.agent-sessions'
 * });
 * ```
 */
export async function startREPL(options: REPLOptions): Promise<void> {
  const {
    provider,
    permissionMode = 'interactive',
    maxIterations = 20,
    model,
    showTokenUsage = true,
    storageDir = './.agent-sessions',
  } = options;

  // Create storage and context manager
  const storage = new FilesystemContextStorage(storageDir);
  let contextManager = createContextManager({
    maxMessages: 100,
    maxTokens: 100000,
    storage,
  });

  // Generate or use provided session ID
  let sessionId = options.sessionId ?? generateSessionId();

  // Try to load existing session
  if (options.sessionId) {
    const loaded = await contextManager.loadSession(options.sessionId);
    if (loaded) {
      console.log(colorize(`\n✓ Loaded session: ${options.sessionId}`, 'green'));
    } else {
      console.log(colorize(`\n⚠️ Session not found, starting new: ${sessionId}`, 'yellow'));
    }
  }

  // Create registry with permission mode
  const registry = createStandardRegistry(permissionMode);

  // Track session stats
  const stats = createStats();

  // Wrap provider with cache-aware version for automatic cache marker application
  const cachedProvider = new CacheAwareProvider(provider, {
    minCacheableTokens: 500, // Cache content with 500+ tokens
    alwaysCacheSystem: true, // System prompts always cached
    recentUncachedCount: 2,  // Don't cache last 2 messages (they may change)
    onCacheStats: (cacheStats: CacheStatistics) => {
      // Update our stats when cache info is available
      if (showTokenUsage && cacheStats.hitRate > 0) {
        console.log(colorize(
          `   💾 Cache: ${cacheStats.cachedTokens.toLocaleString()} tokens (${(cacheStats.hitRate * 100).toFixed(1)}% hit rate)`,
          'blue'
        ));
      }
    },
  });

  // Create agent config with cache-aware provider
  const config: CompleteAgentConfig = {
    provider: cachedProvider,
    maxIterations,
    enableCaching: true,
    permissionMode,
    model,
    onEvent: createEventDisplay(showTokenUsage),
  };

  // Setup readline interface
  const rl = readline.createInterface({ input: stdin, output: stdout });

  // Print welcome message
  console.log(boxedHeader('Mini Claude Code - Lesson 9'));
  console.log(colorize(`Session: ${sessionId}`, 'dim'));
  console.log(colorize('Type your request, or /help for commands.\n', 'dim'));

  try {
    while (true) {
      // Prompt for input
      const input = await rl.question(colorize('You: ', 'green'));
      const trimmed = input.trim();

      // Handle empty input
      if (!trimmed) continue;

      // Handle commands
      if (trimmed.startsWith('/')) {
        const parts = trimmed.split(/\s+/);
        const command = parts[0].toLowerCase();
        const args = parts.slice(1);

        if (command === '/quit' || command === '/exit' || command === '/q') {
          // Auto-save on exit
          await contextManager.saveSession();
          console.log(colorize(`\n✓ Session saved: ${sessionId}`, 'green'));
          console.log(colorize('Goodbye! 👋', 'cyan'));
          break;
        }

        if (command === '/help' || command === '/h') {
          showHelp();
          continue;
        }

        if (command === '/tools') {
          showTools();
          continue;
        }

        if (command === '/clear') {
          console.clear();
          console.log(boxedHeader('Mini Claude Code - Lesson 9'));
          console.log(colorize(`Session: ${sessionId}`, 'dim'));
          console.log(colorize('Screen cleared (history preserved).\n', 'dim'));
          continue;
        }

        if (command === '/new') {
          // Start new conversation
          contextManager = createContextManager({
            maxMessages: 100,
            maxTokens: 100000,
            storage,
          });
          sessionId = generateSessionId();
          console.log(colorize(`\n✓ New session started: ${sessionId}`, 'green'));
          continue;
        }

        if (command === '/save') {
          await contextManager.saveSession();
          console.log(colorize(`\n✓ Session saved: ${sessionId}`, 'green'));
          console.log(colorize(`  Messages: ${contextManager.getMessageCount()}`, 'dim'));
          continue;
        }

        if (command === '/load') {
          if (args.length === 0) {
            console.log(colorize('Usage: /load <session-id>', 'yellow'));
            console.log(colorize('Use /sessions to list available sessions.', 'dim'));
            continue;
          }
          const loadId = args[0];
          const loaded = await contextManager.loadSession(loadId);
          if (loaded) {
            sessionId = loadId;
            console.log(colorize(`\n✓ Loaded session: ${loadId}`, 'green'));
            console.log(colorize(`  Messages: ${contextManager.getMessageCount()}`, 'dim'));
          } else {
            console.log(colorize(`\n✗ Session not found: ${loadId}`, 'red'));
          }
          continue;
        }

        if (command === '/sessions') {
          const sessions = await storage.listSessions();
          if (sessions.length === 0) {
            console.log(colorize('\nNo saved sessions found.', 'dim'));
          } else {
            console.log(colorize('\nSaved Sessions:', 'bold'));
            for (const session of sessions) {
              const active = session.id === sessionId ? colorize(' (current)', 'green') : '';
              const date = new Date(session.updatedAt).toLocaleString();
              console.log(`  ${colorize(session.id, 'cyan')}${active}`);
              console.log(colorize(`    Messages: ${session.messageCount}, Updated: ${date}`, 'dim'));
            }
          }
          console.log();
          continue;
        }

        if (command === '/context') {
          const summary = contextManager.buildContextSummary();
          console.log(colorize('\nContext Summary:', 'bold'));
          console.log(summary || colorize('  No context yet.', 'dim'));
          console.log();
          continue;
        }

        if (command === '/status') {
          const cacheInfo = formatCacheStats(stats);
          console.log(`
${colorize('Session Status:', 'bold')}
  Session ID:      ${sessionId}
  Messages:        ${contextManager.getMessageCount()}
  Tasks:           ${stats.successfulTasks}/${stats.totalTasks} successful
  Tool calls:      ${stats.toolCallsCount}
  Permission mode: ${permissionMode}
  Max iterations:  ${maxIterations}
  Model:           ${model || 'default'}

${colorize('Token Usage:', 'bold')}
  Input tokens:    ${stats.totalInputTokens.toLocaleString()}
  Output tokens:   ${stats.totalOutputTokens.toLocaleString()}
  Cached tokens:   ${stats.totalCachedTokens.toLocaleString()}
  ${cacheInfo}
`);
          continue;
        }

        console.log(colorize(`Unknown command: ${trimmed}. Type /help for commands.`, 'yellow'));
        continue;
      }

      // Run agent with persistent context
      try {
        const result = await runAgentWithContext(trimmed, registry, config, contextManager);
        updateStats(stats, result);

        if (result.success) {
          console.log(colorize('\n━━━ Assistant ━━━', 'magenta'));
          console.log(result.message);
          console.log(colorize('━━━━━━━━━━━━━━━━━', 'magenta'));
        } else {
          console.log(colorize('\n⚠️ Task incomplete:', 'yellow'));
          console.log(result.message);
        }

        // Auto-save after each interaction
        await contextManager.saveSession();
      } catch (error) {
        console.log(colorize(`\n❌ Agent error: ${(error as Error).message}`, 'red'));
      }

      console.log(); // Add spacing
    }
  } finally {
    rl.close();
  }
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Generate a unique session ID.
 */
function generateSessionId(): string {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 8);
  return `session-${timestamp}-${random}`;
}

/**
 * Create a boxed header for nice console output.
 */
function boxedHeader(title: string): string {
  const width = 60;
  const padding = Math.floor((width - title.length - 2) / 2);
  const line = '═'.repeat(width);

  return `
${colorize('╔' + line + '╗', 'cyan')}
${colorize('║' + ' '.repeat(padding) + title + ' '.repeat(width - padding - title.length) + '║', 'cyan')}
${colorize('╚' + line + '╝', 'cyan')}
`;
}

// =============================================================================
// SINGLE-TASK MODE
// =============================================================================

/**
 * Run a single task (non-interactive mode).
 * Useful for scripting or one-off commands.
 *
 * @example
 * ```typescript
 * const result = await runSingleTask(provider, 'List all TypeScript files');
 * console.log(result.message);
 * ```
 */
export async function runSingleTask(
  provider: LLMProviderWithTools,
  task: string,
  options: Partial<REPLOptions> = {}
): Promise<AgentResult> {
  const {
    permissionMode = 'interactive',
    maxIterations = 20,
    model,
    showTokenUsage = true,
    storageDir = './.agent-sessions',
  } = options;

  const registry = createStandardRegistry(permissionMode);

  // Create context manager for the single task
  const storage = new FilesystemContextStorage(storageDir);
  const contextManager = createContextManager({
    maxMessages: 100,
    maxTokens: 100000,
    storage,
  });

  // Wrap with cache-aware provider
  const cachedProvider = new CacheAwareProvider(provider, {
    minCacheableTokens: 500,
    alwaysCacheSystem: true,
  });

  const config: CompleteAgentConfig = {
    provider: cachedProvider,
    maxIterations,
    enableCaching: true,
    permissionMode,
    model,
    onEvent: createEventDisplay(showTokenUsage),
  };

  return runAgentWithContext(task, registry, config, contextManager);
}
