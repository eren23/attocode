/**
 * Lesson 26: Console Reporter
 *
 * Formats benchmark results for console output with colors and structure.
 */

import type { SuiteResult, TaskResult, RunComparison } from '../../types.js';

// =============================================================================
// COLORS
// =============================================================================

const COLORS = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
};

function color(c: keyof typeof COLORS, text: string): string {
  return `${COLORS[c]}${text}${COLORS.reset}`;
}

// =============================================================================
// CONSOLE REPORTER
// =============================================================================

/**
 * Report benchmark results to console.
 */
export class ConsoleReporter {
  private useColors: boolean;

  constructor(useColors: boolean = true) {
    this.useColors = useColors;
  }

  /**
   * Report suite results.
   */
  reportSuite(result: SuiteResult): void {
    this.printHeader(result);
    this.printTaskResults(result.taskResults);
    this.printMetrics(result);
    this.printCategoryBreakdown(result);
    this.printFooter(result);
  }

  /**
   * Report a single task result (for progress).
   */
  reportTask(result: TaskResult, taskName?: string): void {
    const icon = result.passed
      ? this.c('green', '✓')
      : this.c('red', '✗');

    const name = taskName ?? result.taskId;
    const duration = `${(result.durationMs / 1000).toFixed(1)}s`;
    const iterations = `${result.iterations} iter`;
    const tokens = `${result.totalTokens.toLocaleString()} tok`;

    console.log(`  ${icon} ${name.padEnd(30)} ${duration.padStart(8)} ${iterations.padStart(10)} ${tokens.padStart(12)}`);

    if (!result.passed && result.validation.message) {
      console.log(`    ${this.c('dim', result.validation.message)}`);
    }
  }

  /**
   * Report comparison results.
   */
  reportComparison(comparison: RunComparison): void {
    console.log('');
    console.log(this.c('bold', '═══════════════════════════════════════════════════════════'));
    console.log(this.c('bold', '                    BENCHMARK COMPARISON'));
    console.log(this.c('bold', '═══════════════════════════════════════════════════════════'));
    console.log('');
    console.log(`  Baseline:    ${comparison.baselineRunId}`);
    console.log(`  Comparison:  ${comparison.comparisonRunId}`);
    console.log('');

    this.printComparisonMetrics(comparison);
    this.printRegressions(comparison);
    this.printImprovements(comparison);
    this.printComparisonSummary(comparison);
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  private printHeader(result: SuiteResult): void {
    console.log('');
    console.log(this.c('bold', '═══════════════════════════════════════════════════════════'));
    console.log(this.c('bold', `  Benchmark: ${result.suiteId}`));
    console.log(this.c('bold', '═══════════════════════════════════════════════════════════'));
    console.log('');
    console.log(`  Model: ${this.c('cyan', result.model)}`);
    console.log(`  Run ID: ${result.runId.slice(0, 8)}`);
    console.log(`  Started: ${new Date(result.startTime).toISOString()}`);
    console.log('');
    console.log(this.c('dim', '  Task'.padEnd(34) + 'Duration'.padStart(8) + 'Iterations'.padStart(12) + 'Tokens'.padStart(12)));
    console.log(this.c('dim', '  ' + '─'.repeat(62)));
  }

  private printTaskResults(results: TaskResult[]): void {
    for (const result of results) {
      this.reportTask(result);
    }
  }

  private printMetrics(result: SuiteResult): void {
    const m = result.metrics;

    console.log('');
    console.log(this.c('bold', '─── Summary ──────────────────────────────────────────────'));
    console.log('');

    // Pass@1 with color based on value
    const passColor = m.passAt1 >= 0.8 ? 'green' : m.passAt1 >= 0.5 ? 'yellow' : 'red';
    console.log(`  Pass@1:       ${this.c(passColor, `${(m.passAt1 * 100).toFixed(1)}%`)} (${m.passedTasks}/${m.totalTasks})`);

    console.log(`  Avg Iterations: ${m.avgIterations.toFixed(1)}`);
    console.log(`  Avg Tokens:     ${m.avgTokens.toLocaleString()}`);
    console.log(`  Total Cost:     ${this.c('yellow', '$' + m.totalCost.toFixed(4))}`);
    console.log(`  Duration:       ${(result.durationMs / 1000).toFixed(1)}s`);
  }

  private printCategoryBreakdown(result: SuiteResult): void {
    const m = result.metrics;

    if (Object.keys(m.byCategory).length > 1) {
      console.log('');
      console.log(this.c('bold', '─── By Category ──────────────────────────────────────────'));
      console.log('');

      for (const [cat, data] of Object.entries(m.byCategory)) {
        const passColor = data.passRate >= 0.8 ? 'green' : data.passRate >= 0.5 ? 'yellow' : 'red';
        console.log(`  ${cat.padEnd(20)} ${this.c(passColor, `${(data.passRate * 100).toFixed(0)}%`.padStart(5))} (${data.passed}/${data.total})`);
      }
    }

    if (Object.keys(m.byDifficulty).length > 1) {
      console.log('');
      console.log(this.c('bold', '─── By Difficulty ────────────────────────────────────────'));
      console.log('');

      for (const diff of ['easy', 'medium', 'hard']) {
        const data = m.byDifficulty[diff];
        if (!data) continue;

        const passColor = data.passRate >= 0.8 ? 'green' : data.passRate >= 0.5 ? 'yellow' : 'red';
        console.log(`  ${diff.padEnd(20)} ${this.c(passColor, `${(data.passRate * 100).toFixed(0)}%`.padStart(5))} (${data.passed}/${data.total})`);
      }
    }
  }

  private printFooter(result: SuiteResult): void {
    console.log('');
    console.log(this.c('bold', '═══════════════════════════════════════════════════════════'));
    console.log('');
  }

  private printComparisonMetrics(comparison: RunComparison): void {
    console.log(this.c('bold', '─── Metrics ──────────────────────────────────────────────'));
    console.log('');

    this.printMetricRow('Pass@1', comparison.baseline.passAt1, comparison.comparison.passAt1, comparison.diff.passAt1, true);
    this.printMetricRow('Avg Iterations', comparison.baseline.avgIterations, comparison.comparison.avgIterations, comparison.diff.avgIterations, false);
    this.printMetricRow('Avg Tokens', comparison.baseline.avgTokens, comparison.comparison.avgTokens, comparison.diff.avgTokens, false);
    this.printMetricRow('Total Cost', comparison.baseline.totalCost, comparison.comparison.totalCost, comparison.diff.totalCost, false);
    console.log('');
  }

  private printMetricRow(name: string, baseline: number, comparison: number, diff: number, isPercentage: boolean): void {
    const formatValue = (v: number) => {
      if (isPercentage) return `${(v * 100).toFixed(1)}%`;
      if (v < 1) return v.toFixed(4);
      return v.toFixed(1);
    };

    const formatDiff = (d: number) => {
      const sign = d >= 0 ? '+' : '';
      if (isPercentage) return `${sign}${(d * 100).toFixed(1)}%`;
      return `${sign}${d.toFixed(2)}`;
    };

    const diffColor = (isPercentage && diff > 0) || (!isPercentage && name === 'Pass@1' && diff > 0)
      ? 'green'
      : diff < 0 && name === 'Pass@1'
        ? 'red'
        : 'dim';

    const diffStr = this.c(diffColor, formatDiff(diff));
    console.log(`  ${name.padEnd(16)} ${formatValue(baseline).padStart(10)} → ${formatValue(comparison).padStart(10)}  (${diffStr})`);
  }

  private printRegressions(comparison: RunComparison): void {
    if (comparison.regressions.length === 0) return;

    console.log(this.c('red', '─── Regressions ──────────────────────────────────────────'));
    console.log('');

    for (const reg of comparison.regressions) {
      console.log(`  ${this.c('red', '✗')} ${reg.taskId}`);
    }
    console.log('');
  }

  private printImprovements(comparison: RunComparison): void {
    if (comparison.improvements.length === 0) return;

    console.log(this.c('green', '─── Improvements ─────────────────────────────────────────'));
    console.log('');

    for (const imp of comparison.improvements) {
      console.log(`  ${this.c('green', '✓')} ${imp.taskId}`);
    }
    console.log('');
  }

  private printComparisonSummary(comparison: RunComparison): void {
    console.log(this.c('bold', '─── Summary ──────────────────────────────────────────────'));
    console.log('');

    const netChange = comparison.improvements.length - comparison.regressions.length;
    if (netChange > 0) {
      console.log(`  ${this.c('green', `Net improvement: +${netChange} tasks`)}`);
    } else if (netChange < 0) {
      console.log(`  ${this.c('red', `Net regression: ${netChange} tasks`)}`);
    } else {
      console.log('  No net change');
    }

    console.log('');
    console.log(this.c('bold', '═══════════════════════════════════════════════════════════'));
    console.log('');
  }

  /**
   * Apply color if enabled.
   */
  private c(colorName: keyof typeof COLORS, text: string): string {
    if (!this.useColors) return text;
    return color(colorName, text);
  }
}

/**
 * Create a console reporter.
 */
export function createConsoleReporter(useColors: boolean = true): ConsoleReporter {
  return new ConsoleReporter(useColors);
}
