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

// Provider detection and resilience
import { getProvider } from './providers/provider.js';
import { getResilientProvider, createResilientFallbackChain } from './providers/resilient-provider.js';
import type { LLMProviderWithTools } from './providers/types.js';
import { DEFAULT_PROVIDER_RESILIENCE_CONFIG } from './defaults.js';
import type { ProviderResilienceConfig } from './types.js';

// Agent and tools
import { createProductionAgent } from './agent/index.js';
import { ProviderAdapter, convertToolsFromRegistry } from './adapters.js';
import { createStandardRegistry } from './tools/standard.js';

// CLI and configuration
import { parseArgs, showHelp, shouldUseTUI, VERSION } from './cli.js';
import { loadConfig } from './config/index.js';

// First-run and init command
import { runInit } from './commands/init.js';
import { isFirstRun, hasUsableProvider, getFirstRunMessage } from './first-run.js';

// Modes
import { startTUIMode, startProductionREPL } from './modes/index.js';

// Event display for single-task mode
import { createEventDisplay } from './tui/event-display.js';

// Persistence debug for --debug flag
import { persistenceDebug } from './integrations/persistence/persistence.js';

// Process handlers for graceful shutdown
import { installProcessHandlers } from './core/process-handlers.js';

// Health check system
import {
  createHealthChecker,
  createFileSystemHealthCheck,
  createNetworkHealthCheck,
  createProviderHealthCheck,
  createSQLiteHealthCheck,
  formatHealthReport,
} from './integrations/quality/health-check.js';

// Structured logger
import { logger, configureLogger, ConsoleSink, MemorySink } from './integrations/utilities/logger.js';

// Swarm mode support
import { DEFAULT_SWARM_CONFIG, autoDetectWorkerModels, type SwarmConfig } from './integrations/swarm/index.js';
import { loadSwarmYamlConfig, parseSwarmYaml, yamlToSwarmConfig, mergeSwarmConfigs, normalizeSwarmModelConfig } from './integrations/swarm/swarm-config-loader.js';
import { readFileSync } from 'node:fs';

/**
 * Build a SwarmConfig from CLI args.
 * V3: Supports YAML configs with merge order: DEFAULT < yaml < CLI.
 */
async function buildSwarmConfig(
  swarmArg: boolean | string,
  orchestratorModel: string,
  resumeSessionId?: string,
  paidOnly?: boolean,
  orchestratorModelExplicit?: boolean,
): Promise<SwarmConfig> {
  let yamlConfig: Partial<SwarmConfig> | null = null;

  if (typeof swarmArg === 'string') {
    // Explicit config file path
    try {
      const content = readFileSync(swarmArg, 'utf-8');
      if (swarmArg.endsWith('.json')) {
        // JSON: direct parse as SwarmConfig partial
        yamlConfig = JSON.parse(content) as Partial<SwarmConfig>;
      } else {
        // YAML: parse and map
        const parsed = parseSwarmYaml(content);
        yamlConfig = yamlToSwarmConfig(parsed, orchestratorModel);
      }
    } catch (err) {
      logger.warn('[Swarm] Failed to load config', { path: swarmArg, error: String((err as Error).message) });
    }
  } else {
    // Auto-load: try .attocode/swarm.yaml, then ~/.attocode/swarm.yaml
    const rawYaml = loadSwarmYamlConfig();
    if (rawYaml) {
      yamlConfig = yamlToSwarmConfig(rawYaml, orchestratorModel);
    }
  }

  // Resolve 'latest' session ID before merge
  let resolvedResumeId = resumeSessionId;
  if (resolvedResumeId === 'latest') {
    try {
      const { SwarmStateStore } = await import('./integrations/swarm/swarm-state-store.js');
      const stateDir = '.agent/swarm-state';
      const sessions = SwarmStateStore.listSessions(stateDir);
      if (sessions.length > 0) {
        resolvedResumeId = sessions[0].sessionId;
        logger.info('[Swarm] Resuming latest session', { sessionId: resolvedResumeId });
      } else {
        logger.warn('[Swarm] No previous sessions found to resume — starting fresh');
        resolvedResumeId = undefined;
      }
    } catch {
      logger.warn('[Swarm] Could not list sessions — starting fresh');
      resolvedResumeId = undefined;
    }
  }

  // Merge: DEFAULT < yaml < CLI
  const config = mergeSwarmConfigs(DEFAULT_SWARM_CONFIG, yamlConfig, {
    paidOnly,
    orchestratorModel,
    orchestratorModelExplicit,
    resumeSessionId: resolvedResumeId,
  });

  // Normalize malformed model IDs (e.g. anthropic/z-ai/glm-5 -> z-ai/glm-5).
  const normalized = normalizeSwarmModelConfig(config);
  if (normalized.warnings.length > 0) {
    const mode = config.modelValidation?.mode ?? 'autocorrect';
    const onInvalid = config.modelValidation?.onInvalid ?? 'warn';
    if (mode === 'strict' || onInvalid === 'fail') {
      throw new Error(
        `Invalid swarm model configuration:\n${normalized.warnings.join('\n')}`
      );
    }
    for (const warning of normalized.warnings) {
      logger.warn('[Swarm] Model config adjusted', { warning });
    }
  }
  const finalConfig = normalized.config;

  // V3: Pre-flight key check for rate limit awareness
  const apiKey = process.env.OPENROUTER_API_KEY;
  if (apiKey) {
    try {
      const { OpenRouterProvider } = await import('./providers/adapters/openrouter.js');
      const keyInfo = await OpenRouterProvider.checkKeyInfo(apiKey);
      if (!yamlConfig && paidOnly === undefined && keyInfo.isPaid === true) {
        finalConfig.paidOnly = true;
        if (!finalConfig.throttle) {
          finalConfig.throttle = 'paid';
        }
        logger.info('[Swarm] No swarm config found; defaulting to paid-only worker model selection for paid-tier key');
      }
      if (keyInfo.isPaid === false && !finalConfig.paidOnly) {
        logger.info('[Swarm] Free-tier API key detected — throttle will auto-adjust.');
      }
      if (keyInfo.creditsRemaining !== undefined && keyInfo.creditsRemaining < 0.5) {
        logger.warn('[Swarm] Low credits remaining', { credits: `$${keyInfo.creditsRemaining.toFixed(2)}` });
      }
    } catch {
      // Non-fatal: continue without key info
    }
  }

  // Auto-detect workers if none configured
  if (finalConfig.workers.length === 0) {
    if (apiKey) {
      try {
        finalConfig.workers = await autoDetectWorkerModels({
          apiKey,
          orchestratorModel,
          paidOnly: finalConfig.paidOnly,
        });
      } catch {
        // Fall through to hardcoded fallback
      }
    }

    // If still no workers, use hardcoded fallback
    if (finalConfig.workers.length === 0) {
      finalConfig.workers = await autoDetectWorkerModels({
        apiKey: '',
        orchestratorModel,
        paidOnly: finalConfig.paidOnly,
      });
    }
  }

  logger.info('[Swarm] Resolved config', {
    orchestratorModel: finalConfig.orchestratorModel,
    workerCount: finalConfig.workers.length,
    workerModels: finalConfig.workers.map(w => w.model),
    paidOnly: finalConfig.paidOnly ?? false,
    throttle: finalConfig.throttle ?? false,
    totalBudget: finalConfig.totalBudget,
    maxCost: finalConfig.maxCost,
  });

  return finalConfig;
}

// =============================================================================
// MAIN
// =============================================================================

async function main(): Promise<void> {
  // Install process error handlers for graceful shutdown
  installProcessHandlers();

  const args = parseArgs();

  // Enable debug mode if requested
  if (args.debug) {
    persistenceDebug.enable();
  }

  if (args.version) {
    // eslint-disable-next-line no-console
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
    // eslint-disable-next-line no-console
    console.log(getFirstRunMessage());
    // eslint-disable-next-line no-console
    console.log('\nRun "attocode init" to set up.\n');
    process.exit(1);
  }

  const useTUI = shouldUseTUI(args);

  // Load user config (user-level + project-level, validated)
  const { config: userConfig, warnings: configWarnings } = loadConfig();
  for (const warn of configWarnings) {
    logger.warn(`[Config] ${warn}`);
  }

  // eslint-disable-next-line no-console
  console.log('Detecting LLM provider...');

  // Merge provider resilience config with defaults
  const providerResilienceConfig: ProviderResilienceConfig = {
    ...DEFAULT_PROVIDER_RESILIENCE_CONFIG,
    ...(userConfig?.providerResilience || {}),
  };
  const resilienceEnabled = providerResilienceConfig.enabled !== false;

  let provider: LLMProviderWithTools;
  try {
    // Use preferred provider from config if available
    const preferredProvider = userConfig?.providers?.default;

    // Determine if we should use fallback chain (multiple providers configured)
    const hasFallbackProviders =
      providerResilienceConfig.fallbackProviders &&
      providerResilienceConfig.fallbackProviders.length > 0;

    if (resilienceEnabled && hasFallbackProviders) {
      // Use fallback chain with circuit breaker protection
      const chain = await createResilientFallbackChain({
        providers: preferredProvider
          ? [preferredProvider, ...providerResilienceConfig.fallbackProviders!]
          : providerResilienceConfig.fallbackProviders,
        circuitBreaker: providerResilienceConfig.circuitBreaker,
        fallback: providerResilienceConfig.fallbackChain,
        onFallback: providerResilienceConfig.onFallback ?? ((from, to, error) => {
          logger.info('[Resilience] Falling back', { from, to, error: error.message });
        }),
      });

      if (!('chatWithTools' in chain)) {
        logger.error('Provider does not support native tool use.');
        process.exit(1);
      }

      provider = chain as LLMProviderWithTools;
      // eslint-disable-next-line no-console
      console.log(`+ Provider resilience: fallback chain enabled (${providerResilienceConfig.fallbackProviders!.length + 1} providers)`);
    } else if (resilienceEnabled && providerResilienceConfig.circuitBreaker !== false) {
      // Use single provider with circuit breaker protection
      const resilientProvider = await getResilientProvider(preferredProvider, {
        circuitBreaker: providerResilienceConfig.circuitBreaker,
      });

      if (!('chatWithTools' in resilientProvider)) {
        logger.error('Provider does not support native tool use.');
        logger.error('Set OPENROUTER_API_KEY to use this application.');
        process.exit(1);
      }

      provider = resilientProvider as LLMProviderWithTools;
      // eslint-disable-next-line no-console
      console.log('+ Provider resilience: circuit breaker enabled');
    } else {
      // Use basic provider without resilience
      const baseProvider = await getProvider(preferredProvider);

      if (!('chatWithTools' in baseProvider)) {
        logger.error('Provider does not support native tool use.');
        logger.error('Set OPENROUTER_API_KEY to use this application.');
        process.exit(1);
      }

      provider = baseProvider as LLMProviderWithTools;
    }
  } catch (error) {
    logger.error('Failed to initialize provider', { error: String((error as Error).message) });
    logger.error('Set one of: OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY');
    process.exit(1);
  }

  // Resolve model: CLI args > env var > user config > provider default
  const resolvedModel = args.model || process.env.OPENROUTER_MODEL || userConfig?.model || provider.defaultModel;
  // eslint-disable-next-line no-console
  console.log(`+ Using ${provider.name} (${resolvedModel})`);
  if (args.trace) {
    // eslint-disable-next-line no-console
    console.log(`+ Trace capture enabled -> .traces/`);
  }

  // Initialize health checker
  const healthChecker = createHealthChecker({
    onStatusChange: (name, healthy, prev) => {
      // Only warn when something becomes unhealthy (not on initial check)
      if (!healthy && prev !== undefined) {
        logger.warn('[Health] Check became unhealthy', { name });
      }
    },
  });

  // Register health checks
  const fsCheck = createFileSystemHealthCheck('/tmp');
  healthChecker.register(fsCheck.name, fsCheck.check, fsCheck);

  // Network check uses the provider's API endpoint
  const networkCheck = createNetworkHealthCheck('https://api.anthropic.com');
  healthChecker.register(networkCheck.name, networkCheck.check, networkCheck);

  // LLM provider check verifies the provider can respond
  const providerCheck = createProviderHealthCheck(provider as any, provider.name);
  healthChecker.register(providerCheck.name, providerCheck.check, providerCheck);

  // SQLite check verifies session persistence database
  const sqliteCheck = createSQLiteHealthCheck('.agent/sessions/sessions.db');
  healthChecker.register(sqliteCheck.name, sqliteCheck.check, sqliteCheck);

  // Run initial health check (non-blocking)
  healthChecker.checkAll().then(report => {
    if (!report.healthy) {
      const unhealthy = report.checks.filter(c => !c.healthy).map(c => c.name);
      logger.warn('[Health] Some checks failed', { unhealthy: unhealthy.join(', ') });
      if (args.debug) {
        logger.warn(formatHealthReport(report));
      }
    } else if (args.debug) {
      logger.debug('[Health] All checks passed', { totalCount: report.totalCount });
    }
  }).catch(err => {
    // Don't block startup on health check failure
    if (args.debug) {
      logger.warn('[Health] Initial check failed', { error: String(err.message) });
    }
  });

  // eslint-disable-next-line no-console
  console.log('');

  if (args.task) {
    // Single task mode (non-interactive)
    const registry = createStandardRegistry(args.permission);
    const tools = convertToolsFromRegistry(registry);
    const adaptedProvider = new ProviderAdapter(provider, resolvedModel);

    // Build swarm config if --swarm flag is set
    const swarmConfig = args.swarm ? await buildSwarmConfig(args.swarm, resolvedModel, args.swarmResume, args.paidOnly, !!args.model) : undefined;

    const agent = createProductionAgent({
      provider: adaptedProvider,
      tools,
      model: resolvedModel,
      maxIterations: args.maxIterations,
      humanInLoop: false, // Disable for non-interactive
      executionPolicy: { defaultPolicy: 'allow' }, // No user to prompt in non-interactive mode
      codebaseContext: {
        enabled: true,
        root: process.cwd(),
      },
      swarm: swarmConfig || false,
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

    // eslint-disable-next-line no-console
    console.log(`Task: ${args.task}\n`);

    const result = await agent.run(args.task);

    // eslint-disable-next-line no-console
    console.log('\n' + '='.repeat(60));
    // eslint-disable-next-line no-console
    console.log(result.success ? '+ Task completed' : '! Task incomplete');
    // eslint-disable-next-line no-console
    console.log('='.repeat(60));
    // eslint-disable-next-line no-console
    console.log(result.response || result.error);

    // Show trace file location if tracing was enabled
    const traceCollector = agent.getTraceCollector();
    if (traceCollector) {
      // eslint-disable-next-line no-console
      console.log(`\nTrace saved to: .traces/`);
    }

    await agent.cleanup();
    process.exit(result.success ? 0 : 1);
  } else {
    // Interactive mode
    if (useTUI) {
      // eslint-disable-next-line no-console
      console.log('Starting TUI mode (use --no-tui for readline)');
      await startTUIMode(provider, {
        permissionMode: args.permission,
        maxIterations: args.maxIterations,
        model: resolvedModel,
        trace: args.trace,
        theme: args.theme,
        swarm: args.swarm ? await buildSwarmConfig(args.swarm, resolvedModel, args.swarmResume, args.paidOnly, !!args.model) : undefined,
      });
    } else {
      await startProductionREPL(provider, {
        permissionMode: args.permission,
        maxIterations: args.maxIterations,
        model: resolvedModel,
        trace: args.trace,
        swarm: args.swarm ? await buildSwarmConfig(args.swarm, resolvedModel, args.swarmResume, args.paidOnly, !!args.model) : undefined,
      });
    }
  }
}

main().catch((error) => {
  logger.error('Fatal error', { error: String(error) });
  process.exit(1);
});
