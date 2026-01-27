/**
 * Lesson 25: Multi-Agent Integration
 *
 * Integrates multi-agent coordination (from Lesson 17) into
 * the production agent. Enables team-based execution with
 * consensus and role-based task distribution.
 */

import type { LLMProvider, ToolDefinition, AgentResult as BaseAgentResult } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Agent role definition.
 */
export interface AgentRole {
  name: string;
  description: string;
  systemPrompt: string;
  capabilities: string[];
  authority: number; // 0-10, higher = more authority
  model?: string;
}

/**
 * Multi-agent team configuration.
 */
export interface TeamConfig {
  roles: AgentRole[];
  consensusStrategy: ConsensusStrategy;
  communicationMode: 'broadcast' | 'directed';
  coordinatorRole?: string; // Role that coordinates, defaults to highest authority
}

export type ConsensusStrategy =
  | 'voting'
  | 'authority'
  | 'unanimous'
  | 'first-complete';

/**
 * Task for team execution.
 */
export interface TeamTask {
  id: string;
  goal: string;
  context?: string;
  requiredCapabilities?: string[];
  deadline?: Date;
}

/**
 * Individual agent result.
 */
export interface AgentTaskResult {
  agentId: string;
  role: string;
  success: boolean;
  output: string;
  artifacts?: Artifact[];
  confidence?: number;
}

export interface Artifact {
  type: string;
  name: string;
  content: string;
}

/**
 * Team execution result.
 */
export interface TeamResult {
  success: boolean;
  task: TeamTask;
  agentResults: AgentTaskResult[];
  consensus?: Decision;
  coordinator: string;
  duration: number;
}

export interface Decision {
  agreed: boolean;
  result: string;
  votes: Map<string, boolean>;
  dissent: string[];
}

/**
 * Multi-agent events.
 */
export type MultiAgentEvent =
  | { type: 'team.start'; task: TeamTask }
  | { type: 'agent.spawn'; agentId: string; role: string }
  | { type: 'agent.working'; agentId: string; status: string }
  | { type: 'agent.complete'; agentId: string; result: AgentTaskResult }
  | { type: 'consensus.start'; strategy: ConsensusStrategy }
  | { type: 'consensus.vote'; agentId: string; vote: boolean }
  | { type: 'consensus.reached'; decision: Decision }
  | { type: 'team.complete'; result: TeamResult };

export type MultiAgentEventListener = (event: MultiAgentEvent) => void;

// =============================================================================
// MULTI-AGENT MANAGER
// =============================================================================

/**
 * MultiAgentManager coordinates team-based task execution.
 */
export class MultiAgentManager {
  private roles = new Map<string, AgentRole>();
  private provider: LLMProvider;
  private tools: ToolDefinition[];
  private listeners: MultiAgentEventListener[] = [];

  constructor(
    provider: LLMProvider,
    tools: ToolDefinition[],
    initialRoles?: AgentRole[]
  ) {
    this.provider = provider;
    this.tools = tools;

    if (initialRoles) {
      for (const role of initialRoles) {
        this.roles.set(role.name, role);
      }
    }
  }

  /**
   * Register an agent role.
   */
  registerRole(role: AgentRole): void {
    this.roles.set(role.name, role);
  }

  /**
   * Get all registered roles.
   */
  getRoles(): AgentRole[] {
    return Array.from(this.roles.values());
  }

  /**
   * Find roles with specific capability.
   */
  findRolesWithCapability(capability: string): AgentRole[] {
    return this.getRoles().filter(r => r.capabilities.includes(capability));
  }

  /**
   * Execute task with a team.
   */
  async runWithTeam(
    task: TeamTask,
    config: TeamConfig
  ): Promise<TeamResult> {
    const startTime = Date.now();

    this.emit({ type: 'team.start', task });

    // Select coordinator (highest authority or specified)
    const coordinator = this.selectCoordinator(config);

    // Select agents for task based on capabilities
    const selectedRoles = this.selectAgents(task, config);

    // Spawn agents and run in parallel
    const agentResults = await this.runAgents(task, selectedRoles);

    // Build consensus if multiple agents
    let consensus: Decision | undefined;
    if (agentResults.length > 1) {
      consensus = await this.buildConsensus(
        agentResults,
        config.consensusStrategy
      );
    }

    const result: TeamResult = {
      success: consensus ? consensus.agreed : agentResults[0]?.success ?? false,
      task,
      agentResults,
      consensus,
      coordinator: coordinator.name,
      duration: Date.now() - startTime,
    };

    this.emit({ type: 'team.complete', result });

    return result;
  }

  /**
   * Subscribe to events.
   */
  on(listener: MultiAgentEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // -------------------------------------------------------------------------
  // PRIVATE METHODS
  // -------------------------------------------------------------------------

  private emit(event: MultiAgentEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  private selectCoordinator(config: TeamConfig): AgentRole {
    if (config.coordinatorRole) {
      const role = this.roles.get(config.coordinatorRole);
      if (role) return role;
    }

    // Default to highest authority
    return config.roles.reduce((max, role) =>
      role.authority > max.authority ? role : max
    );
  }

  private selectAgents(task: TeamTask, config: TeamConfig): AgentRole[] {
    if (!task.requiredCapabilities || task.requiredCapabilities.length === 0) {
      return config.roles;
    }

    // Select roles that have at least one required capability
    return config.roles.filter(role =>
      task.requiredCapabilities!.some(cap =>
        role.capabilities.includes(cap)
      )
    );
  }

  private async runAgents(
    task: TeamTask,
    roles: AgentRole[]
  ): Promise<AgentTaskResult[]> {
    const results: AgentTaskResult[] = [];

    // Run agents in parallel
    const promises = roles.map(async (role, idx) => {
      const agentId = `agent-${idx}-${role.name}`;

      this.emit({ type: 'agent.spawn', agentId, role: role.name });

      try {
        const result = await this.runSingleAgent(agentId, role, task);
        this.emit({ type: 'agent.complete', agentId, result });
        return result;
      } catch (error) {
        const errorResult: AgentTaskResult = {
          agentId,
          role: role.name,
          success: false,
          output: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
        };
        this.emit({ type: 'agent.complete', agentId, result: errorResult });
        return errorResult;
      }
    });

    results.push(...await Promise.all(promises));

    return results;
  }

  private async runSingleAgent(
    agentId: string,
    role: AgentRole,
    task: TeamTask
  ): Promise<AgentTaskResult> {
    this.emit({ type: 'agent.working', agentId, status: 'thinking' });

    const messages = [
      { role: 'system' as const, content: role.systemPrompt },
      {
        role: 'user' as const,
        content: `Task: ${task.goal}\n${task.context ? `\nContext: ${task.context}` : ''}`,
      },
    ];

    const response = await this.provider.chat(messages, {
      model: role.model,
      tools: this.tools,
    });

    return {
      agentId,
      role: role.name,
      success: true,
      output: response.content,
      confidence: 0.8, // Could be extracted from response
    };
  }

  private async buildConsensus(
    results: AgentTaskResult[],
    strategy: ConsensusStrategy
  ): Promise<Decision> {
    this.emit({ type: 'consensus.start', strategy });

    const votes = new Map<string, boolean>();
    const dissent: string[] = [];

    switch (strategy) {
      case 'voting': {
        // Simple majority voting
        for (const result of results) {
          const vote = result.success && (result.confidence ?? 0.5) > 0.5;
          votes.set(result.agentId, vote);
          this.emit({ type: 'consensus.vote', agentId: result.agentId, vote });

          if (!vote) {
            dissent.push(`${result.role}: ${result.output.slice(0, 100)}`);
          }
        }
        const yesVotes = Array.from(votes.values()).filter(v => v).length;
        const agreed = yesVotes > results.length / 2;

        const decision: Decision = {
          agreed,
          result: agreed
            ? results.find(r => r.success)?.output ?? ''
            : 'No consensus reached',
          votes,
          dissent,
        };
        this.emit({ type: 'consensus.reached', decision });
        return decision;
      }

      case 'authority': {
        // Highest authority wins
        const sorted = [...results].sort((a, b) => {
          const roleA = this.roles.get(a.role);
          const roleB = this.roles.get(b.role);
          return (roleB?.authority ?? 0) - (roleA?.authority ?? 0);
        });

        for (const result of results) {
          const vote = result === sorted[0];
          votes.set(result.agentId, vote);
        }

        const decision: Decision = {
          agreed: sorted[0]?.success ?? false,
          result: sorted[0]?.output ?? 'No result',
          votes,
          dissent,
        };
        this.emit({ type: 'consensus.reached', decision });
        return decision;
      }

      case 'unanimous': {
        // All must agree
        const allSuccess = results.every(r => r.success);
        for (const result of results) {
          votes.set(result.agentId, result.success);
          if (!result.success) {
            dissent.push(`${result.role}: ${result.output.slice(0, 100)}`);
          }
        }

        const decision: Decision = {
          agreed: allSuccess,
          result: allSuccess
            ? results[0]?.output ?? ''
            : 'Unanimous agreement not reached',
          votes,
          dissent,
        };
        this.emit({ type: 'consensus.reached', decision });
        return decision;
      }

      case 'first-complete': {
        // First successful result wins
        const first = results.find(r => r.success);
        for (const result of results) {
          votes.set(result.agentId, result === first);
        }

        const decision: Decision = {
          agreed: !!first,
          result: first?.output ?? 'No successful result',
          votes,
          dissent: [],
        };
        this.emit({ type: 'consensus.reached', decision });
        return decision;
      }
    }
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a multi-agent manager.
 */
export function createMultiAgentManager(
  provider: LLMProvider,
  tools: ToolDefinition[],
  roles?: AgentRole[]
): MultiAgentManager {
  return new MultiAgentManager(provider, tools, roles);
}

// =============================================================================
// BUILT-IN ROLES
// =============================================================================

export const CODER_ROLE: AgentRole = {
  name: 'coder',
  description: 'Expert software developer',
  systemPrompt: `You are an expert software developer.
Focus on:
- Writing clean, maintainable code
- Following best practices
- Considering edge cases
- Writing tests when appropriate`,
  capabilities: ['code', 'debug', 'refactor', 'test'],
  authority: 5,
};

export const REVIEWER_ROLE: AgentRole = {
  name: 'reviewer',
  description: 'Code reviewer focused on quality',
  systemPrompt: `You are a code reviewer.
Focus on:
- Security vulnerabilities
- Performance issues
- Code style and consistency
- Potential bugs`,
  capabilities: ['review', 'analyze', 'security'],
  authority: 6,
};

export const ARCHITECT_ROLE: AgentRole = {
  name: 'architect',
  description: 'System architect',
  systemPrompt: `You are a system architect.
Focus on:
- Overall system design
- Scalability considerations
- Technology choices
- Integration patterns`,
  capabilities: ['design', 'architect', 'plan'],
  authority: 8,
};

export const RESEARCHER_ROLE: AgentRole = {
  name: 'researcher',
  description: 'Technical researcher',
  systemPrompt: `You are a technical researcher.
Focus on:
- Finding relevant information
- Evaluating solutions
- Understanding trade-offs
- Synthesizing knowledge`,
  capabilities: ['research', 'analyze', 'evaluate'],
  authority: 4,
};
