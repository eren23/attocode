/**
 * Event Display
 *
 * Creates event handlers for displaying agent events in the console
 * and logging critical junctures to SQLite.
 */

import type { AgentEvent } from '../types.js';
import type { SQLiteStore } from '../integrations/index.js';
import { logger } from '../integrations/utilities/logger.js';

/**
 * Create an event display handler for console output.
 * Returns a function that handles AgentEvents and logs them to console.
 */
export function createEventDisplay() {
  return (event: AgentEvent): void => {
    switch (event.type) {
      case 'start':
        logger.debug('Starting task');
        break;

      case 'planning':
        logger.debug('Plan created', {
          steps: event.plan.tasks.length,
          tasks: event.plan.tasks.map((t, i) => `${i + 1}. ${t.description}`),
        });
        break;

      case 'task.start':
        logger.debug('Task starting', { description: event.task.description });
        break;

      case 'task.complete':
        logger.debug('Task completed', { description: event.task.description });
        break;

      case 'llm.start':
        logger.debug('Calling LLM', { model: event.model });
        break;

      case 'llm.complete':
        if (event.response.usage) {
          logger.debug('LLM response tokens', {
            inputTokens: event.response.usage.inputTokens,
            outputTokens: event.response.usage.outputTokens,
            cacheReadTokens: event.response.usage.cacheReadTokens || 0,
            cacheWriteTokens: event.response.usage.cacheWriteTokens || 0,
          });
        }
        break;

      case 'tool.start':
        logger.debug('Tool invoked', { tool: event.tool, args: event.args });
        break;

      case 'tool.complete':
        logger.debug('Tool completed', { result: String(event.result).slice(0, 200) });
        break;

      case 'tool.blocked':
        logger.warn('Tool blocked', { reason: event.reason });
        break;

      case 'approval.required':
        logger.debug('Approval required', { action: event.request.action });
        break;

      case 'reflection':
        logger.debug('Reflection', { attempt: event.attempt, satisfied: event.satisfied });
        break;

      case 'memory.retrieved':
        logger.debug('Memory retrieved', { count: event.count });
        break;

      case 'react.thought':
        logger.debug('ReAct thought', { step: event.step, thought: event.thought });
        break;

      case 'react.action':
        logger.debug('ReAct action', { action: event.action });
        break;

      case 'react.observation':
        logger.debug('ReAct observation', { observation: event.observation.slice(0, 100) });
        break;

      case 'react.answer':
        logger.debug('ReAct answer', { answer: event.answer });
        break;

      case 'multiagent.spawn':
        logger.debug('Spawning agent', { role: event.role, agentId: event.agentId });
        break;

      case 'multiagent.complete':
        logger.debug('Agent finished', { agentId: event.agentId, success: event.success });
        break;

      case 'agent.spawn':
        logger.debug('Spawning subagent', {
          name: (event as any).name || event.agentId,
          task: (event as any).task,
        });
        break;

      case 'agent.complete':
        logger.debug('Subagent finished', { agentId: event.agentId, success: event.success });
        break;

      case 'agent.error':
        logger.error('Subagent error', { error: String((event as any).error) });
        break;

      case 'agent.registered':
        logger.debug('Agent registered', { name: (event as any).name });
        break;

      case 'consensus.start':
        logger.debug('Building consensus', { strategy: event.strategy });
        break;

      case 'consensus.reached':
        logger.debug('Consensus reached', {
          agreed: event.agreed,
          result: event.result.slice(0, 100),
        });
        break;

      case 'checkpoint.created':
        logger.debug('Checkpoint created', { label: event.label || event.checkpointId });
        break;

      case 'checkpoint.restored':
        logger.debug('Checkpoint restored', { checkpointId: event.checkpointId });
        break;

      case 'rollback':
        logger.debug('Rolled back', { steps: event.steps });
        break;

      case 'thread.forked':
        logger.debug('Thread forked', { threadId: event.threadId });
        break;

      case 'error':
        logger.error('Agent error', { error: String(event.error) });
        break;

      case 'complete':
        logger.debug('Task complete', { success: event.result.success });
        break;
    }
  };
}

/**
 * Create a juncture logger that captures critical moments from agent events.
 * Requires a SQLite store to persist junctures.
 */
export function createJunctureLogger(store: SQLiteStore) {
  return (event: AgentEvent): void => {
    switch (event.type) {
      case 'tool.blocked':
        store.logJuncture('failure', `Tool blocked: ${(event as any).tool || 'unknown'}`, {
          outcome: (event as any).reason,
          importance: 2,
        });
        break;

      case 'agent.error':
        store.logJuncture('failure', `Subagent error: ${(event as any).agentId}`, {
          outcome: String((event as any).error),
          importance: 1,
        });
        break;

      case 'error':
        store.logJuncture('failure', `Error: ${(event as any).error}`, {
          importance: 1,
        });
        break;

      case 'complete':
        if (!event.result.success) {
          store.logJuncture('failure', 'Task failed', {
            outcome: (event.result as any).output?.slice(0, 200) || 'No output',
            importance: 1,
          });
        }
        break;

      case 'reflection':
        // Log when reflection requires multiple attempts (indicates difficulty)
        if ((event as any).attempt > 2) {
          store.logJuncture('pivot', `Reflection required ${(event as any).attempt} attempts`, {
            outcome: (event as any).satisfied ? 'resolved' : 'ongoing',
            importance: 3,
          });
        }
        break;
    }
  };
}
