#!/usr/bin/env npx tsx
/**
 * Evaluation Framework CLI
 *
 * Main entry point for running evaluations.
 *
 * Usage:
 *   npx tsx tools/eval/src/cli.ts run --dataset golden --model claude-3-5-sonnet
 *   npx tsx tools/eval/src/cli.ts compare results/run-a.json results/run-b.json
 *   npx tsx tools/eval/src/cli.ts list --dataset golden
 */

import type { EvalRunConfig, EvalResult, EvalSummary } from './types.js';
import { loadDataset, filterTasks } from './lib/dataset-loader.js';
import { ProductionAgentRunner } from './runners/agent-runner.js';
import * as fs from 'fs/promises';
import * as path from 'path';

// =============================================================================
// CLI PARSING
// =============================================================================

interface CLIArgs {
  command: 'run' | 'compare' | 'list' | 'help';
  dataset?: string;
  model?: string;
  provider?: 'anthropic' | 'openrouter' | 'openai';
  trace?: boolean;
  mockLlm?: boolean;
  costLimit?: number;
  difficulty?: string[];
  category?: string[];
  tags?: string[];
  taskIds?: string[];
  outputDir?: string;
  files?: string[];
}

function parseArgs(argv: string[]): CLIArgs {
  const args: CLIArgs = { command: 'help' };

  // Get command
  const command = argv[2];
  if (command === 'run' || command === 'compare' || command === 'list') {
    args.command = command;
  }

  // Parse flags
  for (let i = 3; i < argv.length; i++) {
    const arg = argv[i];
    const next = argv[i + 1];

    switch (arg) {
      case '--dataset':
      case '-d':
        args.dataset = next;
        i++;
        break;
      case '--model':
      case '-m':
        args.model = next;
        i++;
        break;
      case '--provider':
      case '-p':
        args.provider = next as 'anthropic' | 'openrouter' | 'openai';
        i++;
        break;
      case '--trace':
        args.trace = true;
        break;
      case '--mock-llm':
        args.mockLlm = true;
        break;
      case '--cost-limit':
        args.costLimit = parseFloat(next);
        i++;
        break;
      case '--difficulty':
        args.difficulty = next.split(',');
        i++;
        break;
      case '--category':
        args.category = next.split(',');
        i++;
        break;
      case '--tags':
        args.tags = next.split(',');
        i++;
        break;
      case '--task-ids':
        args.taskIds = next.split(',');
        i++;
        break;
      case '--output-dir':
      case '-o':
        args.outputDir = next;
        i++;
        break;
      default:
        // Positional args (for compare command)
        if (!arg.startsWith('-')) {
          if (!args.files) args.files = [];
          args.files.push(arg);
        }
    }
  }

  return args;
}

// =============================================================================
// COMMANDS
// =============================================================================

async function runCommand(args: CLIArgs): Promise<void> {
  if (!args.dataset) {
    console.error('Error: --dataset is required');
    process.exit(1);
  }

  const config: EvalRunConfig = {
    dataset: args.dataset,
    model: args.model || 'claude-3-5-sonnet-20241022',
    provider: args.provider || 'anthropic',
    trace: args.trace,
    mock_llm: args.mockLlm,
    cost_limit: args.costLimit,
    difficulty: args.difficulty as EvalRunConfig['difficulty'],
    category: args.category as EvalRunConfig['category'],
    tags: args.tags,
    task_ids: args.taskIds,
    output_dir: args.outputDir || './tools/eval/results',
  };

  console.log(`
╔══════════════════════════════════════════════════════════════╗
║                    ATTOCODE EVALUATION                      ║
╚══════════════════════════════════════════════════════════════╝
`);

  // Load dataset
  console.log(`Loading dataset: ${config.dataset}...`);
  const dataset = await loadDataset(config.dataset);
  console.log(`  Loaded ${dataset.tasks.length} tasks from "${dataset.name}" v${dataset.version}`);

  // Filter tasks
  const tasks = filterTasks(dataset.tasks, config);
  console.log(`  Running ${tasks.length} tasks after filtering`);

  if (tasks.length === 0) {
    console.log('\nNo tasks to run after filtering.');
    return;
  }

  // Create runner
  const runner = new ProductionAgentRunner({
    outputDir: config.output_dir,
  });

  // Run evaluation
  const results = await runner.runDataset(tasks, config);

  // Calculate and print summary
  const summary = calculateSummary(results);
  printSummary(summary, config);

  // Save results
  const resultPath = await saveResults(results, summary, config);
  console.log(`\nResults saved to: ${resultPath}`);

  await runner.cleanup();
}

async function compareCommand(args: CLIArgs): Promise<void> {
  if (!args.files || args.files.length !== 2) {
    console.error('Error: compare command requires exactly 2 result files');
    console.error('Usage: npx tsx cli.ts compare <baseline.json> <challenger.json>');
    process.exit(1);
  }

  const [baselinePath, challengerPath] = args.files;

  console.log(`
╔══════════════════════════════════════════════════════════════╗
║                  EVALUATION COMPARISON                      ║
╚══════════════════════════════════════════════════════════════╝
`);

  // Load results
  const baseline = JSON.parse(await fs.readFile(baselinePath, 'utf-8'));
  const challenger = JSON.parse(await fs.readFile(challengerPath, 'utf-8'));

  // Compare
  const baselineResults: EvalResult[] = baseline.results || baseline;
  const challengerResults: EvalResult[] = challenger.results || challenger;

  const baselineSummary = calculateSummary(baselineResults);
  const challengerSummary = calculateSummary(challengerResults);

  console.log('BASELINE:');
  console.log(`  Model: ${baselineResults[0]?.model || 'unknown'}`);
  console.log(`  Pass rate: ${baselineSummary.passed}/${baselineSummary.total_tasks} (${(baselineSummary.pass_rate * 100).toFixed(1)}%)`);
  console.log(`  Total cost: $${baselineSummary.total_cost.toFixed(4)}`);

  console.log('\nCHALLENGER:');
  console.log(`  Model: ${challengerResults[0]?.model || 'unknown'}`);
  console.log(`  Pass rate: ${challengerSummary.passed}/${challengerSummary.total_tasks} (${(challengerSummary.pass_rate * 100).toFixed(1)}%)`);
  console.log(`  Total cost: $${challengerSummary.total_cost.toFixed(4)}`);

  // Per-task comparison
  console.log('\nPER-TASK COMPARISON:');
  console.log('─'.repeat(60));

  let baselineWins = 0;
  let challengerWins = 0;
  let ties = 0;

  const baselineMap = new Map(baselineResults.map(r => [r.task_id, r]));
  const challengerMap = new Map(challengerResults.map(r => [r.task_id, r]));

  const allTaskIds = new Set([...baselineMap.keys(), ...challengerMap.keys()]);

  for (const taskId of allTaskIds) {
    const b = baselineMap.get(taskId);
    const c = challengerMap.get(taskId);

    if (!b || !c) continue;

    const bScore = b.partial_credit;
    const cScore = c.partial_credit;

    let winner: string;
    if (bScore > cScore) {
      baselineWins++;
      winner = '← Baseline';
    } else if (cScore > bScore) {
      challengerWins++;
      winner = 'Challenger →';
    } else {
      ties++;
      winner = 'Tie';
    }

    console.log(`  ${taskId}: ${(bScore * 100).toFixed(0)}% vs ${(cScore * 100).toFixed(0)}%  ${winner}`);
  }

  console.log('─'.repeat(60));
  console.log(`\nSUMMARY:`);
  console.log(`  Baseline wins: ${baselineWins}`);
  console.log(`  Challenger wins: ${challengerWins}`);
  console.log(`  Ties: ${ties}`);
  console.log(`  Pass rate diff: ${((challengerSummary.pass_rate - baselineSummary.pass_rate) * 100).toFixed(1)}%`);
  console.log(`  Cost diff: $${(challengerSummary.total_cost - baselineSummary.total_cost).toFixed(4)}`);
}

async function listCommand(args: CLIArgs): Promise<void> {
  if (!args.dataset) {
    console.error('Error: --dataset is required');
    process.exit(1);
  }

  const dataset = await loadDataset(args.dataset);

  console.log(`
Dataset: ${dataset.name}
Version: ${dataset.version}
Description: ${dataset.description}
Total tasks: ${dataset.tasks.length}

Tasks:
─────────────────────────────────────────────────────────────────
`);

  for (const task of dataset.tasks) {
    const diff = task.metadata.difficulty.padEnd(6);
    const cat = task.metadata.category.padEnd(12);
    console.log(`  ${task.id.padEnd(25)} [${diff}] [${cat}] ${task.name}`);
  }
}

function showHelp(): void {
  console.log(`
╔══════════════════════════════════════════════════════════════╗
║                 ATTOCODE EVALUATION CLI                     ║
╚══════════════════════════════════════════════════════════════╝

USAGE:
  npx tsx tools/eval/src/cli.ts <command> [options]

COMMANDS:
  run         Run evaluation on a dataset
  compare     Compare two evaluation results
  list        List tasks in a dataset
  help        Show this help message

RUN OPTIONS:
  --dataset, -d <name>       Dataset to evaluate (required)
                             Built-in: golden, smoke, swe-bench-lite
  --model, -m <model>        Model to use (default: claude-3-5-sonnet-20241022)
  --provider, -p <provider>  Provider: anthropic, openrouter, openai (default: anthropic)
  --trace                    Enable detailed tracing
  --mock-llm                 Use mock LLM (for testing framework)
  --cost-limit <dollars>     Stop if cost exceeds limit
  --difficulty <levels>      Filter by difficulty (comma-separated: easy,medium,hard,expert)
  --category <cats>          Filter by category (comma-separated)
  --tags <tags>              Filter by tags (comma-separated)
  --task-ids <ids>           Run specific task IDs only (comma-separated)
  --output-dir, -o <dir>     Output directory (default: ./tools/eval/results)

EXAMPLES:
  # Run golden dataset with default model
  npx tsx tools/eval/src/cli.ts run --dataset golden

  # Run with specific model and cost limit
  npx tsx tools/eval/src/cli.ts run -d golden -m claude-3-5-sonnet-20241022 --cost-limit 10

  # Run only easy tasks
  npx tsx tools/eval/src/cli.ts run -d golden --difficulty easy

  # Test eval framework without LLM costs
  npx tsx tools/eval/src/cli.ts run -d smoke --mock-llm

  # Run SWE-bench Lite (requires Python + datasets)
  npx tsx tools/eval/src/cli.ts run -d swe-bench-lite --provider openrouter -m anthropic/claude-3.5-sonnet:beta

  # Run subset of SWE-bench using env vars
  SWE_BENCH_LIMIT=5 npx tsx tools/eval/src/cli.ts run -d swe-bench-lite

  # Compare two runs
  npx tsx tools/eval/src/cli.ts compare results/run-a.json results/run-b.json

  # List tasks in a dataset
  npx tsx tools/eval/src/cli.ts list --dataset golden

SWE-BENCH LITE NOTES:
  Requires: pip install datasets swebench
  Env vars: SWE_BENCH_LIMIT, SWE_BENCH_INSTANCE_IDS
  Full grading needs the official SWE-bench harness
`);
}

// =============================================================================
// HELPERS
// =============================================================================

function calculateSummary(results: EvalResult[]): EvalSummary {
  const total = results.length;
  const passed = results.filter(r => r.success).length;
  const failed = total - passed;

  const byDifficulty: Record<string, { passed: number; total: number }> = {};
  const byCategory: Record<string, { passed: number; total: number }> = {};

  // We don't have metadata in results, so we can't compute by_difficulty/by_category
  // In a real implementation, we'd store this metadata in the results

  return {
    total_tasks: total,
    passed,
    failed,
    pass_rate: total > 0 ? passed / total : 0,
    avg_partial_credit: results.reduce((sum, r) => sum + r.partial_credit, 0) / (total || 1),
    total_cost: results.reduce((sum, r) => sum + r.metrics.estimated_cost, 0),
    total_duration_ms: results.reduce((sum, r) => sum + r.metrics.duration_ms, 0),
    by_difficulty: byDifficulty,
    by_category: byCategory,
  };
}

function printSummary(summary: EvalSummary, config: EvalRunConfig): void {
  console.log(`
╔══════════════════════════════════════════════════════════════╗
║                      FINAL SUMMARY                          ║
╚══════════════════════════════════════════════════════════════╝

  Model:        ${config.model}
  Provider:     ${config.provider}
  Dataset:      ${config.dataset}

  Pass rate:    ${summary.passed}/${summary.total_tasks} (${(summary.pass_rate * 100).toFixed(1)}%)
  Avg score:    ${(summary.avg_partial_credit * 100).toFixed(1)}%
  Total cost:   $${summary.total_cost.toFixed(4)}
  Total time:   ${(summary.total_duration_ms / 1000).toFixed(1)}s
`);
}

async function saveResults(
  results: EvalResult[],
  summary: EvalSummary,
  config: EvalRunConfig
): Promise<string> {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const modelSlug = config.model.replace(/[/:]/g, '-');
  const filename = `eval-${config.dataset}-${modelSlug}-${timestamp}.json`;
  const filepath = path.join(config.output_dir || './tools/eval/results', filename);

  // Ensure directory exists
  await fs.mkdir(path.dirname(filepath), { recursive: true });

  const output = {
    config,
    summary,
    results,
    timestamp: new Date().toISOString(),
  };

  await fs.writeFile(filepath, JSON.stringify(output, null, 2));
  return filepath;
}

// =============================================================================
// MAIN
// =============================================================================

async function main(): Promise<void> {
  const args = parseArgs(process.argv);

  try {
    switch (args.command) {
      case 'run':
        await runCommand(args);
        break;
      case 'compare':
        await compareCommand(args);
        break;
      case 'list':
        await listCommand(args);
        break;
      case 'help':
      default:
        showHelp();
        break;
    }
  } catch (error) {
    console.error('\nError:', error instanceof Error ? error.message : error);
    process.exit(1);
  }
}

main();
