/**
 * Swarm Worker Pool
 *
 * Manages concurrent worker dispatch via existing spawnAgent() infrastructure.
 * Uses slot-based concurrency control and dynamic agent registration.
 */

import type { AgentRegistry, AgentDefinition, SpawnResult } from '../agent-registry.js';
import type { SwarmConfig, SwarmTask, SwarmTaskResult, SwarmWorkerSpec, SwarmWorkerStatus } from './types.js';
import { SUBTASK_TO_CAPABILITY, type WorkerCapability } from './types.js';
import { selectWorkerForCapability } from './model-selector.js';
import type { SwarmBudgetPool } from './swarm-budget.js';
import { buildDelegationPrompt, createMinimalDelegationSpec } from '../delegation-protocol.js';
import { getSubagentQualityPrompt } from '../thinking-strategy.js';
import { getEnvironmentFacts, formatFactsBlock, formatFactsCompact } from '../environment-facts.js';
import { calculateCost, isModelCacheInitialized } from '../openrouter-pricing.js';

// ─── Types ─────────────────────────────────────────────────────────────────

/** Function signature matching ProductionAgent.spawnAgent() */
export type SpawnAgentFn = (agentName: string, task: string) => Promise<SpawnResult>;

/** Active worker tracking */
interface ActiveWorker {
  taskId: string;
  task: SwarmTask;
  workerName: string;
  model: string;
  startedAt: number;
  promise: Promise<{ taskId: string; result: SpawnResult; startedAt: number }>;
}

// ─── Worker Pool ───────────────────────────────────────────────────────────

export class SwarmWorkerPool {
  private config: SwarmConfig;
  private agentRegistry: AgentRegistry;
  private spawnAgent: SpawnAgentFn;
  private budgetPool: SwarmBudgetPool;
  private workers: SwarmWorkerSpec[];

  private activeWorkers: Map<string, ActiveWorker> = new Map();
  private registeredAgentNames: Set<string> = new Set();
  private dispatchCount = 0;

  constructor(
    config: SwarmConfig,
    agentRegistry: AgentRegistry,
    spawnAgent: SpawnAgentFn,
    budgetPool: SwarmBudgetPool,
  ) {
    this.config = config;
    this.agentRegistry = agentRegistry;
    this.spawnAgent = spawnAgent;
    this.budgetPool = budgetPool;
    this.workers = config.workers;
  }

  /**
   * Get number of available slots.
   */
  get availableSlots(): number {
    return Math.max(0, this.config.maxConcurrency - this.activeWorkers.size);
  }

  /**
   * Get number of active workers.
   */
  get activeCount(): number {
    return this.activeWorkers.size;
  }

  /**
   * Select the best worker spec for a task based on capability matching.
   */
  selectWorker(task: SwarmTask): SwarmWorkerSpec | undefined {
    const capability: WorkerCapability = SUBTASK_TO_CAPABILITY[task.type] ?? 'code';
    return selectWorkerForCapability(this.workers, capability, this.dispatchCount++);
  }

  /**
   * Dispatch a task to a worker.
   *
   * 1. Uses pre-selected worker or selects appropriate worker model
   * 2. Registers a dynamic agent definition
   * 3. Calls spawnAgent() to create the worker
   */
  async dispatch(task: SwarmTask, preSelectedWorker?: SwarmWorkerSpec): Promise<void> {
    if (this.availableSlots <= 0) {
      throw new Error('No available worker slots');
    }

    if (!this.budgetPool.hasCapacity()) {
      throw new Error('Budget pool exhausted');
    }

    const worker = preSelectedWorker ?? this.selectWorker(task);
    if (!worker) {
      throw new Error(`No worker available for task type: ${task.type}`);
    }

    // Create a unique agent name for this worker instance
    const agentName = `swarm-${worker.name}-${task.id}`;

    // Register dynamic agent definition
    // V2: toolAccessMode 'all' gives workers all tools (including MCP) by setting tools to undefined.
    // This leverages existing behavior in agent-registry.ts:filterToolsForAgent() which returns
    // all tools when agent.tools is undefined.
    const tools = this.config.toolAccessMode === 'all'
      ? undefined
      : worker.allowedTools;

    const agentDef: AgentDefinition = {
      name: agentName,
      description: `Swarm worker (${worker.name}) for: ${task.description.slice(0, 100)}`,
      systemPrompt: this.buildWorkerSystemPrompt(task, worker),
      tools,
      model: worker.model,
      maxTokenBudget: worker.maxTokens ?? this.config.maxTokensPerWorker,
      maxIterations: this.config.workerMaxIterations,
      capabilities: worker.capabilities,
    };

    this.agentRegistry.registerAgent(agentDef);
    this.registeredAgentNames.add(agentName);

    // Build the task prompt with dependency context
    const taskPrompt = this.buildTaskPrompt(task);

    // Create the promise that tracks execution
    const startedAt = Date.now();
    // V6: Per-task-type timeout — research/analysis tasks get more time by default
    const typeTimeout = this.config.taskTypeTimeouts?.[task.type];
    const timeoutMs = typeTimeout ?? this.config.workerTimeout;

    // H3: Wrap spawn with timeout enforcement
    const spawnPromise = this.spawnAgent(agentName, taskPrompt);
    let timeoutHandle: ReturnType<typeof setTimeout>;
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutHandle = setTimeout(() => reject(new Error(`Worker timeout after ${timeoutMs}ms`)), timeoutMs);
    });
    const promise = Promise.race([spawnPromise, timeoutPromise]).then(result => {
      clearTimeout(timeoutHandle);
      return { taskId: task.id, result, startedAt };
    });

    // Track active worker
    this.activeWorkers.set(task.id, {
      taskId: task.id,
      task,
      workerName: worker.name,
      model: worker.model,
      startedAt,
      promise,
    });
  }

  /**
   * Wait for any active worker to complete.
   * Returns the task ID, spawn result, and worker startedAt timestamp.
   *
   * H1: Rewritten to handle errors correctly. The old approach used
   * Promise.race([promise, Promise.resolve('pending')]) which always
   * resolved to 'pending' immediately, making error detection impossible.
   */
  async waitForAny(): Promise<{ taskId: string; result: SpawnResult; startedAt: number } | null> {
    if (this.activeWorkers.size === 0) return null;

    // Wrap each promise so rejections become resolved error results
    // This ensures Promise.race always resolves (never rejects)
    const wrappedPromises = [...this.activeWorkers.values()].map(worker =>
      worker.promise.catch((error): { taskId: string; result: SpawnResult; startedAt: number } => ({
        taskId: worker.taskId,
        result: {
          success: false,
          output: `Worker error: ${(error as Error).message}`,
          metrics: {
            tokens: 0,
            duration: Date.now() - worker.startedAt,
            // V7: Use -1 for timeout errors so the orchestrator can distinguish
            // timeouts (worker was working but ran out of time) from hollow completions
            // (worker produced no tool calls at all)
            toolCalls: (error as Error).message.includes('timeout') ? -1 : 0,
          },
        },
        startedAt: worker.startedAt,
      })),
    );

    const completed = await Promise.race(wrappedPromises);

    // Clean up the completed worker
    const worker = this.activeWorkers.get(completed.taskId);
    if (worker) {
      this.activeWorkers.delete(completed.taskId);
      const agentName = `swarm-${worker.workerName}-${completed.taskId}`;
      this.agentRegistry.unregisterAgent(agentName);
      this.registeredAgentNames.delete(agentName);
    }

    return completed;
  }

  /**
   * Wait for all active workers to complete.
   */
  async waitForAll(): Promise<{ taskId: string; result: SpawnResult; startedAt: number }[]> {
    const results: { taskId: string; result: SpawnResult; startedAt: number }[] = [];

    while (this.activeWorkers.size > 0) {
      const result = await this.waitForAny();
      if (result) results.push(result);
    }

    return results;
  }

  /**
   * Convert a SpawnResult to a SwarmTaskResult.
   * Uses OpenRouter pricing when available, falls back to rough estimate.
   */
  toTaskResult(spawnResult: SpawnResult, task: SwarmTask, durationMs: number): SwarmTaskResult {
    const tokens = spawnResult.metrics.tokens;
    const model = task.assignedModel ?? 'unknown';
    // Use real pricing from OpenRouter when cache is initialized, otherwise fallback
    const estimatedCost = isModelCacheInitialized()
      ? calculateCost(model, Math.floor(tokens * 0.6), Math.floor(tokens * 0.4))
      : tokens * 0.0000005;

    return {
      success: spawnResult.success,
      output: spawnResult.output,
      closureReport: spawnResult.structured,
      tokensUsed: tokens,
      costUsed: estimatedCost,
      durationMs,
      model: task.assignedModel ?? 'unknown',
      filesModified: spawnResult.structured?.actionsTaken
        ?.filter((a: string) => a.includes('file') || a.includes('wrote') || a.includes('created'))
        ?? [],
      findings: spawnResult.structured?.findings,
    };
  }

  /**
   * Get status of all active workers (for TUI).
   */
  getActiveWorkerStatus(): SwarmWorkerStatus[] {
    const now = Date.now();
    return [...this.activeWorkers.values()].map(w => ({
      taskId: w.taskId,
      taskDescription: w.task.description,
      model: w.model,
      workerName: w.workerName,
      elapsedMs: now - w.startedAt,
      startedAt: w.startedAt,
    }));
  }

  /**
   * Cancel all active workers and wait briefly for cleanup.
   * M6: Used by orchestrator cancel() to let workers finish gracefully.
   */
  async cancelAll(): Promise<void> {
    // Give active workers a brief window to complete
    if (this.activeWorkers.size > 0) {
      const timeout = Math.min(5000, this.config.workerTimeout / 10);
      await Promise.race([
        Promise.allSettled([...this.activeWorkers.values()].map(w => w.promise)),
        new Promise<void>(resolve => setTimeout(resolve, timeout)),
      ]);
    }
    this.cleanup();
  }

  /**
   * Clean up all registered agents.
   */
  cleanup(): void {
    for (const name of this.registeredAgentNames) {
      this.agentRegistry.unregisterAgent(name);
    }
    this.registeredAgentNames.clear();
    this.activeWorkers.clear();
  }

  /**
   * Build a system prompt for a worker.
   * V2: Enhanced with anti-loop rules, no-exploration directive, and output format requirements.
   * V7: Progressive prompt reduction — retries use lighter prompts to avoid overwhelming cheap models.
   *
   * Prompt tiers based on attempt number:
   *   attempt 0: 'full'    — all additions (delegation, env facts block, quality self-assessment)
   *   attempt 1: 'reduced' — compact facts, skip delegation for research/analysis tasks
   *   attempt 2+: 'minimal' — only persona + task description + type rules + retry context
   */
  private buildWorkerSystemPrompt(task: SwarmTask, worker: SwarmWorkerSpec): string {
    const stuckThreshold = this.config.workerStuckThreshold ?? 3;
    const parts: string[] = [];

    // Determine prompt tier based on attempt number
    const promptTier: 'full' | 'reduced' | 'minimal' =
      task.attempts === 0 ? 'full'
      : task.attempts === 1 ? 'reduced'
      : 'minimal';

    // V3: Inject worker persona if configured
    if (worker.persona) {
      parts.push(worker.persona, '');
    }

    parts.push(
      `You are a ${worker.name} worker${worker.role ? ` (${worker.role})` : ''} in a swarm of specialized AI agents.`,
      `Your specific task: ${task.description}`,
      '',
    );

    // V4/V7: Environment facts — full block on first attempt, compact one-liner on retries
    const customFacts = this.config.facts?.custom ?? [];
    if (promptTier === 'full') {
      parts.push(formatFactsBlock(getEnvironmentFacts(customFacts)), '');
    } else if (promptTier === 'reduced') {
      parts.push(formatFactsCompact(getEnvironmentFacts(customFacts)), '');
    }
    // 'minimal' tier: skip environment facts entirely

    // V3: Inject philosophy if configured (skip on minimal tier)
    if (this.config.philosophy && promptTier !== 'minimal') {
      parts.push('═══ PHILOSOPHY ═══', '', this.config.philosophy, '');
    }

    // Task-type-specific rules: research/analysis/design get research rules,
    // merge gets synthesis rules, document gets doc rules, everything else gets code rules
    const taskType = task.type;

    if (taskType === 'research' || taskType === 'analysis' || taskType === 'design') {
      parts.push(
        '═══ RESEARCH TASK RULES ═══',
        '',
        'RESEARCH RULES (violations waste budget):',
        '- Use web_search, read_file, glob, grep to gather information.',
        '- You are NOT expected to write or edit code files.',
        `- After ${stuckThreshold} iterations without new findings, write up what you have.`,
        '- Do NOT run ls/find/tree to "understand the project". You have context below.',
        '- If you get the same result from a tool twice, try a COMPLETELY different approach.',
        '',
        'EFFICIENCY RULES:',
        '- Focus ONLY on your assigned research topic. Do not explore unrelated areas.',
        `- You have ${this.config.workerMaxIterations} max iterations and a limited token budget.`,
        '- Prefer grep and targeted reads over reading entire files.',
        '- Synthesize findings as you go — do not wait until the end.',
        '',
        'OUTPUT FORMAT — When finished, summarize:',
        '1. Key findings and insights',
        '2. Sources consulted (files read, searches performed)',
        '3. Any gaps or areas needing further investigation',
      );
    } else if (taskType === 'merge') {
      parts.push(
        '═══ SYNTHESIS TASK RULES ═══',
        '',
        'SYNTHESIS RULES (violations waste budget):',
        '- Read outputs from dependency tasks provided in context below.',
        '- Combine, synthesize, and summarize the material into a coherent result.',
        '- Do NOT re-research — work with the material given to you.',
        '- Do NOT run web_search or explore the codebase independently.',
        '- If you get the same result from a tool twice, try a COMPLETELY different approach.',
        '',
        'EFFICIENCY RULES:',
        '- Focus ONLY on synthesizing the provided inputs.',
        `- You have ${this.config.workerMaxIterations} max iterations and a limited token budget.`,
        '- Read dependency outputs first, then produce your synthesis.',
        '',
        'OUTPUT FORMAT — When finished, provide:',
        '1. Synthesized result combining all inputs',
        '2. Key themes or patterns across inputs',
        '3. Any conflicts or gaps between inputs',
      );
    } else if (taskType === 'document') {
      parts.push(
        '═══ DOCUMENTATION TASK RULES ═══',
        '',
        'DOCUMENTATION RULES (violations waste budget):',
        `- Never run ls, find, pwd, or tree more than once each.`,
        '- If you get the same result from a tool twice, try a COMPLETELY different approach.',
        `- After ${stuckThreshold} iterations without writing a file, START WRITING IMMEDIATELY.`,
        '- Do NOT run ls/find/tree to "understand the project". You have context below.',
        '',
        'EFFICIENCY RULES:',
        '- Focus ONLY on your assigned documentation task.',
        `- You have ${this.config.workerMaxIterations} max iterations and a limited token budget.`,
        '- Read files for context, then write documentation.',
        '',
        'OUTPUT FORMAT — When finished, summarize:',
        '1. Documentation files created/modified',
        '2. Key sections documented',
        '3. Any areas needing further documentation',
      );
    } else {
      // Default: code/test/refactor/integrate/deploy — original behavior preserved exactly
      parts.push(
        '═══ CRITICAL RULES ═══',
        '',
        'ANTI-LOOP RULES (violations waste budget):',
        `- Never run ls, find, pwd, or tree more than once each.`,
        '- If you get the same result from a tool twice, try a COMPLETELY different approach.',
        `- After ${stuckThreshold} iterations without writing/editing a file, START CODING IMMEDIATELY.`,
        '- Do NOT run ls/find/tree to "understand the project". You have context below.',
        '',
        'EFFICIENCY RULES:',
        '- Focus ONLY on your assigned task. Do not explore unrelated code.',
        `- You have ${this.config.workerMaxIterations} max iterations and a limited token budget.`,
        '- Read files only when you need specific content. Prefer grep over reading entire files.',
        '- Make changes incrementally — edit one file, verify, move on.',
        '',
        'OUTPUT FORMAT — When finished, summarize:',
        '1. What you accomplished (files created/modified)',
        '2. Key decisions made',
        '3. Any issues encountered or unresolved items',
      );
    }

    // V5: Retry context — inject previous feedback so worker doesn't repeat mistakes
    if (task.attempts > 0 && task.retryContext) {
      parts.push(
        '',
        '═══ RETRY CONTEXT (THIS IS YOUR 2ND+ ATTEMPT) ═══',
        '',
      );
      if (task.retryContext.previousScore === 0) {
        parts.push(
          `Your previous attempt FAILED with error:`,
          task.retryContext.previousFeedback,
          '',
          'Diagnose what went wrong and try a completely different approach.',
        );
      } else {
        parts.push(
          `Previous attempt scored ${task.retryContext.previousScore}/5.`,
          `Judge feedback: ${task.retryContext.previousFeedback}`,
          '',
          'You MUST address the feedback above. Try a DIFFERENT approach from your previous attempt.',
          'Focus specifically on what the judge flagged as wrong.',
        );
      }
    }

    if (task.targetFiles && task.targetFiles.length > 0) {
      parts.push('', `TARGET FILES (you should modify these):`, ...task.targetFiles.map(f => `  - ${f}`));
    }

    if (task.readFiles && task.readFiles.length > 0) {
      parts.push('', `REFERENCE FILES (read for context):`, ...task.readFiles.map(f => `  - ${f}`));
    }

    // V7: Delegation spec — skip for research/analysis tasks (redundant with research rules)
    // and skip on retries (prompt is already long enough)
    if (promptTier === 'full' && taskType !== 'research' && taskType !== 'analysis') {
      const delegationSpec = createMinimalDelegationSpec(task.description, worker.name);
      parts.push('', '═══ DELEGATION SPEC ═══', '', buildDelegationPrompt(delegationSpec));
    }

    // V7: Quality self-assessment — only on first attempt
    if (promptTier === 'full') {
      parts.push('', getSubagentQualityPrompt());
    }

    return parts.join('\n');
  }

  /**
   * Build a task prompt including dependency context.
   * V2: Truncates large dependency context to prevent context explosion.
   */
  private buildTaskPrompt(task: SwarmTask): string {
    const parts: string[] = [task.description];

    if (task.dependencyContext) {
      let context = task.dependencyContext;
      // V3: Respect communication config for max dependency context length
      const maxLen = this.config.communication?.dependencyContextMaxLength ?? 2000;
      // Truncate large context — extract key lines (file names, "created"/"implemented" mentions)
      if (context.length > maxLen) {
        const lines = context.split('\n');
        const keyLines = lines.filter(line =>
          line.startsWith('[Dependency:') ||
          /\b(created|implemented|modified|wrote|built|added|file|\.ts|\.js|\.tsx)\b/i.test(line),
        );
        context = keyLines.join('\n');
        if (context.length > maxLen) {
          context = context.slice(0, maxLen) + '\n... (truncated)';
        }
      }
      parts.push('', '--- CONTEXT FROM COMPLETED DEPENDENCIES ---', context);
    }

    return parts.join('\n');
  }
}

/**
 * Factory function.
 */
export function createSwarmWorkerPool(
  config: SwarmConfig,
  agentRegistry: AgentRegistry,
  spawnAgent: SpawnAgentFn,
  budgetPool: SwarmBudgetPool,
): SwarmWorkerPool {
  return new SwarmWorkerPool(config, agentRegistry, spawnAgent, budgetPool);
}
