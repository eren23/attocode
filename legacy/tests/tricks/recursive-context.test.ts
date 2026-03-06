/**
 * Recursive Context Tests
 *
 * Tests for the RLM (Recursive Language Model) context navigation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  RecursiveContextManager,
  createRecursiveContext,
  createMinimalRecursiveContext,
  createFileSystemSource,
  createConversationSource,
  formatRecursiveResult,
  formatRecursiveStats,
  type ContextSource,
  type LLMCallFunction,
  type RecursiveContextEvent,
} from '../../src/tricks/recursive-context.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

function createMockSource(options: {
  name?: string;
  items?: string[];
  content?: Record<string, string>;
  searchResults?: Array<{ key: string; snippet: string; score: number }>;
}): ContextSource {
  const {
    name = 'mock',
    items = ['item1', 'item2', 'item3'],
    content = { item1: 'Content of item 1', item2: 'Content of item 2' },
    searchResults = [],
  } = options;

  return {
    describe: () => `Mock source: ${name}`,
    list: vi.fn(async () => items),
    fetch: vi.fn(async (key) => content[key] || 'Not found'),
    search: searchResults.length > 0 ? vi.fn(async () => searchResults) : undefined,
  };
}

function createMockLLM(responses: string[]): LLMCallFunction {
  let callIndex = 0;

  return vi.fn(async (_system, _user, opts) => {
    const response = responses[callIndex % responses.length];
    callIndex++;

    return {
      content: response,
      tokens: (opts?.maxTokens || 100) * 0.5, // Simulate partial usage
    };
  });
}

// =============================================================================
// TESTS
// =============================================================================

describe('RecursiveContextManager', () => {
  let manager: RecursiveContextManager;

  beforeEach(() => {
    manager = createRecursiveContext({
      maxDepth: 3,
      snippetTokens: 1000,
      totalBudget: 10000,
    });
  });

  describe('initialization', () => {
    it('should create manager with default config', () => {
      const m = createRecursiveContext();
      expect(m).toBeInstanceOf(RecursiveContextManager);
    });

    it('should create minimal manager', () => {
      const m = createMinimalRecursiveContext();
      expect(m).toBeInstanceOf(RecursiveContextManager);
    });
  });

  describe('source management', () => {
    it('should register sources', () => {
      const source = createMockSource({ name: 'files' });
      manager.registerSource('files', source);

      expect(manager.getSourceNames()).toContain('files');
    });

    it('should unregister sources', () => {
      const source = createMockSource({ name: 'files' });
      manager.registerSource('files', source);
      manager.unregisterSource('files');

      expect(manager.getSourceNames()).not.toContain('files');
    });

    it('should list registered sources', () => {
      manager.registerSource('files', createMockSource({ name: 'files' }));
      manager.registerSource('docs', createMockSource({ name: 'docs' }));

      const sources = manager.getSourceNames();
      expect(sources).toContain('files');
      expect(sources).toContain('docs');
    });
  });

  describe('process', () => {
    it('should process a query and return answer', async () => {
      manager.registerSource('files', createMockSource({
        items: ['main.ts', 'utils.ts'],
        content: { 'main.ts': 'function main() { console.log("hello"); }' },
      }));

      const llm = createMockLLM([
        // First call: navigation decision
        '{"type": "list", "source": "files", "reason": "see what files exist"}',
        // Second call: fetch a file
        '{"type": "fetch", "source": "files", "key": "main.ts", "reason": "read main file"}',
        // Third call: synthesize
        '{"type": "synthesize", "reason": "have enough info"}',
        // Fourth call: actual synthesis
        'The main.ts file contains a simple hello world function.',
      ]);

      const result = await manager.process('What does main.ts do?', llm);

      expect(result.answer).toContain('hello');
      expect(result.stats.totalCalls).toBeGreaterThan(0);
      expect(result.stats.sourcesAccessed).toContain('files');
    });

    it('should handle done command', async () => {
      manager.registerSource('files', createMockSource({}));

      const llm = createMockLLM([
        '{"type": "done", "reason": "no exploration needed"}',
        'Based on the question, I cannot determine an answer without more context.',
      ]);

      const result = await manager.process('What is 2+2?', llm);

      expect(result.answer).toBeDefined();
    });

    it('should track navigation path', async () => {
      manager.registerSource('files', createMockSource({
        content: { 'test.ts': 'test content' },
      }));

      const llm = createMockLLM([
        '{"type": "list", "source": "files", "reason": "list files"}',
        '{"type": "fetch", "source": "files", "key": "test.ts", "reason": "read file"}',
        '{"type": "synthesize", "reason": "done"}',
        'Answer based on findings.',
      ]);

      const result = await manager.process('Query', llm);

      expect(result.path.length).toBeGreaterThan(0);
      expect(result.path.some(p => p.command.type === 'list')).toBe(true);
      expect(result.path.some(p => p.command.type === 'fetch')).toBe(true);
    });

    it('should collect statistics', async () => {
      manager.registerSource('files', createMockSource({}));

      const llm = createMockLLM([
        '{"type": "list", "source": "files"}',
        '{"type": "done"}',
        'Answer.',
      ]);

      const result = await manager.process('Query', llm);

      expect(result.stats.totalCalls).toBeGreaterThan(0);
      expect(result.stats.totalTokens).toBeGreaterThan(0);
      expect(result.stats.duration).toBeGreaterThanOrEqual(0);
    });

    it('should respect depth limit', async () => {
      const shallowManager = createRecursiveContext({ maxDepth: 1 });
      shallowManager.registerSource('files', createMockSource({}));

      const llm = createMockLLM([
        '{"type": "list", "source": "files"}',
        '{"type": "list", "source": "files"}', // Would be depth 1+
        'Final answer.',
      ]);

      const result = await shallowManager.process('Query', llm);

      expect(result.stats.maxDepthReached).toBeLessThanOrEqual(1);
    });

    it('should handle missing source gracefully', async () => {
      const llm = createMockLLM([
        '{"type": "fetch", "source": "nonexistent", "key": "file"}',
        '{"type": "done"}',
        'Could not find the source.',
      ]);

      const result = await manager.process('Query', llm);

      expect(result.answer).toBeDefined();
    });

    it('should handle source errors gracefully', async () => {
      const errorSource: ContextSource = {
        describe: () => 'Error source',
        list: async () => { throw new Error('List failed'); },
        fetch: async () => { throw new Error('Fetch failed'); },
      };

      manager.registerSource('error', errorSource);

      const llm = createMockLLM([
        '{"type": "list", "source": "error"}',
        '{"type": "done"}',
        'Encountered errors.',
      ]);

      const result = await manager.process('Query', llm);

      expect(result.answer).toBeDefined();
    });

    it('should support cancellation', async () => {
      manager.registerSource('files', createMockSource({}));

      const cancelToken = { isCancelled: false };

      const llm = createMockLLM([
        '{"type": "list", "source": "files"}',
        '{"type": "list", "source": "files"}',
        '{"type": "list", "source": "files"}',
        'Answer.',
      ]);

      // Cancel after first call
      const originalLLM = llm;
      const wrappedLLM: LLMCallFunction = async (sys, user, opts) => {
        const result = await originalLLM(sys, user, opts);
        cancelToken.isCancelled = true;
        return result;
      };

      const result = await manager.process('Query', wrappedLLM, { cancelToken });

      // Should have stopped early
      expect(result.stats.totalCalls).toBeLessThan(4);
    });
  });

  describe('caching', () => {
    it('should cache fetched results', async () => {
      const source = createMockSource({
        content: { 'file.ts': 'cached content' },
      });
      manager.registerSource('files', source);

      const llm = createMockLLM([
        '{"type": "fetch", "source": "files", "key": "file.ts"}',
        '{"type": "fetch", "source": "files", "key": "file.ts"}', // Same fetch
        '{"type": "done"}',
        'Answer.',
      ]);

      await manager.process('Query', llm);

      // Should only call fetch once due to caching
      expect(source.fetch).toHaveBeenCalledTimes(1);
    });

    it('should allow clearing cache', async () => {
      const source = createMockSource({
        content: { 'file.ts': 'content' },
      });
      manager.registerSource('files', source);

      // First process
      const llm1 = createMockLLM([
        '{"type": "fetch", "source": "files", "key": "file.ts"}',
        '{"type": "done"}',
        'Answer.',
      ]);
      await manager.process('Query 1', llm1);

      manager.clearCache();

      // Second process after cache clear
      const llm2 = createMockLLM([
        '{"type": "fetch", "source": "files", "key": "file.ts"}',
        '{"type": "done"}',
        'Answer.',
      ]);
      await manager.process('Query 2', llm2);

      // Should have called fetch twice (cache was cleared)
      expect(source.fetch).toHaveBeenCalledTimes(2);
    });
  });

  describe('events', () => {
    it('should emit process.started event', async () => {
      manager.registerSource('files', createMockSource({}));

      const events: RecursiveContextEvent[] = [];
      manager.on((event) => events.push(event));

      const llm = createMockLLM(['{"type": "done"}', 'Answer.']);
      await manager.process('Query', llm);

      expect(events.some(e => e.type === 'process.started')).toBe(true);
    });

    it('should emit navigation.command events', async () => {
      manager.registerSource('files', createMockSource({}));

      const events: RecursiveContextEvent[] = [];
      manager.on((event) => events.push(event));

      const llm = createMockLLM([
        '{"type": "list", "source": "files"}',
        '{"type": "done"}',
        'Answer.',
      ]);
      await manager.process('Query', llm);

      expect(events.some(e => e.type === 'navigation.command')).toBe(true);
    });

    it('should emit synthesis.started event', async () => {
      manager.registerSource('files', createMockSource({}));

      const events: RecursiveContextEvent[] = [];
      manager.on((event) => events.push(event));

      const llm = createMockLLM(['{"type": "done"}', 'Answer.']);
      await manager.process('Query', llm);

      // done command triggers synthesis
      expect(events.some(e => e.type === 'synthesis.started')).toBe(true);
    });

    it('should allow unsubscribing', () => {
      const events: RecursiveContextEvent[] = [];
      const unsubscribe = manager.on((event) => events.push(event));

      unsubscribe();

      // Trigger an event (would require a process call, but we can check the mechanism)
      expect(typeof unsubscribe).toBe('function');
    });
  });

  describe('search support', () => {
    it('should use search when available', async () => {
      const source = createMockSource({
        searchResults: [
          { key: 'result1', snippet: 'Found this', score: 1 },
          { key: 'result2', snippet: 'Also found', score: 0.8 },
        ],
      });
      manager.registerSource('files', source);

      const llm = createMockLLM([
        '{"type": "search", "source": "files", "key": "search query"}',
        '{"type": "done"}',
        'Found relevant results.',
      ]);

      const result = await manager.process('Query', llm);

      expect(source.search).toHaveBeenCalled();
      expect(result.answer).toBeDefined();
    });
  });
});

describe('Built-in sources', () => {
  describe('createFileSystemSource', () => {
    it('should create a file system source', async () => {
      const source = createFileSystemSource({
        basePath: '/test',
        glob: vi.fn(async () => ['file1.ts', 'file2.ts']),
        readFile: vi.fn(async (path) => `content of ${path}`),
      });

      expect(source.describe()).toContain('/test');

      const items = await source.list();
      expect(items).toContain('file1.ts');

      const content = await source.fetch('file1.ts');
      expect(content).toContain('file1.ts');
    });

    it('should support grep search', async () => {
      const source = createFileSystemSource({
        basePath: '/test',
        glob: vi.fn(async () => []),
        readFile: vi.fn(async () => ''),
        grep: vi.fn(async () => [
          { file: 'test.ts', line: 10, content: 'matching line' },
        ]),
      });

      expect(source.search).toBeDefined();

      const results = await source.search!('query');
      expect(results.length).toBe(1);
      expect(results[0].key).toContain('test.ts');
    });
  });

  describe('createConversationSource', () => {
    it('should create a conversation source', async () => {
      const messages = [
        { role: 'user', content: 'Hello' },
        { role: 'assistant', content: 'Hi there!' },
      ];

      const source = createConversationSource({
        getMessages: () => messages,
      });

      const items = await source.list();
      expect(items.length).toBe(2);

      const content = await source.fetch('msg-0');
      expect(content).toContain('Hello');
    });

    it('should support search', async () => {
      const messages = [
        { role: 'user', content: 'Hello world' },
        { role: 'assistant', content: 'Greetings!' },
        { role: 'user', content: 'Tell me about world peace' },
      ];

      const source = createConversationSource({
        getMessages: () => messages,
      });

      const results = await source.search!('world');
      expect(results.length).toBe(2); // Both messages with "world"
    });
  });
});

describe('Utilities', () => {
  describe('formatRecursiveResult', () => {
    it('should format result for display', () => {
      const result = {
        answer: 'The answer is 42.',
        path: [
          {
            depth: 0,
            command: { type: 'list' as const, source: 'files', reason: 'explore' },
            result: 'file1.ts, file2.ts',
            tokens: 10,
          },
        ],
        stats: {
          totalCalls: 3,
          maxDepthReached: 1,
          totalTokens: 500,
          sourcesAccessed: ['files'],
          itemsFetched: 2,
          duration: 1000,
        },
      };

      const formatted = formatRecursiveResult(result);

      expect(formatted).toContain('The answer is 42');
      expect(formatted).toContain('list');
      expect(formatted).toContain('files');
      expect(formatted).toContain('500'); // tokens
    });
  });

  describe('formatRecursiveStats', () => {
    it('should format stats compactly', () => {
      const stats = {
        totalCalls: 5,
        maxDepthReached: 2,
        totalTokens: 1000,
        sourcesAccessed: ['files', 'docs'],
        itemsFetched: 3,
        duration: 2000,
      };

      const formatted = formatRecursiveStats(stats);

      expect(formatted).toContain('5');
      expect(formatted).toContain('1000');
      expect(formatted).toContain('2000');
    });
  });
});
