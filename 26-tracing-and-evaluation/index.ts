/**
 * Lesson 26: Tracing and Evaluation
 *
 * State-of-the-art observability and benchmark-based evaluation
 * for AI coding agents.
 *
 * @example
 * ```typescript
 * import {
 *   createTraceCollector,
 *   createBenchmarkRunner,
 *   createResultStore,
 *   allSuites,
 * } from './26-tracing-and-evaluation/index.js';
 *
 * // Set up tracing
 * const collector = createTraceCollector({ outputPath: '.traces' });
 * const sessionId = collector.startSession('my-task', 'claude-3-5-sonnet');
 *
 * // Run benchmarks
 * const runner = createBenchmarkRunner({ model: 'claude-3-5-sonnet' });
 * const result = await runner.runSuite(allSuites[0]);
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

export type {
  // Trace types
  LLMRequestTrace,
  ToolExecutionTrace,
  SessionTrace,
  IterationTrace,
  TracedMessage,
  TracedToolDefinition,
  TracedToolCall,
  TokenBreakdown,
  CacheBreakdown,
  CacheBreakpointInfo,

  // Benchmark types
  BenchmarkTask,
  BenchmarkSuite,
  BenchmarkSandbox,
  ExpectedOutcome,
  ValidationResult,
  TaskResult,
  SuiteResult,
  RunComparison,

  // Configuration types
  TraceCollectorConfig,
  BenchmarkRunnerConfig,

  // JSONL entry types
  SessionStartEntry,
  SessionEndEntry,
  LLMRequestEntry,
  LLMResponseEntry,
  ToolExecutionEntry,
  JSONLEntry,
} from './types.js';

// =============================================================================
// TRACING
// =============================================================================

export {
  TraceCollector,
  createTraceCollector,
} from './trace-collector.js';

export {
  TraceExporter,
  createTraceExporter,
} from './trace-exporter.js';

export {
  TraceVisualizer,
  createTraceVisualizer,
} from './trace-visualizer.js';

export {
  CacheBoundaryTracker,
  createCacheBoundaryTracker,
} from './cache-boundary-tracker.js';

export {
  TracedAgentWrapper,
  createTracedAgentWrapper,
} from './agent-integration.js';

// =============================================================================
// EVALUATION
// =============================================================================

export {
  BenchmarkRunner,
  createBenchmarkRunner,
} from './evaluation/benchmark-runner.js';

export {
  ResultStore,
  createResultStore,
} from './evaluation/result-store.js';

export {
  validateTask,
  validateSuite,
  validateExpectedOutcome,
  task,
  suite,
  BenchmarkTaskBuilder,
  BenchmarkSuiteBuilder,
} from './evaluation/benchmark-schema.js';

// =============================================================================
// REPORTERS
// =============================================================================

export {
  ConsoleReporter,
  createConsoleReporter,
} from './evaluation/reporters/console.js';

export {
  MarkdownReporter,
  createMarkdownReporter,
} from './evaluation/reporters/markdown.js';

// =============================================================================
// BUILT-IN BENCHMARKS
// =============================================================================

export {
  simpleCodingSuite,
  bugFixingSuite,
  fileEditingSuite,
  multiFileSuite,
  allSuites,
  getSuiteById,
  getSuitesByCategory,
  getAvailableSuiteIds,
  getTotalTaskCount,
  getBenchmarkStats,
} from './evaluation/benchmarks/index.js';

// =============================================================================
// DEFAULT CONFIG
// =============================================================================

import { DEFAULT_TRACE_CONFIG, DEFAULT_BENCHMARK_CONFIG } from './types.js';

export const defaultTraceConfig = DEFAULT_TRACE_CONFIG;
export const defaultBenchmarkConfig = DEFAULT_BENCHMARK_CONFIG;
