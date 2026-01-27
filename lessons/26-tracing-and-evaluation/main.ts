/**
 * ╔═══════════════════════════════════════════════════════════════════════════╗
 * ║                                                                           ║
 * ║              LESSON 26: TRACING AND EVALUATION                            ║
 * ║                                                                           ║
 * ║   State-of-the-art observability and benchmark-based evaluation           ║
 * ║   for AI coding agents.                                                   ║
 * ║                                                                           ║
 * ╚═══════════════════════════════════════════════════════════════════════════╝
 *
 * This lesson teaches you to:
 *
 * 1. TRACE everything - LLM requests, tool executions, token usage
 * 2. MEASURE cache efficiency - understand KV cache hit rates
 * 3. BENCHMARK systematically - SWE-bench style pass@1 metrics
 * 4. COMPARE runs - detect regressions and improvements
 *
 * Why This Matters:
 * ─────────────────
 * - You can't improve what you can't measure
 * - Token costs add up fast; cache efficiency is crucial
 * - Agent quality must be quantified, not guessed
 * - Regressions happen; you need to catch them early
 *
 * Run with:
 *   npx tsx 26-tracing-and-evaluation/main.ts [--trace|--eval|--compare]
 */

import { parseArgs } from 'node:util';
import { TraceCollector, createTraceCollector } from './trace-collector.js';
import { TraceVisualizer, createTraceVisualizer } from './trace-visualizer.js';
import { TraceExporter, createTraceExporter } from './trace-exporter.js';
import { CacheBoundaryTracker, createCacheBoundaryTracker } from './cache-boundary-tracker.js';
import { BenchmarkRunner, createBenchmarkRunner } from './evaluation/benchmark-runner.js';
import { ResultStore, createResultStore } from './evaluation/result-store.js';
import { ConsoleReporter, createConsoleReporter } from './evaluation/reporters/console.js';
import { MarkdownReporter, createMarkdownReporter } from './evaluation/reporters/markdown.js';
import { allSuites, getSuiteById, getBenchmarkStats } from './evaluation/benchmarks/index.js';
import type { TracedMessage, CacheBreakdown } from './types.js';

// =============================================================================
// PART 1: WHY TRACING MATTERS
// =============================================================================

function part1_WhyTracingMatters(): void {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  PART 1: WHY TRACING MATTERS                                              ║
╚═══════════════════════════════════════════════════════════════════════════╝

In production AI systems, you need visibility into:

┌─────────────────────────────────────────────────────────────────────────┐
│  WHAT TO TRACE                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. LLM REQUESTS                                                        │
│     • Full message content (system, user, assistant)                    │
│     • Tool definitions sent                                             │
│     • Model parameters (temperature, max_tokens)                        │
│                                                                         │
│  2. LLM RESPONSES                                                       │
│     • Generated content                                                 │
│     • Tool calls made                                                   │
│     • Stop reason (end_turn, tool_use, max_tokens)                      │
│                                                                         │
│  3. TOKEN BREAKDOWN                                                     │
│     • Input tokens (what you sent)                                      │
│     • Output tokens (what was generated)                                │
│     • Cache read tokens (from KV cache)                                 │
│     • Cache write tokens (written to KV cache)                          │
│                                                                         │
│  4. TOOL EXECUTIONS                                                     │
│     • Which tool was called                                             │
│     • Input parameters                                                  │
│     • Result or error                                                   │
│     • Duration                                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

Why Full Traces?
────────────────
• Debug failures: See exactly what the model saw
• Optimize prompts: Identify bloated system prompts
• Track costs: Know where tokens are spent
• Detect drift: Compare behavior across versions

`);
}

// =============================================================================
// PART 2: FULL TRACE CAPTURE DEMO
// =============================================================================

function part2_TraceCapture(): void {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  PART 2: FULL TRACE CAPTURE                                               ║
╚═══════════════════════════════════════════════════════════════════════════╝

The TraceCollector is the central hub for all observability data.
It captures events from your agent and writes them to JSONL format.

Usage:
──────
\`\`\`typescript
import { createTraceCollector } from './trace-collector.js';

const collector = createTraceCollector({
  outputDir: '.traces',
  captureMessageContent: true,
  captureToolResults: true,
});

// Start a session
collector.startSession('Fix bug in auth.ts', 'claude-3-5-sonnet');

// Record events as they happen...
collector.recordLLMRequest({ messages, tools });
collector.recordLLMResponse({ content, toolCalls, tokens });
collector.recordToolExecution({ name: 'read_file', result, duration });

// End session
await collector.endSession('success', 'Bug fixed');
\`\`\`

Example JSONL output:
─────────────────────────────────────────────────────────────────────

{"_type":"session.start","_ts":"2024-01-15T10:00:00.000Z","sessionId":"abc123","task":"example-task","model":"claude-3-5-sonnet"}
{"_type":"llm.request","_ts":"2024-01-15T10:00:01.000Z","requestId":"req1","messageCount":3,"toolCount":15}
{"_type":"llm.response","_ts":"2024-01-15T10:00:03.000Z","requestId":"req1","tokens":{"input":5000,"output":150,"cacheRead":4200,"cacheWrite":800}}
{"_type":"tool.execution","_ts":"2024-01-15T10:00:03.500Z","toolName":"read_file","durationMs":50,"status":"success"}
{"_type":"session.end","_ts":"2024-01-15T10:00:10.000Z","sessionId":"abc123","status":"success","totalTokens":5150}

─────────────────────────────────────────────────────────────────────

Key Design Decisions:
─────────────────────
1. JSONL format: One JSON object per line, easy to process
2. Discriminated unions: _type field enables type-safe parsing
3. Timestamps: ISO format for cross-system compatibility
4. Async writes: Non-blocking, uses write queue pattern

`);
}

// =============================================================================
// PART 3: CACHE EFFICIENCY ANALYSIS
// =============================================================================

function part3_CacheEfficiency(): void {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  PART 3: CACHE EFFICIENCY ANALYSIS                                        ║
╚═══════════════════════════════════════════════════════════════════════════╝

Anthropic's KV cache can dramatically reduce costs and latency.
Understanding your cache hit rate is crucial for optimization.

How KV Cache Works:
───────────────────
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  Request 1:  [System Prompt] [User Message 1]                            │
│              └───────────────────┬───────────────────┘                   │
│                    Written to cache (cache_write_tokens)                 │
│                                                                          │
│  Request 2:  [System Prompt] [User Message 1] [Assistant 1] [User 2]     │
│              └─────── Cache Hit ────────────┘ └── Fresh ──┘              │
│                   (cache_read_tokens)          (input_tokens)            │
│                                                                          │
│  Cache hits = FREE input tokens! (or heavily discounted)                 │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

`);

  // Demo cache boundary tracking
  const tracker = createCacheBoundaryTracker();

  // Simulate requests with proper structure
  const request1 = {
    systemPrompt: 'You are a helpful assistant.',
    messages: [
      { role: 'user' as const, content: 'Hello!', estimatedTokens: 5 },
    ],
  };

  const request2 = {
    systemPrompt: 'You are a helpful assistant.',
    messages: [
      { role: 'user' as const, content: 'Hello!', estimatedTokens: 5 },
      { role: 'assistant' as const, content: 'Hi there!', estimatedTokens: 5 },
      { role: 'user' as const, content: 'How are you?', estimatedTokens: 5 },
    ],
  };

  tracker.recordRequest(request1);
  tracker.recordResponse(15, 5, 10);

  tracker.recordRequest(request2);
  tracker.recordResponse(25, 15, 10);

  const analysis = tracker.analyze();

  console.log(`
Demo Cache Analysis:
────────────────────
  Overall Hit Rate:     ${(analysis.hitRate * 100).toFixed(1)}%
  Avg Hit Rate:         ${(analysis.avgHitRate * 100).toFixed(1)}%
  Tokens Saved:         ${analysis.tokensSaved}
  Estimated Savings:    $${analysis.estimatedSavings.toFixed(4)}
  Trend:                ${analysis.trend}

Recommendations:
`);

  for (const rec of analysis.recommendations) {
    console.log(`  • ${rec}`);
  }

  console.log(`

Cache Optimization Tips:
────────────────────────
1. Keep system prompts stable (any change invalidates the whole cache)
2. Use cache_control markers for multi-turn conversations
3. Avoid dynamic content early in the message sequence
4. Monitor cache hit rate in production

`);
}

// =============================================================================
// PART 4: RUNNING BENCHMARKS
// =============================================================================

async function part4_RunningBenchmarks(): Promise<void> {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  PART 4: RUNNING BENCHMARKS                                               ║
╚═══════════════════════════════════════════════════════════════════════════╝

Benchmarks give you quantitative measures of agent quality.
We use SWE-bench style metrics focused on Pass@1.

Available Benchmark Suites:
───────────────────────────
`);

  const stats = getBenchmarkStats();

  for (const suite of allSuites) {
    console.log(`  📦 ${suite.id.padEnd(20)} ${suite.tasks.length} tasks`);
    console.log(`     ${suite.description}`);
    console.log('');
  }

  console.log(`
Summary:
  Total Suites:  ${stats.totalSuites}
  Total Tasks:   ${stats.totalTasks}
  By Difficulty: easy=${stats.byDifficulty['easy'] ?? 0}, medium=${stats.byDifficulty['medium'] ?? 0}, hard=${stats.byDifficulty['hard'] ?? 0}

Key Metrics:
────────────
  • Pass@1:         Success rate on first attempt
  • Avg Iterations: Agent turns needed per task
  • Avg Tokens:     Tokens consumed per task
  • Total Cost:     Dollar cost for the run

How to Run:
───────────
  # Run a specific suite
  npx tsx 26-tracing-and-evaluation/main.ts --eval simple-coding

  # Run all suites
  npx tsx 26-tracing-and-evaluation/main.ts --eval all

`);
}

// =============================================================================
// PART 5: COMPARING RESULTS
// =============================================================================

async function part5_ComparingResults(): Promise<void> {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  PART 5: COMPARING RESULTS                                                ║
╚═══════════════════════════════════════════════════════════════════════════╝

Compare benchmark runs to detect regressions and improvements.

Example Comparison Report:
──────────────────────────

  ═══════════════════════════════════════════════════════════════
                      BENCHMARK COMPARISON
  ═══════════════════════════════════════════════════════════════

    Baseline:    run-2024-01-10-claude-3-5-sonnet
    Comparison:  run-2024-01-15-claude-3-5-sonnet-v2

  ─── Metrics ──────────────────────────────────────────────────

    Pass@1           80.0% →     85.0%  (+5.0%)
    Avg Iterations    2.5  →      2.3   (-0.2)
    Avg Tokens       5000  →     4500   (-500)
    Total Cost      $0.50 →    $0.45   (-$0.05)

  ─── Regressions ──────────────────────────────────────────────

    ✗ bug-fixing-003 (was passing, now failing)

  ─── Improvements ─────────────────────────────────────────────

    ✓ multi-file-002 (was failing, now passing)
    ✓ multi-file-003 (was failing, now passing)

  ─── Summary ──────────────────────────────────────────────────

    Net improvement: +1 tasks

  ═══════════════════════════════════════════════════════════════

How to Compare:
───────────────
  # Compare two runs
  npx tsx 26-tracing-and-evaluation/main.ts --compare run-abc,run-xyz

Results are stored in .eval-results/ as JSONL files.

`);
}

// =============================================================================
// VISUALIZATION DEMO
// =============================================================================

function showVisualizationDemo(): void {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  BONUS: TRACE VISUALIZATION                                               ║
╚═══════════════════════════════════════════════════════════════════════════╝

The TraceVisualizer formats session data as a readable tree:

Example Output:
───────────────

Session: abc123
Task: Fix the off-by-one error
Model: claude-3-5-sonnet
Duration: 15.2s
═══════════════════════════════════════════════════════════════

✓ Iteration 1 (4.2s)
   ├── Messages: 3 (system, user, assistant)
   ├── Tokens: 6,000 in / 150 out
   ├── Cache: 83% hit rate (5,000 read, 1,000 fresh)
   └── Tools:
       ├── ✓ read_file (src/sum.ts) - 52ms
       └── ✓ edit_file (src/sum.ts) - 18ms

✓ Iteration 2 (2.1s)
   ├── Messages: 5
   ├── Tokens: 6,200 in / 80 out
   ├── Cache: 94% hit rate (5,800 read, 400 fresh)
   └── Tools:
       └── ✓ run_tests - 1,850ms

═══════════════════════════════════════════════════════════════
Summary:
  Total Iterations: 2
  Total Tokens: 12,200 in / 230 out
  Total Cost: $0.0367
  Outcome: SUCCESS
═══════════════════════════════════════════════════════════════

`);
}

// =============================================================================
// PART 6: INTEGRATION WITH PRODUCTION AGENT
// =============================================================================

function part6_ProductionAgentIntegration(): void {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  PART 6: PRODUCTION AGENT INTEGRATION (LESSON 25)                         ║
╚═══════════════════════════════════════════════════════════════════════════╝

Trace capture is integrated directly into the ProductionAgent from Lesson 25.

Enable it via the observability config:
────────────────────────────────────────

\`\`\`typescript
import { createProductionAgent } from '../25-production-agent/agent.js';

const agent = createProductionAgent({
  provider: myProvider,
  tools: myTools,
  observability: {
    enabled: true,
    // Standard observability (spans, metrics, logging)
    tracing: { enabled: true, serviceName: 'my-agent' },
    metrics: { enabled: true, collectTokens: true },

    // Full trace capture (Lesson 26)
    traceCapture: {
      enabled: true,                    // Enable JSONL trace capture
      outputDir: '.traces',              // Where to save traces
      captureMessageContent: true,       // Include full message text
      captureToolResults: true,          // Include tool outputs
      analyzeCacheBoundaries: true,      // Track KV cache efficiency
    },
  },
});

// Run the agent
const result = await agent.run('Implement a FizzBuzz function');

// Access trace collector for analysis
const traceCollector = agent.getTraceCollector();
if (traceCollector) {
  const sessionTrace = traceCollector.getSessionTrace();
  console.log('Iterations:', sessionTrace?.iterations.length);
  console.log('Total tokens:', sessionTrace?.totalTokens);
}
\`\`\`

Output Files:
─────────────
Traces are saved as JSONL files in the output directory:

  .traces/
    trace-session-abc123-2024-01-15.jsonl

Each line is a JSON object with a _type field:

  {"_type":"session.start","_ts":"...","task":"..."}
  {"_type":"llm.request","_ts":"...","messages":[...]}
  {"_type":"llm.response","_ts":"...","tokens":{...}}
  {"_type":"tool.execution","_ts":"...","toolName":"read_file"}
  {"_type":"session.end","_ts":"...","status":"success"}

`);
}

// =============================================================================
// MAIN ENTRY POINT
// =============================================================================

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      trace: { type: 'boolean', default: false },
      eval: { type: 'string', default: '' },
      compare: { type: 'string', default: '' },
      help: { type: 'boolean', short: 'h', default: false },
      all: { type: 'boolean', default: false },
    },
    allowPositionals: true,
  });

  if (values.help) {
    printHelp();
    return;
  }

  // Show trace demo
  if (values.trace) {
    part1_WhyTracingMatters();
    part2_TraceCapture();
    part3_CacheEfficiency();
    part6_ProductionAgentIntegration();
    showVisualizationDemo();
    return;
  }

  // Run evaluation
  if (values.eval) {
    await runEvaluation(values.eval);
    return;
  }

  // Compare runs
  if (values.compare) {
    await compareRuns(values.compare);
    return;
  }

  // Default: show all educational content
  if (values.all) {
    part1_WhyTracingMatters();
    part2_TraceCapture();
    part3_CacheEfficiency();
    await part4_RunningBenchmarks();
    await part5_ComparingResults();
    part6_ProductionAgentIntegration();
    showVisualizationDemo();
    return;
  }

  // Interactive menu
  printWelcome();
}

function printWelcome(): void {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║              LESSON 26: TRACING AND EVALUATION                            ║
║                                                                           ║
║   State-of-the-art observability and benchmark-based evaluation           ║
║   for AI coding agents.                                                   ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝

Usage:
  npx tsx 26-tracing-and-evaluation/main.ts [options]

Options:
  --trace              Show tracing demo (Parts 1-3, 6)
  --eval <suite>       Run a benchmark suite (e.g., simple-coding)
  --compare <a,b>      Compare two benchmark runs
  --all                Show all educational content (Parts 1-6)
  -h, --help           Show this help message

Integration with Lesson 25:
  Trace capture is built into ProductionAgent via observability.traceCapture

Available Benchmark Suites:
`);

  for (const suite of allSuites) {
    console.log(`  • ${suite.id.padEnd(18)} (${suite.tasks.length} tasks)`);
  }

  console.log(`
Examples:
  npx tsx 26-tracing-and-evaluation/main.ts --trace
  npx tsx 26-tracing-and-evaluation/main.ts --eval simple-coding
  npx tsx 26-tracing-and-evaluation/main.ts --compare run-001,run-002
  npx tsx 26-tracing-and-evaluation/main.ts --all
`);
}

function printHelp(): void {
  printWelcome();
}

async function runEvaluation(suiteId: string): Promise<void> {
  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  RUNNING BENCHMARK: ${suiteId.padEnd(54)}║
╚═══════════════════════════════════════════════════════════════════════════╝
`);

  const suite = getSuiteById(suiteId);
  if (!suite) {
    console.error(`Unknown suite: ${suiteId}`);
    console.log('Available suites:', allSuites.map(s => s.id).join(', '));
    process.exit(1);
  }

  console.log(`Suite: ${suite.name}`);
  console.log(`Description: ${suite.description}`);
  console.log(`Tasks: ${suite.tasks.length}`);
  console.log('');

  console.log('⚠️  Note: Running benchmarks requires an agent implementation.');
  console.log('   This demo shows the benchmark structure without execution.');
  console.log('');

  console.log('Tasks in this suite:');
  console.log('─'.repeat(70));

  for (const task of suite.tasks) {
    const diffIcon = task.difficulty === 'easy' ? '🟢' : task.difficulty === 'medium' ? '🟡' : '🔴';
    console.log(`  ${diffIcon} ${task.id.padEnd(25)} ${task.name}`);
    console.log(`     Category: ${task.category}, Timeout: ${task.timeout / 1000}s`);
  }

  console.log('');
  console.log('To run with a real agent, integrate TracedAgentWrapper from agent-integration.ts');
}

async function compareRuns(runIds: string): Promise<void> {
  const [baselineId, comparisonId] = runIds.split(',');

  if (!baselineId || !comparisonId) {
    console.error('Usage: --compare baseline-id,comparison-id');
    process.exit(1);
  }

  console.log(`
╔═══════════════════════════════════════════════════════════════════════════╗
║  COMPARING RUNS                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝

Baseline:    ${baselineId}
Comparison:  ${comparisonId}

⚠️  Note: No results found in .eval-results/ directory.
   Run benchmarks first to generate results to compare.

Example workflow:
  1. npx tsx main.ts --eval simple-coding  # Creates run-001.jsonl
  2. # Make changes to your agent
  3. npx tsx main.ts --eval simple-coding  # Creates run-002.jsonl
  4. npx tsx main.ts --compare run-001,run-002
`);
}

// Run main
main().catch(console.error);
