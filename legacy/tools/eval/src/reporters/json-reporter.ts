/**
 * JSON Reporter
 *
 * Outputs evaluation results in JSON format.
 */

import type { EvalResult, EvalSummary, EvalComparison, Reporter } from '../types.js';
import * as fs from 'fs/promises';
import * as path from 'path';

export class JSONReporter implements Reporter {
  private results: EvalResult[] = [];
  private outputPath?: string;

  constructor(options?: { outputPath?: string }) {
    this.outputPath = options?.outputPath;
  }

  reportTask(result: EvalResult): void {
    this.results.push(result);
  }

  reportSummary(results: EvalResult[], summary: EvalSummary): void {
    // Print to console
    console.log(JSON.stringify({ summary, results }, null, 2));
  }

  reportComparison(comparison: EvalComparison): void {
    console.log(JSON.stringify(comparison, null, 2));
  }

  async finalize(): Promise<void> {
    if (this.outputPath) {
      await fs.mkdir(path.dirname(this.outputPath), { recursive: true });
      await fs.writeFile(this.outputPath, JSON.stringify(this.results, null, 2));
    }
  }
}

export class ConsoleReporter implements Reporter {
  reportTask(result: EvalResult): void {
    const status = result.success ? '\x1b[32m✓\x1b[0m' : '\x1b[31m✗\x1b[0m';
    console.log(`${status} ${result.task_id}: ${(result.partial_credit * 100).toFixed(0)}%`);
  }

  reportSummary(results: EvalResult[], summary: EvalSummary): void {
    console.log(`\n${'═'.repeat(50)}`);
    console.log('SUMMARY');
    console.log(`${'═'.repeat(50)}`);
    console.log(`Pass rate: ${summary.passed}/${summary.total_tasks} (${(summary.pass_rate * 100).toFixed(1)}%)`);
    console.log(`Avg score: ${(summary.avg_partial_credit * 100).toFixed(1)}%`);
    console.log(`Total cost: $${summary.total_cost.toFixed(4)}`);
    console.log(`Total time: ${(summary.total_duration_ms / 1000).toFixed(1)}s`);
  }

  reportComparison(comparison: EvalComparison): void {
    const { baseline, challenger } = comparison;

    console.log(`\n${'═'.repeat(50)}`);
    console.log('COMPARISON');
    console.log(`${'═'.repeat(50)}`);
    console.log(`\nBASELINE (${baseline.model}):`);
    console.log(`  Pass rate: ${(baseline.summary.pass_rate * 100).toFixed(1)}%`);
    console.log(`  Cost: $${baseline.summary.total_cost.toFixed(4)}`);

    console.log(`\nCHALLENGER (${challenger.model}):`);
    console.log(`  Pass rate: ${(challenger.summary.pass_rate * 100).toFixed(1)}%`);
    console.log(`  Cost: $${challenger.summary.total_cost.toFixed(4)}`);

    console.log(`\nWINS:`);
    console.log(`  Baseline: ${comparison.comparison.baseline_wins}`);
    console.log(`  Challenger: ${comparison.comparison.challenger_wins}`);
    console.log(`  Ties: ${comparison.comparison.ties}`);
  }

  async finalize(): Promise<void> {
    // Nothing to finalize for console output
  }
}
