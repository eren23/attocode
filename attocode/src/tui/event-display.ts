/**
 * Event Display
 *
 * Creates event handlers for displaying agent events in the console
 * and logging critical junctures to SQLite.
 */

import type { AgentEvent } from '../types.js';
import type { SQLiteStore } from '../integrations/index.js';

// ANSI color codes for terminal output
const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  white: '\x1b[37m',
};

function c(text: string, color: keyof typeof colors): string {
  return `${colors[color]}${text}${colors.reset}`;
}

/**
 * Create an event display handler for console output.
 * Returns a function that handles AgentEvents and logs them to console.
 */
export function createEventDisplay() {
  return (event: AgentEvent): void => {
    switch (event.type) {
      case 'start':
        console.log(c(`\n Starting task...`, 'dim'));
        break;

      case 'planning':
        console.log(c(`\n Plan created with ${event.plan.tasks.length} steps:`, 'blue'));
        event.plan.tasks.forEach((t, i) => {
          console.log(c(`   ${i + 1}. ${t.description}`, 'dim'));
        });
        break;

      case 'task.start':
        console.log(c(`\n> Starting: ${event.task.description}`, 'cyan'));
        break;

      case 'task.complete':
        console.log(c(`   Completed: ${event.task.description}`, 'green'));
        break;

      case 'llm.start':
        console.log(c(`\n Calling LLM (${event.model})...`, 'dim'));
        break;

      case 'llm.complete':
        if (event.response.usage) {
          console.log(c(
            `   Tokens: ${event.response.usage.inputTokens} in / ${event.response.usage.outputTokens} out`,
            'dim'
          ));
        }
        break;

      case 'tool.start':
        console.log(c(`\n Tool: ${event.tool}`, 'cyan'));
        const argsStr = JSON.stringify(event.args, null, 2).split('\n').join('\n   ');
        console.log(c(`   Args: ${argsStr}`, 'dim'));
        break;

      case 'tool.complete':
        const output = String(event.result).split('\n')[0].slice(0, 200);
        console.log(c(`   ${output}${String(event.result).length > 200 ? '...' : ''}`, 'green'));
        break;

      case 'tool.blocked':
        console.log(c(`   Blocked: ${event.reason}`, 'red'));
        break;

      case 'approval.required':
        console.log(c(`\n Approval required: ${event.request.action}`, 'yellow'));
        break;

      case 'reflection':
        console.log(c(`\n Reflection (attempt ${event.attempt}): ${event.satisfied ? 'satisfied' : 'refining'}`, 'magenta'));
        break;

      case 'memory.retrieved':
        console.log(c(`\n Retrieved ${event.count} relevant memories`, 'blue'));
        break;

      case 'react.thought':
        console.log(c(`\n Thought ${event.step}: ${event.thought}`, 'cyan'));
        break;

      case 'react.action':
        console.log(c(`   Action: ${event.action}`, 'yellow'));
        break;

      case 'react.observation':
        console.log(c(`   Observation: ${event.observation.slice(0, 100)}...`, 'dim'));
        break;

      case 'react.answer':
        console.log(c(`\n Answer: ${event.answer}`, 'green'));
        break;

      case 'multiagent.spawn':
        console.log(c(`\n Spawning agent: ${event.role} (${event.agentId})`, 'magenta'));
        break;

      case 'multiagent.complete':
        console.log(c(`   ${event.success ? '+' : 'x'} Agent ${event.agentId} finished`, event.success ? 'green' : 'red'));
        break;

      case 'agent.spawn':
        console.log(c(`\n Spawning subagent: ${(event as any).name || event.agentId}`, 'magenta'));
        if ((event as any).task) {
          console.log(c(`   Task: ${(event as any).task}`, 'dim'));
        }
        break;

      case 'agent.complete':
        console.log(c(`   ${event.success ? '+' : 'x'} Subagent ${event.agentId} finished`, event.success ? 'green' : 'red'));
        break;

      case 'agent.error':
        console.log(c(`   Subagent error: ${(event as any).error}`, 'yellow'));
        break;

      case 'agent.registered':
        console.log(c(`   Agent registered: ${(event as any).name}`, 'green'));
        break;

      case 'consensus.start':
        console.log(c(`\n Building consensus (${event.strategy})...`, 'blue'));
        break;

      case 'consensus.reached':
        console.log(c(`   ${event.agreed ? '+' : 'x'} Consensus: ${event.result.slice(0, 100)}`, event.agreed ? 'green' : 'yellow'));
        break;

      case 'checkpoint.created':
        console.log(c(`\n Checkpoint: ${event.label || event.checkpointId}`, 'blue'));
        break;

      case 'checkpoint.restored':
        console.log(c(`\n Restored checkpoint: ${event.checkpointId}`, 'yellow'));
        break;

      case 'rollback':
        console.log(c(`\n Rolled back ${event.steps} steps`, 'yellow'));
        break;

      case 'thread.forked':
        console.log(c(`\n Forked thread: ${event.threadId}`, 'cyan'));
        break;

      case 'error':
        console.log(c(`\n Error: ${event.error}`, 'red'));
        break;

      case 'complete':
        console.log(c(`\n Task ${event.result.success ? 'completed' : 'failed'}`, event.result.success ? 'green' : 'red'));
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
