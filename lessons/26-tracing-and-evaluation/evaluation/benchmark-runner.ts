/**
 * Lesson 26: Benchmark Runner
 *
 * Executes benchmark tasks in isolated sandboxes and validates outcomes.
 * Supports sequential and parallel execution with timeout handling.
 *
 * @example
 * ```typescript
 * import { BenchmarkRunner } from './benchmark-runner.js';
 * import { simpleCodingSuite } from './benchmarks/simple-coding.js';
 *
 * const runner = new BenchmarkRunner({
 *   model: 'claude-3-sonnet',
 *   maxIterations: 10,
 *   timeout: 60000,
 * });
 *
 * const result = await runner.runSuite(simpleCodingSuite);
 * console.log(`Pass@1: ${result.metrics.passAt1}`);
 * ```
 */

import { mkdir, writeFile, readFile, rm, access, readdir } from 'fs/promises';
import { join, relative } from 'path';
import { tmpdir } from 'os';
import { randomUUID } from 'crypto';
import { execFile as execFileCb } from 'child_process';
import { promisify } from 'util';

import type {
  BenchmarkTask,
  BenchmarkSuite,
  BenchmarkSandbox,
  BenchmarkRunnerConfig,
  TaskResult,
  SuiteResult,
  ValidationResult,
} from '../types.js';
import { createTraceCollector, TraceCollector } from '../trace-collector.js';

const execFileAsync = promisify(execFileCb);

// =============================================================================
// SANDBOX IMPLEMENTATION
// =============================================================================

/**
 * Create an isolated sandbox for task execution.
 */
async function createSandbox(taskId: string): Promise<BenchmarkSandbox> {
  const sandboxPath = join(tmpdir(), `benchmark-${taskId}-${Date.now()}`);
  await mkdir(sandboxPath, { recursive: true });

  return {
    path: sandboxPath,

    async readFile(relativePath: string): Promise<string> {
      const fullPath = join(sandboxPath, relativePath);
      return readFile(fullPath, 'utf-8');
    },

    async exists(relativePath: string): Promise<boolean> {
      const fullPath = join(sandboxPath, relativePath);
      try {
        await access(fullPath);
        return true;
      } catch {
        return false;
      }
    },

    async run(command: string, args: string[], options?: { timeout?: number }): Promise<{ stdout: string; stderr: string; exitCode: number }> {
      try {
        const { stdout, stderr } = await execFileAsync(command, args, {
          cwd: sandboxPath,
          timeout: options?.timeout ?? 30000,
          maxBuffer: 10 * 1024 * 1024, // 10MB
        });
        return { stdout, stderr, exitCode: 0 };
      } catch (err) {
        const execError = err as { stdout?: string; stderr?: string; code?: number };
        return {
          stdout: execError.stdout ?? '',
          stderr: execError.stderr ?? (err instanceof Error ? err.message : String(err)),
          exitCode: execError.code ?? 1,
        };
      }
    },

    async glob(pattern: string): Promise<string[]> {
      // Simple glob implementation using recursive readdir
      const files = await readdir(sandboxPath, { recursive: true, withFileTypes: true });
      const allFiles = files
        .filter(f => f.isFile())
        .map(f => {
          // Handle nested paths
          const parentPath = f.parentPath || f.path || '';
          const relativePath = parentPath.startsWith(sandboxPath)
            ? relative(sandboxPath, parentPath)
            : parentPath;
          return relativePath ? join(relativePath, f.name) : f.name;
        });

      // Convert glob pattern to regex
      const regexPattern = pattern
        .replace(/\*\*/g, '<<<GLOBSTAR>>>')
        .replace(/\*/g, '[^/]*')
        .replace(/\?/g, '.')
        .replace(/<<<GLOBSTAR>>>/g, '.*');
      const regex = new RegExp(`^${regexPattern}$`);

      return allFiles.filter(f => regex.test(f));
    },

    async cleanup(): Promise<void> {
      try {
        await rm(sandboxPath, { recursive: true, force: true });
      } catch {
        // Ignore cleanup errors
      }
    },
  };
}

/**
 * Setup sandbox with files and run setup commands.
 */
async function setupSandbox(
  sandbox: BenchmarkSandbox,
  files?: Record<string, string>,
  commands?: Array<{ command: string; args: string[] }>
): Promise<void> {
  // Write setup files
  if (files) {
    for (const [relativePath, content] of Object.entries(files)) {
      const fullPath = join(sandbox.path, relativePath);
      const dir = join(fullPath, '..');
      await mkdir(dir, { recursive: true });
      await writeFile(fullPath, content);
    }
  }

  // Run setup commands
  if (commands) {
    for (const cmd of commands) {
      const result = await sandbox.run(cmd.command, cmd.args, { timeout: 60000 });
      if (result.exitCode !== 0) {
        throw new Error(`Setup command failed: ${cmd.command} ${cmd.args.join(' ')}\n${result.stderr}`);
      }
    }
  }
}

// =============================================================================
// OUTCOME VALIDATORS
// =============================================================================

/**
 * Validate task outcome based on expected outcome type.
 */
async function validateOutcome(
  sandbox: BenchmarkSandbox,
  outcome: BenchmarkTask['expectedOutcome']
): Promise<ValidationResult> {
  switch (outcome.type) {
    case 'test_pass':
      return validateTestPass(sandbox, outcome);

    case 'file_match':
      return validateFileMatch(sandbox, outcome);

    case 'file_contains':
      return validateFileContains(sandbox, outcome);

    case 'file_not_contains':
      return validateFileNotContains(sandbox, outcome);

    case 'custom':
      return outcome.validator(sandbox);

    default:
      return { passed: false, score: 0, message: 'Unknown outcome type' };
  }
}

/**
 * Validate test pass outcome.
 */
async function validateTestPass(
  sandbox: BenchmarkSandbox,
  outcome: Extract<BenchmarkTask['expectedOutcome'], { type: 'test_pass' }>
): Promise<ValidationResult> {
  const args = outcome.testArgs ?? [];
  if (outcome.testFile) {
    args.push(outcome.testFile);
  }

  const result = await sandbox.run(outcome.testCommand, args, { timeout: 60000 });

  if (result.exitCode === 0) {
    return {
      passed: true,
      score: 1.0,
      message: 'All tests passed',
      details: result.stdout,
    };
  }

  return {
    passed: false,
    score: 0,
    message: `Tests failed with exit code ${result.exitCode}`,
    details: `stdout:\n${result.stdout}\n\nstderr:\n${result.stderr}`,
  };
}

/**
 * Validate file match outcome.
 */
async function validateFileMatch(
  sandbox: BenchmarkSandbox,
  outcome: Extract<BenchmarkTask['expectedOutcome'], { type: 'file_match' }>
): Promise<ValidationResult> {
  try {
    const content = await sandbox.readFile(outcome.filePath);
    const pattern = typeof outcome.pattern === 'string'
      ? new RegExp(outcome.pattern)
      : outcome.pattern;

    if (pattern.test(content)) {
      return {
        passed: true,
        score: 1.0,
        message: `File ${outcome.filePath} matches pattern`,
      };
    }

    return {
      passed: false,
      score: 0,
      message: `File ${outcome.filePath} does not match pattern`,
      details: `Expected pattern: ${pattern}\nActual content:\n${content.slice(0, 500)}`,
    };
  } catch (err) {
    return {
      passed: false,
      score: 0,
      message: `Could not read file: ${outcome.filePath}`,
      details: err instanceof Error ? err.message : String(err),
    };
  }
}

/**
 * Validate file contains outcome.
 */
async function validateFileContains(
  sandbox: BenchmarkSandbox,
  outcome: Extract<BenchmarkTask['expectedOutcome'], { type: 'file_contains' }>
): Promise<ValidationResult> {
  try {
    const content = await sandbox.readFile(outcome.filePath);
    const missing: string[] = [];

    for (const expected of outcome.content) {
      if (!content.includes(expected)) {
        missing.push(expected);
      }
    }

    if (missing.length === 0) {
      return {
        passed: true,
        score: 1.0,
        message: `File ${outcome.filePath} contains all expected content`,
      };
    }

    const score = (outcome.content.length - missing.length) / outcome.content.length;
    return {
      passed: false,
      score,
      message: `File ${outcome.filePath} missing ${missing.length} expected items`,
      details: `Missing:\n${missing.join('\n')}`,
    };
  } catch (err) {
    return {
      passed: false,
      score: 0,
      message: `Could not read file: ${outcome.filePath}`,
      details: err instanceof Error ? err.message : String(err),
    };
  }
}

/**
 * Validate file not contains outcome.
 */
async function validateFileNotContains(
  sandbox: BenchmarkSandbox,
  outcome: Extract<BenchmarkTask['expectedOutcome'], { type: 'file_not_contains' }>
): Promise<ValidationResult> {
  try {
    const content = await sandbox.readFile(outcome.filePath);
    const found: string[] = [];

    for (const unexpected of outcome.content) {
      if (content.includes(unexpected)) {
        found.push(unexpected);
      }
    }

    if (found.length === 0) {
      return {
        passed: true,
        score: 1.0,
        message: `File ${outcome.filePath} correctly excludes all items`,
      };
    }

    const score = (outcome.content.length - found.length) / outcome.content.length;
    return {
      passed: false,
      score,
      message: `File ${outcome.filePath} contains ${found.length} unexpected items`,
      details: `Found:\n${found.join('\n')}`,
    };
  } catch (err) {
    return {
      passed: false,
      score: 0,
      message: `Could not read file: ${outcome.filePath}`,
      details: err instanceof Error ? err.message : String(err),
    };
  }
}

// =============================================================================
// BENCHMARK RUNNER
// =============================================================================

/**
 * Default benchmark configuration.
 */
const DEFAULT_CONFIG: BenchmarkRunnerConfig = {
  model: 'claude-3-sonnet',
  maxIterations: 10,
  timeout: 120000,
  parallel: false,
  maxParallel: 4,
  enableTracing: true,
  outputDir: '.eval-results',
  retryFailed: false,
  maxRetries: 1,
};

/**
 * Runs benchmark tasks and collects results.
 */
export class BenchmarkRunner {
  private config: BenchmarkRunnerConfig;
  private traceCollector: TraceCollector | null = null;

  constructor(config: Partial<BenchmarkRunnerConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };

    if (this.config.enableTracing) {
      this.traceCollector = createTraceCollector({
        outputDir: this.config.outputDir,
      });
    }
  }

  /**
   * Run a single benchmark task.
   */
  async runTask(
    task: BenchmarkTask,
    runId: string,
    agentRunner: (prompt: string, sandbox: BenchmarkSandbox) => Promise<{ success: boolean; iterations: number; tokens: number; cost: number }>
  ): Promise<TaskResult> {
    const startTime = Date.now();
    let sandbox: BenchmarkSandbox | null = null;

    try {
      // Create sandbox
      sandbox = await createSandbox(task.id);

      // Setup sandbox with task files
      await setupSandbox(sandbox, task.setupFiles, task.setupCommands);

      // Build prompt with sandbox context
      const prompt = this.buildTaskPrompt(task, sandbox.path);

      // Run agent with timeout
      const timeoutMs = task.timeout ?? this.config.timeout;
      const agentResult = await Promise.race([
        agentRunner(prompt, sandbox),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('Task timeout')), timeoutMs)
        ),
      ]);

      // Validate outcome
      const validation = await validateOutcome(sandbox, task.expectedOutcome);

      const durationMs = Date.now() - startTime;

      return {
        taskId: task.id,
        runId,
        passed: validation.passed,
        score: validation.score,
        iterations: agentResult.iterations,
        totalTokens: agentResult.tokens,
        cost: agentResult.cost,
        durationMs,
        validation,
        timestamp: Date.now(),
      };
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      const durationMs = Date.now() - startTime;

      return {
        taskId: task.id,
        runId,
        passed: false,
        score: 0,
        iterations: 0,
        totalTokens: 0,
        cost: 0,
        durationMs,
        validation: {
          passed: false,
          score: 0,
          message: `Task error: ${error.message}`,
        },
        error: error.message,
        timestamp: Date.now(),
      };
    } finally {
      // Cleanup sandbox
      if (sandbox) {
        await sandbox.cleanup();
      }
    }
  }

  /**
   * Run a benchmark suite.
   */
  async runSuite(
    suite: BenchmarkSuite,
    agentRunner: (prompt: string, sandbox: BenchmarkSandbox) => Promise<{ success: boolean; iterations: number; tokens: number; cost: number }>
  ): Promise<SuiteResult> {
    const runId = randomUUID();
    const startTime = Date.now();

    // Suite-level setup (shared across tasks)
    // Note: Each task still gets its own sandbox, but we can copy shared files

    const taskResults: TaskResult[] = [];

    if (this.config.parallel && suite.tasks.length > 1) {
      // Parallel execution
      const chunks = this.chunkArray(suite.tasks, this.config.maxParallel);

      for (const chunk of chunks) {
        const results = await Promise.all(
          chunk.map(task => this.runTask(task, runId, agentRunner))
        );
        taskResults.push(...results);
      }
    } else {
      // Sequential execution
      for (const task of suite.tasks) {
        const result = await this.runTask(task, runId, agentRunner);
        taskResults.push(result);

        // Retry failed tasks if configured
        if (!result.passed && this.config.retryFailed) {
          for (let retry = 0; retry < this.config.maxRetries; retry++) {
            const retryResult = await this.runTask(task, runId, agentRunner);
            if (retryResult.passed) {
              taskResults[taskResults.length - 1] = retryResult;
              break;
            }
          }
        }
      }
    }

    const endTime = Date.now();

    // Calculate metrics
    const metrics = this.calculateMetrics(taskResults, suite.tasks);

    return {
      suiteId: suite.id,
      runId,
      model: this.config.model,
      startTime,
      endTime,
      durationMs: endTime - startTime,
      taskResults,
      metrics,
      config: {
        model: this.config.model,
        maxIterations: this.config.maxIterations,
        timeout: this.config.timeout,
        parallel: this.config.parallel,
      },
    };
  }

  /**
   * Build the prompt for a task.
   */
  private buildTaskPrompt(task: BenchmarkTask, sandboxPath: string): string {
    let prompt = task.prompt;

    // Add sandbox context
    prompt += `\n\nWorking directory: ${sandboxPath}`;

    if (task.setupFiles) {
      const files = Object.keys(task.setupFiles);
      prompt += `\n\nExisting files: ${files.join(', ')}`;
    }

    return prompt;
  }

  /**
   * Calculate aggregated metrics.
   */
  private calculateMetrics(
    results: TaskResult[],
    tasks: BenchmarkTask[]
  ): SuiteResult['metrics'] {
    const passed = results.filter(r => r.passed);
    const totalTasks = results.length;

    // Category breakdown
    const byCategory: Record<string, { passed: number; total: number; passRate: number }> = {};
    for (const task of tasks) {
      if (!byCategory[task.category]) {
        byCategory[task.category] = { passed: 0, total: 0, passRate: 0 };
      }
      byCategory[task.category].total++;
    }
    for (const result of results) {
      const task = tasks.find(t => t.id === result.taskId);
      if (task && result.passed) {
        byCategory[task.category].passed++;
      }
    }
    for (const cat of Object.keys(byCategory)) {
      byCategory[cat].passRate = byCategory[cat].passed / byCategory[cat].total;
    }

    // Difficulty breakdown
    const byDifficulty: Record<string, { passed: number; total: number; passRate: number }> = {};
    for (const task of tasks) {
      if (!byDifficulty[task.difficulty]) {
        byDifficulty[task.difficulty] = { passed: 0, total: 0, passRate: 0 };
      }
      byDifficulty[task.difficulty].total++;
    }
    for (const result of results) {
      const task = tasks.find(t => t.id === result.taskId);
      if (task && result.passed) {
        byDifficulty[task.difficulty].passed++;
      }
    }
    for (const diff of Object.keys(byDifficulty)) {
      byDifficulty[diff].passRate = byDifficulty[diff].passed / byDifficulty[diff].total;
    }

    // Aggregate values
    const totalIterations = results.reduce((sum, r) => sum + r.iterations, 0);
    const totalTokens = results.reduce((sum, r) => sum + r.totalTokens, 0);
    const totalCost = results.reduce((sum, r) => sum + r.cost, 0);

    return {
      passAt1: passed.length / totalTasks,
      totalTasks,
      passedTasks: passed.length,
      failedTasks: totalTasks - passed.length,
      avgIterations: totalIterations / totalTasks,
      avgTokens: totalTokens / totalTasks,
      avgCost: totalCost / totalTasks,
      totalCost,
      byCategory,
      byDifficulty,
    };
  }

  /**
   * Chunk array for parallel processing.
   */
  private chunkArray<T>(array: T[], size: number): T[][] {
    const chunks: T[][] = [];
    for (let i = 0; i < array.length; i += size) {
      chunks.push(array.slice(i, i + size));
    }
    return chunks;
  }

  /**
   * Get configuration.
   */
  getConfig(): BenchmarkRunnerConfig {
    return { ...this.config };
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a benchmark runner.
 */
export function createBenchmarkRunner(
  config?: Partial<BenchmarkRunnerConfig>
): BenchmarkRunner {
  return new BenchmarkRunner(config);
}
