/**
 * Exercise Tests: Lesson 17 - Agent Coordinator
 */
import { describe, it, expect } from 'vitest';
import { AgentCoordinator } from './exercises/answers/exercise-1.js';

describe('AgentCoordinator', () => {
  it('should register agents', () => {
    const coordinator = new AgentCoordinator();
    coordinator.registerAgent({
      name: 'coder',
      capabilities: ['code', 'implement'],
      execute: async () => 'done',
    });

    expect(coordinator.getAgents()).toHaveLength(1);
  });

  it('should find agent for task', () => {
    const coordinator = new AgentCoordinator();
    coordinator.registerAgent({
      name: 'coder',
      capabilities: ['code'],
      execute: async () => '',
    });

    const agent = coordinator.findAgentForTask('Write code for feature');
    expect(agent?.name).toBe('coder');
  });

  it('should execute with specific agent', async () => {
    const coordinator = new AgentCoordinator();
    coordinator.registerAgent({
      name: 'greeter',
      capabilities: ['greet'],
      execute: async (task) => `Hello: ${task}`,
    });

    const result = await coordinator.executeWithAgent('greeter', 'world');
    expect(result).toBe('Hello: world');
  });

  it('should coordinate multiple agents', async () => {
    const coordinator = new AgentCoordinator();
    coordinator.registerAgent({
      name: 'analyzer',
      capabilities: ['analyze'],
      execute: async () => 'Analysis complete',
    });
    coordinator.registerAgent({
      name: 'reviewer',
      capabilities: ['review'],
      execute: async () => 'Review complete',
    });

    const result = await coordinator.coordinateTask('review code', ['analyzer', 'reviewer']);

    expect(result.agentResults).toHaveLength(2);
    expect(result.finalResult).toContain('Analysis');
    expect(result.finalResult).toContain('Review');
  });
});
