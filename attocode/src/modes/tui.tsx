/**
 * TUI Mode
 *
 * Full-featured Terminal User Interface for the coding agent.
 * Uses Ink/React for rendering with anti-flicker patterns.
 *
 * Features:
 * - Flicker-free rendering via Ink's <Static> component
 * - Single useInput hook (no input conflicts)
 * - Command palette with fuzzy search (Ctrl+P)
 * - Theme system (dark, light, high-contrast)
 * - LSP integration for code intelligence
 * - Session persistence with checkpoints
 */

import { createProductionAgent } from '../agent/index.js';
import { ProviderAdapter, convertToolsFromRegistry, createTUIApprovalBridge } from '../adapters.js';
import { createStandardRegistry } from '../tools/standard.js';
import { TUIPermissionChecker } from '../tools/permission.js';
import type { LLMProviderWithTools } from '../providers/types.js';
import type { PermissionMode } from '../tools/types.js';

import {
  SQLiteStore,
  createSQLiteStore,
  createSessionStore,
  createMCPClient,
  createCompactor,
  createDeadLetterQueue,
  type DeadLetterQueue,
} from '../integrations/index.js';

import {
  persistenceDebug,
  saveCheckpointToStore,
  loadSessionState,
  type AnySessionStore,
} from '../integrations/persistence/persistence.js';

import { getMCPConfigPaths } from '../paths.js';
import { showSessionPicker, showQuickPicker, formatSessionsTable } from '../session-picker.js';
import { TUI_ROOT_BUDGET } from '../integrations/budget/economics.js';
import { createLSPManager } from '../integrations/lsp/lsp.js';
import { createLSPFileTools } from '../agent-tools/lsp-file-tools.js';
import { initPricingCache } from '../integrations/utilities/openrouter-pricing.js';
import { logger } from '../integrations/utilities/logger.js';

// Import TUI components and utilities
import { TUIApp, type TUIAppProps, checkTUICapabilities } from '../tui/index.js';

// Import REPL mode for fallback
import { startProductionREPL } from './repl.js';

export interface TUIModeOptions {
  permissionMode?: PermissionMode;
  maxIterations?: number;
  model?: string;
  trace?: boolean;
  theme?: 'dark' | 'light' | 'auto';
  swarm?: import('../integrations/swarm/types.js').SwarmConfig;
}

/**
 * Start the TUI mode.
 * Falls back to REPL mode if TUI is not available.
 */
export async function startTUIMode(
  provider: LLMProviderWithTools,
  options: TUIModeOptions = {}
): Promise<void> {
  const {
    permissionMode = 'interactive',
    maxIterations = 500,
    model,
    trace = false,
    theme = 'auto',
    swarm,
  } = options;

  try {
    // Check Ink availability
    const capabilities = await checkTUICapabilities();

    if (!capabilities.inkAvailable) {
      // eslint-disable-next-line no-console
      console.log('! TUI not available. Falling back to legacy mode.');
      return startProductionREPL(provider, options);
    }

    // Enable TUI mode for debug logger to prevent console interference with Ink
    persistenceDebug.enableTUIMode();

    // CRITICAL: Initialize session storage FIRST, before any heavy dynamic imports
    // This ensures better-sqlite3 native module loads cleanly
    let sessionStore: AnySessionStore;

    persistenceDebug.log('[TUI] Initializing session store BEFORE dynamic imports...');

    // Dead letter queue for failed operations (will be null if SQLite unavailable)
    let dlq: DeadLetterQueue | null = null;

    try {
      sessionStore = await createSQLiteStore({ baseDir: '.agent/sessions' });

      if (persistenceDebug.isEnabled()) {
        const sqliteStore = sessionStore as SQLiteStore;
        const stats = sqliteStore.getStats();
        persistenceDebug.log('[TUI] SQLite store initialized!', { sessions: stats.sessionCount, checkpoints: stats.checkpointCount });
      }
      // eslint-disable-next-line no-console
      console.log('+ SQLite session store initialized');

      // Initialize DLQ with SQLite store's database
      const sqliteStore = sessionStore as SQLiteStore;
      dlq = createDeadLetterQueue(sqliteStore.getDatabase());

      // Check for pending DLQ items at startup
      if (dlq.isAvailable()) {
        const pending = dlq.getPending({ limit: 10 });
        if (pending.length > 0) {
          // eslint-disable-next-line no-console
          console.log(`[DLQ] ${pending.length} failed operation(s) pending retry`);
        }
      }
    } catch (sqliteError) {
      const errMsg = (sqliteError as Error).message;
      if (persistenceDebug.isEnabled()) {
        process.stderr.write(`[DEBUG] [TUI] SQLite FAILED: ${errMsg}\n`);
      }
      // eslint-disable-next-line no-console
      console.log('! SQLite unavailable, using JSONL fallback');
      // eslint-disable-next-line no-console
      console.log(`   Error: ${errMsg}`);
      sessionStore = await createSessionStore({ baseDir: '.agent/sessions' });
      // DLQ stays null - not available without SQLite
    }

    // Dynamic imports - using our modular TUI components
    const { render } = await import('ink');
    const React = await import('react');

    // Initialize pricing cache from OpenRouter
    await initPricingCache();

    // Setup agent
    // Create approval bridge FIRST so we can use it for the permission checker
    // This must be created before the registry to inject the TUI permission checker
    const approvalBridge = permissionMode === 'interactive' ? createTUIApprovalBridge() : null;

    // Create registry with the real permission mode
    // For interactive mode, we inject a TUIPermissionChecker that routes through the TUI dialog
    // This prevents the console-based permission prompt from conflicting with Ink
    const registry = createStandardRegistry(permissionMode);

    // In interactive mode, inject TUI permission checker that routes through approval dialog
    if (approvalBridge) {
      const tuiChecker = new TUIPermissionChecker(approvalBridge);
      registry.setPermissionChecker(tuiChecker);
    }

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
        // eslint-disable-next-line no-console
        console.log(`@ LSP: Started ${lspServers.join(', ')} language server(s)`);
      } else {
        // eslint-disable-next-line no-console
        console.log(`* LSP: No language servers found (optional)`);
        // eslint-disable-next-line no-console
        console.log(`   For inline diagnostics: npm i -g typescript-language-server typescript`);
      }
    } catch (err) {
      logger.warn('LSP: Could not start language servers', { error: String((err as Error).message) });
    }

    // Create LSP-enhanced file tools (replaces standard edit_file/write_file)
    const lspFileTools = createLSPFileTools({ lspManager, diagnosticDelay: 500 });

    // Replace standard edit_file/write_file with LSP-enhanced versions
    const standardToolsWithoutFileOps = tools.filter(t => !['edit_file', 'write_file'].includes(t.name));
    const allTools = [...standardToolsWithoutFileOps, ...lspFileTools];

    // approvalBridge is already created above with the permission checker

    const agent = createProductionAgent({
      toolResolver: (toolName: string) => toolName.startsWith('mcp_') ? mcpClient.getFullToolDefinition(toolName) : null,
      mcpToolSummaries: mcpSummaries,
      provider: adaptedProvider,
      tools: allTools,
      model,
      maxIterations,
      budget: TUI_ROOT_BUDGET,
      memory: { enabled: true, types: { episodic: true, semantic: true, working: true } },
      planning: { enabled: true, autoplan: true, complexityThreshold: 6 },
      // Thread management with auto-checkpoints (same as REPL mode)
      threads: {
        enabled: true,
        autoCheckpoint: true,
        checkpointFrequency: 5,
        maxCheckpoints: 10,
        enableRollback: true,
        enableForking: true,
      },
      humanInLoop: permissionMode === 'interactive'
        ? {
            enabled: true,
            riskThreshold: 'moderate',  // Require approval for moderate+ risk tools
            alwaysApprove: [],  // Don't auto-approve anything, show dialog
            neverApprove: ['read_file', 'list_files', 'glob', 'grep', 'task_create', 'task_update', 'task_get', 'task_list'],  // Safe read + task tools
            approvalHandler: approvalBridge!.handler,  // TUI approval handler
            auditLog: true,
          }
        : false,
      // Observability: trace capture to file when --trace, logging disabled in TUI (use debug mode instead)
      observability: trace
        ? { enabled: true, traceCapture: { enabled: true, outputDir: '.traces' }, logging: { enabled: false } }
        : undefined,
      // Codebase context: lazy analysis on first prompt, ready by second turn
      codebaseContext: {
        enabled: true,
        root: process.cwd(),
      },
      // Swarm mode (experimental)
      swarm: swarm || false,
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
    let hadRunFailure = false;
    let lastFailureReason: string | undefined;
    const unsubAgentOutcome = agent.subscribe((event) => {
      if (event.type === 'complete' && !event.result.success) {
        hadRunFailure = true;
        lastFailureReason = event.result.error || 'At least one task failed during this terminal session';
      } else if (event.type === 'error') {
        hadRunFailure = true;
        lastFailureReason = event.error || 'Agent reported an error';
      }
    });

    // Session store was already initialized at the top
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
          // eslint-disable-next-line no-console
          console.log('Goodbye!');
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
    sessionStore.setCurrentSessionId(currentSessionId);

    // Wire durable SQLite worker-results storage into the agent when available.
    if (
      'hasWorkerResultsFeature' in sessionStore &&
      typeof sessionStore.hasWorkerResultsFeature === 'function' &&
      sessionStore.hasWorkerResultsFeature()
    ) {
      agent.setStore(sessionStore as SQLiteStore);
    }

    // Inject DLQ if available for failed operation tracking
    if (dlq) {
      registry.setDeadLetterQueue(dlq, currentSessionId);
      mcpClient.setDeadLetterQueue(dlq, currentSessionId);

      // Set up retry executor for tool operations
      dlq.setRetryExecutor(async (item) => {
        const args = JSON.parse(item.args);
        if (item.operation.startsWith('tool:')) {
          const toolName = item.operation.slice(5);
          try {
            const result = await registry.execute(toolName, args);
            return result.success;
          } catch {
            return false;
          }
        }
        return false;
      });

      // Start periodic retry loop (every 2 minutes, non-blocking)
      dlq.startRetryLoop(120000);
    }

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
        // eslint-disable-next-line no-console
        console.log(`+ Resumed ${sessionState.messages.length} messages from session`);
      }
    }

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

    // Render TUI (don't clear in debug mode so we can see initialization messages)
    if (!persistenceDebug.isEnabled()) {
      // eslint-disable-next-line no-console
      console.clear();
    } else {
      logger.debug('TUI Starting (debug mode - console not cleared)');
    }

    // Start trace session for the entire terminal session (if tracing enabled)
    // Individual tasks within the session will be tracked via startTask/endTask in agent.run()
    const terminalSessionId = `terminal-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const traceCollector = agent.getTraceCollector();
    if (trace && traceCollector) {
      await traceCollector.startSession(
        terminalSessionId,
        undefined, // No single task - this is a terminal session with multiple tasks
        model || 'default',
        { type: 'tui', permissionMode }
      );
      persistenceDebug.log(`[TUI] Trace session started: ${terminalSessionId}`);
    }

    // Pass all required props to the TUIApp
    const tuiProps: TUIAppProps = {
      agent,
      sessionStore: sessionStore as SQLiteStore,
      mcpClient,
      compactor,
      lspManager: {
        cleanup: () => lspManager.cleanup(),
        getActiveServers: () => lspManager.getActiveServers(),
      },
      theme: theme as string,
      model: model || 'default',
      gitBranch,
      currentSessionId,
      formatSessionsTable,
      saveCheckpointToStore,
      loadSessionState,
      persistenceDebug: {
        isEnabled: () => persistenceDebug.isEnabled(),
        log: (message: string, data?: any) => persistenceDebug.log(message, data),
        error: (message: string, error?: any) => persistenceDebug.error(message, error),
      },
      // Approval bridge for TUI permission dialogs (only in interactive mode)
      approvalBridge: approvalBridge || undefined,
    };

    const instance = render(React.createElement(TUIApp, tuiProps));
    try {
      await instance.waitUntilExit();
    } finally {
      // End trace session for the terminal session
      if (trace && traceCollector?.isSessionActive()) {
        try {
          await traceCollector.endSession(
            hadRunFailure
              ? { success: false, failureReason: lastFailureReason ?? 'At least one task failed during this terminal session' }
              : { success: true }
          );
          persistenceDebug.log(`[TUI] Trace session ended -> .traces/`);
        } catch (err) {
          persistenceDebug.error(`[TUI] Failed to end trace session`, err);
        }
      }
      unsubAgentOutcome();
      await agent.cleanup();
      await mcpClient.cleanup();
      await lspManager.cleanup();
    }

  } catch (error) {
    logger.error('TUI failed', { error: String((error as Error).message) });
    // eslint-disable-next-line no-console
    console.log('   Falling back to legacy mode.');
    return startProductionREPL(provider, options);
  }
}
