/**
 * Spawn Agent Tool
 *
 * Allows the LLM to autonomously spawn specialized subagents
 * to handle tasks. This bridges the gap between the AgentRegistry
 * (which defines available agents) and the LLM's ability to delegate work.
 */

import type { ToolDefinition } from '../types.js';
import type { SpawnResult } from '../integrations/agent-registry.js';

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * Available agent types that can be spawned.
 */
export const SPAWNABLE_AGENTS = [
  'researcher',
  'coder',
  'reviewer',
  'architect',
  'debugger',
  'documenter',
] as const;

export type SpawnableAgent = typeof SPAWNABLE_AGENTS[number];

/**
 * Spawn constraints for focused execution.
 * Optional limits to keep subagents on-task.
 */
export interface SpawnConstraints {
  /** Hard budget limit for tokens consumed */
  maxTokens?: number;
  /** Directories/files to focus on (glob patterns) */
  focusAreas?: string[];
  /** Directories/files to avoid (glob patterns) */
  excludeAreas?: string[];
  /** Required outputs - agent must produce these */
  requiredDeliverables?: string[];
  /** Soft time limit in minutes (agent will be warned) */
  timeboxMinutes?: number;
}

/**
 * Input type for spawn_agent tool.
 */
export interface SpawnAgentInput {
  agent: SpawnableAgent;
  task: string;
  constraints?: SpawnConstraints;
}

// =============================================================================
// TOOL DEFINITION
// =============================================================================

/**
 * JSON Schema parameters for the spawn_agent tool.
 */
const spawnAgentParameters: Record<string, unknown> = {
  type: 'object',
  properties: {
    agent: {
      type: 'string',
      enum: SPAWNABLE_AGENTS,
      description: 'The specialized agent to spawn',
    },
    task: {
      type: 'string',
      description: 'The specific task for the agent to complete',
    },
    constraints: {
      type: 'object',
      description: 'Optional constraints to keep the subagent focused',
      properties: {
        maxTokens: {
          type: 'number',
          description: 'Hard budget limit for tokens consumed',
        },
        focusAreas: {
          type: 'array',
          items: { type: 'string' },
          description: 'Directories/files to focus on (glob patterns like "src/**/*.ts")',
        },
        excludeAreas: {
          type: 'array',
          items: { type: 'string' },
          description: 'Directories/files to avoid (glob patterns)',
        },
        requiredDeliverables: {
          type: 'array',
          items: { type: 'string' },
          description: 'Required outputs the agent must produce',
        },
        timeboxMinutes: {
          type: 'number',
          description: 'Soft time limit in minutes',
        },
      },
    },
  },
  required: ['agent', 'task'],
};

/**
 * Description for the spawn_agent tool.
 */
const SPAWN_AGENT_DESCRIPTION = `Spawn a specialized subagent to handle a specific task autonomously.

Available agents:
- researcher: Explores codebases, finds files, gathers information
- coder: Writes and modifies code
- reviewer: Reviews code for quality, bugs, and best practices
- architect: Makes system design decisions
- debugger: Troubleshoots issues and investigates bugs
- documenter: Writes documentation

The subagent runs with its own context, executes the task, and returns results.
Use this for tasks that benefit from specialized focus or parallel work.

Optional constraints help keep subagents focused:
- focusAreas: Limit exploration to specific directories (e.g., ["src/api/**"])
- excludeAreas: Avoid certain directories (e.g., ["node_modules/**", "dist/**"])
- maxTokens: Set a hard token budget
- timeboxMinutes: Soft time warning`;

// =============================================================================
// BOUND TOOL FACTORY
// =============================================================================

/**
 * Type for the spawn function provided by ProductionAgent.
 */
export type SpawnFunction = (agentName: string, task: string, constraints?: SpawnConstraints) => Promise<SpawnResult>;

/**
 * Create a spawn_agent tool bound to a specific agent's spawnAgent method.
 *
 * @param spawnFn - The agent's spawnAgent method
 * @returns A ToolDefinition that can be registered and used by the LLM
 *
 * @example
 * ```typescript
 * // In ProductionAgent.initializeFeatures():
 * if (this.agentRegistry) {
 *   const boundTool = createBoundSpawnAgentTool(
 *     (name, task) => this.spawnAgent(name, task)
 *   );
 *   this.tools.set(boundTool.name, boundTool);
 * }
 * ```
 */
export function createBoundSpawnAgentTool(spawnFn: SpawnFunction): ToolDefinition {
  return {
    name: 'spawn_agent',
    description: SPAWN_AGENT_DESCRIPTION,
    parameters: spawnAgentParameters,
    dangerLevel: 'moderate',
    execute: async (args: Record<string, unknown>) => {
      const input = args as unknown as SpawnAgentInput;

      // Validate agent name
      if (!SPAWNABLE_AGENTS.includes(input.agent as SpawnableAgent)) {
        return {
          success: false,
          output: `Invalid agent: ${input.agent}. Available agents: ${SPAWNABLE_AGENTS.join(', ')}`,
        };
      }

      // Validate task
      if (!input.task || typeof input.task !== 'string') {
        return {
          success: false,
          output: 'Task is required and must be a string',
        };
      }

      const result = await spawnFn(input.agent, input.task, input.constraints);

      // Append structured summary to output when available
      const structuredSummary = result.structured
        ? `\n\n**Subagent Structured Report:**\n` +
          `Exit: ${result.structured.exitReason}\n` +
          `Findings: ${result.structured.findings.join('; ') || 'none'}\n` +
          `Actions: ${result.structured.actionsTaken.join('; ') || 'none'}\n` +
          `Failures: ${result.structured.failures.join('; ') || 'none'}\n` +
          `Remaining: ${result.structured.remainingWork.join('; ') || 'none'}\n` +
          (result.structured.suggestedNextSteps?.length
            ? `Next steps: ${result.structured.suggestedNextSteps.join('; ')}\n` : '')
        : '';

      return {
        success: result.success,
        output: result.output + structuredSummary,
        metadata: {
          agent: input.agent,
          task: input.task,
          constraints: input.constraints,
          metrics: result.metrics,
          structured: result.structured,
        },
      };
    },
  };
}

// =============================================================================
// PARALLEL SPAWN TOOL
// =============================================================================

/**
 * Input type for spawn_agents_parallel tool.
 */
export interface SpawnAgentsParallelInput {
  tasks: Array<{
    agent: string;
    task: string;
  }>;
}

/**
 * Type for the parallel spawn function.
 */
export type ParallelSpawnFunction = (
  tasks: Array<{ agent: string; task: string }>
) => Promise<SpawnResult[]>;

/**
 * JSON Schema parameters for the spawn_agents_parallel tool.
 */
const spawnAgentsParallelParameters: Record<string, unknown> = {
  type: 'object',
  properties: {
    tasks: {
      type: 'array',
      description: 'Array of tasks to execute in parallel',
      items: {
        type: 'object',
        properties: {
          agent: {
            type: 'string',
            description: 'The specialized agent to spawn (researcher, coder, reviewer, etc.)',
          },
          task: {
            type: 'string',
            description: 'The specific task for this agent to complete',
          },
        },
        required: ['agent', 'task'],
      },
      minItems: 2,
      maxItems: 5,
    },
  },
  required: ['tasks'],
};

/**
 * Description for the spawn_agents_parallel tool.
 */
const SPAWN_AGENTS_PARALLEL_DESCRIPTION = `Spawn multiple subagents to work on independent tasks in parallel.

Use this when you have 2+ tasks that:
- Are independent (don't depend on each other's results)
- Can benefit from parallel execution
- Each require different specializations or focus areas

Example use cases:
- Research two different parts of a codebase simultaneously
- Create multiple files at once (with different agents)
- Run code review while implementing related changes

The agents share a coordination blackboard to:
- Avoid duplicate work
- Prevent file edit conflicts
- Share discoveries across agents

Returns results from all agents once they complete.`;

/**
 * Create a spawn_agents_parallel tool bound to a specific agent's parallel spawn method.
 */
export function createBoundSpawnAgentsParallelTool(
  parallelSpawnFn: ParallelSpawnFunction
): ToolDefinition {
  return {
    name: 'spawn_agents_parallel',
    description: SPAWN_AGENTS_PARALLEL_DESCRIPTION,
    parameters: spawnAgentsParallelParameters,
    dangerLevel: 'moderate',
    execute: async (args: Record<string, unknown>) => {
      const input = args as unknown as SpawnAgentsParallelInput;

      // Validate tasks array
      if (!Array.isArray(input.tasks) || input.tasks.length < 2) {
        return {
          success: false,
          output: 'At least 2 tasks are required for parallel execution. Use spawn_agent for single tasks.',
        };
      }

      if (input.tasks.length > 5) {
        return {
          success: false,
          output: 'Maximum 5 parallel tasks allowed. Split into batches if needed.',
        };
      }

      // Validate each task
      for (const task of input.tasks) {
        if (!task.agent || typeof task.agent !== 'string') {
          return {
            success: false,
            output: 'Each task must have an agent name',
          };
        }
        if (!task.task || typeof task.task !== 'string') {
          return {
            success: false,
            output: 'Each task must have a task description',
          };
        }
      }

      const results = await parallelSpawnFn(input.tasks);

      // Aggregate results
      const successCount = results.filter(r => r.success).length;
      const totalTokens = results.reduce((sum, r) => sum + (r.metrics?.tokens || 0), 0);
      const totalDuration = Math.max(...results.map(r => r.metrics?.duration || 0));

      const outputs = results.map((r, i) => {
        const task = input.tasks[i];
        return `## ${task.agent} (${r.success ? '✓' : '✗'})\n${r.output}`;
      }).join('\n\n');

      return {
        success: successCount === results.length,
        output: `Parallel execution complete: ${successCount}/${results.length} succeeded\n\n${outputs}`,
        metadata: {
          tasks: input.tasks,
          results: results.map(r => ({ success: r.success, metrics: r.metrics })),
          aggregateMetrics: {
            totalTokens,
            wallClockDuration: totalDuration,
            successRate: successCount / results.length,
          },
        },
      };
    },
  };
}
