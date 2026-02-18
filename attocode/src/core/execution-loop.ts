/**
 * Execution Loop Module (Phase 2.1)
 *
 * Extracted from ProductionAgent.executeDirectly().
 * Contains the main ReAct while(true) loop: cancellation checks, resource checks,
 * economics/budget checks with compaction recovery, loop detection, context
 * engineering injection (recitation, failure evidence), LLM call dispatch,
 * resilience handling, tool execution, and compaction.
 */

import type { Message, OpenTaskSummary } from '../types.js';

import { isFeatureEnabled } from '../defaults.js';
import { estimateTokenCount, estimateTokensFromCharCount } from '../integrations/utilities/token-estimate.js';

import type { AgentContext, AgentContextMutators } from './types.js';
import { callLLM } from './response-handler.js';
import { executeToolCalls } from './tool-executor.js';

import {
  TIMEOUT_WRAPUP_PROMPT,
  stableStringify,
  type InjectionSlot,
} from '../integrations/index.js';
import { detectIncompleteActionResponse } from './completion-analyzer.js';
export { detectIncompleteActionResponse } from './completion-analyzer.js';

import { createComponentLogger } from '../integrations/utilities/logger.js';
import { validateSyntax } from '../integrations/safety/edit-validator.js';
import { runTypeCheck, formatTypeCheckNudge } from '../integrations/safety/type-checker.js';
import { invalidateAST } from '../integrations/context/codebase-ast.js';
import * as fs from 'node:fs';

const log = createComponentLogger('ExecutionLoop');

export type ExecutionTerminationReason =
  | 'completed'
  | 'resource_limit'
  | 'budget_limit'
  | 'max_iterations'
  | 'hard_context_limit'
  | 'incomplete_action'
  | 'open_tasks'
  | 'error';

export interface ExecutionLoopResult {
  success: boolean;
  terminationReason: ExecutionTerminationReason;
  failureReason?: string;
  openTasks?: OpenTaskSummary;
}

// =============================================================================
// EXECUTION LOOP DEFAULTS
// =============================================================================

export const EXECUTION_LOOP_DEFAULTS = {
  /** Preview length when compacting long tool outputs */
  COMPACT_PREVIEW_LENGTH: 200,
  /** Max expensive results preserved from compaction */
  MAX_PRESERVED_EXPENSIVE_RESULTS: 6,
  /** Messages to keep during emergency truncation */
  PRESERVE_RECENT: 10,
  /** Max chars per tool output before truncation */
  MAX_TOOL_OUTPUT_CHARS: 8000,
  /** Number of TS edits before triggering a type check */
  TYPE_CHECK_EDIT_THRESHOLD: 5,
  /** Safety margin ratio for context overflow guard */
  CONTEXT_SAFETY_RATIO: 0.9,
  /** Per-result budget safety margin */
  PER_RESULT_BUDGET_RATIO: 0.95,
} as const;

// =============================================================================
// HELPER FUNCTIONS (extracted from ProductionAgent private methods)
// =============================================================================

/**
 * Estimate total tokens in a message array.
 * Delegates to the shared token estimation utility (~3.5 chars/token).
 */
export function estimateContextTokens(messages: Message[]): number {
  let totalChars = 0;
  for (const msg of messages) {
    if (msg.content) {
      totalChars += msg.content.length;
    }
    if (msg.toolCalls) {
      for (const tc of msg.toolCalls) {
        totalChars += tc.name.length;
        totalChars += JSON.stringify(tc.arguments).length;
      }
    }
  }
  return estimateTokensFromCharCount(totalChars);
}

/**
 * Compact tool outputs to save context.
 */
export function compactToolOutputs(messages: Message[]): void {
  const { COMPACT_PREVIEW_LENGTH, MAX_PRESERVED_EXPENSIVE_RESULTS } = EXECUTION_LOOP_DEFAULTS;
  let compactedCount = 0;
  let savedChars = 0;

  const preservedExpensiveIndexes = messages
    .map((msg, index) => ({ msg, index }))
    .filter(({ msg }) => msg.role === 'tool' && msg.metadata?.preserveFromCompaction === true)
    .map(({ index }) => index);
  const preserveSet = new Set(preservedExpensiveIndexes.slice(-MAX_PRESERVED_EXPENSIVE_RESULTS));

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role === 'tool' && msg.content && msg.content.length > COMPACT_PREVIEW_LENGTH * 2) {
      if (msg.metadata?.preserveFromCompaction === true && preserveSet.has(i)) {
        continue;
      }
      const originalLength = msg.content.length;
      const preview = msg.content.slice(0, COMPACT_PREVIEW_LENGTH).replace(/\n/g, ' ');
      msg.content = `[${preview}...] (${originalLength} chars, compacted)`;
      savedChars += originalLength - msg.content.length;
      compactedCount++;
    }
  }

  if (compactedCount > 0 && process.env.DEBUG) {
    log.debug('Compacted tool outputs', {
      compactedCount,
      savedTokens: estimateTokensFromCharCount(savedChars),
    });
  }
}

/**
 * Extract a requested markdown artifact filename from a task prompt.
 */
export function extractRequestedArtifact(task: string): string | null {
  const markdownArtifactMatch = task.match(
    /(?:write|save|create)[^.\n]{0,120}\b([A-Za-z0-9._/-]+\.md)\b/i,
  );
  return markdownArtifactMatch?.[1] ?? null;
}

/**
 * Check whether a requested artifact appears to be missing.
 */
export function isRequestedArtifactMissing(
  requestedArtifact: string | null,
  executedToolNames: Set<string>,
): boolean {
  if (!requestedArtifact) return false;
  const artifactWriteTools = ['write_file', 'edit_file', 'apply_patch', 'append_file'];
  return !artifactWriteTools.some((toolName) => executedToolNames.has(toolName));
}

function getOpenTaskSummary(ctx: AgentContext): OpenTaskSummary | undefined {
  if (!ctx.taskManager) return undefined;
  const tasks = ctx.taskManager.list();
  const pending = tasks.filter((t) => t.status === 'pending').length;
  const inProgress = tasks.filter((t) => t.status === 'in_progress').length;
  const blocked = tasks.filter(
    (t) => t.status === 'pending' && ctx.taskManager?.isBlocked(t.id),
  ).length;
  return { pending, inProgress, blocked };
}

function getPendingWithOwnerCount(ctx: AgentContext): number {
  if (!ctx.taskManager) return 0;
  return ctx.taskManager.list().filter((t) => t.status === 'pending' && !!t.owner).length;
}

// =============================================================================
// EXTRACTED TESTABLE FUNCTIONS
// =============================================================================

/**
 * Narrow deps interface for budget pre-flight check.
 * Keeps the function testable without a full AgentContext.
 */
export interface BudgetCheckDeps {
  economics: {
    checkBudget(): {
      canContinue: boolean;
      forceTextOnly?: boolean;
      injectedPrompt?: string;
      allowTaskContinuation?: boolean;
      percentUsed: number;
      budgetType?: string;
      budgetMode?: string;
      isSoftLimit?: boolean;
      suggestedAction?: string;
      reason?: string;
    };
    getBudget(): { maxTokens: number; enforcementMode?: string };
    getUsage(): { tokens: number };
    updateBaseline(tokens: number): void;
  } | null;
  getTotalIterations(): number;
  maxIterations: number;
  parentIterations: number;
  state: { iteration: number; metrics: { retryCount?: number }; messages: Message[] };
  workLog?: { hasContent(): boolean; toCompactString(): string } | null;
  observability?: { logger?: { info(msg: string, data?: any): void; warn(msg: string, data?: any): void } | null } | null;
  traceCollector?: { record(entry: any): void } | null;
  emit(event: any): void;
}

export type BudgetCheckResult =
  | { action: 'continue'; forceTextOnly: boolean; budgetInjectedPrompt?: string; budgetAllowsTaskContinuation: boolean }
  | { action: 'recovery_success' }
  | { action: 'stop'; result: ExecutionLoopResult };

/**
 * Check economics/iteration budget before an iteration.
 * Returns whether to continue, stop, or whether recovery succeeded.
 */
export function checkIterationBudget(deps: BudgetCheckDeps, messages: Message[]): BudgetCheckResult {
  if (deps.economics) {
    const budgetCheck = deps.economics.checkBudget();

    const forceTextOnly = budgetCheck.forceTextOnly ?? false;
    const budgetInjectedPrompt = budgetCheck.injectedPrompt;
    const budgetAllowsTaskContinuation = budgetCheck.allowTaskContinuation ?? true;

    deps.traceCollector?.record({
      type: 'budget.check',
      data: {
        iteration: deps.state.iteration,
        canContinue: budgetCheck.canContinue,
        percentUsed: budgetCheck.percentUsed,
        budgetType: budgetCheck.budgetType,
        budgetMode: budgetCheck.budgetMode,
        forceTextOnly,
        allowTaskContinuation: budgetAllowsTaskContinuation,
        enforcementMode: deps.economics.getBudget().enforcementMode ?? 'strict',
        tokenUsage: deps.economics.getUsage().tokens,
        maxTokens: deps.economics.getBudget().maxTokens,
      },
    });

    if (!budgetCheck.canContinue) {
      // RECOVERY ATTEMPT: Try emergency context reduction
      const isTokenLimit =
        budgetCheck.budgetType === 'tokens' || budgetCheck.budgetType === 'cost';
      const alreadyTriedRecovery =
        (deps.state as { _recoveryAttempted?: boolean })._recoveryAttempted === true;

      if (isTokenLimit && !alreadyTriedRecovery) {
        deps.observability?.logger?.info(
          'Budget limit reached, attempting recovery via context reduction',
          { reason: budgetCheck.reason, percentUsed: budgetCheck.percentUsed },
        );

        deps.emit({
          type: 'resilience.retry',
          reason: 'budget_limit_compaction',
          attempt: 1,
          maxAttempts: 1,
        });
        deps.state.metrics.retryCount = (deps.state.metrics.retryCount ?? 0) + 1;
        (deps.state as { _recoveryAttempted?: boolean })._recoveryAttempted = true;

        const tokensBefore = estimateContextTokens(messages);

        // Step 1: Compact tool outputs aggressively
        compactToolOutputs(deps.state.messages);

        // Step 2: Emergency truncation - keep system + last N messages
        const PRESERVE_RECENT = EXECUTION_LOOP_DEFAULTS.PRESERVE_RECENT;
        if (messages.length > PRESERVE_RECENT + 2) {
          const systemMessage = messages.find((m) => m.role === 'system');
          const recentMessages = messages.slice(-PRESERVE_RECENT);

          messages.length = 0;
          if (systemMessage) {
            messages.push(systemMessage);
          }
          messages.push({
            role: 'system',
            content: `[CONTEXT REDUCED: Earlier messages were removed to stay within budget. Conversation continues from recent context.]`,
          });
          messages.push(...recentMessages);

          // Inject work log after emergency truncation
          if (deps.workLog?.hasContent()) {
            messages.push({ role: 'user', content: deps.workLog.toCompactString() });
          }

          // Update state messages too
          deps.state.messages.length = 0;
          deps.state.messages.push(...messages);
        }

        const tokensAfter = estimateContextTokens(messages);
        const reduction = Math.round((1 - tokensAfter / tokensBefore) * 100);

        if (tokensAfter < tokensBefore * 0.8) {
          deps.observability?.logger?.info(
            'Context reduction successful, continuing execution',
            { tokensBefore, tokensAfter, reduction },
          );

          deps.emit({ type: 'resilience.recovered', reason: 'budget_limit_compaction', attempts: 1 });
          deps.emit({ type: 'compaction.auto', tokensBefore, tokensAfter, messagesCompacted: tokensBefore - tokensAfter });
          deps.economics?.updateBaseline(tokensAfter);

          return { action: 'recovery_success' };
        }

        deps.observability?.logger?.warn('Context reduction insufficient', {
          tokensBefore, tokensAfter, reduction,
        });
      }

      // Hard limit reached and recovery failed
      deps.observability?.logger?.warn('Budget limit reached', {
        reason: budgetCheck.reason,
        budgetType: budgetCheck.budgetType,
      });

      if (budgetCheck.budgetType === 'iterations') {
        const totalIter = deps.getTotalIterations();
        const iterMsg =
          deps.parentIterations > 0
            ? `${deps.state.iteration} + ${deps.parentIterations} parent = ${totalIter}`
            : `${deps.state.iteration}`;
        const reason = `Max iterations reached (${iterMsg})`;
        deps.emit({ type: 'error', error: reason });
        return { action: 'stop', result: { success: false, terminationReason: 'max_iterations', failureReason: reason } };
      } else {
        const reason = budgetCheck.reason || 'Budget exceeded';
        deps.emit({ type: 'error', error: reason });
        return { action: 'stop', result: { success: false, terminationReason: 'budget_limit', failureReason: reason } };
      }
    }

    // Check for soft limits
    if (budgetCheck.isSoftLimit && budgetCheck.suggestedAction === 'request_extension') {
      deps.observability?.logger?.info('Approaching budget limit', {
        reason: budgetCheck.reason,
        percentUsed: budgetCheck.percentUsed,
      });
    }

    return { action: 'continue', forceTextOnly, budgetInjectedPrompt, budgetAllowsTaskContinuation };
  } else {
    // Fallback to simple iteration check
    if (deps.getTotalIterations() >= deps.maxIterations) {
      const totalIter = deps.getTotalIterations();
      const reason = `Max iterations reached (${totalIter})`;
      deps.observability?.logger?.warn('Max iterations reached', {
        iteration: deps.state.iteration,
        parentIterations: deps.parentIterations,
        total: totalIter,
      });
      deps.emit({ type: 'error', error: reason });
      return { action: 'stop', result: { success: false, terminationReason: 'max_iterations', failureReason: reason } };
    }
    return { action: 'continue', forceTextOnly: false, budgetAllowsTaskContinuation: true };
  }
}

/**
 * Narrow deps for auto-compaction handler.
 */
export interface AutoCompactionDeps {
  autoCompactionManager: {
    checkAndMaybeCompact(input: { currentTokens: number; messages: Message[] }): Promise<{
      status: string;
      compactedMessages?: Message[];
      ratio: number;
    }>;
  } | null;
  economics: {
    getUsage(): { tokens: number };
    getBudget(): { maxTokens: number };
    updateBaseline(tokens: number): void;
  } | null;
  compactionPending: boolean;
  store?: { getGoalsSummary(): string; getJuncturesSummary(arg0: undefined, count: number): string | null } | null;
  learningStore?: { getLearningContext(opts: { maxLearnings: number }): string | null } | null;
  workLog?: { hasContent(): boolean; toCompactString(): string } | null;
  observability?: { logger?: { info(msg: string, data?: any): void } | null } | null;
  traceCollector?: { record(entry: any): void } | null;
  emit(event: any): void;
}

export type AutoCompactionResult =
  | { status: 'ok' }
  | { status: 'compaction_prompt_injected' }
  | { status: 'compacted'; tokensBefore: number; tokensAfter: number }
  | { status: 'hard_limit'; result: ExecutionLoopResult }
  | { status: 'simple_compaction_triggered' };

/**
 * Handle auto-compaction of context when approaching token limits.
 * Returns the compaction status and whether messages were modified.
 */
export async function handleAutoCompaction(
  deps: AutoCompactionDeps,
  messages: Message[],
  stateMessages: Message[],
  setCompactionPending: (v: boolean) => void,
): Promise<AutoCompactionResult> {
  const currentContextTokens = estimateContextTokens(messages);

  if (deps.autoCompactionManager) {
    const compactionResult = await deps.autoCompactionManager.checkAndMaybeCompact({
      currentTokens: currentContextTokens,
      messages: messages,
    });

    if (compactionResult.status === 'compacted' && compactionResult.compactedMessages) {
      if (!deps.compactionPending) {
        setCompactionPending(true);
        const preCompactionMsg: Message = {
          role: 'user',
          content:
            '[SYSTEM] Context compaction is imminent. Summarize your current progress, key findings, and next steps into a single concise message. This will be preserved after compaction.',
        };
        messages.push(preCompactionMsg);
        stateMessages.push(preCompactionMsg);

        deps.observability?.logger?.info('Pre-compaction agentic turn: injected summary request');
        return { status: 'compaction_prompt_injected' };
      } else {
        setCompactionPending(false);

        // Replace messages with compacted version
        messages.length = 0;
        messages.push(...compactionResult.compactedMessages);
        stateMessages.length = 0;
        stateMessages.push(...compactionResult.compactedMessages);

        // Inject work log after compaction
        if (deps.workLog?.hasContent()) {
          const workLogMessage: Message = { role: 'user', content: deps.workLog.toCompactString() };
          messages.push(workLogMessage);
          stateMessages.push(workLogMessage);
        }

        // Context recovery
        const recoveryParts: string[] = [];

        if (deps.store) {
          const goalsSummary = deps.store.getGoalsSummary();
          if (goalsSummary && goalsSummary !== 'No active goals.' && goalsSummary !== 'Goals feature not available.') {
            recoveryParts.push(goalsSummary);
          }
        }

        if (deps.store) {
          const juncturesSummary = deps.store.getJuncturesSummary(undefined, 5);
          if (juncturesSummary) {
            recoveryParts.push(juncturesSummary);
          }
        }

        if (deps.learningStore) {
          const learnings = deps.learningStore.getLearningContext({ maxLearnings: 3 });
          if (learnings) {
            recoveryParts.push(learnings);
          }
        }

        if (recoveryParts.length > 0) {
          const recoveryMessage: Message = {
            role: 'user',
            content: `[CONTEXT RECOVERY — Re-injected after compaction]\n\n${recoveryParts.join('\n\n')}`,
          };
          messages.push(recoveryMessage);
          stateMessages.push(recoveryMessage);
        }

        const compactionTokensAfter = estimateContextTokens(messages);
        deps.economics?.updateBaseline(compactionTokensAfter);

        const compactionEvent = {
          type: 'context.compacted',
          tokensBefore: currentContextTokens,
          tokensAfter: compactionTokensAfter,
          recoveryInjected: recoveryParts.length > 0,
        };
        deps.emit(compactionEvent as any);

        deps.traceCollector?.record({
          type: 'context.compacted',
          data: {
            tokensBefore: currentContextTokens,
            tokensAfter: compactionTokensAfter,
            recoveryInjected: recoveryParts.length > 0,
          },
        });

        return { status: 'compacted', tokensBefore: currentContextTokens, tokensAfter: compactionTokensAfter };
      }
    } else if (compactionResult.status === 'hard_limit') {
      const reason = `Context hard limit reached (${Math.round(compactionResult.ratio * 100)}% of max tokens)`;
      deps.emit({ type: 'error', error: reason });
      return {
        status: 'hard_limit',
        result: { success: false, terminationReason: 'hard_context_limit', failureReason: reason },
      };
    }
  } else if (deps.economics) {
    // Fallback to simple compaction
    const currentUsage = deps.economics.getUsage();
    const budget = deps.economics.getBudget();
    const percentUsed = (currentUsage.tokens / budget.maxTokens) * 100;

    if (percentUsed >= 70) {
      deps.observability?.logger?.info('Proactive compaction triggered', {
        percentUsed: Math.round(percentUsed),
        currentTokens: currentUsage.tokens,
        maxTokens: budget.maxTokens,
      });
      compactToolOutputs(stateMessages);
      return { status: 'simple_compaction_triggered' };
    }
  }

  return { status: 'ok' };
}

/**
 * Narrow deps for context overflow guard.
 */
export interface OverflowGuardDeps {
  economics: {
    getBudget(): { maxTokens: number };
  } | null;
  emit(event: any): void;
}

export interface ToolResult {
  callId: string;
  result: string | unknown;
}

/**
 * Guard against mass tool results overflowing the context window.
 * Truncates tool results that would push total context beyond budget.
 * Mutates toolResults in-place.
 */
export function applyContextOverflowGuard(
  deps: OverflowGuardDeps,
  messages: Message[],
  toolResults: ToolResult[],
): number {
  if (!deps.economics || toolResults.length <= 10) return 0;

  const preAccumTokens = estimateContextTokens(messages);
  const budget = deps.economics.getBudget();
  const availableTokens = budget.maxTokens * EXECUTION_LOOP_DEFAULTS.CONTEXT_SAFETY_RATIO - preAccumTokens;

  const MAX_TOOL_OUTPUT_CHARS = EXECUTION_LOOP_DEFAULTS.MAX_TOOL_OUTPUT_CHARS;

  let totalResultTokens = 0;
  for (const r of toolResults) {
    const c = typeof r.result === 'string' ? r.result : stableStringify(r.result);
    totalResultTokens += estimateTokensFromCharCount(Math.min(c.length, MAX_TOOL_OUTPUT_CHARS));
  }

  if (totalResultTokens > availableTokens && availableTokens > 0) {
    log.warn('Tool results would exceed context budget — truncating batch', {
      resultCount: toolResults.length,
      estimatedTokens: totalResultTokens,
      availableTokens: Math.round(availableTokens),
    });
    let tokenBudget = availableTokens;
    for (let i = 0; i < toolResults.length; i++) {
      const c =
        typeof toolResults[i].result === 'string'
          ? (toolResults[i].result as string)
          : stableStringify(toolResults[i].result);
      const tokens = estimateTokensFromCharCount(Math.min(c.length, MAX_TOOL_OUTPUT_CHARS));
      if (tokens > tokenBudget) {
        const skipped = toolResults.length - i;
        for (let j = i; j < toolResults.length; j++) {
          toolResults[j] = {
            callId: toolResults[j].callId,
            result: `[Result omitted: context overflow guard — ${skipped} of ${toolResults.length} results skipped]`,
          };
        }
        deps.emit({
          type: 'safeguard.context_overflow_guard',
          estimatedTokens: totalResultTokens,
          maxTokens: budget.maxTokens,
          toolResultsSkipped: skipped,
        });
        return skipped;
      }
      tokenBudget -= tokens;
    }
  }

  return 0;
}

// =============================================================================
// MAIN EXECUTION LOOP
// =============================================================================

/**
 * Execute a task directly without planning.
 * This is the main ReAct loop extracted from ProductionAgent.executeDirectly().
 *
 * @param task - The user task to execute
 * @param ctx - Agent context (managers, config, state)
 * @param mutators - Functions to update mutable agent state
 */
export async function executeDirectly(
  task: string,
  messages: Message[],
  ctx: AgentContext,
  mutators: AgentContextMutators,
): Promise<ExecutionLoopResult> {
  // Reset economics for new task
  ctx.economics?.reset();
  const taskLeaseStaleMs =
    typeof ctx.config.resilience === 'object'
      ? (ctx.config.resilience.taskLeaseStaleMs ?? 5 * 60 * 1000)
      : 5 * 60 * 1000;

  // Recover orphaned in-progress tasks left behind by interrupted runs.
  if (ctx.taskManager) {
    const recovered = ctx.taskManager.reconcileStaleInProgress({
      staleAfterMs: taskLeaseStaleMs,
      reason: 'execution_loop_start',
    });
    if (recovered.reconciled > 0) {
      log.info('Recovered stale in-progress tasks at execution start', {
        recovered: recovered.reconciled,
      });
    }
  }

  // Reflection configuration
  const reflectionConfig = ctx.config.reflection;
  const reflectionEnabled = isFeatureEnabled(reflectionConfig);
  const autoReflect = reflectionEnabled && reflectionConfig.autoReflect;
  const maxReflectionAttempts = reflectionEnabled ? reflectionConfig.maxAttempts || 3 : 1;
  const confidenceThreshold = reflectionEnabled ? reflectionConfig.confidenceThreshold || 0.8 : 0.8;

  let reflectionAttempt = 0;
  let lastResponse = '';
  let incompleteActionRetries = 0;
  const requestedArtifact = extractRequestedArtifact(task);
  const executedToolNames = new Set<string>();
  let result: ExecutionLoopResult = {
    success: true,
    terminationReason: 'completed',
  };

  // Outer loop for reflection (if enabled)
  while (reflectionAttempt < maxReflectionAttempts) {
    reflectionAttempt++;

    // Agent loop - uses economics-based budget checking
    while (true) {
      ctx.state.iteration++;
      ctx.emit({ type: 'iteration.before', iteration: ctx.state.iteration });

      // Record iteration start for tracing
      ctx.traceCollector?.record({
        type: 'iteration.start',
        data: { iterationNumber: ctx.state.iteration },
      });

      // =======================================================================
      // CANCELLATION CHECK
      // =======================================================================
      if (ctx.cancellation?.isCancelled) {
        ctx.cancellation.token.throwIfCancellationRequested();
      }

      // =======================================================================
      // RESOURCE CHECK
      // =======================================================================
      if (ctx.resourceManager) {
        const resourceCheck = ctx.resourceManager.check();

        if (!resourceCheck.canContinue) {
          ctx.observability?.logger?.warn('Resource limit reached', {
            status: resourceCheck.status,
            message: resourceCheck.message,
          });
          const reason = resourceCheck.message || 'Resource limit exceeded';
          ctx.emit({ type: 'error', error: reason });
          result = {
            success: false,
            terminationReason: 'resource_limit',
            failureReason: reason,
          };
          break;
        }

        if (resourceCheck.status === 'warning' || resourceCheck.status === 'critical') {
          ctx.observability?.logger?.info(`Resource status: ${resourceCheck.status}`, {
            message: resourceCheck.message,
          });
        }
      }

      // =======================================================================
      // ECONOMICS CHECK (Token Budget) — delegated to checkIterationBudget()
      // =======================================================================
      let forceTextOnly = false;
      let budgetInjectedPrompt: string | undefined;
      let budgetAllowsTaskContinuation = true;

      const budgetResult = checkIterationBudget({
        economics: ctx.economics,
        getTotalIterations: () => ctx.getTotalIterations(),
        maxIterations: ctx.config.maxIterations,
        parentIterations: ctx.parentIterations,
        state: ctx.state,
        workLog: ctx.workLog,
        observability: ctx.observability,
        traceCollector: ctx.traceCollector,
        emit: (event: any) => ctx.emit(event),
      }, messages);

      if (budgetResult.action === 'recovery_success') {
        continue;
      } else if (budgetResult.action === 'stop') {
        result = budgetResult.result;
        break;
      } else {
        forceTextOnly = budgetResult.forceTextOnly;
        budgetInjectedPrompt = budgetResult.budgetInjectedPrompt;
        budgetAllowsTaskContinuation = budgetResult.budgetAllowsTaskContinuation;
      }

      // =======================================================================
      // GRACEFUL WRAPUP CHECK
      // =======================================================================
      if (ctx.wrapupRequested && !forceTextOnly) {
        forceTextOnly = true;
        budgetInjectedPrompt = TIMEOUT_WRAPUP_PROMPT;
        mutators.setWrapupRequested(false);
      }

      // =======================================================================
      // EXTERNAL CANCELLATION CHECK (deferred)
      // =======================================================================
      if (ctx.externalCancellationToken?.isCancellationRequested && !forceTextOnly) {
        ctx.externalCancellationToken.throwIfCancellationRequested();
      }

      // =======================================================================
      // INTELLIGENT LOOP DETECTION & NUDGE INJECTION
      // =======================================================================
      if (ctx.economics && budgetInjectedPrompt) {
        messages.push({
          role: 'user',
          content: budgetInjectedPrompt,
        });

        const loopState = ctx.economics.getLoopState();
        const phaseState = ctx.economics.getPhaseState();

        ctx.observability?.logger?.info('Loop detection - injecting guidance', {
          iteration: ctx.state.iteration,
          doomLoop: loopState.doomLoopDetected,
          phase: phaseState.phase,
          filesRead: phaseState.uniqueFilesRead,
          filesModified: phaseState.filesModified,
          shouldTransition: phaseState.shouldTransition,
          forceTextOnly,
        });
      }

      // =======================================================================
      // RECITATION INJECTION (Trick Q)
      // =======================================================================
      if (ctx.contextEngineering) {
        if (process.env.DEBUG_LLM) {
          if (process.env.DEBUG) log.debug('Recitation before', { messageCount: messages.length });
        }

        const enrichedMessages = ctx.contextEngineering.injectRecitation(
          messages as Array<{ role: 'system' | 'user' | 'assistant' | 'tool'; content: string }>,
          {
            goal: task,
            plan: ctx.state.plan
              ? {
                  description: ctx.state.plan.goal || task,
                  tasks: ctx.state.plan.tasks.map((t) => ({
                    id: t.id,
                    description: t.description,
                    status: t.status,
                  })),
                  currentTaskIndex: ctx.state.plan.tasks.findIndex(
                    (t) => t.status === 'in_progress',
                  ),
                }
              : undefined,
            activeFiles: ctx.economics?.getProgress().filesModified
              ? [`${ctx.economics.getProgress().filesModified} files modified`]
              : undefined,
            recentErrors: ctx.contextEngineering.getFailureInsights().slice(0, 2),
          },
        );

        if (process.env.DEBUG_LLM) {
          if (process.env.DEBUG)
            log.debug('Recitation after', {
              messageCount: enrichedMessages?.length ?? 'null/undefined',
            });
        }

        if (enrichedMessages && enrichedMessages !== messages && enrichedMessages.length > 0) {
          messages.length = 0;
          messages.push(...enrichedMessages);
        } else if (!enrichedMessages || enrichedMessages.length === 0) {
          log.warn('Recitation returned empty/null messages, keeping original');
        }

        const contextTokens = estimateContextTokens(messages);
        ctx.contextEngineering.updateRecitationFrequency(contextTokens);
      }

      // =======================================================================
      // FAILURE CONTEXT INJECTION (Trick S)
      // =======================================================================
      if (ctx.contextEngineering) {
        const failureContext = ctx.contextEngineering.getFailureContext(5);
        if (failureContext) {
          let lastUserIdx = -1;
          for (let i = messages.length - 1; i >= 0; i--) {
            if (messages[i].role === 'user') {
              lastUserIdx = i;
              break;
            }
          }
          if (lastUserIdx > 0) {
            messages.splice(lastUserIdx, 0, {
              role: 'system',
              content: failureContext,
            });
          }
        }
      }

      // =======================================================================
      // RESUME ORIENTATION — after compaction, nudge the agent to act, not re-summarize
      // =======================================================================
      const hasCompactionSummary = messages.some(
        (m) =>
          m.role === 'system' &&
          typeof m.content === 'string' &&
          m.content.includes('[Conversation Summary'),
      );
      if (hasCompactionSummary && ctx.state.iteration <= 2) {
        messages.push({
          role: 'user',
          content: `[System] Context was compacted. Review the summary above for what's been done and what remains. Do NOT repeat the summary — start working on the next task immediately using your tools.`,
        });
      }

      // =======================================================================
      // INJECTION BUDGET ANALYSIS (Phase 2 - monitoring mode)
      // =======================================================================
      if (ctx.injectionBudget) {
        const proposals: InjectionSlot[] = [];
        if (budgetInjectedPrompt) {
          proposals.push({
            name: 'budget_warning',
            priority: 0,
            maxTokens: 500,
            content: budgetInjectedPrompt,
          });
        }
        if (ctx.contextEngineering) {
          const failureCtx = ctx.contextEngineering.getFailureContext(5);
          if (failureCtx) {
            proposals.push({
              name: 'failure_context',
              priority: 2,
              maxTokens: 300,
              content: failureCtx,
            });
          }
        }
        if (proposals.length > 0) {
          const accepted = ctx.injectionBudget.allocate(proposals);
          const stats = ctx.injectionBudget.getLastStats();
          if (stats && stats.droppedNames.length > 0 && process.env.DEBUG) {
            log.debug('Injection budget dropped items', {
              droppedNames: stats.droppedNames.join(', '),
              proposedTokens: stats.proposedTokens,
              acceptedTokens: stats.acceptedTokens,
            });
          }
          if (stats && process.env.DEBUG_LLM) {
            log.debug('Injection budget summary', {
              iteration: ctx.state.iteration,
              accepted: accepted.length,
              total: proposals.length,
              tokens: stats.acceptedTokens,
            });
          }
        }
      }

      // =======================================================================
      // RESILIENT LLM CALL
      // =======================================================================
      const resilienceConfig =
        typeof ctx.config.resilience === 'object' ? ctx.config.resilience : {};
      const resilienceEnabled = isFeatureEnabled(ctx.config.resilience);
      const MAX_EMPTY_RETRIES = resilienceConfig.maxEmptyRetries ?? 2;
      const MAX_CONTINUATIONS = resilienceConfig.maxContinuations ?? 3;
      const AUTO_CONTINUE = resilienceConfig.autoContinue ?? true;
      const MIN_CONTENT_LENGTH = resilienceConfig.minContentLength ?? 1;
      const INCOMPLETE_ACTION_RECOVERY = resilienceConfig.incompleteActionRecovery ?? true;
      const MAX_INCOMPLETE_ACTION_RETRIES = resilienceConfig.maxIncompleteActionRetries ?? 2;
      const ENFORCE_REQUESTED_ARTIFACTS = resilienceConfig.enforceRequestedArtifacts ?? true;

      // PRE-FLIGHT BUDGET CHECK
      if (ctx.economics && !forceTextOnly) {
        const estimatedInputTokens = estimateContextTokens(messages);
        const currentUsage = ctx.economics.getUsage();
        const budget = ctx.economics.getBudget();
        const isStrictEnforcement = (budget.enforcementMode ?? 'strict') === 'strict';
        // Use proportional output estimate: 10% of remaining budget, capped at 4096, floored at 512.
        // The old hardcoded 4096 caused premature wrapup for subagents with smaller budgets.
        const remainingTokens = budget.maxTokens - currentUsage.tokens - estimatedInputTokens;
        const estimatedOutputTokens = Math.min(
          4096,
          Math.max(512, Math.floor(remainingTokens * 0.1)),
        );
        const projectedTotal = currentUsage.tokens + estimatedInputTokens + estimatedOutputTokens;

        if (projectedTotal > budget.maxTokens) {
          ctx.observability?.logger?.warn('Pre-flight budget check: projected overshoot', {
            currentTokens: currentUsage.tokens,
            estimatedInput: estimatedInputTokens,
            projectedTotal,
            maxTokens: budget.maxTokens,
            enforcementMode: budget.enforcementMode ?? 'strict',
          });

          // Only force text-only in strict mode. In doomloop_only mode,
          // the pre-flight check warns but does not kill the agent.
          // NEVER force text-only on the first iteration — an agent that hasn't
          // made a single tool call yet should always get at least one chance.
          // This prevents swarm workers from being killed before they can work.
          if (isStrictEnforcement && ctx.state.iteration > 1) {
            if (!budgetInjectedPrompt) {
              messages.push({
                role: 'user',
                content:
                  '[System] BUDGET CRITICAL: This is your LAST response. Summarize findings concisely and stop. Do NOT call tools.',
              });
              ctx.state.messages.push({
                role: 'user',
                content:
                  '[System] BUDGET CRITICAL: This is your LAST response. Summarize findings concisely and stop. Do NOT call tools.',
              });
            }
            forceTextOnly = true;
          }
        }
      }

      // EARLY EXIT: When forceTextOnly is set but task continuation is allowed,
      // skip the expensive LLM call (whose tool calls would be discarded) and
      // go directly to the task continuation gate. Only allowed once per
      // forceTextOnly episode to prevent tight loops.
      if (
        forceTextOnly &&
        budgetAllowsTaskContinuation &&
        ctx.taskManager &&
        !(ctx.state as { _lastSkippedLLMIteration?: number })._lastSkippedLLMIteration
      ) {
        const availableTasks = ctx.taskManager.getAvailableTasks();
        if (availableTasks.length > 0) {
          log.info(
            'Skipping LLM call — forceTextOnly with tasks available, going to task continuation',
            {
              availableTasks: availableTasks.length,
              iteration: ctx.state.iteration,
            },
          );
          // Mark that we skipped so we don't skip again on the next iteration
          (ctx.state as { _lastSkippedLLMIteration?: number })._lastSkippedLLMIteration =
            ctx.state.iteration;
          // Reset forceTextOnly for the next iteration so the task can run normally
          forceTextOnly = false;
          const nextTask = availableTasks[0];
          ctx.taskManager.claim(nextTask.id, ctx.agentId);
          const taskPrompt: Message = {
            role: 'user',
            content: `[System] Budget warning noted. Continuing with next task:\n\n**Task ${nextTask.id}: ${nextTask.subject}**\n${nextTask.description}\n\nStart working on this task now using your tools.`,
          };
          messages.push(taskPrompt);
          ctx.state.messages.push(taskPrompt);
          ctx.emit({
            type: 'iteration.after',
            iteration: ctx.state.iteration,
            hadToolCalls: false,
            completionCandidate: false,
          });
          continue; // Re-enter main loop for next task without wasting an LLM call
        }
      }

      let response = await callLLM(messages, ctx);
      // Clear the LLM-skip guard now that we've made a real LLM call
      delete (ctx.state as { _lastSkippedLLMIteration?: number })._lastSkippedLLMIteration;
      let emptyRetries = 0;
      let continuations = 0;

      // Phase 1: Handle empty responses with retry
      while (resilienceEnabled && emptyRetries < MAX_EMPTY_RETRIES) {
        const hasContent = response.content && response.content.length >= MIN_CONTENT_LENGTH;
        const hasToolCalls = response.toolCalls && response.toolCalls.length > 0;
        const hasThinking = response.thinking && response.thinking.length > 0;

        if (hasContent || hasToolCalls) {
          if (emptyRetries > 0) {
            ctx.emit({
              type: 'resilience.recovered',
              reason: 'empty_response',
              attempts: emptyRetries,
            });
            ctx.observability?.logger?.info('Recovered from empty response', {
              retries: emptyRetries,
            });
          }
          break;
        }

        if (hasThinking && !hasContent && !hasToolCalls) {
          if (emptyRetries === 0) {
            emptyRetries++;
            ctx.emit({
              type: 'resilience.retry',
              reason: 'thinking_only_response',
              attempt: emptyRetries,
              maxAttempts: MAX_EMPTY_RETRIES,
            });
            ctx.state.metrics.retryCount = (ctx.state.metrics.retryCount ?? 0) + 1;
            ctx.observability?.logger?.warn(
              'Thinking-only response (no visible content), nudging',
              {
                thinkingLength: response.thinking!.length,
              },
            );

            const thinkingNudge: Message = {
              role: 'user',
              content:
                '[System: You produced reasoning but no visible response. Please provide your answer based on your analysis.]',
            };
            messages.push(thinkingNudge);
            ctx.state.messages.push(thinkingNudge);
            response = await callLLM(messages, ctx);
            continue;
          }
          ctx.observability?.logger?.info('Accepting thinking as content after nudge failed', {
            thinkingLength: response.thinking!.length,
          });
          response = { ...response, content: response.thinking! };
          break;
        }

        emptyRetries++;
        ctx.emit({
          type: 'resilience.retry',
          reason: 'empty_response',
          attempt: emptyRetries,
          maxAttempts: MAX_EMPTY_RETRIES,
        });
        ctx.state.metrics.retryCount = (ctx.state.metrics.retryCount ?? 0) + 1;
        ctx.observability?.logger?.warn('Empty LLM response, retrying', {
          attempt: emptyRetries,
          maxAttempts: MAX_EMPTY_RETRIES,
        });

        const nudgeMessage: Message = {
          role: 'user',
          content:
            '[System: Your previous response was empty. Please provide a response or use a tool.]',
        };
        messages.push(nudgeMessage);
        ctx.state.messages.push(nudgeMessage);

        response = await callLLM(messages, ctx);
      }

      // Phase 2: Handle max_tokens truncation with continuation
      if (
        resilienceEnabled &&
        AUTO_CONTINUE &&
        response.stopReason === 'max_tokens' &&
        !response.toolCalls?.length
      ) {
        let accumulatedContent = response.content || '';

        while (continuations < MAX_CONTINUATIONS && response.stopReason === 'max_tokens') {
          continuations++;
          ctx.emit({
            type: 'resilience.continue',
            reason: 'max_tokens',
            continuation: continuations,
            maxContinuations: MAX_CONTINUATIONS,
            accumulatedLength: accumulatedContent.length,
          });
          ctx.observability?.logger?.info('Response truncated at max_tokens, continuing', {
            continuation: continuations,
            accumulatedLength: accumulatedContent.length,
          });

          const continuationMessage: Message = {
            role: 'assistant',
            content: accumulatedContent,
          };
          const continueRequest: Message = {
            role: 'user',
            content:
              '[System: Please continue from where you left off. Do not repeat what you already said.]',
          };
          messages.push(continuationMessage, continueRequest);
          ctx.state.messages.push(continuationMessage, continueRequest);

          response = await callLLM(messages, ctx);

          if (response.content) {
            accumulatedContent += response.content;
          }
        }

        if (continuations > 0) {
          response = { ...response, content: accumulatedContent };
          ctx.emit({
            type: 'resilience.completed',
            reason: 'max_tokens_continuation',
            continuations,
            finalLength: accumulatedContent.length,
          });
        }
      }

      // Phase 2b: Handle truncated tool calls
      if (resilienceEnabled && response.stopReason === 'max_tokens' && response.toolCalls?.length) {
        ctx.emit({
          type: 'resilience.truncated_tool_call',
          toolNames: response.toolCalls.map((tc) => tc.name),
        });
        ctx.observability?.logger?.warn('Tool call truncated at max_tokens', {
          toolNames: response.toolCalls.map((tc) => tc.name),
          outputTokens: response.usage?.outputTokens,
        });

        const truncatedResponse = response;
        response = { ...response, toolCalls: undefined };
        const recoveryMessage: Message = {
          role: 'user',
          content:
            '[System: Your previous tool call was truncated because the output exceeded the token limit. ' +
            'The tool call arguments were cut off and could not be parsed. ' +
            'Please retry with a smaller approach: for write_file, break the content into smaller chunks ' +
            'or use edit_file for targeted changes instead of rewriting entire files.]',
        };
        messages.push({ role: 'assistant', content: truncatedResponse.content || '' });
        messages.push(recoveryMessage);
        ctx.state.messages.push({ role: 'assistant', content: truncatedResponse.content || '' });
        ctx.state.messages.push(recoveryMessage);

        response = await callLLM(messages, ctx);
      }

      // Record LLM usage for economics
      if (ctx.economics && response.usage) {
        ctx.economics.recordLLMUsage(
          response.usage.inputTokens,
          response.usage.outputTokens,
          ctx.config.model,
          response.usage.cost,
          response.usage.cacheReadTokens,
        );

        // POST-LLM BUDGET CHECK
        if (!forceTextOnly) {
          const postCheck = ctx.economics.checkBudget();
          if (!postCheck.canContinue) {
            ctx.observability?.logger?.warn(
              'Budget exceeded after LLM call, skipping tool execution',
              {
                reason: postCheck.reason,
              },
            );
            forceTextOnly = true;
          }
        }
      }

      // Add assistant message
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.content,
        toolCalls: response.toolCalls,
        ...(response.thinking ? { metadata: { thinking: response.thinking } } : {}),
      };
      messages.push(assistantMessage);
      ctx.state.messages.push(assistantMessage);
      lastResponse = response.content || (response.thinking ? response.thinking : '');

      // Plan mode: capture exploration findings
      if (
        ctx.modeManager.getMode() === 'plan' &&
        response.content &&
        response.content.length > 50
      ) {
        const hasReadOnlyTools = response.toolCalls?.every((tc) =>
          ['read_file', 'list_files', 'glob', 'grep', 'search', 'mcp_'].some(
            (prefix) => tc.name.startsWith(prefix) || tc.name === prefix,
          ),
        );
        if (
          hasReadOnlyTools &&
          !response.content.match(/^(Let me|I'll|I will|I need to|First,)/i)
        ) {
          ctx.pendingPlanManager.appendExplorationFinding(response.content.slice(0, 1000));
        }
      }

      // Check for tool calls
      const hasToolCalls = response.toolCalls && response.toolCalls.length > 0;
      if (!hasToolCalls || forceTextOnly) {
        if (forceTextOnly && hasToolCalls) {
          ctx.observability?.logger?.info(
            'Ignoring tool calls due to forceTextOnly (max steps reached)',
            {
              toolCallCount: response.toolCalls?.length,
              iteration: ctx.state.iteration,
            },
          );
        }

        // Track text-only turns for summary-loop detection (skip forceTextOnly — that's expected)
        if (!hasToolCalls && !forceTextOnly) {
          ctx.economics?.recordTextOnlyTurn();
        }

        const incompleteAction = detectIncompleteActionResponse(response.content || '');
        const missingRequiredArtifact = ENFORCE_REQUESTED_ARTIFACTS
          ? isRequestedArtifactMissing(requestedArtifact, executedToolNames)
          : false;
        const shouldRecoverIncompleteAction =
          resilienceEnabled &&
          INCOMPLETE_ACTION_RECOVERY &&
          !forceTextOnly &&
          (incompleteAction || missingRequiredArtifact);

        if (shouldRecoverIncompleteAction) {
          ctx.emit({
            type: 'completion.before',
            reason:
              missingRequiredArtifact && requestedArtifact
                ? `missing_requested_artifact:${requestedArtifact}`
                : 'future_intent_without_action',
            attempt: incompleteActionRetries + 1,
            maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
          });
          if (incompleteActionRetries < MAX_INCOMPLETE_ACTION_RETRIES) {
            incompleteActionRetries++;
            const reason =
              missingRequiredArtifact && requestedArtifact
                ? `missing_requested_artifact:${requestedArtifact}`
                : 'future_intent_without_action';
            ctx.emit({
              type: 'recovery.before',
              reason,
              attempt: incompleteActionRetries,
              maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
            });
            ctx.emit({
              type: 'resilience.incomplete_action_detected',
              reason,
              attempt: incompleteActionRetries,
              maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
              requiresArtifact: missingRequiredArtifact,
            });
            ctx.observability?.logger?.warn('Incomplete action detected, retrying with nudge', {
              reason,
              attempt: incompleteActionRetries,
              maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
            });

            const nudgeMessage: Message = {
              role: 'user',
              content:
                missingRequiredArtifact && requestedArtifact
                  ? `[System: You said you would complete the next action, but no tool call was made. The task requires creating or updating "${requestedArtifact}". Execute the required tool now, or explicitly explain why it cannot be produced.]`
                  : '[System: You described a next action but did not execute it. If work remains, call the required tool now. If the task is complete, provide a final answer with no pending action language.]',
            };
            messages.push(nudgeMessage);
            ctx.state.messages.push(nudgeMessage);
            ctx.emit({
              type: 'iteration.after',
              iteration: ctx.state.iteration,
              hadToolCalls: false,
              completionCandidate: false,
            });
            continue;
          }

          const failureReason =
            missingRequiredArtifact && requestedArtifact
              ? `incomplete_action_missing_artifact:${requestedArtifact}`
              : 'incomplete_action_unresolved';
          ctx.emit({
            type: 'resilience.incomplete_action_failed',
            reason: failureReason,
            attempts: incompleteActionRetries,
            maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
          });
          ctx.emit({
            type: 'recovery.after',
            reason: failureReason,
            recovered: false,
            attempts: incompleteActionRetries,
          });
          const reason = `LLM failed to complete requested action after ${incompleteActionRetries} retries (${failureReason})`;
          result = {
            success: false,
            terminationReason: 'incomplete_action',
            failureReason: reason,
          };
          ctx.emit({
            type: 'completion.after',
            success: false,
            reason: 'incomplete_action',
            details: reason,
          });
          throw new Error(reason);
        }

        if (incompleteActionRetries > 0) {
          ctx.emit({
            type: 'resilience.incomplete_action_recovered',
            reason: 'incomplete_action',
            attempts: incompleteActionRetries,
          });
          ctx.emit({
            type: 'recovery.after',
            reason: 'incomplete_action',
            recovered: true,
            attempts: incompleteActionRetries,
          });
          incompleteActionRetries = 0;
        }

        // TypeScript compilation gate — block completion if TS files edited and errors exist
        if (
          ctx.typeCheckerState?.tsconfigDir &&
          !forceTextOnly &&
          (ctx.typeCheckerState.tsEditsSinceLastCheck > 0 || !ctx.typeCheckerState.hasRunOnce)
        ) {
          const tscResult = await runTypeCheck(ctx.typeCheckerState.tsconfigDir);
          ctx.typeCheckerState.tsEditsSinceLastCheck = 0;
          ctx.typeCheckerState.lastResult = tscResult;
          ctx.typeCheckerState.hasRunOnce = true;
          ctx.verificationGate?.recordCompilationResult(tscResult.success, tscResult.errorCount);
          ctx.emit({
            type: 'diagnostics.tsc-check',
            errorCount: tscResult.errorCount,
            duration: tscResult.duration,
            trigger: 'completion',
          });

          if (!tscResult.success) {
            const vState = ctx.verificationGate?.getState();
            const maxCompNudges = 8;
            if (!vState || (vState.compilationNudgeCount ?? 0) < maxCompNudges) {
              const nudge = formatTypeCheckNudge(tscResult);
              const nudgeMessage: Message = { role: 'user', content: nudge };
              messages.push(nudgeMessage);
              ctx.state.messages.push(nudgeMessage);
              ctx.verificationGate?.incrementCompilationNudge();
              log.info('Compilation gate blocked completion', {
                count: tscResult.errorCount,
                nudgeCount: ctx.verificationGate?.getState().compilationNudgeCount,
              });
              ctx.emit({
                type: 'iteration.after',
                iteration: ctx.state.iteration,
                hadToolCalls: false,
                completionCandidate: false,
              });
              continue; // Re-enter main loop — agent must fix errors
            }
            // If exceeded max nudges, fall through to verification gate (which will forceAllow)
          }
        }

        // Verification gate
        if (ctx.verificationGate && !forceTextOnly) {
          const vResult = ctx.verificationGate.check();
          if (!vResult.satisfied && !vResult.forceAllow && vResult.nudge) {
            const nudgeMessage: Message = {
              role: 'user',
              content: vResult.nudge,
            };
            messages.push(nudgeMessage);
            ctx.state.messages.push(nudgeMessage);
            ctx.observability?.logger?.info('Verification gate nudge', {
              missing: vResult.missing,
              nudgeCount: ctx.verificationGate.getState().nudgeCount,
            });
            ctx.emit({
              type: 'iteration.after',
              iteration: ctx.state.iteration,
              hadToolCalls: false,
              completionCandidate: false,
            });
            continue;
          }
        }

        // No tool calls — agent is done
        compactToolOutputs(ctx.state.messages);

        // Plan mode: capture exploration summary
        if (ctx.modeManager.getMode() === 'plan' && ctx.pendingPlanManager.hasPendingPlan()) {
          const explorationContent = response.content || '';
          if (explorationContent.length > 0) {
            ctx.pendingPlanManager.setExplorationSummary(explorationContent);
          }
        }

        // Final validation
        if (!response.content || response.content.length === 0) {
          ctx.observability?.logger?.error('Agent finished with empty response after all retries', {
            emptyRetries,
            continuations,
            iteration: ctx.state.iteration,
          });
          ctx.emit({
            type: 'resilience.failed',
            reason: 'empty_final_response',
            emptyRetries,
            continuations,
          });
        }
        ctx.emit({
          type: 'completion.after',
          success: true,
          reason: 'completed',
        });
        ctx.emit({
          type: 'iteration.after',
          iteration: ctx.state.iteration,
          hadToolCalls: false,
          completionCandidate: true,
        });

        // Record iteration end for tracing (no tool calls case)
        ctx.traceCollector?.record({
          type: 'iteration.end',
          data: { iterationNumber: ctx.state.iteration },
        });

        // =====================================================================
        // TASK EXECUTION LOOP — pick up next available task before exiting
        // =====================================================================
        if (ctx.taskManager) {
          // Reconcile stale in-progress tasks before deciding there is no more work.
          ctx.taskManager.reconcileStaleInProgress({
            staleAfterMs: taskLeaseStaleMs,
            reason: 'completion_gate',
          });
          const pendingWithOwner = getPendingWithOwnerCount(ctx);
          const availableTasks = ctx.taskManager.getAvailableTasks();
          if ((!forceTextOnly || budgetAllowsTaskContinuation) && availableTasks.length > 0) {
            const nextTask = availableTasks[0];
            ctx.taskManager.claim(nextTask.id, ctx.agentId);
            log.info('Picking up next task from task list', {
              taskId: nextTask.id,
              subject: nextTask.subject,
            });
            const taskPrompt: Message = {
              role: 'user',
              content: `[System] Previous work is done. Now work on the next task:\n\n**Task ${nextTask.id}: ${nextTask.subject}**\n${nextTask.description}\n\nStart working on this task now using your tools.`,
            };
            messages.push(taskPrompt);
            ctx.state.messages.push(taskPrompt);
            ctx.emit({
              type: 'iteration.after',
              iteration: ctx.state.iteration,
              hadToolCalls: false,
              completionCandidate: false,
            });
            continue; // Re-enter the main loop for the next task
          }
          const openTasks = getOpenTaskSummary(ctx);
          if (openTasks && (openTasks.inProgress > 0 || openTasks.pending > 0)) {
            if (forceTextOnly) {
              const reason = `Task continuation suppressed by forceTextOnly mode: ${openTasks.pending} pending, ${openTasks.inProgress} in_progress`;
              ctx.emit({
                type: 'completion.blocked',
                reasons: [reason],
                openTasks,
                diagnostics: {
                  forceTextOnly: true,
                  availableTasks: availableTasks.length,
                  pendingWithOwner,
                },
              });
              result = {
                success: false,
                terminationReason: 'budget_limit',
                failureReason: reason,
                openTasks,
              };
              break;
            }
            const reasons = [
              `Open tasks remain: ${openTasks.pending} pending, ${openTasks.inProgress} in_progress`,
              openTasks.blocked > 0
                ? `${openTasks.blocked} pending tasks are currently blocked`
                : '',
            ].filter(Boolean);
            ctx.emit({
              type: 'completion.blocked',
              reasons,
              openTasks,
              diagnostics: {
                forceTextOnly: false,
                availableTasks: availableTasks.length,
                pendingWithOwner,
              },
            });
            result = {
              success: false,
              terminationReason: 'open_tasks',
              failureReason: reasons.join('; '),
              openTasks,
            };
          }
        }

        break;
      }

      // Execute tool calls
      const toolCalls = response.toolCalls!;

      // SAFEGUARD: Hard cap on tool calls per LLM response
      const maxToolCallsPerResponse =
        ctx.economics?.getBudget()?.tuning?.maxToolCallsPerResponse ?? 25;
      if (toolCalls.length > maxToolCallsPerResponse) {
        log.warn('Tool call explosion detected — capping', {
          requested: toolCalls.length,
          cap: maxToolCallsPerResponse,
          toolNames: [...new Set(toolCalls.map((tc) => tc.name))],
        });
        ctx.emit({
          type: 'safeguard.tool_call_cap',
          requested: toolCalls.length,
          cap: maxToolCallsPerResponse,
          droppedCount: toolCalls.length - maxToolCallsPerResponse,
        });
        toolCalls.splice(maxToolCallsPerResponse);
      }

      const toolResults = await executeToolCalls(toolCalls, ctx);
      ctx.emit({
        type: 'iteration.after',
        iteration: ctx.state.iteration,
        hadToolCalls: true,
        completionCandidate: false,
      });

      // Record tool calls for economics/progress tracking + work log
      for (let i = 0; i < toolCalls.length; i++) {
        const toolCall = toolCalls[i];
        const result = toolResults[i];
        executedToolNames.add(toolCall.name);
        ctx.economics?.recordToolCall(toolCall.name, toolCall.arguments, result?.result);
        ctx.stateMachine?.recordToolCall(
          toolCall.name,
          toolCall.arguments as Record<string, unknown>,
          result?.result,
        );
        // Record in work log
        const toolOutput =
          result?.result && typeof result.result === 'object' && 'output' in (result.result as any)
            ? String((result.result as any).output)
            : typeof result?.result === 'string'
              ? result.result
              : undefined;
        ctx.workLog?.recordToolExecution(toolCall.name, toolCall.arguments, toolOutput);
        // Record in verification gate
        if (ctx.verificationGate) {
          if (toolCall.name === 'bash') {
            const toolRes = result?.result as any;
            const output =
              toolRes && typeof toolRes === 'object' && 'output' in toolRes
                ? String(toolRes.output)
                : typeof toolRes === 'string'
                  ? toolRes
                  : '';
            const exitCode =
              toolRes && typeof toolRes === 'object' && toolRes.metadata
                ? ((toolRes.metadata as any).exitCode ?? null)
                : null;
            ctx.verificationGate.recordBashExecution(
              String(toolCall.arguments.command || ''),
              output,
              exitCode,
            );
          }
          if (['write_file', 'edit_file'].includes(toolCall.name)) {
            ctx.verificationGate.recordFileChange();
          }
        }

        // Phase 5.1: Post-edit syntax validation + AST cache invalidation
        if (
          ['write_file', 'edit_file'].includes(toolCall.name) &&
          result?.result &&
          (result.result as any).success
        ) {
          const filePath = String(toolCall.arguments.path || '');
          if (filePath) {
            // Invalidate stale AST cache entry so next analysis/validation reparses
            invalidateAST(filePath);
            try {
              const content =
                toolCall.name === 'write_file'
                  ? String(toolCall.arguments.content || '')
                  : await fs.promises.readFile(filePath, 'utf-8');
              // Update codebase context first — fullReparse caches the AST tree,
              // so validateSyntax below will use the cached tree (no double-parse)
              if (ctx.codebaseContext) {
                try {
                  await ctx.codebaseContext.updateFile(filePath, content);
                } catch {
                  /* non-blocking */
                }
              }
              const validation = validateSyntax(content, filePath);
              if (!validation.valid && result.result && typeof result.result === 'object') {
                const errorSummary = validation.errors
                  .slice(0, 3)
                  .map((e) => `  L${e.line}:${e.column}: ${e.message}`)
                  .join('\n');
                (result.result as any).output +=
                  `\n\n⚠ Syntax validation warning:\n${errorSummary}`;
                // Emit diagnostic events for each syntax error
                for (const err of validation.errors.slice(0, 5)) {
                  ctx.emit({
                    type: 'diagnostics.syntax-error',
                    file: filePath,
                    line: err.line,
                    message: err.message,
                  });
                }
              }
            } catch {
              // Validation failure is non-blocking
            }

            // Track .ts/.tsx edits for periodic type checking
            if (ctx.typeCheckerState?.tsconfigDir && /\.(ts|tsx)$/.test(filePath)) {
              ctx.typeCheckerState.tsEditsSinceLastCheck++;
            }
          }
        }
      }

      // Add tool results to messages (with truncation and proactive budget management)
      const MAX_TOOL_OUTPUT_CHARS = EXECUTION_LOOP_DEFAULTS.MAX_TOOL_OUTPUT_CHARS;

      // PROACTIVE BUDGET CHECK — delegate to extracted function
      const compactionStatus = await handleAutoCompaction(
        {
          autoCompactionManager: ctx.autoCompactionManager ?? null,
          compactionPending: ctx.compactionPending,
          economics: ctx.economics,
          workLog: ctx.workLog,
          store: ctx.store,
          learningStore: ctx.learningStore,
          observability: ctx.observability,
          traceCollector: ctx.traceCollector,
          emit: (event: any) => ctx.emit(event),
        },
        messages,
        ctx.state.messages,
        (v) => mutators.setCompactionPending(v),
      );

      if (compactionStatus.status === 'hard_limit') {
        result = compactionStatus.result;
        break;
      }

      // SAFEGUARD: Aggregate context guard — delegate to extracted function
      applyContextOverflowGuard(
        { economics: ctx.economics, emit: (event: any) => ctx.emit(event) },
        messages,
        toolResults,
      );

      const toolCallNameById = new Map(toolCalls.map((tc) => [tc.id, tc.name]));

      for (const result of toolResults) {
        let content =
          typeof result.result === 'string'
            ? result.result
            : ctx.contextEngineering
              ? ctx.contextEngineering.serialize(result.result)
              : stableStringify(result.result);
        const sourceToolName = toolCallNameById.get(result.callId);
        const isExpensiveResult =
          sourceToolName === 'spawn_agent' || sourceToolName === 'spawn_agents_parallel';

        const effectiveMaxChars = isExpensiveResult
          ? MAX_TOOL_OUTPUT_CHARS * 2
          : MAX_TOOL_OUTPUT_CHARS;
        if (content.length > effectiveMaxChars) {
          content =
            content.slice(0, effectiveMaxChars) +
            `\n\n... [truncated ${content.length - effectiveMaxChars} chars]`;
        }

        // Check if adding this result would exceed budget
        if (ctx.economics) {
          const estimatedNewTokens = estimateTokenCount(content);
          const currentCtxTokens = estimateContextTokens(messages);
          const budget = ctx.economics.getBudget();

          if (currentCtxTokens + estimatedNewTokens > budget.maxTokens * EXECUTION_LOOP_DEFAULTS.PER_RESULT_BUDGET_RATIO) {
            ctx.observability?.logger?.warn('Skipping tool result to stay within budget', {
              toolCallId: result.callId,
              estimatedTokens: estimatedNewTokens,
              currentContext: currentCtxTokens,
              limit: budget.maxTokens,
            });

            const toolMessage: Message = {
              role: 'tool',
              content: `[Result omitted to stay within token budget. Original size: ${content.length} chars]`,
              toolCallId: result.callId,
            };
            messages.push(toolMessage);
            ctx.state.messages.push(toolMessage);
            continue;
          }
        }

        const toolMessage: Message = {
          role: 'tool',
          content,
          toolCallId: result.callId,
          ...(isExpensiveResult
            ? {
                metadata: {
                  preserveFromCompaction: true,
                  costToRegenerate: 'high',
                  source: sourceToolName,
                },
              }
            : {}),
        };
        messages.push(toolMessage);
        ctx.state.messages.push(toolMessage);
      }

      // Periodic TypeScript compilation check (every 5 TS edits)
      const TYPE_CHECK_EDIT_THRESHOLD = EXECUTION_LOOP_DEFAULTS.TYPE_CHECK_EDIT_THRESHOLD;
      if (
        ctx.typeCheckerState?.tsconfigDir &&
        ctx.typeCheckerState.tsEditsSinceLastCheck >= TYPE_CHECK_EDIT_THRESHOLD &&
        !forceTextOnly
      ) {
        const tscResult = await runTypeCheck(ctx.typeCheckerState.tsconfigDir);
        ctx.typeCheckerState.tsEditsSinceLastCheck = 0;
        ctx.typeCheckerState.lastResult = tscResult;
        ctx.typeCheckerState.hasRunOnce = true;
        ctx.verificationGate?.recordCompilationResult(tscResult.success, tscResult.errorCount);
        ctx.emit({
          type: 'diagnostics.tsc-check',
          errorCount: tscResult.errorCount,
          duration: tscResult.duration,
          trigger: 'periodic',
        });

        if (!tscResult.success) {
          const nudge = formatTypeCheckNudge(tscResult);
          const infoMsg: Message = { role: 'user', content: nudge };
          messages.push(infoMsg);
          ctx.state.messages.push(infoMsg);
          log.info('Periodic tsc check found errors', { count: tscResult.errorCount });
        }
      }

      // Emit context health
      const currentTokenEstimate = estimateContextTokens(messages);
      const contextLimit = ctx.getMaxContextTokens();
      const percentUsed = Math.round((currentTokenEstimate / contextLimit) * 100);
      const avgTokensPerExchange = currentTokenEstimate / Math.max(1, ctx.state.iteration);
      const remainingTokens = contextLimit - currentTokenEstimate;
      const estimatedExchanges = Math.floor(remainingTokens / Math.max(1, avgTokensPerExchange));

      ctx.emit({
        type: 'context.health',
        currentTokens: currentTokenEstimate,
        maxTokens: contextLimit,
        estimatedExchanges,
        percentUsed,
      });

      // Record iteration end
      ctx.traceCollector?.record({
        type: 'iteration.end',
        data: { iterationNumber: ctx.state.iteration },
      });
    }

    // =======================================================================
    // REFLECTION (Lesson 16)
    // =======================================================================
    if (!result.success) {
      break;
    }

    if (autoReflect && ctx.planning && reflectionAttempt < maxReflectionAttempts) {
      ctx.emit({ type: 'reflection', attempt: reflectionAttempt, satisfied: false });

      const reflectionResult = await ctx.planning.reflect(task, lastResponse, ctx.provider);
      ctx.state.metrics.reflectionAttempts = reflectionAttempt;

      if (reflectionResult.satisfied && reflectionResult.confidence >= confidenceThreshold) {
        ctx.emit({ type: 'reflection', attempt: reflectionAttempt, satisfied: true });
        break;
      }

      const feedbackMessage: Message = {
        role: 'user',
        content: `[Reflection feedback]\nThe previous output needs improvement:\n- Critique: ${reflectionResult.critique}\n- Suggestions: ${reflectionResult.suggestions.join(', ')}\n\nPlease improve the output.`,
      };
      messages.push(feedbackMessage);
      ctx.state.messages.push(feedbackMessage);

      ctx.observability?.logger?.info('Reflection not satisfied, retrying', {
        attempt: reflectionAttempt,
        confidence: reflectionResult.confidence,
        critique: reflectionResult.critique,
      });
    } else {
      break;
    }
  }

  // Store conversation in memory
  ctx.memory?.storeConversation(ctx.state.messages);
  // Memory stats update (hook point)
  ctx.memory?.getStats();
  return result;
}
