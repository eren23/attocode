/**
 * Swarm Worker Pool
 *
 * Manages concurrent worker dispatch via existing spawnAgent() infrastructure.
 * Uses slot-based concurrency control and dynamic agent registration.
 */

import type { AgentRegistry, AgentDefinition, SpawnResult } from '../agent-registry.js';
import type { SwarmConfig, SwarmTask, SwarmTaskResult, SwarmWorkerSpec, SwarmWorkerStatus } from './types.js';
import { getTaskTypeConfig, type WorkerCapability } from './types.js';
import { selectWorkerForCapability, type ModelHealthTracker } from './model-selector.js';
import type { SwarmBudgetPool } from './swarm-budget.js';
import type { SharedContextEngine } from '../../shared/context-engine.js';
import { WorkerBudgetTracker, createWorkerBudgetTracker } from '../../shared/budget-tracker.js';
import { buildDelegationPrompt, createMinimalDelegationSpec } from '../delegation-protocol.js';
import { getSubagentQualityPrompt } from '../thinking-strategy.js';
import { getEnvironmentFacts, formatFactsBlock, formatFactsCompact } from '../environment-facts.js';
import { calculateCost, isModelCacheInitialized } from '../openrouter-pricing.js';
import { resolvePolicyProfile } from '../policy-engine.js';

// ─── D2: Lightweight Model Detection ───────────────────────────────────────

/** D2: Detect cheap/weak models that benefit from minimal prompts. */
export function isLightweightModel(model: string): boolean {
  const lower = model.toLowerCase();
  return /\b(mini|micro|small|nano|tiny|lite|glm|phi|gemma-2b|qwen.*0\.5|qwen.*1\.5)\b/.test(lower);
}

// ─── Worker Timeout Error ──────────────────────────────────────────────────

/** Typed error for worker timeouts, used to distinguish timeouts from hollow completions. */
export class WorkerTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'WorkerTimeoutError';
  }
}

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
  budgetTracker: WorkerBudgetTracker;
  promise: Promise<{ taskId: string; result: SpawnResult; startedAt: number }>;
}

// ─── Worker Pool ───────────────────────────────────────────────────────────

export class SwarmWorkerPool {
  private config: SwarmConfig;
  private agentRegistry: AgentRegistry;
  private spawnAgent: SpawnAgentFn;
  private budgetPool: SwarmBudgetPool;
  private workers: SwarmWorkerSpec[];
  private healthTracker?: ModelHealthTracker;
  private sharedContextEngine?: SharedContextEngine;

  private activeWorkers: Map<string, ActiveWorker> = new Map();
  private completedTrackers: Map<string, WorkerBudgetTracker> = new Map();
  private registeredAgentNames: Set<string> = new Set();
  private dispatchCount = 0;

  constructor(
    config: SwarmConfig,
    agentRegistry: AgentRegistry,
    spawnAgent: SpawnAgentFn,
    budgetPool: SwarmBudgetPool,
    healthTracker?: ModelHealthTracker,
    sharedContextEngine?: SharedContextEngine,
  ) {
    this.config = config;
    this.agentRegistry = agentRegistry;
    this.spawnAgent = spawnAgent;
    this.budgetPool = budgetPool;
    this.workers = config.workers;
    this.healthTracker = healthTracker;
    this.sharedContextEngine = sharedContextEngine;
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
    const capability: WorkerCapability = getTaskTypeConfig(task.type, this.config).capability ?? 'code';
    return selectWorkerForCapability(this.workers, capability, this.dispatchCount++, this.healthTracker);
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

    const requestedProfile = worker.policyProfile;
    const policyResolution = resolvePolicyProfile({
      isSwarmWorker: true,
      requestedProfile,
      swarmConfig: this.config,
      worker,
      taskType: task.type,
      legacyAllowedTools: this.config.toolAccessMode === 'whitelist' ? worker.allowedTools : undefined,
      legacyDeniedTools: worker.deniedTools,
      globalDeniedTools: this.config.globalDeniedTools,
    });
    const { profile } = policyResolution;

    // If profile requires whitelist, expose only allowed tools to this worker.
    const tools = (this.config.toolAccessMode === 'all' && !requestedProfile)
      ? undefined
      : (profile.toolAccessMode === 'whitelist'
        ? profile.allowedTools
        : worker.allowedTools);

    // V7: Get effective per-type config (user overrides > builtin defaults > fallback)
    const typeConfig = getTaskTypeConfig(task.type, this.config);

    // F3: Wider complexity scaling: 0.3 + complexity * 0.14 (range 0.44x-1.7x)
    // Previously 0.5 + complexity * 0.1 (range 0.6x-1.5x) — too narrow for diverse tasks.
    const complexityMultiplier = 0.3 + (task.complexity ?? 5) * 0.14;
    // Escalating retry budget — if a worker ran out on the first attempt,
    // giving it the same budget will produce the same result.
    // 1st retry: 1.3x, 2nd: 1.6x, 3rd+: 2.0x (double budget).
    const retryMultiplier = task.attempts === 0 ? 1.0
      : task.attempts === 1 ? 1.3
      : task.attempts === 2 ? 1.6
      : 2.0;

    // F3: Task-aware budget using tokenBudgetRange from TaskTypeConfig.
    // Foundation tasks get max budget, leaf tasks get proportional to complexity.
    let baseTokenBudget: number;
    if (typeConfig.tokenBudgetRange) {
      const { min, max } = typeConfig.tokenBudgetRange;
      if (task.isFoundation) {
        baseTokenBudget = max;
      } else {
        // Scale linearly: complexity 1 → min, complexity 10 → max
        const ratio = Math.min(1, Math.max(0, ((task.complexity ?? 5) - 1) / 9));
        baseTokenBudget = Math.round(min + ratio * (max - min));
      }
    } else {
      baseTokenBudget = typeConfig.tokenBudget ?? worker.maxTokens ?? this.config.maxTokensPerWorker;
    }
    const baseMaxIterations = typeConfig.maxIterations ?? this.config.workerMaxIterations;
    // 2nd+ retries get 50% more iterations — more turns to complete the task
    const iterationMultiplier = task.attempts >= 2 ? 1.5 : 1.0;

    // V7: Per-task-type timeout from TaskTypeConfig, with backward compat to taskTypeTimeouts
    // Computed before agentDef so we can pass it through to spawnAgent's timeout chain
    const baseTimeoutMs = typeConfig.timeout ?? this.config.taskTypeTimeouts?.[task.type] ?? Math.max(this.config.workerTimeout, 240_000);
    // Foundation tasks (3+ dependents) get 2.5x timeout to reduce cascade failure risk
    const adjustedTimeoutMs = task.isFoundation ? Math.round(baseTimeoutMs * 2.5) : baseTimeoutMs;
    // Apply both complexity and retry multipliers — retries get more wall-clock time too
    const timeoutMs = Math.round(adjustedTimeoutMs * complexityMultiplier * retryMultiplier);

    const agentDef: AgentDefinition = {
      name: agentName,
      description: `Swarm worker (${worker.name}) for: ${task.description.slice(0, 100)}`,
      systemPrompt: this.buildWorkerSystemPrompt(task, worker),
      tools,
      // Pin the resolved profile so spawnAgent does not re-infer a different one.
      policyProfile: policyResolution.profileName,
      // Respect failover-assigned model on retries.
      model: task.assignedModel ?? worker.model,
      taskType: task.type,
      maxTokenBudget: Math.round(baseTokenBudget * complexityMultiplier * retryMultiplier),
      maxIterations: Math.round(baseMaxIterations * complexityMultiplier * retryMultiplier * iterationMultiplier),
      timeout: timeoutMs,  // Pass calculated timeout through to spawnAgent (highest priority in timeout chain)
      idleTimeout: typeConfig.idleTimeout,  // V7: Configurable idle timeout (for long-running tasks)
      capabilities: worker.capabilities,
      // W3: Swarm workers get tighter economics thresholds by default
      // These can be overridden via swarmConfig.economicsTuning
      economicsTuning: {
        doomLoopThreshold: 2,
        doomLoopFuzzyThreshold: 3,
        explorationFileThreshold: 5,
        explorationIterThreshold: 3,
        zeroProgressThreshold: 3,
        progressCheckpoint: 3,
        ...(this.config.economicsTuning ?? {}),
      },
    };

    this.agentRegistry.registerAgent(agentDef);
    this.registeredAgentNames.add(agentName);

    // Build the task prompt with dependency context
    const taskPrompt = this.buildTaskPrompt(task);

    // Create the promise that tracks execution
    const startedAt = Date.now();

    // V8: Worker pool timeout is a backstop AFTER the agent's graceful timeout.
    // The agent's graceful timeout (in spawnAgent) provides a wrapup window before hard kill.
    // This backstop fires 60s later to catch cases where graceful timeout fails.
    const backstopTimeoutMs = timeoutMs + 60_000;
    const spawnPromise = this.spawnAgent(agentName, taskPrompt);
    let timeoutHandle: ReturnType<typeof setTimeout>;
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutHandle = setTimeout(() => reject(new WorkerTimeoutError(`Worker timeout after ${backstopTimeoutMs}ms (base: ${timeoutMs}ms + 60s backstop)`)), backstopTimeoutMs);
    });
    const promise = Promise.race([spawnPromise, timeoutPromise]).then(result => {
      clearTimeout(timeoutHandle);
      return { taskId: task.id, result, startedAt };
    });

    // Create per-worker budget tracker (orchestrator-side visibility)
    const budgetTracker = createWorkerBudgetTracker({
      workerId: task.id,
      maxTokens: agentDef.maxTokenBudget!,
      maxIterations: agentDef.maxIterations!,
      doomLoopThreshold: agentDef.economicsTuning?.doomLoopThreshold ?? 3,
    });

    // Track active worker
    this.activeWorkers.set(task.id, {
      taskId: task.id,
      task,
      workerName: worker.name,
      model: worker.model,
      startedAt,
      budgetTracker,
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
            // (worker produced no tool calls at all).
            // Uses instanceof check instead of fragile string matching.
            toolCalls: (error instanceof WorkerTimeoutError) ? -1 : 0,
          },
        },
        startedAt: worker.startedAt,
      })),
    );

    const completed = await Promise.race(wrappedPromises);

    // Clean up the completed worker and populate budget tracker
    const worker = this.activeWorkers.get(completed.taskId);
    if (worker) {
      // Populate budget tracker with actual usage from SpawnResult
      const tokens = completed.result.metrics.tokens;
      worker.budgetTracker.recordLLMUsage(
        Math.floor(tokens * 0.6),  // estimate input
        Math.floor(tokens * 0.4),  // estimate output
      );
      // Store tracker for utilization lookup before removing active worker
      this.completedTrackers.set(completed.taskId, worker.budgetTracker);

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

    // Look up per-worker budget utilization from completed tracker
    const tracker = this.completedTrackers.get(task.id);
    const budgetUtilization = tracker ? tracker.getUtilization() : undefined;

    return {
      success: spawnResult.success,
      output: spawnResult.output,
      closureReport: spawnResult.structured,
      tokensUsed: tokens,
      costUsed: estimatedCost,
      durationMs,
      model: task.assignedModel ?? 'unknown',
      filesModified: spawnResult.filesModified ?? [],
      findings: spawnResult.structured?.findings,
      toolCalls: spawnResult.metrics.toolCalls,
      budgetUtilization,
    };
  }

  /**
   * Get budget utilization for a completed worker.
   */
  getWorkerUtilization(taskId: string): { tokenPercent: number; iterationPercent: number } | undefined {
    return this.completedTrackers.get(taskId)?.getUtilization();
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
    this.completedTrackers.clear();
  }

  /**
   * Build a system prompt for a worker.
   * V2: Enhanced with anti-loop rules, no-exploration directive, and output format requirements.
   * V7: Progressive prompt reduction — retries use lighter prompts to avoid overwhelming cheap models.
   *
   * Prompt tiers based on attempt number:
   *   attempt 0: 'full'    — all additions (delegation, env facts block, quality self-assessment)
   *   attempt 1+: 'reduced' — compact facts, skip delegation for research/analysis tasks
   */
  private buildWorkerSystemPrompt(task: SwarmTask, worker: SwarmWorkerSpec): string {
    const stuckThreshold = this.config.workerStuckThreshold ?? 3;
    const parts: string[] = [];

    // D2: Determine prompt tier — explicit override > retry detection > model detection > full
    const promptTier: 'full' | 'reduced' | 'minimal' =
      worker.promptTier ??
      (task.attempts > 0 ? 'reduced' :
       isLightweightModel(task.assignedModel ?? worker.model) ? 'reduced' : 'full');

    // D2: Minimal prompt tier for cheap/weak models — drastically reduced prompt
    if (promptTier === 'minimal') {
      parts.push(
        `You are a ${worker.name} worker. Your task: ${task.description}`,
        '',
        '═══ RULES ═══',
        '',
        'CRITICAL:',
        '- Use tools to do your work. A response with zero tool calls is failure.',
        '- Use read_file/grep to read code. Use write_file/edit_file to modify code.',
        '- Do NOT use bash for file reading (no cat/head/tail). Use read_file instead.',
        `- You have ${this.config.workerMaxIterations} max iterations. Work fast.`,
        '',
        `AVAILABLE TOOLS: ${(worker.allowedTools ?? ['write_file', 'edit_file', 'read_file', 'glob', 'grep', 'bash']).join(', ')}`,
      );

      if (task.targetFiles && task.targetFiles.length > 0) {
        parts.push('', `TARGET FILES: ${task.targetFiles.join(', ')}`);
      }
      if (task.readFiles && task.readFiles.length > 0) {
        parts.push('', `REFERENCE FILES: ${task.readFiles.join(', ')}`);
      }
      if (task.attempts > 0 && task.retryContext) {
        parts.push(
          '',
          `RETRY #${task.attempts}: Previous score ${task.retryContext.previousScore}/5. Fix: ${task.retryContext.previousFeedback}`,
        );
        // F12: Hollow completion — prescribe exact first action
        if (task.retryContext.previousScore <= 1) {
          const firstTarget = task.targetFiles?.[0] ?? task.readFiles?.[0];
          parts.push(
            '',
            '⚠ YOUR PREVIOUS ATTEMPT HAD ZERO TOOL CALLS — THIS IS AN AUTOMATIC FAILURE.',
            firstTarget
              ? `YOUR VERY FIRST ACTION: Call ${task.targetFiles?.[0] ? 'write_file' : 'read_file'} on "${firstTarget}".`
              : 'YOUR VERY FIRST ACTION: Call read_file or write_file. Text-only responses = failure.',
          );
        }
      }
      return parts.join('\n');
    }

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
    } else {
      parts.push(formatFactsCompact(getEnvironmentFacts(customFacts)), '');
    }

    // V3: Inject philosophy if configured
    if (this.config.philosophy) {
      parts.push('═══ PHILOSOPHY ═══', '', this.config.philosophy, '');
    }

    // V7: Use promptTemplate from TaskTypeConfig for dispatching prompt rules.
    // Built-in templates: 'research', 'synthesis', 'document', 'code' (default).
    const typeConfig = getTaskTypeConfig(task.type, this.config);
    const promptTemplate = typeConfig.promptTemplate ?? 'code';
    const taskType = task.type;

    if (promptTemplate === 'research') {
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
    } else if (promptTemplate === 'synthesis') {
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
    } else if (promptTemplate === 'document') {
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
        'TOOL USAGE:',
        '- To CREATE a new file: use write_file (NOT bash with cat/echo/heredoc)',
        '- To MODIFY an existing file: use edit_file (NOT bash with sed/awk)',
        '- To READ a file: use read_file (NOT bash with cat/head/tail)',
        '- Use bash ONLY for: running commands (npm, node, git, tsc, tests, etc.)',
        '- NEVER send file contents as a bash command argument',
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
        'TOOL USAGE:',
        '- To CREATE a new file: use write_file (NOT bash with cat/echo/heredoc)',
        '- To MODIFY an existing file: use edit_file (NOT bash with sed/awk)',
        '- To READ a file: use read_file (NOT bash with cat/head/tail)',
        '- To SEARCH for files: use glob (NOT bash with find/ls)',
        '- To SEARCH file contents: use grep (NOT bash with grep/rg)',
        '- Use bash ONLY for: running commands (npm, node, git, tsc, tests, etc.)',
        '- NEVER send file contents as a bash command argument',
        '',
        'OUTPUT FORMAT — When finished, summarize:',
        '1. What you accomplished (files created/modified)',
        '2. Key decisions made',
        '3. Any issues encountered or unresolved items',
      );
    }

    // Inject available tool names so the model knows exactly what it can call
    if (worker.allowedTools && worker.allowedTools.length > 0) {
      parts.push('', `AVAILABLE TOOLS: ${worker.allowedTools.join(', ')}`);
    } else {
      parts.push('', 'You have access to ALL tools including: write_file, edit_file, read_file, glob, grep, bash, web_search');
    }

    // V9: Action-orientation reinforcement for task types that MUST produce file changes
    if (taskType === 'implement' || taskType === 'test' || taskType === 'refactor') {
      parts.push(
        '',
        '═══ ACTION ORIENTATION ═══',
        '',
        'You are judged by actual file changes and tool usage, not by the quality of your written analysis.',
        'If your task type is implement, test, or refactor, you MUST make file changes.',
        'A response with zero tool calls is an automatic failure.',
      );
    }

    // V5: Retry context — inject previous feedback so worker doesn't repeat mistakes
    if (task.attempts > 0 && task.retryContext) {
      // F22: Include swarm progress so retrying workers know what's been accomplished
      if (task.retryContext.swarmProgress) {
        parts.push(
          '',
          '═══ SWARM PROGRESS ═══',
          '',
          task.retryContext.swarmProgress,
        );
      }

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
          'REMINDER: Use write_file to create files and edit_file to modify them. Do NOT use bash for file operations.',
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
      // F12: Hollow completion — prescribe exact first action
      if (task.retryContext.previousScore <= 1) {
        const firstTarget = task.targetFiles?.[0] ?? task.readFiles?.[0];
        parts.push(
          '',
          '⚠ YOUR PREVIOUS ATTEMPT HAD ZERO TOOL CALLS — THIS IS AN AUTOMATIC FAILURE.',
          firstTarget
            ? `YOUR VERY FIRST ACTION: Call ${task.targetFiles?.[0] ? 'write_file' : 'read_file'} on "${firstTarget}".`
            : 'YOUR VERY FIRST ACTION: Call read_file or write_file. Text-only responses = failure.',
        );
      }
    }

    if (task.retryContext?.previousFiles?.length) {
      parts.push(
        '',
        '═══ FILES FROM PREVIOUS ATTEMPT ═══',
        '',
        'These files ALREADY EXIST on disk from the previous attempt:',
        ...task.retryContext.previousFiles.map(f => `  - ${f}`),
        '',
        'DO NOT recreate these with write_file. Use edit_file to fix issues, or read_file to check state.',
      );
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

    // Phase 3.1: Cross-worker failure learning via SharedContextEngine
    if (this.sharedContextEngine) {
      const failureGuidance = this.sharedContextEngine.getFailureGuidance();
      if (failureGuidance) {
        parts.push('', '═══ CROSS-WORKER FAILURE LEARNING ═══', '', failureGuidance);
      }
      // Goal recitation only on full prompts (not reduced/minimal)
      if (promptTier === 'full') {
        const workerTask = { id: task.id, description: task.description, goal: task.description, dependencies: task.dependencies };
        const goalRecitation = this.sharedContextEngine.getGoalRecitation(workerTask);
        if (goalRecitation) parts.push('', goalRecitation);
      }
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
  healthTracker?: ModelHealthTracker,
  sharedContextEngine?: SharedContextEngine,
): SwarmWorkerPool {
  return new SwarmWorkerPool(config, agentRegistry, spawnAgent, budgetPool, healthTracker, sharedContextEngine);
}
