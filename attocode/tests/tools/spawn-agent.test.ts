/**
 * Spawn Agent Tool Tests
 */

import { describe, it, expect, vi } from 'vitest';
import {
  createBoundSpawnAgentTool,
  SPAWNABLE_AGENTS,
  type SpawnConstraints,
  type SpawnFunction,
} from '../../src/tools/agent.js';

describe('spawn_agent tool', () => {
  describe('createBoundSpawnAgentTool', () => {
    it('should create a tool with correct metadata', () => {
      const mockSpawn: SpawnFunction = vi.fn();
      const tool = createBoundSpawnAgentTool(mockSpawn);

      expect(tool.name).toBe('spawn_agent');
      expect(tool.description).toContain('specialized subagent');
      expect(tool.dangerLevel).toBe('moderate');
    });

    it('should validate agent name', async () => {
      const mockSpawn: SpawnFunction = vi.fn();
      const tool = createBoundSpawnAgentTool(mockSpawn);

      const result = await tool.execute({ agent: 'invalid_agent', task: 'do something' });

      expect(result.success).toBe(false);
      expect(result.output).toContain('Invalid agent');
      expect(mockSpawn).not.toHaveBeenCalled();
    });

    it('should validate task is required', async () => {
      const mockSpawn: SpawnFunction = vi.fn();
      const tool = createBoundSpawnAgentTool(mockSpawn);

      const result = await tool.execute({ agent: 'researcher', task: '' });

      expect(result.success).toBe(false);
      expect(result.output).toContain('Task is required');
      expect(mockSpawn).not.toHaveBeenCalled();
    });

    it('should call spawn function with correct arguments', async () => {
      const mockSpawn: SpawnFunction = vi.fn().mockResolvedValue({
        success: true,
        output: 'Task completed',
        metrics: { tokens: 100, duration: 1000, toolCalls: 5 },
      });
      const tool = createBoundSpawnAgentTool(mockSpawn);

      const result = await tool.execute({
        agent: 'researcher',
        task: 'Find all TypeScript files',
      });

      expect(mockSpawn).toHaveBeenCalledWith('researcher', 'Find all TypeScript files', undefined);
      expect(result.success).toBe(true);
      expect(result.output).toBe('Task completed');
    });

    it('should pass constraints to spawn function', async () => {
      const mockSpawn: SpawnFunction = vi.fn().mockResolvedValue({
        success: true,
        output: 'Task completed with constraints',
        metrics: { tokens: 50, duration: 500, toolCalls: 2 },
      });
      const tool = createBoundSpawnAgentTool(mockSpawn);

      const constraints: SpawnConstraints = {
        focusAreas: ['src/**/*.ts'],
        excludeAreas: ['node_modules/**'],
        maxTokens: 5000,
        timeboxMinutes: 5,
        requiredDeliverables: ['summary.md'],
      };

      const result = await tool.execute({
        agent: 'coder',
        task: 'Refactor the utils',
        constraints,
      });

      expect(mockSpawn).toHaveBeenCalledWith('coder', 'Refactor the utils', constraints);
      expect(result.success).toBe(true);
      expect(result.metadata?.constraints).toEqual(constraints);
    });

    it('should include constraints in result metadata', async () => {
      const mockSpawn: SpawnFunction = vi.fn().mockResolvedValue({
        success: true,
        output: 'Done',
        metrics: { tokens: 100, duration: 1000, toolCalls: 3 },
      });
      const tool = createBoundSpawnAgentTool(mockSpawn);

      const constraints: SpawnConstraints = {
        focusAreas: ['src/api/**'],
      };

      const result = await tool.execute({
        agent: 'reviewer',
        task: 'Review API changes',
        constraints,
      });

      expect(result.metadata).toMatchObject({
        agent: 'reviewer',
        task: 'Review API changes',
        constraints: { focusAreas: ['src/api/**'] },
      });
    });
  });

  describe('SPAWNABLE_AGENTS', () => {
    it('should include expected agent types', () => {
      expect(SPAWNABLE_AGENTS).toContain('researcher');
      expect(SPAWNABLE_AGENTS).toContain('coder');
      expect(SPAWNABLE_AGENTS).toContain('reviewer');
      expect(SPAWNABLE_AGENTS).toContain('architect');
      expect(SPAWNABLE_AGENTS).toContain('debugger');
      expect(SPAWNABLE_AGENTS).toContain('documenter');
    });
  });
});
