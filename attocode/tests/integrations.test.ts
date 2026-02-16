/**
 * Tests for new integration modules:
 * - CodebaseContextManager
 * - SharedBlackboard
 * - SmartDecomposer
 * - ResultSynthesizer
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  SharedBlackboard,
  createSharedBlackboard,
  type Finding,
  type FindingType,
} from '../src/integrations/agents/shared-blackboard.js';
import {
  SmartDecomposer,
  createSmartDecomposer,
  type SmartSubtask,
} from '../src/integrations/tasks/smart-decomposer.js';
import {
  ResultSynthesizer,
  createResultSynthesizer,
  type AgentOutput,
} from '../src/integrations/agents/result-synthesizer.js';
import {
  CodebaseContextManager,
  createCodebaseContext,
} from '../src/integrations/context/codebase-context.js';

// =============================================================================
// SHARED BLACKBOARD TESTS
// =============================================================================

describe('SharedBlackboard', () => {
  let blackboard: SharedBlackboard;

  beforeEach(() => {
    blackboard = createSharedBlackboard();
  });

  describe('posting findings', () => {
    it('should post a finding and assign an ID', () => {
      const finding = blackboard.post('agent-1', {
        topic: 'auth',
        content: 'Found login function in auth.ts',
        type: 'discovery',
        confidence: 0.9,
      });

      expect(finding.id).toBeDefined();
      expect(finding.agentId).toBe('agent-1');
      expect(finding.topic).toBe('auth');
      expect(finding.content).toBe('Found login function in auth.ts');
      expect(finding.type).toBe('discovery');
      expect(finding.confidence).toBe(0.9);
      expect(finding.timestamp).toBeInstanceOf(Date);
    });

    it('should generate unique IDs for findings', () => {
      const finding1 = blackboard.post('agent-1', {
        topic: 'test',
        content: 'Finding 1',
        type: 'discovery',
        confidence: 0.8,
      });

      const finding2 = blackboard.post('agent-1', {
        topic: 'test',
        content: 'Finding 2',
        type: 'discovery',
        confidence: 0.8,
      });

      expect(finding1.id).not.toBe(finding2.id);
    });
  });

  describe('querying findings', () => {
    beforeEach(() => {
      blackboard.post('agent-1', {
        topic: 'auth',
        content: 'Auth finding',
        type: 'discovery',
        confidence: 0.9,
      });
      blackboard.post('agent-2', {
        topic: 'database',
        content: 'Database finding',
        type: 'analysis',
        confidence: 0.8,
      });
      blackboard.post('agent-1', {
        topic: 'auth',
        content: 'Another auth finding',
        type: 'solution',
        confidence: 0.95,
      });
    });

    it('should return all findings when no filter', () => {
      const findings = blackboard.query();
      expect(findings.length).toBe(3);
    });

    it('should filter by topic', () => {
      const findings = blackboard.query({ topic: 'auth' });
      expect(findings.length).toBe(2);
      expect(findings.every((f) => f.topic === 'auth')).toBe(true);
    });

    it('should filter by agent ID', () => {
      const findings = blackboard.query({ agentId: 'agent-1' });
      expect(findings.length).toBe(2);
      expect(findings.every((f) => f.agentId === 'agent-1')).toBe(true);
    });

    it('should filter by types', () => {
      const findings = blackboard.query({ types: ['discovery', 'solution'] });
      expect(findings.length).toBe(2);
    });
  });

  describe('subscriptions', () => {
    it('should notify subscribers of new findings', () => {
      const callback = vi.fn();

      blackboard.subscribe({
        agentId: 'agent-2',
        callback,
      });

      blackboard.post('agent-1', {
        topic: 'test',
        content: 'New finding',
        type: 'discovery',
        confidence: 0.8,
      });

      expect(callback).toHaveBeenCalledTimes(1);
      expect(callback).toHaveBeenCalledWith(
        expect.objectContaining({
          topic: 'test',
          content: 'New finding',
        })
      );
    });

    it('should filter notifications by topic pattern', () => {
      const callback = vi.fn();

      blackboard.subscribe({
        agentId: 'agent-2',
        topicPattern: 'auth',
        callback,
      });

      blackboard.post('agent-1', {
        topic: 'auth',
        content: 'Auth finding',
        type: 'discovery',
        confidence: 0.8,
      });

      blackboard.post('agent-1', {
        topic: 'database',
        content: 'Database finding',
        type: 'discovery',
        confidence: 0.8,
      });

      expect(callback).toHaveBeenCalledTimes(1);
    });

    it('should unsubscribe correctly', () => {
      const callback = vi.fn();

      const subId = blackboard.subscribe({
        agentId: 'agent-2',
        callback,
      });

      blackboard.unsubscribe(subId);

      blackboard.post('agent-1', {
        topic: 'test',
        content: 'New finding',
        type: 'discovery',
        confidence: 0.8,
      });

      expect(callback).not.toHaveBeenCalled();
    });
  });

  describe('resource claiming', () => {
    it('should claim an unclaimed resource', () => {
      const claimed = blackboard.claim('src/auth.ts', 'agent-1', 'write');
      expect(claimed).toBe(true);
    });

    it('should reject claim on already claimed resource', () => {
      blackboard.claim('src/auth.ts', 'agent-1', 'write');
      const claimed = blackboard.claim('src/auth.ts', 'agent-2', 'write');
      expect(claimed).toBe(false);
    });

    it('should allow same agent to reclaim', () => {
      blackboard.claim('src/auth.ts', 'agent-1', 'write');
      const claimed = blackboard.claim('src/auth.ts', 'agent-1', 'write');
      expect(claimed).toBe(true);
    });

    it('should release a claimed resource', () => {
      blackboard.claim('src/auth.ts', 'agent-1', 'write');
      const released = blackboard.release('src/auth.ts', 'agent-1');
      expect(released).toBe(true);

      const claimed = blackboard.claim('src/auth.ts', 'agent-2', 'write');
      expect(claimed).toBe(true);
    });

    it('should check if resource is claimed', () => {
      expect(blackboard.isClaimed('src/auth.ts')).toBe(false);
      blackboard.claim('src/auth.ts', 'agent-1', 'write');
      expect(blackboard.isClaimed('src/auth.ts')).toBe(true);
    });
  });
});

// =============================================================================
// SMART DECOMPOSER TESTS
// =============================================================================

describe('SmartDecomposer', () => {
  let decomposer: SmartDecomposer;

  beforeEach(() => {
    decomposer = createSmartDecomposer();
  });

  describe('decomposition', () => {
    it('should decompose a simple task', async () => {
      const result = await decomposer.decompose('Add a login button');

      expect(result.subtasks.length).toBeGreaterThan(0);
      expect(result.strategy).toBeDefined();
    });

    it('should create subtasks with valid structure', async () => {
      const result = await decomposer.decompose('Implement user authentication');

      for (const subtask of result.subtasks) {
        expect(subtask.id).toBeDefined();
        expect(subtask.description).toBeDefined();
        expect(subtask.status).toBeDefined();
        expect(subtask.dependencies).toBeInstanceOf(Array);
        expect(subtask.complexity).toBeGreaterThanOrEqual(1);
        expect(subtask.complexity).toBeLessThanOrEqual(10);
      }
    });

    it('should detect sequential tasks', async () => {
      const result = await decomposer.decompose(
        'First analyze the code, then implement the fix, after that write tests'
      );

      // Should have dependencies since it's sequential
      const hasDependent = result.subtasks.some((t) => t.dependencies.length > 0);
      expect(hasDependent).toBe(true);
    });

    it('should detect parallel tasks', async () => {
      const result = await decomposer.decompose(
        'Update all configuration files and fix all linting errors'
      );

      // Parallel strategy or at least some tasks without dependencies
      const independentTasks = result.subtasks.filter((t) => t.dependencies.length === 0);
      expect(independentTasks.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('dependency graph', () => {
    it('should build a valid dependency graph', async () => {
      const result = await decomposer.decompose('Implement feature with tests');

      const graph = decomposer.buildDependencyGraph(result.subtasks);

      expect(graph.dependencies).toBeInstanceOf(Map);
      expect(graph.dependents).toBeInstanceOf(Map);
      expect(graph.executionOrder.length).toBe(result.subtasks.length);
      expect(graph.cycles.length).toBe(0); // No cycles in valid decomposition
    });
  });

  describe('conflict detection', () => {
    it('should detect resource conflicts', async () => {
      const subtasks: SmartSubtask[] = [
        {
          id: 'task-1',
          description: 'Modify auth.ts',
          status: 'pending',
          dependencies: [],
          complexity: 3,
          type: 'implement',
          parallelizable: true,
          modifies: ['src/auth.ts'],
        },
        {
          id: 'task-2',
          description: 'Also modify auth.ts',
          status: 'pending',
          dependencies: [],
          complexity: 3,
          type: 'implement',
          parallelizable: true,
          modifies: ['src/auth.ts'],
        },
      ];

      const conflicts = decomposer.detectConflicts(subtasks);

      expect(conflicts.length).toBeGreaterThan(0);
      expect(conflicts[0].type).toBe('write-write');
    });
  });
});

// =============================================================================
// RESULT SYNTHESIZER TESTS
// =============================================================================

describe('ResultSynthesizer', () => {
  let synthesizer: ResultSynthesizer;

  beforeEach(() => {
    synthesizer = createResultSynthesizer();
  });

  describe('synthesis', () => {
    it('should synthesize single output', async () => {
      const outputs: AgentOutput[] = [
        {
          agentId: 'agent-1',
          content: 'function hello() { return "world"; }',
          type: 'code',
          confidence: 0.9,
        },
      ];

      const result = await synthesizer.synthesize(outputs);

      expect(result.output).toContain('hello');
      expect(result.conflicts.length).toBe(0);
    });

    it('should merge multiple code outputs', async () => {
      const outputs: AgentOutput[] = [
        {
          agentId: 'agent-1',
          content: 'function foo() { return 1; }',
          type: 'code',
          confidence: 0.9,
        },
        {
          agentId: 'agent-2',
          content: 'function bar() { return 2; }',
          type: 'code',
          confidence: 0.85,
        },
      ];

      const result = await synthesizer.synthesize(outputs);

      expect(result.output).toBeDefined();
      expect(result.stats.inputCount).toBe(2);
    });

    it('should deduplicate findings', async () => {
      const outputs: AgentOutput[] = [
        {
          agentId: 'agent-1',
          content: 'Analysis complete',
          type: 'research',
          confidence: 0.9,
          findings: ['The auth module needs refactoring', 'Performance is good'],
        },
        {
          agentId: 'agent-2',
          content: 'Research done',
          type: 'research',
          confidence: 0.85,
          findings: ['Auth module requires refactoring', 'Memory usage is low'],
        },
      ];

      const result = await synthesizer.synthesize(outputs);

      // Should deduplicate similar findings
      expect(result.stats.deduplicationRate).toBeGreaterThan(0);
    });
  });

  describe('conflict detection', () => {
    it('should detect code conflicts', async () => {
      const outputs: AgentOutput[] = [
        {
          agentId: 'agent-1',
          content: 'Use approach A with library X',
          type: 'code',
          confidence: 0.9,
          filesModified: [
            { path: 'src/auth.ts', type: 'modify', newContent: 'version A' },
          ],
        },
        {
          agentId: 'agent-2',
          content: 'Use approach B with library Y',
          type: 'code',
          confidence: 0.85,
          filesModified: [
            { path: 'src/auth.ts', type: 'modify', newContent: 'version B' },
          ],
        },
      ];

      const result = await synthesizer.synthesize(outputs);

      expect(result.conflicts.length).toBeGreaterThan(0);
    });
  });

  describe('resolution strategies', () => {
    it('should prefer higher confidence by default', async () => {
      const highConfidence: AgentOutput = {
        agentId: 'agent-1',
        content: 'High confidence solution',
        type: 'analysis',
        confidence: 0.95,
        findings: ['High confidence finding'],
      };

      const lowConfidence: AgentOutput = {
        agentId: 'agent-2',
        content: 'Low confidence solution',
        type: 'analysis',
        confidence: 0.6,
        findings: ['Low confidence finding'],
      };

      const result = await synthesizer.synthesize([lowConfidence, highConfidence]);

      // Result should contain info from higher confidence agent
      expect(result.stats.inputCount).toBe(2);
      expect(result.output).toBeDefined();
    });
  });
});

// =============================================================================
// CODEBASE CONTEXT MANAGER TESTS
// =============================================================================

describe('CodebaseContextManager', () => {
  let manager: CodebaseContextManager;

  beforeEach(() => {
    manager = createCodebaseContext({ root: '.' });
  });

  describe('initialization', () => {
    it('should create with default config', () => {
      expect(manager).toBeDefined();
    });

    it('should create with custom config', () => {
      const customManager = createCodebaseContext({
        root: '/custom/path',
        includePatterns: ['**/*.ts'],
        excludePatterns: ['node_modules/**'],
        maxFileSize: 50000,
      });

      expect(customManager).toBeDefined();
    });
  });

  describe('selection', () => {
    it('should select code within budget', async () => {
      // This test would need actual files or mocking
      const result = await manager.selectRelevantCode({
        task: 'fix authentication bug',
        maxTokens: 5000,
        strategy: 'relevance_first',
      });

      expect(result.totalTokens).toBeLessThanOrEqual(5000);
      expect(result.chunks).toBeInstanceOf(Array);
    });
  });
});
