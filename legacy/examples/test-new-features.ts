/**
 * Interactive test script for new features.
 * Run with: npx tsx examples/test-new-features.ts
 */

import {
  // Circuit Breaker
  createCircuitBreaker,
  createStrictCircuitBreaker,
  formatCircuitBreakerMetrics,
} from '../src/providers/circuit-breaker.js';

import {
  // Fallback Chain
  createFallbackChain,
} from '../src/providers/fallback-chain.js';

import {
  // Recursive Context (RLM)
  createRecursiveContext,
  createFileSystemSource,
  formatRecursiveStats,
} from '../src/tricks/recursive-context.js';

import {
  // Interactive Planning
  createInteractivePlanner,
  formatPlan,
} from '../src/integrations/interactive-planning.js';

import {
  // Learning Store
  createInMemoryLearningStore,
  formatLearningsContext,
  formatLearningStats,
} from '../src/integrations/learning-store.js';

import { createFailureTracker } from '../src/tricks/failure-evidence.js';

// =============================================================================
// TEST FUNCTIONS
// =============================================================================

async function testCircuitBreaker() {
  console.log('\n=== Circuit Breaker Test ===\n');

  const breaker = createStrictCircuitBreaker();

  // Subscribe to events
  breaker.on((event) => {
    console.log(`  Event: ${event.type}`);
  });

  console.log(`Initial state: ${breaker.getState()}`);

  // Simulate some failures
  console.log('\nSimulating failures...');
  breaker.recordFailure();
  console.log(`After 1 failure: ${breaker.getState()}`);
  breaker.recordFailure();
  console.log(`After 2 failures: ${breaker.getState()}`);
  breaker.recordFailure();
  console.log(`After 3 failures: ${breaker.getState()}`);

  // Try to execute (should be rejected)
  try {
    await breaker.execute(() => Promise.resolve('test'));
  } catch (e) {
    console.log(`\nExecution rejected: ${(e as Error).message}`);
  }

  // Show metrics
  console.log('\nMetrics:');
  console.log(formatCircuitBreakerMetrics(breaker.getMetrics()));

  // Reset
  breaker.reset();
  console.log(`\nAfter reset: ${breaker.getState()}`);
}

async function testFallbackChain() {
  console.log('\n=== Fallback Chain Test ===\n');

  // Create mock providers with the ChainedProvider format
  const mockProvider1 = {
    name: 'primary',
    defaultModel: 'primary-model',
    isConfigured: () => true,
    chat: async () => {
      throw new Error('Primary failed');
    },
  };

  const mockProvider2 = {
    name: 'secondary',
    defaultModel: 'secondary-model',
    isConfigured: () => true,
    chat: async () => ({
      content: 'Response from secondary!',
      stopReason: 'end_turn' as const,
      usage: { inputTokens: 10, outputTokens: 20 },
    }),
  };

  const chain = createFallbackChain({
    providers: [
      { provider: mockProvider1 as any, priority: 1 },
      { provider: mockProvider2 as any, priority: 2 },
    ],
    cooldownMs: 5000,
  });

  // Subscribe to events
  chain.on((event) => {
    console.log(`  Event: ${event.type}`);
  });

  console.log('Attempting chat with fallback...\n');

  const result = await chain.chat([{ role: 'user', content: 'Hello' }]);
  console.log(`\nResponse: ${result.content}`);
  console.log(`Provider used: ${result.usage ? 'secondary (fallback worked!)' : 'unknown'}`);
}

async function testRecursiveContext() {
  console.log('\n=== Recursive Context (RLM) Test ===\n');

  const manager = createRecursiveContext({
    maxDepth: 3,
    snippetTokens: 500,
    totalBudget: 5000,
  });

  // Register a mock file system source
  const mockFiles = {
    'main.ts': 'export function main() { console.log("Hello"); }',
    'utils.ts': 'export const add = (a, b) => a + b;',
    'config.ts': 'export const config = { debug: true };',
  };

  manager.registerSource('files', {
    describe: () => 'Mock file system',
    list: async () => Object.keys(mockFiles),
    fetch: async (key) => mockFiles[key as keyof typeof mockFiles] || 'Not found',
  });

  console.log('Registered sources:', manager.getSourceNames());

  // Subscribe to events
  manager.on((event) => {
    if (event.type === 'navigation.command') {
      console.log(`  Navigation: ${event.command.type} ${event.command.source || ''}`);
    }
  });

  // Mock LLM that navigates then synthesizes
  let callCount = 0;
  const mockLLM = async () => {
    callCount++;
    if (callCount === 1) {
      return { content: '{"type": "list", "source": "files"}', tokens: 10 };
    } else if (callCount === 2) {
      return { content: '{"type": "fetch", "source": "files", "key": "main.ts"}', tokens: 10 };
    } else if (callCount === 3) {
      return { content: '{"type": "done"}', tokens: 10 };
    } else {
      return { content: 'The main.ts file exports a main function that logs Hello.', tokens: 50 };
    }
  };

  console.log('\nProcessing query...\n');
  const result = await manager.process('What does main.ts do?', mockLLM);

  console.log(`Answer: ${result.answer}`);
  console.log(`\nStats: ${formatRecursiveStats(result.stats)}`);
}

async function testInteractivePlanning() {
  console.log('\n=== Interactive Planning Test ===\n');

  const planner = createInteractivePlanner({
    autoCheckpoint: true,
    confirmBeforeExecute: true,
  });

  // Subscribe to events
  planner.on((event) => {
    console.log(`  Event: ${event.type}`);
  });

  // Mock LLM for plan generation
  const mockPlanLLM = async () => ({
    content: JSON.stringify({
      reasoning: 'Breaking down the auth implementation',
      steps: [
        { description: 'Analyze existing code structure', complexity: 2 },
        { description: 'Design authentication middleware', complexity: 3 },
        { description: 'Implement JWT handling', complexity: 4, isDecisionPoint: true, decisionOptions: ['Use jsonwebtoken', 'Use jose', 'Use custom'] },
        { description: 'Add login/logout routes', complexity: 3 },
        { description: 'Write tests', complexity: 2 },
      ],
    }),
  });

  console.log('Creating plan...\n');
  const plan = await planner.draft('Add authentication to the API', mockPlanLLM);

  console.log(formatPlan(plan));

  // Edit the plan
  console.log('\n--- Editing plan ---\n');
  await planner.edit('skip step 5');
  await planner.edit('add rate limiting after step 3');

  console.log(formatPlan(planner.getPlan()!));

  // Approve and start execution
  console.log('\n--- Approving and executing ---\n');
  planner.approve();

  for (const step of planner.execute()) {
    console.log(`Executing: ${step.description}`);
    planner.completeStep('Done');
  }

  // Should be paused at decision point
  console.log(`\nPlan status: ${planner.getPlan()!.status}`);
}

async function testLearningStore() {
  console.log('\n=== Learning Store Test ===\n');

  const store = createInMemoryLearningStore({
    requireValidation: false, // Auto-validate for demo
  });

  // Connect to failure tracker
  const tracker = createFailureTracker();
  store.connectFailureTracker(tracker);

  // Subscribe to events
  store.on((event) => {
    console.log(`  Event: ${event.type}`);
  });

  // Propose some learnings
  console.log('Adding learnings...\n');

  store.proposeLearning({
    type: 'gotcha',
    description: 'Always check file exists before reading',
    actions: ['read_file'],
    categories: ['not_found'],
    confidence: 0.9,
  });

  store.proposeLearning({
    type: 'workaround',
    description: 'Use absolute paths for reliability',
    actions: ['bash', 'read_file', 'write_file'],
    categories: ['not_found'],
    confidence: 0.85,
  });

  store.proposeLearning({
    type: 'antipattern',
    description: 'Avoid hardcoded credentials in scripts',
    actions: ['bash'],
    categories: ['permission'],
    confidence: 0.95,
  });

  // Retrieve by action
  console.log('Retrieving by action "bash":');
  const bashLearnings = store.retrieveByAction('bash');
  bashLearnings.forEach((l) => console.log(`  - ${l.description}`));

  // Get context for LLM
  console.log('\nLearning context for LLM:\n');
  console.log(store.getLearningContext({ actions: ['read_file'] }));

  // Show stats
  console.log('Stats:');
  console.log(formatLearningStats(store.getStats()));

  store.close();
}

// =============================================================================
// MAIN
// =============================================================================

async function main() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║     Testing New Attocode Features      ║');
  console.log('╚════════════════════════════════════════╝');

  try {
    await testCircuitBreaker();
    await testFallbackChain();
    await testRecursiveContext();
    await testInteractivePlanning();
    await testLearningStore();

    console.log('\n✅ All tests completed successfully!\n');
  } catch (error) {
    console.error('\n❌ Test failed:', error);
    process.exit(1);
  }
}

main();
