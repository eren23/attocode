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
import { createProductionAgent } from './agent.js';
import { ProviderAdapter, convertToolsFromRegistry } from './adapters.js';
import { createStandardRegistry } from './tools/standard.js';

// CLI and configuration
import { parseArgs, showHelp, shouldUseTUI, VERSION } from './cli.js';
import { loadUserConfig } from './config.js';

// First-run and init command
import { runInit } from './commands/init.js';
import { isFirstRun, hasUsableProvider, getFirstRunMessage } from './first-run.js';

// Modes
import { startTUIMode, startProductionREPL } from './modes/index.js';

// Event display for single-task mode
import { createEventDisplay } from './tui/event-display.js';

// Persistence debug for --debug flag
import { persistenceDebug } from './integrations/persistence.js';

// Process handlers for graceful shutdown
import { installProcessHandlers } from './core/process-handlers.js';

// Health check system
import {
  createHealthChecker,
  createFileSystemHealthCheck,
  createNetworkHealthCheck,
  formatHealthReport,
} from './integrations/health-check.js';

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
          console.log(`[Resilience] Falling back from ${from} to ${to}: ${error.message}`);
        }),
      });

      if (!('chatWithTools' in chain)) {
        console.error('Provider does not support native tool use.');
        process.exit(1);
      }

      provider = chain as LLMProviderWithTools;
      console.log(`+ Provider resilience: fallback chain enabled (${providerResilienceConfig.fallbackProviders!.length + 1} providers)`);
    } else if (resilienceEnabled && providerResilienceConfig.circuitBreaker !== false) {
      // Use single provider with circuit breaker protection
      const resilientProvider = await getResilientProvider(preferredProvider, {
        circuitBreaker: providerResilienceConfig.circuitBreaker,
      });

      if (!('chatWithTools' in resilientProvider)) {
        console.error('Provider does not support native tool use.');
        console.error('   Set OPENROUTER_API_KEY to use this application.');
        process.exit(1);
      }

      provider = resilientProvider as LLMProviderWithTools;
      console.log('+ Provider resilience: circuit breaker enabled');
    } else {
      // Use basic provider without resilience
      const baseProvider = await getProvider(preferredProvider);

      if (!('chatWithTools' in baseProvider)) {
        console.error('Provider does not support native tool use.');
        console.error('   Set OPENROUTER_API_KEY to use this application.');
        process.exit(1);
      }

      provider = baseProvider as LLMProviderWithTools;
    }
  } catch (error) {
    console.error('Failed to initialize provider:', (error as Error).message);
    console.error('\nSet one of: OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY');
    process.exit(1);
  }

  // Resolve model: CLI args > env var > user config > provider default
  const resolvedModel = args.model || process.env.OPENROUTER_MODEL || userConfig?.model || provider.defaultModel;
  console.log(`+ Using ${provider.name} (${resolvedModel})`);
  if (args.trace) {
    console.log(`+ Trace capture enabled -> .traces/`);
  }

  // Initialize health checker
  const healthChecker = createHealthChecker({
    onStatusChange: (name, healthy, prev) => {
      // Only warn when something becomes unhealthy (not on initial check)
      if (!healthy && prev !== undefined) {
        console.warn(`[Health] ${name} became unhealthy`);
      }
    },
  });

  // Register health checks
  const fsCheck = createFileSystemHealthCheck('/tmp');
  healthChecker.register(fsCheck.name, fsCheck.check, fsCheck);

  // Network check uses the provider's API endpoint
  const networkCheck = createNetworkHealthCheck('https://api.anthropic.com');
  healthChecker.register(networkCheck.name, networkCheck.check, networkCheck);

  // Run initial health check (non-blocking)
  healthChecker.checkAll().then(report => {
    if (!report.healthy) {
      const unhealthy = report.checks.filter(c => !c.healthy).map(c => c.name);
      console.warn(`[Health] Some checks failed: ${unhealthy.join(', ')}`);
      if (args.debug) {
        console.warn(formatHealthReport(report));
      }
    } else if (args.debug) {
      console.log(`[Health] All ${report.totalCount} checks passed`);
    }
  }).catch(err => {
    // Don't block startup on health check failure
    if (args.debug) {
      console.warn('[Health] Initial check failed:', err.message);
    }
  });

  console.log('');

  if (args.task) {
    // Single task mode (non-interactive)
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

    console.log(`Task: ${args.task}\n`);

    const result = await agent.run(args.task);

    console.log('\n' + '='.repeat(60));
    console.log(result.success ? '+ Task completed' : '! Task incomplete');
    console.log('='.repeat(60));
    console.log(result.response || result.error);

    // Show trace file location if tracing was enabled
    const traceCollector = agent.getTraceCollector();
    if (traceCollector) {
      console.log(`\nTrace saved to: .traces/`);
    }

    await agent.cleanup();
    process.exit(result.success ? 0 : 1);
  } else {
    // Interactive mode
    if (useTUI) {
      console.log('Starting TUI mode (use --no-tui for readline)');
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
