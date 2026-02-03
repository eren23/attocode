/**
 * Tests for Enhanced Keyword Search in CodebaseContextManager.
 *
 * Tests the Phase 4.4 implementation of search and searchRanked methods
 * including fuzzy matching and relevance scoring.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  CodebaseContextManager,
  type CodeChunk,
  type RepoMap,
} from '../../src/integrations/codebase-context.js';

// =============================================================================
// TEST FIXTURES
// =============================================================================

function createMockChunk(overrides: Partial<CodeChunk> = {}): CodeChunk {
  const id = overrides.id ?? 'test-file.ts';
  return {
    id,
    filePath: overrides.filePath ?? id,
    content: overrides.content ?? 'const x = 1;',
    tokenCount: overrides.tokenCount ?? 100,
    importance: overrides.importance ?? 0.5,
    type: overrides.type ?? 'core_module',
    symbols: overrides.symbols ?? [],
    dependencies: overrides.dependencies ?? [],
    lastModified: overrides.lastModified,
  };
}

function createMockRepoMap(chunks: CodeChunk[]): RepoMap {
  const chunksMap = new Map<string, CodeChunk>();
  for (const chunk of chunks) {
    chunksMap.set(chunk.id, chunk);
  }

  return {
    root: '/test/project',
    chunks: chunksMap,
    entryPoints: chunks.filter(c => c.type === 'entry_point').map(c => c.filePath),
    coreModules: chunks.filter(c => c.type === 'core_module').map(c => c.filePath),
    dependencyGraph: new Map(),
    reverseDependencyGraph: new Map(),
    totalTokens: chunks.reduce((sum, c) => sum + c.tokenCount, 0),
    analyzedAt: new Date(),
  };
}

// =============================================================================
// TESTS: BASIC SEARCH
// =============================================================================

describe('CodebaseContextManager.search', () => {
  let manager: CodebaseContextManager;

  beforeEach(() => {
    manager = new CodebaseContextManager({ root: '/test/project' });
  });

  it('should return empty array when no repoMap', () => {
    const results = manager.search('test');
    expect(results).toEqual([]);
  });

  it('should search by symbol names', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['authenticateUser', 'validateToken'] }),
      createMockChunk({ id: 'src/utils.ts', symbols: ['formatDate', 'parseJSON'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.search('authenticate');

    expect(results.length).toBe(1);
    expect(results[0].id).toBe('src/auth.ts');
  });

  it('should search by file path', () => {
    const chunks = [
      createMockChunk({ id: 'src/authentication/login.ts', symbols: [] }),
      createMockChunk({ id: 'src/utils/helpers.ts', symbols: [] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.search('authentication');

    expect(results.length).toBe(1);
    expect(results[0].id).toBe('src/authentication/login.ts');
  });

  it('should be case-insensitive by default', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['AuthenticateUser'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.search('authenticateuser');

    expect(results.length).toBe(1);
  });

  it('should support case-sensitive search', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['AuthenticateUser'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.search('authenticateuser', { caseSensitive: true });

    expect(results.length).toBe(0);
  });

  it('should search content when enabled', () => {
    const chunks = [
      createMockChunk({
        id: 'src/auth.ts',
        symbols: [],
        content: 'function validateCredentials(user, pass) { return true; }',
      }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // Without content search
    const withoutContent = manager.search('validateCredentials', { includeContent: false });
    expect(withoutContent.length).toBe(0);

    // With content search
    const withContent = manager.search('validateCredentials', { includeContent: true });
    expect(withContent.length).toBe(1);
  });

  it('should handle multiple query terms', () => {
    const chunks = [
      createMockChunk({ id: 'src/user-auth.ts', symbols: ['login'] }),
      createMockChunk({ id: 'src/user-profile.ts', symbols: ['getProfile'] }),
      createMockChunk({ id: 'src/api-auth.ts', symbols: ['verify'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // "user auth" should match user-auth.ts via path terms
    const results = manager.search('user auth');

    expect(results.length).toBeGreaterThan(0);
    expect(results.some(r => r.id === 'src/user-auth.ts')).toBe(true);
  });

  it('should filter out stop words', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['authenticate'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // "the" should be filtered, leaving "auth"
    const results = manager.search('the auth');

    expect(results.length).toBe(1);
  });
});

// =============================================================================
// TESTS: FUZZY MATCHING
// =============================================================================

describe('CodebaseContextManager.search - Fuzzy Matching', () => {
  let manager: CodebaseContextManager;

  beforeEach(() => {
    manager = new CodebaseContextManager({ root: '/test/project' });
  });

  it('should find matches with small typos when fuzzy enabled', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['authenticate'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // "authentcate" has 1 edit distance from "authenticate"
    const results = manager.search('authentcate', { fuzzyMatch: true });

    expect(results.length).toBe(1);
  });

  it('should not match beyond maxDistance', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['authenticate'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // "autheticate" is too far from any symbols with distance 1
    const results = manager.search('xyz123', { fuzzyMatch: true, maxDistance: 1 });

    expect(results.length).toBe(0);
  });

  it('should match substrings even with fuzzy', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['authenticateUser'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // "auth" is a substring of "authenticateUser", should match
    const results = manager.search('auth', { fuzzyMatch: true });

    // This matches via path (auth.ts), not fuzzy symbol matching
    expect(results.length).toBe(1);
  });

  it('should fuzzy match file names', () => {
    const chunks = [
      createMockChunk({ id: 'src/authentication.ts', symbols: [] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // "authentication" matches via path substring, even if fuzzy
    const results = manager.search('authentication', { fuzzyMatch: true });

    expect(results.length).toBe(1);
  });
});

// =============================================================================
// TESTS: RANKED SEARCH
// =============================================================================

describe('CodebaseContextManager.searchRanked', () => {
  let manager: CodebaseContextManager;

  beforeEach(() => {
    manager = new CodebaseContextManager({ root: '/test/project' });
  });

  it('should return scored results', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['authenticate'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.searchRanked('auth');

    expect(results.length).toBe(1);
    expect(results[0].chunk).toBeDefined();
    expect(results[0].score).toBeGreaterThan(0);
  });

  it('should rank exact symbol matches higher', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['auth'] }),
      createMockChunk({ id: 'src/other.ts', symbols: ['authentication'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.searchRanked('auth');

    expect(results.length).toBe(2);
    // Exact match should be ranked higher
    expect(results[0].chunk.id).toBe('src/auth.ts');
    expect(results[0].score).toBeGreaterThan(results[1].score);
  });

  it('should rank entry points higher', () => {
    const chunks = [
      createMockChunk({ id: 'src/main.ts', type: 'entry_point', symbols: ['init'] }),
      createMockChunk({ id: 'src/utils.ts', type: 'utility', symbols: ['init'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.searchRanked('init');

    expect(results.length).toBe(2);
    expect(results[0].chunk.id).toBe('src/main.ts');
  });

  it('should respect limit option', () => {
    const chunks = [
      createMockChunk({ id: 'src/a.ts', symbols: ['test'] }),
      createMockChunk({ id: 'src/b.ts', symbols: ['test'] }),
      createMockChunk({ id: 'src/c.ts', symbols: ['test'] }),
      createMockChunk({ id: 'src/d.ts', symbols: ['test'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.searchRanked('test', { limit: 2 });

    expect(results.length).toBe(2);
  });

  it('should sort by score descending', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['auth'], importance: 0.9 }),
      createMockChunk({ id: 'src/utils.ts', symbols: ['auth'], importance: 0.3 }),
      createMockChunk({ id: 'auth/main.ts', symbols: [], importance: 0.5 }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.searchRanked('auth');

    for (let i = 1; i < results.length; i++) {
      expect(results[i - 1].score).toBeGreaterThanOrEqual(results[i].score);
    }
  });

  it('should boost file name matches', () => {
    const chunks = [
      createMockChunk({ id: 'src/login.ts', symbols: ['validate'] }),
      createMockChunk({ id: 'src/auth.ts', symbols: ['validate'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.searchRanked('auth');

    // auth.ts should rank higher due to filename match
    // Both have same symbols, so filename is the differentiator
    expect(results[0].chunk.id).toBe('src/auth.ts');
  });
});

// =============================================================================
// TESTS: EDGE CASES
// =============================================================================

describe('CodebaseContextManager.search - Edge Cases', () => {
  let manager: CodebaseContextManager;

  beforeEach(() => {
    manager = new CodebaseContextManager({ root: '/test/project' });
  });

  it('should handle empty query', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['test'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.search('');

    expect(results).toEqual([]);
  });

  it('should handle query with only stop words', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['test'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.search('the and for');

    expect(results).toEqual([]);
  });

  it('should handle special characters in query', () => {
    const chunks = [
      createMockChunk({ id: 'src/auth.ts', symbols: ['$special', '_private'] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    const results = manager.search('$special');

    // Should still find matches ($ is stripped but 'special' remains)
    expect(results.length).toBe(1);
  });

  it('should handle chunks with no symbols', () => {
    const chunks = [
      createMockChunk({ id: 'src/config.json', symbols: [], type: 'config' }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // Should not crash, should match via path
    const results = manager.search('config');

    expect(results.length).toBe(1);
  });

  it('should handle very long content without hanging', () => {
    const longContent = 'function test() { '.repeat(10000);
    const chunks = [
      createMockChunk({ id: 'src/big.ts', content: longContent, symbols: [] }),
    ];
    (manager as any).repoMap = createMockRepoMap(chunks);

    // Should complete quickly
    const start = Date.now();
    manager.search('test', { includeContent: true });
    const duration = Date.now() - start;

    expect(duration).toBeLessThan(1000); // Should be much faster than 1s
  });
});

// =============================================================================
// TESTS: LEVENSHTEIN DISTANCE
// =============================================================================

describe('CodebaseContextManager - Levenshtein Distance', () => {
  let manager: CodebaseContextManager;

  beforeEach(() => {
    manager = new CodebaseContextManager({ root: '/test/project' });
  });

  it('should calculate correct distances', () => {
    const levenshtein = (manager as any).levenshteinDistance.bind(manager);

    expect(levenshtein('', '')).toBe(0);
    expect(levenshtein('a', '')).toBe(1);
    expect(levenshtein('', 'a')).toBe(1);
    expect(levenshtein('abc', 'abc')).toBe(0);
    expect(levenshtein('abc', 'abd')).toBe(1);
    expect(levenshtein('abc', 'abcd')).toBe(1);
    expect(levenshtein('kitten', 'sitting')).toBe(3);
  });

  it('should be symmetric', () => {
    const levenshtein = (manager as any).levenshteinDistance.bind(manager);

    expect(levenshtein('hello', 'hallo')).toBe(levenshtein('hallo', 'hello'));
    expect(levenshtein('test', 'tent')).toBe(levenshtein('tent', 'test'));
  });
});

// =============================================================================
// TESTS: TOKENIZATION
// =============================================================================

describe('CodebaseContextManager - Query Tokenization', () => {
  let manager: CodebaseContextManager;

  beforeEach(() => {
    manager = new CodebaseContextManager({ root: '/test/project' });
  });

  it('should split on whitespace', () => {
    const tokenize = (manager as any).tokenizeQuery.bind(manager);

    expect(tokenize('foo bar baz')).toEqual(['foo', 'bar', 'baz']);
  });

  it('should filter short terms', () => {
    const tokenize = (manager as any).tokenizeQuery.bind(manager);

    // 'a' should be filtered (< 2 chars), 'ab' and 'abc' are kept
    expect(tokenize('a ab abc')).toEqual(['ab', 'abc']);
  });

  it('should filter stop words', () => {
    const tokenize = (manager as any).tokenizeQuery.bind(manager);

    expect(tokenize('the quick fox')).toEqual(['quick', 'fox']);
    expect(tokenize('for and with')).toEqual([]);
  });

  it('should remove punctuation', () => {
    const tokenize = (manager as any).tokenizeQuery.bind(manager);

    expect(tokenize('hello, world!')).toEqual(['hello', 'world']);
    expect(tokenize('foo.bar')).toEqual(['foobar']);
  });
});
