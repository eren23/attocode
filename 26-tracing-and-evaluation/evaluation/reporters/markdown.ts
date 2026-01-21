/**
 * Lesson 26: Markdown Reporter
 *
 * Generates markdown reports for benchmark results.
 * Suitable for GitHub, documentation, or archival purposes.
 */

import type { SuiteResult, RunComparison } from '../../types.js';

// =============================================================================
// MARKDOWN REPORTER
// =============================================================================

/**
 * Generate markdown reports for benchmark results.
 */
export class MarkdownReporter {
  /**
   * Generate a full suite report.
   */
  generateSuiteReport(result: SuiteResult): string {
    const lines: string[] = [];

    // Header
    lines.push(`# Benchmark Report: ${result.suiteId}`);
    lines.push('');
    lines.push(`**Run ID:** \`${result.runId}\``);
    lines.push(`**Model:** ${result.model}`);
    lines.push(`**Date:** ${new Date(result.startTime).toISOString()}`);
    lines.push(`**Duration:** ${(result.durationMs / 1000).toFixed(1)}s`);
    lines.push('');

    // Summary
    lines.push('## Summary');
    lines.push('');
    lines.push('| Metric | Value |');
    lines.push('|--------|-------|');
    lines.push(`| Pass@1 | ${(result.metrics.passAt1 * 100).toFixed(1)}% |`);
    lines.push(`| Passed Tasks | ${result.metrics.passedTasks}/${result.metrics.totalTasks} |`);
    lines.push(`| Avg Iterations | ${result.metrics.avgIterations.toFixed(1)} |`);
    lines.push(`| Avg Tokens | ${result.metrics.avgTokens.toLocaleString()} |`);
    lines.push(`| Total Cost | $${result.metrics.totalCost.toFixed(4)} |`);
    lines.push('');

    // Task Results
    lines.push('## Task Results');
    lines.push('');
    lines.push('| Task | Status | Iterations | Tokens | Duration |');
    lines.push('|------|--------|------------|--------|----------|');

    for (const task of result.taskResults) {
      const status = task.passed ? '✅' : '❌';
      const duration = `${(task.durationMs / 1000).toFixed(1)}s`;
      lines.push(`| ${task.taskId} | ${status} | ${task.iterations} | ${task.totalTokens.toLocaleString()} | ${duration} |`);
    }
    lines.push('');

    // Category Breakdown
    if (Object.keys(result.metrics.byCategory).length > 1) {
      lines.push('## By Category');
      lines.push('');
      lines.push('| Category | Pass Rate | Passed/Total |');
      lines.push('|----------|-----------|--------------|');

      for (const [cat, data] of Object.entries(result.metrics.byCategory)) {
        lines.push(`| ${cat} | ${(data.passRate * 100).toFixed(0)}% | ${data.passed}/${data.total} |`);
      }
      lines.push('');
    }

    // Difficulty Breakdown
    if (Object.keys(result.metrics.byDifficulty).length > 1) {
      lines.push('## By Difficulty');
      lines.push('');
      lines.push('| Difficulty | Pass Rate | Passed/Total |');
      lines.push('|------------|-----------|--------------|');

      for (const diff of ['easy', 'medium', 'hard']) {
        const data = result.metrics.byDifficulty[diff];
        if (data) {
          lines.push(`| ${diff} | ${(data.passRate * 100).toFixed(0)}% | ${data.passed}/${data.total} |`);
        }
      }
      lines.push('');
    }

    // Failed Tasks Detail
    const failedTasks = result.taskResults.filter(t => !t.passed);
    if (failedTasks.length > 0) {
      lines.push('## Failed Tasks');
      lines.push('');

      for (const task of failedTasks) {
        lines.push(`### ${task.taskId}`);
        lines.push('');
        lines.push(`**Error:** ${task.validation.message}`);
        if (task.validation.details) {
          lines.push('');
          lines.push('```');
          lines.push(task.validation.details.slice(0, 500));
          if (task.validation.details.length > 500) {
            lines.push('...[truncated]');
          }
          lines.push('```');
        }
        lines.push('');
      }
    }

    // Configuration
    lines.push('## Configuration');
    lines.push('');
    lines.push('```json');
    lines.push(JSON.stringify(result.config, null, 2));
    lines.push('```');
    lines.push('');

    return lines.join('\n');
  }

  /**
   * Generate a comparison report.
   */
  generateComparisonReport(comparison: RunComparison): string {
    const lines: string[] = [];

    lines.push('# Benchmark Comparison Report');
    lines.push('');
    lines.push(`**Baseline:** \`${comparison.baselineRunId}\``);
    lines.push(`**Comparison:** \`${comparison.comparisonRunId}\``);
    lines.push('');

    // Metrics Comparison
    lines.push('## Metrics Comparison');
    lines.push('');
    lines.push('| Metric | Baseline | Comparison | Change |');
    lines.push('|--------|----------|------------|--------|');

    const formatPercent = (v: number) => `${(v * 100).toFixed(1)}%`;
    const formatNum = (v: number) => v < 1 ? v.toFixed(4) : v.toFixed(1);
    const formatChange = (d: number, isPercent: boolean) => {
      const sign = d >= 0 ? '+' : '';
      return isPercent ? `${sign}${(d * 100).toFixed(1)}%` : `${sign}${d.toFixed(2)}`;
    };

    lines.push(`| Pass@1 | ${formatPercent(comparison.baseline.passAt1)} | ${formatPercent(comparison.comparison.passAt1)} | ${formatChange(comparison.diff.passAt1, true)} |`);
    lines.push(`| Avg Iterations | ${formatNum(comparison.baseline.avgIterations)} | ${formatNum(comparison.comparison.avgIterations)} | ${formatChange(comparison.diff.avgIterations, false)} |`);
    lines.push(`| Avg Tokens | ${formatNum(comparison.baseline.avgTokens)} | ${formatNum(comparison.comparison.avgTokens)} | ${formatChange(comparison.diff.avgTokens, false)} |`);
    lines.push(`| Total Cost | $${formatNum(comparison.baseline.totalCost)} | $${formatNum(comparison.comparison.totalCost)} | ${formatChange(comparison.diff.totalCost, false)} |`);
    lines.push('');

    // Regressions
    if (comparison.regressions.length > 0) {
      lines.push('## ⚠️ Regressions');
      lines.push('');
      lines.push('Tasks that were passing but are now failing:');
      lines.push('');

      for (const reg of comparison.regressions) {
        lines.push(`- ❌ **${reg.taskId}**`);
      }
      lines.push('');
    }

    // Improvements
    if (comparison.improvements.length > 0) {
      lines.push('## ✅ Improvements');
      lines.push('');
      lines.push('Tasks that were failing but are now passing:');
      lines.push('');

      for (const imp of comparison.improvements) {
        lines.push(`- ✅ **${imp.taskId}**`);
      }
      lines.push('');
    }

    // Summary
    lines.push('## Summary');
    lines.push('');

    const netChange = comparison.improvements.length - comparison.regressions.length;
    if (netChange > 0) {
      lines.push(`**Net Improvement:** +${netChange} tasks`);
    } else if (netChange < 0) {
      lines.push(`**Net Regression:** ${netChange} tasks`);
    } else {
      lines.push('**No net change in task pass/fail status**');
    }

    lines.push('');

    return lines.join('\n');
  }

  /**
   * Generate a short summary suitable for CI/CD.
   */
  generateShortSummary(result: SuiteResult): string {
    const lines: string[] = [];

    const status = result.metrics.passAt1 >= 0.8 ? '✅' : result.metrics.passAt1 >= 0.5 ? '⚠️' : '❌';

    lines.push(`${status} **${result.suiteId}**: ${(result.metrics.passAt1 * 100).toFixed(0)}% Pass@1 (${result.metrics.passedTasks}/${result.metrics.totalTasks})`);
    lines.push(`   Model: ${result.model} | Cost: $${result.metrics.totalCost.toFixed(4)} | Duration: ${(result.durationMs / 1000).toFixed(0)}s`);

    return lines.join('\n');
  }

  /**
   * Generate badge markdown.
   */
  generateBadge(result: SuiteResult): string {
    const passRate = Math.round(result.metrics.passAt1 * 100);
    const color = passRate >= 80 ? 'brightgreen' : passRate >= 50 ? 'yellow' : 'red';
    return `![Pass@1](https://img.shields.io/badge/Pass%401-${passRate}%25-${color})`;
  }
}

/**
 * Create a markdown reporter.
 */
export function createMarkdownReporter(): MarkdownReporter {
  return new MarkdownReporter();
}
