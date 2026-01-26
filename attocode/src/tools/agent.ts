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
 * Input type for spawn_agent tool.
 */
export interface SpawnAgentInput {
  agent: SpawnableAgent;
  task: string;
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
Use this for tasks that benefit from specialized focus or parallel work.`;

// =============================================================================
// BOUND TOOL FACTORY
// =============================================================================

/**
 * Type for the spawn function provided by ProductionAgent.
 */
export type SpawnFunction = (agentName: string, task: string) => Promise<SpawnResult>;

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

      const result = await spawnFn(input.agent, input.task);

      return {
        success: result.success,
        output: result.output,
        metadata: {
          agent: input.agent,
          task: input.task,
          metrics: result.metrics,
        },
      };
    },
  };
}
