/**
 * Lesson 10: Hook & Event System
 *
 * This lesson demonstrates how to build an extensible architecture
 * using events and hooks. Events enable loose coupling between
 * components, while hooks allow intercepting and modifying behavior.
 *
 * Key concepts:
 * 1. Events for observation (logging, metrics, debugging)
 * 2. Hooks for interception (validation, security, transformation)
 * 3. Priority ordering for predictable execution
 * 4. Error isolation so one hook can't break others
 *
 * Run: npm run lesson:10
 */

import chalk from 'chalk';
import { EventBus, createEvent, waitForEvent } from './event-bus.js';
import { HookRegistry } from './hook-registry.js';
import {
  createLoggingHook,
  registerLoggingHooks,
  registerMetricsHooks,
  createSecurityHook,
  createValidationHook,
  TimingTracker,
} from './built-in-hooks.js';
import type {
  AgentEvent,
  ToolBeforeEvent,
  ToolAfterEvent,
  Metric,
} from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 10: Hook & Event System                       ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: EVENT BUS BASICS
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Event Bus Basics'));
console.log(chalk.gray('─'.repeat(60)));

const eventBus = new EventBus();

// Subscribe to specific event type
const toolSubscription = eventBus.on('tool.before', (event) => {
  console.log(chalk.blue(`  📥 Tool event received: ${event.tool}`));
});

// Subscribe to all events
const globalSubscription = eventBus.onAny((event) => {
  console.log(chalk.gray(`  🌐 Global listener: ${event.type}`));
});

// Emit some events
console.log(chalk.green('\nEmitting tool.before event...'));
await eventBus.emit(
  createEvent('tool.before', {
    tool: 'bash',
    args: { command: 'ls -la' },
  })
);

console.log(chalk.green('\nEmitting session.start event...'));
await eventBus.emit(
  createEvent('session.start', {
    sessionId: 'demo-session-1',
    config: { maxIterations: 10 },
  })
);

// Cleanup
toolSubscription.unsubscribe();
globalSubscription.unsubscribe();
console.log(chalk.gray('\nSubscriptions cleaned up.'));

// =============================================================================
// PART 2: HOOK REGISTRY
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Hook Registry with Priority Ordering'));
console.log(chalk.gray('─'.repeat(60)));

const registry = new HookRegistry({
  errorStrategy: 'continue',
  trackPerformance: true,
  debug: false,
});

// Register hooks with different priorities
registry.register({
  id: 'hook-c',
  event: 'tool.before',
  priority: 150, // Runs last
  handler: () => {
    console.log(chalk.magenta('  3️⃣  Hook C (priority 150) - User hook'));
  },
});

registry.register({
  id: 'hook-a',
  event: 'tool.before',
  priority: 50, // Runs first
  handler: () => {
    console.log(chalk.magenta('  1️⃣  Hook A (priority 50) - System hook'));
  },
});

registry.register({
  id: 'hook-b',
  event: 'tool.before',
  priority: 100, // Runs second
  handler: () => {
    console.log(chalk.magenta('  2️⃣  Hook B (priority 100) - Plugin hook'));
  },
});

console.log(chalk.green('\nExecuting hooks for tool.before event:'));
const event: ToolBeforeEvent = {
  type: 'tool.before',
  tool: 'test-tool',
  args: {},
};

const result = await registry.execute(event);
console.log(chalk.gray(`\n  Hooks executed: ${result.hooksExecuted}`));
console.log(chalk.gray(`  Duration: ${result.durationMs.toFixed(2)}ms`));

// =============================================================================
// PART 3: INTERCEPTING HOOKS (SECURITY)
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Intercepting Hooks - Security Example'));
console.log(chalk.gray('─'.repeat(60)));

// Create a new registry with security hook
const secureRegistry = new HookRegistry({ debug: false });
secureRegistry.register(createSecurityHook());

// Test safe command
console.log(chalk.green('\nTesting safe command: "ls -la"'));
const safeEvent: ToolBeforeEvent = {
  type: 'tool.before',
  tool: 'bash',
  args: { command: 'ls -la' },
};

const safeResult = await secureRegistry.execute(safeEvent);
console.log(
  safeEvent.preventDefault
    ? chalk.red('  ❌ Command BLOCKED')
    : chalk.green('  ✅ Command ALLOWED')
);

// Test dangerous command
console.log(chalk.green('\nTesting dangerous command: "rm -rf /"'));
const dangerousEvent: ToolBeforeEvent = {
  type: 'tool.before',
  tool: 'bash',
  args: { command: 'rm -rf /' },
};

await secureRegistry.execute(dangerousEvent);
console.log(
  dangerousEvent.preventDefault
    ? chalk.red('  ❌ Command BLOCKED (as expected)')
    : chalk.green('  ✅ Command ALLOWED')
);

// =============================================================================
// PART 4: METRICS COLLECTION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Metrics Collection'));
console.log(chalk.gray('─'.repeat(60)));

const metricsRegistry = new HookRegistry();
const collectedMetrics: Metric[] = [];

registerMetricsHooks(metricsRegistry, {
  prefix: 'demo',
  onMetric: (metric) => {
    collectedMetrics.push(metric);
    console.log(
      chalk.cyan(`  📊 Metric: ${metric.name} = ${metric.value} (${metric.type})`)
    );
  },
});

// Simulate tool execution
console.log(chalk.green('\nSimulating tool execution...'));

await metricsRegistry.execute(
  createEvent('tool.before', { tool: 'read_file', args: { path: '/etc/hosts' } })
);

const afterEvent: ToolAfterEvent = {
  type: 'tool.after',
  tool: 'read_file',
  args: { path: '/etc/hosts' },
  result: { success: true, content: '...' },
  durationMs: 42,
};
await metricsRegistry.execute(afterEvent);

console.log(chalk.gray(`\n  Total metrics collected: ${collectedMetrics.length}`));

// =============================================================================
// PART 5: COMBINED EXAMPLE - TOOL WRAPPER
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Complete Tool Wrapper with Hooks'));
console.log(chalk.gray('─'.repeat(60)));

/**
 * This is a complete example showing how hooks integrate with
 * actual tool execution. The wrapper:
 * 1. Emits tool.before and checks if prevented
 * 2. Executes the tool (or mock in this demo)
 * 3. Emits tool.after with result and timing
 */

// Create registry with all hooks
const completeRegistry = new HookRegistry({ trackPerformance: true });
const timingTracker = new TimingTracker();

// Logging (observing)
completeRegistry.register({
  id: 'logger',
  event: 'tool.before',
  priority: 0,
  handler: (event) => {
    console.log(chalk.gray(`  [LOG] Tool ${event.tool} called`));
  },
});

completeRegistry.register({
  id: 'logger-after',
  event: 'tool.after',
  priority: 0,
  handler: (event) => {
    console.log(chalk.gray(`  [LOG] Tool ${event.tool} completed in ${event.durationMs}ms`));
  },
});

// Security (intercepting)
completeRegistry.register({
  id: 'security',
  event: 'tool.before',
  priority: 10,
  canModify: true,
  handler: (event) => {
    if (event.tool === 'dangerous_tool') {
      console.log(chalk.red(`  [SECURITY] Blocking dangerous tool!`));
      event.preventDefault = true;
    }
  },
});

// Metrics (observing)
completeRegistry.register({
  id: 'metrics',
  event: 'tool.after',
  priority: 100,
  handler: (event) => {
    console.log(chalk.cyan(`  [METRICS] Duration: ${event.durationMs}ms`));
  },
});

/**
 * Wrapper function that integrates hooks with tool execution.
 */
async function executeToolWithHooks(
  tool: string,
  args: unknown,
  mockExecutor: (args: unknown) => Promise<unknown>
): Promise<{ success: boolean; result?: unknown; blocked?: boolean }> {
  // Create and emit tool.before event
  const beforeEvent: ToolBeforeEvent = {
    type: 'tool.before',
    tool,
    args,
  };

  const callId = timingTracker.start(tool);
  await completeRegistry.execute(beforeEvent);

  // Check if blocked
  if (beforeEvent.preventDefault) {
    return { success: false, blocked: true };
  }

  // Use modified args if provided
  const finalArgs = beforeEvent.modifiedArgs ?? args;

  // Execute tool
  try {
    const result = await mockExecutor(finalArgs);
    const durationMs = timingTracker.end(callId);

    // Emit tool.after event
    const afterEvent: ToolAfterEvent = {
      type: 'tool.after',
      tool,
      args: finalArgs,
      result,
      durationMs,
    };
    await completeRegistry.execute(afterEvent);

    return { success: true, result };
  } catch (error) {
    const durationMs = timingTracker.end(callId);

    // Emit tool.error event
    await completeRegistry.execute(
      createEvent('tool.error', {
        tool,
        args: finalArgs,
        error: error instanceof Error ? error : new Error(String(error)),
      })
    );

    return { success: false };
  }
}

// Test normal execution
console.log(chalk.green('\nExecuting "read_file" tool:'));
await executeToolWithHooks(
  'read_file',
  { path: '/tmp/test.txt' },
  async () => {
    await new Promise((r) => setTimeout(r, 50)); // Simulate work
    return { content: 'file contents here' };
  }
);

// Test blocked execution
console.log(chalk.green('\nExecuting "dangerous_tool" (should be blocked):'));
const blockedResult = await executeToolWithHooks(
  'dangerous_tool',
  { action: 'delete_everything' },
  async () => ({ deleted: true })
);
console.log(chalk.yellow(`  Result: ${blockedResult.blocked ? 'BLOCKED' : 'Executed'}`));

// =============================================================================
// PART 6: HOOK STATISTICS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Hook Performance Statistics'));
console.log(chalk.gray('─'.repeat(60)));

const stats = completeRegistry.getAllStats();
console.log(chalk.green('\nHook Statistics:'));
for (const stat of stats) {
  console.log(chalk.white(`  ${stat.hookId}:`));
  console.log(chalk.gray(`    Event: ${stat.event}`));
  console.log(chalk.gray(`    Invocations: ${stat.invocations}`));
  console.log(chalk.gray(`    Avg Duration: ${stat.averageDurationMs.toFixed(3)}ms`));
}

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. EventBus provides loose coupling through pub/sub'));
console.log(chalk.gray('  2. HookRegistry adds interception with priority ordering'));
console.log(chalk.gray('  3. Built-in hooks handle logging, security, and metrics'));
console.log(chalk.gray('  4. Hooks can modify or prevent events (interceptors)'));
console.log(chalk.gray('  5. Performance tracking helps identify slow hooks'));
console.log();
console.log(chalk.white('Architecture benefits:'));
console.log(chalk.gray('  - Components don\'t need to know about each other'));
console.log(chalk.gray('  - Easy to add new functionality without changing core code'));
console.log(chalk.gray('  - Testable: hooks can be tested in isolation'));
console.log(chalk.gray('  - Debuggable: events provide visibility into system behavior'));
console.log();
console.log(chalk.bold.green('Next: Lesson 11 - Plugin Architecture'));
console.log(chalk.gray('Build on hooks to create a full plugin system!'));
console.log();

// Print registry summary
console.log(chalk.gray(completeRegistry.summary()));
