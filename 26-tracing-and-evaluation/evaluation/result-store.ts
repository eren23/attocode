/**
 * Lesson 26: Result Store
 *
 * Stores benchmark results and enables comparison between runs.
 * Results are saved as JSON files for persistence and analysis.
 *
 * @example
 * ```typescript
 * import { ResultStore } from './result-store.js';
 *
 * const store = new ResultStore('.eval-results');
 *
 * // Save results
 * await store.save(suiteResult);
 *
 * // Load and compare
 * const baseline = await store.load('run-abc');
 * const comparison = await store.load('run-xyz');
 * const diff = store.compare(baseline, comparison);
 * ```
 */

import { mkdir, writeFile, readFile, readdir } from 'fs/promises';
import { join } from 'path';
import type {
  SuiteResult,
  TaskResult,
  RunComparison,
} from '../types.js';

// =============================================================================
// RESULT STORE
// =============================================================================

/**
 * Stores and retrieves benchmark results.
 */
export class ResultStore {
  private outputDir: string;

  constructor(outputDir: string = '.eval-results') {
    this.outputDir = outputDir;
  }

  /**
   * Save a suite result.
   */
  async save(result: SuiteResult): Promise<string> {
    await mkdir(this.outputDir, { recursive: true });

    const filename = `${result.suiteId}-${result.runId}.json`;
    const filepath = join(this.outputDir, filename);

    await writeFile(filepath, JSON.stringify(result, null, 2));

    return filepath;
  }

  /**
   * Load a suite result by run ID.
   */
  async load(runId: string): Promise<SuiteResult | null> {
    try {
      const files = await readdir(this.outputDir);
      const matchingFile = files.find(f => f.includes(runId) && f.endsWith('.json'));

      if (!matchingFile) {
        return null;
      }

      const filepath = join(this.outputDir, matchingFile);
      const content = await readFile(filepath, 'utf-8');
      return JSON.parse(content) as SuiteResult;
    } catch {
      return null;
    }
  }

  /**
   * Load all results for a suite.
   */
  async loadAllForSuite(suiteId: string): Promise<SuiteResult[]> {
    try {
      const files = await readdir(this.outputDir);
      const matchingFiles = files.filter(f => f.startsWith(suiteId) && f.endsWith('.json'));

      const results: SuiteResult[] = [];
      for (const file of matchingFiles) {
        const filepath = join(this.outputDir, file);
        const content = await readFile(filepath, 'utf-8');
        results.push(JSON.parse(content) as SuiteResult);
      }

      // Sort by start time descending (newest first)
      return results.sort((a, b) => b.startTime - a.startTime);
    } catch {
      return [];
    }
  }

  /**
   * List all available results.
   */
  async listAll(): Promise<Array<{ suiteId: string; runId: string; timestamp: number; passRate: number }>> {
    try {
      const files = await readdir(this.outputDir);
      const jsonFiles = files.filter(f => f.endsWith('.json'));

      const results: Array<{ suiteId: string; runId: string; timestamp: number; passRate: number }> = [];

      for (const file of jsonFiles) {
        const filepath = join(this.outputDir, file);
        const content = await readFile(filepath, 'utf-8');
        const data = JSON.parse(content) as SuiteResult;

        results.push({
          suiteId: data.suiteId,
          runId: data.runId,
          timestamp: data.startTime,
          passRate: data.metrics.passAt1,
        });
      }

      return results.sort((a, b) => b.timestamp - a.timestamp);
    } catch {
      return [];
    }
  }

  /**
   * Compare two benchmark runs.
   */
  compare(baseline: SuiteResult, comparison: SuiteResult): RunComparison {
    // Calculate differences
    const diff = {
      passAt1: comparison.metrics.passAt1 - baseline.metrics.passAt1,
      avgIterations: comparison.metrics.avgIterations - baseline.metrics.avgIterations,
      avgTokens: comparison.metrics.avgTokens - baseline.metrics.avgTokens,
      avgCost: comparison.metrics.avgCost - baseline.metrics.avgCost,
      totalCost: comparison.metrics.totalCost - baseline.metrics.totalCost,
    };

    // Calculate percentage changes
    const percentChange = {
      passAt1: baseline.metrics.passAt1 > 0
        ? (diff.passAt1 / baseline.metrics.passAt1) * 100
        : 0,
      avgIterations: baseline.metrics.avgIterations > 0
        ? (diff.avgIterations / baseline.metrics.avgIterations) * 100
        : 0,
      avgTokens: baseline.metrics.avgTokens > 0
        ? (diff.avgTokens / baseline.metrics.avgTokens) * 100
        : 0,
      avgCost: baseline.metrics.avgCost > 0
        ? (diff.avgCost / baseline.metrics.avgCost) * 100
        : 0,
    };

    // Find regressions and improvements
    const regressions: RunComparison['regressions'] = [];
    const improvements: RunComparison['improvements'] = [];

    // Create map of baseline results
    const baselineResults = new Map<string, TaskResult>();
    for (const result of baseline.taskResults) {
      baselineResults.set(result.taskId, result);
    }

    // Compare each task
    for (const compResult of comparison.taskResults) {
      const baseResult = baselineResults.get(compResult.taskId);
      if (!baseResult) continue;

      if (baseResult.passed && !compResult.passed) {
        regressions.push({
          taskId: compResult.taskId,
          baselinePassed: true,
          comparisonPassed: false,
          message: `Regression: Task ${compResult.taskId} now failing`,
        });
      } else if (!baseResult.passed && compResult.passed) {
        improvements.push({
          taskId: compResult.taskId,
          baselinePassed: false,
          comparisonPassed: true,
          message: `Improvement: Task ${compResult.taskId} now passing`,
        });
      }
    }

    return {
      baselineRunId: baseline.runId,
      comparisonRunId: comparison.runId,
      baseline: baseline.metrics,
      comparison: comparison.metrics,
      diff,
      percentChange,
      regressions,
      improvements,
    };
  }

  /**
   * Format comparison as text report.
   */
  formatComparison(comparison: RunComparison): string {
    const lines: string[] = [];

    lines.push('═══════════════════════════════════════════════════════════');
    lines.push('                    BENCHMARK COMPARISON');
    lines.push('═══════════════════════════════════════════════════════════');
    lines.push('');
    lines.push(`Baseline:    ${comparison.baselineRunId}`);
    lines.push(`Comparison:  ${comparison.comparisonRunId}`);
    lines.push('');

    // Metrics comparison
    lines.push('─── Metrics ──────────────────────────────────────────────');
    lines.push('');
    lines.push(this.formatMetricRow('Pass@1', comparison.baseline.passAt1, comparison.comparison.passAt1, comparison.diff.passAt1, comparison.percentChange.passAt1, true));
    lines.push(this.formatMetricRow('Avg Iterations', comparison.baseline.avgIterations, comparison.comparison.avgIterations, comparison.diff.avgIterations, comparison.percentChange.avgIterations, false));
    lines.push(this.formatMetricRow('Avg Tokens', comparison.baseline.avgTokens, comparison.comparison.avgTokens, comparison.diff.avgTokens, comparison.percentChange.avgTokens, false));
    lines.push(this.formatMetricRow('Avg Cost ($)', comparison.baseline.avgCost, comparison.comparison.avgCost, comparison.diff.avgCost, comparison.percentChange.avgCost, false));
    lines.push(this.formatMetricRow('Total Cost ($)', comparison.baseline.totalCost, comparison.comparison.totalCost, comparison.diff.totalCost, 0, false));
    lines.push('');

    // Regressions
    if (comparison.regressions.length > 0) {
      lines.push('─── Regressions ──────────────────────────────────────────');
      lines.push('');
      for (const reg of comparison.regressions) {
        lines.push(`  ✗ ${reg.message}`);
      }
      lines.push('');
    }

    // Improvements
    if (comparison.improvements.length > 0) {
      lines.push('─── Improvements ─────────────────────────────────────────');
      lines.push('');
      for (const imp of comparison.improvements) {
        lines.push(`  ✓ ${imp.message}`);
      }
      lines.push('');
    }

    // Summary
    lines.push('─── Summary ──────────────────────────────────────────────');
    lines.push('');

    const netChange = comparison.improvements.length - comparison.regressions.length;
    if (netChange > 0) {
      lines.push(`  Net improvement: +${netChange} tasks`);
    } else if (netChange < 0) {
      lines.push(`  Net regression: ${netChange} tasks`);
    } else {
      lines.push('  No net change in pass/fail status');
    }

    if (comparison.diff.passAt1 > 0) {
      lines.push(`  Pass@1 improved by ${(comparison.diff.passAt1 * 100).toFixed(1)}%`);
    } else if (comparison.diff.passAt1 < 0) {
      lines.push(`  Pass@1 declined by ${(Math.abs(comparison.diff.passAt1) * 100).toFixed(1)}%`);
    }

    lines.push('');
    lines.push('═══════════════════════════════════════════════════════════');

    return lines.join('\n');
  }

  /**
   * Format a metric row.
   */
  private formatMetricRow(
    name: string,
    baseline: number,
    comparison: number,
    diff: number,
    percentChange: number,
    isPercentage: boolean
  ): string {
    const formatValue = (v: number) => {
      if (isPercentage) return `${(v * 100).toFixed(1)}%`;
      if (v < 1) return v.toFixed(4);
      if (v < 100) return v.toFixed(2);
      return v.toFixed(0);
    };

    const formatDiff = (d: number) => {
      const sign = d >= 0 ? '+' : '';
      if (isPercentage) return `${sign}${(d * 100).toFixed(1)}%`;
      if (Math.abs(d) < 1) return `${sign}${d.toFixed(4)}`;
      return `${sign}${d.toFixed(2)}`;
    };

    const changeIndicator = diff > 0 ? '↑' : diff < 0 ? '↓' : '→';

    return `  ${name.padEnd(16)} ${formatValue(baseline).padStart(12)} → ${formatValue(comparison).padStart(12)}  ${changeIndicator} ${formatDiff(diff).padStart(10)}`;
  }

  /**
   * Get the latest result for a suite.
   */
  async getLatest(suiteId: string): Promise<SuiteResult | null> {
    const results = await this.loadAllForSuite(suiteId);
    return results[0] ?? null;
  }

  /**
   * Delete a result.
   */
  async delete(runId: string): Promise<boolean> {
    try {
      const files = await readdir(this.outputDir);
      const matchingFile = files.find(f => f.includes(runId) && f.endsWith('.json'));

      if (matchingFile) {
        const { unlink } = await import('fs/promises');
        await unlink(join(this.outputDir, matchingFile));
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }

  /**
   * Generate a summary report for all runs of a suite.
   */
  async generateSummaryReport(suiteId: string): Promise<string> {
    const results = await this.loadAllForSuite(suiteId);
    if (results.length === 0) {
      return `No results found for suite: ${suiteId}`;
    }

    const lines: string[] = [];

    lines.push(`Suite: ${suiteId}`);
    lines.push(`Total runs: ${results.length}`);
    lines.push('');
    lines.push('Run History:');
    lines.push('─'.repeat(80));
    lines.push(`${'Date'.padEnd(24)} ${'Model'.padEnd(20)} ${'Pass@1'.padStart(8)} ${'Cost'.padStart(10)} ${'Duration'.padStart(10)}`);
    lines.push('─'.repeat(80));

    for (const result of results) {
      const date = new Date(result.startTime).toISOString().split('T')[0];
      const time = new Date(result.startTime).toISOString().split('T')[1].slice(0, 8);
      const passRate = `${(result.metrics.passAt1 * 100).toFixed(1)}%`;
      const cost = `$${result.metrics.totalCost.toFixed(4)}`;
      const duration = `${(result.durationMs / 1000).toFixed(1)}s`;

      lines.push(`${date} ${time}  ${result.model.padEnd(20)} ${passRate.padStart(8)} ${cost.padStart(10)} ${duration.padStart(10)}`);
    }

    // Statistics
    const passRates = results.map(r => r.metrics.passAt1);
    const avgPassRate = passRates.reduce((a, b) => a + b, 0) / passRates.length;
    const maxPassRate = Math.max(...passRates);
    const minPassRate = Math.min(...passRates);

    lines.push('─'.repeat(80));
    lines.push('');
    lines.push('Statistics:');
    lines.push(`  Average Pass@1: ${(avgPassRate * 100).toFixed(1)}%`);
    lines.push(`  Best Pass@1:    ${(maxPassRate * 100).toFixed(1)}%`);
    lines.push(`  Worst Pass@1:   ${(minPassRate * 100).toFixed(1)}%`);

    return lines.join('\n');
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a result store.
 */
export function createResultStore(outputDir?: string): ResultStore {
  return new ResultStore(outputDir);
}
