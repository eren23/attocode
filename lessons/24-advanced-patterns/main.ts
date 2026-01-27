/**
 * Lesson 24: Advanced Patterns - Demo
 *
 * Demonstrates advanced agent patterns including:
 * - Thread management (fork, merge, rollback)
 * - Checkpoints and state snapshots
 * - Hierarchical configuration
 * - Configuration-driven agents
 * - Cancellation tokens
 * - Resource monitoring
 *
 * Run with: npx tsx 24-advanced-patterns/main.ts
 */

import * as path from 'path';
import { fileURLToPath } from 'url';

import { ThreadManager, createThreadManager } from './thread-manager.js';
import { CheckpointStore, createCheckpointStore } from './checkpoint-store.js';
import {
  HierarchicalStateManager,
  createStateManager,
  AGENT_CONFIG_SCHEMA,
} from './hierarchical-state.js';
import {
  AgentLoader,
  createAgentLoader,
  AGENT_TEMPLATES,
} from './agent-loader.js';
import {
  createCancellationTokenSource,
  withCancellation,
  sleep,
  CancellationError,
} from './cancellation.js';
import {
  ResourceMonitor,
  createResourceMonitor,
  ResourceLimitError,
} from './resource-monitor.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// =============================================================================
// DEMO UTILITIES
// =============================================================================

function printHeader(title: string): void {
  console.log('\n' + '='.repeat(60));
  console.log(title);
  console.log('='.repeat(60));
}

function printSubheader(title: string): void {
  console.log(`\n--- ${title} ---`);
}

// =============================================================================
// DEMO 1: THREAD MANAGEMENT
// =============================================================================

async function demoThreadManagement(): Promise<void> {
  printHeader('Demo 1: Thread Management (Fork, Merge, Rollback)');

  const tm = createThreadManager();

  // Add initial conversation
  console.log('\nBuilding initial conversation...');
  tm.addMessage('user', 'Help me write a function to sort an array');
  tm.addMessage('assistant', 'I can help! Do you want quicksort or mergesort?');
  tm.addMessage('user', 'Let me think about it...');

  console.log(`Active thread: ${tm.getActiveThread()?.name}`);
  console.log(`Messages: ${tm.getMessages().length}`);

  // Fork to explore quicksort
  printSubheader('Forking to explore quicksort');
  const quicksortBranch = tm.fork({ name: 'quicksort-exploration' });
  console.log(`Created branch: ${quicksortBranch.name} (${quicksortBranch.id})`);

  tm.addMessage('user', 'Let\'s try quicksort');
  tm.addMessage('assistant', 'Here\'s a quicksort implementation...');

  console.log(`Branch messages: ${tm.getMessages().length}`);

  // Go back and fork for mergesort
  printSubheader('Going back to fork mergesort');
  tm.switchThread(quicksortBranch.parentId!);
  const mergesortBranch = tm.fork({ name: 'mergesort-exploration' });
  console.log(`Created branch: ${mergesortBranch.name} (${mergesortBranch.id})`);

  tm.addMessage('user', 'Actually, let\'s try mergesort');
  tm.addMessage('assistant', 'Here\'s a mergesort implementation...');

  // Show thread tree
  printSubheader('Thread Tree');
  const tree = tm.getThreadTree();
  function printTree(node: { thread: { name?: string; id: string }; children: any[] }, indent = 0): void {
    const prefix = '  '.repeat(indent);
    const current = tm.getActiveThread()?.id === node.thread.id ? ' (active)' : '';
    console.log(`${prefix}- ${node.thread.name || node.thread.id}${current}`);
    for (const child of node.children) {
      printTree(child, indent + 1);
    }
  }
  printTree(tree);

  // Merge mergesort branch
  printSubheader('Merging mergesort branch');
  const mergeResult = tm.merge(mergesortBranch.id, tree.thread.id, {
    strategy: 'append',
  });
  console.log(`Merge result: ${mergeResult.message}`);
  console.log(`Main thread now has ${tm.getMessages().length} messages`);

  // Rollback demonstration
  printSubheader('Rollback demonstration');
  const messages = tm.getMessages();
  console.log(`Rolling back 2 messages...`);
  const rollbackResult = tm.rollbackBy(2);
  console.log(`Rollback result: ${rollbackResult.message}`);
  console.log(`Messages after rollback: ${tm.getMessages().length}`);
}

// =============================================================================
// DEMO 2: CHECKPOINTS
// =============================================================================

async function demoCheckpoints(): Promise<void> {
  printHeader('Demo 2: Checkpoints and State Recovery');

  const tm = createThreadManager();
  const store = createCheckpointStore(tm);

  // Build up some state
  tm.addMessage('user', 'Start a new project');
  tm.addMessage('assistant', 'What kind of project?');
  tm.addMessage('user', 'A web application');

  // Create a checkpoint
  printSubheader('Creating checkpoint');
  const thread = tm.getActiveThread()!;
  const checkpoint1 = store.createCheckpoint(thread, { label: 'after-setup' });
  console.log(`Created checkpoint: ${checkpoint1.label} (${checkpoint1.id})`);
  console.log(`At message index: ${checkpoint1.messageIndex}`);

  // Continue conversation
  tm.addMessage('assistant', 'I\'ll set up React with TypeScript');
  tm.addMessage('user', 'Actually, use Vue instead');
  tm.addMessage('assistant', 'Switching to Vue...');

  console.log(`\nCurrent messages: ${tm.getMessages().length}`);

  // Create another checkpoint
  const checkpoint2 = store.createCheckpoint(thread, { label: 'vue-decision' });
  console.log(`Created checkpoint: ${checkpoint2.label}`);

  // Show checkpoints
  printSubheader('All checkpoints');
  for (const ckpt of store.getThreadCheckpoints(thread.id)) {
    console.log(`  ${ckpt.label}: ${ckpt.state.messages.length} messages`);
  }

  // Restore to earlier checkpoint
  printSubheader('Restoring to earlier checkpoint');
  console.log(`Before restore: ${tm.getMessages().length} messages`);

  const restored = store.restore(checkpoint1.id, tm);
  console.log(`After restore: ${tm.getMessages().length} messages`);
  console.log(`Restored to: ${checkpoint1.label}`);

  // Show stats
  printSubheader('Checkpoint stats');
  const stats = store.getStats();
  console.log(`Total checkpoints: ${stats.totalCheckpoints}`);
  console.log(`Avg messages per checkpoint: ${stats.averageMessagesPerCheckpoint.toFixed(1)}`);
}

// =============================================================================
// DEMO 3: HIERARCHICAL CONFIGURATION
// =============================================================================

async function demoHierarchicalState(): Promise<void> {
  printHeader('Demo 3: Hierarchical Configuration');

  // Define defaults
  const defaults = {
    model: 'claude-3-5-sonnet',
    maxTokens: 4096,
    temperature: 0.7,
    verbose: false,
  };

  const manager = createStateManager(defaults, AGENT_CONFIG_SCHEMA);

  printSubheader('Default configuration');
  console.log(manager.resolve().config);

  // Simulate global config (user preferences)
  printSubheader('Adding global config (user preferences)');
  manager.setLevel('global', {
    model: 'claude-3-5-haiku', // User prefers haiku
    verbose: true,
  }, '~/.agent/config.json');

  console.log('Resolved config:');
  const resolved1 = manager.resolve();
  for (const [key, value] of Object.entries(resolved1.config)) {
    const source = resolved1.sources[key];
    console.log(`  ${key}: ${value} (from ${source})`);
  }

  // Simulate workspace config (project settings)
  printSubheader('Adding workspace config (project settings)');
  manager.setLevel('workspace', {
    maxTokens: 8192, // This project needs more tokens
    temperature: 0.5, // More deterministic for this project
  }, '.agent/config.json');

  console.log('Resolved config:');
  const resolved2 = manager.resolve();
  for (const [key, value] of Object.entries(resolved2.config)) {
    const source = resolved2.sources[key];
    console.log(`  ${key}: ${value} (from ${source})`);
  }

  // Session override
  printSubheader('Adding session override');
  manager.setSessionOverride('model', 'claude-3-opus'); // Need opus for this task

  console.log('Final resolved config:');
  const resolved3 = manager.resolve();
  for (const [key, value] of Object.entries(resolved3.config)) {
    const source = resolved3.sources[key];
    console.log(`  ${key}: ${value} (from ${source})`);
  }

  // Show diff
  printSubheader('Diff: workspace vs session');
  const diff = manager.diff('workspace', 'session');
  console.log(`Changed: ${diff.changed.join(', ') || 'none'}`);
  console.log(`Added in session: ${diff.added.join(', ') || 'none'}`);
}

// =============================================================================
// DEMO 4: CONFIGURATION-DRIVEN AGENTS
// =============================================================================

async function demoAgentLoader(): Promise<void> {
  printHeader('Demo 4: Configuration-Driven Agents');

  const loader = createAgentLoader();

  // Load from built-in templates
  printSubheader('Loading built-in agent templates');
  loader.loadFromString(AGENT_TEMPLATES.coder);
  loader.loadFromString(AGENT_TEMPLATES.reviewer);
  loader.loadFromString(AGENT_TEMPLATES.researcher);

  console.log('Loaded agents:', loader.getAgentNames().join(', '));

  // Show agent details
  printSubheader('Agent details');
  for (const name of loader.getAgentNames()) {
    const agent = loader.getAgent(name)!;
    console.log(`\n${agent.displayName || agent.name}:`);
    console.log(`  Model: ${agent.model || 'default'}`);
    console.log(`  Tools: ${agent.tools?.join(', ') || 'none'}`);
    console.log(`  Authority: ${agent.authority || 'not set'}`);
    console.log(`  Prompt: ${agent.systemPrompt.substring(0, 50)}...`);
  }

  // Load from directory
  printSubheader('Loading from agents/ directory');
  const agentsDir = path.join(__dirname, 'agents');
  const loaded = loader.loadFromDirectory(agentsDir);
  console.log(`Loaded ${loaded.length} agents from directory`);

  // Generate markdown for an agent
  printSubheader('Generating agent markdown');
  const customAgent = loader.createAgent({
    name: 'custom-tester',
    displayName: 'Test Engineer',
    model: 'claude-3-5-haiku',
    tools: ['read_file', 'bash'],
    systemPrompt: 'You are a test engineer focused on writing comprehensive tests.',
    authority: 3,
  });

  console.log('Generated markdown preview:');
  const markdown = loader.toMarkdown(customAgent);
  console.log(markdown.split('\n').slice(0, 10).join('\n') + '\n...');
}

// =============================================================================
// DEMO 5: CANCELLATION TOKENS
// =============================================================================

async function demoCancellation(): Promise<void> {
  printHeader('Demo 5: Cancellation Tokens');

  // Basic cancellation
  printSubheader('Basic cancellation');
  const cts = createCancellationTokenSource();

  // Start a long operation
  const operation = withCancellation(
    async () => {
      console.log('Operation started...');
      for (let i = 1; i <= 5; i++) {
        await sleep(100, cts.token);
        console.log(`  Step ${i}/5`);
      }
      return 'completed';
    },
    { cancellationToken: cts.token }
  );

  // Cancel after 250ms
  setTimeout(() => {
    console.log('Requesting cancellation...');
    cts.cancel();
  }, 250);

  try {
    const result = await operation;
    console.log(`Result: ${result}`);
  } catch (error) {
    if (error instanceof CancellationError) {
      console.log('Operation was cancelled (as expected)');
    } else {
      throw error;
    }
  }

  // Timeout-based cancellation
  printSubheader('Timeout-based cancellation');
  const cts2 = createCancellationTokenSource();

  // Register cleanup callback
  cts2.token.register(() => {
    console.log('Cleanup: releasing resources...');
  });

  try {
    await withCancellation(
      async () => {
        await sleep(500);
        return 'should not reach';
      },
      { timeout: 100 }
    );
  } catch (error) {
    if (error instanceof CancellationError) {
      console.log('Operation timed out (as expected)');
    }
  }
}

// =============================================================================
// DEMO 6: RESOURCE MONITORING
// =============================================================================

async function demoResourceMonitor(): Promise<void> {
  printHeader('Demo 6: Resource Monitoring');

  const monitor = createResourceMonitor({
    maxMemoryBytes: 100 * 1024 * 1024, // 100 MB for demo
    maxCpuTimeMs: 5000, // 5 seconds
    maxOperations: 3,
    warningThreshold: 0.5,
    criticalThreshold: 0.8,
  });

  // Subscribe to events
  monitor.subscribe(event => {
    if (event.type === 'resource.warning') {
      console.log(`  [WARNING] ${event.limit} approaching limit`);
    } else if (event.type === 'resource.critical') {
      console.log(`  [CRITICAL] ${event.limit} at critical level`);
    }
  });

  // Show current usage
  printSubheader('Current resource usage');
  const usage = monitor.getUsage();
  console.log(`Memory: ${(usage.memoryBytes / 1024 / 1024).toFixed(2)} MB`);
  console.log(`CPU Time: ${usage.cpuTimeMs} ms`);
  console.log(`Operations: ${usage.activeOperations}`);

  // Check status
  const check = monitor.check();
  console.log(`Status: ${check.status}`);
  if (check.recommendations && check.recommendations.length > 0) {
    console.log('Recommendations:');
    for (const rec of check.recommendations) {
      console.log(`  - ${rec}`);
    }
  }

  // Run operations with tracking
  printSubheader('Running operations with tracking');

  const operations = [1, 2, 3, 4].map(async i => {
    if (!monitor.canStartOperation()) {
      console.log(`  Operation ${i}: waiting for slot...`);
      await monitor.waitForSlot(1000);
    }

    return monitor.runOperation(async () => {
      console.log(`  Operation ${i}: started`);
      await new Promise(r => setTimeout(r, 200));
      console.log(`  Operation ${i}: completed`);
      return i;
    });
  });

  await Promise.all(operations);

  // Show final stats
  printSubheader('Final stats');
  const stats = monitor.getStats();
  console.log(`Uptime: ${stats.uptime} ms`);
  console.log(`Current memory: ${(stats.currentMemory / 1024 / 1024).toFixed(2)} MB`);
}

// =============================================================================
// MAIN
// =============================================================================

async function main(): Promise<void> {
  console.log('Lesson 24: Advanced Patterns');
  console.log('============================');
  console.log('This lesson demonstrates advanced agent patterns including');
  console.log('thread management, checkpoints, hierarchical config, and more.\n');

  try {
    await demoThreadManagement();
    await demoCheckpoints();
    await demoHierarchicalState();
    await demoAgentLoader();
    await demoCancellation();
    await demoResourceMonitor();

    printHeader('Summary');
    console.log(`
Key takeaways:

1. Thread Management: Fork conversations to explore alternatives,
   merge successful branches, rollback on failure

2. Checkpoints: Save state snapshots for recovery, enable safe
   exploration with rollback points

3. Hierarchical Config: Cascade settings from global to local,
   with runtime overrides

4. Agent Loader: Define agents in markdown files with YAML
   frontmatter for easy configuration

5. Cancellation: Cooperative cancellation with tokens, timeouts,
   and cleanup callbacks

6. Resource Monitor: Track and limit memory, CPU, and concurrent
   operations to prevent runaway behavior

Next: Lesson 25 integrates ALL patterns into a production-ready agent.
`);
  } catch (error) {
    console.error('Demo error:', error);
    process.exit(1);
  }
}

main();
