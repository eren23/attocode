/**
 * Execution Loop Module (Phase 2.1)
 *
 * Extracted from ProductionAgent.executeDirectly().
 * Contains the main ReAct while(true) loop: cancellation checks, resource checks,
 * economics/budget checks with compaction recovery, loop detection, context
 * engineering injection (recitation, failure evidence), LLM call dispatch,
 * resilience handling, tool execution, and compaction.
 */

import type {
  Message,
} from '../types.js';

import { isFeatureEnabled } from '../defaults.js';

import type { AgentContext, AgentContextMutators } from './types.js';
import { callLLM } from './response-handler.js';
import { executeToolCalls } from './tool-executor.js';

import {
  TIMEOUT_WRAPUP_PROMPT,
  stableStringify,
  type InjectionSlot,
} from '../integrations/index.js';

import { createComponentLogger } from '../integrations/logger.js';
import { validateSyntax } from '../integrations/edit-validator.js';
import * as fs from 'node:fs';

const log = createComponentLogger('ExecutionLoop');

// =============================================================================
// HELPER FUNCTIONS (extracted from ProductionAgent private methods)
// =============================================================================

/**
 * Estimate total tokens in a message array.
 * Uses ~4 chars per token heuristic for fast estimation.
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
  return Math.ceil(totalChars / 4);
}

/**
 * Compact tool outputs to save context.
 */
export function compactToolOutputs(messages: Message[]): void {
  const COMPACT_PREVIEW_LENGTH = 200;
  const MAX_PRESERVED_EXPENSIVE_RESULTS = 6;
  let compactedCount = 0;
  let savedChars = 0;

  const preservedExpensiveIndexes = messages
    .map((msg, index) => ({ msg, index }))
    .filter(({ msg }) =>
      msg.role === 'tool' && msg.metadata?.preserveFromCompaction === true
    )
    .map(({ index }) => index);
  const preserveSet = new Set(
    preservedExpensiveIndexes.slice(-MAX_PRESERVED_EXPENSIVE_RESULTS)
  );

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
    log.debug('Compacted tool outputs', { compactedCount, savedTokens: Math.round(savedChars / 4) });
  }
}

/**
 * Extract a requested markdown artifact filename from a task prompt.
 */
export function extractRequestedArtifact(task: string): string | null {
  const markdownArtifactMatch = task.match(/(?:write|save|create)[^.\n]{0,120}\b([A-Za-z0-9._/-]+\.md)\b/i);
  return markdownArtifactMatch?.[1] ?? null;
}

/**
 * Check whether a requested artifact appears to be missing.
 */
export function isRequestedArtifactMissing(
  requestedArtifact: string | null,
  executedToolNames: Set<string>
): boolean {
  if (!requestedArtifact) return false;
  const artifactWriteTools = ['write_file', 'edit_file', 'apply_patch', 'append_file'];
  return !artifactWriteTools.some(toolName => executedToolNames.has(toolName));
}

/**
 * Detect "future-intent" responses that imply the model has not completed work.
 */
export function detectIncompleteActionResponse(content: string): boolean {
  const trimmed = content.trim();
  if (!trimmed) return false;

  const lower = trimmed.toLowerCase();
  const futureIntentPatterns: RegExp[] = [
    /^(now|next|then)\s+(i\s+will|i'll|let me)\b/,
    /^i\s+(will|am going to|can)\b/,
    /^(let me|i'll|i will)\s+(create|write|save|do|make|generate|start)\b/,
    /^(now|next|then)\s+i(?:'ll| will)\b/,
  ];
  const completionSignals = /\b(done|completed|finished|here is|created|saved|wrote)\b/;

  return futureIntentPatterns.some(pattern => pattern.test(lower)) && !completionSignals.test(lower);
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
): Promise<void> {
  // Reset economics for new task
  ctx.economics?.reset();

  // Reflection configuration
  const reflectionConfig = ctx.config.reflection;
  const reflectionEnabled = isFeatureEnabled(reflectionConfig);
  const autoReflect = reflectionEnabled && reflectionConfig.autoReflect;
  const maxReflectionAttempts = reflectionEnabled
    ? (reflectionConfig.maxAttempts || 3)
    : 1;
  const confidenceThreshold = reflectionEnabled
    ? (reflectionConfig.confidenceThreshold || 0.8)
    : 0.8;

  let reflectionAttempt = 0;
  let lastResponse = '';
  let incompleteActionRetries = 0;
  const requestedArtifact = extractRequestedArtifact(task);
  const executedToolNames = new Set<string>();

  // Outer loop for reflection (if enabled)
  while (reflectionAttempt < maxReflectionAttempts) {
    reflectionAttempt++;

    // Agent loop - uses economics-based budget checking
    while (true) {
      ctx.state.iteration++;

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
          ctx.emit({ type: 'error', error: resourceCheck.message || 'Resource limit exceeded' });
          break;
        }

        if (resourceCheck.status === 'warning' || resourceCheck.status === 'critical') {
          ctx.observability?.logger?.info(`Resource status: ${resourceCheck.status}`, {
            message: resourceCheck.message,
          });
        }
      }

      // =======================================================================
      // ECONOMICS CHECK (Token Budget)
      // =======================================================================
      let forceTextOnly = false;
      let budgetInjectedPrompt: string | undefined;

      if (ctx.economics) {
        const budgetCheck = ctx.economics.checkBudget();

        forceTextOnly = budgetCheck.forceTextOnly ?? false;
        budgetInjectedPrompt = budgetCheck.injectedPrompt;

        if (!budgetCheck.canContinue) {
          // RECOVERY ATTEMPT: Try emergency context reduction
          const isTokenLimit = budgetCheck.budgetType === 'tokens' || budgetCheck.budgetType === 'cost';
          const alreadyTriedRecovery = (ctx.state as { _recoveryAttempted?: boolean })._recoveryAttempted === true;

          if (isTokenLimit && !alreadyTriedRecovery) {
            ctx.observability?.logger?.info('Budget limit reached, attempting recovery via context reduction', {
              reason: budgetCheck.reason,
              percentUsed: budgetCheck.percentUsed,
            });

            ctx.emit({
              type: 'resilience.retry',
              reason: 'budget_limit_compaction',
              attempt: 1,
              maxAttempts: 1,
            });
            ctx.state.metrics.retryCount = (ctx.state.metrics.retryCount ?? 0) + 1;

            (ctx.state as { _recoveryAttempted?: boolean })._recoveryAttempted = true;

            const tokensBefore = estimateContextTokens(messages);

            // Step 1: Compact tool outputs aggressively
            compactToolOutputs(ctx.state.messages);

            // Step 2: Emergency truncation - keep system + last N messages
            const PRESERVE_RECENT = 10;
            if (messages.length > PRESERVE_RECENT + 2) {
              const systemMessage = messages.find(m => m.role === 'system');
              const recentMessages = messages.slice(-(PRESERVE_RECENT));

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
              if (ctx.workLog?.hasContent()) {
                const workLogMessage: Message = {
                  role: 'user',
                  content: ctx.workLog.toCompactString(),
                };
                messages.push(workLogMessage);
              }

              // Update state messages too
              ctx.state.messages.length = 0;
              ctx.state.messages.push(...messages);
            }

            const tokensAfter = estimateContextTokens(messages);
            const reduction = Math.round((1 - tokensAfter / tokensBefore) * 100);

            if (tokensAfter < tokensBefore * 0.8) {
              ctx.observability?.logger?.info('Context reduction successful, continuing execution', {
                tokensBefore,
                tokensAfter,
                reduction,
              });

              ctx.emit({
                type: 'resilience.recovered',
                reason: 'budget_limit_compaction',
                attempts: 1,
              });

              ctx.emit({
                type: 'compaction.auto',
                tokensBefore,
                tokensAfter,
                messagesCompacted: tokensBefore - tokensAfter,
              });

              continue;
            }

            ctx.observability?.logger?.warn('Context reduction insufficient', {
              tokensBefore,
              tokensAfter,
              reduction,
            });
          }

          // Hard limit reached and recovery failed
          ctx.observability?.logger?.warn('Budget limit reached', {
            reason: budgetCheck.reason,
            budgetType: budgetCheck.budgetType,
          });

          if (budgetCheck.budgetType === 'iterations') {
            const totalIter = ctx.getTotalIterations();
            const iterMsg = ctx.parentIterations > 0
              ? `${ctx.state.iteration} + ${ctx.parentIterations} parent = ${totalIter}`
              : `${ctx.state.iteration}`;
            ctx.emit({ type: 'error', error: `Max iterations reached (${iterMsg})` });
          } else {
            ctx.emit({ type: 'error', error: budgetCheck.reason || 'Budget exceeded' });
          }
          break;
        }

        // Check for soft limits and potential extension
        if (budgetCheck.isSoftLimit && budgetCheck.suggestedAction === 'request_extension') {
          ctx.observability?.logger?.info('Approaching budget limit', {
            reason: budgetCheck.reason,
            percentUsed: budgetCheck.percentUsed,
          });
        }
      } else {
        // Fallback to simple iteration check
        if (ctx.getTotalIterations() >= ctx.config.maxIterations) {
          ctx.observability?.logger?.warn('Max iterations reached', {
            iteration: ctx.state.iteration,
            parentIterations: ctx.parentIterations,
            total: ctx.getTotalIterations(),
          });
          break;
        }
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
            plan: ctx.state.plan ? {
              description: ctx.state.plan.goal || task,
              tasks: ctx.state.plan.tasks.map(t => ({
                id: t.id,
                description: t.description,
                status: t.status,
              })),
              currentTaskIndex: ctx.state.plan.tasks.findIndex(t => t.status === 'in_progress'),
            } : undefined,
            activeFiles: ctx.economics?.getProgress().filesModified
              ? [`${ctx.economics.getProgress().filesModified} files modified`]
              : undefined,
            recentErrors: ctx.contextEngineering.getFailureInsights().slice(0, 2),
          }
        );

        if (process.env.DEBUG_LLM) {
          if (process.env.DEBUG) log.debug('Recitation after', { messageCount: enrichedMessages?.length ?? 'null/undefined' });
        }

        if (enrichedMessages && enrichedMessages !== messages && enrichedMessages.length > 0) {
          messages.length = 0;
          messages.push(...enrichedMessages);
        } else if (!enrichedMessages || enrichedMessages.length === 0) {
          log.warn('Recitation returned empty/null messages, keeping original');
        }

        const contextTokens = messages.reduce((sum, m) => sum + (m.content?.length || 0) / 4, 0);
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
      // INJECTION BUDGET ANALYSIS (Phase 2 - monitoring mode)
      // =======================================================================
      if (ctx.injectionBudget) {
        const proposals: InjectionSlot[] = [];
        if (budgetInjectedPrompt) {
          proposals.push({ name: 'budget_warning', priority: 0, maxTokens: 500, content: budgetInjectedPrompt });
        }
        if (ctx.contextEngineering) {
          const failureCtx = ctx.contextEngineering.getFailureContext(5);
          if (failureCtx) {
            proposals.push({ name: 'failure_context', priority: 2, maxTokens: 300, content: failureCtx });
          }
        }
        if (proposals.length > 0) {
          const accepted = ctx.injectionBudget.allocate(proposals);
          const stats = ctx.injectionBudget.getLastStats();
          if (stats && stats.droppedNames.length > 0 && process.env.DEBUG) {
            log.debug('Injection budget dropped items', { droppedNames: stats.droppedNames.join(', '), proposedTokens: stats.proposedTokens, acceptedTokens: stats.acceptedTokens });
          }
          if (stats && process.env.DEBUG_LLM) {
            log.debug('Injection budget summary', { iteration: ctx.state.iteration, accepted: accepted.length, total: proposals.length, tokens: stats.acceptedTokens });
          }
        }
      }

      // =======================================================================
      // RESILIENT LLM CALL
      // =======================================================================
      const resilienceConfig = typeof ctx.config.resilience === 'object'
        ? ctx.config.resilience
        : {};
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
        const estimatedOutputTokens = 4096;
        const currentUsage = ctx.economics.getUsage();
        const budget = ctx.economics.getBudget();
        const projectedTotal = currentUsage.tokens + estimatedInputTokens + estimatedOutputTokens;

        if (projectedTotal > budget.maxTokens) {
          ctx.observability?.logger?.warn('Pre-flight budget check: projected overshoot', {
            currentTokens: currentUsage.tokens,
            estimatedInput: estimatedInputTokens,
            projectedTotal,
            maxTokens: budget.maxTokens,
          });

          if (!budgetInjectedPrompt) {
            messages.push({
              role: 'user',
              content: '[System] BUDGET CRITICAL: This is your LAST response. Summarize findings concisely and stop. Do NOT call tools.',
            });
            ctx.state.messages.push({
              role: 'user',
              content: '[System] BUDGET CRITICAL: This is your LAST response. Summarize findings concisely and stop. Do NOT call tools.',
            });
          }
          forceTextOnly = true;
        }
      }

      let response = await callLLM(messages, ctx);
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
            ctx.observability?.logger?.warn('Thinking-only response (no visible content), nudging', {
              thinkingLength: response.thinking!.length,
            });

            const thinkingNudge: Message = {
              role: 'user',
              content: '[System: You produced reasoning but no visible response. Please provide your answer based on your analysis.]',
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
          content: '[System: Your previous response was empty. Please provide a response or use a tool.]',
        };
        messages.push(nudgeMessage);
        ctx.state.messages.push(nudgeMessage);

        response = await callLLM(messages, ctx);
      }

      // Phase 2: Handle max_tokens truncation with continuation
      if (resilienceEnabled && AUTO_CONTINUE && response.stopReason === 'max_tokens' && !response.toolCalls?.length) {
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
            content: '[System: Please continue from where you left off. Do not repeat what you already said.]',
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
          toolNames: response.toolCalls.map(tc => tc.name),
        });
        ctx.observability?.logger?.warn('Tool call truncated at max_tokens', {
          toolNames: response.toolCalls.map(tc => tc.name),
          outputTokens: response.usage?.outputTokens,
        });

        const truncatedResponse = response;
        response = { ...response, toolCalls: undefined };
        const recoveryMessage: Message = {
          role: 'user',
          content: '[System: Your previous tool call was truncated because the output exceeded the token limit. ' +
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
          response.usage.cost
        );

        // POST-LLM BUDGET CHECK
        if (!forceTextOnly) {
          const postCheck = ctx.economics.checkBudget();
          if (!postCheck.canContinue) {
            ctx.observability?.logger?.warn('Budget exceeded after LLM call, skipping tool execution', {
              reason: postCheck.reason,
            });
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
      if (ctx.modeManager.getMode() === 'plan' && response.content && response.content.length > 50) {
        const hasReadOnlyTools = response.toolCalls?.every(tc =>
          ['read_file', 'list_files', 'glob', 'grep', 'search', 'mcp_'].some(prefix =>
            tc.name.startsWith(prefix) || tc.name === prefix
          )
        );
        if (hasReadOnlyTools && !response.content.match(/^(Let me|I'll|I will|I need to|First,)/i)) {
          ctx.pendingPlanManager.appendExplorationFinding(response.content.slice(0, 1000));
        }
      }

      // Check for tool calls
      const hasToolCalls = response.toolCalls && response.toolCalls.length > 0;
      if (!hasToolCalls || forceTextOnly) {
        if (forceTextOnly && hasToolCalls) {
          ctx.observability?.logger?.info('Ignoring tool calls due to forceTextOnly (max steps reached)', {
            toolCallCount: response.toolCalls?.length,
            iteration: ctx.state.iteration,
          });
        }

        const incompleteAction = detectIncompleteActionResponse(response.content || '');
        const missingRequiredArtifact = ENFORCE_REQUESTED_ARTIFACTS
          ? isRequestedArtifactMissing(requestedArtifact, executedToolNames)
          : false;
        const shouldRecoverIncompleteAction = resilienceEnabled
          && INCOMPLETE_ACTION_RECOVERY
          && !forceTextOnly
          && (incompleteAction || missingRequiredArtifact);

        if (shouldRecoverIncompleteAction) {
          if (incompleteActionRetries < MAX_INCOMPLETE_ACTION_RETRIES) {
            incompleteActionRetries++;
            const reason = missingRequiredArtifact && requestedArtifact
              ? `missing_requested_artifact:${requestedArtifact}`
              : 'future_intent_without_action';
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
              content: missingRequiredArtifact && requestedArtifact
                ? `[System: You said you would complete the next action, but no tool call was made. The task requires creating or updating "${requestedArtifact}". Execute the required tool now, or explicitly explain why it cannot be produced.]`
                : '[System: You described a next action but did not execute it. If work remains, call the required tool now. If the task is complete, provide a final answer with no pending action language.]',
            };
            messages.push(nudgeMessage);
            ctx.state.messages.push(nudgeMessage);
            continue;
          }

          const failureReason = missingRequiredArtifact && requestedArtifact
            ? `incomplete_action_missing_artifact:${requestedArtifact}`
            : 'incomplete_action_unresolved';
          ctx.emit({
            type: 'resilience.incomplete_action_failed',
            reason: failureReason,
            attempts: incompleteActionRetries,
            maxAttempts: MAX_INCOMPLETE_ACTION_RETRIES,
          });
          throw new Error(`LLM failed to complete requested action after ${incompleteActionRetries} retries (${failureReason})`);
        }

        if (incompleteActionRetries > 0) {
          ctx.emit({
            type: 'resilience.incomplete_action_recovered',
            reason: 'incomplete_action',
            attempts: incompleteActionRetries,
          });
          incompleteActionRetries = 0;
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

        // Record iteration end for tracing (no tool calls case)
        ctx.traceCollector?.record({
          type: 'iteration.end',
          data: { iterationNumber: ctx.state.iteration },
        });
        break;
      }

      // Execute tool calls
      const toolCalls = response.toolCalls!;
      const toolResults = await executeToolCalls(toolCalls, ctx);

      // Record tool calls for economics/progress tracking + work log
      for (let i = 0; i < toolCalls.length; i++) {
        const toolCall = toolCalls[i];
        const result = toolResults[i];
        executedToolNames.add(toolCall.name);
        ctx.economics?.recordToolCall(toolCall.name, toolCall.arguments, result?.result);
        // Record in work log
        const toolOutput = result?.result && typeof result.result === 'object' && 'output' in (result.result as any)
          ? String((result.result as any).output)
          : typeof result?.result === 'string' ? result.result : undefined;
        ctx.workLog?.recordToolExecution(
          toolCall.name,
          toolCall.arguments,
          toolOutput,
        );
        // Record in verification gate
        if (ctx.verificationGate) {
          if (toolCall.name === 'bash') {
            const toolRes = result?.result as any;
            const output = toolRes && typeof toolRes === 'object' && 'output' in toolRes
              ? String(toolRes.output)
              : typeof toolRes === 'string' ? toolRes : '';
            const exitCode = toolRes && typeof toolRes === 'object' && toolRes.metadata
              ? (toolRes.metadata as any).exitCode ?? null
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

        // Phase 5.1: Post-edit syntax validation
        if (['write_file', 'edit_file'].includes(toolCall.name) && result?.result && (result.result as any).success) {
          const filePath = String(toolCall.arguments.path || '');
          if (filePath) {
            try {
              const content = toolCall.name === 'write_file'
                ? String(toolCall.arguments.content || '')
                : await fs.promises.readFile(filePath, 'utf-8');
              const validation = validateSyntax(content, filePath);
              if (!validation.valid && result.result && typeof result.result === 'object') {
                const errorSummary = validation.errors
                  .slice(0, 3)
                  .map(e => `  L${e.line}:${e.column}: ${e.message}`)
                  .join('\n');
                (result.result as any).output += `\n\n⚠ Syntax validation warning:\n${errorSummary}`;
              }
            } catch {
              // Validation failure is non-blocking
            }
          }
        }
      }

      // Add tool results to messages (with truncation and proactive budget management)
      const MAX_TOOL_OUTPUT_CHARS = 8000;

      // PROACTIVE BUDGET CHECK
      const currentContextTokens = estimateContextTokens(messages);

      if (ctx.autoCompactionManager) {
        const compactionResult = await ctx.autoCompactionManager.checkAndMaybeCompact({
          currentTokens: currentContextTokens,
          messages: messages,
        });

        if (compactionResult.status === 'compacted' && compactionResult.compactedMessages) {
          if (!ctx.compactionPending) {
            mutators.setCompactionPending(true);
            const preCompactionMsg: Message = {
              role: 'user',
              content: '[SYSTEM] Context compaction is imminent. Summarize your current progress, key findings, and next steps into a single concise message. This will be preserved after compaction.',
            };
            messages.push(preCompactionMsg);
            ctx.state.messages.push(preCompactionMsg);

            ctx.observability?.logger?.info('Pre-compaction agentic turn: injected summary request');
          } else {
            mutators.setCompactionPending(false);

            // Pre-compaction checkpoint
            // NOTE: autoCheckpoint is called via the agent's method, not directly here
            // The agent wires this through the mutators pattern

            // Replace messages with compacted version
            messages.length = 0;
            messages.push(...compactionResult.compactedMessages);
            ctx.state.messages.length = 0;
            ctx.state.messages.push(...compactionResult.compactedMessages);

            // Inject work log after compaction
            if (ctx.workLog?.hasContent()) {
              const workLogMessage: Message = {
                role: 'user',
                content: ctx.workLog.toCompactString(),
              };
              messages.push(workLogMessage);
              ctx.state.messages.push(workLogMessage);
            }

            // Context recovery
            const recoveryParts: string[] = [];

            if (ctx.store) {
              const goalsSummary = ctx.store.getGoalsSummary();
              if (goalsSummary && goalsSummary !== 'No active goals.' && goalsSummary !== 'Goals feature not available.') {
                recoveryParts.push(goalsSummary);
              }
            }

            if (ctx.store) {
              const juncturesSummary = ctx.store.getJuncturesSummary(undefined, 5);
              if (juncturesSummary) {
                recoveryParts.push(juncturesSummary);
              }
            }

            if (ctx.learningStore) {
              const learnings = ctx.learningStore.getLearningContext({ maxLearnings: 3 });
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
              ctx.state.messages.push(recoveryMessage);
            }

            // Emit compaction event
            const compactionTokensAfter = estimateContextTokens(messages);
            const compactionRecoveryInjected = recoveryParts.length > 0;
            const compactionEvent = {
              type: 'context.compacted',
              tokensBefore: currentContextTokens,
              tokensAfter: compactionTokensAfter,
              recoveryInjected: compactionRecoveryInjected,
            };
            ctx.emit(compactionEvent as any);

            if (ctx.traceCollector) {
              ctx.traceCollector.record({
                type: 'context.compacted',
                data: {
                  tokensBefore: currentContextTokens,
                  tokensAfter: compactionTokensAfter,
                  recoveryInjected: compactionRecoveryInjected,
                },
              });
            }
          }
        } else if (compactionResult.status === 'hard_limit') {
          ctx.emit({
            type: 'error',
            error: `Context hard limit reached (${Math.round(compactionResult.ratio * 100)}% of max tokens)`,
          });
          break;
        }
      } else if (ctx.economics) {
        // Fallback to simple compaction
        const currentUsage = ctx.economics.getUsage();
        const budget = ctx.economics.getBudget();
        const percentUsed = (currentUsage.tokens / budget.maxTokens) * 100;

        if (percentUsed >= 70) {
          ctx.observability?.logger?.info('Proactive compaction triggered', {
            percentUsed: Math.round(percentUsed),
            currentTokens: currentUsage.tokens,
            maxTokens: budget.maxTokens,
          });

          compactToolOutputs(ctx.state.messages);
        }
      }

      const toolCallNameById = new Map(toolCalls.map(tc => [tc.id, tc.name]));

      for (const result of toolResults) {
        let content = typeof result.result === 'string' ? result.result : stableStringify(result.result);
        const sourceToolName = toolCallNameById.get(result.callId);
        const isExpensiveResult = sourceToolName === 'spawn_agent' || sourceToolName === 'spawn_agents_parallel';

        const effectiveMaxChars = isExpensiveResult ? MAX_TOOL_OUTPUT_CHARS * 2 : MAX_TOOL_OUTPUT_CHARS;
        if (content.length > effectiveMaxChars) {
          content = content.slice(0, effectiveMaxChars) + `\n\n... [truncated ${content.length - effectiveMaxChars} chars]`;
        }

        // Check if adding this result would exceed budget
        if (ctx.economics) {
          const estimatedNewTokens = Math.ceil(content.length / 4);
          const currentCtxTokens = estimateContextTokens(messages);
          const budget = ctx.economics.getBudget();

          if (currentCtxTokens + estimatedNewTokens > budget.maxTokens * 0.95) {
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
}
