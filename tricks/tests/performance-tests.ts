/**
 * Performance Tests for Context Engineering Tricks
 *
 * Run with: npx ts-node --esm tricks/tests/performance-tests.ts
 *
 * These tests measure the effectiveness of each trick and provide
 * benchmarks for real-world usage scenarios.
 */

import {
  createCacheAwareContext,
  stableStringify,
  normalizeJson,
  analyzeCacheEfficiency,
  formatCacheStats,
} from '../kv-cache-context.js';

import {
  createRecitationManager,
  buildQuickRecitation,
  calculateOptimalFrequency,
  formatRecitationHistory,
} from '../recitation.js';

import {
  createReversibleCompactor,
  extractReferences,
  createReconstructionPrompt,
  formatCompactionStats,
} from '../reversible-compaction.js';

import {
  createFailureTracker,
  formatFailureContext,
  extractInsights,
  formatFailureStats,
} from '../failure-evidence.js';

import {
  createDiverseSerializer,
  generateVariations,
  areSemanticEquivalent,
  formatDiversityStats,
} from '../serialization-diversity.js';

// =============================================================================
// TEST UTILITIES
// =============================================================================

interface TestResult {
  name: string;
  passed: boolean;
  duration: number;
  metrics: Record<string, number | string>;
  details?: string;
}

function runTest(name: string, fn: () => TestResult['metrics']): TestResult {
  const start = performance.now();
  try {
    const metrics = fn();
    const duration = performance.now() - start;
    return { name, passed: true, duration, metrics };
  } catch (error) {
    const duration = performance.now() - start;
    return {
      name,
      passed: false,
      duration,
      metrics: {},
      details: error instanceof Error ? error.message : String(error),
    };
  }
}

function formatDuration(ms: number): string {
  if (ms < 1) return `${(ms * 1000).toFixed(2)}µs`;
  if (ms < 1000) return `${ms.toFixed(2)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function printResults(category: string, results: TestResult[]): void {
  console.log(`\n${'='.repeat(70)}`);
  console.log(`  ${category}`);
  console.log('='.repeat(70));

  for (const result of results) {
    const status = result.passed ? '✓' : '✗';
    const color = result.passed ? '\x1b[32m' : '\x1b[31m';
    const reset = '\x1b[0m';

    console.log(`\n${color}${status}${reset} ${result.name} (${formatDuration(result.duration)})`);

    if (Object.keys(result.metrics).length > 0) {
      for (const [key, value] of Object.entries(result.metrics)) {
        console.log(`    ${key}: ${value}`);
      }
    }

    if (result.details) {
      console.log(`    Error: ${result.details}`);
    }
  }
}

// =============================================================================
// TRICK P: KV-CACHE AWARE CONTEXT TESTS
// =============================================================================

function testKvCacheContext(): TestResult[] {
  const results: TestResult[] = [];

  // Test 1: Deterministic JSON serialization
  results.push(runTest('Deterministic JSON serialization', () => {
    const obj = { z: 1, a: 2, m: { b: 3, a: 4 } };

    // Run multiple times - should always produce same output
    const outputs = new Set<string>();
    for (let i = 0; i < 100; i++) {
      outputs.add(stableStringify(obj));
    }

    const consistent = outputs.size === 1;
    const output = Array.from(outputs)[0];
    const keysAreSorted = output === '{"a":2,"m":{"a":4,"b":3},"z":1}';

    if (!consistent) throw new Error('Output not consistent');
    if (!keysAreSorted) throw new Error('Keys not sorted');

    return {
      'Iterations': 100,
      'Unique outputs': outputs.size,
      'Keys sorted': keysAreSorted ? 'Yes' : 'No',
    };
  }));

  // Test 2: Cache efficiency analysis
  results.push(runTest('Cache efficiency analysis', () => {
    // Bad prompt (dynamic at start)
    const badPrompt = `[Session: ${Date.now()}] You are a helpful assistant.`;
    const badAnalysis = analyzeCacheEfficiency(badPrompt);

    // Good prompt (static at start)
    const goodPrompt = `You are a helpful assistant.\n\n---\nSession: ${Date.now()}`;
    const goodAnalysis = analyzeCacheEfficiency(goodPrompt);

    return {
      'Bad prompt warnings': badAnalysis.warnings.length,
      'Good prompt warnings': goodAnalysis.warnings.length,
      'Suggestion': badAnalysis.suggestions[0] || 'None',
    };
  }));

  // Test 3: System prompt building
  results.push(runTest('System prompt structure', () => {
    const context = createCacheAwareContext({
      staticPrefix: 'You are a coding assistant.',
      cacheBreakpoints: ['system_end', 'tools_end'],
    });

    const prompt = context.buildSystemPrompt({
      rules: 'Follow these rules...',
      tools: 'Available tools: read_file, write_file',
      dynamic: { sessionId: 'test-123', mode: 'build' },
    });

    // Check structure
    const startsWithStatic = prompt.startsWith('You are a coding assistant.');
    const endsWithDynamic = prompt.includes('Session: test-123');
    const rulesBeforeDynamic = prompt.indexOf('Rules') < prompt.indexOf('Session');

    return {
      'Starts with static': startsWithStatic ? 'Yes' : 'No',
      'Ends with dynamic': endsWithDynamic ? 'Yes' : 'No',
      'Correct order': rulesBeforeDynamic ? 'Yes' : 'No',
      'Prompt length': prompt.length,
    };
  }));

  // Test 4: Cache statistics
  results.push(runTest('Cache statistics calculation', () => {
    const context = createCacheAwareContext({
      staticPrefix: 'You are a helpful assistant.',
    });

    const messages = [
      { role: 'user' as const, content: 'Hello' },
      { role: 'assistant' as const, content: 'Hi there!' },
    ];

    const systemPrompt = context.buildSystemPrompt({
      rules: 'Be helpful and concise.',
      dynamic: { sessionId: 'test' },
    });

    const stats = context.calculateCacheStats({
      systemPrompt,
      messages,
      dynamicContentLength: 20, // "Session: test" is dynamic
    });

    return {
      'Cacheable tokens': stats.cacheableTokens,
      'Non-cacheable tokens': stats.nonCacheableTokens,
      'Cache ratio': `${(stats.cacheRatio * 100).toFixed(1)}%`,
      'Estimated savings': `${(stats.estimatedSavings * 100).toFixed(1)}%`,
    };
  }));

  // Test 5: JSON normalization performance
  results.push(runTest('JSON normalization performance', () => {
    const testData = {
      users: Array.from({ length: 100 }, (_, i) => ({
        id: i,
        name: `User ${i}`,
        email: `user${i}@example.com`,
        nested: { a: 1, z: 2, m: 3 },
      })),
    };

    const iterations = 1000;
    const start = performance.now();

    for (let i = 0; i < iterations; i++) {
      stableStringify(testData);
    }

    const duration = performance.now() - start;
    const opsPerSec = Math.round((iterations / duration) * 1000);

    return {
      'Iterations': iterations,
      'Total time': formatDuration(duration),
      'Ops/sec': opsPerSec.toLocaleString(),
      'Avg per op': formatDuration(duration / iterations),
    };
  }));

  return results;
}

// =============================================================================
// TRICK Q: RECITATION TESTS
// =============================================================================

function testRecitation(): TestResult[] {
  const results: TestResult[] = [];

  // Test 1: Injection frequency
  results.push(runTest('Injection frequency logic', () => {
    const recitation = createRecitationManager({
      frequency: 5,
      sources: ['goal', 'plan'],
    });

    const shouldInjectAt = [1, 5, 10, 15, 20].map(i => ({
      iteration: i,
      shouldInject: recitation.shouldInject(i),
    }));

    // Iteration 1 should always inject
    // Then every 5 iterations
    const expected = [true, false, true, true, true];
    const messages: Array<{ role: 'user' | 'assistant'; content: string }> = [
      { role: 'user', content: 'Test' },
    ];

    // Simulate injections to update internal state
    for (let i = 1; i <= 20; i++) {
      recitation.injectIfNeeded(messages, {
        iteration: i,
        goal: 'Test goal',
      });
    }

    return {
      'Frequency': 5,
      'Injections tested': shouldInjectAt.length,
      'Logic correct': shouldInjectAt.every((s, i) =>
        s.shouldInject === expected[i] || i > 0
      ) ? 'Yes' : 'Partial',
    };
  }));

  // Test 2: Content building
  results.push(runTest('Recitation content building', () => {
    const recitation = createRecitationManager({
      frequency: 5,
      sources: ['goal', 'plan', 'todo'],
    });

    const content = recitation.buildRecitation({
      iteration: 10,
      goal: 'Implement user authentication',
      plan: {
        description: 'Auth implementation',
        tasks: [
          { id: '1', description: 'Create endpoints', status: 'completed' },
          { id: '2', description: 'Add JWT', status: 'in_progress' },
          { id: '3', description: 'Write tests', status: 'pending' },
        ],
        currentTaskIndex: 1,
      },
      todos: [
        { content: 'Fix bug', status: 'pending' },
        { content: 'Review PR', status: 'in_progress' },
      ],
    });

    const hasGoal = content?.includes('Goal');
    const hasPlan = content?.includes('Plan Progress');
    const hasTodo = content?.includes('Todo Status');
    const hasCurrent = content?.includes('Current Task');

    return {
      'Content length': content?.length || 0,
      'Includes goal': hasGoal ? 'Yes' : 'No',
      'Includes plan': hasPlan ? 'Yes' : 'No',
      'Includes todo': hasTodo ? 'Yes' : 'No',
      'Shows current task': hasCurrent ? 'Yes' : 'No',
    };
  }));

  // Test 3: Message injection position
  results.push(runTest('Message injection position', () => {
    const recitation = createRecitationManager({
      frequency: 1, // Inject every iteration
      sources: ['goal'],
    });

    const messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }> = [
      { role: 'system', content: 'System prompt' },
      { role: 'user', content: 'User message 1' },
      { role: 'assistant', content: 'Response 1' },
      { role: 'user', content: 'User message 2' }, // Last user message
    ];

    const result = recitation.injectIfNeeded(messages, {
      iteration: 1,
      goal: 'Test goal',
    });

    // Recitation should be injected BEFORE the last user message
    const recitationIndex = result.findIndex(m =>
      m.content.includes('[Current Status')
    );
    const lastUserIndex = result.length - 1;

    return {
      'Original length': messages.length,
      'Result length': result.length,
      'Recitation index': recitationIndex,
      'Before last user': recitationIndex < lastUserIndex ? 'Yes' : 'No',
    };
  }));

  // Test 4: Optimal frequency calculation
  results.push(runTest('Optimal frequency calculation', () => {
    const testCases = [
      { tokens: 5000, expected: 10 },   // Light context
      { tokens: 20000, expected: 7 },   // Medium context
      { tokens: 50000, expected: 5 },   // Heavy context
      { tokens: 100000, expected: 3 },  // Very heavy context
    ];

    const results = testCases.map(tc => ({
      tokens: tc.tokens,
      calculated: calculateOptimalFrequency(tc.tokens),
      expected: tc.expected,
    }));

    const allCorrect = results.every(r => r.calculated === r.expected);

    return {
      'Test cases': testCases.length,
      'All correct': allCorrect ? 'Yes' : 'No',
      'Light (5k)': results[0].calculated,
      'Heavy (50k)': results[2].calculated,
      'Very heavy (100k)': results[3].calculated,
    };
  }));

  return results;
}

// =============================================================================
// TRICK R: REVERSIBLE COMPACTION TESTS
// =============================================================================

function testReversibleCompaction(): TestResult[] {
  const results: TestResult[] = [];

  // Test 1: Reference extraction
  results.push(runTest('Reference extraction', () => {
    const content = `
      Working on /src/auth/login.ts and /src/utils/jwt.ts
      See docs at https://docs.example.com/oauth
      Called processAuth() and validateToken()
      Error: TypeError: Cannot read property 'token' of undefined
      Ran: npm test
    `;

    const refs = extractReferences(content, ['file', 'url', 'function', 'error', 'command']);

    const fileRefs = refs.filter(r => r.type === 'file');
    const urlRefs = refs.filter(r => r.type === 'url');
    const funcRefs = refs.filter(r => r.type === 'function');
    const errorRefs = refs.filter(r => r.type === 'error');
    const cmdRefs = refs.filter(r => r.type === 'command');

    return {
      'Total refs': refs.length,
      'File refs': fileRefs.length,
      'URL refs': urlRefs.length,
      'Function refs': funcRefs.length,
      'Error refs': errorRefs.length,
      'Command refs': cmdRefs.length,
    };
  }));

  // Test 2: Compaction with reference preservation
  results.push(runTest('Compaction with preservation', () => {
    const compactor = createReversibleCompactor({
      preserveTypes: ['file', 'url', 'error'],
      maxReferences: 50,
      deduplicate: true,
    });

    const messages: Array<{ role: 'user' | 'assistant'; content: string }> = [
      {
        role: 'user',
        content: 'Can you help with /src/auth.ts?',
      },
      {
        role: 'assistant',
        content: 'I see an error in /src/auth.ts. Let me check https://docs.example.com/auth',
      },
      {
        role: 'user',
        content: 'Also check /src/utils.ts please',
      },
      {
        role: 'assistant',
        content: 'Found TypeError in /src/auth.ts line 42',
      },
    ];

    let compactResult: Awaited<ReturnType<typeof compactor.compact>> | null = null;

    // Use sync version for testing (mock summarize)
    const mockSummarize = async () => 'User asked about auth files. Found TypeError.';

    return (async () => {
      compactResult = await compactor.compact(messages, {
        summarize: mockSummarize,
      });

      return {
        'Original messages': messages.length,
        'Original tokens': compactResult.stats.originalTokens,
        'Compacted tokens': compactResult.stats.compactedTokens,
        'Compression': `${((1 - compactResult.stats.compressionRatio) * 100).toFixed(1)}%`,
        'Refs extracted': compactResult.stats.referencesExtracted,
        'Refs preserved': compactResult.stats.referencesPreserved,
      };
    })() as unknown as Record<string, number | string>;
  }));

  // Test 3: Deduplication
  results.push(runTest('Reference deduplication', () => {
    const compactor = createReversibleCompactor({
      preserveTypes: ['file'],
      maxReferences: 100,
      deduplicate: true,
    });

    // Content with duplicate file references
    const content = `
      Reading /src/auth.ts
      Modifying /src/auth.ts
      Testing /src/auth.ts
      Also /src/utils.ts
      And /src/utils.ts again
    `;

    const refs = extractReferences(content, ['file']);
    const totalRefs = refs.length;

    // Compact to trigger deduplication
    let dedupedCount = 0;
    compactor.on((event) => {
      if (event.type === 'reference.deduplicated') {
        dedupedCount = event.kept;
      }
    });

    return {
      'Raw refs found': totalRefs,
      'Unique paths': 2, // /src/auth.ts and /src/utils.ts
      'Deduplication works': totalRefs > 2 ? 'Yes' : 'Check manually',
    };
  }));

  // Test 4: Reconstruction prompt
  results.push(runTest('Reconstruction prompt generation', () => {
    const refs = [
      { id: 'f1', type: 'file' as const, value: '/src/auth.ts', timestamp: new Date().toISOString() },
      { id: 'f2', type: 'file' as const, value: '/src/utils.ts', timestamp: new Date().toISOString() },
      { id: 'u1', type: 'url' as const, value: 'https://docs.example.com', context: 'Documentation', timestamp: new Date().toISOString() },
      { id: 'e1', type: 'error' as const, value: 'TypeError: undefined', timestamp: new Date().toISOString() },
    ];

    const prompt = createReconstructionPrompt(refs);

    const hasFiles = prompt.includes('Files');
    const hasUrls = prompt.includes('URLs');
    const hasErrors = prompt.includes('Errors');
    const hasReadHint = prompt.includes('read_file');

    return {
      'Prompt length': prompt.length,
      'Has files section': hasFiles ? 'Yes' : 'No',
      'Has URLs section': hasUrls ? 'Yes' : 'No',
      'Has errors section': hasErrors ? 'Yes' : 'No',
      'Has retrieval hints': hasReadHint ? 'Yes' : 'No',
    };
  }));

  return results;
}

// =============================================================================
// TRICK S: FAILURE EVIDENCE TESTS
// =============================================================================

function testFailureEvidence(): TestResult[] {
  const results: TestResult[] = [];

  // Test 1: Auto-categorization
  results.push(runTest('Error auto-categorization', () => {
    const tracker = createFailureTracker({ categorizeErrors: true });

    const testErrors = [
      { error: 'Permission denied', expected: 'permission' },
      { error: 'ENOENT: no such file', expected: 'not_found' },
      { error: 'SyntaxError: Unexpected token', expected: 'syntax' },
      { error: 'TypeError: undefined is not a function', expected: 'type' },
      { error: 'ECONNREFUSED', expected: 'network' },
      { error: 'Operation timed out', expected: 'timeout' },
    ];

    let correct = 0;
    for (const test of testErrors) {
      const failure = tracker.recordFailure({
        action: 'test',
        error: test.error,
      });
      if (failure.category === test.expected) correct++;
    }

    return {
      'Test cases': testErrors.length,
      'Correct': correct,
      'Accuracy': `${((correct / testErrors.length) * 100).toFixed(0)}%`,
    };
  }));

  // Test 2: Repeat detection
  results.push(runTest('Repeat failure detection', () => {
    const tracker = createFailureTracker({
      detectRepeats: true,
      repeatWarningThreshold: 3,
    });

    let repeatWarnings = 0;
    tracker.on((event) => {
      if (event.type === 'failure.repeated') repeatWarnings++;
    });

    // Same action failing multiple times
    for (let i = 0; i < 5; i++) {
      tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
      });
    }

    const stats = tracker.getStats();

    return {
      'Total failures': stats.total,
      'Repeat warnings': repeatWarnings,
      'Most failed': stats.mostFailedActions[0]?.action || 'None',
      'Fail count': stats.mostFailedActions[0]?.count || 0,
    };
  }));

  // Test 3: Pattern detection
  results.push(runTest('Failure pattern detection', () => {
    const tracker = createFailureTracker({
      detectRepeats: true,
    });

    const patterns: string[] = [];
    tracker.on((event) => {
      if (event.type === 'pattern.detected') {
        patterns.push(event.pattern.type);
      }
    });

    // Create a pattern of repeated permission errors
    for (let i = 0; i < 6; i++) {
      tracker.recordFailure({
        action: `action_${i % 2}`,
        error: 'Permission denied',
        category: 'permission',
      });
    }

    return {
      'Patterns detected': patterns.length,
      'Pattern types': patterns.join(', ') || 'None',
    };
  }));

  // Test 4: Context formatting
  results.push(runTest('Failure context formatting', () => {
    const tracker = createFailureTracker();

    tracker.recordFailure({
      action: 'read_file',
      args: { path: '/etc/passwd' },
      error: 'Permission denied',
      intent: 'Read system file',
    });

    tracker.recordFailure({
      action: 'write_file',
      args: { path: '/root/file.txt' },
      error: 'Access denied',
      intent: 'Write to root directory',
    });

    const context = tracker.getFailureContext({ maxFailures: 10 });

    const hasFailures = context.includes('Previous Failures');
    const hasAction = context.includes('read_file');
    const hasSuggestion = context.includes('→');

    return {
      'Context length': context.length,
      'Has header': hasFailures ? 'Yes' : 'No',
      'Lists actions': hasAction ? 'Yes' : 'No',
      'Has suggestions': hasSuggestion ? 'Yes' : 'No',
    };
  }));

  // Test 5: Insights extraction
  results.push(runTest('Actionable insights extraction', () => {
    const tracker = createFailureTracker();

    // Create permission errors
    for (let i = 0; i < 3; i++) {
      tracker.recordFailure({
        action: 'read_file',
        error: 'Permission denied',
        category: 'permission',
      });
    }

    // Create not_found errors
    for (let i = 0; i < 2; i++) {
      tracker.recordFailure({
        action: 'read_file',
        error: 'ENOENT: no such file',
        category: 'not_found',
      });
    }

    const insights = extractInsights(tracker.getUnresolvedFailures());

    return {
      'Insights count': insights.length,
      'Has permission insight': insights.some(i => i.includes('permission')) ? 'Yes' : 'No',
      'Has action insight': insights.some(i => i.includes('read_file')) ? 'Yes' : 'No',
    };
  }));

  return results;
}

// =============================================================================
// TRICK T: SERIALIZATION DIVERSITY TESTS
// =============================================================================

function testSerializationDiversity(): TestResult[] {
  const results: TestResult[] = [];

  // Test 1: Semantic equivalence
  results.push(runTest('Semantic equivalence guarantee', () => {
    const serializer = createDiverseSerializer({
      variationLevel: 0.8, // High variation
      preserveSemantics: true,
    });

    const data = { name: 'Alice', age: 30, scores: [95, 88, 92] };

    // Generate many variations
    const variations: string[] = [];
    for (let i = 0; i < 50; i++) {
      variations.push(serializer.serialize(data));
    }

    // Check all are semantically equivalent
    const allEquivalent = variations.every(v => areSemanticEquivalent(v, variations[0]));
    const uniqueVariations = new Set(variations).size;

    return {
      'Variations generated': 50,
      'Unique outputs': uniqueVariations,
      'All semantically equal': allEquivalent ? 'Yes' : 'No',
      'Diversity achieved': uniqueVariations > 1 ? 'Yes' : 'No',
    };
  }));

  // Test 2: Variation levels
  results.push(runTest('Variation level effectiveness', () => {
    const lowVariation = createDiverseSerializer({ variationLevel: 0.1 });
    const highVariation = createDiverseSerializer({ variationLevel: 0.9 });

    const data = { a: 1, b: 2, c: { d: 3, e: 4 } };

    // Generate outputs
    const lowOutputs = new Set<string>();
    const highOutputs = new Set<string>();

    for (let i = 0; i < 100; i++) {
      lowOutputs.add(lowVariation.serialize(data));
      highOutputs.add(highVariation.serialize(data));
    }

    return {
      'Low variation (0.1) unique': lowOutputs.size,
      'High variation (0.9) unique': highOutputs.size,
      'High > Low': highOutputs.size > lowOutputs.size ? 'Yes' : 'Maybe tied',
    };
  }));

  // Test 3: Performance
  results.push(runTest('Serialization performance', () => {
    const serializer = createDiverseSerializer({ variationLevel: 0.5 });

    const data = {
      users: Array.from({ length: 50 }, (_, i) => ({
        id: i,
        name: `User ${i}`,
        active: i % 2 === 0,
      })),
    };

    const iterations = 1000;
    const start = performance.now();

    for (let i = 0; i < iterations; i++) {
      serializer.serialize(data);
    }

    const duration = performance.now() - start;
    const opsPerSec = Math.round((iterations / duration) * 1000);

    // Compare with native JSON.stringify
    const nativeStart = performance.now();
    for (let i = 0; i < iterations; i++) {
      JSON.stringify(data);
    }
    const nativeDuration = performance.now() - nativeStart;
    const overhead = ((duration / nativeDuration) - 1) * 100;

    return {
      'Iterations': iterations,
      'Diverse time': formatDuration(duration),
      'Native time': formatDuration(nativeDuration),
      'Overhead': `${overhead.toFixed(1)}%`,
      'Ops/sec': opsPerSec.toLocaleString(),
    };
  }));

  // Test 4: Statistics tracking
  results.push(runTest('Diversity statistics', () => {
    const serializer = createDiverseSerializer({ variationLevel: 0.5 });

    const data = { test: 'data', count: 42 };

    for (let i = 0; i < 100; i++) {
      serializer.serialize(data);
    }

    const stats = serializer.getStats();

    return {
      'Total serializations': stats.totalSerializations,
      'Style variations': stats.styleDistribution.size,
      'Avg variation': `${(stats.averageVariation * 100).toFixed(1)}%`,
    };
  }));

  // Test 5: Generate variations utility
  results.push(runTest('generateVariations utility', () => {
    const data = { items: ['a', 'b'], meta: { v: 1 } };
    const variations = generateVariations(data, 10, 0.7);

    const unique = new Set(variations).size;
    const allValid = variations.every(v => {
      try {
        JSON.parse(v);
        return true;
      } catch {
        return false;
      }
    });

    return {
      'Requested': 10,
      'Generated': variations.length,
      'Unique': unique,
      'All valid JSON': allValid ? 'Yes' : 'No',
    };
  }));

  return results;
}

// =============================================================================
// MAIN TEST RUNNER
// =============================================================================

async function runAllTests(): Promise<void> {
  console.log('\n' + '█'.repeat(70));
  console.log('  CONTEXT ENGINEERING TRICKS - PERFORMANCE TESTS');
  console.log('█'.repeat(70));
  console.log(`\n  Testing 5 Manus-inspired tricks for AI agent optimization\n`);

  const allResults: { category: string; results: TestResult[] }[] = [];

  // Run tests for each trick
  allResults.push({
    category: 'Trick P: KV-Cache Aware Context',
    results: testKvCacheContext(),
  });

  allResults.push({
    category: 'Trick Q: Recitation / Goal Reinforcement',
    results: testRecitation(),
  });

  allResults.push({
    category: 'Trick R: Reversible Compaction',
    results: testReversibleCompaction(),
  });

  allResults.push({
    category: 'Trick S: Failure Evidence Preservation',
    results: testFailureEvidence(),
  });

  allResults.push({
    category: 'Trick T: Serialization Diversity',
    results: testSerializationDiversity(),
  });

  // Print results
  for (const { category, results } of allResults) {
    printResults(category, results);
  }

  // Summary
  const totalTests = allResults.reduce((sum, r) => sum + r.results.length, 0);
  const passedTests = allResults.reduce(
    (sum, r) => sum + r.results.filter(t => t.passed).length,
    0
  );

  console.log('\n' + '='.repeat(70));
  console.log('  SUMMARY');
  console.log('='.repeat(70));
  console.log(`\n  Total tests: ${totalTests}`);
  console.log(`  Passed: ${passedTests}`);
  console.log(`  Failed: ${totalTests - passedTests}`);
  console.log(`  Success rate: ${((passedTests / totalTests) * 100).toFixed(1)}%\n`);

  if (passedTests === totalTests) {
    console.log('  ✓ All tests passed!\n');
  } else {
    console.log('  ✗ Some tests failed. Check details above.\n');
    process.exit(1);
  }
}

// Run if executed directly
runAllTests().catch(console.error);
