/**
 * Exercise 17: Agent Coordinator - REFERENCE SOLUTION
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

export class AgentCoordinator {
  private agents: Map<string, AgentRole> = new Map();

  registerAgent(agent: AgentRole): void {
    this.agents.set(agent.name, agent);
  }

  findAgentForTask(task: string): AgentRole | undefined {
    const taskLower = task.toLowerCase();
    for (const agent of this.agents.values()) {
      if (agent.capabilities.some(cap => taskLower.includes(cap.toLowerCase()))) {
        return agent;
      }
    }
    return undefined;
  }

  async executeWithAgent(agentName: string, task: string): Promise<string> {
    const agent = this.agents.get(agentName);
    if (!agent) throw new Error(`Agent not found: ${agentName}`);
    return agent.execute(task);
  }

  async coordinateTask(task: string, agentNames: string[]): Promise<CoordinationResult> {
    const agentResults: Array<{ agent: string; result: string }> = [];

    for (const name of agentNames) {
      const result = await this.executeWithAgent(name, task);
      agentResults.push({ agent: name, result });
    }

    const finalResult = agentResults.map(r => r.result).join('\n---\n');

    return { task, agentResults, finalResult };
  }

  getAgents(): AgentRole[] {
    return Array.from(this.agents.values());
  }
}
