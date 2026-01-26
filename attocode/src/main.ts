#!/usr/bin/env node
/**
 * Attocode - A Production Coding Agent
 *
 * A fully-featured coding agent for development tasks.
 *
 * Features:
 * - Real LLM integration (OpenRouter, Anthropic, OpenAI)
 * - Full tool suite (file ops, bash, search, etc.)
 * - Memory system (remembers past interactions)
 * - Planning for complex tasks
 * - Multi-Agent Coordination
 * - ReAct Pattern
 * - Observability (tracing, metrics)
 * - Safety controls (sandbox, human-in-loop)
 * - Execution Policies
 * - Thread Management & Checkpoints
 * - Session persistence
 *
 * Run: npx tsx src/main.ts
 */

// Load environment
import { config } from 'dotenv';
config();

// Import adapters to register them
import './providers/adapters/openrouter.js';
import './providers/adapters/anthropic.js';
import './providers/adapters/openai.js';
import './providers/adapters/mock.js';

import * as readline from 'node:readline/promises';
import { stdin, stdout } from 'node:process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { existsSync, readFileSync } from 'node:fs';

import { getProvider } from './providers/provider.js';
import { createStandardRegistry } from './tools/standard.js';
import type { LLMProviderWithTools } from './providers/types.js';
import type { PermissionMode } from './tools/types.js';

import { ProductionAgent, createProductionAgent } from './agent.js';
import { ProviderAdapter, convertToolsFromRegistry, createInteractiveApprovalHandler } from './adapters.js';
import type { AgentEvent, AgentResult } from './types.js';

// New integrations
import {
  SQLiteStore,
  createSQLiteStore,
  SessionStore,
  createSessionStore,
  MCPClient,
  createMCPClient,
  formatServerList,
  Compactor,
  createCompactor,
  formatCompactionResult,
  getContextUsage,
  createMCPMetaTools,
} from './integrations/index.js';

// First-run and init command
import { runInit } from './commands/init.js';
import { isFirstRun, hasUsableProvider, getFirstRunMessage } from './first-run.js';

// Config paths
import { getConfigPath, getMCPConfigPaths } from './paths.js';

// Session picker
import { showSessionPicker, showQuickPicker, formatSessionsTable } from './session-picker.js';

// Session store type that works with both SQLite and JSONL
type AnySessionStore = SQLiteStore | SessionStore;

// =============================================================================
// PROCESS ERROR HANDLERS
// =============================================================================

/**
 * Global cleanup resources - populated during initialization.
 * Used by process error handlers to gracefully clean up before exit.
 */
interface CleanupResources {
  agent?: { cleanup: () => Promise<void> };
  mcpClient?: { cleanup: () => Promise<void> };
  tui?: { cleanup: () => void };
  rl?: { close: () => void };
}

let cleanupResources: CleanupResources = {};
let isCleaningUp = false;

/**
 * Gracefully clean up all resources before exit.
 * Times out after 5 seconds to prevent hanging.
 */
async function gracefulCleanup(reason: string): Promise<void> {
  // Prevent recursive cleanup
  if (isCleaningUp) {
    return;
  }
  isCleaningUp = true;

  console.error(`\n[CLEANUP] Starting graceful cleanup (reason: ${reason})...`);

  // Set a hard timeout to prevent hanging
  const forceExitTimeout = setTimeout(() => {
    console.error('[CLEANUP] Timeout reached, forcing exit');
    process.exit(1);
  }, 5000);

  try {
    // Clean up in reverse initialization order
    // 1. TUI (synchronous)
    if (cleanupResources.tui) {
      try {
        cleanupResources.tui.cleanup();
      } catch (e) {
        console.error('[CLEANUP] TUI cleanup error:', e);
      }
    }

    // 2. Readline (synchronous)
    if (cleanupResources.rl) {
      try {
        cleanupResources.rl.close();
      } catch (e) {
        console.error('[CLEANUP] Readline cleanup error:', e);
      }
    }

    // 3. Agent (async)
    if (cleanupResources.agent) {
      try {
        await cleanupResources.agent.cleanup();
      } catch (e) {
        console.error('[CLEANUP] Agent cleanup error:', e);
      }
    }

    // 4. MCP Client (async)
    if (cleanupResources.mcpClient) {
      try {
        await cleanupResources.mcpClient.cleanup();
      } catch (e) {
        console.error('[CLEANUP] MCP cleanup error:', e);
      }
    }

    console.error('[CLEANUP] Cleanup completed');
  } finally {
    clearTimeout(forceExitTimeout);
  }
}

/**
 * Register a resource for cleanup on process exit.
 */
function registerCleanupResource<K extends keyof CleanupResources>(
  key: K,
  resource: CleanupResources[K]
): void {
  cleanupResources[key] = resource;
}

// Handle unhandled promise rejections
process.on('unhandledRejection', async (reason, _promise) => {
  console.error('\n[FATAL] Unhandled Promise Rejection:');
  console.error('  Reason:', reason);
  if (reason instanceof Error && reason.stack) {
    console.error('  Stack:', reason.stack.split('\n').slice(0, 5).join('\n'));
  }
  await gracefulCleanup('unhandled rejection');
  process.exit(1);
});

// Handle uncaught exceptions
process.on('uncaughtException', async (error, origin) => {
  console.error(`\n[FATAL] Uncaught Exception (${origin}):`);
  console.error('  Error:', error.message);
  if (error.stack) {
    console.error('  Stack:', error.stack.split('\n').slice(0, 5).join('\n'));
  }
  await gracefulCleanup('uncaught exception');
  process.exit(1);
});

// Handle SIGTERM for graceful shutdown (e.g., container orchestration)
process.on('SIGTERM', async () => {
  console.error('\n[INFO] Received SIGTERM signal');
  await gracefulCleanup('SIGTERM');
  process.exit(0);
});

// =============================================================================
// CONFIG LOADING
// =============================================================================

interface UserConfig {
  providers?: { default?: string };
  model?: string;
  maxIterations?: number;
  timeout?: number;
}

/**
 * Load user config from ~/.config/attocode/config.json
 * Returns undefined if file doesn't exist or is invalid.
 */
function loadUserConfig(): UserConfig | undefined {
  try {
    const configPath = getConfigPath();
    if (!existsSync(configPath)) {
      return undefined;
    }
    const content = readFileSync(configPath, 'utf-8');
    return JSON.parse(content) as UserConfig;
  } catch {
    return undefined;
  }
}

// =============================================================================
// DEBUG LOGGER FOR PERSISTENCE OPERATIONS
// =============================================================================

/**
 * Debug logger for persistence operations.
 * Enabled via --debug flag. Shows data flow at each layer boundary.
 * In TUI mode, logs are buffered instead of printed to avoid interfering with Ink.
 */
class PersistenceDebugger {
  private enabled = false;
  private tuiMode = false;
  private buffer: string[] = [];

  enable(): void {
    this.enabled = true;
    this.log('🔍 Persistence debug mode ENABLED');
  }

  enableTUIMode(): void {
    this.tuiMode = true;
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  getBuffer(): string[] {
    const logs = [...this.buffer];
    this.buffer = [];
    return logs;
  }

  log(message: string, data?: unknown): void {
    if (!this.enabled) return;
    const timestamp = new Date().toISOString().split('T')[1].slice(0, 12);
    const logLine = `[${timestamp}] 🔧 ${message}`;
    const dataLine = data !== undefined ? `    └─ ${JSON.stringify(data, null, 2).split('\n').join('\n    ')}` : '';

    if (this.tuiMode) {
      // Buffer logs in TUI mode to avoid console interference
      this.buffer.push(logLine);
      if (dataLine) this.buffer.push(dataLine);
    } else {
      console.log(logLine);
      if (dataLine) console.log(dataLine);
    }
  }

  error(message: string, err: unknown): void {
    if (!this.enabled) return;
    const timestamp = new Date().toISOString().split('T')[1].slice(0, 12);
    const errLine = `[${timestamp}] ❌ ${message}`;
    let details = '';
    if (err instanceof Error) {
      details = `    └─ ${err.message}`;
      if (err.stack) {
        details += `\n    └─ Stack: ${err.stack.split('\n').slice(1, 3).join(' → ')}`;
      }
    } else {
      details = `    └─ ${String(err)}`;
    }

    if (this.tuiMode) {
      this.buffer.push(errLine);
      this.buffer.push(details);
    } else {
      console.error(errLine);
      console.error(details);
    }
  }

  storeType(store: AnySessionStore): string {
    if ('saveCheckpoint' in store && typeof store.saveCheckpoint === 'function') {
      return 'SQLiteStore';
    }
    return 'JSONLStore';
  }
}

// Global debug instance - enabled via --debug flag
const persistenceDebug = new PersistenceDebugger();

/**
 * Checkpoint data structure for full state restoration.
 */
interface CheckpointData {
  id: string;
  label?: string;
  messages: unknown[];
  iteration: number;
  metrics?: unknown;
  plan?: unknown;
  memoryContext?: string[];
}

/**
 * Save checkpoint to session store (works with both SQLite and JSONL).
 * Now includes plan and memoryContext for full state restoration.
 */
function saveCheckpointToStore(
  store: AnySessionStore,
  checkpoint: CheckpointData
): void {
  const storeType = persistenceDebug.storeType(store);
  persistenceDebug.log(`saveCheckpointToStore called`, {
    storeType,
    checkpointId: checkpoint.id,
    messageCount: checkpoint.messages?.length ?? 0,
    hasLabel: !!checkpoint.label,
    hasPlan: !!checkpoint.plan,
  });

  try {
    if ('saveCheckpoint' in store && typeof store.saveCheckpoint === 'function') {
      // SQLite store - check currentSessionId
      const sqliteStore = store as SQLiteStore;
      const currentSessionId = sqliteStore.getCurrentSessionId();
      persistenceDebug.log(`SQLite saveCheckpoint`, {
        currentSessionId,
        hasCurrentSession: !!currentSessionId,
      });

      if (!currentSessionId) {
        persistenceDebug.error('SQLite store has no currentSessionId!', new Error('No active session'));
      }

      const ckptId = store.saveCheckpoint(
        {
          id: checkpoint.id,
          label: checkpoint.label,
          messages: checkpoint.messages,
          iteration: checkpoint.iteration,
          metrics: checkpoint.metrics,
          plan: checkpoint.plan,
          memoryContext: checkpoint.memoryContext,
        },
        checkpoint.label || `auto-checkpoint-${checkpoint.id}`
      );
      persistenceDebug.log(`SQLite checkpoint saved successfully`, { returnedId: ckptId });
    } else if ('appendEntry' in store && typeof store.appendEntry === 'function') {
      // JSONL store - use appendEntry with checkpoint type
      persistenceDebug.log(`JSONL appendEntry (checkpoint type)`);
      store.appendEntry({
        type: 'checkpoint',
        data: {
          id: checkpoint.id,
          label: checkpoint.label,
          messages: checkpoint.messages,
          iteration: checkpoint.iteration,
          metrics: checkpoint.metrics,
          plan: checkpoint.plan,
          memoryContext: checkpoint.memoryContext,
          createdAt: new Date().toISOString(),
        },
      });
      persistenceDebug.log(`JSONL checkpoint appended successfully`);
    } else {
      persistenceDebug.error('No compatible save method found on store', { storeType });
    }
  } catch (err) {
    persistenceDebug.error(`Failed to save checkpoint`, err);
    // Re-throw in debug mode so the error is visible
    if (persistenceDebug.isEnabled()) {
      throw err;
    }
  }
}

/**
 * Load session state (checkpoint or messages) for resuming.
 * Returns checkpoint data if found, or null.
 */
async function loadSessionState(
  sessionStore: AnySessionStore,
  sessionId: string
): Promise<CheckpointData | null> {
  persistenceDebug.log('Loading session state', { sessionId });

  // Try SQLite's loadLatestCheckpoint first
  if ('loadLatestCheckpoint' in sessionStore && typeof sessionStore.loadLatestCheckpoint === 'function') {
    const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(sessionId);
    if (sqliteCheckpoint?.state) {
      persistenceDebug.log('Loaded from SQLite checkpoint', {
        messageCount: (sqliteCheckpoint.state as any).messages?.length,
      });
      return sqliteCheckpoint.state as unknown as CheckpointData;
    }
  }

  // Fall back to entries-based lookup (for JSONL or if SQLite checkpoint not found)
  try {
    const entriesResult = sessionStore.loadSession(sessionId);
    const entries = Array.isArray(entriesResult) ? entriesResult : await entriesResult;

    // Try to find a checkpoint entry
    const checkpoint = [...entries].reverse().find(e => e.type === 'checkpoint');
    if (checkpoint?.data) {
      persistenceDebug.log('Loaded from entries checkpoint', {
        messageCount: (checkpoint.data as any).messages?.length,
      });
      return checkpoint.data as CheckpointData;
    }

    // No checkpoint, try to load messages directly from entries
    const messages = entries
      .filter((e: { type: string }) => e.type === 'message')
      .map((e: { data: unknown }) => e.data);

    if (messages.length > 0) {
      persistenceDebug.log('Loaded messages from entries', { count: messages.length });
      return {
        id: `loaded-${sessionId}`,
        messages,
        iteration: 0,
      };
    }
  } catch (error) {
    persistenceDebug.error('Failed to load session entries', error);
  }

  return null;
}

// LSP integration
import { createLSPManager, type LSPManager } from './integrations/lsp.js';
import { createLSPFileTools } from './agent-tools/lsp-file-tools.js';

// Pricing
import { initPricingCache } from './integrations/openrouter-pricing.js';

// TUI for colored output
import { createTUIRenderer } from './tui/index.js';

// ESM equivalent of __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// =============================================================================
// COLORS
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

function c(text: string, color: keyof typeof colors): string {
  return `${colors[color]}${text}${colors.reset}`;
}

// =============================================================================
// EVENT DISPLAY
// =============================================================================

function createEventDisplay() {
  return (event: AgentEvent): void => {
    switch (event.type) {
      case 'start':
        console.log(c(`\n💭 Starting task...`, 'dim'));
        break;

      case 'planning':
        console.log(c(`\n📋 Plan created with ${event.plan.tasks.length} steps:`, 'blue'));
        event.plan.tasks.forEach((t, i) => {
          console.log(c(`   ${i + 1}. ${t.description}`, 'dim'));
        });
        break;

      case 'task.start':
        console.log(c(`\n▶ Starting: ${event.task.description}`, 'cyan'));
        break;

      case 'task.complete':
        console.log(c(`   ✓ Completed: ${event.task.description}`, 'green'));
        break;

      case 'llm.start':
        console.log(c(`\n🤖 Calling LLM (${event.model})...`, 'dim'));
        break;

      case 'llm.complete':
        if (event.response.usage) {
          console.log(c(
            `   📊 Tokens: ${event.response.usage.inputTokens} in / ${event.response.usage.outputTokens} out`,
            'dim'
          ));
        }
        break;

      case 'tool.start':
        console.log(c(`\n🔧 Tool: ${event.tool}`, 'cyan'));
        const argsStr = JSON.stringify(event.args, null, 2).split('\n').join('\n   ');
        console.log(c(`   Args: ${argsStr}`, 'dim'));
        break;

      case 'tool.complete':
        const output = String(event.result).split('\n')[0].slice(0, 200);
        console.log(c(`   ✓ ${output}${String(event.result).length > 200 ? '...' : ''}`, 'green'));
        break;

      case 'tool.blocked':
        console.log(c(`   ❌ Blocked: ${event.reason}`, 'red'));
        break;

      case 'approval.required':
        console.log(c(`\n⚠️  Approval required: ${event.request.action}`, 'yellow'));
        break;

      case 'reflection':
        console.log(c(`\n🔍 Reflection (attempt ${event.attempt}): ${event.satisfied ? 'satisfied' : 'refining'}`, 'magenta'));
        break;

      case 'memory.retrieved':
        console.log(c(`\n🧠 Retrieved ${event.count} relevant memories`, 'blue'));
        break;

      case 'react.thought':
        console.log(c(`\n💭 Thought ${event.step}: ${event.thought}`, 'cyan'));
        break;

      case 'react.action':
        console.log(c(`   🎯 Action: ${event.action}`, 'yellow'));
        break;

      case 'react.observation':
        console.log(c(`   👁 Observation: ${event.observation.slice(0, 100)}...`, 'dim'));
        break;

      case 'react.answer':
        console.log(c(`\n✅ Answer: ${event.answer}`, 'green'));
        break;

      case 'multiagent.spawn':
        console.log(c(`\n🤖 Spawning agent: ${event.role} (${event.agentId})`, 'magenta'));
        break;

      case 'multiagent.complete':
        console.log(c(`   ${event.success ? '✓' : '✗'} Agent ${event.agentId} finished`, event.success ? 'green' : 'red'));
        break;

      case 'agent.spawn':
        console.log(c(`\n🚀 Spawning subagent: ${(event as any).name || event.agentId}`, 'magenta'));
        if ((event as any).task) {
          console.log(c(`   Task: ${(event as any).task}`, 'dim'));
        }
        break;

      case 'agent.complete':
        console.log(c(`   ${event.success ? '✓' : '✗'} Subagent ${event.agentId} finished`, event.success ? 'green' : 'red'));
        break;

      case 'agent.error':
        console.log(c(`   ⚠️ Subagent error: ${(event as any).error}`, 'yellow'));
        break;

      case 'agent.registered':
        console.log(c(`   ✓ Agent registered: ${(event as any).name}`, 'green'));
        break;

      case 'consensus.start':
        console.log(c(`\n🗳 Building consensus (${event.strategy})...`, 'blue'));
        break;

      case 'consensus.reached':
        console.log(c(`   ${event.agreed ? '✓' : '✗'} Consensus: ${event.result.slice(0, 100)}`, event.agreed ? 'green' : 'yellow'));
        break;

      case 'checkpoint.created':
        console.log(c(`\n💾 Checkpoint: ${event.label || event.checkpointId}`, 'blue'));
        break;

      case 'checkpoint.restored':
        console.log(c(`\n⏪ Restored checkpoint: ${event.checkpointId}`, 'yellow'));
        break;

      case 'rollback':
        console.log(c(`\n⏪ Rolled back ${event.steps} steps`, 'yellow'));
        break;

      case 'thread.forked':
        console.log(c(`\n🌿 Forked thread: ${event.threadId}`, 'cyan'));
        break;

      case 'error':
        console.log(c(`\n❌ Error: ${event.error}`, 'red'));
        break;

      case 'complete':
        console.log(c(`\n✅ Task ${event.result.success ? 'completed' : 'failed'}`, event.result.success ? 'green' : 'red'));
        break;
    }
  };
}

/**
 * Create a juncture logger that captures critical moments from agent events.
 * Requires a SQLite store to persist junctures.
 */
function createJunctureLogger(store: SQLiteStore) {
  return (event: AgentEvent): void => {
    switch (event.type) {
      case 'tool.blocked':
        store.logJuncture('failure', `Tool blocked: ${(event as any).tool || 'unknown'}`, {
          outcome: (event as any).reason,
          importance: 2,
        });
        break;

      case 'agent.error':
        store.logJuncture('failure', `Subagent error: ${(event as any).agentId}`, {
          outcome: String((event as any).error),
          importance: 1,
        });
        break;

      case 'error':
        store.logJuncture('failure', `Error: ${(event as any).error}`, {
          importance: 1,
        });
        break;

      case 'complete':
        if (!event.result.success) {
          store.logJuncture('failure', 'Task failed', {
            outcome: (event.result as any).output?.slice(0, 200) || 'No output',
            importance: 1,
          });
        }
        break;

      case 'reflection':
        // Log when reflection requires multiple attempts (indicates difficulty)
        if ((event as any).attempt > 2) {
          store.logJuncture('pivot', `Reflection required ${(event as any).attempt} attempts`, {
            outcome: (event as any).satisfied ? 'resolved' : 'ongoing',
            importance: 3,
          });
        }
        break;
    }
  };
}

// =============================================================================
// MAIN REPL
// =============================================================================

async function startProductionREPL(
  provider: LLMProviderWithTools,
  options: {
    permissionMode?: PermissionMode;
    maxIterations?: number;
    model?: string;
    trace?: boolean;
  } = {}
): Promise<void> {
  const {
    permissionMode = 'interactive',
    maxIterations = 50,
    model,
    trace = false,
  } = options;

  // Create readline interface
  const rl = readline.createInterface({ input: stdin, output: stdout });

  // Create tool registry and convert to production format
  const registry = createStandardRegistry(permissionMode);
  const tools = convertToolsFromRegistry(registry);

  // Create provider adapter
  const adaptedProvider = new ProviderAdapter(provider, model);

  // Create MCP client early so we can use it for lazy-loading tool resolution
  // Uses hierarchical config: global (~/.config/attocode/mcp.json) + workspace (.mcp.json)
  const mcpClient = await createMCPClient({
    configPaths: getMCPConfigPaths(),
    lazyLoading: true,  // Enable lazy loading by default
    alwaysLoadTools: [], // No tools always loaded - use search on-demand
    summaryDescriptionLimit: 100,
    maxToolsPerSearch: 5,
  });

  // Get MCP tool summaries (lightweight: name + description only)
  const mcpSummaries = mcpClient.getAllToolSummaries().map(s => ({
    name: s.name,
    description: s.description,
  }));

  // Create the production agent with tool resolver for MCP auto-loading
  const agent = createProductionAgent({
    // Tool resolver: auto-loads MCP tools when the model tries to use them
    // This way the model doesn't need to explicitly search - just call the tool
    toolResolver: (toolName: string) => {
      if (toolName.startsWith('mcp_')) {
        return mcpClient.getFullToolDefinition(toolName);
      }
      return null;
    },
    // MCP tool summaries for system prompt - model can see what's available
    mcpToolSummaries: mcpSummaries,
    provider: adaptedProvider,
    tools,
    model,
    maxIterations,
    // Enable all features
    memory: {
      enabled: true,
      types: { episodic: true, semantic: true, working: true },
      retrievalStrategy: 'hybrid',
      retrievalLimit: 10,
    },
    planning: {
      enabled: true,
      autoplan: true,
      complexityThreshold: 6,
      maxDepth: 3,
      allowReplan: true,
    },
    reflection: {
      enabled: true,
      autoReflect: false, // Enable via /reflect command
      maxAttempts: 3,
      confidenceThreshold: 0.8,
    },
    observability: {
      enabled: true,
      tracing: { enabled: true, serviceName: 'production-agent', exporter: 'console' },
      metrics: { enabled: true, collectTokens: true, collectCosts: true, collectLatencies: true },
      logging: { enabled: false }, // Disable to avoid cluttering REPL
      // Lesson 26: Full trace capture (enable with --trace flag)
      traceCapture: trace ? {
        enabled: true,
        outputDir: '.traces',
        captureMessageContent: true,
        captureToolResults: true,
        analyzeCacheBoundaries: true,
      } : undefined,
    },
    sandbox: {
      enabled: true,
      isolation: 'process',
      allowedCommands: ['node', 'npm', 'npx', 'yarn', 'git', 'ls', 'cat', 'head', 'tail', 'grep', 'find', 'echo', 'pwd'],
      blockedCommands: ['rm -rf /', 'sudo', 'chmod 777'],
      resourceLimits: { timeout: 60000 },
      // Allow reading from user's home directory by default for codebase analysis
      allowedPaths: [
        process.cwd(),
        process.env.HOME || '/Users',
        '/tmp',
      ],
    },
    humanInLoop: {
      enabled: permissionMode === 'interactive',
      riskThreshold: 'high',
      alwaysApprove: ['delete_file', 'rm'],
      neverApprove: ['read_file', 'list_files', 'glob', 'grep'],
      approvalHandler: createInteractiveApprovalHandler(rl),
      auditLog: true,
    },
    executionPolicy: {
      enabled: true,
      defaultPolicy: 'prompt',
      toolPolicies: {
        read_file: { policy: 'allow' },
        list_files: { policy: 'allow' },
        glob: { policy: 'allow' },
        grep: { policy: 'allow' },
      },
      intentAware: true,
      intentConfidenceThreshold: 0.7,
    },
    threads: {
      enabled: true,
      autoCheckpoint: true,
      checkpointFrequency: 5,
      maxCheckpoints: 10,
      enableRollback: true,
      enableForking: true,
    },
    multiAgent: {
      enabled: true,
      roles: [
        {
          name: 'researcher',
          description: 'Explores codebases and gathers information',
          systemPrompt: 'You are a code researcher. Your job is to explore codebases, find relevant files, and summarize information.',
          capabilities: ['read_file', 'list_files', 'glob', 'grep'],
          authority: 1,
        },
        {
          name: 'coder',
          description: 'Writes and modifies code',
          systemPrompt: 'You are a coder. Your job is to write clean, well-documented code.',
          capabilities: ['read_file', 'write_file', 'edit_file', 'bash'],
          authority: 2,
        },
        {
          name: 'reviewer',
          description: 'Reviews code for quality and issues',
          systemPrompt: 'You are a code reviewer. Your job is to find bugs, security issues, and suggest improvements.',
          capabilities: ['read_file', 'grep', 'glob'],
          authority: 2,
        },
        {
          name: 'architect',
          description: 'Designs system architecture',
          systemPrompt: 'You are a software architect. Your job is to design scalable, maintainable systems.',
          capabilities: ['read_file', 'list_files', 'glob'],
          authority: 3,
        },
      ],
      consensusStrategy: 'voting',
    },
    react: {
      enabled: true,
      maxSteps: 15,
      stopOnAnswer: true,
      includeReasoning: true,
    },
    hooks: { enabled: true },
    plugins: { enabled: true },
    // LSP integration for code intelligence and diagnostics
    lsp: {
      enabled: true,
      autoDetect: true, // Auto-detect and start language servers based on file types
    },
  });

  // Subscribe to events
  agent.subscribe(createEventDisplay());

  // Initialize session storage (try SQLite, fall back to JSONL if native module fails)
  let sessionStore: AnySessionStore;
  let usingSQLite = false;
  persistenceDebug.log('Initializing session store', { baseDir: '.agent/sessions' });
  try {
    sessionStore = await createSQLiteStore({ baseDir: '.agent/sessions' });
    usingSQLite = true;
    persistenceDebug.log('SQLite store created successfully');
    console.log(c('✓ SQLite session store initialized', 'green'));

    // Debug: verify SQLite tables
    if (persistenceDebug.isEnabled()) {
      const sqliteStore = sessionStore as SQLiteStore;
      const stats = sqliteStore.getStats();
      persistenceDebug.log('SQLite store stats', stats);
    }

    // Subscribe juncture logger for automatic failure tracking
    agent.subscribe(createJunctureLogger(sessionStore as SQLiteStore));
  } catch (sqliteError) {
    persistenceDebug.error('SQLite initialization failed', sqliteError);
    console.log(c('⚠️  SQLite unavailable, using JSONL fallback', 'yellow'));
    console.log(c(`   Error: ${(sqliteError as Error).message}`, 'dim'));
    sessionStore = await createSessionStore({ baseDir: '.agent/sessions' });
    persistenceDebug.log('JSONL store created as fallback');
  }
  // mcpClient was created earlier for toolResolver
  const compactor = createCompactor(adaptedProvider, {
    tokenThreshold: 80000,
    preserveRecentCount: 10,
  });

  // Initialize TUI for colored code output
  const tui = await createTUIRenderer({
    showToolCalls: true,
    showThinking: false,
    showStreaming: true,
  });
  await tui.init();

  // Register cleanup resources for graceful shutdown on process errors
  registerCleanupResource('rl', rl);
  registerCleanupResource('mcpClient', mcpClient);
  registerCleanupResource('agent', agent);
  registerCleanupResource('tui', tui);

  // Add MCP meta-tools for dynamic tool discovery
  // These enable the agent to search and load tools on-demand
  const mcpMetaTools = createMCPMetaTools(mcpClient, {
    autoLoad: true,
    defaultLimit: 5,
    // Callback when tools are dynamically loaded via search
    onToolsLoaded: (loadedTools) => {
      for (const tool of loadedTools) {
        agent.addTool(tool);
      }
      console.log(c(`  ✓ Dynamically loaded ${loadedTools.length} MCP tool(s)`, 'dim'));
    },
  });

  for (const metaTool of mcpMetaTools) {
    agent.addTool(metaTool);
  }

  // In lazy loading mode, DON'T add all MCP tools upfront
  // Instead, the agent uses mcp_tool_search to find and load tools on-demand
  // This saves ~83% context tokens (summaries vs full schemas)

  // Show MCP status
  const mcpServers = mcpClient.listServers();
  if (mcpServers.length > 0) {
    console.log(c(`MCP Servers: ${mcpServers.length} configured`, 'dim'));
    for (const srv of mcpServers) {
      const icon = srv.status === 'connected' ? '✓' : srv.status === 'error' ? '✗' : '○';
      console.log(c(`  ${icon} ${srv.name} (${srv.status})${srv.toolCount > 0 ? ` - ${srv.toolCount} tools` : ''}`, 'dim'));
    }
  }

  // Check for existing sessions to offer resume
  let sessionId: string;
  let resumedSession = false;

  const existingSessions = await sessionStore.listSessions();
  persistenceDebug.log('Checking existing sessions', { count: existingSessions.length });

  if (existingSessions.length > 0) {
    // Show quick picker (most recent session)
    const pickerResult = await showQuickPicker(existingSessions);

    if (pickerResult.action === 'cancel') {
      // User typed 'list' - show full picker
      const fullResult = await showSessionPicker(existingSessions);

      if (fullResult.action === 'resume' && fullResult.sessionId) {
        sessionId = fullResult.sessionId;
        resumedSession = true;
      } else if (fullResult.action === 'cancel') {
        console.log(c('Goodbye! 👋', 'cyan'));
        await mcpClient.cleanup();
        await agent.cleanup();
        tui.cleanup();
        rl.close();
        return;
      } else {
        sessionId = await sessionStore.createSession();
      }
    } else if (pickerResult.action === 'resume' && pickerResult.sessionId) {
      sessionId = pickerResult.sessionId;
      resumedSession = true;
    } else {
      sessionId = await sessionStore.createSession();
    }
  } else {
    // No existing sessions - create new
    sessionId = await sessionStore.createSession();
  }

  persistenceDebug.log('Session selected', {
    sessionId,
    resumed: resumedSession,
    storeType: persistenceDebug.storeType(sessionStore),
  });

  // CRITICAL: Sync the session ID to the store's internal state
  // This is necessary for resumption because sessionStore.createSession()
  // sets this internally, but resumption only returns the ID.
  sessionStore.setCurrentSessionId(sessionId);

  // If resuming, load the session state
  if (resumedSession) {
    const sessionState = await loadSessionState(sessionStore, sessionId);
    if (sessionState?.messages) {
      agent.loadState({
        messages: sessionState.messages as any,
        iteration: sessionState.iteration,
        metrics: sessionState.metrics as any,
        plan: sessionState.plan as any,
        memoryContext: sessionState.memoryContext,
      });
      console.log(c(`✓ Resumed ${sessionState.messages.length} messages from session`, 'green'));
    }
  }

  // Welcome banner (simplified)
  console.log(`
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('                    ATTOCODE - PRODUCTION CODING AGENT', 'bold')}
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
`);
  console.log(c(`Session: ${sessionId}${resumedSession ? ' (resumed)' : ''}`, 'dim'));
  console.log(c(`Model: ${model || provider.defaultModel}`, 'dim'));
  console.log(c(`Permission mode: ${permissionMode}`, 'dim'));
  console.log(c('\nType your request, or /help for commands.\n', 'dim'));

  try {
    while (true) {
      const input = await rl.question(c('You: ', 'green'));
      const trimmed = input.trim();

      if (!trimmed) continue;

      // Commands
      if (trimmed.startsWith('/')) {
        const [cmd, ...args] = trimmed.split(/\s+/);
        const handled = await handleCommand(cmd.toLowerCase(), args, agent, sessionId, rl, {
          sessionStore,
          mcpClient,
          compactor,
        });
        if (handled === 'quit') {
          console.log(c('Goodbye! 👋', 'cyan'));
          break;
        }
        continue;
      }

      // Run agent
      try {
        const result = await agent.run(trimmed);

        if (result.success) {
          console.log(c('\n━━━ Assistant ━━━', 'magenta'));
          // Use TUI for formatted code output
          tui.renderAssistantMessage(result.response);
          console.log(c('━━━━━━━━━━━━━━━━━', 'magenta'));
        } else {
          console.log(c('\n⚠️ Task incomplete:', 'yellow'));
          tui.showError(result.error || result.response);
        }

        // Show trace info if enabled (Lesson 26)
        if (trace && agent.getTraceCollector()) {
          console.log(c('📊 Trace captured → .traces/', 'dim'));
        }

        // Show metrics
        const metrics = result.metrics;
        console.log(c(`\n📊 Tokens: ${metrics.inputTokens} in / ${metrics.outputTokens} out | Tools: ${metrics.toolCalls} | Duration: ${metrics.duration}ms`, 'dim'));

        // Auto-checkpoint after Q&A cycle (force=true for every Q&A)
        persistenceDebug.log('Attempting auto-checkpoint');
        const checkpoint = agent.autoCheckpoint(true);
        if (checkpoint) {
          console.log(c(`💾 Auto-checkpoint: ${checkpoint.id}`, 'dim'));
          persistenceDebug.log('Auto-checkpoint created in agent', {
            id: checkpoint.id,
            label: checkpoint.label,
            messageCount: checkpoint.state.messages?.length ?? 0,
            iteration: checkpoint.state.iteration,
          });

          // Persist checkpoint to session store for cross-session recovery
          try {
            saveCheckpointToStore(sessionStore, {
              id: checkpoint.id,
              label: checkpoint.label,
              messages: checkpoint.state.messages,
              iteration: checkpoint.state.iteration,
              metrics: checkpoint.state.metrics,
              plan: checkpoint.state.plan,
              memoryContext: checkpoint.state.memoryContext,
            });
          } catch (err) {
            // Log error in debug mode, otherwise silent
            persistenceDebug.error('Failed to persist checkpoint to store', err);
            if (persistenceDebug.isEnabled()) {
              console.log(c(`⚠️  Checkpoint persistence failed: ${(err as Error).message}`, 'yellow'));
            }
          }
        } else {
          persistenceDebug.log('No checkpoint created (autoCheckpoint returned null)');
        }

      } catch (error) {
        tui.showError((error as Error).message);
      }

      console.log();
    }
  } finally {
    // Cleanup all resources
    tui.cleanup();
    await mcpClient.cleanup();
    await agent.cleanup();
    rl.close();
  }
}

// =============================================================================
// COMMAND HANDLER
// =============================================================================

async function handleCommand(
  cmd: string,
  args: string[],
  agent: ProductionAgent,
  sessionId: string,
  rl: readline.Interface,
  integrations: {
    sessionStore: AnySessionStore;
    mcpClient: MCPClient;
    compactor: Compactor;
  }
): Promise<string | void> {
  const { sessionStore, mcpClient, compactor } = integrations;
  switch (cmd) {
    case '/quit':
    case '/exit':
    case '/q':
      return 'quit';

    case '/help':
    case '/h':
      console.log(`
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('                           ATTOCODE HELP', 'bold')}
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}

${c('GENERAL', 'bold')}
  ${c('/help', 'cyan')}              Show this help (alias: /h, /?)
  ${c('/status', 'cyan')}            Show session stats, metrics & token usage
  ${c('/clear', 'cyan')}             Clear the screen
  ${c('/reset', 'cyan')}             Reset agent state (clears conversation)
  ${c('/quit', 'cyan')}              Exit attocode (alias: /exit, /q)

${c('SESSIONS & PERSISTENCE', 'bold')}
  ${c('/save', 'cyan')}              Save current session to disk
  ${c('/load <id>', 'cyan')}         Load a previous session by ID
  ${c('/sessions', 'cyan')}          List all saved sessions with timestamps
  ${c('/resume', 'cyan')}            Resume most recent session (auto-loads last checkpoint)

  ${c('Note:', 'dim')} Sessions auto-save after each Q&A with checkpoints for recovery.

${c('CONTEXT MANAGEMENT', 'bold')}
  ${c('/context', 'cyan')}           Show context window usage (tokens used/available)
  ${c('/context breakdown', 'cyan')} Detailed token breakdown by category
  ${c('/compact', 'cyan')}           Summarize & compress context to free tokens
  ${c('/compact status', 'cyan')}    Check if compaction is recommended

${c('CHECKPOINTS & THREADS', 'bold')}
  ${c('/checkpoint [label]', 'cyan')} Create a named checkpoint (alias: /cp)
  ${c('/checkpoints', 'cyan')}       List all checkpoints (alias: /cps)
  ${c('/restore <id>', 'cyan')}      Restore conversation to a checkpoint
  ${c('/rollback [n]', 'cyan')}      Rollback n steps (default: 1) (alias: /rb)
  ${c('/fork <name>', 'cyan')}       Fork conversation into a new thread
  ${c('/threads', 'cyan')}           List all conversation threads
  ${c('/switch <id>', 'cyan')}       Switch to a different thread

  ${c('Note:', 'dim')} Auto-checkpoint runs after every Q&A for recovery.

${c('REASONING MODES', 'bold')}
  ${c('/react <task>', 'cyan')}      Run with ReAct (Reason + Act) pattern
                       Explicit think → act → observe loop
  ${c('/team <task>', 'cyan')}       Run with multi-agent team coordination
                       Spawns specialized agents for subtasks

${c('SUBAGENTS', 'bold')}
  ${c('/agents', 'cyan')}            List all available agents with descriptions
  ${c('/spawn <agent> <task>', 'cyan')} Spawn a specific agent to handle task
  ${c('/find <query>', 'cyan')}      Find agents by keyword search
  ${c('/suggest <task>', 'cyan')}    AI-powered agent suggestion for task
  ${c('/auto <task>', 'cyan')}       Auto-route task to best agent

${c('MCP INTEGRATION', 'bold')}
  ${c('/mcp', 'cyan')}               List MCP servers and connection status
  ${c('/mcp connect <name>', 'cyan')} Connect to an MCP server
  ${c('/mcp disconnect <name>', 'cyan')} Disconnect from server
  ${c('/mcp tools', 'cyan')}         List all available MCP tools
  ${c('/mcp search <query>', 'cyan')} Search & lazy-load MCP tools
  ${c('/mcp stats', 'cyan')}         Show MCP context usage statistics

${c('BUDGET & ECONOMICS', 'bold')}
  ${c('/budget', 'cyan')}            Show token/cost budget and usage
  ${c('/extend <type> <n>', 'cyan')} Extend budget limit
                       Types: tokens, cost, time
                       Example: /extend tokens 50000

${c('PERMISSIONS & SECURITY', 'bold')}
  ${c('/grants', 'cyan')}            Show active permission grants
  ${c('/audit', 'cyan')}             Show security audit log

${c('DEBUGGING & TESTING', 'bold')}
  ${c('/skills', 'cyan')}            List loaded skills
  ${c('/sandbox', 'cyan')}           Show sandbox modes available
  ${c('/sandbox test', 'cyan')}      Test sandbox execution
  ${c('/shell', 'cyan')}             Show PTY shell integration info
  ${c('/shell test', 'cyan')}        Test persistent shell
  ${c('/lsp', 'cyan')}               Show LSP integration status
  ${c('/tui', 'cyan')}               Show TUI features & capabilities

${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('FEATURES ENABLED', 'bold')}
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
  ${c('✓', 'green')} Auto-Checkpoint   After every Q&A, persisted to session files
  ${c('✓', 'green')} Memory System     Remembers past interactions across sessions
  ${c('✓', 'green')} Planning          Auto-plans complex multi-step tasks
  ${c('✓', 'green')} Reflection        Self-critique and improvement
  ${c('✓', 'green')} Multi-Agent       Team coordination via /team
  ${c('✓', 'green')} ReAct             Explicit reasoning via /react
  ${c('✓', 'green')} Observability     Token/cost tracking & tracing
  ${c('✓', 'green')} Sandboxing        Safe code execution
  ${c('✓', 'green')} Human-in-Loop     Permission approval workflow
  ${c('✓', 'green')} Execution Policy  Intent-aware access control
  ${c('✓', 'green')} Thread Management Fork/rollback conversations
  ${c('✓', 'green')} Token Budget      Smart execution limits
  ${c('✓', 'green')} Subagents         Specialized agent spawning
  ${c('✓', 'green')} MCP Integration   External tools via Model Context Protocol
  ${c('✓', 'green')} Lazy Loading      On-demand MCP tool schema loading
  ${c('✓', 'green')} Session Persist   Auto-save/load with JSONL format
  ${c('✓', 'green')} Context Compact   Auto-summarize long contexts
  ${c('✓', 'green')} Skills System     Reusable prompts & workflows
  ${c('✓', 'green')} PTY Shell         Persistent shell state
  ${c('✓', 'green')} TUI               Syntax highlighted output
  ${c('✓', 'green')} Goal Tracking     Persistent goals via /goals

${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('SHORTCUTS', 'bold')}
  ${c('Ctrl+C', 'yellow')}  Exit          ${c('Ctrl+L', 'yellow')}  Clear screen
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
`);
      break;

    case '/status':
      const metrics = agent.getMetrics();
      const state = agent.getState();

      // Get goals summary if SQLite store
      let goalsSummary = '';
      if ('listActiveGoals' in sessionStore) {
        const sqlStore = sessionStore as SQLiteStore;
        const activeGoals = sqlStore.listActiveGoals();
        if (activeGoals.length > 0) {
          // Calculate overall progress
          let totalCurrent = 0;
          let totalExpected = 0;
          const goalLines: string[] = [];

          for (const goal of activeGoals) {
            if (goal.progressTotal) {
              totalCurrent += goal.progressCurrent;
              totalExpected += goal.progressTotal;
              const pct = Math.round((goal.progressCurrent / goal.progressTotal) * 100);
              goalLines.push(`  • ${goal.goalText} (${goal.progressCurrent}/${goal.progressTotal} - ${pct}%)`);
            } else {
              goalLines.push(`  • ${goal.goalText}`);
            }
          }

          goalsSummary = `\n${c('Active Goals:', 'bold')} (${activeGoals.length})`;
          if (totalExpected > 0) {
            const overallPct = Math.round((totalCurrent / totalExpected) * 100);
            goalsSummary += c(` [Overall: ${overallPct}%]`, 'cyan');
          }
          goalsSummary += '\n' + goalLines.slice(0, 5).join('\n');
          if (activeGoals.length > 5) {
            goalsSummary += c(`\n  ... and ${activeGoals.length - 5} more`, 'dim');
          }
        }
      }

      console.log(`
${c('Session Status:', 'bold')}
  Session ID:      ${sessionId}
  Status:          ${state.status}
  Iteration:       ${state.iteration}
  Messages:        ${state.messages.length}

${c('Token Usage:', 'bold')}
  Input tokens:    ${metrics.inputTokens.toLocaleString()}
  Output tokens:   ${metrics.outputTokens.toLocaleString()}
  Total tokens:    ${metrics.totalTokens.toLocaleString()}

${c('Activity:', 'bold')}
  LLM calls:       ${metrics.llmCalls}
  Tool calls:      ${metrics.toolCalls}
  Duration:        ${metrics.duration}ms
  Est. Cost:       $${metrics.estimatedCost.toFixed(4)}
${goalsSummary}`);
      break;

    case '/goals':
      // Goal management commands
      if ('listActiveGoals' in sessionStore) {
        const sqliteStore = sessionStore as SQLiteStore;
        const subCmd = args[0]?.toLowerCase();

        if (!subCmd || subCmd === 'list') {
          // List active goals
          const goals = sqliteStore.listActiveGoals();
          if (goals.length === 0) {
            console.log(c('No active goals. Use /goals add <text> to create one.', 'dim'));
          } else {
            console.log(c('\nActive Goals:', 'bold'));
            for (const goal of goals) {
              const progress = goal.progressTotal
                ? ` (${goal.progressCurrent}/${goal.progressTotal})`
                : '';
              const priority = goal.priority === 1 ? c(' [HIGH]', 'red') :
                              goal.priority === 3 ? c(' [low]', 'dim') : '';
              console.log(`  • ${goal.goalText}${progress}${priority}`);
              console.log(c(`    ID: ${goal.id}`, 'dim'));
            }
            console.log('');
          }
        } else if (subCmd === 'add' && args.length > 1) {
          // Add new goal
          const goalText = args.slice(1).join(' ');
          const goalId = sqliteStore.createGoal(goalText);
          console.log(c(`✓ Goal created: ${goalId}`, 'green'));
        } else if (subCmd === 'done' && args[1]) {
          // Complete a goal
          sqliteStore.completeGoal(args[1]);
          console.log(c(`✓ Goal completed: ${args[1]}`, 'green'));
        } else if (subCmd === 'progress' && args[1] && args[2] && args[3]) {
          // Update progress: /goals progress <id> <current> <total>
          sqliteStore.updateGoal(args[1], {
            progressCurrent: parseInt(args[2], 10),
            progressTotal: parseInt(args[3], 10),
          });
          console.log(c(`✓ Progress updated: ${args[2]}/${args[3]}`, 'green'));
        } else if (subCmd === 'all') {
          // List all goals including completed
          const goals = sqliteStore.listGoals();
          console.log(c('\nAll Goals:', 'bold'));
          for (const goal of goals) {
            const status = goal.status === 'completed' ? c('✓', 'green') :
                          goal.status === 'abandoned' ? c('✗', 'red') : ' ';
            console.log(`  ${status} ${goal.goalText} [${goal.status}]`);
          }
          console.log('');
        } else if (subCmd === 'junctures') {
          // Show recent junctures
          const junctures = sqliteStore.listJunctures(undefined, 10);
          if (junctures.length === 0) {
            console.log(c('No junctures logged yet.', 'dim'));
          } else {
            console.log(c('\nRecent Key Moments:', 'bold'));
            for (const j of junctures) {
              const icon = j.type === 'failure' ? c('✗', 'red') :
                          j.type === 'breakthrough' ? c('★', 'yellow') :
                          j.type === 'decision' ? c('→', 'cyan') : c('↻', 'magenta');
              console.log(`  ${icon} [${j.type}] ${j.description}`);
              if (j.outcome) console.log(c(`     └─ ${j.outcome}`, 'dim'));
            }
            console.log('');
          }
        } else {
          console.log(c('Usage:', 'bold'));
          console.log(c('  /goals              - List active goals', 'dim'));
          console.log(c('  /goals add <text>   - Create a new goal', 'dim'));
          console.log(c('  /goals done <id>    - Mark goal as completed', 'dim'));
          console.log(c('  /goals progress <id> <current> <total> - Update progress', 'dim'));
          console.log(c('  /goals all          - List all goals (including completed)', 'dim'));
          console.log(c('  /goals junctures    - Show recent key moments', 'dim'));
        }
      } else {
        console.log(c('Goals require SQLite store (not available with JSONL fallback)', 'yellow'));
      }
      break;

    case '/handoff':
      // Export session for handoff to another agent or human
      if ('exportSessionManifest' in sessionStore) {
        const sqliteStore = sessionStore as SQLiteStore;
        const format = args[0]?.toLowerCase() || 'markdown';

        if (format === 'json') {
          const manifest = sqliteStore.exportSessionManifest();
          if (manifest) {
            console.log(JSON.stringify(manifest, null, 2));
          } else {
            console.log(c('No active session to export', 'yellow'));
          }
        } else {
          // Default: markdown format
          const markdown = sqliteStore.exportSessionMarkdown();
          console.log(markdown);
        }
      } else {
        console.log(c('Handoff requires SQLite store (not available with JSONL fallback)', 'yellow'));
      }
      break;

    case '/theme':
      try {
        const { getThemeNames, getTheme } = await import('./tui/theme/index.js');
        const themes = getThemeNames();

        if (args.length === 0) {
          console.log(`
${c('Available Themes:', 'bold')}
${themes.map(t => `  ${c(t, 'cyan')}`).join('\n')}

${c('Usage:', 'dim')} /theme <name>
${c('Note:', 'dim')} Theme switching is visual in TUI mode. REPL mode uses fixed ANSI colors.
`);
        } else {
          const themeName = args[0];
          if (themes.includes(themeName)) {
            const selectedTheme = getTheme(themeName as 'dark' | 'light' | 'high-contrast' | 'auto');
            console.log(c(`✓ Theme set to: ${themeName}`, 'green'));
            console.log(c(`  Primary: ${selectedTheme.colors.primary}`, 'dim'));
            console.log(c(`  Note: Full theme support requires TUI mode`, 'dim'));
          } else {
            console.log(c(`Unknown theme: ${themeName}`, 'red'));
            console.log(c(`Available: ${themes.join(', ')}`, 'dim'));
          }
        }
      } catch (error) {
        console.log(c(`Error loading themes: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/react':
      if (args.length === 0) {
        console.log(c('Usage: /react <task>', 'yellow'));
      } else {
        const task = args.join(' ');
        console.log(c(`\n🧠 Running with ReAct pattern: ${task}`, 'cyan'));
        try {
          const trace = await agent.runWithReAct(task);
          console.log(c('\n━━━ ReAct Trace ━━━', 'magenta'));
          console.log(agent.formatReActTrace(trace));
          console.log(c('━━━━━━━━━━━━━━━━━━━', 'magenta'));
        } catch (error) {
          console.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/team':
      if (args.length === 0) {
        console.log(c('Usage: /team <task>', 'yellow'));
      } else {
        const task = args.join(' ');
        console.log(c(`\n👥 Running with team: ${task}`, 'cyan'));
        try {
          // Import built-in roles
          const { CODER_ROLE, REVIEWER_ROLE, RESEARCHER_ROLE, ARCHITECT_ROLE } = await import('./integrations/multi-agent.js');
          const result = await agent.runWithTeam(
            { id: `team-${Date.now()}`, goal: task, context: '' },
            [RESEARCHER_ROLE, CODER_ROLE, REVIEWER_ROLE]
          );
          console.log(c('\n━━━ Team Result ━━━', 'magenta'));
          console.log(`Success: ${result.success}`);
          console.log(`Coordinator: ${result.coordinator}`);
          if (result.consensus) {
            console.log(`Consensus: ${result.consensus.agreed ? 'Agreed' : 'Disagreed'} - ${result.consensus.result}`);
          }
          console.log(c('━━━━━━━━━━━━━━━━━━━', 'magenta'));
        } catch (error) {
          console.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/checkpoint':
      try {
        const label = args.length > 0 ? args.join(' ') : undefined;
        const checkpoint = agent.createCheckpoint(label);
        console.log(c(`✓ Checkpoint created: ${checkpoint.id}${label ? ` (${label})` : ''}`, 'green'));
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/checkpoints':
      try {
        const checkpoints = agent.getCheckpoints();
        if (checkpoints.length === 0) {
          console.log(c('No checkpoints.', 'dim'));
        } else {
          console.log(c('\nCheckpoints:', 'bold'));
          checkpoints.forEach(cp => {
            console.log(`  ${c(cp.id, 'cyan')}${cp.label ? ` - ${cp.label}` : ''}`);
          });
        }
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/restore':
      if (args.length === 0) {
        console.log(c('Usage: /restore <checkpoint-id>', 'yellow'));
      } else {
        const success = agent.restoreCheckpoint(args[0]);
        console.log(success ? c(`✓ Restored: ${args[0]}`, 'green') : c(`✗ Not found: ${args[0]}`, 'red'));
      }
      break;

    case '/rollback':
      const steps = args.length > 0 ? parseInt(args[0], 10) : 1;
      if (isNaN(steps) || steps < 1) {
        console.log(c('Usage: /rollback <steps>', 'yellow'));
      } else {
        const success = agent.rollback(steps);
        console.log(success ? c(`✓ Rolled back ${steps} steps`, 'green') : c('✗ Rollback failed', 'red'));
      }
      break;

    case '/fork':
      if (args.length === 0) {
        console.log(c('Usage: /fork <name>', 'yellow'));
      } else {
        try {
          const threadId = agent.fork(args.join(' '));
          console.log(c(`✓ Forked: ${threadId}`, 'green'));
        } catch (error) {
          console.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/threads':
      try {
        const threads = agent.getAllThreads();
        if (threads.length === 0) {
          console.log(c('No threads.', 'dim'));
        } else {
          console.log(c('\nThreads:', 'bold'));
          threads.forEach((t: any) => {
            console.log(`  ${c(t.id, 'cyan')}${t.name ? ` - ${t.name}` : ''} (${t.messages?.length || 0} messages)`);
          });
        }
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/switch':
      if (args.length === 0) {
        console.log(c('Usage: /switch <thread-id>', 'yellow'));
      } else {
        const success = agent.switchThread(args[0]);
        console.log(success ? c(`✓ Switched to: ${args[0]}`, 'green') : c(`✗ Not found: ${args[0]}`, 'red'));
      }
      break;

    case '/grants':
      try {
        const grants = agent.getActiveGrants();
        if (grants.length === 0) {
          console.log(c('No active permission grants.', 'dim'));
        } else {
          console.log(c('\nActive Grants:', 'bold'));
          grants.forEach((g: any) => {
            console.log(`  ${c(g.id, 'cyan')} - ${g.toolName} (${g.grantedBy})`);
          });
        }
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/audit':
      try {
        const log = agent.getAuditLog();
        if (log.length === 0) {
          console.log(c('No audit entries.', 'dim'));
        } else {
          console.log(c('\nAudit Log:', 'bold'));
          log.slice(-10).forEach((entry: any) => {
            const status = entry.approved ? c('✓', 'green') : c('✗', 'red');
            console.log(`  ${status} ${entry.action} - ${entry.tool || 'n/a'}`);
          });
        }
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/clear':
      console.clear();
      console.log(c(`Production Agent - Session: ${sessionId}`, 'cyan'));
      break;

    case '/reset':
      agent.reset();
      console.log(c('✓ Agent state reset', 'green'));
      break;

    case '/budget':
      try {
        const usage = agent.getBudgetUsage();
        const limits = agent.getBudgetLimits();
        const progress = agent.getProgress();

        if (!usage || !limits) {
          console.log(c('Economics not available.', 'dim'));
        } else {
          console.log(`
${c('Budget Usage:', 'bold')}
  Tokens:      ${usage.tokens.toLocaleString()} / ${limits.maxTokens.toLocaleString()} (${usage.percentUsed.toFixed(1)}%)
  Cost:        $${usage.cost.toFixed(4)} / $${limits.maxCost.toFixed(2)}
  Duration:    ${Math.round(usage.duration / 1000)}s / ${Math.round(limits.maxDuration / 1000)}s
  Iterations:  ${usage.iterations} / ${limits.maxIterations}

${c('Progress:', 'bold')}
  Files read:     ${progress?.filesRead || 0}
  Files modified: ${progress?.filesModified || 0}
  Commands run:   ${progress?.commandsRun || 0}
  Status:         ${progress?.isStuck ? c('STUCK', 'red') : c('Active', 'green')}
`);
        }
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/extend':
      if (args.length === 0) {
        console.log(c('Usage: /extend <tokens|cost|time> <amount>', 'yellow'));
        console.log(c('  e.g., /extend tokens 100000', 'dim'));
        console.log(c('  e.g., /extend cost 0.5', 'dim'));
        console.log(c('  e.g., /extend time 120 (seconds)', 'dim'));
      } else {
        const [what, amount] = args;
        const value = parseFloat(amount);
        if (isNaN(value)) {
          console.log(c('Invalid amount', 'red'));
        } else {
          const limits = agent.getBudgetLimits();
          if (!limits) {
            console.log(c('Economics not available', 'dim'));
          } else {
            switch (what) {
              case 'tokens':
                agent.extendBudget({ maxTokens: limits.maxTokens + value });
                console.log(c(`✓ Token budget extended to ${(limits.maxTokens + value).toLocaleString()}`, 'green'));
                break;
              case 'cost':
                agent.extendBudget({ maxCost: limits.maxCost + value });
                console.log(c(`✓ Cost budget extended to $${(limits.maxCost + value).toFixed(2)}`, 'green'));
                break;
              case 'time':
                agent.extendBudget({ maxDuration: limits.maxDuration + value * 1000 });
                console.log(c(`✓ Time budget extended to ${Math.round((limits.maxDuration + value * 1000) / 1000)}s`, 'green'));
                break;
              default:
                console.log(c('Unknown budget type. Use: tokens, cost, or time', 'yellow'));
            }
          }
        }
      }
      break;

    case '/agents':
      try {
        const agentList = agent.formatAgentList();
        console.log(c('\nAvailable Agents:', 'bold'));
        console.log(agentList);
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/spawn':
      if (args.length < 2) {
        console.log(c('Usage: /spawn <agent-name> <task>', 'yellow'));
        console.log(c('  e.g., /spawn researcher Find all configuration files', 'dim'));
        console.log(c('  e.g., /spawn coder Add a header comment to main.ts', 'dim'));
      } else {
        const agentName = args[0];
        const task = args.slice(1).join(' ');
        console.log(c(`\n🤖 Spawning ${agentName}: ${task}`, 'cyan'));
        try {
          const result = await agent.spawnAgent(agentName, task);
          console.log(c('\n━━━ Agent Result ━━━', 'magenta'));
          console.log(`Success: ${result.success}`);
          console.log(`Output: ${result.output}`);
          console.log(c(`\n📊 Tokens: ${result.metrics.tokens} | Tools: ${result.metrics.toolCalls} | Duration: ${result.metrics.duration}ms`, 'dim'));
          console.log(c('━━━━━━━━━━━━━━━━━━━', 'magenta'));
        } catch (error) {
          console.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/find':
      if (args.length === 0) {
        console.log(c('Usage: /find <query>', 'yellow'));
        console.log(c('  e.g., /find explore codebase and find files', 'dim'));
        console.log(c('  e.g., /find fix bugs in code', 'dim'));
      } else {
        const query = args.join(' ');
        console.log(c(`\n🔍 Finding agents for: "${query}"`, 'cyan'));
        const matches = agent.findAgentsForTask(query);
        if (matches.length === 0) {
          console.log(c('No matching agents found.', 'dim'));
        } else {
          console.log(c('\nMatching Agents:', 'bold'));
          matches.forEach((a, i) => {
            console.log(`  ${i + 1}. ${c(a.name, 'cyan')} (${a.source})`);
            console.log(`     ${a.description.split('.')[0]}`);
            if (a.capabilities?.length) {
              console.log(c(`     Capabilities: ${a.capabilities.join(', ')}`, 'dim'));
            }
          });
          console.log(c('\nUse /spawn <agent-name> <task> to run an agent.', 'dim'));
        }
      }
      break;

    case '/suggest':
      if (args.length === 0) {
        console.log(c('Usage: /suggest <task description>', 'yellow'));
        console.log(c('  e.g., /suggest find all configuration files in the project', 'dim'));
        console.log(c('  e.g., /suggest review the security of auth.ts', 'dim'));
      } else {
        const taskDesc = args.join(' ');
        console.log(c(`\n🧠 Analyzing task: "${taskDesc}"`, 'cyan'));
        console.log(c('   Using AI to suggest best agent...', 'dim'));
        try {
          const { suggestions, shouldDelegate, delegateAgent } = await agent.suggestAgentForTask(taskDesc);

          if (suggestions.length === 0) {
            console.log(c('\nNo specialized agent recommended. Main agent should handle this task.', 'dim'));
          } else {
            console.log(c('\nAgent Suggestions:', 'bold'));
            suggestions.forEach((s, i) => {
              const confidenceBar = '█'.repeat(Math.round(s.confidence * 10)) + '░'.repeat(10 - Math.round(s.confidence * 10));
              console.log(`  ${i + 1}. ${c(s.agent.name, 'cyan')} [${confidenceBar}] ${(s.confidence * 100).toFixed(0)}%`);
              console.log(`     ${s.reason}`);
            });

            if (shouldDelegate && delegateAgent) {
              console.log(c(`\n💡 Recommendation: Delegate to "${delegateAgent}"`, 'green'));
              console.log(c(`   Run: /spawn ${delegateAgent} ${taskDesc}`, 'dim'));
            } else {
              console.log(c('\n💡 Recommendation: Main agent should handle this task.', 'dim'));
            }
          }
        } catch (error) {
          console.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/auto':
      if (args.length === 0) {
        console.log(c('Usage: /auto <task>', 'yellow'));
        console.log(c('  Automatically routes to the best agent based on task analysis.', 'dim'));
        console.log(c('  e.g., /auto explore the project structure', 'dim'));
      } else {
        const autoTask = args.join(' ');
        console.log(c(`\n🚀 Auto-routing: "${autoTask}"`, 'cyan'));
        try {
          // Create a confirmation callback that asks the user
          const confirmDelegate = async (suggestedAgent: any, reason: string): Promise<boolean> => {
            console.log(c(`\n💡 Suggested agent: ${suggestedAgent.name}`, 'yellow'));
            console.log(c(`   Reason: ${reason}`, 'dim'));
            const answer = await rl.question(c('   Delegate to this agent? (y/n): ', 'yellow'));
            return answer.toLowerCase().startsWith('y');
          };

          const result = await agent.runWithAutoRouting(autoTask, {
            confidenceThreshold: 0.75,
            confirmDelegate,
          });

          // Check if it's a SpawnResult or AgentResult
          if ('output' in result) {
            // SpawnResult from subagent
            console.log(c('\n━━━ Subagent Result ━━━', 'magenta'));
            console.log(`Success: ${result.success}`);
            console.log(result.output);
            console.log(c(`\n📊 Tokens: ${result.metrics.tokens} | Duration: ${result.metrics.duration}ms`, 'dim'));
            console.log(c('━━━━━━━━━━━━━━━━━━━━━━━━', 'magenta'));
          } else {
            // AgentResult from main agent
            console.log(c('\n━━━ Assistant ━━━', 'magenta'));
            console.log(result.response);
            console.log(c('━━━━━━━━━━━━━━━━━', 'magenta'));
            console.log(c(`\n📊 Tokens: ${result.metrics.inputTokens} in / ${result.metrics.outputTokens} out | Tools: ${result.metrics.toolCalls}`, 'dim'));
          }
        } catch (error) {
          console.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    // =========================================================================
    // NEW INTEGRATION COMMANDS
    // =========================================================================

    case '/mcp':
      if (args.length === 0) {
        // List all MCP servers
        const servers = mcpClient.listServers();
        console.log(formatServerList(servers));
      } else if (args[0] === 'connect' && args[1]) {
        // Connect to a server
        console.log(c(`Connecting to ${args[1]}...`, 'cyan'));
        try {
          await mcpClient.connectServer(args[1]);
          console.log(c(`✓ Connected to ${args[1]}`, 'green'));
          // Re-add tools after connecting
          const tools = mcpClient.getAllTools();
          for (const tool of tools) {
            agent.addTool(tool);
          }
          console.log(c(`  Added ${tools.length} tools from MCP servers`, 'dim'));
        } catch (error) {
          console.log(c(`Error: ${(error as Error).message}`, 'red'));
        }
      } else if (args[0] === 'disconnect' && args[1]) {
        // Disconnect from a server
        await mcpClient.disconnectServer(args[1]);
        console.log(c(`✓ Disconnected from ${args[1]}`, 'green'));
      } else if (args[0] === 'tools') {
        // List tools from all servers
        const tools = mcpClient.getAllTools();
        if (tools.length === 0) {
          console.log(c('No MCP tools available.', 'dim'));
        } else {
          console.log(c('\nMCP Tools:', 'bold'));
          tools.forEach(t => {
            const loaded = mcpClient.isToolLoaded(t.name);
            const status = loaded ? c('✓', 'green') : c('○', 'dim');
            console.log(`  ${status} ${c(t.name, 'cyan')} - ${t.description?.slice(0, 60) || 'No description'}...`);
          });
          const stats = mcpClient.getContextStats();
          console.log(c(`\n  Legend: ✓ = full schema loaded, ○ = summary only`, 'dim'));
          console.log(c(`  Loaded: ${stats.loadedCount}/${stats.totalTools} tools`, 'dim'));
        }
      } else if (args[0] === 'search') {
        // Search and load tools dynamically
        const query = args.slice(1).join(' ');
        if (!query) {
          console.log(c('Usage: /mcp search <query>', 'yellow'));
          console.log(c('  e.g., /mcp search browser click', 'dim'));
          console.log(c('  e.g., /mcp search screenshot', 'dim'));
        } else {
          console.log(c(`Searching for: "${query}"...`, 'cyan'));
          const results = mcpClient.searchTools(query, { limit: 10 });
          if (results.length === 0) {
            console.log(c('No matching tools found.', 'dim'));
          } else {
            console.log(c(`\nFound ${results.length} tool(s):`, 'bold'));
            results.forEach(r => {
              console.log(`  ${c(r.name, 'cyan')} (${r.serverName})`);
              console.log(`    ${r.description}`);
            });
            // Auto-load found tools
            const loadedTools = mcpClient.loadTools(results.map(r => r.name));
            for (const tool of loadedTools) {
              agent.addTool(tool);
            }
            console.log(c(`\n✓ Loaded ${loadedTools.length} tool(s). They are now available for use.`, 'green'));
          }
        }
      } else if (args[0] === 'stats') {
        // Show MCP context usage stats
        const stats = mcpClient.getContextStats();
        const fullLoadEstimate = stats.totalTools * 200;
        const currentTokens = stats.summaryTokens + stats.definitionTokens;
        const savingsPercent = fullLoadEstimate > 0
          ? Math.round((1 - currentTokens / fullLoadEstimate) * 100)
          : 0;

        console.log(`
${c('MCP Context Usage:', 'bold')}
  Tool summaries:    ${stats.summaryCount.toString().padStart(3)} tools (~${stats.summaryTokens.toLocaleString()} tokens)
  Full definitions:  ${stats.loadedCount.toString().padStart(3)} tools (~${stats.definitionTokens.toLocaleString()} tokens)
  ─────────────────────────────────────
  Total:             ${stats.totalTools.toString().padStart(3)} tools (~${currentTokens.toLocaleString()} tokens)

  Context savings:   ${savingsPercent}% vs loading all full schemas
  ${savingsPercent > 50 ? c('✓ Good - lazy loading is saving context', 'green') : c('⚠ Consider using lazy loading more', 'yellow')}

${c('Tip:', 'dim')} Use /mcp search <query> to load specific tools on-demand.
`);
      } else {
        console.log(c('Usage:', 'bold'));
        console.log(c('  /mcp                - List servers', 'dim'));
        console.log(c('  /mcp connect <name> - Connect to server', 'dim'));
        console.log(c('  /mcp disconnect <name> - Disconnect', 'dim'));
        console.log(c('  /mcp tools          - List available tools', 'dim'));
        console.log(c('  /mcp search <query> - Search & load tools', 'dim'));
        console.log(c('  /mcp stats          - Show context usage stats', 'dim'));
      }
      break;

    case '/save':
      try {
        const state = agent.getState();
        const metrics = agent.getMetrics();
        const saveCheckpointId = `ckpt-manual-${Date.now().toString(36)}`;

        persistenceDebug.log('/save command - creating checkpoint', {
          checkpointId: saveCheckpointId,
          messageCount: state.messages?.length ?? 0,
        });

        saveCheckpointToStore(sessionStore, {
          id: saveCheckpointId,
          label: 'manual-save',
          messages: state.messages,
          iteration: state.iteration,
          metrics: metrics,
          plan: state.plan,
          memoryContext: state.memoryContext,
        });

        console.log(c(`✓ Session saved: ${sessionId} (checkpoint: ${saveCheckpointId})`, 'green'));
      } catch (error) {
        persistenceDebug.error('/save command failed', error);
        console.log(c(`Error saving session: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/load':
      if (args.length === 0) {
        console.log(c('Usage: /load <session-id>', 'yellow'));
        console.log(c('  Use /sessions to list available sessions', 'dim'));
      } else {
        const loadId = args[0];
        try {
          // Try SQLite's loadLatestCheckpoint first (checkpoints are in separate table)
          let checkpointData: CheckpointData | undefined;
          if ('loadLatestCheckpoint' in sessionStore && typeof sessionStore.loadLatestCheckpoint === 'function') {
            const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(loadId);
            if (sqliteCheckpoint?.state) {
              checkpointData = sqliteCheckpoint.state as unknown as CheckpointData;
            }
          }

          // Fall back to entries-based lookup (for JSONL or if SQLite checkpoint not found)
          if (!checkpointData) {
            const entries = await sessionStore.loadSession(loadId);
            if (entries.length === 0) {
              console.log(c(`No entries found for session: ${loadId}`, 'yellow'));
              break;
            }
            const checkpoint = [...entries].reverse().find(e => e.type === 'checkpoint');
            checkpointData = checkpoint?.data as CheckpointData | undefined;
          }

          if (checkpointData?.messages) {
            // Use loadState for full state restoration
            agent.loadState({
              messages: checkpointData.messages as any,
              iteration: checkpointData.iteration,
              metrics: checkpointData.metrics as any,
              plan: checkpointData.plan as any,
              memoryContext: checkpointData.memoryContext,
            });
            console.log(c(`✓ Loaded ${checkpointData.messages.length} messages from ${loadId}`, 'green'));
          } else {
            console.log(c('No checkpoint found in session', 'yellow'));
          }
        } catch (error) {
          console.log(c(`Error loading session: ${(error as Error).message}`, 'red'));
        }
      }
      break;

    case '/resume':
      try {
        const recentSession = sessionStore.getRecentSession();
        if (!recentSession) {
          console.log(c('No previous sessions found', 'yellow'));
        } else {
          console.log(c(`📂 Found recent session: ${recentSession.id}`, 'dim'));
          console.log(c(`   Created: ${new Date(recentSession.createdAt).toLocaleString()}`, 'dim'));
          console.log(c(`   Messages: ${recentSession.messageCount}`, 'dim'));

          // Try SQLite's loadLatestCheckpoint first (checkpoints are in separate table)
          let resumeCheckpointData: CheckpointData | undefined;
          if ('loadLatestCheckpoint' in sessionStore && typeof sessionStore.loadLatestCheckpoint === 'function') {
            const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(recentSession.id);
            if (sqliteCheckpoint?.state) {
              resumeCheckpointData = sqliteCheckpoint.state as unknown as CheckpointData;
            }
          }

          // Fall back to entries-based lookup (for JSONL or if SQLite checkpoint not found)
          if (!resumeCheckpointData) {
            const entriesResult = sessionStore.loadSession(recentSession.id);
            const entries = Array.isArray(entriesResult) ? entriesResult : await entriesResult;
            const checkpoint = [...entries].reverse().find(e => e.type === 'checkpoint');
            if (checkpoint?.data) {
              resumeCheckpointData = checkpoint.data as CheckpointData;
            } else {
              // No checkpoint, try to load messages directly from entries
              const messages = entries
                .filter((e: { type: string }) => e.type === 'message')
                .map((e: { data: unknown }) => e.data);
              if (messages.length > 0) {
                agent.loadState({ messages: messages as any });
                console.log(c(`✓ Resumed ${messages.length} messages from last session`, 'green'));
              } else {
                console.log(c('No messages found in last session', 'yellow'));
              }
            }
          }

          if (resumeCheckpointData?.messages) {
            // Use loadState for full state restoration
            agent.loadState({
              messages: resumeCheckpointData.messages as any,
              iteration: resumeCheckpointData.iteration,
              metrics: resumeCheckpointData.metrics as any,
              plan: resumeCheckpointData.plan as any,
              memoryContext: resumeCheckpointData.memoryContext,
            });
            console.log(c(`✓ Resumed ${resumeCheckpointData.messages.length} messages from last session`, 'green'));
            if (resumeCheckpointData.iteration) {
              console.log(c(`   Iteration: ${resumeCheckpointData.iteration}`, 'dim'));
            }
            if (resumeCheckpointData.plan) {
              console.log(c(`   Plan restored`, 'dim'));
            }
          }
        }
      } catch (error) {
        console.log(c(`Error resuming session: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/sessions':
      try {
        const sessions = await sessionStore.listSessions();
        console.log(formatSessionsTable(sessions));
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/compact':
      try {
        const state = agent.getState();
        const contextUsage = getContextUsage(state.messages, 80000);

        if (args[0] === 'status') {
          console.log(`
${c('Context Status:', 'bold')}
  Messages:    ${state.messages.length}
  Est. Tokens: ${contextUsage.tokens.toLocaleString()}
  Usage:       ${contextUsage.percent}%
  Threshold:   80%
  Should Compact: ${contextUsage.shouldCompact ? c('Yes', 'yellow') : c('No', 'green')}
`);
        } else {
          if (state.messages.length < 5) {
            console.log(c('Not enough messages to compact.', 'dim'));
          } else {
            console.log(c('Compacting context...', 'cyan'));
            const result = await compactor.compact(state.messages);
            agent.loadMessages(result.preservedMessages);
            console.log(formatCompactionResult(result));
          }
        }
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/context':
      try {
        const state = agent.getState();

        if (args[0] === 'breakdown') {
          // Detailed token breakdown by category
          const mcpContextStats = integrations.mcpClient.getContextStats();
          const mcpServers = integrations.mcpClient.listServers();
          const mcpSummaries = integrations.mcpClient.getAllToolSummaries();

          // Get the actual system prompt (it's built dynamically, not stored in messages until run)
          const systemPromptContent = agent.getSystemPromptWithMode();

          // Token estimation heuristics:
          // ~3.2 chars/token for natural language text
          // ~2.5 chars/token for JSON-heavy content (schemas, tool definitions)
          const estimateTokens = (str: string) => Math.ceil(str.length / 3.2);

          const systemPromptTokens = estimateTokens(systemPromptContent);

          // Calculate actual tokens from MCP stats (respects lazy loading)
          const actualMcpTokens = mcpContextStats.summaryTokens + mcpContextStats.definitionTokens;

          // Server breakdown showing loaded vs total
          const serverBreakdown: { name: string; total: number; loaded: number; tokens: number }[] = [];
          for (const server of mcpServers) {
            if (server.status !== 'connected') continue;

            const serverSummaries = mcpSummaries.filter(s => s.serverName === server.name);
            let loadedCount = 0;
            let serverTokens = 0;

            for (const summary of serverSummaries) {
              const isLoaded = integrations.mcpClient.isToolLoaded(summary.name);
              if (isLoaded) {
                loadedCount++;
                serverTokens += 200; // Estimate for full schema
              } else {
                serverTokens += 50;  // Estimate for summary
              }
            }

            serverBreakdown.push({
              name: server.name,
              total: serverSummaries.length,
              loaded: loadedCount,
              tokens: serverTokens,
            });
          }

          // Sort by tokens descending
          serverBreakdown.sort((a, b) => b.tokens - a.tokens);

          // Recalculate conversation tokens with better heuristic
          const conversationTokens = state.messages
            .filter(m => m.role !== 'system')
            .reduce((sum, m) => sum + estimateTokens(m.content), 0);

          // Agent's own tools (non-MCP)
          const agentTools = agent.getTools().filter(t => !t.name.startsWith('mcp_'));
          const agentToolTokens = agentTools.length * 150; // Estimate

          // Final total (actual tokens used, not hypothetical)
          const totalTokens = systemPromptTokens + actualMcpTokens + agentToolTokens + conversationTokens;

          // Build server breakdown lines
          const serverLines = serverBreakdown.map(s => {
            const pct = actualMcpTokens > 0 ? Math.round((s.tokens / actualMcpTokens) * 100) : 0;
            const status = s.loaded === 0
              ? c('[summaries only]', 'dim')
              : s.loaded === s.total
                ? c('[all loaded]', 'green')
                : c(`[${s.loaded}/${s.total} loaded]`, 'yellow');
            return `      ${s.name.padEnd(15)} ~${s.tokens.toLocaleString().padStart(5)} tokens  ${pct.toString().padStart(2)}%  (${s.total} tools) ${status}`;
          }).join('\n');

          // Calculate percentages based on actual total
          const sysPct = totalTokens > 0 ? Math.round((systemPromptTokens / totalTokens) * 100) : 0;
          const mcpPct = totalTokens > 0 ? Math.round((actualMcpTokens / totalTokens) * 100) : 0;
          const agentPct = totalTokens > 0 ? Math.round((agentToolTokens / totalTokens) * 100) : 0;
          const convPct = totalTokens > 0 ? Math.round((conversationTokens / totalTokens) * 100) : 0;

          const messageCount = state.messages.filter(m => m.role !== 'system').length;

          // Calculate lazy loading savings
          const fullLoadEstimate = mcpContextStats.totalTools * 200;
          const savingsPercent = fullLoadEstimate > 0
            ? Math.round((1 - actualMcpTokens / fullLoadEstimate) * 100)
            : 0;

          console.log(`
${c('Context Token Breakdown', 'bold')} (Total: ~${totalTokens.toLocaleString()} tokens)

${c('  Category             Tokens    % of Total', 'dim')}
  ─────────────────────────────────────────────────
  System prompt:     ${systemPromptTokens.toLocaleString().padStart(7)} tokens  ${sysPct.toString().padStart(3)}%
  MCP tools:         ${actualMcpTokens.toLocaleString().padStart(7)} tokens  ${mcpPct.toString().padStart(3)}%  (${mcpContextStats.loadedCount} loaded / ${mcpContextStats.totalTools} total)
  Agent tools:       ${agentToolTokens.toLocaleString().padStart(7)} tokens  ${agentPct.toString().padStart(3)}%  (${agentTools.length} tools)
  Conversation:      ${conversationTokens.toLocaleString().padStart(7)} tokens  ${convPct.toString().padStart(3)}%  (${messageCount} messages)

${c('  MCP Server Status:', 'dim')}
${serverLines}

${c('  Lazy Loading Impact:', 'dim')}
      Current usage: ~${actualMcpTokens.toLocaleString()} tokens
      If all loaded: ~${fullLoadEstimate.toLocaleString()} tokens
      ${savingsPercent > 0 ? c(`Savings: ${savingsPercent}% (${(fullLoadEstimate - actualMcpTokens).toLocaleString()} tokens saved)`, 'green') : ''}

${c('Tip:', 'dim')} Use mcp_tool_search to load specific tools when needed.
`);
        } else {
          // Default: simple context overview using actual lazy loading stats
          const mcpStats = integrations.mcpClient.getContextStats();
          const systemPrompt = agent.getSystemPromptWithMode();

          const estimateTokens = (str: string) => Math.ceil(str.length / 3.2);

          // System prompt tokens
          const systemTokens = estimateTokens(systemPrompt);

          // MCP tokens (uses actual lazy loading state)
          const mcpTokens = mcpStats.summaryTokens + mcpStats.definitionTokens;

          // Agent's own tools (non-MCP)
          const agentTools = agent.getTools().filter(t => !t.name.startsWith('mcp_'));
          const agentToolTokens = agentTools.length * 150;

          const baseTokens = systemTokens + mcpTokens + agentToolTokens;

          // Conversation tokens
          const convTokens = state.messages
            .filter(m => m.role !== 'system')
            .reduce((sum, m) => sum + estimateTokens(m.content), 0);

          const totalTokens = baseTokens + convTokens;
          const contextLimit = 80000;
          const percent = Math.round((totalTokens / contextLimit) * 100);
          const shouldCompact = percent >= 80;

          const bar = '█'.repeat(Math.min(20, Math.round(percent / 5))) +
                     '░'.repeat(Math.max(0, 20 - Math.round(percent / 5)));
          const color = percent >= 80 ? 'red' : percent >= 60 ? 'yellow' : 'green';

          const mcpStatus = mcpStats.loadedCount === 0
            ? c(`${mcpStats.totalTools} MCP tools (summaries only)`, 'dim')
            : c(`${mcpStats.loadedCount}/${mcpStats.totalTools} MCP tools loaded`, 'yellow');

          console.log(`
${c('Context Window:', 'bold')}
  [${c(bar, color)}] ${percent}%
  Base:     ~${baseTokens.toLocaleString()} tokens (system + ${agentTools.length} agent tools)
  MCP:      ~${mcpTokens.toLocaleString()} tokens (${mcpStatus})
  Messages: ${state.messages.filter(m => m.role !== 'system').length} (~${convTokens.toLocaleString()} tokens)
  Total:    ~${totalTokens.toLocaleString()} / ${(contextLimit / 1000).toFixed(0)}k tokens
  ${shouldCompact ? c('⚠️  Consider running /compact', 'yellow') : c('✓ Healthy', 'green')}

  ${c('Tip: Use /context breakdown for detailed token usage', 'dim')}
`);
        }
      } catch (error) {
        console.log(c(`Error: ${(error as Error).message}`, 'red'));
      }
      break;

    // =========================================================================
    // FEATURE TESTING COMMANDS
    // =========================================================================

    case '/skills':
      try {
        const skills = agent.getSkills();
        if (skills.length === 0) {
          console.log(c('No skills loaded.', 'dim'));
          console.log(c('Add .md files to .skills/ directory to create skills.', 'dim'));
        } else {
          console.log(c('\nLoaded Skills:', 'bold'));
          skills.forEach((skill: any) => {
            const active = skill.active ? c('✓', 'green') : c('○', 'dim');
            console.log(`  ${active} ${c(skill.name, 'cyan')} - ${skill.description || 'No description'}`);
            if (skill.triggers?.length > 0) {
              console.log(c(`      Triggers: ${skill.triggers.join(', ')}`, 'dim'));
            }
          });
          console.log(c('\nUse agent.activateSkill(name) to enable a skill.', 'dim'));
        }
      } catch (error) {
        console.log(c(`Skills not available: ${(error as Error).message}`, 'yellow'));
      }
      break;

    case '/sandbox':
      try {
        // Import sandbox manager to check available modes
        const { createSandboxManager } = await import('./integrations/sandbox/index.js');
        const sandboxManager = createSandboxManager({ mode: 'auto', verbose: true });
        const available = await sandboxManager.getAvailableSandboxes();

        console.log(c('\nSandbox Modes:', 'bold'));
        for (const { mode, available: isAvailable } of available) {
          const icon = isAvailable ? c('✓', 'green') : c('✗', 'red');
          const desc: Record<string, string> = {
            auto: 'Auto-detect best available sandbox',
            seatbelt: 'macOS sandbox-exec with Seatbelt profiles',
            landlock: 'Linux Landlock LSM / bubblewrap / firejail',
            docker: 'Docker container isolation',
            basic: 'Allowlist-based command validation',
            none: 'No sandboxing (passthrough)',
          };
          const modeDesc = desc[mode] || '';
          console.log(`  ${icon} ${c(mode.padEnd(10), 'cyan')} ${modeDesc}`);
        }

        // Test current sandbox
        const sandbox = await sandboxManager.getSandbox();
        console.log(c(`\nActive sandbox: ${sandbox.getType()}`, 'green'));

        // Test a safe command
        if (args[0] === 'test') {
          console.log(c('\nTesting sandbox with "echo hello"...', 'dim'));
          const result = await sandboxManager.execute('echo hello');
          console.log(`  Exit code: ${result.exitCode}`);
          console.log(`  Output: ${result.stdout.trim()}`);
          console.log(`  Sandboxed: ${sandbox.getType() !== 'none' ? 'Yes' : 'No'}`);
        } else {
          console.log(c('\nUse /sandbox test to run a test command.', 'dim'));
        }

        await sandboxManager.cleanup();
      } catch (error) {
        console.log(c(`Sandbox error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/shell':
      try {
        const { createPTYShell } = await import('./integrations/pty-shell.js');

        if (args[0] === 'test') {
          console.log(c('\nTesting persistent PTY shell...', 'cyan'));
          const shell = createPTYShell({ timeout: 5000 });
          await shell.start();

          // Test command persistence
          console.log(c('  1. Setting variable: export TEST_VAR="hello"', 'dim'));
          await shell.execute('export TEST_VAR="hello"');

          console.log(c('  2. Reading variable back...', 'dim'));
          const result = await shell.execute('echo $TEST_VAR');
          console.log(`     Result: ${result.output}`);
          console.log(`     Exit code: ${result.exitCode}`);

          console.log(c('  3. Checking state persistence...', 'dim'));
          const state = shell.getState();
          console.log(`     CWD: ${state.cwd}`);
          console.log(`     Commands run: ${state.history.length}`);
          console.log(`     Shell running: ${state.isRunning}`);

          await shell.cleanup();
          console.log(c('\n✓ PTY shell test passed!', 'green'));
        } else {
          console.log(`
${c('PTY Shell:', 'bold')}
  The persistent shell maintains state between commands:
  - Working directory persists across cd commands
  - Environment variables are retained
  - Command history is tracked

  ${c('Use /shell test to run a quick test.', 'dim')}
`);
        }
      } catch (error) {
        console.log(c(`Shell error: ${(error as Error).message}`, 'red'));
      }
      break;

    case '/lsp':
      // LSP tools are available via getLSPFileTools() - show info about them
      console.log(`
${c('LSP Integration:', 'bold')}
  The LSP-enhanced file tools provide real-time diagnostics:

${c('LSP-Enhanced Tools:', 'bold')}
  • ${c('lsp_edit_file', 'cyan')} - Edit with diagnostics feedback
  • ${c('lsp_write_file', 'cyan')} - Write with diagnostics feedback

${c('How it works:', 'dim')}
  1. After edit/write, LSP server analyzes the file
  2. Returns errors, warnings, and hints inline
  3. Agent can self-correct based on feedback

${c('To enable:', 'dim')}
  // In your agent setup:
  const lspManager = createLSPManager({ ... });
  const lspTools = agent.getLSPFileTools(lspManager);
  for (const tool of lspTools) agent.addTool(tool);

${c('Example output after edit:', 'dim')}
  ${c('✓ File edited successfully', 'green')}
  ${c('⚠ Line 5: Unused variable "x"', 'yellow')}
  ${c('❌ Line 10: Property "foo" does not exist on type "Bar"', 'red')}
`);
      break;

    case '/tui':
      console.log(`
${c('TUI (Terminal UI):', 'bold')}
  Status: ${c('Active', 'green')} (SimpleTextRenderer)

${c('Features:', 'bold')}
  • Syntax highlighting for code blocks
  • Colored tool call display
  • Progress spinners
  • Error/success styling

${c('Code Highlighting Languages:', 'dim')}
  Python, JavaScript, TypeScript

${c('Test it:', 'dim')}
  Ask the agent to write code, e.g.:
  "Write a Python function to calculate factorial"
`);
      break;

    default:
      console.log(c(`Unknown command: ${cmd}. Type /help`, 'yellow'));
  }

  console.log();
}

// =============================================================================
// CLI ARGS
// =============================================================================

interface CLIArgs {
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
}

function parseArgs(): CLIArgs {
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
    } else if (arg === '--max-iterations' || arg === '-i') {
      result.maxIterations = parseInt(args[++i], 10);
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

function showHelp(): void {
  console.log(`
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
  -i, --max-iterations N  Max agent iterations (default: 50)
  -t, --task TASK         Run single task non-interactively

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

// =============================================================================
// TUI MODE
// =============================================================================

const VERSION = '1.0.0';

function shouldUseTUI(args: CLIArgs): boolean {
  if (args.tui === true) return true;
  if (args.tui === false) return false;
  // Auto-detect: use TUI when TTY and interactive
  return process.stdin.isTTY && process.stdout.isTTY && !args.task;
}

async function startTUIMode(
  provider: LLMProviderWithTools,
  options: {
    permissionMode?: PermissionMode;
    maxIterations?: number;
    model?: string;
    trace?: boolean;
    theme?: 'dark' | 'light' | 'auto';
  } = {}
): Promise<void> {
  const {
    permissionMode = 'interactive',
    maxIterations = 50,
    model,
    trace = false,
    theme = 'auto',
  } = options;

  try {
    // Check Ink availability
    const { checkTUICapabilities } = await import('./tui/index.js');
    const capabilities = await checkTUICapabilities();

    if (!capabilities.inkAvailable) {
      console.log('⚠️  TUI not available. Falling back to legacy mode.');
      return startProductionREPL(provider, options);
    }

    // Enable TUI mode for debug logger to prevent console interference with Ink
    persistenceDebug.enableTUIMode();

    // CRITICAL: Initialize session storage FIRST, before any heavy dynamic imports
    // This ensures better-sqlite3 native module loads cleanly
    let sessionStore: AnySessionStore;
    let usingSQLiteTUI = false;

    persistenceDebug.log('[TUI] Initializing session store BEFORE dynamic imports...');

    try {
      sessionStore = await createSQLiteStore({ baseDir: '.agent/sessions' });
      usingSQLiteTUI = true;

      if (persistenceDebug.isEnabled()) {
        const sqliteStore = sessionStore as SQLiteStore;
        const stats = sqliteStore.getStats();
        persistenceDebug.log('[TUI] ✓ SQLite store initialized!', { sessions: stats.sessionCount, checkpoints: stats.checkpointCount });
      }
      console.log('✓ SQLite session store initialized');
    } catch (sqliteError) {
      const errMsg = (sqliteError as Error).message;
      if (persistenceDebug.isEnabled()) {
        process.stderr.write(`[DEBUG] [TUI] ❌ SQLite FAILED: ${errMsg}\n`);
      }
      console.log('⚠️  SQLite unavailable, using JSONL fallback');
      console.log(`   Error: ${errMsg}`);
      sessionStore = await createSessionStore({ baseDir: '.agent/sessions' });
    }

    // Dynamic imports - using our modular TUI components
    const { render, Box, Text, useApp, useInput } = await import('ink');
    const React = await import('react');
    const { useState, useCallback, useEffect } = React;
    const { getTheme, getThemeNames } = await import('./tui/theme/index.js');
    const { ToolCallList } = await import('./tui/components/ToolCall.js');
    const { Header } = await import('./tui/layout/Header.js');
    const { Footer } = await import('./tui/layout/Footer.js');
    type ToolCallDisplay = import('./tui/types.js').ToolCallDisplay;

    // Initialize pricing cache from OpenRouter
    await initPricingCache();

    // Setup agent (same as legacy)
    const registry = createStandardRegistry(permissionMode);
    const tools = convertToolsFromRegistry(registry);
    const adaptedProvider = new ProviderAdapter(provider, model);

    // Hierarchical MCP config: global (~/.config/attocode/mcp.json) + workspace (.mcp.json)
    const mcpClient = await createMCPClient({
      configPaths: getMCPConfigPaths(),
      lazyLoading: true,
      alwaysLoadTools: [],
      summaryDescriptionLimit: 100,
      maxToolsPerSearch: 5,
    });

    const mcpSummaries = mcpClient.getAllToolSummaries().map(s => ({
      name: s.name,
      description: s.description,
    }));

    // Initialize LSP manager for code intelligence
    const lspManager = createLSPManager({ autoDetect: true });
    let lspServers: string[] = [];
    try {
      lspServers = await lspManager.autoStart(process.cwd());
      if (lspServers.length > 0) {
        console.log(`🔍 LSP: Started ${lspServers.join(', ')} language server(s)`);
      } else {
        console.log(`💡 LSP: No language servers found (optional)`);
        console.log(`   For inline diagnostics: npm i -g typescript-language-server typescript`);
      }
    } catch (err) {
      console.log(`⚠️  LSP: Could not start language servers (${(err as Error).message})`);
    }

    // Create LSP-enhanced file tools (replaces standard edit_file/write_file)
    const lspFileTools = createLSPFileTools({ lspManager, diagnosticDelay: 500 });

    // Replace standard edit_file/write_file with LSP-enhanced versions
    const standardToolsWithoutFileOps = tools.filter(t => !['edit_file', 'write_file'].includes(t.name));
    const allTools = [...standardToolsWithoutFileOps, ...lspFileTools];

    const agent = createProductionAgent({
      toolResolver: (toolName: string) => toolName.startsWith('mcp_') ? mcpClient.getFullToolDefinition(toolName) : null,
      mcpToolSummaries: mcpSummaries,
      provider: adaptedProvider,
      tools: allTools,
      model,
      maxIterations,
      memory: { enabled: true, types: { episodic: true, semantic: true, working: true } },
      planning: { enabled: true, autoplan: true, complexityThreshold: 6 },
      humanInLoop: permissionMode === 'interactive' ? { enabled: true, alwaysApprove: ['dangerous'] } : false,
      // Observability: trace capture to file when --trace, logging disabled in TUI (use debug mode instead)
      observability: trace
        ? { enabled: true, traceCapture: { enabled: true, outputDir: '.traces' }, logging: { enabled: false } }
        : undefined,
      // Hooks: Only enable console output in debug mode
      hooks: {
        enabled: true,
        builtIn: {
          logging: persistenceDebug.isEnabled(), // Only show [Hook] logs in debug mode
          timing: persistenceDebug.isEnabled(),  // Only show timing in debug mode
          metrics: true,
        },
        custom: [],
      },
    });

    // Session store was already initialized at the top of startTUIMode
    const compactor = createCompactor(adaptedProvider, {
      tokenThreshold: 80000,
      preserveRecentCount: 10,
    });

    // Check for existing sessions to offer resume
    let currentSessionId: string;
    let resumedSession = false;

    const existingSessions = await sessionStore.listSessions();
    persistenceDebug.log('[TUI] Checking existing sessions', { count: existingSessions.length });

    if (existingSessions.length > 0) {
      const pickerResult = await showQuickPicker(existingSessions);

      if (pickerResult.action === 'cancel') {
        // User typed 'list' - show full picker
        const fullResult = await showSessionPicker(existingSessions);

        if (fullResult.action === 'resume' && fullResult.sessionId) {
          currentSessionId = fullResult.sessionId;
          resumedSession = true;
        } else if (fullResult.action === 'cancel') {
          console.log('Goodbye! 👋');
          await mcpClient.cleanup();
          await agent.cleanup();
          await lspManager.cleanup();
          return;
        } else {
          currentSessionId = await sessionStore.createSession();
        }
      } else if (pickerResult.action === 'resume' && pickerResult.sessionId) {
        currentSessionId = pickerResult.sessionId;
        resumedSession = true;
      } else {
        currentSessionId = await sessionStore.createSession();
      }
    } else {
      currentSessionId = await sessionStore.createSession();
    }

    persistenceDebug.log('[TUI] Session selected', {
      sessionId: currentSessionId,
      resumed: resumedSession,
      storeType: persistenceDebug.storeType(sessionStore),
    });

    // CRITICAL: Sync the session ID to the store's internal state
    // This is necessary for resumption because sessionStore.createSession()
    // sets this internally, but resumption only returns the ID.
    sessionStore.setCurrentSessionId(currentSessionId);

    // If resuming, load the session state
    if (resumedSession) {
      const sessionState = await loadSessionState(sessionStore, currentSessionId);
      if (sessionState?.messages) {
        agent.loadState({
          messages: sessionState.messages as any,
          iteration: sessionState.iteration,
          metrics: sessionState.metrics as any,
          plan: sessionState.plan as any,
          memoryContext: sessionState.memoryContext,
        });
        console.log(`✓ Resumed ${sessionState.messages.length} messages from session`);
      }
    }

    // Initial theme (will be stateful inside component)
    const initialTheme = getTheme(theme);

    // Get git branch for status line (using execFileSync for safety - no shell injection possible)
    const getGitBranch = (): string => {
      try {
        const { execFileSync } = require('child_process');
        return execFileSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'], { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
      } catch {
        return '';
      }
    };
    const gitBranch = getGitBranch();

    // TUI Component - direct rendering with static icons (flicker-free)
    const TUIApp = () => {
      const { exit } = useApp();
      const [messages, setMessages] = useState<Array<{ id: string; role: string; content: string; ts: Date }>>([]);
      const [inputValue, setInputValue] = useState('');
      const [isProcessing, setIsProcessing] = useState(false);
      const [status, setStatus] = useState({ iter: 0, tokens: 0, cost: 0, mode: 'ready' });
      const [toolCalls, setToolCalls] = useState<ToolCallDisplay[]>([]);
      const [currentThemeName, setCurrentThemeName] = useState<string>(theme);
      const [contextTokens, setContextTokens] = useState(0);
      const [elapsedTime, setElapsedTime] = useState(0);
      const processingStartRef = React.useRef<number | null>(null);

      // Display toggles
      const [toolCallsExpanded, setToolCallsExpanded] = useState(false);
      const [showThinking, setShowThinking] = useState(true);

      // Derive theme and colors from state
      const selectedTheme = getTheme(currentThemeName);
      const colors = selectedTheme.colors;

      const addMessage = useCallback((role: string, content: string) => {
        setMessages(prev => [...prev, { id: `${role}-${Date.now()}`, role, content, ts: new Date() }]);
      }, []);

      const handleCommand = useCallback(async (cmd: string, args: string[]) => {
        // General commands
        switch (cmd) {
          case 'quit':
          case 'exit':
          case 'q':
            await agent.cleanup();
            await mcpClient.cleanup();
            await lspManager.cleanup();
            exit();
            return;

          case 'clear':
          case 'cls':
            setMessages([]);
            setToolCalls([]);
            return;

          case 'status':
          case 'stats': {
            const metrics = agent.getMetrics();
            const agentState = agent.getState();
            const statusLines = [
              `Session Status:`,
              `  Status: ${agentState.status} | Iteration: ${agentState.iteration}`,
              `  Messages: ${agentState.messages.length}`,
              `  Tokens: ${metrics.totalTokens.toLocaleString()} (${metrics.inputTokens} in / ${metrics.outputTokens} out)`,
              `  LLM Calls: ${metrics.llmCalls} | Tool Calls: ${metrics.toolCalls}`,
              `  Duration: ${metrics.duration}ms | Cost: $${metrics.estimatedCost.toFixed(4)}`,
            ];

            // Add goals progress if available
            if ('listActiveGoals' in sessionStore) {
              const goalsStore = sessionStore as SQLiteStore;
              const activeGoals = goalsStore.listActiveGoals();
              if (activeGoals.length > 0) {
                let totalCurrent = 0, totalExpected = 0;
                for (const g of activeGoals) {
                  if (g.progressTotal) {
                    totalCurrent += g.progressCurrent;
                    totalExpected += g.progressTotal;
                  }
                }
                statusLines.push('');
                statusLines.push(`Active Goals: ${activeGoals.length}`);
                if (totalExpected > 0) {
                  const pct = Math.round((totalCurrent / totalExpected) * 100);
                  statusLines.push(`  Progress: ${totalCurrent}/${totalExpected} (${pct}%)`);
                }
              }
            }

            addMessage('system', statusLines.join('\n'));
            return;
          }

          case 'goals':
            if ('listActiveGoals' in sessionStore) {
              const sqlStore = sessionStore as SQLiteStore;
              const subCmd = args[0]?.toLowerCase();

              if (!subCmd || subCmd === 'list') {
                const goals = sqlStore.listActiveGoals();
                if (goals.length === 0) {
                  addMessage('system', 'No active goals. Use /goals add <text> to create one.');
                } else {
                  const lines = ['Active Goals:'];
                  for (const goal of goals) {
                    const progress = goal.progressTotal ? ` (${goal.progressCurrent}/${goal.progressTotal})` : '';
                    const priority = goal.priority === 1 ? ' [HIGH]' : goal.priority === 3 ? ' [low]' : '';
                    lines.push(`  • ${goal.goalText}${progress}${priority}`);
                  }
                  addMessage('system', lines.join('\n'));
                }
              } else if (subCmd === 'add' && args.length > 1) {
                const goalText = args.slice(1).join(' ');
                const goalId = sqlStore.createGoal(goalText);
                addMessage('system', `✓ Goal created: ${goalId}`);
              } else if (subCmd === 'done' && args[1]) {
                sqlStore.completeGoal(args[1]);
                addMessage('system', `✓ Goal completed`);
              } else if (subCmd === 'junctures') {
                const junctures = sqlStore.listJunctures(undefined, 10);
                if (junctures.length === 0) {
                  addMessage('system', 'No junctures logged yet.');
                } else {
                  const lines = ['Recent Key Moments:'];
                  for (const j of junctures) {
                    const icon = j.type === 'failure' ? '✗' : j.type === 'breakthrough' ? '★' :
                                j.type === 'decision' ? '→' : '↻';
                    lines.push(`  ${icon} [${j.type}] ${j.description}`);
                  }
                  addMessage('system', lines.join('\n'));
                }
              } else {
                addMessage('system', 'Usage: /goals [list|add <text>|done <id>|junctures]');
              }
            } else {
              addMessage('system', 'Goals require SQLite store');
            }
            return;

          case 'handoff':
            if ('exportSessionManifest' in sessionStore) {
              const sqlStore = sessionStore as SQLiteStore;
              const format = args[0]?.toLowerCase() || 'markdown';

              if (format === 'json') {
                const manifest = sqlStore.exportSessionManifest();
                if (manifest) {
                  addMessage('system', JSON.stringify(manifest, null, 2));
                } else {
                  addMessage('system', 'No active session to export');
                }
              } else {
                const markdown = sqlStore.exportSessionMarkdown();
                addMessage('system', markdown);
              }
            } else {
              addMessage('system', 'Handoff requires SQLite store');
            }
            return;

          case 'help':
          case 'h':
            addMessage('system', [
              '═══════════════════════════════════════════════════════',
              '                    ATTOCODE COMMANDS',
              '═══════════════════════════════════════════════════════',
              '',
              '▸ GENERAL',
              '  /help /h          Show this help',
              '  /quit /exit /q    Exit the agent',
              '  /clear /cls       Clear screen',
              '  /reset            Reset agent state',
              '  /status /stats    Show session metrics',
              '  /model            Show/change model',
              '  /theme [name]     Show/change theme',
              '  /tools            List available tools',
              '',
              '▸ SESSIONS & PERSISTENCE',
              '  /save             Save current session',
              '  /load <id>        Load a session',
              '  /sessions         List all sessions',
              '  /resume           Resume last session',
              '  /handoff [json]   Export session for handoff',
              '  /checkpoint       Create checkpoint',
              '  /checkpoints      List checkpoints',
              '  /restore <id>     Restore checkpoint',
              '  /rollback [n]     Rollback n steps',
              '',
              '▸ CONTEXT & MEMORY',
              '  /context /ctx     Show context token breakdown',
              '  /compact          Compress context',
              '  /goals            Manage goals [list|add|done|junctures]',
              '',
              '▸ THREADS & BRANCHING',
              '  /fork <name>      Fork conversation',
              '  /threads          List all threads',
              '  /switch <id>      Switch to thread',
              '',
              '▸ MCP SERVERS',
              '  /mcp              List MCP servers',
              '  /mcp tools        List MCP tools',
              '  /mcp search <q>   Search & load tools',
              '  /mcp stats        Show MCP context usage',
              '',
              '▸ SUBAGENTS',
              '  /agents           List available agents',
              '  /spawn <a> <task> Spawn agent with task',
              '  /find <query>     Find agents for task',
              '  /suggest <task>   Get agent suggestions',
              '  /auto <task>      Auto-route to best agent',
              '',
              '▸ ADVANCED',
              '  /react <task>     Run with ReAct reasoning',
              '  /team <task>      Run with multi-agent team',
              '  /grants           List permission grants',
              '  /audit            Show audit log',
              '  /budget           Show budget usage',
              '  /extend <t> <n>   Extend budget (tokens|cost|time)',
              '',
              '▸ DEBUG',
              '  /skills           List loaded skills',
              '  /sandbox          Show sandbox status',
              '  /shell            Show shell status',
              '  /lsp              Show LSP status',
              '  /tui              Show TUI status',
              '',
              '═══════════════════════════════════════════════════════',
              'KEYBOARD SHORTCUTS',
              '  Ctrl+C    Exit',
              '  Ctrl+L    Clear screen',
              '  Ctrl+P    Command palette',
              '  Cmd+T     Toggle tool details',
              '  Cmd+O     Toggle thinking display',
              '═══════════════════════════════════════════════════════',
            ].join('\n'));
            return;

          case 'reset':
            agent.reset();
            setMessages([]);
            setToolCalls([]);
            addMessage('system', 'Agent state reset');
            return;

          // Sessions
          case 'save':
            try {
              const agentState = agent.getState();
              const agentMetrics = agent.getMetrics();
              const tuiSaveCheckpointId = `ckpt-manual-${Date.now().toString(36)}`;

              persistenceDebug.log('[TUI] /save command - creating checkpoint', {
                checkpointId: tuiSaveCheckpointId,
                messageCount: agentState.messages?.length ?? 0,
              });

              saveCheckpointToStore(sessionStore, {
                id: tuiSaveCheckpointId,
                label: 'manual-save',
                messages: agentState.messages,
                iteration: agentState.iteration,
                metrics: agentMetrics,
                plan: agentState.plan,
                memoryContext: agentState.memoryContext,
              });

              addMessage('system', `Session saved: ${currentSessionId} (checkpoint: ${tuiSaveCheckpointId})`);
            } catch (e) {
              persistenceDebug.error('[TUI] /save command failed', e);
              addMessage('error', (e as Error).message);
            }
            return;

          case 'load':
            if (!args[0]) {
              addMessage('system', 'Usage: /load <session-id>');
              return;
            }
            try {
              // Try SQLite's loadLatestCheckpoint first (checkpoints are in separate table)
              let tuiLoadCheckpoint: CheckpointData | undefined;
              if ('loadLatestCheckpoint' in sessionStore && typeof sessionStore.loadLatestCheckpoint === 'function') {
                const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(args[0]);
                if (sqliteCheckpoint?.state) {
                  tuiLoadCheckpoint = sqliteCheckpoint.state as unknown as CheckpointData;
                }
              }

              // Fall back to entries-based lookup
              if (!tuiLoadCheckpoint) {
                const loadResult = sessionStore.loadSession(args[0]);
                const loadEntries = Array.isArray(loadResult) ? loadResult : await loadResult;
                const checkpoint = [...loadEntries].reverse().find((e: any) => e.type === 'checkpoint');
                if (checkpoint?.data) {
                  tuiLoadCheckpoint = checkpoint.data as CheckpointData;
                }
              }

              if (tuiLoadCheckpoint?.messages) {
                // Use loadState for full state restoration
                agent.loadState({
                  messages: tuiLoadCheckpoint.messages as any,
                  iteration: tuiLoadCheckpoint.iteration,
                  metrics: tuiLoadCheckpoint.metrics as any,
                  plan: tuiLoadCheckpoint.plan as any,
                  memoryContext: tuiLoadCheckpoint.memoryContext,
                });
                // Sync TUI with loaded messages
                const loadedMsgs = agent.getState().messages;
                const syncedLoaded = loadedMsgs.map((m, i) => ({
                  id: `msg-${i}`,
                  role: m.role,
                  content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                  ts: new Date(),
                }));
                setMessages(syncedLoaded);
                addMessage('system', `Loaded ${tuiLoadCheckpoint.messages.length} messages from ${args[0]}`);
              } else {
                addMessage('system', 'No checkpoint found in session');
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'resume':
            try {
              const recentSess = sessionStore.getRecentSession();
              if (!recentSess) {
                addMessage('system', 'No previous sessions found');
                return;
              }
              addMessage('system', `📂 Found: ${recentSess.id} (${recentSess.messageCount} messages)`);

              // Try SQLite's loadLatestCheckpoint first (checkpoints are in separate table)
              let tuiResumeCheckpoint: CheckpointData | undefined;
              if ('loadLatestCheckpoint' in sessionStore && typeof sessionStore.loadLatestCheckpoint === 'function') {
                const sqliteCheckpoint = sessionStore.loadLatestCheckpoint(recentSess.id);
                if (sqliteCheckpoint?.state) {
                  tuiResumeCheckpoint = sqliteCheckpoint.state as unknown as CheckpointData;
                }
              }

              // Fall back to entries-based lookup
              if (!tuiResumeCheckpoint) {
                const resumeResult = sessionStore.loadSession(recentSess.id);
                const resumeEntries = Array.isArray(resumeResult) ? resumeResult : await resumeResult;
                const resumeCheckpoint = [...resumeEntries].reverse().find((e: any) => e.type === 'checkpoint');
                if (resumeCheckpoint?.data) {
                  tuiResumeCheckpoint = resumeCheckpoint.data as CheckpointData;
                } else {
                  // No checkpoint, try to load messages directly from entries
                  const msgs = resumeEntries
                    .filter((e: any) => e.type === 'message')
                    .map((e: any) => e.data);
                  if (msgs.length > 0) {
                    agent.loadState({ messages: msgs as any });
                  }
                }
              }

              if (tuiResumeCheckpoint?.messages) {
                // Use loadState for full state restoration
                agent.loadState({
                  messages: tuiResumeCheckpoint.messages as any,
                  iteration: tuiResumeCheckpoint.iteration,
                  metrics: tuiResumeCheckpoint.metrics as any,
                  plan: tuiResumeCheckpoint.plan as any,
                  memoryContext: tuiResumeCheckpoint.memoryContext,
                });
              }

              // Sync TUI with loaded messages
              const resumedMsgs = agent.getState().messages;
              if (resumedMsgs.length > 0) {
                const syncedResumed = resumedMsgs.map((m, i) => ({
                  id: `msg-${i}`,
                  role: m.role,
                  content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                  ts: new Date(),
                }));
                setMessages(syncedResumed);
                addMessage('system', `✓ Resumed ${resumedMsgs.length} messages`);
              } else {
                addMessage('system', 'No messages found in last session');
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'sessions':
            try {
              const sessions = await sessionStore.listSessions();
              addMessage('system', formatSessionsTable(sessions));
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          // Context
          case 'context':
          case 'ctx': {
            const agentState = agent.getState();
            const mcpStats = mcpClient.getContextStats();

            // Token estimation
            const estimateTokens = (str: string) => Math.ceil(str.length / 3.2);

            // System prompt tokens
            const systemPrompt = agent.getSystemPromptWithMode ? agent.getSystemPromptWithMode() : '';
            const systemTokens = estimateTokens(systemPrompt);

            // MCP tokens (lazy loading aware)
            const mcpTokens = mcpStats.summaryTokens + mcpStats.definitionTokens;

            // Agent tools (non-MCP)
            const agentTools = agent.getTools().filter(t => !t.name.startsWith('mcp_'));
            const agentToolTokens = agentTools.length * 150;

            // Conversation tokens
            const convTokens = agentState.messages
              .filter(m => m.role !== 'system')
              .reduce((sum, m) => sum + estimateTokens(typeof m.content === 'string' ? m.content : JSON.stringify(m.content)), 0);

            const totalTokens = systemTokens + mcpTokens + agentToolTokens + convTokens;
            const contextLimit = 80000;
            const percent = Math.round((totalTokens / contextLimit) * 100);
            const bar = '█'.repeat(Math.min(20, Math.round(percent / 5))) + '░'.repeat(Math.max(0, 20 - Math.round(percent / 5)));

            // Calculate lazy loading savings
            const fullLoadEstimate = mcpStats.totalTools * 200;
            const savingsPercent = fullLoadEstimate > 0 ? Math.round((1 - mcpTokens / fullLoadEstimate) * 100) : 0;

            addMessage('system', [
              `Context Token Breakdown (Total: ~${totalTokens.toLocaleString()} / ${(contextLimit / 1000)}k)`,
              `  [${bar}] ${percent}%`,
              ``,
              `  System prompt:   ~${systemTokens.toLocaleString().padStart(6)} tokens`,
              `  Agent tools:     ~${agentToolTokens.toLocaleString().padStart(6)} tokens  (${agentTools.length} tools)`,
              `  MCP tools:       ~${mcpTokens.toLocaleString().padStart(6)} tokens  (${mcpStats.loadedCount}/${mcpStats.totalTools} loaded)`,
              `  Conversation:    ~${convTokens.toLocaleString().padStart(6)} tokens  (${agentState.messages.length} messages)`,
              ``,
              `  MCP Lazy Loading: ${savingsPercent}% saved vs full load`,
              `  ${percent >= 80 ? '⚠️ Consider /compact' : '✓ Healthy'}`,
            ].join('\n'));
            return;
          }

          case 'compact':
            try {
              const agentState = agent.getState();
              if (agentState.messages.length < 5) {
                addMessage('system', 'Not enough messages to compact.');
                return;
              }
              setIsProcessing(true);
              setStatus(s => ({ ...s, mode: 'compacting' }));
              const result = await compactor.compact(agentState.messages);
              agent.loadMessages(result.preservedMessages);
              const savedTokens = result.tokensBefore - result.tokensAfter;
              addMessage('system', `Compacted: ${result.compactedCount + result.preservedMessages.length} → ${result.preservedMessages.length} messages (saved ~${savedTokens} tokens)`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            setIsProcessing(false);
            setStatus(s => ({ ...s, mode: 'ready' }));
            return;

          // MCP
          case 'mcp': {
            if (args[0] === 'connect' && args[1]) {
              try {
                await mcpClient.connectServer(args[1]);
                const tools = mcpClient.getAllTools();
                for (const tool of tools) agent.addTool(tool);
                addMessage('system', `Connected to ${args[1]} (${tools.length} tools)`);
              } catch (e) {
                addMessage('error', (e as Error).message);
              }
              return;
            }
            if (args[0] === 'disconnect' && args[1]) {
              await mcpClient.disconnectServer(args[1]);
              addMessage('system', `Disconnected from ${args[1]}`);
              return;
            }
            if (args[0] === 'tools') {
              const tools = mcpClient.getAllTools();
              if (tools.length === 0) {
                addMessage('system', 'No MCP tools available.');
              } else {
                const stats = mcpClient.getContextStats();
                addMessage('system', `MCP Tools (${stats.loadedCount}/${stats.totalTools} loaded):\n${tools.slice(0, 15).map(t => `  ${mcpClient.isToolLoaded(t.name) ? '✓' : '○'} ${t.name}`).join('\n')}`);
              }
              return;
            }
            if (args[0] === 'search' && args.slice(1).length > 0) {
              const query = args.slice(1).join(' ');
              const results = mcpClient.searchTools(query, { limit: 10 });
              if (results.length === 0) {
                addMessage('system', `No tools found for: "${query}"`);
              } else {
                const loaded = mcpClient.loadTools(results.map(r => r.name));
                for (const tool of loaded) agent.addTool(tool);
                addMessage('system', `Found & loaded ${loaded.length} tool(s):\n${results.map(r => `  ${r.name} - ${r.description?.slice(0, 50)}`).join('\n')}`);
              }
              return;
            }
            if (args[0] === 'stats') {
              const stats = mcpClient.getContextStats();
              const fullLoadEstimate = stats.totalTools * 200;
              const currentTokens = stats.summaryTokens + stats.definitionTokens;
              const savingsPercent = fullLoadEstimate > 0 ? Math.round((1 - currentTokens / fullLoadEstimate) * 100) : 0;

              addMessage('system', [
                `MCP Context Usage:`,
                `  Tool summaries:   ${stats.summaryCount.toString().padStart(3)} tools  (~${stats.summaryTokens.toLocaleString()} tokens)`,
                `  Full definitions: ${stats.loadedCount.toString().padStart(3)} tools  (~${stats.definitionTokens.toLocaleString()} tokens)`,
                `  ─────────────────────────────────────`,
                `  Total:            ${stats.totalTools.toString().padStart(3)} tools  (~${currentTokens.toLocaleString()} tokens)`,
                ``,
                `  Context savings:  ${savingsPercent}% vs loading all full schemas`,
                `  If all loaded:    ~${fullLoadEstimate.toLocaleString()} tokens`,
                `  ${savingsPercent > 50 ? '✓ Lazy loading saving context' : '⚠ Consider using lazy loading more'}`,
                ``,
                `  Tip: Use /mcp search <query> to load specific tools on-demand`,
              ].join('\n'));
              return;
            }
            // Default: list servers with stats
            const servers = mcpClient.listServers();
            const stats = mcpClient.getContextStats();
            if (servers.length === 0) {
              addMessage('system', 'No MCP servers configured. Add servers to src/.mcp.json');
            } else {
              const fullLoadEstimate = stats.totalTools * 200;
              const currentTokens = stats.summaryTokens + stats.definitionTokens;
              const savingsPercent = fullLoadEstimate > 0 ? Math.round((1 - currentTokens / fullLoadEstimate) * 100) : 0;

              addMessage('system', [
                `MCP Servers:`,
                ...servers.map(s => `  ${s.status === 'connected' ? '✓' : '○'} ${s.name} (${s.status}) - ${s.toolCount || 0} tools`),
                ``,
                `Lazy Loading: ${stats.loadedCount}/${stats.totalTools} tools loaded (${savingsPercent}% context saved)`,
                `Current usage: ~${currentTokens.toLocaleString()} tokens`,
                ``,
                `Commands: /mcp tools | /mcp search <query> | /mcp stats`,
              ].join('\n'));
            }
            return;
          }

          // Advanced - ReAct
          case 'react':
            if (!args.length) {
              addMessage('system', 'Usage: /react <task>');
              return;
            }
            setIsProcessing(true);
            setStatus(s => ({ ...s, mode: 'react' }));
            try {
              const trace = await agent.runWithReAct(args.join(' '));
              addMessage('assistant', agent.formatReActTrace(trace));
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            setIsProcessing(false);
            setStatus(s => ({ ...s, mode: 'ready' }));
            return;

          // Advanced - Team
          case 'team':
            if (!args.length) {
              addMessage('system', 'Usage: /team <task>');
              return;
            }
            setIsProcessing(true);
            setStatus(s => ({ ...s, mode: 'team' }));
            try {
              const { CODER_ROLE, REVIEWER_ROLE, RESEARCHER_ROLE } = await import('./integrations/multi-agent.js');
              const result = await agent.runWithTeam(
                { id: `team-${Date.now()}`, goal: args.join(' '), context: '' },
                [RESEARCHER_ROLE, CODER_ROLE, REVIEWER_ROLE]
              );
              addMessage('assistant', `Team result: ${result.success ? 'Success' : 'Failed'}\n${result.consensus?.result || ''}`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            setIsProcessing(false);
            setStatus(s => ({ ...s, mode: 'ready' }));
            return;

          // Checkpoints
          case 'checkpoint':
          case 'cp':
            try {
              const cp = agent.createCheckpoint(args.join(' ') || undefined);
              addMessage('system', `Checkpoint created: ${cp.id}${cp.label ? ` (${cp.label})` : ''}`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'checkpoints':
          case 'cps':
            try {
              const cps = agent.getCheckpoints();
              if (cps.length === 0) {
                addMessage('system', 'No checkpoints.');
              } else {
                addMessage('system', `Checkpoints:\n${cps.map(cp => `  ${cp.id}${cp.label ? ` - ${cp.label}` : ''}`).join('\n')}`);
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'restore':
            if (!args[0]) {
              addMessage('system', 'Usage: /restore <checkpoint-id>');
              return;
            }
            const restoreOk = agent.restoreCheckpoint(args[0]);
            if (restoreOk) {
              // Sync TUI messages with agent state after restore
              const restoredMessages = agent.getState().messages;
              const syncedRestored = restoredMessages.map((m, i) => ({
                id: `msg-${i}`,
                role: m.role,
                content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                ts: new Date(),
              }));
              setMessages(syncedRestored);
              addMessage('system', `Restored: ${args[0]} - ${restoredMessages.length} messages`);
            } else {
              addMessage('system', `Not found: ${args[0]}`);
            }
            return;

          case 'rollback':
          case 'rb': {
            const rbSteps = parseInt(args[0], 10) || 1;
            const rbSuccess = agent.rollback(rbSteps);
            if (rbSuccess) {
              // Sync TUI messages with agent state after rollback
              const agentMessages = agent.getState().messages;
              const syncedMessages = agentMessages.map((m, i) => ({
                id: `msg-${i}`,
                role: m.role,
                content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                ts: new Date(),
              }));
              setMessages(syncedMessages);
              addMessage('system', `Rolled back ${rbSteps} step(s) - ${agentMessages.length} messages remaining`);
            } else {
              addMessage('system', 'Rollback failed - not enough messages');
            }
            return;
          }

          // Threads
          case 'fork':
            if (!args.length) {
              addMessage('system', 'Usage: /fork <name>');
              return;
            }
            try {
              const threadId = agent.fork(args.join(' '));
              addMessage('system', `Forked: ${threadId}`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'threads':
            try {
              const threads = agent.getAllThreads();
              if (threads.length === 0) {
                addMessage('system', 'No threads.');
              } else {
                addMessage('system', `Threads:\n${threads.map((t: any) => `  ${t.id}${t.name ? ` - ${t.name}` : ''} (${t.messages?.length || 0} msgs)`).join('\n')}`);
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'switch':
            if (!args[0]) {
              addMessage('system', 'Usage: /switch <thread-id>');
              return;
            }
            const switchOk = agent.switchThread(args[0]);
            addMessage('system', switchOk ? `Switched to: ${args[0]}` : `Not found: ${args[0]}`);
            return;

          // Permissions
          case 'grants':
            try {
              const grants = agent.getActiveGrants();
              if (grants.length === 0) {
                addMessage('system', 'No active permission grants.');
              } else {
                addMessage('system', `Active Grants:\n${grants.map((g: any) => `  ${g.id} - ${g.toolName}`).join('\n')}`);
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'audit':
            try {
              const log = agent.getAuditLog();
              if (log.length === 0) {
                addMessage('system', 'No audit entries.');
              } else {
                addMessage('system', `Audit Log (last 10):\n${log.slice(-10).map((e: any) => `  ${e.approved ? '✓' : '✗'} ${e.action} - ${e.tool || 'n/a'}`).join('\n')}`);
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          // Budget
          case 'budget': {
            try {
              const usage = agent.getBudgetUsage();
              const limits = agent.getBudgetLimits();
              if (!usage || !limits) {
                addMessage('system', 'Budget info not available.');
              } else {
                addMessage('system', [
                  `Budget Usage:`,
                  `  Tokens: ${usage.tokens.toLocaleString()} / ${limits.maxTokens.toLocaleString()} (${usage.percentUsed.toFixed(1)}%)`,
                  `  Cost: $${usage.cost.toFixed(4)} / $${limits.maxCost.toFixed(2)}`,
                  `  Duration: ${Math.round(usage.duration / 1000)}s / ${Math.round(limits.maxDuration / 1000)}s`,
                ].join('\n'));
              }
            } catch (e) {
              const m = agent.getMetrics();
              addMessage('system', `Budget: ${m.totalTokens} tokens | $${m.estimatedCost.toFixed(4)} cost`);
            }
            return;
          }

          case 'extend':
            if (args.length < 2) {
              addMessage('system', 'Usage: /extend <tokens|cost|time> <amount>');
              return;
            }
            try {
              const [what, amount] = args;
              const value = parseFloat(amount);
              if (isNaN(value)) {
                addMessage('error', 'Invalid amount');
                return;
              }
              const limits = agent.getBudgetLimits();
              if (!limits) {
                addMessage('system', 'Budget not available');
                return;
              }
              if (what === 'tokens') {
                agent.extendBudget({ maxTokens: limits.maxTokens + value });
                addMessage('system', `Token budget extended to ${(limits.maxTokens + value).toLocaleString()}`);
              } else if (what === 'cost') {
                agent.extendBudget({ maxCost: limits.maxCost + value });
                addMessage('system', `Cost budget extended to $${(limits.maxCost + value).toFixed(2)}`);
              } else if (what === 'time') {
                agent.extendBudget({ maxDuration: limits.maxDuration + value * 1000 });
                addMessage('system', `Time budget extended to ${Math.round((limits.maxDuration + value * 1000) / 1000)}s`);
              } else {
                addMessage('system', 'Unknown budget type. Use: tokens, cost, or time');
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          // Tools
          case 'tools': {
            const allTools = agent.getTools();
            const builtInTools = allTools.filter(t => !t.name.startsWith('mcp_'));
            const mcpTools = allTools.filter(t => t.name.startsWith('mcp_'));
            const mcpStats = mcpClient.getContextStats();

            addMessage('system', [
              `Agent Tools (${allTools.length} total):`,
              ``,
              `Built-in (${builtInTools.length}):`,
              ...builtInTools.map(t => `  • ${t.name} - ${t.description?.slice(0, 50) || 'No description'}...`),
              ``,
              `MCP Loaded (${mcpTools.length}/${mcpStats.totalTools}):`,
              ...(mcpTools.length > 0
                ? mcpTools.slice(0, 10).map(t => `  • ${t.name}`)
                : ['  (none loaded - use /mcp search <query> to load)']),
              mcpTools.length > 10 ? `  ... and ${mcpTools.length - 10} more` : '',
            ].filter(Boolean).join('\n'));
            return;
          }

          // Subagents
          case 'agents':
            try {
              const agentList = agent.formatAgentList();
              addMessage('system', `Available Agents:\n${agentList}`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'spawn':
            if (args.length < 2) {
              addMessage('system', 'Usage: /spawn <agent-name> <task>');
              return;
            }
            setIsProcessing(true);
            setStatus(s => ({ ...s, mode: 'spawning' }));
            try {
              const [agentName, ...taskParts] = args;
              const task = taskParts.join(' ');
              const result = await agent.spawnAgent(agentName, task);
              addMessage('assistant', `Agent ${agentName}: ${result.success ? 'Success' : 'Failed'}\n${result.output}`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            setIsProcessing(false);
            setStatus(s => ({ ...s, mode: 'ready' }));
            return;

          case 'find':
            if (!args.length) {
              addMessage('system', 'Usage: /find <query>');
              return;
            }
            try {
              const matches = agent.findAgentsForTask(args.join(' '));
              if (matches.length === 0) {
                addMessage('system', 'No matching agents found.');
              } else {
                addMessage('system', `Matching Agents:\n${matches.map((a, i) => `  ${i + 1}. ${a.name} - ${a.description?.split('.')[0] || ''}`).join('\n')}`);
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'suggest':
            if (!args.length) {
              addMessage('system', 'Usage: /suggest <task>');
              return;
            }
            setIsProcessing(true);
            setStatus(s => ({ ...s, mode: 'suggesting' }));
            try {
              const { suggestions, shouldDelegate, delegateAgent } = await agent.suggestAgentForTask(args.join(' '));
              if (suggestions.length === 0) {
                addMessage('system', 'No specialized agent recommended. Main agent should handle this.');
              } else {
                addMessage('system', [
                  `Agent Suggestions:`,
                  ...suggestions.map((s, i) => `  ${i + 1}. ${s.agent.name} (${(s.confidence * 100).toFixed(0)}%) - ${s.reason}`),
                  shouldDelegate && delegateAgent ? `\n💡 Recommended: /spawn ${delegateAgent} ${args.join(' ')}` : '',
                ].join('\n'));
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            setIsProcessing(false);
            setStatus(s => ({ ...s, mode: 'ready' }));
            return;

          case 'auto':
            if (!args.length) {
              addMessage('system', 'Usage: /auto <task>');
              return;
            }
            setIsProcessing(true);
            setStatus(s => ({ ...s, mode: 'auto-routing' }));
            try {
              const result = await agent.runWithAutoRouting(args.join(' '), {
                confidenceThreshold: 0.75,
                confirmDelegate: async () => true, // Auto-confirm in TUI mode
              });
              if ('output' in result) {
                addMessage('assistant', `Subagent: ${result.output}`);
              } else {
                addMessage('assistant', result.response || 'No response');
              }
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            setIsProcessing(false);
            setStatus(s => ({ ...s, mode: 'ready' }));
            return;

          // Testing
          case 'skills':
            try {
              const skills = agent.getSkills();
              if (skills.length === 0) {
                addMessage('system', 'No skills loaded. Add .md files to .skills/ directory.');
              } else {
                addMessage('system', `Skills:\n${skills.map((s: any) => `  ${s.active ? '✓' : '○'} ${s.name} - ${s.description || 'No description'}`).join('\n')}`);
              }
            } catch (e) {
              addMessage('system', 'Skills not available');
            }
            return;

          case 'sandbox':
            addMessage('system', [
              'Sandbox Modes:',
              '  ✓ auto     - Auto-detect best available',
              '  ○ seatbelt - macOS sandbox-exec',
              '  ○ landlock - Linux Landlock LSM',
              '  ○ docker   - Docker container',
              '  ✓ basic    - Allowlist validation',
              '',
              'Use /sandbox test to verify.',
            ].join('\n'));
            return;

          case 'shell':
            addMessage('system', [
              'PTY Shell:',
              '  Persistent shell maintains state across commands:',
              '  • Working directory persists',
              '  • Environment variables retained',
              '  • Command history tracked',
            ].join('\n'));
            return;

          case 'lsp': {
            const activeServers = lspManager.getActiveServers();
            const serverStatus = activeServers.length > 0
              ? activeServers.map(s => `  ✅ ${s}`).join('\n')
              : '  ⚠️  No language servers running';

            const supportedLangs = [
              '  • TypeScript/JavaScript (typescript-language-server)',
              '  • Python (pyright-langserver)',
              '  • Rust (rust-analyzer)',
              '  • Go (gopls)',
            ];

            addMessage('system', [
              '🔍 LSP Integration Status',
              '',
              'Active Servers:',
              serverStatus,
              '',
              'Supported Languages:',
              ...supportedLangs,
              '',
              'How it works:',
              '  edit_file and write_file now return LSP diagnostics',
              '  (errors, warnings) after each change.',
              '',
              activeServers.length === 0
                ? 'To enable: npm install -g typescript-language-server typescript'
                : '✅ LSP diagnostics active for supported files',
            ].join('\n'));
            return;
          }

          case 'tui':
            addMessage('system', [
              'TUI Status: Active (Ink)',
              '',
              'Features:',
              '  • Syntax highlighting',
              '  • Tool call display',
              '  • Progress indicators',
              '  • Keyboard shortcuts',
            ].join('\n'));
            return;

          case 'model': {
            const currentModel = model || process.env.OPENROUTER_MODEL || 'auto (provider default)';
            const popularModels = [
              'anthropic/claude-sonnet-4',
              'anthropic/claude-3.5-sonnet',
              'openai/gpt-4o',
              'google/gemini-2.0-flash-exp',
              'deepseek/deepseek-chat',
            ];
            addMessage('system', [
              `🤖 Current model: ${currentModel}`,
              '',
              'Popular models:',
              ...popularModels.map(m => `  • ${m}`),
              '',
              '⚠️  Model switching requires restart:',
              `  npx tsx src/main.ts --model <model-name>`,
              '',
              'Or set OPENROUTER_MODEL in .env',
            ].join('\n'));
            return;
          }

          case 'theme': {
            const availableThemes = getThemeNames();
            if (!args[0]) {
              addMessage('system', [
                `Current theme: ${currentThemeName}`,
                `Available: ${availableThemes.join(', ')}`,
                '',
                'Usage: /theme <name>',
              ].join('\n'));
              return;
            }
            const newTheme = args[0].toLowerCase();
            if (availableThemes.includes(newTheme) || newTheme === 'auto') {
              setCurrentThemeName(newTheme);
              addMessage('system', `✅ Theme changed to: ${newTheme}`);
            } else {
              addMessage('system', `❌ Unknown theme: ${newTheme}\nAvailable: ${availableThemes.join(', ')}`);
            }
            return;
          }

          default:
            addMessage('system', `Unknown command: /${cmd}. Try /help`);
        }
      }, [addMessage, exit, agent, mcpClient, sessionStore, compactor, model, currentThemeName]);

      const handleSubmit = useCallback(async (input: string) => {
        const trimmed = input.trim();
        if (!trimmed) return;

        addMessage('user', trimmed);

        if (trimmed.startsWith('/')) {
          const parts = trimmed.slice(1).split(/\s+/);
          await handleCommand(parts[0], parts.slice(1));
          return;
        }

        setIsProcessing(true);
        setStatus(s => ({ ...s, mode: 'thinking' }));

        // Subscribe to events for live progress
        const unsub = agent.subscribe((event) => {
          if (event.type === 'tool.start') {
            const now = new Date();
            setStatus(s => ({ ...s, mode: `calling ${event.tool}` }));
            setToolCalls(prev => [...prev.slice(-4), {
              id: `${event.tool}-${Date.now()}`,
              name: event.tool,
              args: (event as any).args || {},
              status: 'running' as const,
              startTime: now,
            }]);
          } else if (event.type === 'tool.complete') {
            setStatus(s => ({ ...s, mode: 'thinking' }));
            setToolCalls(prev => prev.map(t => t.name === event.tool ? {
              ...t,
              status: 'success' as const,
              result: (event as any).result,
              duration: t.startTime ? Date.now() - t.startTime.getTime() : undefined,
            } : t));
          } else if (event.type === 'tool.blocked') {
            setToolCalls(prev => prev.map(t => t.name === event.tool ? {
              ...t,
              status: 'error' as const,
              error: (event as any).reason || 'Blocked',
            } : t));
          } else if (event.type === 'llm.start') {
            setStatus(s => ({ ...s, mode: 'thinking', iter: s.iter + 1 }));
          } else if (event.type === 'react.thought') {
            // Show ReAct reasoning step
            const thought = (event as any).thought || '';
            if (thought) {
              setStatus(s => ({ ...s, mode: `💭 ${thought.slice(0, 50)}` }));
            }
          } else if (event.type === 'react.action') {
            // Show ReAct action being taken
            const action = (event as any).action || '';
            if (action) {
              setStatus(s => ({ ...s, mode: `▶ ${action}` }));
            }
          } else if (event.type === 'react.observation') {
            // Show observation received
            setStatus(s => ({ ...s, mode: 'processing result' }));
          }
          // Insight events for verbose feedback (only shown when showThinking is enabled)
          else if (event.type === 'insight.context' && showThinking) {
            const e = event as { currentTokens: number; maxTokens: number; percentUsed: number; messageCount: number };
            addMessage('system', `★ Context: ${e.currentTokens.toLocaleString()}/${e.maxTokens.toLocaleString()} tokens (${e.percentUsed}%) │ ${e.messageCount} messages`);
          } else if (event.type === 'insight.tokens' && showThinking) {
            const e = event as { inputTokens: number; outputTokens: number; cacheReadTokens?: number; cacheWriteTokens?: number; cost?: number; model: string };
            const cacheInfo = e.cacheReadTokens ? ` │ Cache: ${e.cacheReadTokens.toLocaleString()} read` : '';
            const costInfo = e.cost ? ` │ $${e.cost.toFixed(6)}` : '';
            addMessage('system', `★ Tokens: ${e.inputTokens.toLocaleString()} in, ${e.outputTokens.toLocaleString()} out${cacheInfo}${costInfo}`);
          } else if (event.type === 'insight.tool' && showThinking) {
            const e = event as { tool: string; summary: string; durationMs: number; success: boolean };
            const icon = e.success ? '✓' : '✗';
            addMessage('system', `  ${icon} ${e.tool}: ${e.summary} (${e.durationMs}ms)`);
          } else if (event.type === 'insight.routing' && showThinking) {
            const e = event as { model: string; reason: string; complexity?: string };
            const complexityInfo = e.complexity ? ` [${e.complexity}]` : '';
            addMessage('system', `★ Model: ${e.model}${complexityInfo} - ${e.reason}`);
          }
        });

        try {
          const result = await agent.run(trimmed);
          const metrics = agent.getMetrics();
          setStatus({ iter: metrics.llmCalls, tokens: metrics.totalTokens, cost: metrics.estimatedCost, mode: 'ready' });

          // Show response with metrics
          const response = result.response || result.error || 'No response';
          const durationSec = (metrics.duration / 1000).toFixed(1);
          const metricsLine = [
            '',
            '───────────────────────────────────────',
            `📊 ${metrics.inputTokens.toLocaleString()} in │ ${metrics.outputTokens.toLocaleString()} out │ 🔧 ${metrics.toolCalls} tools │ ⏱️ ${durationSec}s`,
          ].join('\n');
          addMessage('assistant', response + metricsLine);

          // Auto-checkpoint after Q&A cycle (force=true for every Q&A)
          persistenceDebug.log('[TUI] Attempting auto-checkpoint');
          const checkpoint = agent.autoCheckpoint(true);
          if (checkpoint) {
            addMessage('system', `💾 Auto-checkpoint: ${checkpoint.id}`);
            persistenceDebug.log('[TUI] Auto-checkpoint created in agent', {
              id: checkpoint.id,
              label: checkpoint.label,
              messageCount: checkpoint.state.messages?.length ?? 0,
              iteration: checkpoint.state.iteration,
            });

            // Persist checkpoint to session store for cross-session recovery
            try {
              saveCheckpointToStore(sessionStore, {
                id: checkpoint.id,
                label: checkpoint.label,
                messages: checkpoint.state.messages,
                iteration: checkpoint.state.iteration,
                metrics: checkpoint.state.metrics,
                plan: checkpoint.state.plan,
                memoryContext: checkpoint.state.memoryContext,
              });
            } catch (ckptErr) {
              // Log error in debug mode, otherwise silent
              persistenceDebug.error('[TUI] Failed to persist checkpoint to store', ckptErr);
              if (persistenceDebug.isEnabled()) {
                addMessage('system', `⚠️ Checkpoint persistence failed: ${(ckptErr as Error).message}`);
              }
            }
          } else {
            persistenceDebug.log('[TUI] No checkpoint created (autoCheckpoint returned null)');
          }
        } catch (e) {
          addMessage('error', (e as Error).message);
        } finally {
          unsub();
          setIsProcessing(false);
          setToolCalls([]);
        }
      }, [addMessage, handleCommand]);

      useInput((input, key) => {
        // Ctrl+C to exit
        if (key.ctrl && input === 'c') {
          agent.cleanup().then(() => mcpClient.cleanup()).then(() => lspManager.cleanup()).then(() => exit());
          return;
        }
        // Ctrl+L to clear screen
        if (key.ctrl && input === 'l') {
          setMessages([]);
          setToolCalls([]);
          return;
        }
        // Ctrl+P for command palette/help
        if (key.ctrl && input === 'p') {
          addMessage('system', [
            '╭────────────────────────────────────────────────────╮',
            '│              ⌘ Command Palette ⌘                  │',
            '├────────────────────────────────────────────────────┤',
            '│ GENERAL                                            │',
            '│   /help /status /clear /reset /theme /model /tools │',
            '│ SESSIONS                                           │',
            '│   /save /load <id> /sessions /resume /handoff      │',
            '│ CONTEXT                                            │',
            '│   /context /compact /goals                         │',
            '│ MCP                                                 │',
            '│   /mcp /mcp tools /mcp search <q> /mcp stats       │',
            '│ ADVANCED                                           │',
            '│   /react /team /checkpoint /rollback /fork         │',
            '│   /threads /switch /grants /audit                  │',
            '│ SUBAGENTS                                          │',
            '│   /agents /spawn <agent> <task> /find /suggest     │',
            '│   /auto <task>                                     │',
            '│ BUDGET                                             │',
            '│   /budget /extend <tokens|cost|time> <amount>      │',
            '│ DEBUG                                              │',
            '│   /skills /sandbox /shell /lsp /tui                │',
            '├────────────────────────────────────────────────────┤',
            '│ SHORTCUTS                                          │',
            '│   ^C exit  ^L clear  ^P this palette               │',
            '│   ⌥T toggle tool details  ⌥O toggle thinking  ESC cancel │',
            '╰────────────────────────────────────────────────────╯',
          ].join('\n'));
          return;
        }
        // ESC to cancel current processing
        if (key.escape) {
          if (isProcessing) {
            agent.cancel('Cancelled by user (ESC)');
            setIsProcessing(false);
            addMessage('system', '⏹ Cancelled by ESC');
          }
          return;
        }
        // Alt+T / Option+T (produces '†' on macOS) to toggle tool call expansion
        if (input === '†' || (key.meta && input === 't')) {
          setToolCallsExpanded(prev => !prev);
          addMessage('system', toolCallsExpanded ? '○ Tool details: collapsed' : '● Tool details: expanded');
          return;
        }
        // Alt+O / Option+O (produces 'ø' on macOS) to toggle thinking/status display
        if (input === 'ø' || (key.meta && input === 'o')) {
          setShowThinking(prev => !prev);
          addMessage('system', showThinking ? '○ Thinking display: minimal' : '● Thinking display: verbose');
          return;
        }
        if (isProcessing) return;

        if (key.return && inputValue.trim()) {
          handleSubmit(inputValue);
          setInputValue('');
        } else if (key.backspace || key.delete) {
          setInputValue(v => v.slice(0, -1));
        } else if (input && !key.ctrl && !key.meta) {
          setInputValue(v => v + input);
        }
      });

      // ===== DIRECT RENDERING (flicker-free via static icons) =====

      // Update context tokens when status changes
      useEffect(() => {
        const agentState = agent.getState();
        const estimateTokens = (str: string) => Math.ceil(str.length / 3.2);
        const tokens = agentState.messages.reduce((sum, m) =>
          sum + estimateTokens(typeof m.content === 'string' ? m.content : JSON.stringify(m.content)), 0);
        setContextTokens(tokens);
      }, [status.tokens, messages.length]);

      // Track elapsed time during processing
      useEffect(() => {
        if (isProcessing) {
          processingStartRef.current = Date.now();
          setElapsedTime(0);
          const interval = setInterval(() => {
            if (processingStartRef.current) {
              setElapsedTime(Math.floor((Date.now() - processingStartRef.current) / 1000));
            }
          }, 1000);
          return () => clearInterval(interval);
        } else {
          processingStartRef.current = null;
          return undefined;
        }
      }, [isProcessing]);

      // Keep last N messages visible to prevent layout overflow
      const visibleMessages = messages.slice(-15);

      // Helper to format tool args concisely
      const formatToolArgs = (args: Record<string, unknown>): string => {
        const entries = Object.entries(args);
        if (entries.length === 0) return '';
        if (entries.length === 1) {
          const [key, val] = entries[0];
          const valStr = typeof val === 'string' ? val : JSON.stringify(val);
          return valStr.length > 50 ? `${key}: ${valStr.slice(0, 47)}...` : `${key}: ${valStr}`;
        }
        return `{${entries.length} args}`;
      };

      // Status line components
      const modelShort = (model || 'unknown').split('/').pop() || model || 'unknown';
      const contextPct = Math.round((contextTokens / 80000) * 100);
      const costStr = status.cost > 0 ? `$${status.cost.toFixed(4)}` : '$0.00';

      return React.createElement(Box, { flexDirection: 'column', height: '100%' },
        // Messages area - direct rendering
        React.createElement(Box, { flexDirection: 'column', flexGrow: 1, marginBottom: 1 },
          visibleMessages.length === 0
            ? React.createElement(Text, { color: colors.textMuted }, 'Type a message or /help')
            : visibleMessages.map(m => {
                const isUser = m.role === 'user';
                const isAssistant = m.role === 'assistant';
                const isError = m.role === 'error';
                const icon = isUser ? '❯' : isAssistant ? '◆' : isError ? '✖' : '●';
                const roleColor = isUser ? '#87CEEB' : isAssistant ? '#98FB98' : isError ? '#FF6B6B' : '#FFD700';
                const label = isUser ? 'You' : isAssistant ? 'Assistant' : isError ? 'Error' : 'System';

                return React.createElement(Box, { key: m.id, marginBottom: 1, flexDirection: 'column' },
                  // Role header
                  React.createElement(Box, { gap: 1 },
                    React.createElement(Text, { color: roleColor, bold: true }, icon),
                    React.createElement(Text, { color: roleColor, bold: true }, label),
                    React.createElement(Text, { color: colors.textMuted, dimColor: true },
                      ` ${m.ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`
                    )
                  ),
                  // Message content
                  React.createElement(Box, { marginLeft: 2 },
                    React.createElement(Text, { wrap: 'wrap', color: isError ? colors.error : colors.text }, m.content)
                  )
                );
              })
        ),

        // Tool calls - expandable view
        toolCalls.length > 0 && React.createElement(Box, { flexDirection: 'column', marginBottom: 1 },
          React.createElement(Text, { color: '#DDA0DD', bold: true }, `🔧 Tools ${toolCallsExpanded ? '▼' : '▶'}`),
          ...toolCalls.slice(-5).map(tc => {
            const icon = tc.status === 'success' ? '✓' : tc.status === 'error' ? '✗' : tc.status === 'running' ? '⟳' : '○';
            const statusColor = tc.status === 'success' ? '#98FB98' : tc.status === 'error' ? '#FF6B6B' : tc.status === 'running' ? '#87CEEB' : colors.textMuted;
            const argsStr = formatToolArgs(tc.args);

            // Expanded view shows more details
            if (toolCallsExpanded) {
              return React.createElement(Box, { key: `${tc.id}-${tc.status}`, marginLeft: 2, flexDirection: 'column' },
                React.createElement(Box, { gap: 1 },
                  React.createElement(Text, { color: statusColor }, icon),
                  React.createElement(Text, { color: '#DDA0DD', bold: true }, tc.name),
                  tc.duration ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, `(${tc.duration}ms)`) : null
                ),
                // Show args in expanded mode
                Object.keys(tc.args).length > 0 ? React.createElement(Box, { marginLeft: 3 },
                  React.createElement(Text, { color: colors.textMuted, dimColor: true },
                    JSON.stringify(tc.args, null, 0).slice(0, 100) + (JSON.stringify(tc.args).length > 100 ? '...' : '')
                  )
                ) : null,
                // Show result preview in expanded mode
                (tc.status === 'success' && tc.result) ? React.createElement(Box, { marginLeft: 3 },
                  React.createElement(Text, { color: '#98FB98', dimColor: true },
                    `→ ${String(tc.result).slice(0, 80)}${String(tc.result).length > 80 ? '...' : ''}`
                  )
                ) : null,
                // Show error in expanded mode
                (tc.status === 'error' && tc.error) ? React.createElement(Box, { marginLeft: 3 },
                  React.createElement(Text, { color: '#FF6B6B' }, `✗ ${tc.error}`)
                ) : null
              );
            }

            // Collapsed view (default)
            return React.createElement(Box, { key: `${tc.id}-${tc.status}`, marginLeft: 2, gap: 1 },
              React.createElement(Text, { color: statusColor }, icon),
              React.createElement(Text, { color: '#DDA0DD', bold: true }, tc.name),
              argsStr ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, argsStr) : null,
              tc.duration ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, `(${tc.duration}ms)`) : null
            );
          })
        ),

        // Input box
        React.createElement(Box, {
          borderStyle: 'round',
          borderColor: isProcessing ? colors.textMuted : '#87CEEB',
          paddingX: 1,
        },
          React.createElement(Text, { color: '#98FB98', bold: true }, '❯ '),
          React.createElement(Text, {}, inputValue),
          !isProcessing && React.createElement(Text, { backgroundColor: '#87CEEB', color: '#1a1a2e' }, ' ')
        ),

        // ═══════════════════════════════════════════════════════════════════════
        // FIXED STATUS BAR - Always visible at bottom (like Claude Code)
        // Shows: [action indicator] current mode • elapsed time • tokens • cost
        // ═══════════════════════════════════════════════════════════════════════
        React.createElement(Box, {
          borderStyle: 'single',
          borderColor: isProcessing ? colors.info : colors.textMuted,
          paddingX: 1,
          justifyContent: 'space-between',
        },
          // Left: Current action/mode with indicator
          React.createElement(Box, { gap: 1 },
            // Status indicator (spinning when processing)
            React.createElement(Text, {
              color: isProcessing ? colors.info : '#98FB98',
              bold: isProcessing,
            }, isProcessing ? '⏳' : '●'),
            // Current mode/action
            React.createElement(Text, {
              color: isProcessing ? colors.info : colors.text,
              bold: isProcessing,
            }, isProcessing
              ? (status.mode.length > 40 ? status.mode.slice(0, 37) + '...' : status.mode)
              : 'ready'
            ),
            // Elapsed time when processing
            isProcessing && elapsedTime > 0 && React.createElement(Text, {
              color: colors.textMuted,
              dimColor: true,
            }, `• ${elapsedTime}s`),
            // Iteration count
            status.iter > 0 && React.createElement(Text, {
              color: colors.textMuted,
              dimColor: true,
            }, `• iter ${status.iter}`)
          ),
          // Right: Stats and shortcuts
          React.createElement(Box, { gap: 2 },
            // Model
            React.createElement(Text, { color: '#DDA0DD', dimColor: true }, modelShort),
            // Context usage
            React.createElement(Text, {
              color: contextPct > 70 ? '#FFD700' : colors.textMuted,
              dimColor: true,
            }, `${(contextTokens / 1000).toFixed(1)}k`),
            // Cost
            React.createElement(Text, { color: '#98FB98', dimColor: true }, costStr),
            // Git branch
            gitBranch ? React.createElement(Text, { color: '#87CEEB', dimColor: true }, ` ${gitBranch}`) : null,
            // Shortcuts hint
            React.createElement(Text, { color: colors.textMuted, dimColor: true }, 'ESC:cancel ^P:help')
          )
        )
      );
    };

    // Render TUI (don't clear in debug mode so we can see initialization messages)
    if (!persistenceDebug.isEnabled()) {
      console.clear();
    } else {
      console.log('\n--- TUI Starting (debug mode - console not cleared) ---\n');
    }
    const instance = render(React.createElement(TUIApp));
    await instance.waitUntilExit();
    await agent.cleanup();
    await mcpClient.cleanup();
    await lspManager.cleanup();

  } catch (error) {
    console.error('⚠️  TUI failed:', (error as Error).message);
    console.log('   Falling back to legacy mode.');
    return startProductionREPL(provider, options);
  }
}

// =============================================================================
// MAIN
// =============================================================================

async function main(): Promise<void> {
  const args = parseArgs();

  // Enable debug mode if requested
  if (args.debug) {
    persistenceDebug.enable();
  }

  if (args.version) {
    console.log(`attocode v${VERSION}`);
    return;
  }

  if (args.help) {
    showHelp();
    return;
  }

  // Handle init command
  if (args.init) {
    await runInit();
    return;
  }

  // First-run check
  if (isFirstRun() && !hasUsableProvider()) {
    console.log(getFirstRunMessage());
    console.log('\nRun "attocode init" to set up.\n');
    process.exit(1);
  }

  const useTUI = shouldUseTUI(args);

  // Load user config from ~/.config/attocode/config.json
  const userConfig = loadUserConfig();

  console.log('🔌 Detecting LLM provider...');

  let provider: LLMProviderWithTools;
  try {
    // Use preferred provider from config if available
    const preferredProvider = userConfig?.providers?.default;
    const baseProvider = await getProvider(preferredProvider);

    if (!('chatWithTools' in baseProvider)) {
      console.error('❌ Provider does not support native tool use.');
      console.error('   Set OPENROUTER_API_KEY to use this lesson.');
      process.exit(1);
    }

    provider = baseProvider as LLMProviderWithTools;
  } catch (error) {
    console.error('❌ Failed to initialize provider:', (error as Error).message);
    console.error('\nSet one of: OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY');
    process.exit(1);
  }

  // Resolve model: CLI args > env var > user config > provider default
  const resolvedModel = args.model || process.env.OPENROUTER_MODEL || userConfig?.model || provider.defaultModel;
  console.log(`✓ Using ${provider.name} (${resolvedModel})`);
  if (args.trace) {
    console.log(`📊 Trace capture enabled → .traces/ (Lesson 26)`);
  }
  console.log('');

  if (args.task) {
    // Single task mode
    const registry = createStandardRegistry(args.permission);
    const tools = convertToolsFromRegistry(registry);
    const adaptedProvider = new ProviderAdapter(provider, resolvedModel);

    const agent = createProductionAgent({
      provider: adaptedProvider,
      tools,
      model: resolvedModel,
      maxIterations: args.maxIterations,
      humanInLoop: false, // Disable for non-interactive
      observability: args.trace ? {
        enabled: true,
        traceCapture: {
          enabled: true,
          outputDir: '.traces',
          captureMessageContent: true,
          captureToolResults: true,
        },
      } : undefined,
    });

    agent.subscribe(createEventDisplay());

    console.log(`📋 Task: ${args.task}\n`);

    const result = await agent.run(args.task);

    console.log('\n' + '='.repeat(60));
    console.log(result.success ? '✅ Task completed' : '⚠️ Task incomplete');
    console.log('='.repeat(60));
    console.log(result.response || result.error);

    // Show trace file location if tracing was enabled
    const traceCollector = agent.getTraceCollector();
    if (traceCollector) {
      console.log(`\n📊 Trace saved to: .traces/`);
    }

    await agent.cleanup();
    process.exit(result.success ? 0 : 1);
  } else {
    // Interactive mode
    if (useTUI) {
      console.log('🖥️  Starting TUI mode (use --legacy for readline)');
      await startTUIMode(provider, {
        permissionMode: args.permission,
        maxIterations: args.maxIterations,
        model: resolvedModel,
        trace: args.trace,
        theme: args.theme,
      });
    } else {
      await startProductionREPL(provider, {
        permissionMode: args.permission,
        maxIterations: args.maxIterations,
        model: resolvedModel,
        trace: args.trace,
      });
    }
  }
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
