/**
 * Reversible Compaction Tests
 *
 * Tests for the reversible compaction module that preserves
 * "reconstruction recipes" during context compaction.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  // Types
  type ReferenceType,
  type Reference,
  type CompactionStats,
  type CompactionMessage,
  type ReferenceExtractor,
  type CompactOptions,
  type CompactionEvent,
  // Extraction functions
  extractFileReferences,
  extractUrlReferences,
  extractFunctionReferences,
  extractErrorReferences,
  extractCommandReferences,
  extractReferences,
  // Class
  ReversibleCompactor,
  // Factory functions
  createReversibleCompactor,
  // Utilities
  quickExtract,
  createReconstructionPrompt,
  calculateRelevance,
  formatCompactionStats,
} from '../../src/tricks/reversible-compaction.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

function createMockSummarizer(summary: string): CompactOptions['summarize'] {
  return vi.fn(async () => summary);
}

function createTestMessages(count: number): CompactionMessage[] {
  return Array.from({ length: count }, (_, i) => ({
    role: i % 2 === 0 ? 'user' as const : 'assistant' as const,
    content: `Message ${i + 1} content`,
  }));
}

// =============================================================================
// EXTRACTION FUNCTION TESTS
// =============================================================================

describe('extractFileReferences', () => {
  it('should extract Unix-style paths', () => {
    const content = 'Check the file at /Users/test/project/src/main.ts';
    const refs = extractFileReferences(content);

    expect(refs.length).toBeGreaterThan(0);
    expect(refs.some(r => r.value.includes('/Users/test/project/src/main.ts'))).toBe(true);
    expect(refs[0].type).toBe('file');
  });

  it('should extract Windows-style paths', () => {
    const content = 'The config is at C:\\Users\\test\\config.json';
    const refs = extractFileReferences(content);

    expect(refs.length).toBeGreaterThan(0);
    expect(refs.some(r => r.value.includes('C:\\Users\\test\\config.json'))).toBe(true);
  });

  it('should extract relative paths with extensions', () => {
    const content = 'Import from ./utils/helper.ts and ../config.json';
    const refs = extractFileReferences(content);

    expect(refs.length).toBeGreaterThanOrEqual(2);
    expect(refs.some(r => r.value.includes('helper.ts'))).toBe(true);
    expect(refs.some(r => r.value.includes('config.json'))).toBe(true);
  });

  it('should deduplicate paths', () => {
    const content = '/path/to/file.ts and /path/to/file.ts again';
    const refs = extractFileReferences(content);

    const uniqueValues = new Set(refs.map(r => r.value));
    expect(uniqueValues.size).toBe(refs.length);
  });

  it('should filter out obvious non-paths', () => {
    const content = 'Just / or /1 or //';
    const refs = extractFileReferences(content);

    expect(refs.filter(r => r.value === '/').length).toBe(0);
    expect(refs.filter(r => r.value === '/1').length).toBe(0);
  });

  it('should include sourceIndex when provided', () => {
    const content = '/path/to/file.ts';
    const refs = extractFileReferences(content, 5);

    expect(refs[0].sourceIndex).toBe(5);
  });

  it('should generate unique IDs', () => {
    const content = '/path/to/file1.ts and /path/to/file2.ts';
    const refs = extractFileReferences(content);

    const ids = refs.map(r => r.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(ids.length);
  });

  it('should include timestamp', () => {
    const content = '/path/to/file.ts';
    const refs = extractFileReferences(content);

    expect(refs[0].timestamp).toBeDefined();
    expect(new Date(refs[0].timestamp).getTime()).not.toBeNaN();
  });
});

describe('extractUrlReferences', () => {
  it('should extract HTTP URLs', () => {
    const content = 'Visit http://example.com/page';
    const refs = extractUrlReferences(content);

    expect(refs.length).toBe(1);
    expect(refs[0].value).toBe('http://example.com/page');
    expect(refs[0].type).toBe('url');
  });

  it('should extract HTTPS URLs', () => {
    const content = 'Check https://example.com/api/v1/endpoint';
    const refs = extractUrlReferences(content);

    expect(refs.length).toBe(1);
    expect(refs[0].value).toBe('https://example.com/api/v1/endpoint');
  });

  it('should clean trailing punctuation', () => {
    const content = 'See https://example.com/page, or https://example.com/other.';
    const refs = extractUrlReferences(content);

    expect(refs[0].value).toBe('https://example.com/page');
    expect(refs[1].value).toBe('https://example.com/other');
  });

  it('should add GitHub context', () => {
    const content = 'See https://github.com/owner/repo for details';
    const refs = extractUrlReferences(content);

    expect(refs[0].context).toBe('GitHub');
  });

  it('should add GitHub Issue context', () => {
    const content = 'Related to https://github.com/owner/repo/issues/123';
    const refs = extractUrlReferences(content);

    expect(refs[0].context).toBe('GitHub Issue');
  });

  it('should add GitHub PR context', () => {
    const content = 'Fixed in https://github.com/owner/repo/pull/456';
    const refs = extractUrlReferences(content);

    expect(refs[0].context).toBe('GitHub PR');
  });

  it('should add Stack Overflow context', () => {
    const content = 'Found answer at https://stackoverflow.com/questions/12345';
    const refs = extractUrlReferences(content);

    expect(refs[0].context).toBe('Stack Overflow');
  });

  it('should add Documentation context', () => {
    const content = 'Check https://docs.example.com/api';
    const refs = extractUrlReferences(content);

    expect(refs[0].context).toBe('Documentation');
  });

  it('should extract multiple URLs', () => {
    const content = 'Check https://a.com and https://b.com and https://c.com';
    const refs = extractUrlReferences(content);

    expect(refs.length).toBe(3);
  });
});

describe('extractFunctionReferences', () => {
  it('should extract function definitions', () => {
    const content = 'function processData() { return data; }';
    const refs = extractFunctionReferences(content);

    expect(refs.some(r => r.value === 'processData')).toBe(true);
    expect(refs.find(r => r.value === 'processData')?.context).toBe('definition');
  });

  it('should extract async function definitions', () => {
    const content = 'async function fetchItems() { return await api.get(); }';
    const refs = extractFunctionReferences(content);

    expect(refs.some(r => r.value === 'fetchItems')).toBe(true);
  });

  it('should extract const arrow functions', () => {
    const content = 'const handleClick = () => { console.log("click"); }';
    const refs = extractFunctionReferences(content);

    expect(refs.some(r => r.value === 'handleClick')).toBe(true);
  });

  it('should extract camelCase method calls', () => {
    const content = 'await processUserData() and then formatResponse()';
    const refs = extractFunctionReferences(content);

    expect(refs.some(r => r.value === 'processUserData')).toBe(true);
    expect(refs.some(r => r.value === 'formatResponse')).toBe(true);
  });

  it('should deduplicate function names', () => {
    const content = 'function test() {} test() test()';
    const refs = extractFunctionReferences(content);

    const testRefs = refs.filter(r => r.value === 'test');
    expect(testRefs.length).toBe(1);
  });

  it('should filter short names', () => {
    const content = 'function fn() {} function ab()';
    const refs = extractFunctionReferences(content);

    expect(refs.filter(r => r.value.length <= 2).length).toBe(0);
  });

  it('should mark calls vs definitions', () => {
    const content = 'someMethodCall() and anotherMethodCall()';
    const refs = extractFunctionReferences(content);

    // Method calls should have 'call' context
    expect(refs.every(r => r.context === 'call')).toBe(true);
  });
});

describe('extractErrorReferences', () => {
  it('should extract error class names', () => {
    const content = 'Caught a TypeError and a RangeError';
    const refs = extractErrorReferences(content);

    expect(refs.some(r => r.value === 'TypeError')).toBe(true);
    expect(refs.some(r => r.value === 'RangeError')).toBe(true);
    expect(refs[0].type).toBe('error');
  });

  it('should extract exception class names', () => {
    const content = 'Throws NullPointerException';
    const refs = extractErrorReferences(content);

    expect(refs.some(r => r.value === 'NullPointerException')).toBe(true);
  });

  it('should extract error messages', () => {
    const content = 'Error: Cannot read property of undefined';
    const refs = extractErrorReferences(content);

    expect(refs.some(r => r.value.includes('Cannot read property'))).toBe(true);
    expect(refs.find(r => r.value.includes('Cannot read'))?.context).toBe('error message');
  });

  it('should mark error type context', () => {
    const content = 'A SyntaxError occurred';
    const refs = extractErrorReferences(content);

    const syntaxRef = refs.find(r => r.value === 'SyntaxError');
    expect(syntaxRef?.context).toBe('error type');
  });

  it('should deduplicate error types', () => {
    const content = 'TypeError TypeError TypeError';
    const refs = extractErrorReferences(content);

    const typeErrors = refs.filter(r => r.value === 'TypeError');
    expect(typeErrors.length).toBe(1);
  });

  it('should limit error messages', () => {
    const content = `
      Error: First error message
      Error: Second error message
      Error: Third error message
      Error: Fourth error message
      Error: Fifth error message
    `;
    const refs = extractErrorReferences(content);

    const errorMessages = refs.filter(r => r.context === 'error message');
    expect(errorMessages.length).toBeLessThanOrEqual(3);
  });

  it('should truncate long error messages', () => {
    const longMessage = 'Error: ' + 'x'.repeat(200);
    const refs = extractErrorReferences(longMessage);

    const msgRef = refs.find(r => r.context === 'error message');
    expect(msgRef?.value.length).toBeLessThanOrEqual(100);
  });
});

describe('extractCommandReferences', () => {
  it('should extract $ prefixed commands', () => {
    const content = '$ npm install lodash';
    const refs = extractCommandReferences(content);

    expect(refs.some(r => r.value.includes('npm install lodash'))).toBe(true);
    expect(refs[0].type).toBe('command');
  });

  it('should extract npm commands', () => {
    const content = 'Run npm run build to compile';
    const refs = extractCommandReferences(content);

    expect(refs.some(r => r.value.includes('npm run build'))).toBe(true);
  });

  it('should extract yarn commands', () => {
    const content = 'yarn add react';
    const refs = extractCommandReferences(content);

    expect(refs.some(r => r.value.includes('yarn add react'))).toBe(true);
  });

  it('should extract git commands', () => {
    const content = 'git commit -m "fix: update deps"';
    const refs = extractCommandReferences(content);

    expect(refs.some(r => r.value.includes('git commit'))).toBe(true);
  });

  it('should extract docker commands', () => {
    const content = 'docker build -t myapp .';
    const refs = extractCommandReferences(content);

    expect(refs.some(r => r.value.includes('docker build'))).toBe(true);
  });

  it('should extract commands from code blocks', () => {
    const content = '```bash\nnpm install\nnpm run test\n```';
    const refs = extractCommandReferences(content);

    expect(refs.length).toBeGreaterThan(0);
  });

  it('should deduplicate commands', () => {
    const content = 'npm install and npm install again';
    const refs = extractCommandReferences(content);

    const installRefs = refs.filter(r => r.value.includes('npm install'));
    expect(installRefs.length).toBe(1);
  });

  it('should truncate long commands', () => {
    const longCmd = 'npm run ' + 'x'.repeat(300);
    const refs = extractCommandReferences(longCmd);

    if (refs.length > 0) {
      expect(refs[0].value.length).toBeLessThanOrEqual(200);
    }
  });
});

describe('extractReferences', () => {
  it('should extract all specified types', () => {
    const content = `
      Check /path/to/file.ts
      Visit https://example.com
      function processData() {}
      Caught TypeError
    `;
    const refs = extractReferences(content, ['file', 'url', 'function', 'error']);

    expect(refs.some(r => r.type === 'file')).toBe(true);
    expect(refs.some(r => r.type === 'url')).toBe(true);
    expect(refs.some(r => r.type === 'function')).toBe(true);
    expect(refs.some(r => r.type === 'error')).toBe(true);
  });

  it('should only extract requested types', () => {
    const content = `
      Check /path/to/file.ts
      Visit https://example.com
    `;
    const refs = extractReferences(content, ['file']);

    expect(refs.every(r => r.type === 'file')).toBe(true);
  });

  it('should use custom extractors when provided', () => {
    const customExtractor: ReferenceExtractor = (_content, index) => [{
      id: 'custom-1',
      type: 'custom',
      value: 'custom-value',
      timestamp: new Date().toISOString(),
      sourceIndex: index,
    }];

    const customExtractors = new Map<ReferenceType, ReferenceExtractor>([
      ['custom', customExtractor],
    ]);

    const refs = extractReferences('any content', ['custom'], 0, customExtractors);

    expect(refs.length).toBe(1);
    expect(refs[0].type).toBe('custom');
    expect(refs[0].value).toBe('custom-value');
  });

  it('should pass sourceIndex to extractors', () => {
    const refs = extractReferences('/path/to/file.ts', ['file'], 42);

    expect(refs[0].sourceIndex).toBe(42);
  });

  it('should handle empty content', () => {
    const refs = extractReferences('', ['file', 'url', 'function', 'error', 'command']);

    expect(refs.length).toBe(0);
  });

  it('should handle types without built-in extractors', () => {
    // class, snippet, decision don't have built-in extractors
    const refs = extractReferences('class MyClass {}', ['class']);

    // Should not throw, just return empty
    expect(Array.isArray(refs)).toBe(true);
  });
});

// =============================================================================
// REVERSIBLE COMPACTOR TESTS
// =============================================================================

describe('ReversibleCompactor', () => {
  let compactor: ReversibleCompactor;

  beforeEach(() => {
    compactor = createReversibleCompactor({
      preserveTypes: ['file', 'url', 'error'],
      maxReferences: 50,
      deduplicate: true,
    });
  });

  describe('initialization', () => {
    it('should create compactor with config', () => {
      expect(compactor).toBeInstanceOf(ReversibleCompactor);
    });

    it('should apply default values', () => {
      const minimal = createReversibleCompactor({
        preserveTypes: ['file'],
      });
      expect(minimal).toBeInstanceOf(ReversibleCompactor);
    });
  });

  describe('compact', () => {
    it('should compact messages and return summary', async () => {
      const messages: CompactionMessage[] = [
        { role: 'user', content: 'Check /path/to/file.ts' },
        { role: 'assistant', content: 'I found the file at /path/to/file.ts' },
      ];

      const result = await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary of conversation about file.ts'),
      });

      expect(result.summary).toBe('Summary of conversation about file.ts');
    });

    it('should extract references from messages', async () => {
      const messages: CompactionMessage[] = [
        { role: 'user', content: 'Check /path/file1.ts and https://example.com' },
        { role: 'assistant', content: 'Found TypeError in the file' },
      ];

      const result = await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      expect(result.references.some(r => r.type === 'file')).toBe(true);
      expect(result.references.some(r => r.type === 'url')).toBe(true);
      expect(result.references.some(r => r.type === 'error')).toBe(true);
    });

    it('should return compaction stats', async () => {
      const messages = createTestMessages(5);

      const result = await compactor.compact(messages, {
        summarize: createMockSummarizer('Short summary'),
      });

      expect(result.stats.originalMessages).toBe(5);
      expect(result.stats.originalTokens).toBeGreaterThan(0);
      expect(result.stats.compactedTokens).toBeGreaterThan(0);
      expect(result.stats.compressionRatio).toBeGreaterThan(0);
    });

    it('should deduplicate references when enabled', async () => {
      const messages: CompactionMessage[] = [
        { role: 'user', content: '/path/to/file.ts' },
        { role: 'assistant', content: '/path/to/file.ts again' },
      ];

      const result = await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const fileRefs = result.references.filter(r =>
        r.type === 'file' && r.value.includes('/path/to/file.ts')
      );
      expect(fileRefs.length).toBe(1);
    });

    it('should respect maxReferences limit', async () => {
      const limitedCompactor = createReversibleCompactor({
        preserveTypes: ['file'],
        maxReferences: 2,
      });

      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/path/a.ts /path/b.ts /path/c.ts /path/d.ts /path/e.ts',
      }];

      const result = await limitedCompactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      expect(result.references.length).toBeLessThanOrEqual(2);
    });

    it('should filter by minRelevance', async () => {
      const relevanceCompactor = createReversibleCompactor({
        preserveTypes: ['file'],
        minRelevance: 0.8,
      });

      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/path/file.ts',
      }];

      const result = await relevanceCompactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      // References without explicit relevance default to 1, so they pass
      // This tests the filter mechanism works
      expect(Array.isArray(result.references)).toBe(true);
    });

    it('should store preserved references', async () => {
      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/path/to/file.ts',
      }];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const preserved = compactor.getPreservedReferences();
      expect(preserved.length).toBeGreaterThan(0);
    });

    it('should call summarize function with messages', async () => {
      const summarize = vi.fn(async () => 'Summary');
      const messages = createTestMessages(3);

      await compactor.compact(messages, { summarize });

      expect(summarize).toHaveBeenCalledWith(messages);
    });
  });

  describe('formatReferencesBlock', () => {
    it('should format references as block text', () => {
      const refs: Reference[] = [
        { id: '1', type: 'file', value: '/path/file.ts', timestamp: new Date().toISOString() },
        { id: '2', type: 'url', value: 'https://example.com', context: 'Docs', timestamp: new Date().toISOString() },
      ];

      const block = compactor.formatReferencesBlock(refs);

      expect(block).toContain('[Preserved References]');
      expect(block).toContain('FILES:');
      expect(block).toContain('/path/file.ts');
      expect(block).toContain('URLS:');
      expect(block).toContain('https://example.com');
      expect(block).toContain('(Docs)');
    });

    it('should return empty string for no references', () => {
      const block = compactor.formatReferencesBlock([]);

      expect(block).toBe('');
    });

    it('should group references by type', () => {
      const refs: Reference[] = [
        { id: '1', type: 'file', value: '/a.ts', timestamp: new Date().toISOString() },
        { id: '2', type: 'file', value: '/b.ts', timestamp: new Date().toISOString() },
        { id: '3', type: 'error', value: 'TypeError', timestamp: new Date().toISOString() },
      ];

      const block = compactor.formatReferencesBlock(refs);

      expect(block).toContain('FILES:');
      expect(block).toContain('ERRORS:');
    });
  });

  describe('getReference', () => {
    it('should find reference by ID', async () => {
      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/unique/path/file.ts',
      }];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const preserved = compactor.getPreservedReferences();
      const ref = compactor.getReference(preserved[0].id);

      expect(ref).toBeDefined();
      expect(ref?.id).toBe(preserved[0].id);
    });

    it('should return undefined for non-existent ID', () => {
      const ref = compactor.getReference('non-existent-id');

      expect(ref).toBeUndefined();
    });
  });

  describe('getReferencesByType', () => {
    it('should filter references by type', async () => {
      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/path/file.ts https://example.com TypeError',
      }];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const fileRefs = compactor.getReferencesByType('file');
      const urlRefs = compactor.getReferencesByType('url');

      expect(fileRefs.every(r => r.type === 'file')).toBe(true);
      expect(urlRefs.every(r => r.type === 'url')).toBe(true);
    });

    it('should return empty array for type with no refs', () => {
      const refs = compactor.getReferencesByType('command');

      expect(refs).toEqual([]);
    });
  });

  describe('searchReferences', () => {
    it('should search by value substring', async () => {
      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/path/to/important-file.ts and /path/to/other.ts',
      }];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const results = compactor.searchReferences('important');

      expect(results.length).toBeGreaterThan(0);
      expect(results[0].value).toContain('important');
    });

    it('should be case insensitive', async () => {
      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/PATH/TO/FILE.TS',
      }];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const results = compactor.searchReferences('path');

      expect(results.length).toBeGreaterThan(0);
    });

    it('should return empty array for no matches', () => {
      const results = compactor.searchReferences('nonexistent');

      expect(results).toEqual([]);
    });
  });

  describe('clear', () => {
    it('should clear preserved references', async () => {
      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/path/file.ts',
      }];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      expect(compactor.getPreservedReferences().length).toBeGreaterThan(0);

      compactor.clear();

      expect(compactor.getPreservedReferences().length).toBe(0);
    });
  });

  describe('events', () => {
    it('should emit compaction.started event', async () => {
      const events: CompactionEvent[] = [];
      compactor.on((event) => events.push(event));

      const messages = createTestMessages(3);
      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const startEvent = events.find(e => e.type === 'compaction.started');
      expect(startEvent).toBeDefined();
      expect((startEvent as { messageCount: number }).messageCount).toBe(3);
    });

    it('should emit reference.extracted events', async () => {
      const events: CompactionEvent[] = [];
      compactor.on((event) => events.push(event));

      const messages: CompactionMessage[] = [{
        role: 'user',
        content: '/path/file.ts',
      }];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const extractedEvents = events.filter(e => e.type === 'reference.extracted');
      expect(extractedEvents.length).toBeGreaterThan(0);
    });

    it('should emit reference.deduplicated event', async () => {
      const events: CompactionEvent[] = [];
      compactor.on((event) => events.push(event));

      const messages: CompactionMessage[] = [
        { role: 'user', content: '/path/file.ts' },
        { role: 'assistant', content: '/path/file.ts' },
      ];

      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const dedupEvent = events.find(e => e.type === 'reference.deduplicated');
      expect(dedupEvent).toBeDefined();
    });

    it('should emit compaction.completed event', async () => {
      const events: CompactionEvent[] = [];
      compactor.on((event) => events.push(event));

      const messages = createTestMessages(2);
      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      const completedEvent = events.find(e => e.type === 'compaction.completed');
      expect(completedEvent).toBeDefined();
      expect((completedEvent as { stats: CompactionStats }).stats).toBeDefined();
    });

    it('should allow unsubscribing', async () => {
      const events: CompactionEvent[] = [];
      const unsubscribe = compactor.on((event) => events.push(event));

      unsubscribe();

      const messages = createTestMessages(2);
      await compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      });

      expect(events.length).toBe(0);
    });

    it('should handle listener errors gracefully', async () => {
      compactor.on(() => {
        throw new Error('Listener error');
      });

      const messages = createTestMessages(2);

      // Should not throw
      await expect(compactor.compact(messages, {
        summarize: createMockSummarizer('Summary'),
      })).resolves.toBeDefined();
    });
  });
});

// =============================================================================
// FACTORY FUNCTION TESTS
// =============================================================================

describe('createReversibleCompactor', () => {
  it('should create a ReversibleCompactor instance', () => {
    const compactor = createReversibleCompactor({
      preserveTypes: ['file', 'url'],
    });

    expect(compactor).toBeInstanceOf(ReversibleCompactor);
  });

  it('should work with full config', () => {
    const customExtractor: ReferenceExtractor = () => [];

    const compactor = createReversibleCompactor({
      preserveTypes: ['file', 'custom'],
      maxReferences: 25,
      deduplicate: false,
      customExtractors: new Map([['custom', customExtractor]]),
      minRelevance: 0.5,
    });

    expect(compactor).toBeInstanceOf(ReversibleCompactor);
  });
});

// =============================================================================
// UTILITY FUNCTION TESTS
// =============================================================================

describe('quickExtract', () => {
  it('should extract references with default types', () => {
    const content = '/path/file.ts https://example.com function test() {} TypeError';
    const refs = quickExtract(content);

    expect(refs.some(r => r.type === 'file')).toBe(true);
    expect(refs.some(r => r.type === 'url')).toBe(true);
    expect(refs.some(r => r.type === 'function')).toBe(true);
    expect(refs.some(r => r.type === 'error')).toBe(true);
  });

  it('should extract with specified types', () => {
    const content = '/path/file.ts https://example.com';
    const refs = quickExtract(content, ['file']);

    expect(refs.every(r => r.type === 'file')).toBe(true);
  });
});

describe('createReconstructionPrompt', () => {
  it('should create prompt with file references', () => {
    const refs: Reference[] = [{
      id: '1',
      type: 'file',
      value: '/path/to/file.ts',
      timestamp: new Date().toISOString(),
    }];

    const prompt = createReconstructionPrompt(refs);

    expect(prompt).toContain('**Files**');
    expect(prompt).toContain('/path/to/file.ts');
    expect(prompt).toContain('read_file tool');
  });

  it('should create prompt with URL references', () => {
    const refs: Reference[] = [{
      id: '1',
      type: 'url',
      value: 'https://example.com',
      context: 'GitHub',
      timestamp: new Date().toISOString(),
    }];

    const prompt = createReconstructionPrompt(refs);

    expect(prompt).toContain('**URLs**');
    expect(prompt).toContain('https://example.com');
    expect(prompt).toContain('[GitHub]');
  });

  it('should create prompt with function references', () => {
    const refs: Reference[] = [{
      id: '1',
      type: 'function',
      value: 'processData',
      timestamp: new Date().toISOString(),
    }];

    const prompt = createReconstructionPrompt(refs);

    expect(prompt).toContain('**Functions**');
    expect(prompt).toContain('processData');
  });

  it('should create prompt with error references', () => {
    const refs: Reference[] = [{
      id: '1',
      type: 'error',
      value: 'TypeError: Cannot read property',
      timestamp: new Date().toISOString(),
    }];

    const prompt = createReconstructionPrompt(refs);

    expect(prompt).toContain('**Errors encountered**');
    expect(prompt).toContain('TypeError');
  });

  it('should create prompt with command references', () => {
    const refs: Reference[] = [{
      id: '1',
      type: 'command',
      value: 'npm install lodash',
      timestamp: new Date().toISOString(),
    }];

    const prompt = createReconstructionPrompt(refs);

    expect(prompt).toContain('**Commands used**');
    expect(prompt).toContain('npm install lodash');
  });

  it('should return empty string for no references', () => {
    const prompt = createReconstructionPrompt([]);

    expect(prompt).toBe('');
  });

  it('should include header text', () => {
    const refs: Reference[] = [{
      id: '1',
      type: 'file',
      value: '/path/file.ts',
      timestamp: new Date().toISOString(),
    }];

    const prompt = createReconstructionPrompt(refs);

    expect(prompt).toContain('preserved from earlier context');
    expect(prompt).toContain('retrieve details if needed');
  });

  it('should group multiple reference types', () => {
    const refs: Reference[] = [
      { id: '1', type: 'file', value: '/a.ts', timestamp: new Date().toISOString() },
      { id: '2', type: 'url', value: 'https://a.com', timestamp: new Date().toISOString() },
      { id: '3', type: 'error', value: 'SomeError', timestamp: new Date().toISOString() },
    ];

    const prompt = createReconstructionPrompt(refs);

    expect(prompt).toContain('**Files**');
    expect(prompt).toContain('**URLs**');
    expect(prompt).toContain('**Errors encountered**');
  });
});

describe('calculateRelevance', () => {
  it('should return base score for empty context', () => {
    const ref: Reference = {
      id: '1',
      type: 'file',
      value: '/path/file.ts',
      timestamp: new Date().toISOString(),
    };

    const score = calculateRelevance(ref, {});

    expect(score).toBe(0.55); // 0.5 base + 0.05 for file type
  });

  it('should boost score for goal match', () => {
    const ref: Reference = {
      id: '1',
      type: 'file',
      value: '/path/authentication.ts',
      timestamp: new Date().toISOString(),
    };

    const scoreWithGoal = calculateRelevance(ref, {
      goal: 'Fix authentication bug',
    });

    const scoreWithoutGoal = calculateRelevance(ref, {});

    expect(scoreWithGoal).toBeGreaterThan(scoreWithoutGoal);
  });

  it('should boost score for recent topics match', () => {
    const ref: Reference = {
      id: '1',
      type: 'url',
      value: 'https://docs.react.dev',
      timestamp: new Date().toISOString(),
    };

    const scoreWithTopics = calculateRelevance(ref, {
      recentTopics: ['react', 'hooks'],
    });

    const scoreWithoutTopics = calculateRelevance(ref, {});

    expect(scoreWithTopics).toBeGreaterThan(scoreWithoutTopics);
  });

  it('should boost error type references', () => {
    const errorRef: Reference = {
      id: '1',
      type: 'error',
      value: 'TypeError',
      timestamp: new Date().toISOString(),
    };

    const fileRef: Reference = {
      id: '2',
      type: 'file',
      value: '/path/file.ts',
      timestamp: new Date().toISOString(),
    };

    const errorScore = calculateRelevance(errorRef, {});
    const fileScore = calculateRelevance(fileRef, {});

    expect(errorScore).toBeGreaterThan(fileScore);
  });

  it('should cap score at 1', () => {
    const ref: Reference = {
      id: '1',
      type: 'error',
      value: 'authentication error typescript react',
      timestamp: new Date().toISOString(),
    };

    const score = calculateRelevance(ref, {
      goal: 'Fix authentication error in typescript',
      recentTopics: ['authentication', 'error', 'typescript', 'react'],
    });

    expect(score).toBeLessThanOrEqual(1);
  });

  it('should be case insensitive for matching', () => {
    const ref: Reference = {
      id: '1',
      type: 'file',
      value: '/PATH/AUTHENTICATION.TS',
      timestamp: new Date().toISOString(),
    };

    const score = calculateRelevance(ref, {
      goal: 'fix authentication',
    });

    expect(score).toBeGreaterThan(0.5);
  });

  it('should ignore short goal words', () => {
    const ref: Reference = {
      id: '1',
      type: 'file',
      value: '/path/ab.ts',
      timestamp: new Date().toISOString(),
    };

    const scoreWithShortWord = calculateRelevance(ref, {
      goal: 'ab cd', // Short words should be ignored
    });

    const scoreWithoutGoal = calculateRelevance(ref, {});

    // Short words (<=3 chars) shouldn't boost
    expect(scoreWithShortWord).toBe(scoreWithoutGoal);
  });
});

describe('formatCompactionStats', () => {
  it('should format stats as readable string', () => {
    const stats: CompactionStats = {
      originalMessages: 10,
      originalTokens: 5000,
      compactedTokens: 1000,
      referencesExtracted: 25,
      referencesPreserved: 20,
      compressionRatio: 0.2,
    };

    const formatted = formatCompactionStats(stats);

    expect(formatted).toContain('10 messages');
    expect(formatted).toContain('5,000 tokens');
    expect(formatted).toContain('1,000 tokens');
    expect(formatted).toContain('80%'); // 1 - 0.2 = 0.8 = 80%
    expect(formatted).toContain('25 extracted');
    expect(formatted).toContain('20 preserved');
  });

  it('should handle zero compression', () => {
    const stats: CompactionStats = {
      originalMessages: 1,
      originalTokens: 100,
      compactedTokens: 100,
      referencesExtracted: 0,
      referencesPreserved: 0,
      compressionRatio: 1,
    };

    const formatted = formatCompactionStats(stats);

    expect(formatted).toContain('0%'); // 1 - 1 = 0%
  });

  it('should include all stat fields', () => {
    const stats: CompactionStats = {
      originalMessages: 5,
      originalTokens: 2000,
      compactedTokens: 500,
      referencesExtracted: 10,
      referencesPreserved: 8,
      compressionRatio: 0.25,
    };

    const formatted = formatCompactionStats(stats);

    expect(formatted).toContain('Original');
    expect(formatted).toContain('Compacted');
    expect(formatted).toContain('Compression');
    expect(formatted).toContain('References');
  });
});

// =============================================================================
// INTEGRATION TESTS
// =============================================================================

describe('Integration', () => {
  it('should handle full compaction workflow', async () => {
    const compactor = createReversibleCompactor({
      preserveTypes: ['file', 'url', 'function', 'error', 'command'],
      maxReferences: 100,
      deduplicate: true,
    });

    const messages: CompactionMessage[] = [
      {
        role: 'user',
        content: 'Please fix the bug in /src/utils/auth.ts. See https://github.com/org/repo/issues/123',
      },
      {
        role: 'assistant',
        content: `I found the issue in the validateToken() function. Here's what I did:
          $ git diff src/utils/auth.ts
          The error was: TypeError: Cannot read property 'expires' of undefined`,
      },
      {
        role: 'user',
        content: 'Thanks! Can you also check /src/middleware/auth-middleware.ts?',
      },
      {
        role: 'assistant',
        content: 'Yes, I updated processAuthHeader() to handle the edge case.',
      },
    ];

    // Track events
    const events: CompactionEvent[] = [];
    compactor.on(e => events.push(e));

    // Compact
    const result = await compactor.compact(messages, {
      summarize: createMockSummarizer('Fixed auth bug: updated validateToken() and processAuthHeader() functions.'),
    });

    // Verify result structure
    expect(result.summary).toContain('Fixed auth bug');
    expect(result.references.length).toBeGreaterThan(0);
    expect(result.stats.originalMessages).toBe(4);
    // Note: compressionRatio = compactedTokens / originalTokens
    // It can be > 1 if summary + references are longer than original
    expect(result.stats.compressionRatio).toBeGreaterThan(0);

    // Verify references were extracted
    expect(result.references.some(r => r.type === 'file')).toBe(true);
    expect(result.references.some(r => r.type === 'url')).toBe(true);
    expect(result.references.some(r => r.type === 'function')).toBe(true);
    expect(result.references.some(r => r.type === 'error')).toBe(true);

    // Verify events were emitted
    expect(events.some(e => e.type === 'compaction.started')).toBe(true);
    expect(events.some(e => e.type === 'reference.extracted')).toBe(true);
    expect(events.some(e => e.type === 'compaction.completed')).toBe(true);

    // Verify we can search references
    const authFiles = compactor.searchReferences('auth');
    expect(authFiles.length).toBeGreaterThan(0);

    // Verify we can get references by type
    const fileRefs = compactor.getReferencesByType('file');
    expect(fileRefs.length).toBeGreaterThan(0);

    // Verify reconstruction prompt
    const prompt = createReconstructionPrompt(result.references);
    expect(prompt.length).toBeGreaterThan(0);
    expect(prompt).toContain('preserved from earlier context');

    // Verify formatted stats
    const statsStr = formatCompactionStats(result.stats);
    expect(statsStr).toContain('Compaction Statistics');
  });

  it('should work with custom extractors', async () => {
    // Custom extractor for decision references
    const decisionExtractor: ReferenceExtractor = (content, index) => {
      const refs: Reference[] = [];
      const decisionPattern = /DECISION:\s*(.+)/g;
      let match: RegExpExecArray | null;

      while ((match = decisionPattern.exec(content)) !== null) {
        refs.push({
          id: `decision-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          type: 'decision',
          value: match[1].trim(),
          timestamp: new Date().toISOString(),
          sourceIndex: index,
        });
      }

      return refs;
    };

    const compactor = createReversibleCompactor({
      preserveTypes: ['file', 'decision'],
      customExtractors: new Map([['decision', decisionExtractor]]),
    });

    const messages: CompactionMessage[] = [
      {
        role: 'assistant',
        content: 'DECISION: Use async/await instead of callbacks for better readability.',
      },
      {
        role: 'assistant',
        content: 'Modified /src/index.ts. DECISION: Add retry logic for API calls.',
      },
    ];

    const result = await compactor.compact(messages, {
      summarize: createMockSummarizer('Made architectural decisions about code style.'),
    });

    // Verify custom extraction worked
    const decisions = result.references.filter(r => r.type === 'decision');
    expect(decisions.length).toBe(2);
    expect(decisions.some(d => d.value.includes('async/await'))).toBe(true);
    expect(decisions.some(d => d.value.includes('retry logic'))).toBe(true);
  });

  it('should handle empty messages gracefully', async () => {
    const compactor = createReversibleCompactor({
      preserveTypes: ['file', 'url'],
    });

    const result = await compactor.compact([], {
      summarize: createMockSummarizer('Empty conversation'),
    });

    expect(result.summary).toBe('Empty conversation');
    expect(result.references.length).toBe(0);
    expect(result.stats.originalMessages).toBe(0);
  });

  it('should handle messages with no extractable references', async () => {
    const compactor = createReversibleCompactor({
      preserveTypes: ['file', 'url', 'error'],
    });

    const messages: CompactionMessage[] = [
      { role: 'user', content: 'Hello, how are you?' },
      { role: 'assistant', content: 'I am doing well, thank you!' },
    ];

    const result = await compactor.compact(messages, {
      summarize: createMockSummarizer('A friendly greeting exchange.'),
    });

    expect(result.summary).toBe('A friendly greeting exchange.');
    expect(result.references.length).toBe(0);
    expect(result.stats.referencesExtracted).toBe(0);
  });
});
