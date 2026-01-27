/**
 * Exercise 17: Agent Coordinator
 * Implement multi-agent coordination.
 */

export interface AgentRole {
  name: string;
  capabilities: string[];
  execute: (task: string) => Promise<string>;
}

export interface CoordinationResult {
  task: string;
  agentResults: Array<{ agent: string; result: string }>;
  finalResult: string;
}

/**
 * TODO: Implement AgentCoordinator
 */
export class AgentCoordinator {
  private agents: Map<string, AgentRole> = new Map();

  registerAgent(_agent: AgentRole): void {
    throw new Error('TODO: Implement registerAgent');
  }

  findAgentForTask(_task: string): AgentRole | undefined {
    // TODO: Find agent with matching capability
    throw new Error('TODO: Implement findAgentForTask');
  }

  async executeWithAgent(_agentName: string, _task: string): Promise<string> {
    throw new Error('TODO: Implement executeWithAgent');
  }

  async coordinateTask(_task: string, _agentNames: string[]): Promise<CoordinationResult> {
    // TODO: Run task through multiple agents, combine results
    throw new Error('TODO: Implement coordinateTask');
  }

  getAgents(): AgentRole[] {
    throw new Error('TODO: Implement getAgents');
  }
}
