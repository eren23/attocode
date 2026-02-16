/**
 * Tests for SharedContextEngine (Phase 3.1)
 *
 * Verifies prompt composition, failure guidance, goal recitation,
 * failure reporting, and reference delegation.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { SharedContextState, createSharedContextState } from '../../src/shared/shared-context-state.js';
import {
  SharedContextEngine,
  createSharedContextEngine,
  type WorkerTask,
} from '../../src/shared/context-engine.js';

describe('SharedContextEngine', () => {
  let state: SharedContextState;
  let engine: SharedContextEngine;

  const sampleTask: WorkerTask = {
    id: 'task-1',
    description: 'Implement user authentication',
    goal: 'Add JWT-based auth to the API endpoints',
    dependencies: ['task-0'],
    context: 'The API uses Express.js with TypeScript.',
  };

  beforeEach(() => {
    state = createSharedContextState({
      maxFailures: 20,
      maxReferences: 10,
      staticPrefix: 'You are a coding assistant for the Attocode project.',
    });
    engine = createSharedContextEngine(state);
  });

  describe('factory', () => {
    it('creates instance via factory function', () => {
      const e = createSharedContextEngine(state);
      expect(e).toBeInstanceOf(SharedContextEngine);
    });
  });

  describe('buildWorkerSystemPrompt', () => {
    it('includes all 4 sections when data is present', () => {
      // Add a failure so guidance section appears
      state.recordFailure('worker-0', {
        action: 'read_file',
        error: 'File not found: /missing.ts',
      });

      const prompt = engine.buildWorkerSystemPrompt(sampleTask);

      // 1. Shared prefix
      expect(prompt).toContain('Attocode project');
      // 2. Task context
      expect(prompt).toContain('task-1');
      expect(prompt).toContain('Implement user authentication');
      expect(prompt).toContain('Express.js');
      // 3. Failure guidance
      expect(prompt).toContain('File not found');
      // 4. Goal recitation
      expect(prompt).toContain('JWT-based auth');
    });

    it('omits empty sections', () => {
      const minState = createSharedContextState({ staticPrefix: '' });
      const minEngine = createSharedContextEngine(minState);

      const task: WorkerTask = {
        id: 'task-2',
        description: 'Simple task',
        goal: 'Do the thing',
      };

      const prompt = minEngine.buildWorkerSystemPrompt(task);
      // Should not have double blank lines from missing prefix or failures
      expect(prompt).not.toContain('\n\n\n\n');
      // Should still have task and goal
      expect(prompt).toContain('task-2');
      expect(prompt).toContain('Do the thing');
    });
  });

  describe('getSharedPrefix', () => {
    it('returns the static prefix from SharedContextState', () => {
      expect(engine.getSharedPrefix()).toBe('You are a coding assistant for the Attocode project.');
    });
  });

  describe('getFailureGuidance', () => {
    it('returns empty string when no failures', () => {
      expect(engine.getFailureGuidance()).toBe('');
    });

    it('includes failure context after recording failures', () => {
      state.recordFailure('worker-1', {
        action: 'write_file',
        error: 'Permission denied',
      });

      const guidance = engine.getFailureGuidance();
      expect(guidance).toContain('Permission denied');
    });

    it('includes insights when enabled (default)', () => {
      // Record multiple similar failures to trigger insights
      for (let i = 0; i < 5; i++) {
        state.recordFailure(`worker-${i}`, {
          action: 'read_file',
          error: 'File not found',
        });
      }

      const guidance = engine.getFailureGuidance();
      // The failure context should at minimum contain the error
      expect(guidance).toContain('File not found');
    });

    it('omits insights when disabled', () => {
      const noInsightsEngine = createSharedContextEngine(state, { includeInsights: false });

      state.recordFailure('worker-1', {
        action: 'write_file',
        error: 'Error writing',
      });

      const guidance = noInsightsEngine.getFailureGuidance();
      expect(guidance).not.toContain('Cross-Worker Insights');
    });
  });

  describe('getGoalRecitation', () => {
    it('formats goal with description', () => {
      const recitation = engine.getGoalRecitation(sampleTask);
      expect(recitation).toContain('Current Goal');
      expect(recitation).toContain('Implement user authentication');
      expect(recitation).toContain('JWT-based auth');
    });

    it('includes dependency list when provided', () => {
      const recitation = engine.getGoalRecitation(sampleTask);
      expect(recitation).toContain('Depends on:');
      expect(recitation).toContain('task-0');
    });

    it('omits dependency line when no dependencies', () => {
      const task: WorkerTask = {
        id: 'task-3',
        description: 'Standalone task',
        goal: 'Independent work',
      };
      const recitation = engine.getGoalRecitation(task);
      expect(recitation).not.toContain('Depends on');
    });
  });

  describe('reportFailure', () => {
    it('delegates to SharedContextState and returns Failure', () => {
      const failure = engine.reportFailure('worker-A', {
        action: 'bash',
        error: 'Command failed',
      });

      expect(failure).toBeDefined();
      expect(failure.action).toContain('worker-A');
      expect(failure.error).toBe('Command failed');
    });

    it('makes failure visible in subsequent guidance', () => {
      engine.reportFailure('worker-B', {
        action: 'edit_file',
        error: 'Conflict detected',
      });

      const guidance = engine.getFailureGuidance();
      expect(guidance).toContain('Conflict detected');
    });
  });

  describe('getRelevantReferences', () => {
    it('delegates to SharedContextState.searchReferences', () => {
      state.addReferences([
        { id: 'ref-1', type: 'file', value: '/src/auth/login.ts', timestamp: new Date().toISOString() },
        { id: 'ref-2', type: 'url', value: 'https://docs.example.com/api', timestamp: new Date().toISOString() },
      ]);

      const results = engine.getRelevantReferences('auth');
      expect(results).toHaveLength(1);
      expect(results[0].value).toContain('auth');
    });

    it('returns empty array when no matches', () => {
      expect(engine.getRelevantReferences('nonexistent')).toEqual([]);
    });
  });
});
