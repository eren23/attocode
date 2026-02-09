/**
 * Agent Runner - Full ProductionAgent Execution
 *
 * This runner uses the complete attocode ProductionAgent with all tools
 * and capabilities, exactly as used in the TUI. No skeleton or mock.
 */

// Load environment variables first
import * as dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import * as pathUtil from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = pathUtil.dirname(__filename);
const projectRoot = pathUtil.resolve(__dirname, '../../../../');
dotenv.config({ path: pathUtil.join(projectRoot, '.env') });

import { createProductionAgent } from '../../../../src/agent.js';
import { ProviderAdapter, convertToolsFromRegistry } from '../../../../src/adapters.js';
import { createStandardRegistry } from '../../../../src/tools/standard.js';
import { getProvider } from '../../../../src/providers/provider.js';
import { initModelCache } from '../../../../src/integrations/openrouter-pricing.js';

// Import providers to register them (side-effect imports)
import '../../../../src/providers/adapters/anthropic.js';
import '../../../../src/providers/adapters/openrouter.js';
import '../../../../src/providers/adapters/openai.js';
import '../../../../src/providers/adapters/mock.js';
import type { LLMProviderWithTools } from '../../../../src/providers/types.js';

import type {
  EvalTask,
  EvalResult,
  EvalRunConfig,
  EvalRunner,
  EvalMetrics,
  AgentOutput,
} from '../types.js';
import { appendPrediction } from '../adapters/swe-bench.js';

import * as fs from 'fs/promises';
import * as path from 'path';
import { existsSync, mkdirSync } from 'fs';
import { execFileSync } from 'child_process';

// =============================================================================
// AGENT RUNNER IMPLEMENTATION
// =============================================================================

export class ProductionAgentRunner implements EvalRunner {
  private baseWorkdir: string;
  private outputDir: string;
  private traceOutputDir: string;

  /** Path to predictions JSONL file for SWE-bench harness grading */
  public predictionsPath: string;

  constructor(options: { workdir?: string; outputDir?: string } = {}) {
    this.baseWorkdir = options.workdir || projectRoot;
    this.outputDir = options.outputDir || path.join(projectRoot, 'tools/eval/results');

    // Use TRACE_OUTPUT_DIR env var for traces (Docker support)
    // Falls back to outputDir for local runs
    this.traceOutputDir = process.env.TRACE_OUTPUT_DIR || this.outputDir;

    // Predictions file for SWE-bench harness
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    this.predictionsPath = path.join(this.outputDir, `predictions-${timestamp}.jsonl`);

    // Ensure output directories exist
    if (!existsSync(this.outputDir)) {
      mkdirSync(this.outputDir, { recursive: true });
    }
    if (this.traceOutputDir !== this.outputDir && !existsSync(this.traceOutputDir)) {
      mkdirSync(this.traceOutputDir, { recursive: true });
    }
  }

  /**
   * Run a single evaluation task using the full ProductionAgent.
   */
  async runTask(task: EvalTask, config: EvalRunConfig): Promise<EvalResult> {
    const startTime = Date.now();
    const timestamp = new Date().toISOString();

    console.log(`\n${'─'.repeat(60)}`);
    console.log(`Running task: ${task.id} (${task.name})`);
    console.log(`Model: ${config.model} | Provider: ${config.provider}`);
    console.log(`${'─'.repeat(60)}`);

    try {
      // Setup task environment
      const workdir = await this.setupTaskEnvironment(task);

      // Create the agent with full capabilities
      const { agent, cleanup: cleanupAgent } = await this.createAgent(config, workdir, task);

      // Get trace files before run to compare after
      const traceFilesBefore = config.trace
        ? new Set(await this.getTraceFiles())
        : new Set<string>();

      // Run the agent with timeout
      const result = await this.runWithTimeout(
        agent.run(task.prompt),
        task.timeout_ms
      );

      // Find the new trace file created during this run
      let tracePath: string | undefined;
      if (config.trace) {
        const traceFilesAfter = await this.getTraceFiles();
        const newTraceFiles = traceFilesAfter.filter(f => !traceFilesBefore.has(f));
        if (newTraceFiles.length > 0) {
          // Get the most recent trace file
          tracePath = newTraceFiles.sort().reverse()[0];
          console.log(`  Trace saved: ${tracePath}`);
        }
      }

      // Build agent output for grading
      const agentOutput: AgentOutput = {
        success: result.success,
        response: result.response,
        files_modified: [], // TODO: Extract from trace
        files_created: [],
        error: result.error,
      };

      // Import and run grader
      const { grade } = await import('../graders/index.js');
      const gradeResult = await grade(task, agentOutput, workdir);

      // Build metrics
      const metrics: EvalMetrics = {
        tokens: {
          input: result.metrics.inputTokens,
          output: result.metrics.outputTokens,
          total: result.metrics.totalTokens,
        },
        iterations: result.metrics.llmCalls,
        tool_calls: result.metrics.toolCalls,
        duration_ms: Date.now() - startTime,
        estimated_cost: result.metrics.estimatedCost,
      };

      // Cleanup
      await cleanupAgent();
      await this.teardownTaskEnvironment(task, workdir);

      const evalResult: EvalResult = {
        task_id: task.id,
        model: config.model,
        provider: config.provider,
        success: gradeResult.success,
        partial_credit: gradeResult.partial_credit,
        grading_details: gradeResult.details,
        explanation: gradeResult.explanation,
        metrics,
        trace_path: tracePath,
        timestamp,
      };

      // Save SWE-bench prediction for harness grading
      if (task.expected?.swe_bench && gradeResult.swe_bench_patch) {
        try {
          appendPrediction({
            instance_id: task.expected.swe_bench.instance_id,
            model_name_or_path: config.model,
            model_patch: gradeResult.swe_bench_patch,
          }, this.predictionsPath);
          console.log(`  Prediction saved to: ${this.predictionsPath}`);
        } catch (err) {
          console.warn(`  Warning: Failed to save prediction: ${err}`);
        }
      }

      this.printTaskResult(evalResult, task);
      return evalResult;

    } catch (error) {
      const duration_ms = Date.now() - startTime;
      const errorMessage = error instanceof Error ? error.message : String(error);

      console.error(`  ✗ Task failed with error: ${errorMessage}`);

      return {
        task_id: task.id,
        model: config.model,
        provider: config.provider,
        success: false,
        partial_credit: 0,
        metrics: {
          tokens: { input: 0, output: 0, total: 0 },
          iterations: 0,
          tool_calls: 0,
          duration_ms,
          estimated_cost: 0,
        },
        error: errorMessage,
        timestamp,
      };
    }
  }

  /**
   * Run all tasks in a dataset.
   */
  async runDataset(tasks: EvalTask[], config: EvalRunConfig): Promise<EvalResult[]> {
    // Initialize OpenRouter pricing cache for accurate cost estimation
    await initModelCache();

    const results: EvalResult[] = [];
    let totalCost = 0;

    console.log(`\n${'═'.repeat(60)}`);
    console.log(`Starting evaluation run`);
    console.log(`Dataset: ${tasks.length} tasks`);
    console.log(`Model: ${config.model} | Provider: ${config.provider}`);
    if (config.cost_limit) {
      console.log(`Cost limit: $${config.cost_limit.toFixed(2)}`);
    }
    console.log(`${'═'.repeat(60)}`);

    for (let i = 0; i < tasks.length; i++) {
      const task = tasks[i];
      console.log(`\n[${i + 1}/${tasks.length}]`);

      // Check cost limit
      if (config.cost_limit && totalCost >= config.cost_limit) {
        console.log(`\n⚠️  Cost limit reached ($${totalCost.toFixed(4)}). Stopping.`);
        break;
      }

      // Run the task
      const result = await this.runTask(task, config);
      results.push(result);
      totalCost += result.metrics.estimated_cost;

      // Save intermediate results
      await this.saveResults(results, config);
    }

    // Print summary
    this.printRunSummary(results);

    return results;
  }

  /**
   * Create a fully-configured ProductionAgent.
   */
  private async createAgent(
    config: EvalRunConfig,
    workdir: string,
    task?: EvalTask,
  ): Promise<{ agent: ReturnType<typeof createProductionAgent>; cleanup: () => Promise<void> }> {

    console.log(`  Working directory: ${workdir}`);

    // Parse SWE-bench FAIL_TO_PASS tests for verification criteria
    let verificationCriteria: { requiredTests?: string[]; requireFileChanges?: boolean; maxAttempts?: number } | undefined;
    if (task?.expected?.swe_bench?.fail_to_pass) {
      try {
        const rawFTP = task.expected.swe_bench.fail_to_pass;
        const failToPass = Array.isArray(rawFTP)
          ? rawFTP
          : typeof rawFTP === 'string' ? JSON.parse(rawFTP) : [];
        if (Array.isArray(failToPass) && failToPass.length > 0) {
          verificationCriteria = {
            requiredTests: failToPass,
            requireFileChanges: true,
            maxAttempts: 2,
          };
        }
      } catch {
        // Ignore parse errors
      }
    }

    // Get the provider
    const provider = config.mock_llm
      ? this.createMockProvider()
      : await getProvider(config.provider) as LLMProviderWithTools;

    // Create tool registry with basePath so all tools resolve paths against the workspace
    const registry = createStandardRegistry('yolo', { basePath: workdir });
    // Use longer default timeout for eval tasks (300s for pip install, test runs, etc.)
    const tools = convertToolsFromRegistry(registry, { defaultTimeout: 300000 });

    // Adapt provider
    const adaptedProvider = new ProviderAdapter(provider, config.model);

    // Create the production agent with full capabilities
    const agent = createProductionAgent({
      provider: adaptedProvider,
      tools,
      model: config.model,
      maxIterations: 50,
      humanInLoop: false, // Disable for automated evals

      // Set workingDirectory so agent internals know the workspace
      workingDirectory: workdir,

      // Enable observability for traces and metrics
      observability: config.trace ? {
        enabled: true,
        metrics: {
          enabled: true,
          collectTokens: true,
          collectCosts: true,
          collectLatencies: true,
        },
        traceCapture: {
          enabled: true,
          outputDir: this.traceOutputDir,
          captureMessageContent: true,
          captureToolResults: true,
        },
      } : {
        // Always enable metrics for cost tracking, even without trace
        enabled: true,
        metrics: {
          enabled: true,
          collectTokens: true,
          collectCosts: true,
          collectLatencies: true,
        },
      },

      // Enable planning for complex tasks
      planning: {
        enabled: true,
        autoplan: true,
      },

      // Enable reflection for self-correction
      reflection: {
        enabled: true,
        autoReflect: false,
        maxAttempts: 2,
      },

      // Disable sandbox for direct file access (eval runs in isolated env anyway)
      sandbox: false,

      // CRITICAL: Allow all tools without prompting for automated evals
      executionPolicy: {
        enabled: true,
        defaultPolicy: 'allow', // Auto-allow everything
        toolPolicies: {}, // No per-tool overrides
      },

      // Disable features that require filesystem access with relative paths
      learningStore: false,

      // Verification gate: auto-configured from FAIL_TO_PASS tests
      verificationCriteria,
    });

    return {
      agent,
      cleanup: async () => {
        await agent.cleanup();
      },
    };
  }

  /**
   * Create a mock provider for testing the eval framework itself.
   */
  private createMockProvider(): LLMProviderWithTools {
    return {
      name: 'mock',
      chat: async () => ({
        content: 'Mock response for testing',
        usage: { inputTokens: 100, outputTokens: 50, totalTokens: 150 },
      }),
    };
  }

  /**
   * Set up isolated environment for a task.
   */
  private async setupTaskEnvironment(task: EvalTask): Promise<string> {
    const workdir = task.setup?.workdir || this.baseWorkdir;

    if (task.setup?.files) {
      for (const [filePath, content] of Object.entries(task.setup.files)) {
        const fullPath = path.join(workdir, filePath);
        await fs.mkdir(path.dirname(fullPath), { recursive: true });
        await fs.writeFile(fullPath, content);
      }
    }

    if (task.setup?.commands) {
      for (const cmd of task.setup.commands) {
        // Use shell for complex commands with && or pipes
        console.log(`  Running setup: ${cmd.slice(0, 80)}${cmd.length > 80 ? '...' : ''}`);
        execFileSync('sh', ['-c', cmd], { cwd: workdir, stdio: 'inherit' });
      }
    }

    // SWE-bench specific setup: install deps + apply test_patch in sequential runner too
    if (task.expected?.swe_bench) {
      const sweBench = task.expected.swe_bench;

      // Install project dependencies (skip if already done by isolation provider)
      if (existsSync(path.join(workdir, '.deps_installed'))) {
        console.log('  Deps already installed by isolation provider, skipping...');
      } else {
        const hasSetupFile = existsSync(path.join(workdir, 'setup.py'))
          || existsSync(path.join(workdir, 'setup.cfg'))
          || existsSync(path.join(workdir, 'pyproject.toml'));
        if (hasSetupFile) {
          // Pin setuptools<70 — older repos (e.g. astropy) use setuptools.dep_util removed in 70.0
          try {
            execFileSync('pip', ['install', 'setuptools<70', 'wheel', 'Cython', '--quiet'], {
              cwd: workdir,
              timeout: 120000,
              stdio: 'pipe',
            });
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            console.warn(`  Warning: setuptools pre-install failed (non-fatal): ${msg}`);
          }

          // Install build-system.requires from pyproject.toml (needed for --no-build-isolation)
          const hasPyproject = existsSync(path.join(workdir, 'pyproject.toml'));
          if (hasPyproject) {
            try {
              const buildDepsOutput = execFileSync('python3', [
                '-c',
                'import tomllib, json, sys; f=open("pyproject.toml","rb"); d=tomllib.load(f); print("\\n".join(d.get("build-system",{}).get("requires",[])))',
              ], { cwd: workdir, timeout: 10000, stdio: 'pipe' });
              const buildDeps = buildDepsOutput.toString().trim().split('\n').filter(Boolean);
              // Filter out setuptools and wheel — they're already pinned and re-installing
              // them causes pip to crash with TypeError on None version metadata
              const filteredDeps = buildDeps.filter(dep => {
                const name = dep.split(/[><=!~\s\[]/)[0].trim().toLowerCase();
                return name !== 'setuptools' && name !== 'wheel';
              });
              if (filteredDeps.length > 0) {
                console.log(`  Installing ${filteredDeps.length} build deps from pyproject.toml...`);
                execFileSync('pip', ['install', '--ignore-installed', ...filteredDeps, '--quiet'], {
                  cwd: workdir,
                  timeout: 120000,
                  stdio: 'pipe',
                });
              }
            } catch (err) {
              const msg = err instanceof Error ? err.message : String(err);
              console.warn(`  Warning: pyproject.toml build deps install failed (non-fatal): ${msg}`);
            }
          }

          try {
            console.log('  Installing project deps (pip install -e .)...');
            execFileSync('pip', ['install', '-e', '.', '--quiet', '--no-build-isolation'], {
              cwd: workdir,
              timeout: 300000,
              stdio: 'pipe',
              env: { ...process.env, SETUPTOOLS_ENABLE_FEATURES: 'legacy-editable' },
            });
            console.log('  Project deps installed');
          } catch (pipError) {
            const stderr = pipError instanceof Error && 'stderr' in pipError
              ? (pipError as { stderr?: Buffer }).stderr?.toString().slice(-500)
              : '';
            console.warn(`  Warning: Failed to install project deps: ${stderr || '(no details)'}`);
          }
        }
      }

      // Apply test_patch so FAIL_TO_PASS tests exist
      if (sweBench.test_patch) {
        const patchPath = path.join(workdir, '.test_patch.diff');
        try {
          await fs.writeFile(patchPath, sweBench.test_patch);
          try {
            // --3way falls back to 3-way merge when context doesn't match exactly
            execFileSync('git', ['apply', '--3way', patchPath], {
              cwd: workdir,
              timeout: 30000,
              stdio: 'pipe',
            });
          } catch {
            // Fallback: use patch(1) which is more lenient with context
            execFileSync('patch', ['-p1', '--batch', '--fuzz=3', '-i', patchPath], {
              cwd: workdir,
              timeout: 30000,
              stdio: 'pipe',
            });
          }
          console.log('  Test patch applied');
        } catch {
          console.warn('  Warning: Failed to apply test patch (non-fatal)');
        } finally {
          try { await fs.unlink(patchPath); } catch { /* ignore */ }
        }
      }
    }

    return workdir;
  }

  /**
   * Clean up task environment.
   */
  private async teardownTaskEnvironment(task: EvalTask, workdir: string): Promise<void> {
    if (task.teardown?.delete_files) {
      for (const file of task.teardown.delete_files) {
        try {
          await fs.unlink(path.join(workdir, file));
        } catch {
          // File may not exist
        }
      }
    }

    if (task.teardown?.commands) {
      for (const cmd of task.teardown.commands) {
        try {
          execFileSync('sh', ['-c', cmd], { cwd: workdir, stdio: 'inherit' });
        } catch {
          // Command may fail
        }
      }
    }
  }

  /**
   * Run a promise with a timeout.
   */
  private async runWithTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
    return Promise.race([
      promise,
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error(`Task timed out after ${timeoutMs}ms`)), timeoutMs)
      ),
    ]);
  }

  /**
   * Save results to file.
   */
  private async saveResults(results: EvalResult[], config: EvalRunConfig): Promise<void> {
    const filename = `eval-${config.model.replace(/[/:]/g, '-')}-${Date.now()}.json`;
    const filepath = path.join(this.outputDir, filename);
    await fs.writeFile(filepath, JSON.stringify(results, null, 2));
  }

  /**
   * Print task result to console.
   */
  private printTaskResult(result: EvalResult, task: EvalTask): void {
    const status = result.success ? '✓' : '✗';
    const color = result.success ? '\x1b[32m' : '\x1b[31m';
    const reset = '\x1b[0m';

    // Build score label with test details when available
    const score = (result.partial_credit * 100).toFixed(0);
    const tests = result.grading_details?.tests;
    let scoreLabel: string;
    if (tests) {
      scoreLabel = `${score}% (${tests.passed}/${tests.total} tests passing)`;
    } else if (result.partial_credit === 0.5) {
      scoreLabel = `${score}% (patch only, unverified)`;
    } else {
      scoreLabel = `${score}%`;
    }

    console.log(`  ${color}${status}${reset} ${task.name}`);
    console.log(`    Score: ${scoreLabel}`);
    if (result.explanation) {
      console.log(`    Reason: ${result.explanation}`);
    }
    console.log(`    Tokens: ${result.metrics.tokens.total} | Cost: $${result.metrics.estimated_cost.toFixed(4)}`);
    console.log(`    Duration: ${(result.metrics.duration_ms / 1000).toFixed(1)}s | Iterations: ${result.metrics.iterations}`);
  }

  /**
   * Print summary of evaluation run.
   */
  private printRunSummary(results: EvalResult[]): void {
    const passed = results.filter(r => r.success).length;
    const total = results.length;
    const passRate = total > 0 ? (passed / total) * 100 : 0;
    const totalCost = results.reduce((sum, r) => sum + r.metrics.estimated_cost, 0);
    const totalDuration = results.reduce((sum, r) => sum + r.metrics.duration_ms, 0);
    const avgScore = results.reduce((sum, r) => sum + r.partial_credit, 0) / (total || 1);

    console.log(`\n${'═'.repeat(60)}`);
    console.log(`EVALUATION SUMMARY`);
    console.log(`${'═'.repeat(60)}`);
    console.log(`  Pass rate: ${passed}/${total} (${passRate.toFixed(1)}%)`);
    console.log(`  Avg score: ${(avgScore * 100).toFixed(1)}%`);
    console.log(`  Total cost: $${totalCost.toFixed(4)}`);
    console.log(`  Total time: ${(totalDuration / 1000).toFixed(1)}s`);
    console.log(`${'═'.repeat(60)}\n`);
  }

  async cleanup(): Promise<void> {
    // Any global cleanup
  }

  /**
   * Get all trace files in the trace output directory.
   */
  private async getTraceFiles(): Promise<string[]> {
    try {
      const files = await fs.readdir(this.traceOutputDir);
      return files
        .filter(f => f.startsWith('trace-') && f.endsWith('.jsonl'))
        .map(f => path.join(this.traceOutputDir, f));
    } catch {
      return [];
    }
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createRunner(options?: { workdir?: string; outputDir?: string }): EvalRunner {
  return new ProductionAgentRunner(options);
}
