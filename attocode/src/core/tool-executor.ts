/**
 * Tool Executor Module (Phase 2.1)
 *
 * Extracted from ProductionAgent.executeToolCalls() and executeSingleToolCall().
 * Handles batch grouping, parallel/sequential dispatch, plan mode interception,
 * policy enforcement, safety validation, blackboard coordination, file cache,
 * and actual tool execution.
 */

import type { Message, ToolCall, ToolResult } from '../types.js';

import type { AgentContext } from './types.js';

import { createComponentLogger } from '../integrations/utilities/logger.js';

// =============================================================================
// TOOL BATCHING CONSTANTS & UTILITIES (moved from agent.ts to break cycle)
// =============================================================================

/**
 * Tools that are safe to execute in parallel (read-only, no side effects).
 * These tools don't modify state, so running them concurrently is safe.
 */
export const PARALLELIZABLE_TOOLS = new Set([
  'read_file',
  'glob',
  'grep',
  'list_files',
  'search_files',
  'search_code',
  'get_file_info',
  'task_create',
  'task_update',
  'task_get',
  'task_list',
]);

/**
 * Tools that can run in parallel IF they target different files.
 * write_file and edit_file on different paths are safe to parallelize.
 */
export const CONDITIONALLY_PARALLEL_TOOLS = new Set(['write_file', 'edit_file']);

/**
 * Extract the target file path from a tool call's arguments.
 * Returns null if no file path can be determined.
 */
export function extractToolFilePath(toolCall: {
  name: string;
  [key: string]: unknown;
}): string | null {
  const args = toolCall as Record<string, unknown>;
  for (const key of ['path', 'file_path', 'filename', 'file']) {
    if (typeof args[key] === 'string') return args[key] as string;
  }
  if (args.args && typeof args.args === 'object') {
    const nested = args.args as Record<string, unknown>;
    for (const key of ['path', 'file_path', 'filename', 'file']) {
      if (typeof nested[key] === 'string') return nested[key] as string;
    }
  }
  if (args.input && typeof args.input === 'object') {
    const input = args.input as Record<string, unknown>;
    for (const key of ['path', 'file_path', 'filename', 'file']) {
      if (typeof input[key] === 'string') return input[key] as string;
    }
  }
  return null;
}

/**
 * Check if a conditionally-parallel tool call conflicts with any tool
 * in the current accumulator (same file path).
 */
function hasFileConflict<T extends { name: string }>(toolCall: T, accumulator: T[]): boolean {
  const path = extractToolFilePath(toolCall as T & Record<string, unknown>);
  if (!path) return true;

  for (const existing of accumulator) {
    const existingPath = extractToolFilePath(existing as T & Record<string, unknown>);
    if (existingPath === path) return true;
  }

  return false;
}

/**
 * Groups tool calls into batches for parallel/sequential execution.
 */
export function groupToolCallsIntoBatches<T extends { name: string }>(
  toolCalls: T[],
  isParallelizable: (tc: T) => boolean = (tc) => PARALLELIZABLE_TOOLS.has(tc.name),
  isConditionallyParallel: (tc: T) => boolean = (tc) => CONDITIONALLY_PARALLEL_TOOLS.has(tc.name),
): T[][] {
  if (toolCalls.length === 0) return [];

  const batches: T[][] = [];
  let parallelAccum: T[] = [];

  for (const toolCall of toolCalls) {
    if (isParallelizable(toolCall)) {
      parallelAccum.push(toolCall);
    } else if (isConditionallyParallel(toolCall)) {
      if (!hasFileConflict(toolCall, parallelAccum)) {
        parallelAccum.push(toolCall);
      } else {
        if (parallelAccum.length > 0) {
          batches.push(parallelAccum);
          parallelAccum = [];
        }
        parallelAccum.push(toolCall);
      }
    } else {
      if (parallelAccum.length > 0) {
        batches.push(parallelAccum);
        parallelAccum = [];
      }
      batches.push([toolCall]);
    }
  }

  if (parallelAccum.length > 0) {
    batches.push(parallelAccum);
  }

  return batches;
}

const log = createComponentLogger('ToolExecutor');

/**
 * Execute tool calls with safety checks and execution policy enforcement.
 * Parallelizable read-only tools are batched and executed concurrently.
 */
export async function executeToolCalls(
  toolCalls: ToolCall[],
  ctx: AgentContext,
): Promise<ToolResult[]> {
  const results: ToolResult[] = [];

  // Circuit breaker state
  const circuitBreakerThreshold =
    ctx.economics?.getBudget()?.tuning?.circuitBreakerFailureThreshold ?? 5;
  let consecutiveFailures = 0;
  let circuitBroken = false;

  // Group consecutive parallelizable tool calls into batches
  const batches = groupToolCallsIntoBatches(toolCalls);

  // Execute batches: parallel batches use Promise.allSettled, sequential execute one-by-one
  for (const batch of batches) {
    // SAFEGUARD: Circuit breaker — skip remaining batches with stub results
    if (circuitBroken) {
      for (const tc of batch) {
        results.push({
          callId: tc.id,
          result: `Error: Skipped — circuit breaker tripped after ${circuitBreakerThreshold} consecutive failures`,
          error: `Circuit breaker tripped after ${circuitBreakerThreshold} consecutive failures`,
        });
      }
      continue;
    }

    if (batch.length > 1 && PARALLELIZABLE_TOOLS.has(batch[0].name)) {
      // Execute parallelizable batch concurrently
      const batchResults = await Promise.allSettled(
        batch.map((tc) => executeSingleToolCall(tc, ctx)),
      );
      let batchFailures = 0;
      for (const result of batchResults) {
        if (result.status === 'fulfilled') {
          results.push(result.value);
          if (result.value.error) {
            batchFailures++;
          }
        } else {
          const error =
            result.reason instanceof Error ? result.reason.message : String(result.reason);
          results.push({ callId: 'unknown', result: `Error: ${error}`, error });
          batchFailures++;
        }
      }
      // If entire parallel batch failed, add to consecutive failures; any success resets
      if (batchFailures === batchResults.length) {
        consecutiveFailures += batchFailures;
      } else {
        consecutiveFailures = 0;
      }
    } else {
      // Execute sequentially
      for (const tc of batch) {
        if (circuitBroken) {
          results.push({
            callId: tc.id,
            result: `Error: Skipped — circuit breaker tripped after ${circuitBreakerThreshold} consecutive failures`,
            error: `Circuit breaker tripped after ${circuitBreakerThreshold} consecutive failures`,
          });
          continue;
        }

        const result = await executeSingleToolCall(tc, ctx);
        results.push(result);

        if (result.error) {
          consecutiveFailures++;
        } else {
          consecutiveFailures = 0;
        }

        if (consecutiveFailures >= circuitBreakerThreshold) {
          circuitBroken = true;
          const skipped = toolCalls.length - results.length;
          log.warn('Circuit breaker tripped — stopping tool execution', {
            totalInBatch: toolCalls.length,
            failures: consecutiveFailures,
            threshold: circuitBreakerThreshold,
            skipped,
          });
          ctx.emit({
            type: 'safeguard.circuit_breaker',
            totalInBatch: toolCalls.length,
            failures: consecutiveFailures,
            threshold: circuitBreakerThreshold,
            skipped,
          });
        }
      }
    }

    // Check circuit breaker after parallel batches too
    if (!circuitBroken && consecutiveFailures >= circuitBreakerThreshold) {
      circuitBroken = true;
      const skipped = toolCalls.length - results.length;
      log.warn('Circuit breaker tripped — stopping tool execution', {
        totalInBatch: toolCalls.length,
        failures: consecutiveFailures,
        threshold: circuitBreakerThreshold,
        skipped,
      });
      ctx.emit({
        type: 'safeguard.circuit_breaker',
        totalInBatch: toolCalls.length,
        failures: consecutiveFailures,
        threshold: circuitBreakerThreshold,
        skipped,
      });
    }
  }

  return results;
}

/**
 * Execute a single tool call with all safety checks, tracing, and error handling.
 */
export async function executeSingleToolCall(
  toolCall: ToolCall,
  ctx: AgentContext,
): Promise<ToolResult> {
  const spanId = ctx.observability?.tracer?.startSpan(`tool.${toolCall.name}`);
  const executionId = `exec-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  ctx.emit({ type: 'tool.start', tool: toolCall.name, args: toolCall.arguments });

  const startTime = Date.now();

  // Short-circuit if tool call arguments failed to parse
  if (toolCall.parseError) {
    const errorMsg = `Tool arguments could not be parsed: ${toolCall.parseError}. Please retry with complete, valid JSON.`;
    ctx.emit({ type: 'tool.blocked', tool: toolCall.name, reason: errorMsg });
    ctx.traceCollector?.record({
      type: 'tool.end',
      data: {
        executionId,
        status: 'error',
        error: new Error(errorMsg),
        durationMs: Date.now() - startTime,
      },
    });
    ctx.observability?.tracer?.endSpan(spanId);
    return { callId: toolCall.id, result: `Error: ${errorMsg}`, error: errorMsg };
  }

  // Record tool start for tracing
  ctx.traceCollector?.record({
    type: 'tool.start',
    data: {
      executionId,
      toolName: toolCall.name,
      arguments: toolCall.arguments as Record<string, unknown>,
    },
  });

  try {
    // =====================================================================
    // PLAN MODE WRITE INTERCEPTION
    // =====================================================================
    if (
      ctx.modeManager.shouldInterceptTool(
        toolCall.name,
        toolCall.arguments as Record<string, unknown>,
      )
    ) {
      const reason = extractChangeReasoning(toolCall, ctx.state.messages);

      // Start a new plan if needed
      if (!ctx.pendingPlanManager.hasPendingPlan()) {
        const lastUserMsg = [...ctx.state.messages].reverse().find((m) => m.role === 'user');
        const task = typeof lastUserMsg?.content === 'string' ? lastUserMsg.content : 'Plan';
        ctx.pendingPlanManager.startPlan(task);
      }

      // Queue the write operation
      const change = ctx.pendingPlanManager.addProposedChange(
        toolCall.name,
        toolCall.arguments as Record<string, unknown>,
        reason,
        toolCall.id,
      );

      // Emit event for UI
      ctx.emit({
        type: 'plan.change.queued',
        tool: toolCall.name,
        changeId: change?.id,
        summary: formatToolArgsForPlan(
          toolCall.name,
          toolCall.arguments as Record<string, unknown>,
        ),
      });

      // Return a message indicating the change was queued
      const queueMessage =
        `[PLAN MODE] Change queued for approval:\n` +
        `Tool: ${toolCall.name}\n` +
        `${formatToolArgsForPlan(toolCall.name, toolCall.arguments as Record<string, unknown>)}\n` +
        `Use /show-plan to see all pending changes, /approve to execute, /reject to discard.`;

      ctx.observability?.tracer?.endSpan(spanId);
      return { callId: toolCall.id, result: queueMessage };
    }

    // =====================================================================
    // EXECUTION POLICY ENFORCEMENT (Lesson 23)
    // =====================================================================
    let policyApprovedByUser = false;
    if (ctx.executionPolicy) {
      const policyContext = {
        messages: ctx.state.messages,
        currentMessage: ctx.state.messages.find((m) => m.role === 'user')?.content,
        previousToolCalls: [],
      };

      const evaluation = ctx.executionPolicy.evaluate(toolCall, policyContext);

      // Emit policy event
      ctx.emit({
        type: 'policy.evaluated',
        tool: toolCall.name,
        policy: evaluation.policy,
        reason: evaluation.reason,
      });

      // Emit decision transparency event
      ctx.emit({
        type: 'decision.tool',
        tool: toolCall.name,
        decision:
          evaluation.policy === 'forbidden'
            ? 'blocked'
            : evaluation.policy === 'prompt'
              ? 'prompted'
              : 'allowed',
        policyMatch: evaluation.reason,
      });

      // Enhanced tracing: Record policy decision
      ctx.traceCollector?.record({
        type: 'decision',
        data: {
          type: 'policy',
          decision: `Tool ${toolCall.name}: ${evaluation.policy}`,
          outcome:
            evaluation.policy === 'forbidden'
              ? 'blocked'
              : evaluation.policy === 'prompt'
                ? 'deferred'
                : 'allowed',
          reasoning: evaluation.reason,
          factors: [
            { name: 'policy', value: evaluation.policy },
            { name: 'requiresApproval', value: evaluation.requiresApproval ?? false },
          ],
          confidence: evaluation.intent?.confidence ?? 0.8,
        },
      });

      // Handle forbidden policy - always block
      if (evaluation.policy === 'forbidden') {
        ctx.emit({
          type: 'policy.tool.blocked',
          tool: toolCall.name,
          phase: 'enforced',
          reason: `Forbidden by execution policy: ${evaluation.reason}`,
        });
        throw new Error(`Forbidden by policy: ${evaluation.reason}`);
      }

      // Handle prompt policy - requires approval
      if (evaluation.policy === 'prompt' && evaluation.requiresApproval) {
        const humanInLoop = ctx.safety?.humanInLoop;
        if (humanInLoop) {
          const approval = await withPausedDuration(ctx, () =>
            humanInLoop.requestApproval(toolCall, `Policy requires approval: ${evaluation.reason}`),
          );

          if (!approval.approved) {
            throw new Error(`Denied by user: ${approval.reason || 'No reason provided'}`);
          }
          policyApprovedByUser = true;

          // Create a grant for future similar calls if approved
          ctx.executionPolicy.createGrant({
            toolName: toolCall.name,
            grantedBy: 'user',
            reason: 'Approved during execution',
            maxUsages: 5,
          });
        } else {
          // No approval handler — auto-allow with warning (defense-in-depth)
          ctx.emit({
            type: 'policy.tool.auto-allowed',
            tool: toolCall.name,
            reason: `No approval handler — auto-allowing (policy: ${evaluation.reason})`,
          });
          policyApprovedByUser = true;
        }
      }

      // Log intent classification if available
      if (evaluation.intent) {
        ctx.emit({
          type: 'intent.classified',
          tool: toolCall.name,
          intent: evaluation.intent.type,
          confidence: evaluation.intent.confidence,
        });
      }
    }

    // =====================================================================
    // SAFETY VALIDATION (Lesson 20-21)
    // =====================================================================
    if (ctx.safety) {
      const safety = ctx.safety;
      const validation = await withPausedDuration(ctx, () =>
        safety.validateAndApprove(toolCall, `Executing tool: ${toolCall.name}`, {
          skipHumanApproval: policyApprovedByUser,
        }),
      );

      if (!validation.allowed) {
        ctx.emit({
          type: 'policy.tool.blocked',
          tool: toolCall.name,
          phase: 'enforced',
          reason: validation.reason || 'Blocked by safety manager',
        });
        if (toolCall.name === 'bash') {
          const args = toolCall.arguments as Record<string, unknown>;
          ctx.emit({
            type: 'policy.bash.blocked',
            phase: 'enforced',
            command: String(args.command || args.cmd || ''),
            reason: validation.reason || 'Blocked by safety manager',
          });
        }
        throw new Error(`Tool call blocked: ${validation.reason}`);
      }
    }

    // Get tool definition (with lazy-loading support for MCP tools)
    let tool = ctx.tools.get(toolCall.name);
    const wasPreloaded = !!tool;
    if (!tool && ctx.toolResolver) {
      const resolved = ctx.toolResolver(toolCall.name);
      if (resolved) {
        ctx.addTool(resolved);
        tool = resolved;
        if (process.env.DEBUG) log.debug('Auto-loaded MCP tool', { tool: toolCall.name });
        ctx.observability?.logger?.info('Tool auto-loaded', { tool: toolCall.name });
      }
    }
    if (!tool) {
      throw new Error(`Unknown tool: ${toolCall.name}`);
    }
    if (process.env.DEBUG && toolCall.name.startsWith('mcp_') && wasPreloaded) {
      log.debug('Using pre-loaded MCP tool', { tool: toolCall.name });
    }

    // =====================================================================
    // BLACKBOARD FILE COORDINATION (Parallel Subagent Support)
    // =====================================================================
    if (ctx.blackboard && (toolCall.name === 'write_file' || toolCall.name === 'edit_file')) {
      const args = toolCall.arguments as Record<string, unknown>;
      const filePath = String(args.path || args.file_path || '');
      if (filePath) {
        const agentId = ctx.agentId;
        const claimed = ctx.blackboard.claim(filePath, agentId, 'write', {
          ttl: 60000,
          intent: `${toolCall.name}: ${filePath}`,
        });
        if (!claimed) {
          const existingClaim = ctx.blackboard.getClaim(filePath);
          throw new Error(
            `File "${filePath}" is being edited by another agent (${existingClaim?.agentId || 'unknown'}). ` +
              `Wait for the other agent to complete or choose a different file.`,
          );
        }
      }
    }

    // FILE CACHE: Check cache for read_file operations before executing
    if (ctx.fileCache && toolCall.name === 'read_file') {
      const args = toolCall.arguments as Record<string, unknown>;
      const readPath = String(args.path || '');
      if (readPath) {
        const cached = ctx.fileCache.get(readPath);
        if (cached !== undefined) {
          const lines = cached.split('\n').length;
          const cacheResult = {
            success: true,
            output: cached,
            metadata: { lines, bytes: cached.length, cached: true },
          };

          const duration = Date.now() - startTime;
          ctx.traceCollector?.record({
            type: 'tool.end',
            data: { executionId, status: 'success', result: cacheResult, durationMs: duration },
          });
          ctx.observability?.metrics?.recordToolCall(toolCall.name, duration, true);
          ctx.state.metrics.toolCalls++;
          ctx.emit({ type: 'tool.complete', tool: toolCall.name, result: cacheResult });

          ctx.observability?.tracer?.endSpan(spanId);
          return {
            callId: toolCall.id,
            result: typeof cacheResult === 'string' ? cacheResult : JSON.stringify(cacheResult),
          };
        }
      }
    }

    // Execute tool (with sandbox if available)
    let result: unknown;
    if (ctx.safety?.sandbox) {
      const isSpawnAgent = toolCall.name === 'spawn_agent';
      const isSpawnParallel = toolCall.name === 'spawn_agents_parallel';
      const isSubagentTool = isSpawnAgent || isSpawnParallel;

      const subagentConfig = ctx.config.subagent;
      const hasSubagentConfig = subagentConfig !== false && subagentConfig !== undefined;
      const subagentTimeout = hasSubagentConfig
        ? ((subagentConfig as { defaultTimeout?: number }).defaultTimeout ?? 600000)
        : 600000;

      const toolTimeout = isSubagentTool ? subagentTimeout + 30000 : undefined;

      result = await ctx.safety.sandbox.executeWithLimits(
        () => tool.execute(toolCall.arguments),
        toolTimeout,
      );
    } else {
      // No sandbox — apply a safety timeout to prevent indefinite hangs
      const DEFAULT_TOOL_TIMEOUT = 300_000; // 5 minutes
      result = await Promise.race([
        tool.execute(toolCall.arguments),
        new Promise<never>((_, reject) =>
          setTimeout(
            () =>
              reject(
                new Error(
                  `Tool '${toolCall.name}' timed out after ${DEFAULT_TOOL_TIMEOUT / 1000}s (no sandbox)`,
                ),
              ),
            DEFAULT_TOOL_TIMEOUT,
          ),
        ),
      ]);
    }

    const duration = Date.now() - startTime;

    // Record tool completion for tracing
    ctx.traceCollector?.record({
      type: 'tool.end',
      data: {
        executionId,
        status: 'success',
        result,
        durationMs: duration,
      },
    });

    // Record metrics
    ctx.observability?.metrics?.recordToolCall(toolCall.name, duration, true);
    ctx.state.metrics.toolCalls++;

    ctx.emit({ type: 'tool.complete', tool: toolCall.name, result });

    // FILE CACHE: Store read results and invalidate on writes
    if (ctx.fileCache) {
      const args = toolCall.arguments as Record<string, unknown>;
      const filePath = String(args.path || args.file_path || '');

      if (toolCall.name === 'read_file' && filePath) {
        const resultObj = result as { success?: boolean; output?: string };
        if (resultObj?.success && typeof resultObj.output === 'string') {
          ctx.fileCache.set(filePath, resultObj.output);
        }
      } else if (
        (toolCall.name === 'write_file' ||
          toolCall.name === 'edit_file' ||
          toolCall.name === 'undo_file_change') &&
        filePath
      ) {
        ctx.fileCache.invalidate(filePath);
      }
    }

    // Emit tool insight with result summary
    const summary = summarizeToolResult(toolCall.name, result);
    ctx.emit({
      type: 'insight.tool',
      tool: toolCall.name,
      summary,
      durationMs: duration,
      success: true,
    });

    // Release blackboard claim after successful file write
    if (ctx.blackboard && (toolCall.name === 'write_file' || toolCall.name === 'edit_file')) {
      const args = toolCall.arguments as Record<string, unknown>;
      const filePath = String(args.path || args.file_path || '');
      if (filePath) {
        const agentId = ctx.agentId;
        ctx.blackboard.release(filePath, agentId);
      }
    }

    // Self-improvement: record success pattern
    ctx.selfImprovement?.recordSuccess(
      toolCall.name,
      toolCall.arguments as Record<string, unknown>,
      typeof result === 'string' ? result.slice(0, 200) : JSON.stringify(result).slice(0, 200),
    );

    ctx.observability?.tracer?.endSpan(spanId);
    return { callId: toolCall.id, result };
  } catch (err) {
    const error = err instanceof Error ? err : new Error(String(err));
    const duration = Date.now() - startTime;

    // Record tool error for tracing
    ctx.traceCollector?.record({
      type: 'tool.end',
      data: {
        executionId,
        status:
          error.message.includes('Blocked') || error.message.includes('Policy')
            ? 'blocked'
            : 'error',
        error,
        durationMs: duration,
      },
    });

    ctx.observability?.metrics?.recordToolCall(toolCall.name, duration, false);
    ctx.observability?.tracer?.recordError(error);
    ctx.observability?.tracer?.endSpan(spanId);

    // FAILURE EVIDENCE RECORDING (Trick S)
    ctx.contextEngineering?.recordFailure({
      action: toolCall.name,
      args: toolCall.arguments as Record<string, unknown>,
      error,
      intent: `Execute tool ${toolCall.name}`,
    });

    // FILE CACHE INVALIDATION ON FAILURE — ensure stale cache doesn't cause repeated failures
    if (ctx.fileCache && ['write_file', 'edit_file'].includes(toolCall.name)) {
      const args = toolCall.arguments as Record<string, unknown>;
      const filePath = String(args.path || args.file_path || '');
      if (filePath) {
        ctx.fileCache.invalidate(filePath);
      }
    }

    // Self-improvement: enhance error message with diagnosis
    if (ctx.selfImprovement) {
      const enhanced = ctx.selfImprovement.enhanceErrorMessage(
        toolCall.name,
        error.message,
        toolCall.arguments as Record<string, unknown>,
      );
      ctx.emit({ type: 'tool.blocked', tool: toolCall.name, reason: enhanced });
      return { callId: toolCall.id, result: `Error: ${enhanced}`, error: enhanced };
    }

    ctx.emit({ type: 'tool.blocked', tool: toolCall.name, reason: error.message });
    return { callId: toolCall.id, result: `Error: ${error.message}`, error: error.message };
  }
}

// =============================================================================
// HELPER FUNCTIONS (extracted from ProductionAgent private methods)
// =============================================================================

/**
 * Execute an async callback while excluding wall-clock wait time from duration budgeting.
 */
async function withPausedDuration<T>(ctx: AgentContext, fn: () => Promise<T>): Promise<T> {
  ctx.economics?.pauseDuration();
  try {
    return await fn();
  } finally {
    ctx.economics?.resumeDuration();
  }
}

/**
 * Create a brief summary of a tool result for insight display.
 */
export function summarizeToolResult(toolName: string, result: unknown): string {
  if (result === null || result === undefined) {
    return 'No output';
  }

  const resultStr = typeof result === 'string' ? result : JSON.stringify(result);

  if (toolName === 'list_files' || toolName === 'glob') {
    const lines = resultStr.split('\n').filter((l) => l.trim());
    return `Found ${lines.length} file${lines.length !== 1 ? 's' : ''}`;
  }
  if (toolName === 'bash' || toolName === 'execute_command') {
    const lines = resultStr.split('\n').filter((l) => l.trim());
    if (resultStr.includes('exit code: 0') || !resultStr.includes('exit code:')) {
      return lines.length > 1 ? `Success (${lines.length} lines)` : 'Success';
    }
    return `Failed - ${lines[0]?.slice(0, 50) || 'see output'}`;
  }
  if (toolName === 'read_file') {
    const lines = resultStr.split('\n').length;
    return `Read ${lines} line${lines !== 1 ? 's' : ''}`;
  }
  if (toolName === 'write_file' || toolName === 'edit_file') {
    return 'File updated';
  }
  if (toolName === 'search' || toolName === 'grep') {
    const matches = (resultStr.match(/\n/g) || []).length;
    return `${matches} match${matches !== 1 ? 'es' : ''}`;
  }

  if (resultStr.length <= 50) {
    return resultStr;
  }
  return `${resultStr.slice(0, 47)}...`;
}

/**
 * Format tool arguments for plan display.
 */
export function formatToolArgsForPlan(toolName: string, args: Record<string, unknown>): string {
  if (toolName === 'write_file') {
    const path = args.path || args.file_path;
    const content = String(args.content || '');
    const preview = content.slice(0, 100).replace(/\n/g, '\\n');
    return `File: ${path}\nContent preview: ${preview}${content.length > 100 ? '...' : ''}`;
  }
  if (toolName === 'edit_file') {
    const path = args.path || args.file_path;
    return `File: ${path}\nOld: ${String(args.old_string || args.search || '').slice(0, 50)}...\nNew: ${String(args.new_string || args.replace || '').slice(0, 50)}...`;
  }
  if (toolName === 'bash') {
    return `Command: ${String(args.command || '').slice(0, 100)}`;
  }
  if (toolName === 'delete_file') {
    return `Delete: ${args.path || args.file_path}`;
  }
  if (toolName === 'spawn_agent' || toolName === 'researcher') {
    const task = String(args.task || args.prompt || args.goal || '');
    const model = args.model ? ` (${args.model})` : '';
    const firstLine = task.split('\n')[0].slice(0, 100);
    return `${firstLine}${task.length > 100 ? '...' : ''}${model}`;
  }
  return `Args: ${JSON.stringify(args).slice(0, 100)}...`;
}

/**
 * Extract contextual reasoning for a proposed change in plan mode.
 */
export function extractChangeReasoning(
  toolCall: { name: string; arguments: unknown },
  messages: Message[],
): string {
  const assistantMsgs = messages
    .filter((m) => m.role === 'assistant' && typeof m.content === 'string')
    .slice(-3)
    .reverse();

  if (assistantMsgs.length === 0) {
    return `Proposed change: ${toolCall.name}`;
  }

  const lastMsg = assistantMsgs[0];
  const content = lastMsg.content as string;

  if (toolCall.name === 'spawn_agent') {
    const args = toolCall.arguments as Record<string, unknown>;
    const task = String(args.task || args.prompt || args.goal || '');
    if (task.length > 0) {
      const firstPara = task.split(/\n\n/)[0];
      return firstPara.length > 500 ? firstPara.slice(0, 500) + '...' : firstPara;
    }
  }

  if (['write_file', 'edit_file'].includes(toolCall.name)) {
    const args = toolCall.arguments as Record<string, unknown>;
    const path = String(args.path || args.file_path || '');

    if (path && content.toLowerCase().includes(path.toLowerCase().split('/').pop() || '')) {
      const sentences = content
        .split(/[.!?\n]+/)
        .filter((s) => s.toLowerCase().includes(path.toLowerCase().split('/').pop() || ''));
      if (sentences.length > 0) {
        const relevant = sentences.slice(0, 2).join('. ').trim();
        return relevant.length > 500 ? relevant.slice(0, 500) + '...' : relevant;
      }
    }
  }

  const paragraphs = content.split(/\n\n+/).filter((p) => p.trim().length > 20);
  if (paragraphs.length > 0) {
    const firstPara = paragraphs[0].trim();
    return firstPara.length > 500 ? firstPara.slice(0, 500) + '...' : firstPara;
  }

  return content.length > 500 ? content.slice(0, 500) + '...' : content;
}
