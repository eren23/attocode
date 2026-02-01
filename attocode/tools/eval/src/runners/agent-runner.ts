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

  constructor(options: { workdir?: string; outputDir?: string } = {}) {
    this.baseWorkdir = options.workdir || process.cwd();
    this.outputDir = options.outputDir || './tools/eval/results';

    // Use TRACE_OUTPUT_DIR env var for traces (Docker support)
    // Falls back to outputDir for local runs
    this.traceOutputDir = process.env.TRACE_OUTPUT_DIR || this.outputDir;

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
      const { agent, cleanup: cleanupAgent } = await this.createAgent(config, workdir);

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
        metrics,
        trace_path: tracePath,
        timestamp,
      };

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
    workdir: string
  ): Promise<{ agent: ReturnType<typeof createProductionAgent>; cleanup: () => Promise<void> }> {

    // CRITICAL: Change to task workspace directory
    // The agent and all its tools (bash, file operations) must operate in the task's directory
    const originalCwd = process.cwd();
    process.chdir(workdir);
    console.log(`  Working directory: ${workdir}`);

    // Get the provider
    const provider = config.mock_llm
      ? this.createMockProvider()
      : await getProvider(config.provider) as LLMProviderWithTools;

    // Create tool registry with all standard tools
    const registry = createStandardRegistry('yolo'); // Auto-approve for evals
    const tools = convertToolsFromRegistry(registry);

    // Adapt provider
    const adaptedProvider = new ProviderAdapter(provider, config.model);

    // Create the production agent with full capabilities
    const agent = createProductionAgent({
      provider: adaptedProvider,
      tools,
      model: config.model,
      maxIterations: 50,
      humanInLoop: false, // Disable for automated evals

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
      // (eval runs change cwd to task workspace, breaking relative paths)
      learningStore: false,
    });

    return {
      agent,
      cleanup: async () => {
        await agent.cleanup();
        // Restore original working directory
        process.chdir(originalCwd);
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

    console.log(`  ${color}${status}${reset} ${task.name}`);
    console.log(`    Score: ${(result.partial_credit * 100).toFixed(0)}%`);
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
