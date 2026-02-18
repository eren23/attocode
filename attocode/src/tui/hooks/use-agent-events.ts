/**
 * useAgentEvents Hook
 *
 * Extracted from TUIApp — handles all agent event subscriptions and state updates.
 * Consolidates the unified event handler + transparency aggregator subscription
 * into a single hook, isolating the event-driven state from the rest of TUIApp.
 */

import { useCallback, useEffect, useRef } from 'react';
import type { AgentEvent } from '../../types.js';
import type { ActiveAgentStatus } from '../components/ActiveAgentsPanel.js';
import type { ToolCallDisplayItem } from '../components/ToolCallItem.js';
import type { Task } from '../../integrations/tasks/task-manager.js';
import type { SwarmStatus } from '../../integrations/swarm/types.js';
import {
  TransparencyAggregator,
  type TransparencyState,
} from '../transparency-aggregator.js';

// Narrow agent interface — only what the hook needs
export interface AgentEventSource {
  subscribe(listener: (event: AgentEvent) => void): () => void;
}

export interface UseAgentEventsRefs {
  executionModeRef: React.MutableRefObject<string>;
  showThinkingRef: React.MutableRefObject<boolean>;
  debugExpandedRef: React.MutableRefObject<boolean>;
}

export interface UseAgentEventsSetters {
  setStatusThrottled: (
    updater: (s: { iter: number; tokens: number; cost: number; mode: string }) => {
      iter: number;
      tokens: number;
      cost: number;
      mode: string;
    },
  ) => void;
  flushStatusThrottle: () => void;
  setToolCalls: React.Dispatch<React.SetStateAction<ToolCallDisplayItem[]>>;
  setActiveAgents: React.Dispatch<React.SetStateAction<import('../components/ActiveAgentsPanel.js').ActiveAgent[]>>;
  setTasks: React.Dispatch<React.SetStateAction<Task[]>>;
  setSwarmStatus: React.Dispatch<React.SetStateAction<SwarmStatus | null>>;
  setTransparencyState: React.Dispatch<React.SetStateAction<TransparencyState | null>>;
}

export interface UseAgentEventsOptions {
  agent: AgentEventSource;
  refs: UseAgentEventsRefs;
  setters: UseAgentEventsSetters;
  addMessage: (role: string, content: string) => void;
  debugBuffer: { debug: (msg: string, data?: Record<string, unknown>) => void };
}

/**
 * Returns a ref to the TransparencyAggregator (for external access if needed).
 */
export function useAgentEvents({
  agent,
  refs,
  setters,
  addMessage,
  debugBuffer,
}: UseAgentEventsOptions): React.MutableRefObject<TransparencyAggregator | null> {
  const { executionModeRef, showThinkingRef, debugExpandedRef } = refs;
  const {
    setStatusThrottled,
    flushStatusThrottle,
    setToolCalls,
    setActiveAgents,
    setTasks,
    setSwarmStatus,
    setTransparencyState,
  } = setters;

  const transparencyAggregatorRef = useRef<TransparencyAggregator | null>(null);
  // Track pending timers for cleanup on unmount (Fix 11)
  const pendingTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  // =========================================================================
  // UNIFIED EVENT HANDLER
  // Consolidated handler for all agent events - prevents duplicate messages
  // =========================================================================

  const handleAgentEvent = useCallback(
    (event: AgentEvent) => {
      const mode = executionModeRef.current;
      if (mode === 'idle' || mode === 'draining') return; // No active execution or draining after cancellation

      // Log event to debug buffer (use ref to avoid dep churn)
      if (debugExpandedRef.current) {
        debugBuffer.debug(`Event: ${event.type}`, event as Record<string, unknown>);
      }

      // Extract subagent from event if present (not all events have it)
      const eventWithSubagent = event as { subagent?: string };
      const subagentPrefix = eventWithSubagent.subagent
        ? `[${eventWithSubagent.subagent}] `
        : '';

      // -----------------------------------------------------------------------
      // Approving-only events (plan execution)
      // -----------------------------------------------------------------------
      if (mode === 'approving') {
        if (event.type === 'plan.approved') {
          const e = event as { changeCount: number };
          addMessage('system', `[PLAN] Executing ${e.changeCount} change(s)...`);
          return;
        }
        if (event.type === 'plan.executing') {
          const e = event as { changeIndex: number; totalChanges: number };
          setStatusThrottled((s) => ({
            ...s,
            mode: `executing ${e.changeIndex + 1}/${e.totalChanges}`,
          }));
          return;
        }
      }

      // -----------------------------------------------------------------------
      // Shared events (both processing and approving modes)
      // -----------------------------------------------------------------------

      // Subagent lifecycle events - also update Active Agents Panel
      if (event.type === 'agent.spawn') {
        const e = event as { agentId: string; name: string; task: string };
        const agentId = e.agentId || `spawn-${Date.now()}`;
        addMessage(
          'system',
          `[AGENT] Spawning ${e.name}: ${e.task.slice(0, 100)}${e.task.length > 100 ? '...' : ''}`,
        );
        setActiveAgents((prev) => {
          const now = Date.now();
          // Evict stale completed/errored agents (>30s old) to prevent unbounded growth
          const active = prev.filter(a =>
            a.status === 'running' || a.status === 'timing_out' ||
            (now - (a.completedAt ?? a.startTime)) < 30000
          );
          return [
            ...active,
            {
              id: agentId,
              type: e.name,
              task: e.task,
              status: 'running' as ActiveAgentStatus,
              tokens: 0,
              startTime: now,
            },
          ];
        });
        return;
      }
      if (event.type === 'agent.complete') {
        const e = event as {
          agentId: string;
          agentType?: string;
          success: boolean;
          output?: string;
        };
        const statusText = e.success ? 'completed' : 'failed';
        const displayName = e.agentType || e.agentId;
        addMessage('system', `[AGENT] ${displayName} ${statusText}`);
        if (e.output && e.output.length > 50) {
          const preview = e.output.slice(0, 1000);
          const truncated = e.output.length > 1000;
          addMessage(
            'system',
            `[AGENT OUTPUT]\n${preview}${truncated ? `\n...(full output: ${e.output.length} chars)` : ''}`,
          );
        }
        setActiveAgents((prev) =>
          prev.map((a) =>
            a.id === e.agentId
              ? {
                  ...a,
                  status: e.success
                    ? ('completed' as ActiveAgentStatus)
                    : ('error' as ActiveAgentStatus),
                  completedAt: Date.now(),
                }
              : a,
          ),
        );
        return;
      }
      if (event.type === 'agent.error') {
        const e = event as { agentId: string; agentType?: string; error: string };
        const displayName = e.agentType || e.agentId;
        addMessage('system', `[AGENT] ${displayName} error: ${e.error}`);

        const isTimeout = e.error.includes('timed out') || e.error.includes('Timed out');

        if (isTimeout) {
          setActiveAgents((prev) =>
            prev.map((a) =>
              a.id === e.agentId ? { ...a, status: 'timing_out' as ActiveAgentStatus } : a,
            ),
          );
          const timerId = setTimeout(() => {
            pendingTimersRef.current.delete(timerId);
            setActiveAgents((prev) =>
              prev.map((a) =>
                a.id === e.agentId && a.status === 'timing_out'
                  ? { ...a, status: 'timeout' as ActiveAgentStatus, completedAt: Date.now() }
                  : a,
              ),
            );
          }, 3000);
          pendingTimersRef.current.add(timerId);
        } else {
          setActiveAgents((prev) =>
            prev.map((a) =>
              a.id === e.agentId
                ? { ...a, status: 'error' as ActiveAgentStatus, completedAt: Date.now() }
                : a,
            ),
          );
        }
        return;
      }
      if (event.type === 'agent.pending_plan') {
        const e = event as { agentId: string; changes: Array<{ tool: string }> };
        addMessage(
          'system',
          `[AGENT] ${e.agentId} queued ${e.changes.length} change(s) to pending plan`,
        );
        return;
      }

      // Tool events
      if (event.type === 'tool.start') {
        const e = event as { tool: string; args?: Record<string, unknown>; subagent?: string };
        const displayName = e.subagent ? `${e.subagent}:${e.tool}` : e.tool;
        setStatusThrottled((s) => ({ ...s, mode: `calling ${displayName}` }));
        setToolCalls((prev) => [
          ...prev.slice(-4),
          {
            id: `${displayName}-${Date.now()}`,
            name: displayName,
            args: e.args || {},
            status: 'running',
            startTime: new Date(),
          },
        ]);
        return;
      }
      if (event.type === 'tool.complete') {
        const e = event as { tool: string; result?: unknown; subagent?: string };
        const displayName = e.subagent ? `${e.subagent}:${e.tool}` : e.tool;
        const modeText = e.subagent
          ? `${e.subagent} thinking`
          : mode === 'approving'
            ? 'executing plan'
            : 'thinking';
        setStatusThrottled((s) => ({ ...s, mode: modeText }));
        setToolCalls((prev) =>
          prev.map((t) =>
            t.name === displayName
              ? {
                  ...t,
                  status: 'success' as const,
                  result: e.result,
                  duration: t.startTime ? Date.now() - t.startTime.getTime() : undefined,
                }
              : t,
          ),
        );
        // Flush pending status immediately so StatusBar syncs with ToolCallsPanel
        flushStatusThrottle();
        return;
      }
      if (event.type === 'tool.blocked') {
        const e = event as { tool: string; reason?: string; subagent?: string };
        const displayName = e.subagent ? `${e.subagent}:${e.tool}` : e.tool;
        setToolCalls((prev) =>
          prev.map((t) =>
            t.name === displayName
              ? {
                  ...t,
                  status: 'error' as const,
                  error: e.reason || 'Blocked',
                }
              : t,
          ),
        );
        return;
      }

      // LLM events
      if (event.type === 'llm.start') {
        const e = event as { subagent?: string };
        const modeText = e.subagent
          ? `${e.subagent} thinking`
          : mode === 'approving'
            ? 'executing plan'
            : 'thinking';
        setStatusThrottled((s) => ({ ...s, mode: modeText, iter: s.iter + 1 }));
        return;
      }
      if (event.type === 'llm.complete' && eventWithSubagent.subagent && showThinkingRef.current) {
        const e = event as { response?: { thinking?: string; content?: string } };
        const thinking = e.response?.thinking;
        if (thinking) {
          const preview = thinking.length > 500 ? thinking.slice(0, 500) + '...' : thinking;
          addMessage('system', `[${eventWithSubagent.subagent}] ${preview}`);
        }
        return;
      }

      // Error events
      if (event.type === 'error') {
        const e = event as { error: string | { message?: string }; subagent?: string };
        const prefix = e.subagent ? `[${e.subagent} ERROR]` : '[ERROR]';
        const errorMsg =
          typeof e.error === 'string' ? e.error : e.error?.message || 'Unknown error';
        addMessage('error', `${prefix} ${errorMsg}`);
        return;
      }
      if (event.type === 'completion.blocked') {
        const e = event as {
          reasons: string[];
          openTasks?: { pending: number; inProgress: number; blocked: number };
          diagnostics?: {
            forceTextOnly?: boolean;
            availableTasks?: number;
            pendingWithOwner?: number;
          };
        };
        const details = e.reasons?.length
          ? e.reasons.join('\n')
          : 'Completion blocked by unresolved work.';
        const openTasksLine = e.openTasks
          ? `Open tasks: ${e.openTasks.pending} pending, ${e.openTasks.inProgress} in_progress, ${e.openTasks.blocked} blocked`
          : '';
        const constrainedLine = e.diagnostics?.forceTextOnly
          ? 'Task continuation is currently suppressed by budget/wrapup force-text mode.'
          : '';
        addMessage(
          'system',
          `[INCOMPLETE]\n${details}${openTasksLine ? `\n${openTasksLine}` : ''}${constrainedLine ? `\n${constrainedLine}` : ''}`,
        );
        setStatusThrottled((s) => ({ ...s, mode: 'incomplete' }));
        return;
      }

      // Insight events - also track tokens for active agents
      if (event.type === 'insight.tokens') {
        const e = event as {
          inputTokens: number;
          outputTokens: number;
          cacheReadTokens?: number;
          cacheWriteTokens?: number;
          cost?: number;
          subagent?: string;
        };
        if (showThinkingRef.current) {
          let cacheStr = '';
          if (e.cacheReadTokens && e.cacheReadTokens > 0) {
            cacheStr += ` [cached: ${e.cacheReadTokens.toLocaleString()}]`;
          }
          if (e.cacheWriteTokens && e.cacheWriteTokens > 0) {
            cacheStr += ` [cache-write: ${e.cacheWriteTokens.toLocaleString()}]`;
          }
          addMessage(
            'system',
            `${subagentPrefix}* ${e.inputTokens.toLocaleString()} in, ${e.outputTokens.toLocaleString()} out${cacheStr}${e.cost ? ` $${e.cost.toFixed(6)}` : ''}`,
          );
        }
        // Update tokens for active agent if this event is from a subagent
        if (e.subagent || eventWithSubagent.subagent) {
          const subagentId =
            (e as { subagentId?: string }).subagentId ||
            (eventWithSubagent as { subagentId?: string }).subagentId;
          const agentName = e.subagent || eventWithSubagent.subagent;
          setActiveAgents((prev) =>
            prev.map((a) => {
              const matchesAgent = subagentId
                ? a.id === subagentId
                : a.type === agentName || a.id.includes(agentName || '');
              const isStillRunning = a.status === 'running';
              if (matchesAgent && isStillRunning) {
                return { ...a, tokens: a.tokens + (e.inputTokens || 0) + (e.outputTokens || 0) };
              }
              return a;
            }),
          );
        }
        return;
      }

      // Resilience events
      if (event.type === 'resilience.retry') {
        const e = event as { reason: string; attempt: number; maxAttempts: number };
        addMessage('system', `[RETRY] ${e.reason} (${e.attempt}/${e.maxAttempts})`);
        return;
      }
      if (event.type === 'resilience.recovered') {
        const e = event as { reason: string; attempts: number };
        addMessage('system', `[RECOVERED] ${e.reason} after ${e.attempts} attempt(s)`);
        return;
      }

      // Subagent visibility events - also update Active Agents Panel
      if (event.type === 'subagent.iteration') {
        const e = event as {
          agentId: string;
          iteration: number;
          maxIterations: number;
          subagentId?: string;
        };
        setStatusThrottled((s) => ({
          ...s,
          mode: `${e.agentId} iter ${e.iteration}/${e.maxIterations}`,
        }));
        setActiveAgents((prev) =>
          prev.map((a) => {
            const matches = e.subagentId
              ? a.id === e.subagentId
              : a.type === e.agentId || a.id.includes(e.agentId);
            return matches ? { ...a, iteration: e.iteration, maxIterations: e.maxIterations } : a;
          }),
        );
        return;
      }
      if (event.type === 'subagent.phase') {
        const e = event as { agentId: string; phase: string; subagentId?: string };
        setStatusThrottled((s) => ({ ...s, mode: `${e.agentId} ${e.phase}` }));
        setActiveAgents((prev) =>
          prev.map((a) => {
            const matches = e.subagentId
              ? a.id === e.subagentId
              : a.type === e.agentId || a.id.includes(e.agentId);
            return matches ? { ...a, currentPhase: e.phase } : a;
          }),
        );
        return;
      }

      // Task events - update Tasks Panel
      if (event.type === 'task.created') {
        const e = event as unknown as { task: Task };
        setTasks((prev) => [...prev, e.task]);
        addMessage('system', `[TASK] Created: ${e.task.subject}`);
        return;
      }
      if (event.type === 'task.updated') {
        const e = event as unknown as { task: Task };
        setTasks((prev) => prev.map((t) => (t.id === e.task.id ? e.task : t)));
        addMessage('system', `[TASK] ${e.task.subject}: ${e.task.status}`);
        return;
      }

      // Swarm events - update Swarm Status Panel
      if (event.type === 'swarm.status') {
        const e = event as { status: SwarmStatus };
        setSwarmStatus(e.status);
        return;
      }
      if (event.type === 'swarm.start') {
        const e = event as { taskCount: number; waveCount: number };
        addMessage('system', `[SWARM] Starting: ${e.taskCount} tasks in ${e.waveCount} waves`);
        return;
      }
      if (event.type === 'swarm.wave.start') {
        const e = event as { wave: number; totalWaves: number; taskCount: number };
        addMessage(
          'system',
          `[SWARM] Wave ${e.wave}/${e.totalWaves}: dispatching ${e.taskCount} tasks`,
        );
        return;
      }
      if (event.type === 'swarm.wave.complete') {
        const e = event as {
          wave: number;
          totalWaves: number;
          completed: number;
          failed: number;
          skipped: number;
        };
        addMessage(
          'system',
          `[SWARM] Wave ${e.wave}/${e.totalWaves} complete: ${e.completed} done${e.failed > 0 ? `, ${e.failed} failed` : ''}${e.skipped > 0 ? `, ${e.skipped} skipped` : ''}`,
        );
        return;
      }
      if (event.type === 'swarm.task.dispatched') {
        const e = event as {
          taskId: string;
          workerName: string;
          model: string;
          description: string;
        };
        addMessage(
          'system',
          `[SWARM] ${e.taskId} -> ${e.workerName} (${e.model.split('/').pop()}): ${e.description.slice(0, 80)}`,
        );
        return;
      }
      if (event.type === 'swarm.task.completed') {
        const e = event as {
          taskId: string;
          success: boolean;
          tokensUsed: number;
          costUsed: number;
          durationMs: number;
        };
        addMessage(
          'system',
          `[SWARM] ${e.taskId} ${e.success ? 'completed' : 'failed'} (${(e.tokensUsed / 1000).toFixed(1)}k tokens, $${e.costUsed.toFixed(4)}, ${(e.durationMs / 1000).toFixed(1)}s)`,
        );
        return;
      }
      if (event.type === 'swarm.task.failed') {
        const e = event as { taskId: string; error: string; willRetry: boolean };
        addMessage(
          'system',
          `[SWARM] ${e.taskId} failed: ${e.error}${e.willRetry ? ' (will retry)' : ''}`,
        );
        return;
      }
      if (event.type === 'swarm.task.skipped') {
        const e = event as { taskId: string; reason: string };
        addMessage('system', `[SWARM] ${e.taskId} skipped: ${e.reason}`);
        return;
      }
      if (event.type === 'swarm.quality.rejected') {
        const e = event as { taskId: string; score: number; feedback: string };
        addMessage(
          'system',
          `[SWARM] ${e.taskId} quality rejected (${e.score}/5): ${e.feedback.slice(0, 100)}`,
        );
        return;
      }
      if (event.type === 'swarm.complete') {
        const e = event as {
          stats: {
            totalTasks: number;
            completedTasks: number;
            failedTasks: number;
            totalTokens: number;
            totalCost: number;
          };
        };
        addMessage(
          'system',
          `[SWARM] Complete: ${e.stats.completedTasks}/${e.stats.totalTasks} tasks, ${(e.stats.totalTokens / 1000).toFixed(0)}k tokens, $${e.stats.totalCost.toFixed(4)}`,
        );
        const swarmTimerId = setTimeout(() => {
          pendingTimersRef.current.delete(swarmTimerId);
          setSwarmStatus(null);
        }, 5000);
        pendingTimersRef.current.add(swarmTimerId);
        return;
      }
      if (event.type === 'swarm.error') {
        const e = event as { error: string; phase: string };
        addMessage('error', `[SWARM ERROR] ${e.phase}: ${e.error}`);
        return;
      }

      // -----------------------------------------------------------------------
      // Processing-only events (normal message submission)
      // -----------------------------------------------------------------------
      if (mode === 'processing') {
        if (event.type === 'plan.change.queued') {
          const e = event as { tool: string; summary?: string; subagent?: string };
          const summary = e.summary ? `: ${e.summary}` : '';
          const prefix = e.subagent ? `[${e.subagent} PLAN]` : '[PLAN]';
          addMessage('system', `${prefix} Queued ${e.tool}${summary}`);
          return;
        }
        if (event.type === 'plan.change.complete') {
          const e = event as {
            changeIndex: number;
            tool: string;
            result: unknown;
            error?: string;
          };
          if (e.error) {
            addMessage('system', `[PLAN ${e.changeIndex + 1}] ${e.tool} FAILED: ${e.error}`);
          } else if (e.tool === 'spawn_agent' && e.result) {
            const output =
              typeof e.result === 'object' && e.result !== null && 'output' in e.result
                ? String((e.result as { output: unknown }).output)
                : String(e.result);
            const preview =
              output.length > 800 ? output.slice(0, 800) + '\n... (truncated)' : output;
            addMessage('system', `[PLAN ${e.changeIndex + 1}] ${e.tool} result:\n${preview}`);
          } else {
            addMessage('system', `[PLAN ${e.changeIndex + 1}] ${e.tool} completed`);
          }
          return;
        }
        if (event.type === 'cache.hit' && showThinkingRef.current) {
          const e = event as { query: string; similarity: number };
          addMessage('system', `[CACHE HIT] similarity: ${(e.similarity * 100).toFixed(0)}%`);
          return;
        }
        if (event.type === 'cache.miss' && showThinkingRef.current) {
          addMessage('system', `[CACHE MISS]`);
          return;
        }
        if (event.type === 'compaction.auto') {
          const e = event as {
            tokensBefore: number;
            tokensAfter: number;
            messagesCompacted: number;
          };
          const before = (e.tokensBefore / 1000).toFixed(1);
          const after = (e.tokensAfter / 1000).toFixed(1);
          addMessage(
            'system',
            `[COMPACT] ${before}k -> ${after}k tokens (${e.messagesCompacted} messages)`,
          );
          return;
        }
        if (event.type === 'compaction.warning' && showThinkingRef.current) {
          const e = event as { currentTokens: number; threshold: number };
          const pct = Math.round((e.currentTokens / e.threshold) * 100);
          addMessage('system', `[!] Context at ${pct}% of threshold`);
          return;
        }
      }
    },
    // State setters (setToolCalls, setActiveAgents, etc.) are intentionally
    // omitted — React guarantees setter identity stability across renders.
    [addMessage],
  );

  // Set up transparency aggregator and subscribe to agent events
  useEffect(() => {
    const aggregator = new TransparencyAggregator();
    transparencyAggregatorRef.current = aggregator;

    let lastNotifiedState: TransparencyState | null = null;
    const unsubscribeAggregator = aggregator.subscribe((state) => {
      if (state !== lastNotifiedState) {
        lastNotifiedState = state;
        setTransparencyState(state);
      }
    });

    const unsubscribeAgent = agent.subscribe((event: AgentEvent) => {
      aggregator.processEvent(event);
      handleAgentEvent(event);
    });

    return () => {
      unsubscribeAggregator();
      unsubscribeAgent();
      // Clean up any pending timers (Fix 11)
      pendingTimersRef.current.forEach(clearTimeout);
      pendingTimersRef.current.clear();
    };
  }, [agent, handleAgentEvent]);

  return transparencyAggregatorRef;
}
