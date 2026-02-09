#!/usr/bin/env npx tsx
/**
 * Evaluation Framework CLI
 *
 * Main entry point for running evaluations.
 *
 * Usage:
 *   npm run eval -- run --dataset golden --model claude-3-5-sonnet
 *   npm run eval -- compare results/run-a.json results/run-b.json
 *   npm run eval -- list --dataset golden
 */

import type { EvalRunConfig, EvalResult, EvalSummary } from './types.js';
import type { IsolationType } from './isolation/types.js';
import { loadDataset, filterTasks } from './lib/dataset-loader.js';
import { ProductionAgentRunner } from './runners/agent-runner.js';
import { BatchOrchestrator } from './runners/batch-orchestrator.js';
import { runSWEBenchEvaluation } from './adapters/swe-bench.js';
import * as fs from 'fs/promises';
import * as path from 'path';
import { existsSync } from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '../../..'); // tools/eval/src -> project root

// =============================================================================
// CLI PARSING
// =============================================================================

interface CLIArgs {
  command: 'run' | 'compare' | 'list' | 'grade' | 'help';
  dataset?: string;
  model?: string;
  provider?: 'anthropic' | 'openrouter' | 'openai';
  trace?: boolean;
  mockLlm?: boolean;
  costLimit?: number;
  parallelism?: number;
  isolation?: IsolationType;
  difficulty?: string[];
  category?: string[];
  tags?: string[];
  taskIds?: string[];
  outputDir?: string;
  files?: string[];
  /** --harness flag: run official SWE-bench harness after eval */
  harness?: boolean;
  /** --predictions: path to predictions.jsonl for grade command */
  predictions?: string;
  /** --max-workers: parallel workers for SWE-bench harness */
  maxWorkers?: number;
  /** --timeout: timeout per instance for SWE-bench harness (seconds) */
  harnessTimeout?: number;
  /** --run-id: run ID for SWE-bench harness output grouping */
  runId?: string;
}

function parseArgs(argv: string[]): CLIArgs {
  const args: CLIArgs = { command: 'help' };

  // Get command
  const command = argv[2];
  if (command === 'run' || command === 'compare' || command === 'list' || command === 'grade') {
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
      case '--parallelism':
        args.parallelism = parseInt(next, 10);
        i++;
        break;
      case '--isolation':
        args.isolation = next as IsolationType;
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
      case '--harness':
        args.harness = true;
        break;
      case '--predictions':
        args.predictions = next;
        i++;
        break;
      case '--max-workers':
        args.maxWorkers = parseInt(next, 10);
        i++;
        break;
      case '--timeout':
        args.harnessTimeout = parseInt(next, 10);
        i++;
        break;
      case '--run-id':
        args.runId = next;
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
    model: args.model || 'z-ai/glm-4.7',
    provider: args.provider || 'openrouter',
    trace: args.trace,
    mock_llm: args.mockLlm,
    cost_limit: args.costLimit,
    difficulty: args.difficulty as EvalRunConfig['difficulty'],
    category: args.category as EvalRunConfig['category'],
    tags: args.tags,
    task_ids: args.taskIds,
    output_dir: args.outputDir || path.join(projectRoot, 'tools/eval/results'),
  };

  console.log(`
╔══════════════════════════════════════════════════════════════╗
║                    ATTOCODE EVALUATION                      ║
╚══════════════════════════════════════════════════════════════╝
`);

  const parallelism = args.parallelism || 1;
  const isolation = args.isolation || (parallelism > 1 ? 'worktree' : 'none');

  // Load dataset (with isolation-managed flag for worktree/docker modes)
  console.log(`Loading dataset: ${config.dataset}...`);
  const dataset = await loadDataset(config.dataset, {
    isolationManaged: isolation !== 'none',
    projectRoot,
  });
  console.log(`  Loaded ${dataset.tasks.length} tasks from "${dataset.name}" v${dataset.version}`);

  // Filter tasks
  const tasks = filterTasks(dataset.tasks, config);
  console.log(`  Running ${tasks.length} tasks after filtering`);

  if (tasks.length === 0) {
    console.log('\nNo tasks to run after filtering.');
    return;
  }

  let results: EvalResult[];
  let predictionsPath: string | undefined;

  if (parallelism > 1 || isolation !== 'none') {
    // Use BatchOrchestrator for parallel / isolated execution
    console.log(`  Parallelism: ${parallelism} | Isolation: ${isolation}`);

    const orchestrator = new BatchOrchestrator({
      batchConfig: {
        parallelism,
        isolation,
        costLimit: config.cost_limit,
        staggerDelayMs: 500,
        saveIntermediate: true,
      },
      evalConfig: config,
      outputDir: config.output_dir,
      onProgress: (event) => {
        switch (event.type) {
          case 'batch.progress':
            console.log(
              `  Progress: ${event.completed}/${event.total} ` +
              `(${event.passed} passed, ${event.failed} failed, $${event.cost.toFixed(4)})`,
            );
            break;
        }
      },
    });

    results = await orchestrator.run(tasks);
    // BatchOrchestrator creates runners internally; check for predictions
    // The predictions are saved per-runner, we need to find them
    const outputDir = config.output_dir || path.join(projectRoot, 'tools/eval/results');
    const files = await fs.readdir(outputDir);
    const predFiles = files.filter(f => f.startsWith('predictions-') && f.endsWith('.jsonl')).sort().reverse();
    if (predFiles.length > 0) {
      predictionsPath = path.join(outputDir, predFiles[0]);
    }
  } else {
    // Sequential mode (legacy behavior)
    const runner = new ProductionAgentRunner({
      outputDir: config.output_dir,
    });

    results = await runner.runDataset(tasks, config);
    predictionsPath = existsSync(runner.predictionsPath) ? runner.predictionsPath : undefined;
    await runner.cleanup();
  }

  // Calculate and print summary
  const summary = calculateSummary(results);
  printSummary(summary, config);

  // Save results
  const resultPath = await saveResults(results, summary, config);
  console.log(`\nResults saved to: ${resultPath}`);

  if (predictionsPath) {
    console.log(`Predictions saved to: ${predictionsPath}`);
  }

  // Run official SWE-bench harness if --harness flag is set
  if (args.harness && predictionsPath) {
    console.log('\n' + '═'.repeat(60));
    console.log('Running official SWE-bench harness...');
    console.log('═'.repeat(60));

    try {
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const harnessResults = await runSWEBenchEvaluation({
        predictionsPath,
        runId: args.runId || `attocode-${timestamp}`,
        maxWorkers: args.maxWorkers || args.parallelism || 4,
        timeout: args.harnessTimeout || 1800,
      });

      console.log('\n' + '─'.repeat(60));
      console.log('SWE-BENCH HARNESS RESULTS');
      console.log('─'.repeat(60));
      console.log(`  Total instances: ${harnessResults.total}`);
      console.log(`  Resolved:        ${harnessResults.resolved}`);
      console.log(`  Resolution rate:  ${(harnessResults.resolutionRate * 100).toFixed(1)}%`);

      if (harnessResults.results.length > 0) {
        console.log('\n  Per-instance results:');
        for (const r of harnessResults.results) {
          const statusIcon = r.status === 'resolved' ? '✓' : r.status === 'error' ? '!' : '✗';
          console.log(`    ${statusIcon} ${r.instance_id}: ${r.status}`);
        }
      }

      console.log('─'.repeat(60));
    } catch (err) {
      console.error(`\nSWE-bench harness failed: ${err instanceof Error ? err.message : err}`);
      console.error('You can run it manually with:');
      console.error(`  npm run eval -- grade --predictions ${predictionsPath}`);
    }
  } else if (args.harness && !predictionsPath) {
    console.warn('\n--harness flag set but no predictions were generated (no SWE-bench patches found).');
  }
}

async function compareCommand(args: CLIArgs): Promise<void> {
  if (!args.files || args.files.length !== 2) {
    console.error('Error: compare command requires exactly 2 result files');
    console.error('Usage: npm run eval -- compare <baseline.json> <challenger.json>');
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

  const dataset = await loadDataset(args.dataset, { projectRoot });

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

async function gradeCommand(args: CLIArgs): Promise<void> {
  if (!args.predictions) {
    // Try positional arg
    if (args.files && args.files.length > 0) {
      args.predictions = args.files[0];
    } else {
      console.error('Error: --predictions <path.jsonl> is required');
      console.error('Usage: npm run eval -- grade --predictions <predictions.jsonl>');
      process.exit(1);
    }
  }

  if (!existsSync(args.predictions)) {
    console.error(`Error: Predictions file not found: ${args.predictions}`);
    process.exit(1);
  }

  console.log(`
╔══════════════════════════════════════════════════════════════╗
║              SWE-BENCH HARNESS GRADING                      ║
╚══════════════════════════════════════════════════════════════╝
`);

  console.log(`Predictions file: ${args.predictions}`);

  // Count predictions
  const content = await fs.readFile(args.predictions, 'utf-8');
  const lines = content.trim().split('\n').filter(l => l.trim());
  console.log(`Instances to evaluate: ${lines.length}`);

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const runId = args.runId || `attocode-${timestamp}`;

  console.log(`Run ID: ${runId}`);
  console.log(`Max workers: ${args.maxWorkers || 4}`);
  console.log(`Timeout per instance: ${args.harnessTimeout || 1800}s`);
  console.log('');

  const harnessResults = await runSWEBenchEvaluation({
    predictionsPath: args.predictions,
    runId,
    maxWorkers: args.maxWorkers || 4,
    timeout: args.harnessTimeout || 1800,
    outputDir: args.outputDir || './swe-bench-results',
  });

  console.log('\n' + '═'.repeat(60));
  console.log('HARNESS RESULTS');
  console.log('═'.repeat(60));
  console.log(`  Total instances:  ${harnessResults.total}`);
  console.log(`  Resolved:         ${harnessResults.resolved}`);
  console.log(`  Resolution rate:  ${(harnessResults.resolutionRate * 100).toFixed(1)}%`);

  if (harnessResults.results.length > 0) {
    console.log('\n  Per-instance:');
    for (const r of harnessResults.results) {
      const statusIcon = r.status === 'resolved' ? '✓' : r.status === 'error' ? '!' : '✗';
      const color = r.status === 'resolved' ? '\x1b[32m' : '\x1b[31m';
      const reset = '\x1b[0m';
      console.log(`    ${color}${statusIcon}${reset} ${r.instance_id}: ${r.status}`);
      if (r.error_message) {
        console.log(`      Error: ${r.error_message.slice(0, 200)}`);
      }
    }
  }

  console.log('═'.repeat(60));
}

function showHelp(): void {
  console.log(`
╔══════════════════════════════════════════════════════════════╗
║                 ATTOCODE EVALUATION CLI                     ║
╚══════════════════════════════════════════════════════════════╝

USAGE:
  npm run eval -- <command> [options]

COMMANDS:
  run         Run evaluation on a dataset
  grade       Grade predictions using official SWE-bench harness
  compare     Compare two evaluation results
  list        List tasks in a dataset
  help        Show this help message

RUN OPTIONS:
  --dataset, -d <name>       Dataset to evaluate (required)
                             Built-in: golden, smoke, swe-bench-lite
  --model, -m <model>        Model to use (default: z-ai/glm-4.7)
  --provider, -p <provider>  Provider: anthropic, openrouter, openai (default: openrouter)
  --parallelism <n>          Run up to N tasks in parallel (default: 1)
  --isolation <type>         Isolation: worktree, docker, none (default: auto)
                             Auto-selects worktree when parallelism > 1
  --trace                    Enable detailed tracing
  --mock-llm                 Use mock LLM (for testing framework)
  --cost-limit <dollars>     Stop if cost exceeds limit
  --difficulty <levels>      Filter by difficulty (comma-separated: easy,medium,hard,expert)
  --category <cats>          Filter by category (comma-separated)
  --tags <tags>              Filter by tags (comma-separated)
  --task-ids <ids>           Run specific task IDs only (comma-separated)
  --output-dir, -o <dir>     Output directory (default: tools/eval/results)
  --harness                  Run official SWE-bench harness after eval run

GRADE OPTIONS:
  --predictions <path>       Path to predictions.jsonl file (required)
  --max-workers <n>          Parallel workers for harness (default: 4)
  --timeout <seconds>        Timeout per instance (default: 1800)
  --run-id <id>              Run ID for harness output grouping

EXAMPLES:
  # Run golden dataset with default model
  npm run eval -- run --dataset golden

  # Run with specific model and cost limit
  npm run eval -- run -d golden -m claude-3-5-sonnet-20241022 --cost-limit 10

  # Run 10 tasks in parallel with worktree isolation
  npm run eval -- run -d swe-bench-lite --parallelism 10 --isolation worktree

  # Run only easy tasks
  npm run eval -- run -d golden --difficulty easy

  # Test eval framework without LLM costs
  npm run eval -- run -d smoke --mock-llm

  # Run SWE-bench Lite (requires Python + datasets)
  npm run eval -- run -d swe-bench-lite --provider openrouter -m anthropic/claude-3.5-sonnet:beta

  # Run subset of SWE-bench using env vars
  SWE_BENCH_LIMIT=5 npm run eval -- run -d swe-bench-lite

  # Compare two runs
  npm run eval -- compare results/run-a.json results/run-b.json

  # List tasks in a dataset
  npm run eval -- list --dataset golden

  # Grade predictions using official SWE-bench harness
  npm run eval -- grade --predictions results/predictions-2026-01-01.jsonl

  # Run eval + auto-grade with harness
  npm run eval -- run -d swe-bench-lite --harness

SWE-BENCH LITE NOTES:
  Requires: pip install datasets swebench
  Env vars: SWE_BENCH_LIMIT, SWE_BENCH_INSTANCE_IDS
  Grade command requires: pip install swebench (and Docker for harness containers)
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
  const filepath = path.join(config.output_dir || path.join(projectRoot, 'tools/eval/results'), filename);

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
      case 'grade':
        await gradeCommand(args);
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
