/**
 * Tests for swarm types and utility functions
 */
import { describe, it, expect } from 'vitest';
import {
  subtaskToSwarmTask,
  taskResultToAgentOutput,
  SUBTASK_TO_CAPABILITY,
  DEFAULT_SWARM_CONFIG,
} from '../../src/integrations/swarm/types.js';
import type { SmartSubtask } from '../../src/integrations/smart-decomposer.js';
import type { SwarmTask } from '../../src/integrations/swarm/types.js';

describe('subtaskToSwarmTask', () => {
  it('should convert a SmartSubtask to SwarmTask', () => {
    const subtask: SmartSubtask = {
      id: 'st-1',
      description: 'Implement the parser',
      status: 'pending',
      dependencies: ['st-0'],
      complexity: 5,
      type: 'implement',
      parallelizable: true,
      modifies: ['src/parser.ts'],
      reads: ['src/types.ts'],
    };

    const swarmTask = subtaskToSwarmTask(subtask, 2);

    expect(swarmTask.id).toBe('st-1');
    expect(swarmTask.description).toBe('Implement the parser');
    expect(swarmTask.type).toBe('implement');
    expect(swarmTask.wave).toBe(2);
    expect(swarmTask.status).toBe('pending'); // Has dependencies
    expect(swarmTask.targetFiles).toEqual(['src/parser.ts']);
    expect(swarmTask.readFiles).toEqual(['src/types.ts']);
    expect(swarmTask.attempts).toBe(0);
  });

  it('should set status to ready when no dependencies', () => {
    const subtask: SmartSubtask = {
      id: 'st-0',
      description: 'Research',
      status: 'pending',
      dependencies: [],
      complexity: 2,
      type: 'research',
      parallelizable: true,
    };

    const swarmTask = subtaskToSwarmTask(subtask, 0);
    expect(swarmTask.status).toBe('ready');
  });
});

describe('taskResultToAgentOutput', () => {
  it('should convert a completed task to AgentOutput', () => {
    const task: SwarmTask = {
      id: 'st-1',
      description: 'Implement parser',
      type: 'implement',
      dependencies: [],
      status: 'completed',
      complexity: 5,
      wave: 1,
      attempts: 1,
      result: {
        success: true,
        output: 'Parser implemented successfully',
        tokensUsed: 1500,
        costUsed: 0.02,
        durationMs: 30000,
        model: 'qwen/qwen-2.5-coder-32b',
        qualityScore: 4,
        findings: ['Implemented recursive descent parser'],
      },
    };

    const output = taskResultToAgentOutput(task);

    expect(output).not.toBeNull();
    expect(output!.agentId).toBe('swarm-worker-st-1');
    expect(output!.type).toBe('code');
    expect(output!.confidence).toBe(0.8); // qualityScore 4 / 5
    expect(output!.content).toBe('Parser implemented successfully');
  });

  it('should return null for failed tasks', () => {
    const task: SwarmTask = {
      id: 'st-1',
      description: 'Failed task',
      type: 'implement',
      dependencies: [],
      status: 'failed',
      complexity: 5,
      wave: 1,
      attempts: 2,
    };

    const output = taskResultToAgentOutput(task);
    expect(output).toBeNull();
  });

  it('should return null for tasks with failed results', () => {
    const task: SwarmTask = {
      id: 'st-1',
      description: 'Failed task',
      type: 'implement',
      dependencies: [],
      status: 'completed',
      complexity: 5,
      wave: 1,
      attempts: 1,
      result: {
        success: false,
        output: 'Error occurred',
        tokensUsed: 100,
        costUsed: 0.001,
        durationMs: 1000,
        model: 'test',
      },
    };

    const output = taskResultToAgentOutput(task);
    expect(output).toBeNull();
  });
});

describe('SUBTASK_TO_CAPABILITY', () => {
  it('should map all subtask types to capabilities', () => {
    expect(SUBTASK_TO_CAPABILITY.implement).toBe('code');
    expect(SUBTASK_TO_CAPABILITY.research).toBe('research');
    expect(SUBTASK_TO_CAPABILITY.review).toBe('review');
    expect(SUBTASK_TO_CAPABILITY.test).toBe('test');
    expect(SUBTASK_TO_CAPABILITY.document).toBe('document');
    expect(SUBTASK_TO_CAPABILITY.refactor).toBe('code');
    expect(SUBTASK_TO_CAPABILITY.integrate).toBe('code');
  });
});

describe('DEFAULT_SWARM_CONFIG V2 fields', () => {
  it('should have V2 default values', () => {
    expect(DEFAULT_SWARM_CONFIG.enablePlanning).toBe(true);
    expect(DEFAULT_SWARM_CONFIG.enableWaveReview).toBe(true);
    expect(DEFAULT_SWARM_CONFIG.enableVerification).toBe(true);
    expect(DEFAULT_SWARM_CONFIG.workerStuckThreshold).toBe(3);
    expect(DEFAULT_SWARM_CONFIG.enablePersistence).toBe(true);
    expect(DEFAULT_SWARM_CONFIG.stateDir).toBe('.agent/swarm-state');
    expect(DEFAULT_SWARM_CONFIG.toolAccessMode).toBe('all');
    expect(DEFAULT_SWARM_CONFIG.enableModelFailover).toBe(true);
    expect(DEFAULT_SWARM_CONFIG.maxVerificationRetries).toBe(2);
  });
});
