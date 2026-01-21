/**
 * Lesson 19: Observability & Tracing
 *
 * This lesson demonstrates how to monitor and debug agent
 * systems using tracing, metrics, and logging.
 *
 * Key concepts:
 * 1. Distributed tracing with spans
 * 2. Metrics collection and aggregation
 * 3. Structured logging with correlation
 * 4. Export formats
 *
 * Run: npm run lesson:19
 */

import chalk from 'chalk';
import { createTracer, formatTraceTree, formatSpanAttributes } from './tracer.js';
import { createMetricsCollector, formatAgentMetrics, formatAggregation } from './metrics.js';
import { createLogger, formatLogs } from './logger.js';
import { ConsoleExporter, JSONLExporter, OTLPExporter } from './exporter.js';
import type { MODEL_PRICING } from './types.js';

// =============================================================================
// DEMO SETUP
// =============================================================================

console.log(chalk.bold.cyan('╔════════════════════════════════════════════════════════════╗'));
console.log(chalk.bold.cyan('║        Lesson 19: Observability & Tracing                  ║'));
console.log(chalk.bold.cyan('╚════════════════════════════════════════════════════════════╝'));
console.log();

// =============================================================================
// PART 1: WHY OBSERVABILITY?
// =============================================================================

console.log(chalk.bold.yellow('Part 1: Why Observability?'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nWithout observability:'));
console.log(chalk.gray(`
  ┌─────────────────────────────────────────────────────────┐
  │  Agent run fails... but why?                            │
  │                                                         │
  │  ❓ Which LLM call took so long?                        │
  │  ❓ Which tool call failed?                             │
  │  ❓ How much did this run cost?                         │
  │  ❓ What was the sequence of operations?                │
  └─────────────────────────────────────────────────────────┘

  With observability:

  ┌─────────────────────────────────────────────────────────┐
  │  Traces show the full execution path                    │
  │  Metrics track tokens, costs, latencies                 │
  │  Logs provide context for debugging                     │
  │                                                         │
  │  ✓ "LLM call at 2:34:15 took 5.2s (timeout was 5s)"    │
  │  ✓ "Tool 'search' returned 0 results"                  │
  │  ✓ "Total cost: $0.0023, 450 input + 120 output tokens"│
  └─────────────────────────────────────────────────────────┘
`));

// =============================================================================
// PART 2: TRACING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 2: Distributed Tracing'));
console.log(chalk.gray('─'.repeat(60)));

const tracer = createTracer('demo-agent', 1.0);

console.log(chalk.green('\nSimulating an agent run with tracing:'));

// Simulate an agent run with nested spans
const runTrace = await tracer.withSpan('agent.run', async (rootSpan) => {
  tracer.setAttribute(rootSpan, 'agent.goal', 'Find Python tutorials');

  // Planning phase
  await tracer.withSpan('agent.plan', async (planSpan) => {
    tracer.setAttribute(planSpan, 'plan.steps', 3);
    await new Promise((r) => setTimeout(r, 50));
  });

  // LLM call
  await tracer.withSpan('llm.call', async (llmSpan) => {
    tracer.setAttribute(llmSpan, 'llm.model', 'claude-3-sonnet');
    tracer.setAttribute(llmSpan, 'llm.input_tokens', 150);
    tracer.setAttribute(llmSpan, 'llm.output_tokens', 50);
    tracer.addEvent(llmSpan, 'prompt.sent');
    await new Promise((r) => setTimeout(r, 100));
    tracer.addEvent(llmSpan, 'response.received');
  }, { kind: 'client' });

  // Tool calls
  await tracer.withSpan('tool.search', async (toolSpan) => {
    tracer.setAttribute(toolSpan, 'tool.name', 'web_search');
    tracer.setAttribute(toolSpan, 'tool.query', 'Python tutorials');
    await new Promise((r) => setTimeout(r, 80));
    tracer.setAttribute(toolSpan, 'tool.results', 5);
  });

  // Another LLM call to process results
  await tracer.withSpan('llm.call', async (llmSpan) => {
    tracer.setAttribute(llmSpan, 'llm.model', 'claude-3-sonnet');
    tracer.setAttribute(llmSpan, 'llm.input_tokens', 300);
    tracer.setAttribute(llmSpan, 'llm.output_tokens', 100);
    await new Promise((r) => setTimeout(r, 120));
  }, { kind: 'client' });

  return 'success';
});

// Get and display the trace
const traces = tracer.getAllTraces();
const trace = traces[0];

console.log(chalk.white('\n  Trace tree:'));
console.log(chalk.gray('  ' + formatTraceTree(trace).split('\n').join('\n  ')));

console.log(chalk.white('\n  Root span attributes:'));
console.log(chalk.gray('  ' + formatSpanAttributes(trace.rootSpan).split('\n').join('\n  ')));

console.log(chalk.white(`\n  Total trace duration: ${trace.duration}ms`));

// =============================================================================
// PART 3: METRICS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 3: Metrics Collection'));
console.log(chalk.gray('─'.repeat(60)));

const metrics = createMetricsCollector({ service: 'demo-agent' });

console.log(chalk.green('\nRecording agent metrics:'));

// Simulate multiple operations
for (let i = 0; i < 5; i++) {
  // Record LLM calls
  metrics.recordLLMCall(
    'claude-3-sonnet',
    100 + Math.floor(Math.random() * 200),
    30 + Math.floor(Math.random() * 70),
    50 + Math.floor(Math.random() * 100),
    Math.random() > 0.7 // Sometimes cached
  );

  // Record tool calls
  metrics.recordToolCall('search', 30 + Math.floor(Math.random() * 50), true);
  metrics.recordToolCall('read_file', 10 + Math.floor(Math.random() * 20), true);
}

// Simulate some errors
metrics.recordError('timeout', 'llm.call');
metrics.recordRetry('llm.call', 2);

// Get aggregated metrics
const agentMetrics = metrics.getAgentMetrics();

console.log(chalk.white('\n  Agent Metrics Summary:'));
console.log(chalk.gray('  ' + formatAgentMetrics(agentMetrics).split('\n').join('\n  ')));

// Show latency distribution
const llmDuration = metrics.getAggregation('agent.llm.duration');
if (llmDuration) {
  console.log(chalk.white('\n  LLM Latency Distribution:'));
  console.log(chalk.gray('  ' + formatAggregation('agent.llm.duration', llmDuration).split('\n').join('\n  ')));
}

// =============================================================================
// PART 4: LOGGING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 4: Structured Logging'));
console.log(chalk.gray('─'.repeat(60)));

const logger = createLogger('demo', { minLevel: 'debug', outputEnabled: false });

console.log(chalk.green('\nLogging with trace correlation:'));

// Start a span to correlate logs
const logTrace = tracer.startSpan('logging.demo');

logger.info('Starting agent task', { goal: 'Find tutorials' });
logger.debug('Loading configuration', { config: { model: 'claude-3-sonnet' } });
logger.info('Making LLM call', { model: 'claude-3-sonnet', tokens: 150 });
logger.warn('Rate limit approaching', { remaining: 10, reset: '60s' });
logger.info('Task completed successfully');

tracer.endSpan(logTrace);

// Show logs
const entries = logger.getEntries();
console.log(chalk.white('\n  Log entries:'));
for (const entry of entries) {
  const level = entry.level.toUpperCase().padEnd(5);
  const traceInfo = entry.traceId ? ` [${entry.traceId.slice(0, 8)}]` : '';
  const data = entry.data ? ` ${JSON.stringify(entry.data)}` : '';

  const levelColor = {
    debug: chalk.gray,
    info: chalk.blue,
    warn: chalk.yellow,
    error: chalk.red,
    fatal: chalk.magenta,
  }[entry.level];

  console.log(levelColor(`    ${level}${traceInfo}: ${entry.message}${data}`));
}

// =============================================================================
// PART 5: COST TRACKING
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 5: Cost Tracking'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nModel pricing (per 1K tokens):'));
console.log(chalk.gray(`
  Model            │ Input    │ Output
  ─────────────────┼──────────┼──────────
  GPT-4            │ $0.030   │ $0.060
  GPT-4-Turbo      │ $0.010   │ $0.030
  GPT-3.5-Turbo    │ $0.0005  │ $0.0015
  Claude-3-Opus    │ $0.015   │ $0.075
  Claude-3-Sonnet  │ $0.003   │ $0.015
  Claude-3-Haiku   │ $0.00025 │ $0.00125
`));

// Calculate some example costs
const costExamples = [
  { model: 'claude-3-sonnet', input: 1000, output: 500 },
  { model: 'gpt-4', input: 1000, output: 500 },
  { model: 'claude-3-haiku', input: 1000, output: 500 },
];

console.log(chalk.green('\nExample cost calculations (1K input + 500 output):'));
for (const example of costExamples) {
  const cost = metrics.calculateCost(example.model, example.input, example.output);
  console.log(chalk.gray(`  ${example.model.padEnd(20)} $${cost.toFixed(5)}`));
}

// =============================================================================
// PART 6: EXPORT FORMATS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 6: Export Formats'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nAvailable export formats:'));
console.log(chalk.gray(`
  console  - Human-readable console output
  json     - Full JSON (good for analysis)
  jsonl    - JSON Lines (good for streaming)
  otlp     - OpenTelemetry Protocol (for observability platforms)
`));

// Demonstrate different exporters
console.log(chalk.green('\nConsole exporter (human-readable):'));
const consoleExporter = new ConsoleExporter(false);
// Export a single span
const demoSpan = trace.spans[0];
await consoleExporter.exportSpans([demoSpan]);

console.log(chalk.green('\nJSONL exporter (streaming format):'));
const jsonlExporter = new JSONLExporter();
await jsonlExporter.exportSpans([demoSpan]);
await jsonlExporter.flush();

// =============================================================================
// PART 7: ALERTING PATTERNS
// =============================================================================

console.log();
console.log(chalk.bold.yellow('Part 7: Alerting Patterns'));
console.log(chalk.gray('─'.repeat(60)));

console.log(chalk.white('\nCommon alerting patterns:'));
console.log(chalk.gray(`
  Latency Alert:
    IF p95(llm.duration) > 5000ms THEN alert "LLM latency high"

  Error Rate:
    IF errors / total > 0.05 THEN alert "Error rate > 5%"

  Cost Alert:
    IF daily_cost > $10 THEN alert "Daily cost exceeded budget"

  Token Usage:
    IF tokens.today > 100000 THEN alert "High token usage"

  Implementation:
    metrics.on((event) => {
      if (event.type === 'metric.recorded') {
        if (event.metric.name === 'agent.errors') {
          // Check error rate and alert
        }
      }
    });
`));

// =============================================================================
// SUMMARY
// =============================================================================

console.log();
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log(chalk.bold.cyan('Summary'));
console.log(chalk.bold.cyan('═'.repeat(60)));
console.log();
console.log(chalk.white('What we learned:'));
console.log(chalk.gray('  1. Traces show the full execution path with timing'));
console.log(chalk.gray('  2. Metrics track tokens, costs, and latencies'));
console.log(chalk.gray('  3. Logs provide context, correlated with traces'));
console.log(chalk.gray('  4. Multiple export formats for different needs'));
console.log(chalk.gray('  5. Cost tracking enables budget management'));
console.log();
console.log(chalk.white('Key components:'));
console.log(chalk.gray('  • Tracer - Creates and manages spans'));
console.log(chalk.gray('  • MetricsCollector - Records and aggregates metrics'));
console.log(chalk.gray('  • Logger - Structured logging with trace correlation'));
console.log(chalk.gray('  • Exporter - Output in various formats'));
console.log();
console.log(chalk.bold.green('Next: Lesson 20 - Sandboxing & Isolation'));
console.log(chalk.gray('Run untrusted code safely!'));
console.log();
