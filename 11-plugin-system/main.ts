/**
 * Lesson 11: Plugin Architecture
 *
 * This lesson demonstrates how to build a plugin system that enables
 * modular, extensible agent functionality. Building on the hook system
 * from Lesson 10, plugins can register hooks, tools, and communicate
 * through events.
 *
 * Key concepts:
 * 1. Plugin lifecycle (register, enable, disable, unregister)
 * 2. Sandboxed plugin context for isolation
 * 3. Resource tracking for clean unloading
 * 4. Inter-plugin communication through events
 *
 * Run: npm run lesson:11
 */

import chalk from 'chalk';
import { PluginManager } from './plugin-manager.js';
import { loggerPlugin } from './example-plugins/logger-plugin.js';
import { securityPlugin } from './example-plugins/security-plugin.js';
import { metricsPlugin } from './example-plugins/metrics-plugin.js';
import { createEvent } from '../10-hook-system/event-bus.js';
import type { Plugin, PluginContext } from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 11: Plugin Architecture                       ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: PLUGIN MANAGER BASICS
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Plugin Manager Basics'));
console.log(chalk.gray('─'.repeat(60)));

const manager = new PluginManager({
  debug: false,
  autoEnable: false, // We'll enable manually for demonstration
});

// Listen to plugin events
manager.on((event) => {
  const emoji = {
    'plugin.registered': '📝',
    'plugin.loading': '⏳',
    'plugin.loaded': '✅',
    'plugin.error': '❌',
    'plugin.unloading': '🔄',
    'plugin.unloaded': '🗑️',
    'plugin.disabled': '⏸️',
    'plugin.enabled': '▶️',
  }[event.type] ?? '📌';

  console.log(chalk.gray(`  ${emoji} Event: ${event.type} - ${event.name}`));
});

console.log(chalk.green('\nRegistering plugins...'));

// Register plugins
await manager.register(loggerPlugin);
await manager.register(securityPlugin);
await manager.register(metricsPlugin);

console.log(chalk.gray('\nPlugin summary:'));
console.log(manager.summary());

// =============================================================================
// PART 2: PLUGIN LIFECYCLE
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Plugin Lifecycle'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nEnabling plugins...'));

// Enable plugins in order
await manager.enable('logger');
await manager.enable('security');
await manager.enable('metrics');

console.log(chalk.gray('\nActive plugins:'));
for (const plugin of manager.getActive()) {
  console.log(chalk.white(`  - ${plugin.plugin.metadata.name} v${plugin.plugin.metadata.version}`));
  console.log(chalk.gray(`    Hooks: ${plugin.resources.hooks.length}`));
  console.log(chalk.gray(`    Tools: ${plugin.resources.tools.join(', ') || 'none'}`));
}

// =============================================================================
// PART 3: HOOKS IN ACTION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Hooks in Action'));
console.log(chalk.gray('─'.repeat(60)));

const hookRegistry = manager.getHookRegistry();

console.log(chalk.green('\nSimulating tool calls through hook system...'));

// Simulate a safe tool call
console.log(chalk.blue('\n1. Safe command: "ls -la"'));
await hookRegistry.execute(
  createEvent('tool.before', {
    tool: 'bash',
    args: { command: 'ls -la' },
  })
);
await hookRegistry.execute(
  createEvent('tool.after', {
    tool: 'bash',
    args: { command: 'ls -la' },
    result: { success: true },
    durationMs: 15,
  })
);

// Simulate a dangerous tool call (should be blocked)
console.log(chalk.blue('\n2. Dangerous command: "rm -rf /"'));
const dangerousEvent = createEvent('tool.before', {
  tool: 'bash',
  args: { command: 'rm -rf /' },
});
await hookRegistry.execute(dangerousEvent);
console.log(
  dangerousEvent.preventDefault
    ? chalk.red('   Result: BLOCKED by security plugin')
    : chalk.green('   Result: Allowed')
);

// Simulate protected file access
console.log(chalk.blue('\n3. Protected file: "/etc/shadow"'));
const protectedEvent = createEvent('tool.before', {
  tool: 'read_file',
  args: { path: '/etc/shadow' },
});
await hookRegistry.execute(protectedEvent);
console.log(
  protectedEvent.preventDefault
    ? chalk.red('   Result: BLOCKED by security plugin')
    : chalk.green('   Result: Allowed')
);

// =============================================================================
// PART 4: INTER-PLUGIN COMMUNICATION
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Inter-Plugin Communication'));
console.log(chalk.gray('─'.repeat(60)));

const eventBus = manager.getEventBus();

// Subscribe to security events
const securitySubscription = eventBus.on('custom', (event) => {
  if (event.name.startsWith('security:')) {
    console.log(chalk.yellow(`  Security event: ${event.name}`), event.data);
  }
});

// Trigger some events
console.log(chalk.green('\nTriggering more tool calls...'));
for (let i = 0; i < 3; i++) {
  await hookRegistry.execute(
    createEvent('tool.before', {
      tool: 'read_file',
      args: { path: `/tmp/file${i}.txt` },
    })
  );
  await hookRegistry.execute(
    createEvent('tool.after', {
      tool: 'read_file',
      args: { path: `/tmp/file${i}.txt` },
      result: { success: true },
      durationMs: 5 + Math.random() * 10,
    })
  );
}

// Request metrics via event
console.log(chalk.green('\nRequesting metrics from metrics plugin...'));
let receivedMetrics: unknown = null;
const metricsSubscription = eventBus.on('custom', (event) => {
  if (event.name === 'metrics:metrics.response') {
    receivedMetrics = event.data;
  }
});

eventBus.emitSync({
  type: 'custom',
  name: 'metrics:metrics.request',
  data: {},
});

if (receivedMetrics) {
  console.log(chalk.gray('  Metrics received via event:'));
  console.log(chalk.gray('  ' + JSON.stringify(receivedMetrics, null, 2).replace(/\n/g, '\n  ')));
}

securitySubscription.unsubscribe();
metricsSubscription.unsubscribe();

// =============================================================================
// PART 5: PLUGIN TOOLS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Plugin-Registered Tools'));
console.log(chalk.gray('─'.repeat(60)));

const toolRegistry = manager.getServices().toolRegistry;
const tools = toolRegistry.list();

console.log(chalk.green('\nTools registered by plugins:'));
for (const tool of tools) {
  console.log(chalk.white(`  - ${tool}`));
}

// =============================================================================
// PART 6: CREATING A CUSTOM PLUGIN
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Creating a Custom Plugin'));
console.log(chalk.gray('─'.repeat(60)));

/**
 * Example of creating a plugin inline.
 * This demonstrates what users would write.
 */
const customPlugin: Plugin = {
  metadata: {
    name: 'custom-example',
    version: '1.0.0',
    description: 'A custom plugin created inline',
  },

  async initialize(context: PluginContext) {
    context.log('info', 'Custom plugin starting!');

    // Store some data
    await context.store('startTime', Date.now());

    // Register a hook
    context.registerHook('tool.before', (event) => {
      context.log('debug', `Custom plugin sees: ${event.tool}`);
    }, { priority: 200 }); // Low priority - runs after other plugins

    // Listen for events from other plugins
    context.subscribe('security.blocked', (data) => {
      context.log('warn', `Security blocked something: ${JSON.stringify(data)}`);
    });

    context.log('info', 'Custom plugin ready!');
  },

  async cleanup() {
    console.log('[custom-example] Goodbye!');
  },
};

console.log(chalk.green('\nRegistering and enabling custom plugin...'));
await manager.register(customPlugin);
await manager.enable('custom-example');

// Test it
console.log(chalk.blue('\nTesting custom plugin hook:'));
await hookRegistry.execute(
  createEvent('tool.before', {
    tool: 'custom_tool',
    args: { test: true },
  })
);

// =============================================================================
// PART 7: PLUGIN DISABLE AND CLEANUP
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Plugin Disable and Cleanup'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nDisabling custom plugin...'));
await manager.disable('custom-example');

console.log(chalk.green('\nUnregistering custom plugin...'));
await manager.unregister('custom-example');

console.log(chalk.gray('\nFinal plugin summary:'));
console.log(manager.summary());

// =============================================================================
// PART 8: SHUTDOWN
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 8: Graceful Shutdown'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.green('\nShutting down plugin manager...'));
await manager.shutdown();

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. PluginManager handles registration and lifecycle'));
console.log(chalk.gray('  2. PluginContext provides sandboxed access to agent services'));
console.log(chalk.gray('  3. Plugins can register hooks, tools, and storage'));
console.log(chalk.gray('  4. Inter-plugin communication works through events'));
console.log(chalk.gray('  5. Resources are tracked for clean unloading'));
console.log();
console.log(chalk.white('Plugin architecture benefits:'));
console.log(chalk.gray('  - Modular: Features can be added/removed independently'));
console.log(chalk.gray('  - Isolated: Plugins can\'t directly interfere with each other'));
console.log(chalk.gray('  - Extensible: Third-party plugins can add functionality'));
console.log(chalk.gray('  - Testable: Plugins can be tested in isolation'));
console.log();
console.log(chalk.bold.green('Next: Lesson 12 - Rules & Instructions System'));
console.log(chalk.gray('Build dynamic system prompts from multiple sources!'));
console.log();
