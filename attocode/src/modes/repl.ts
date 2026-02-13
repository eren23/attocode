/**
 * REPL Mode
 *
 * Legacy readline-based interface for the coding agent.
 * Uses the unified command handler for slash commands.
 */

import * as readline from 'node:readline/promises';
import { stdin, stdout } from 'node:process';

import { createProductionAgent } from '../agent.js';
import { ProviderAdapter, convertToolsFromRegistry, createInteractiveApprovalHandler } from '../adapters.js';
import { createStandardRegistry } from '../tools/standard.js';
import type { LLMProviderWithTools } from '../providers/types.js';
import type { PermissionMode } from '../tools/types.js';

import {
  SQLiteStore,
  createSQLiteStore,
  SessionStore,
  createSessionStore,
  MCPClient,
  createMCPClient,
  createCompactor,
  createMCPMetaTools,
  createDeadLetterQueue,
  type DeadLetterQueue,
} from '../integrations/index.js';
import { initModelCache } from '../integrations/openrouter-pricing.js';
import {
  DEFAULT_POLICY_ENGINE_CONFIG,
  DEFAULT_SANDBOX_CONFIG,
} from '../defaults.js';

import {
  persistenceDebug,
  saveCheckpointToStore,
  loadSessionState,
  type AnySessionStore,
} from '../integrations/persistence.js';

import { createEventDisplay, createJunctureLogger } from '../tui/event-display.js';
import { createTUIRenderer } from '../tui/index.js';
import { getMCPConfigPaths } from '../paths.js';
import { showSessionPicker, showQuickPicker } from '../session-picker.js';
import { registerCleanupResource } from '../core/process-handlers.js';
import { handleCommand, createConsoleOutput } from '../commands/handler.js';
import { logger } from '../integrations/logger.js';

// ANSI color helper
const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  cyan: '\x1b[36m',
  magenta: '\x1b[35m',
};

function c(text: string, color: keyof typeof colors): string {
  return `${colors[color]}${text}${colors.reset}`;
}

export interface REPLOptions {
  permissionMode?: PermissionMode;
  maxIterations?: number;
  model?: string;
  trace?: boolean;
  swarm?: import('../integrations/swarm/types.js').SwarmConfig;
}

/**
 * Start the production REPL mode.
 */
export async function startProductionREPL(
  provider: LLMProviderWithTools,
  options: REPLOptions = {}
): Promise<void> {
  const {
    permissionMode = 'interactive',
    maxIterations = 50,
    model,
    trace = false,
    swarm,
  } = options;

  // Initialize OpenRouter model cache (for context limits + pricing)
  await initModelCache();

  // Create readline interface
  const rl = readline.createInterface({ input: stdin, output: stdout });

  // Create tool registry and convert to production format
  const registry = createStandardRegistry(permissionMode);
  const tools = convertToolsFromRegistry(registry);

  // Create provider adapter
  const adaptedProvider = new ProviderAdapter(provider, model);

  // Create MCP client with lazy loading
  const mcpClient = await createMCPClient({
    configPaths: getMCPConfigPaths(),
    lazyLoading: true,
    alwaysLoadTools: [],
    summaryDescriptionLimit: 100,
    maxToolsPerSearch: 5,
  });

  // Get MCP tool summaries
  const mcpSummaries = mcpClient.getAllToolSummaries().map(s => ({
    name: s.name,
    description: s.description,
  }));

  // Create the production agent
  const agent = createProductionAgent({
    toolResolver: (toolName: string) => {
      if (toolName.startsWith('mcp_')) {
        return mcpClient.getFullToolDefinition(toolName);
      }
      return null;
    },
    mcpToolSummaries: mcpSummaries,
    provider: adaptedProvider,
    tools,
    model,
    maxIterations,
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
      autoReflect: false,
      maxAttempts: 3,
      confidenceThreshold: 0.8,
    },
    observability: {
      enabled: true,
      tracing: { enabled: true, serviceName: 'production-agent', exporter: 'console' },
      metrics: { enabled: true, collectTokens: true, collectCosts: true, collectLatencies: true },
      logging: { enabled: false },
      traceCapture: trace ? {
        enabled: true,
        outputDir: '.traces',
        captureMessageContent: true,
        captureToolResults: true,
        analyzeCacheBoundaries: true,
      } : undefined,
    },
    sandbox: {
      ...DEFAULT_SANDBOX_CONFIG,
      enabled: true,
      resourceLimits: {
        ...DEFAULT_SANDBOX_CONFIG.resourceLimits,
        timeout: 60000,
      },
      allowedPaths: [process.cwd(), process.env.HOME || '/Users', '/tmp'],
    },
    policyEngine: {
      ...DEFAULT_POLICY_ENGINE_CONFIG,
      enabled: true,
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
        { name: 'researcher', description: 'Explores codebases', systemPrompt: 'You are a code researcher.', capabilities: ['read_file', 'list_files', 'glob', 'grep'], authority: 1 },
        { name: 'coder', description: 'Writes code', systemPrompt: 'You are a coder.', capabilities: ['read_file', 'write_file', 'edit_file', 'bash'], authority: 2 },
        { name: 'reviewer', description: 'Reviews code', systemPrompt: 'You are a code reviewer.', capabilities: ['read_file', 'grep', 'glob'], authority: 2 },
        { name: 'architect', description: 'Designs systems', systemPrompt: 'You are a software architect.', capabilities: ['read_file', 'list_files', 'glob'], authority: 3 },
      ],
      consensusStrategy: 'voting',
    },
    react: { enabled: true, maxSteps: 15, stopOnAnswer: true, includeReasoning: true },
    hooks: { enabled: true },
    plugins: { enabled: true },
    lsp: { enabled: true, autoDetect: true },
    swarm: swarm || false,
  });

  // Subscribe to events
  agent.subscribe(createEventDisplay());

  // Initialize session storage
  let sessionStore: AnySessionStore;
  persistenceDebug.log('Initializing session store', { baseDir: '.agent/sessions' });
  try {
    sessionStore = await createSQLiteStore({ baseDir: '.agent/sessions' });
    persistenceDebug.log('SQLite store created successfully');
    // eslint-disable-next-line no-console
    console.log(c('+ SQLite session store initialized', 'green'));

    if (persistenceDebug.isEnabled()) {
      const sqliteStore = sessionStore as SQLiteStore;
      const stats = sqliteStore.getStats();
      persistenceDebug.log('SQLite store stats', stats);
    }

    agent.subscribe(createJunctureLogger(sessionStore as SQLiteStore));
  } catch (sqliteError) {
    persistenceDebug.error('SQLite initialization failed', sqliteError);
    // eslint-disable-next-line no-console
    console.log(c('! SQLite unavailable, using JSONL fallback', 'yellow'));
    // eslint-disable-next-line no-console
    console.log(c(`   Error: ${(sqliteError as Error).message}`, 'dim'));
    sessionStore = await createSessionStore({ baseDir: '.agent/sessions' });
    persistenceDebug.log('JSONL store created as fallback');
  }

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

  // Register cleanup resources
  registerCleanupResource('rl', rl);
  registerCleanupResource('mcpClient', mcpClient);
  registerCleanupResource('agent', agent);
  registerCleanupResource('tui', tui);

  // Add MCP meta-tools
  const mcpMetaTools = createMCPMetaTools(mcpClient, {
    autoLoad: true,
    defaultLimit: 5,
    onToolsLoaded: (loadedTools) => {
      for (const tool of loadedTools) {
        agent.addTool(tool);
      }
      logger.debug('Dynamically loaded MCP tools', { count: loadedTools.length });
    },
  });

  for (const metaTool of mcpMetaTools) {
    agent.addTool(metaTool);
  }

  // Show MCP status
  const mcpServers = mcpClient.listServers();
  if (mcpServers.length > 0) {
    // eslint-disable-next-line no-console
    console.log(c(`MCP Servers: ${mcpServers.length} configured`, 'dim'));
    for (const srv of mcpServers) {
      const icon = srv.status === 'connected' ? '+' : srv.status === 'error' ? 'x' : 'o';
      // eslint-disable-next-line no-console
      console.log(c(`  ${icon} ${srv.name} (${srv.status})${srv.toolCount > 0 ? ` - ${srv.toolCount} tools` : ''}`, 'dim'));
    }
  }

  // Check for existing sessions
  let sessionId: string;
  let resumedSession = false;

  const existingSessions = await sessionStore.listSessions();
  persistenceDebug.log('Checking existing sessions', { count: existingSessions.length });

  if (existingSessions.length > 0) {
    const pickerResult = await showQuickPicker(existingSessions);

    if (pickerResult.action === 'cancel') {
      const fullResult = await showSessionPicker(existingSessions);

      if (fullResult.action === 'resume' && fullResult.sessionId) {
        sessionId = fullResult.sessionId;
        resumedSession = true;
      } else if (fullResult.action === 'cancel') {
        // eslint-disable-next-line no-console
        console.log(c('Goodbye!', 'cyan'));
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
    sessionId = await sessionStore.createSession();
  }

  persistenceDebug.log('Session selected', {
    sessionId,
    resumed: resumedSession,
    storeType: persistenceDebug.storeType(sessionStore),
  });

  sessionStore.setCurrentSessionId(sessionId);

  // Initialize DLQ if SQLite is available
  let dlq: DeadLetterQueue | null = null;
  if (sessionStore instanceof SQLiteStore) {
    dlq = createDeadLetterQueue(sessionStore.getDatabase());
    if (dlq.isAvailable()) {
      const pending = dlq.getPending({ limit: 10 });
      if (pending.length > 0) {
        // eslint-disable-next-line no-console
        console.log(c(`[DLQ] ${pending.length} failed operation(s) pending retry`, 'yellow'));
      }
      // Wire DLQ to registry and MCP client
      registry.setDeadLetterQueue(dlq, sessionId);
      mcpClient.setDeadLetterQueue(dlq, sessionId);
    }
  }

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
      // eslint-disable-next-line no-console
      console.log(c(`+ Resumed ${sessionState.messages.length} messages from session`, 'green'));
    }
  }

  // Welcome banner
  // eslint-disable-next-line no-console
  console.log(`
${c('----------------------------------------------------------------------', 'dim')}
${c('                    ATTOCODE - PRODUCTION CODING AGENT', 'bold')}
${c('----------------------------------------------------------------------', 'dim')}
`);
  // eslint-disable-next-line no-console
  console.log(c(`Session: ${sessionId}${resumedSession ? ' (resumed)' : ''}`, 'dim'));
  // eslint-disable-next-line no-console
  console.log(c(`Model: ${model || provider.defaultModel}`, 'dim'));
  // eslint-disable-next-line no-console
  console.log(c(`Permission mode: ${permissionMode}`, 'dim'));
  // eslint-disable-next-line no-console
  console.log(c('\nType your request, or /help for commands.\n', 'dim'));

  // Create command context
  const commandOutput = createConsoleOutput();

  // Start trace session for the entire terminal session (if tracing enabled)
  // Individual tasks within the session will be tracked via startTask/endTask
  const terminalSessionId = `terminal-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const traceCollector = agent.getTraceCollector();
  if (trace && traceCollector) {
    await traceCollector.startSession(
      terminalSessionId,
      undefined, // No single task - this is a terminal session with multiple tasks
      model || provider.defaultModel,
      { type: 'repl', permissionMode }
    );
    // eslint-disable-next-line no-console
    console.log(c(`Trace session started: ${terminalSessionId}`, 'dim'));
  }

  try {
    while (true) {
      // Generate prompt with mode indicator
      const modeInfo = agent.getModeInfo();
      const pendingCount = agent.getPendingChangeCount();
      let prompt = '';
      if (modeInfo.name !== 'Build') {
        prompt = `${modeInfo.color}${modeInfo.icon}\x1b[0m `;
        if (pendingCount > 0) {
          prompt += c(`[${pendingCount}] `, 'yellow');
        }
      }
      prompt += c('You: ', 'green');

      const input = await rl.question(prompt);
      const trimmed = input.trim();

      if (!trimmed) continue;

      // Handle commands
      if (trimmed.startsWith('/')) {
        const [cmd, ...args] = trimmed.split(/\s+/);
        const result = await handleCommand(cmd.toLowerCase(), args, {
          agent,
          sessionId,
          output: commandOutput,
          integrations: { sessionStore, mcpClient, compactor },
          rl,
        });
        if (result === 'quit') {
          // eslint-disable-next-line no-console
          console.log(c('Goodbye!', 'cyan'));
          break;
        }
        continue;
      }

      // Run agent
      try {
        const result = await agent.run(trimmed);

        if (result.success) {
          // eslint-disable-next-line no-console
          console.log(c('\n--- Assistant ---', 'magenta'));
          tui.renderAssistantMessage(result.response);
          // eslint-disable-next-line no-console
          console.log(c('-----------------', 'magenta'));
        } else {
          // eslint-disable-next-line no-console
          console.log(c('\n! Task incomplete:', 'yellow'));
          tui.showError(result.error || result.response);
        }

        if (trace && agent.getTraceCollector()) {
          logger.debug('Trace captured', { outputDir: '.traces/' });
        }

        const metrics = result.metrics;
        // eslint-disable-next-line no-console
        console.log(c(`\nTokens: ${metrics.inputTokens} in / ${metrics.outputTokens} out | Tools: ${metrics.toolCalls} | Duration: ${metrics.duration}ms`, 'dim'));

        if (agent.hasPendingPlan()) {
          const changeCount = agent.getPendingChangeCount();
          // eslint-disable-next-line no-console
          console.log(c(`\nPlan Mode: ${changeCount} change(s) queued for approval`, 'yellow'));
          // eslint-disable-next-line no-console
          console.log(c('   Use /show-plan to review, /approve to execute, /reject to discard', 'dim'));
        }

        // Auto-checkpoint
        persistenceDebug.log('Attempting auto-checkpoint');
        const checkpoint = agent.autoCheckpoint(true);
        if (checkpoint) {
          logger.debug('Auto-checkpoint created', { checkpointId: checkpoint.id });
          persistenceDebug.log('Auto-checkpoint created in agent', {
            id: checkpoint.id,
            label: checkpoint.label,
            messageCount: checkpoint.state.messages?.length ?? 0,
            iteration: checkpoint.state.iteration,
          });

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

            if (agent.hasPendingPlan() && 'savePendingPlan' in sessionStore && typeof sessionStore.savePendingPlan === 'function') {
              const pendingPlan = agent.getPendingPlan();
              if (pendingPlan) {
                sessionStore.savePendingPlan(pendingPlan, sessionId);
                persistenceDebug.log('Pending plan saved', { planId: pendingPlan.id, changes: pendingPlan.proposedChanges.length });
              }
            }
          } catch (err) {
            persistenceDebug.error('Failed to persist checkpoint to store', err);
            logger.error('Checkpoint persistence failed', { error: String(err) });
          }
        } else {
          persistenceDebug.log('No checkpoint created (autoCheckpoint returned null)');
        }

      } catch (error) {
        tui.showError((error as Error).message);
      }

      // eslint-disable-next-line no-console
      console.log();
    }
  } finally {
    // End trace session for the terminal session
    if (trace && traceCollector?.isSessionActive()) {
      try {
        await traceCollector.endSession({ success: true });
        // eslint-disable-next-line no-console
        console.log(c(`\nTrace session ended -> .traces/`, 'dim'));
      } catch (err) {
        logger.error('Failed to end trace session', { error: String(err) });
      }
    }

    tui.cleanup();
    await mcpClient.cleanup();
    await agent.cleanup();
    rl.close();
  }
}
