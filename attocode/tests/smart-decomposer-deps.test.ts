/**
 * Tests for smart decomposer dependency resolution fix.
 *
 * Verifies that convertLLMResult correctly resolves various
 * LLM dependency reference formats and filters invalid ones.
 */
import { describe, it, expect } from 'vitest';
import { createSmartDecomposer } from '../src/integrations/smart-decomposer.js';
import type { LLMDecomposeResult, SmartDecomposerEvent } from '../src/integrations/smart-decomposer.js';

describe('SmartDecomposer dependency resolution', () => {
  it('should resolve integer index dependencies', async () => {
    const llmResult: LLMDecomposeResult = {
      subtasks: [
        { description: 'Research React', type: 'research', complexity: 3, dependencies: [], parallelizable: true },
        { description: 'Research Vue', type: 'research', complexity: 3, dependencies: [], parallelizable: true },
        { description: 'Synthesize findings', type: 'merge', complexity: 4, dependencies: ['0', '1'], parallelizable: false },
      ],
      strategy: 'parallel',
      reasoning: 'test',
    };

    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => llmResult,
    });

    const result = await decomposer.decompose('Compare React vs Vue');

    // The merge task (index 2) should have resolved deps to the first two task IDs
    const mergeTask = result.subtasks[2];
    expect(mergeTask.dependencies).toHaveLength(2);
    expect(mergeTask.dependencies[0]).toBe(result.subtasks[0].id);
    expect(mergeTask.dependencies[1]).toBe(result.subtasks[1].id);
  });

  it('should resolve task-N style dependencies', async () => {
    const llmResult: LLMDecomposeResult = {
      subtasks: [
        { description: 'Design schema', type: 'design', complexity: 4, dependencies: [], parallelizable: false },
        { description: 'Implement API', type: 'implement', complexity: 6, dependencies: ['task-0'], parallelizable: false },
      ],
      strategy: 'sequential',
      reasoning: 'test',
    };

    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => llmResult,
    });

    const result = await decomposer.decompose('Build API');

    expect(result.subtasks[1].dependencies).toHaveLength(1);
    expect(result.subtasks[1].dependencies[0]).toBe(result.subtasks[0].id);
  });

  it('should resolve subtask-N and st-N style dependencies', async () => {
    const llmResult: LLMDecomposeResult = {
      subtasks: [
        { description: 'Task A', type: 'research', complexity: 2, dependencies: [], parallelizable: true },
        { description: 'Task B', type: 'implement', complexity: 5, dependencies: ['subtask-0'], parallelizable: false },
        { description: 'Task C', type: 'test', complexity: 3, dependencies: ['st-1'], parallelizable: false },
      ],
      strategy: 'sequential',
      reasoning: 'test',
    };

    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => llmResult,
    });

    const result = await decomposer.decompose('Build feature');

    expect(result.subtasks[1].dependencies).toHaveLength(1);
    expect(result.subtasks[1].dependencies[0]).toBe(result.subtasks[0].id);
    expect(result.subtasks[2].dependencies).toHaveLength(1);
    expect(result.subtasks[2].dependencies[0]).toBe(result.subtasks[1].id);
  });

  it('should resolve description-based dependencies', async () => {
    const llmResult: LLMDecomposeResult = {
      subtasks: [
        { description: 'Research authentication methods', type: 'research', complexity: 3, dependencies: [], parallelizable: true },
        { description: 'Implement auth', type: 'implement', complexity: 6, dependencies: ['Research authentication methods'], parallelizable: false },
      ],
      strategy: 'sequential',
      reasoning: 'test',
    };

    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => llmResult,
    });

    const result = await decomposer.decompose('Add auth');

    expect(result.subtasks[1].dependencies).toHaveLength(1);
    expect(result.subtasks[1].dependencies[0]).toBe(result.subtasks[0].id);
  });

  it('should filter out invalid/unresolvable dependencies', async () => {
    const llmResult: LLMDecomposeResult = {
      subtasks: [
        { description: 'Task A', type: 'research', complexity: 2, dependencies: [], parallelizable: true },
        { description: 'Task B', type: 'implement', complexity: 5, dependencies: ['0', 'nonexistent-ref', 'Some Random Text'], parallelizable: false },
      ],
      strategy: 'sequential',
      reasoning: 'test',
    };

    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => llmResult,
    });

    const result = await decomposer.decompose('Build thing');

    // Only '0' should resolve; 'nonexistent-ref' and 'Some Random Text' should be filtered
    expect(result.subtasks[1].dependencies).toHaveLength(1);
    expect(result.subtasks[1].dependencies[0]).toBe(result.subtasks[0].id);
  });

  it('should filter out self-dependencies', async () => {
    const llmResult: LLMDecomposeResult = {
      subtasks: [
        { description: 'Task A', type: 'research', complexity: 2, dependencies: ['0'], parallelizable: true },
      ],
      strategy: 'sequential',
      reasoning: 'test',
    };

    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => llmResult,
    });

    const result = await decomposer.decompose('Do task');

    // Self-reference should be filtered out
    expect(result.subtasks[0].dependencies).toHaveLength(0);
  });

  it('should produce a non-flat DAG when deps are valid', async () => {
    const llmResult: LLMDecomposeResult = {
      subtasks: [
        { description: 'Research A', type: 'research', complexity: 3, dependencies: [], parallelizable: true },
        { description: 'Research B', type: 'research', complexity: 3, dependencies: [], parallelizable: true },
        { description: 'Research C', type: 'research', complexity: 3, dependencies: [], parallelizable: true },
        { description: 'Merge findings', type: 'merge', complexity: 4, dependencies: ['0', '1', '2'], parallelizable: false },
      ],
      strategy: 'parallel',
      reasoning: 'test',
    };

    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => llmResult,
    });

    const result = await decomposer.decompose('Research topic');

    // Merge task should depend on all 3 research tasks
    const mergeTask = result.subtasks[3];
    expect(mergeTask.dependencies).toHaveLength(3);

    // DAG should have 2 parallel groups: [research x3] and [merge]
    expect(result.dependencyGraph.parallelGroups.length).toBeGreaterThanOrEqual(2);
  });

  it('should emit llm.fallback events when LLM returns 0 subtasks (retry + final)', async () => {
    const events: SmartDecomposerEvent[] = [];
    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => ({
        subtasks: [],
        strategy: 'parallel' as const,
        reasoning: 'empty',
      }),
    });
    decomposer.on((e) => events.push(e));

    await decomposer.decompose('Build a feature');

    const fallbackEvents = events.filter((e) => e.type === 'llm.fallback');
    // 2 events: first retry attempt, then final heuristic fallback
    expect(fallbackEvents).toHaveLength(2);
    expect(fallbackEvents[0].type === 'llm.fallback' && fallbackEvents[0].reason).toBe('LLM returned 0 subtasks, retrying...');
    expect(fallbackEvents[1].type === 'llm.fallback' && fallbackEvents[1].reason).toBe('LLM failed after 2 attempts');
  });

  it('should emit llm.fallback events when LLM throws (retry + final)', async () => {
    const events: SmartDecomposerEvent[] = [];
    const decomposer = createSmartDecomposer({
      useLLM: true,
      llmProvider: async () => { throw new Error('LLM connection timeout'); },
    });
    decomposer.on((e) => events.push(e));

    await decomposer.decompose('Build a feature');

    const fallbackEvents = events.filter((e) => e.type === 'llm.fallback');
    // 2 events: first retry attempt, then final heuristic fallback
    expect(fallbackEvents).toHaveLength(2);
    expect(fallbackEvents[0].type === 'llm.fallback' && fallbackEvents[0].reason).toBe('LLM connection timeout, retrying...');
    expect(fallbackEvents[1].type === 'llm.fallback' && fallbackEvents[1].reason).toBe('LLM failed after 2 attempts');
  });

  it('should use adaptive strategy for implement tasks by default (not sequential)', async () => {
    const decomposer = createSmartDecomposer();

    // "implement" is the inferred type; avoid words containing sequential indicators
    // (e.g. "authentication" contains "then", "before" etc.)
    const result = await decomposer.decompose('Implement a login page');

    // Should use adaptive strategy, not sequential
    expect(result.strategy).toBe('adaptive');
    // Adaptive produces parallel research/analysis + dependent impl + test (4 tasks)
    expect(result.subtasks.length).toBeGreaterThanOrEqual(4);
    // First two tasks should be parallelizable (research + analysis)
    const readyTasks = result.subtasks.filter((t) => t.status === 'ready');
    expect(readyTasks.length).toBeGreaterThanOrEqual(2);
  });
});
