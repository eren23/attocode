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
  formatSessionList,
  MCPClient,
  createMCPClient,
  formatServerList,
  Compactor,
  createCompactor,
  formatCompactionResult,
  getContextUsage,
  createMCPMetaTools,
} from './integrations/index.js';

// Session store type that works with both SQLite and JSONL
type AnySessionStore = SQLiteStore | SessionStore;

/**
 * Save checkpoint to session store (works with both SQLite and JSONL).
 */
function saveCheckpointToStore(
  store: AnySessionStore,
  checkpoint: { id: string; label?: string; messages: unknown[]; iteration: number; metrics?: unknown }
): void {
  if ('saveCheckpoint' in store && typeof store.saveCheckpoint === 'function') {
    // SQLite store
    store.saveCheckpoint(
      {
        id: checkpoint.id,
        label: checkpoint.label,
        messages: checkpoint.messages,
        iteration: checkpoint.iteration,
        metrics: checkpoint.metrics,
      },
      checkpoint.label || `auto-checkpoint-${checkpoint.id}`
    );
  } else if ('appendEntry' in store && typeof store.appendEntry === 'function') {
    // JSONL store - use appendEntry with checkpoint type
    store.appendEntry({
      type: 'checkpoint',
      data: {
        id: checkpoint.id,
        label: checkpoint.label,
        messages: checkpoint.messages,
        iteration: checkpoint.iteration,
        metrics: checkpoint.metrics,
        createdAt: new Date().toISOString(),
      },
    });
  }
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
  const mcpClient = await createMCPClient({
    configPath: join(__dirname, '.mcp.json'),
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
  });

  // Subscribe to events
  agent.subscribe(createEventDisplay());

  // Initialize session storage (try SQLite, fall back to JSONL if native module fails)
  let sessionStore: AnySessionStore;
  try {
    sessionStore = await createSQLiteStore({ baseDir: '.agent/sessions' });
  } catch (sqliteError) {
    console.log(c('⚠️  SQLite unavailable, using JSONL fallback', 'yellow'));
    sessionStore = await createSessionStore({ baseDir: '.agent/sessions' });
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

  // Create a new session
  const sessionId = await sessionStore.createSession();

  // Welcome
  console.log(`
${c('╔════════════════════════════════════════════════════════════════╗', 'cyan')}
${c('║          ATTOCODE - PRODUCTION CODING AGENT                ║', 'cyan')}
${c('║                                                                 ║', 'cyan')}
${c('║  A fully-featured coding agent with all lessons integrated:    ║', 'cyan')}
${c('║  • Memory & Planning (Lessons 14-16)                           ║', 'cyan')}
${c('║  • Multi-Agent & ReAct (Lessons 17-18)                         ║', 'cyan')}
${c('║  • Observability & Safety (Lessons 19-21)                      ║', 'cyan')}
${c('║  • Execution Policies (Lesson 23)                              ║', 'cyan')}
${c('║  • Threads & Checkpoints (Lesson 24)                           ║', 'cyan')}
${c('╚════════════════════════════════════════════════════════════════╝', 'cyan')}
`);
  console.log(c(`Session: ${sessionId}`, 'dim'));
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
        const checkpoint = agent.autoCheckpoint(true);
        if (checkpoint) {
          console.log(c(`💾 Auto-checkpoint: ${checkpoint.id}`, 'dim'));

          // Persist checkpoint to session store for cross-session recovery
          try {
            saveCheckpointToStore(sessionStore, {
              id: checkpoint.id,
              label: checkpoint.label,
              messages: checkpoint.state.messages,
              iteration: checkpoint.state.iteration,
              metrics: checkpoint.state.metrics,
            });
          } catch {
            // Silently ignore persistence errors
          }
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

${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
${c('SHORTCUTS', 'bold')}
  ${c('Ctrl+C', 'yellow')}  Exit          ${c('Ctrl+L', 'yellow')}  Clear screen
${c('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'dim')}
`);
      break;

    case '/status':
      const metrics = agent.getMetrics();
      const state = agent.getState();
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
`);
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
        await sessionStore.appendEntry({
          type: 'checkpoint',
          data: {
            messages: state.messages,
            metadata: agent.getMetrics(),
          },
        });
        console.log(c(`✓ Session saved: ${sessionId}`, 'green'));
      } catch (error) {
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
          const entries = await sessionStore.loadSession(loadId);
          if (entries.length === 0) {
            console.log(c(`No entries found for session: ${loadId}`, 'yellow'));
          } else {
            // Find the last checkpoint
            const checkpoint = [...entries].reverse().find(e => e.type === 'checkpoint');
            const checkpointData = checkpoint?.data as { messages?: unknown[] } | undefined;
            if (checkpointData?.messages) {
              agent.loadMessages(checkpointData.messages as any);
              console.log(c(`✓ Loaded ${checkpointData.messages.length} messages from ${loadId}`, 'green'));
            } else {
              console.log(c('No checkpoint found in session', 'yellow'));
            }
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

          // loadSession may be sync (SQLite) or async (JSONL)
          const entriesResult = sessionStore.loadSession(recentSession.id);
          const entries = Array.isArray(entriesResult) ? entriesResult : await entriesResult;

          // Find the last checkpoint
          const checkpoint = [...entries].reverse().find(e => e.type === 'checkpoint');
          const checkpointData = checkpoint?.data as { messages?: unknown[] } | undefined;
          if (checkpointData?.messages) {
            agent.loadMessages(checkpointData.messages as any);
            console.log(c(`✓ Resumed ${checkpointData.messages.length} messages from last session`, 'green'));
          } else {
            // No checkpoint, try to load messages directly from entries
            const messages = entries
              .filter((e: { type: string }) => e.type === 'message')
              .map((e: { data: unknown }) => e.data);
            if (messages.length > 0) {
              agent.loadMessages(messages as any);
              console.log(c(`✓ Resumed ${messages.length} messages from last session`, 'green'));
            } else {
              console.log(c('No messages found in last session', 'yellow'));
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
        console.log(formatSessionList(sessions));
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
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--help' || arg === '-h') {
      result.help = true;
    } else if (arg === '--version' || arg === '-v') {
      result.version = true;
    } else if (arg === '--trace') {
      result.trace = true;
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
  npx tsx src/main.ts [OPTIONS] [TASK]

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

${c('EXAMPLES:', 'bold')}
  ${c('# Interactive mode (auto-detects TUI)', 'dim')}
  npx tsx src/main.ts

  ${c('# Single task execution', 'dim')}
  npx tsx src/main.ts "List all TypeScript files"

  ${c('# With specific model', 'dim')}
  npx tsx src/main.ts -m anthropic/claude-sonnet-4 "Explain this code"

  ${c('# Force legacy mode with tracing', 'dim')}
  npx tsx src/main.ts --legacy --trace

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

    // Dynamic imports - using our modular TUI components
    const { render, Box, Text, useApp, useInput } = await import('ink');
    const React = await import('react');
    const { useState, useCallback } = React;
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

    const mcpClient = await createMCPClient({
      configPath: join(__dirname, '.mcp.json'),
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
      observability: trace ? { enabled: true, traceCapture: { enabled: true, outputDir: '.traces' } } : undefined,
    });

    // Initialize session storage (try SQLite, fall back to JSONL if native module fails)
    let sessionStore: AnySessionStore;
    try {
      sessionStore = await createSQLiteStore({ baseDir: '.agent/sessions' });
    } catch {
      console.log('⚠️  SQLite unavailable, using JSONL fallback');
      sessionStore = await createSessionStore({ baseDir: '.agent/sessions' });
    }
    const compactor = createCompactor(adaptedProvider, {
      tokenThreshold: 80000,
      preserveRecentCount: 10,
    });
    const currentSessionId = await sessionStore.createSession();

    // Initial theme (will be stateful inside component)
    const initialTheme = getTheme(theme);

    // TUI Component
    const TUIApp = () => {
      const { exit } = useApp();
      const [messages, setMessages] = useState<Array<{ id: string; role: string; content: string; ts: Date }>>([]);
      const [inputValue, setInputValue] = useState('');
      const [isProcessing, setIsProcessing] = useState(false);
      const [status, setStatus] = useState({ iter: 0, tokens: 0, cost: 0, mode: 'ready' });
      const [toolCalls, setToolCalls] = useState<ToolCallDisplay[]>([]);
      const [currentThemeName, setCurrentThemeName] = useState<string>(theme);

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
            addMessage('system', [
              `Session Status:`,
              `  Status: ${agentState.status} | Iteration: ${agentState.iteration}`,
              `  Messages: ${agentState.messages.length}`,
              `  Tokens: ${metrics.totalTokens.toLocaleString()} (${metrics.inputTokens} in / ${metrics.outputTokens} out)`,
              `  LLM Calls: ${metrics.llmCalls} | Tool Calls: ${metrics.toolCalls}`,
              `  Duration: ${metrics.duration}ms | Cost: $${metrics.estimatedCost.toFixed(4)}`,
            ].join('\n'));
            return;
          }

          case 'help':
          case 'h':
            addMessage('system', [
              'Available Commands:',
              '',
              'General: /quit /clear /status /reset /help /model /theme /tools',
              'Sessions: /save /load <id> /sessions /resume',
              'Context: /context /compact',
              'MCP: /mcp /mcp tools /mcp search <query> /mcp stats',
              'Advanced: /react <task> /team <task> /checkpoint /rollback /fork /threads /switch',
              'Subagents: /agents /spawn <agent> <task> /find <query> /suggest <task> /auto <task>',
              'Budget: /budget /extend <type> <amount>',
              'Testing: /skills /sandbox /shell /lsp /tui',
              '',
              'Shortcuts: Ctrl+C (quit) | Ctrl+L (clear)',
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
              await sessionStore.appendEntry({
                type: 'checkpoint',
                data: { messages: agentState.messages, metadata: agent.getMetrics() },
              });
              addMessage('system', `Session saved: ${currentSessionId}`);
            } catch (e) {
              addMessage('error', (e as Error).message);
            }
            return;

          case 'load':
            if (!args[0]) {
              addMessage('system', 'Usage: /load <session-id>');
              return;
            }
            try {
              const loadResult = sessionStore.loadSession(args[0]);
              const loadEntries = Array.isArray(loadResult) ? loadResult : await loadResult;
              const checkpoint = [...loadEntries].reverse().find((e: any) => e.type === 'checkpoint');
              const checkpointData = checkpoint?.data as { messages?: unknown[] } | undefined;
              if (checkpointData?.messages) {
                agent.loadMessages(checkpointData.messages as any);
                // Sync TUI with loaded messages
                const loadedMsgs = agent.getState().messages;
                const syncedLoaded = loadedMsgs.map((m, i) => ({
                  id: `msg-${i}`,
                  role: m.role,
                  content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
                  ts: new Date(),
                }));
                setMessages(syncedLoaded);
                addMessage('system', `Loaded ${checkpointData.messages.length} messages from ${args[0]}`);
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

              const resumeResult = sessionStore.loadSession(recentSess.id);
              const resumeEntries = Array.isArray(resumeResult) ? resumeResult : await resumeResult;
              const resumeCheckpoint = [...resumeEntries].reverse().find((e: any) => e.type === 'checkpoint');
              const resumeData = resumeCheckpoint?.data as { messages?: unknown[] } | undefined;

              if (resumeData?.messages) {
                agent.loadMessages(resumeData.messages as any);
              } else {
                const msgs = resumeEntries
                  .filter((e: any) => e.type === 'message')
                  .map((e: any) => e.data);
                if (msgs.length > 0) {
                  agent.loadMessages(msgs as any);
                }
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
              if (sessions.length === 0) {
                addMessage('system', 'No saved sessions.');
              } else {
                addMessage('system', `Sessions (${sessions.length}):\n${sessions.slice(0, 10).map((s: any) => `  ${s.id} - ${new Date(s.created).toLocaleString()}`).join('\n')}`);
              }
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
        setStatus(s => ({ ...s, mode: 'running' }));

        // Subscribe to events
        const unsub = agent.subscribe((event) => {
          if (event.type === 'tool.start') {
            const now = new Date();
            setToolCalls(prev => [...prev.slice(-4), {
              id: `${event.tool}-${Date.now()}`,
              name: event.tool,
              args: (event as any).args || {},
              status: 'running' as const,
              startTime: now,
            }]);
          } else if (event.type === 'tool.complete') {
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
          }
        });

        try {
          const result = await agent.run(trimmed);
          const metrics = agent.getMetrics();
          setStatus({ iter: metrics.llmCalls, tokens: metrics.totalTokens, cost: metrics.estimatedCost, mode: 'ready' });

          // Show response with metrics
          const response = result.response || result.error || 'No response';
          const totalTokens = metrics.inputTokens + metrics.outputTokens;
          const durationSec = (metrics.duration / 1000).toFixed(1);
          const metricsLine = [
            '',
            '───────────────────────────────────────',
            `📊 ${metrics.inputTokens.toLocaleString()} in │ ${metrics.outputTokens.toLocaleString()} out │ 🔧 ${metrics.toolCalls} tools │ ⏱️ ${durationSec}s`,
          ].join('\n');
          addMessage('assistant', response + metricsLine);

          // Auto-checkpoint after Q&A cycle (force=true for every Q&A)
          const checkpoint = agent.autoCheckpoint(true);
          if (checkpoint) {
            addMessage('system', `💾 Auto-checkpoint: ${checkpoint.id}`);

            // Persist checkpoint to session store for cross-session recovery
            try {
              saveCheckpointToStore(sessionStore, {
                id: checkpoint.id,
                label: checkpoint.label,
                messages: checkpoint.state.messages,
                iteration: checkpoint.state.iteration,
                metrics: checkpoint.state.metrics,
              });
            } catch {
              // Silently ignore persistence errors
            }
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
        if (key.ctrl && input === 'c') {
          agent.cleanup().then(() => mcpClient.cleanup()).then(() => lspManager.cleanup()).then(() => exit());
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

      const visibleMessages = messages.slice(-12);

      // Build StatusDisplay for Header component
      const statusDisplay = {
        mode: status.mode,
        iteration: status.iter,
        tokens: status.tokens,
        maxTokens: 128000, // Approximate context window
        cost: status.cost,
        elapsed: agent.getMetrics().duration,
        model: model || 'auto',
      };

      return React.createElement(Box, { flexDirection: 'column', padding: 1 },
        // Header - using our Header component
        React.createElement(Header, {
          theme: selectedTheme,
          title: 'Attocode',
          status: statusDisplay,
          showMetrics: true,
        }),

        // Spacer after header
        React.createElement(Box, { marginBottom: 1 }),

        // Messages
        React.createElement(Box, { flexDirection: 'column', flexGrow: 1, marginBottom: 1 },
          visibleMessages.length === 0
            ? React.createElement(Text, { color: colors.textMuted }, 'Type a message or /help for commands')
            : visibleMessages.map(m => React.createElement(Box, { key: m.id, marginBottom: 1, flexDirection: 'column' },
                React.createElement(Text, { color: m.role === 'user' ? colors.userMessage : m.role === 'assistant' ? colors.assistantMessage : m.role === 'error' ? colors.error : colors.systemMessage, bold: m.role === 'user' },
                  `[${m.role === 'user' ? 'You' : m.role === 'assistant' ? 'AI' : m.role === 'error' ? '!' : 'Sys'}] `
                ),
                React.createElement(Box, { marginLeft: 2 },
                  React.createElement(Text, { wrap: 'wrap' }, m.content.length > 800 ? m.content.slice(0, 800) + '...' : m.content)
                )
              ))
        ),

        // Tool calls (if any) - using ToolCallList component
        toolCalls.length > 0 && React.createElement(ToolCallList, {
          theme: selectedTheme,
          toolCalls: toolCalls,
          maxVisible: 5,
          title: '🔧 Tools',
        }),

        // Processing indicator
        isProcessing && React.createElement(Box, { marginBottom: 1 },
          React.createElement(Text, { color: colors.info }, `🔄 ${status.mode}...`)
        ),

        // Input
        React.createElement(Box, { borderStyle: 'round', borderColor: isProcessing ? colors.textMuted : colors.borderFocus, paddingX: 1 },
          React.createElement(Text, { color: colors.primary }, '> '),
          React.createElement(Text, {}, inputValue),
          !isProcessing && React.createElement(Text, { backgroundColor: colors.primary, color: colors.textInverse }, ' ')
        ),

        // Footer - using our Footer component
        React.createElement(Footer, {
          theme: selectedTheme,
          mode: status.mode,
          showShortcuts: true,
        })
      );
    };

    // Render TUI
    console.clear();
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

  if (args.version) {
    console.log(`attocode v${VERSION}`);
    return;
  }

  if (args.help) {
    showHelp();
    return;
  }

  const useTUI = shouldUseTUI(args);

  console.log('🔌 Detecting LLM provider...');

  let provider: LLMProviderWithTools;
  try {
    const baseProvider = await getProvider();

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

  // Resolve model from args > env > default
  const resolvedModel = args.model || process.env.OPENROUTER_MODEL || provider.defaultModel;
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
